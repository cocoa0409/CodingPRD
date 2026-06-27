"""ATM provisioning, CRUD, listing, initial state, and access control.

Covers queue-B corner instances from the entities, state_machines (initial state),
endpoints (listing), and rbac sections.
"""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, NON_EXISTENT_UUID,
    assert_atm,
    create_atm_payload, create_location_payload,
    TEST_USERS,
    make_field_tech_headers, make_settlement_officer_headers,
    provision_network, create_vault, create_route, create_site_merchant,
    create_location, create_atm, schedule_order,
)

ADMIN = TEST_USERS["platform_admin_headers"]
VAULT = TEST_USERS["vault_controller_headers"]


# ============================================================================
# entities section
# ============================================================================

def test_create_atm_returns_201_with_system_fields(api):
    """PRD §3.2: "A freshly provisioned machine starts with `operational_status` of `IN_SERVICE`
    and `cash_status` of `EMPTY`; its computed counters `monthly_wd_count`, `loaded_cents`, and
    `dispensed_cents_since_load` all start at zero, and its `fee_disclosure_id` is null until
    compliance approves a disclosure for it."
    PRD §2.4: "a system-managed integer that begins at its initial value and increments by
    one on every modification to the resource."

    Design: Corner/entities/create_atm_returns_201_with_system_fields
    """
    net = provision_network()
    payload = create_atm_payload(net["location"]["id"], surcharge_cents=250)
    resp = api.create_atm(payload, headers=ADMIN)
    data = validate_success(resp, expected_status=201)
    assert_atm(data)
    assert data["version"] == 1
    assert data["operational_status"] == "IN_SERVICE"
    assert data["cash_status"] == "EMPTY"
    assert data["monthly_wd_count"] == 0


def test_atm_default_note_denomination_applied(api):
    """PRD §3.2: "The note value the machine dispenses is given by `note_denomination_cents`;
    when omitted it defaults to 2000, meaning the machine dispenses twenty-dollar bills."

    Design: Corner/entities/atm_default_note_denomination_applied
    """
    net = provision_network()
    payload = {"serial_no": "SN-DEF-NOTE", "location_id": net["location"]["id"], "surcharge_cents": 250}
    resp = api.create_atm(payload, headers=ADMIN)
    data = validate_success(resp, expected_status=201)
    assert data["note_denomination_cents"] == 2000


def test_get_atm_nonexistent_returns_404(api):
    """PRD §2.6: "It confirms the first identifier refers to an existing resource before looking
    at the second, and rejects the request with `ERR_NOT_FOUND` against the first identifier that
    does not resolve."

    Design: Corner/entities/get_atm_nonexistent_returns_404
    """
    resp = api.get_atm(NON_EXISTENT_UUID, headers=ADMIN)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND, expected_status=404)


def test_create_atm_missing_required_serial_returns_invalid_request(api):
    """PRD §2.6: "After existence resolves, every create or transition request must have its
    required body fields present and well-typed and every enum-valued field set to a recognized
    member, or the request is rejected with `ERR_INVALID_REQUEST`."

    Design: Corner/entities/create_atm_missing_required_serial_returns_invalid_request
    """
    net = provision_network()
    payload = {"location_id": net["location"]["id"], "surcharge_cents": 250}  # serial_no omitted
    resp = api.create_atm(payload, headers=ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, expected_status=422)


def test_create_location_invalid_enum_jurisdiction_returns_invalid_request(api):
    """PRD §2.6: "After existence resolves, every create or transition request must have its
    required body fields present and well-typed and every enum-valued field set to a recognized
    member, or the request is rejected with `ERR_INVALID_REQUEST`."

    Design: Corner/entities/create_atm_invalid_enum_jurisdiction_on_location_returns_invalid_request
    """
    vault = create_vault()
    route = create_route(vault["id"])
    merchant = create_site_merchant()
    payload = create_location_payload(merchant["id"], route["id"], jurisdiction_code="ZZ")
    resp = api.create_location(payload, headers=ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, expected_status=422)


def test_duplicate_atm_serial_returns_conflict(api):
    """PRD §3.2: "The machine's serial is its physical fingerprint: `serial_no` must be unique
    across every machine in the system, and a collision is rejected with `ERR_DUPLICATE_SERIAL`."

    Design: Corner/entities/duplicate_atm_serial_returns_conflict
    """
    net = provision_network()
    first = create_atm(net["location"]["id"], serial_no="SN-DUP-X", surcharge_cents=250)
    assert first["serial_no"] == "SN-DUP-X"
    dup_payload = create_atm_payload(net["location"]["id"], serial_no="SN-DUP-X", surcharge_cents=250)
    resp = api.create_atm(dup_payload, headers=ADMIN)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_SERIAL, expected_status=409)


def test_create_atm_bad_location_fk_returns_404(api):
    """PRD §2.6: "This same existence pass extends to foreign keys carried in a request body:
    after the path resolves, every referenced entity named in the body must exist, or the request
    is rejected with `ERR_NOT_FOUND`."

    Design: Corner/entities/create_atm_bad_location_fk_returns_404
    """
    payload = create_atm_payload(NON_EXISTENT_UUID, serial_no="SN-BADFK", surcharge_cents=250)
    resp = api.create_atm(payload, headers=ADMIN)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND, expected_status=404)


def test_list_atms_pagination_envelope(api):
    """PRD §2.3: "Paginated and non-paginated list-based responses include the following fields
    in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and
    `has_more`."

    Design: Corner/entities/list_atms_pagination_envelope
    """
    net = provision_network()
    # provision_network already creates one ATM at net["location"]; isolate this
    # pagination assertion to a fresh location so the location_id filter returns
    # exactly the two ATMs created below.
    page_location = create_location(net["merchant"]["id"], net["route"]["id"])
    create_atm(page_location["id"], serial_no="SN-PAGE-1", surcharge_cents=250)
    create_atm(page_location["id"], serial_no="SN-PAGE-2", surcharge_cents=250)
    resp = api.list_atms(headers=ADMIN, params={"location_id": page_location["id"],
                                                "limit": 1, "offset": 0})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 2
    assert meta["has_more"] is True
    assert len(data) == 1


# ============================================================================
# state_machines section — initial state
# ============================================================================

def test_new_atm_starts_in_initial_states(api):
    """PRD §3.2: "A freshly provisioned machine starts with `operational_status` of `IN_SERVICE`
    and `cash_status` of `EMPTY`; its computed counters `monthly_wd_count`, `loaded_cents`, and
    `dispensed_cents_since_load` all start at zero, and its `fee_disclosure_id` is null until
    compliance approves a disclosure for it."

    Design: Corner/state_machines/new_atm_starts_in_initial_states
    """
    net = provision_network()
    payload = create_atm_payload(net["location"]["id"], serial_no="SN-INIT-1", surcharge_cents=250)
    data = validate_success(api.create_atm(payload, headers=ADMIN), expected_status=201)
    assert data["operational_status"] == "IN_SERVICE"
    assert data["cash_status"] == "EMPTY"


# NOTE: Corner/endpoints/list_orders_filtered_by_atm is intentionally SKIPPED under the
# PRD-first filter: the replenishment-order list filter-by-atm_id semantics appear only in the
# §4 routing-table row (endpoint-titular), with no §3 prose stating the filter behavior, so the
# C2 rule-bearing-citation requirement cannot be met. Gap left as a gap.


# ============================================================================
# rbac section
# ============================================================================

def test_fieldtech_cannot_create_vault(api):
    """PRD §2.1: "When the headers are present but the declared role is not permitted to perform
    the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE`."
    PRD §3.1: "configuration is the `PlatformAdmin`'s domain."

    Design: Corner/rbac/fieldtech_cannot_create_vault
    """
    resp = api.create_vault({"name": "V", "provisioned_cents": 1000},
                            headers=make_field_tech_headers())
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE, expected_status=403)


def test_settlementofficer_cannot_dispatch_replenishment(api):
    """PRD §2.1: "When the headers are present but the declared role is not permitted to perform
    the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE`."
    PRD §3.4: "The pivotal action is **dispatch**, performed by a `VaultController`, which advances
    the order from `SCHEDULED` to `DISPATCHED`."

    Design: Corner/rbac/settlementofficer_cannot_dispatch_replenishment
    """
    net = provision_network()
    order = schedule_order(net["atm"]["id"], net["route"]["id"])
    resp = api.dispatch_order(order["id"], {"expected_vault_version": net["vault"]["version"]},
                              headers=make_settlement_officer_headers())
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE, expected_status=403)


def test_missing_auth_headers_returns_401(api):
    """PRD §2.1: "A request missing either header, or carrying a header the server cannot
    interpret, is rejected with `ERR_UNAUTHENTICATED`."

    Design: Corner/rbac/missing_auth_headers_returns_401
    """
    resp = api.get_atm(NON_EXISTENT_UUID, headers={})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED, expected_status=401)
