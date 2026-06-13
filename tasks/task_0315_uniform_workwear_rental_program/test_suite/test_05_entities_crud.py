"""Entity CRUD breadth: account creation defaults, retrieval, paginated listing,
not-found, the grace default, computed-field stamping, parent existence, and
reverse-reachability / filtered listings.
"""
import pytest
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    assert_account,
    NON_EXISTENT_UUID,
    TEST_USERS,
    make_account,
    make_garment_type,
    make_wearer,
    make_garment,
    make_assignment,
    create_account_payload,
    create_wearer_payload,
)

ADMIN = TEST_USERS["program_admin_headers"]
MANAGER = TEST_USERS["account_manager_headers"]


def test_create_account_returns_201_with_computed_defaults(api):
    """PRD §3.1: "A freshly opened account starts life in a `CURRENT` billing posture,
    with its `outstanding_cents` ledger at zero and its `active_wearer_count` at zero."

    Design: Corner/entities/create_account_returns_201_with_computed_defaults
    """
    res = api.create_account(
        create_account_payload(legal_name="Cornerco", service_day="MON", shortage_grace_units=3),
        ADMIN,
    )
    account = validate_success(res, 201)
    assert_account(account)
    assert account["billing_status"] == "CURRENT", (
        f"new account must start CURRENT, got {account['billing_status']}"
    )
    assert account["outstanding_cents"] == 0, (
        f"new account outstanding must be 0, got {account['outstanding_cents']}"
    )
    assert account["active_wearer_count"] == 0, (
        f"new account active_wearer_count must be 0, got {account['active_wearer_count']}"
    )


def test_get_account_returns_stored_entity(api):
    """PRD §2.4: "Every persisted resource carries a server-minted `id` formatted as a
    UUID with no type prefix ... an integer `version` that begins at its initial value on
    creation and increments by exactly one on every mutation."

    Design: Corner/entities/get_account_returns_stored_entity
    """
    created = make_account(legal_name="ReadMe Co", service_day="TUE")
    fetched = validate_success(api.get_account(created["id"], ADMIN), 200)
    assert fetched["legal_name"] == "ReadMe Co", (
        f"stored legal_name should round-trip, got {fetched['legal_name']}"
    )
    assert fetched["version"] == 1, (
        f"an unmutated account must be at version 1, got {fetched['version']}"
    )


def test_list_accounts_paginated_envelope(api):
    """PRD §2.3: "Every list response carries the pagination fields `limit`, `offset`,
    `total_count`, and `has_more` inside the `meta` object of the envelope, where
    `total_count` is the count of all matching resources before the page window is applied
    and `has_more` indicates whether further items remain beyond the current page."

    Design: Corner/entities/list_accounts_paginated_envelope
    """
    make_account(legal_name="A1")
    make_account(legal_name="A2")
    data, meta = validate_paginated(api.list_accounts(ADMIN, params={"limit": 1, "offset": 0}))
    assert meta["total_count"] >= 2, f"total_count should count all matches, got {meta['total_count']}"
    assert meta["has_more"] is True, "a 1-item window over >=2 accounts must report has_more true"


def test_get_account_not_found(api):
    """PRD §2.6: "the system validates each path identifier in left-to-right order and
    rejects the request with `ERR_RESOURCE_NOT_FOUND` the moment the first identifier in
    the path fails to resolve to an existing resource."

    Design: Corner/entities/get_account_not_found
    """
    res = api.get_account(NON_EXISTENT_UUID, ADMIN)
    validate_error(res, "ERR_RESOURCE_NOT_FOUND", expected_status=404)


def test_shortage_grace_units_default_applied(api):
    """PRD §2.8: "Each account declares `shortage_grace_units`, an integer of at least
    zero that defaults to 2 when not supplied at account creation."

    Design: Corner/entities/shortage_grace_units_default_applied
    """
    account = make_account(legal_name="DefCo", service_day="WED")  # grace omitted
    assert account["shortage_grace_units"] == 2, (
        f"omitting shortage_grace_units must default it to 2, got {account['shortage_grace_units']}"
    )


def test_garment_computed_fields_stamped_by_server(api):
    """PRD §3.3: "The first is its inventory `lifecycle_status`, one of `IN_STOCK`,
    `ASSIGNED`, `RETIRED`, or `LOST`, which begins at `IN_STOCK`. The second is its
    `wash_location`, one of `AT_PLANT`, `AT_CUSTOMER`, `IN_SOIL`, or `IN_WASH`, which
    begins at `AT_PLANT`. On provisioning, a garment's `soil_strikes` counter starts at
    zero."

    Design: Corner/entities/garment_computed_fields_ignore_client_input
    """
    acct = make_account(legal_name="CompCo")
    gt = make_garment_type()
    garment = make_garment(acct["id"], gt["id"])
    assert garment["lifecycle_status"] == "IN_STOCK", (
        f"new garment lifecycle must be IN_STOCK, got {garment['lifecycle_status']}"
    )
    assert garment["wash_location"] == "AT_PLANT", (
        f"new garment wash_location must be AT_PLANT, got {garment['wash_location']}"
    )
    assert garment["soil_strikes"] == 0, (
        f"new garment soil_strikes must be 0, got {garment['soil_strikes']}"
    )


def test_wearer_requires_existing_parent_account(api):
    """PRD §2.6: "the system validates each path identifier in left-to-right order and
    rejects the request with `ERR_RESOURCE_NOT_FOUND` the moment the first identifier in
    the path fails to resolve to an existing resource."

    Design: Corner/entities/wearer_requires_existing_parent_account
    """
    res = api.create_wearer(NON_EXISTENT_UUID, create_wearer_payload(full_name="Orphan"), MANAGER)
    validate_error(res, "ERR_RESOURCE_NOT_FOUND", expected_status=404)


def test_list_assignments_filtered_by_account(api):
    """PRD §4 (Endpoint Definitions): "GET | `/assignments` | List assignments (filter by
    garment, wearer, account, status) | ProgramAdmin, AccountManager"
    PRD §2.3: "`total_count` is the count of all matching resources before the page window
    is applied..."

    Design: Corner/entities/fk_reverse_assignments_by_account
    """
    acct = make_account(legal_name="RevCo")
    gt = make_garment_type()
    wearer = make_wearer(acct["id"])
    g = make_garment(acct["id"], gt["id"])
    make_assignment(g["id"], wearer["id"])
    data, meta = validate_paginated(api.list_assignments(ADMIN, params={"account_id": acct["id"]}))
    assert meta["total_count"] == 1, (
        f"the account should have exactly one assignment, got total_count {meta['total_count']}"
    )


def test_list_account_garments_filtered_by_lifecycle(api):
    """PRD §4 (Endpoint Definitions): "GET | `/accounts/{id}/garments` | List garments for
    an account | ProgramAdmin, AccountManager, CleanroomTech"
    PRD §3.3: "its inventory `lifecycle_status`, one of `IN_STOCK`, `ASSIGNED`, `RETIRED`,
    or `LOST`, which begins at `IN_STOCK`."

    Design: Corner/endpoints/list_garments_filter_by_lifecycle
    """
    acct = make_account(legal_name="FilCo")
    gt = make_garment_type()
    wearer = make_wearer(acct["id"])
    g1 = make_garment(acct["id"], gt["id"])
    make_garment(acct["id"], gt["id"])  # stays IN_STOCK
    make_assignment(g1["id"], wearer["id"])  # g1 becomes ASSIGNED
    data, meta = validate_paginated(
        api.list_account_garments(acct["id"], ADMIN, params={"lifecycle_status": "ASSIGNED"})
    )
    assert meta["total_count"] == 1, (
        f"only the one ASSIGNED garment should match, got total_count {meta['total_count']}"
    )
    assert data[0]["id"] == g1["id"], (
        f"the filtered result must be the assigned garment, got {data[0]['id']}"
    )
