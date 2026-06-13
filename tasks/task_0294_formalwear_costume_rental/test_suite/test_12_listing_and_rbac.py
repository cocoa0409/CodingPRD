"""Corner: list pagination, FK-filtered listing, and role-based access control."""
from test_helpers import (
    validate_success, validate_error, validate_paginated, ApiErrorId,
    set_clock, create_catalog, create_unit, create_customer,
    make_customer_headers, setup_party_with_confirmed_member,
)
from test_helpers import api_client
from test_helpers import TEST_USERS
from test_helpers.factories import create_catalog_payload

MANAGER = TEST_USERS["manager_headers"]
CLERK = TEST_USERS["clerk_headers"]


def test_list_catalogs_pagination_envelope(api):
    """PRD §2.3: "The `limit` parameter caps the number of items returned; when omitted it defaults to 10, and it is constrained to a minimum of 1 and a maximum of 100."
    PRD §2.3: "Each list response carries the pagination bookkeeping in the `meta` object, namely `limit`, `offset`, `total_count`, and `has_more`."

    Design: Corner/endpoints/list_catalogs_pagination_envelope
    """
    set_clock()
    create_catalog(style_name="Cat One", category="FORMALWEAR")
    create_catalog(style_name="Cat Two", category="COSTUME")

    data, meta = validate_paginated(api_client.list_catalogs(MANAGER, params={"limit": 1, "offset": 0}))
    assert meta["total_count"] == 2
    assert meta["has_more"] is True
    assert len(data) == 1, "limit caps the page to one item"


def test_filter_garment_units_by_catalog_fk(api):
    """PRD §4: "The list endpoints accept optional filters in addition to `limit` and `offset`: `/catalogs` filters by `category`; `/garment-units` by `catalog_id`, `status`, and `size_code`".

    Design: Corner/endpoints/filter_garment_units_by_catalog_fk
    """
    set_clock()
    cat_a = create_catalog(style_name="CatA")
    cat_b = create_catalog(style_name="CatB")
    unit_a = create_unit(cat_a["id"], "M")
    create_unit(cat_b["id"], "L")

    data, meta = validate_paginated(
        api_client.list_garment_units(MANAGER, params={"catalog_id": cat_a["id"]}))
    assert meta["total_count"] == 1
    assert data[0]["id"] == unit_a["id"], "only catalog A's unit is returned"


def test_customer_cannot_create_catalog_forbidden(api):
    """PRD §2.1: "When an authenticated principal attempts an operation their role is not permitted to perform — or when an ownership-scoped role acts on a resource it does not own — the request is rejected with `ERR_FORBIDDEN`."

    Design: Corner/rbac/customer_cannot_create_catalog_forbidden
    """
    set_clock()
    customer = create_customer()
    res = api_client.create_catalog(
        create_catalog_payload(style_name="Sneaky", category="FORMALWEAR"),
        make_customer_headers(customer["id"]))
    validate_error(res, ApiErrorId.ERR_FORBIDDEN)


def test_clerk_cannot_lock_party_forbidden(api):
    """PRD §3.9: "Only the coordinator may lock or dissolve the party. Locking is a `Customer` action permitted when the `posture` is `READY` and the acting customer is the `coordinator_customer_id".

    Design: Corner/rbac/clerk_cannot_lock_party_forbidden
    """
    info = setup_party_with_confirmed_member(required_member_count=1)
    party = info["party"]
    res = api_client.lock_party_order(
        party["id"], {"expected_party_order_version": info["party_version_after_confirm"]}, CLERK)
    validate_error(res, ApiErrorId.ERR_FORBIDDEN)
    after = validate_success(api_client.get_party_order(
        party["id"], make_customer_headers(info["coordinator"]["id"])), 200)
    assert after["posture"] == "READY"


def test_non_coordinator_customer_cannot_lock_party(api):
    """PRD §3.9: "Locking is a `Customer` action permitted when the `posture` is `READY` and the acting customer is the `coordinator_customer_id`; a non-coordinator is rejected with `ERR_NOT_COORDINATOR`, and the supplied `expected_party_order_version` must match the party's current `version` or the lock is rejected with `ERR_STALE_VERSION`."

    Design: Corner/rbac/non_coordinator_customer_cannot_lock_party
    """
    info = setup_party_with_confirmed_member(required_member_count=1)
    party = info["party"]
    other = create_customer()
    res = api_client.lock_party_order(
        party["id"], {"expected_party_order_version": info["party_version_after_confirm"]},
        make_customer_headers(other["id"]))
    validate_error(res, ApiErrorId.ERR_NOT_COORDINATOR)
    after = validate_success(api_client.get_party_order(
        party["id"], make_customer_headers(info["coordinator"]["id"])), 200)
    assert after["posture"] == "READY"


def test_missing_auth_header_returns_unauthenticated(api):
    """PRD §2.1: "Every request to the API must be authenticated by two mandatory HTTP headers."
    PRD §2.1: "If either header is missing, or if `X-User-Role` is not one of the recognized role names, the request is rejected with `ERR_UNAUTHENTICATED`."

    Design: Corner/rbac/missing_auth_header_returns_unauthenticated
    """
    res = api_client.list_catalogs({})
    validate_error(res, ApiErrorId.ERR_UNAUTHENTICATED)
