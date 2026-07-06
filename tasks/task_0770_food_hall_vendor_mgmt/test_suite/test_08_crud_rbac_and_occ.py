"""CRUD, computed-field, RBAC, authentication, pagination, foreign-key existence,
ownership, and the settlement optimistic-concurrency guard.
"""
import pytest
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    assert_food_hall, NON_EXISTENT_UUID,
    open_stall, create_food_hall, create_active_vendor, create_stall,
    create_provisional_settlement,
    create_food_hall_payload, create_stall_payload, create_lease_payload,
    create_settlement_payload, create_order_payload,
    make_vendor_headers, TEST_USERS, ANONYMOUS_HEADERS, api_client,
)

HM = TEST_USERS["hall_manager_headers"]
POS = TEST_USERS["pos_operator_headers"]


def test_food_hall_create_returns_echoed_fields(api):
    """PRD §3.1: "The venue itself is a food hall, created by a `HallManager` with a
    display `name`, a `total_seating_capacity` of at least one shared seat, a
    `common_area_capacity` of at least one for standing and event occupancy, and
    daily operating bounds."
    PRD §2.4: "`id`: a server-minted UUID with no type prefix, unique across the
    system."

    Design: Corner/entities/food_hall_create_returns_all_fields
    """
    res = api.create_food_hall(create_food_hall_payload(
        name="Central Hall", total_seating_capacity=120, common_area_capacity=400,
        hall_open_minutes=480, hall_close_minutes=1320, event_buffer_minutes=45), HM)
    data = validate_success(res, 201)
    assert_food_hall(data)
    assert data["total_seating_capacity"] == 120
    assert data["common_area_capacity"] == 400
    assert data["event_buffer_minutes"] == 45


def test_stall_create_missing_stall_code_rejected(api):
    """PRD §2.10: "The body must be well-formed: required fields present, enum values
    legal, numeric ranges satisfied, and ordering constraints met. General violations
    return `ERR_INVALID_REQUEST` (422)."

    Design: Corner/entities/stall_create_missing_required_stall_code_returns_invalid_request
    """
    hall = create_food_hall()
    payload = create_stall_payload(hall["id"])
    del payload["stall_code"]
    res = api.create_stall(payload, HM)
    validate_error(res, "ERR_INVALID_REQUEST")


def test_get_nonexistent_stall_not_found(api):
    """PRD §2.9: "A missing resource yields the specific not-found error for that
    resource type: `ERR_FOOD_HALL_NOT_FOUND`, `ERR_VENDOR_NOT_FOUND`,
    `ERR_STALL_NOT_FOUND`, `ERR_LEASE_NOT_FOUND`, `ERR_PERMIT_NOT_FOUND`,
    `ERR_INSPECTION_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, `ERR_SEATING_NOT_FOUND`,
    `ERR_EVENT_NOT_FOUND`, or `ERR_SETTLEMENT_NOT_FOUND`."

    Design: Corner/entities/stall_get_nonexistent_not_found
    """
    res = api.get_stall(NON_EXISTENT_UUID, HM)
    validate_error(res, "ERR_STALL_NOT_FOUND")


def test_stall_create_ignores_client_supplied_posture(api):
    """PRD §3.1: "On creation a stall is vacant — it has no lease — so its
    `current_lease_id` and `current_vendor_id` are null and its posture is
    `SUSPENDED`."

    Design: Corner/entities/stall_create_operational_posture_input_ignored
    """
    hall = create_food_hall()
    payload = create_stall_payload(hall["id"], operational_posture="OPEN")
    data = validate_success(api.create_stall(payload, HM), 201)
    assert data["operational_posture"] == "SUSPENDED"


def test_lease_end_before_start_rejected(api):
    """PRD §2.10: "A lease whose `end_date` is not strictly after its `start_date`,
    or whose `rent_cap_cents` is below its `base_rent_cents`, returns
    `ERR_LEASE_TERM_INVALID` (422)."

    Design: Corner/validations/lease_end_before_start_returns_invalid_request
    """
    hall = create_food_hall()
    vendor = validate_success(api.create_vendor(
        {"legal_name": "V", "contact_email": "v@x.com"}, HM), 201)
    stall = create_stall(hall["id"])
    res = api.create_lease(create_lease_payload(
        stall["id"], vendor["id"], start_date="2026-12-31", end_date="2026-06-01"), HM)
    validate_error(res, "ERR_LEASE_TERM_INVALID")


def test_posoperator_cannot_create_stall(api):
    """PRD §2.1: "When the headers are well-formed but the role is not permitted to
    perform the requested operation — or an ownership-scoped role acts on a resource
    it does not own — the request is rejected with `ERR_UNAUTHORIZED`."

    Design: Corner/validations/posoperator_cannot_create_stall_unauthorized
    """
    hall = create_food_hall()
    res = api.create_stall(create_stall_payload(hall["id"]), POS)
    validate_error(res, "ERR_UNAUTHORIZED")


def test_food_hall_get_without_headers_unauthenticated(api):
    """PRD §2.1: "A request missing either header, or carrying a malformed value, is
    rejected with `ERR_UNAUTHENTICATED`."

    Design: Corner/validations/food_hall_get_unauthenticated
    """
    hall = create_food_hall()
    res = api.get_food_hall(hall["id"], ANONYMOUS_HEADERS)
    validate_error(res, "ERR_UNAUTHENTICATED")


def test_stalls_list_paginated_by_hall(api):
    """PRD §2.3: "Every list response includes `limit`, `offset`, `total_count`, and
    `has_more` in the `meta` object of the envelope."

    Design: Corner/endpoints/stalls_list_paginated_by_hall
    """
    hall = create_food_hall()
    create_stall(hall["id"], stall_code="A-1")
    create_stall(hall["id"], stall_code="A-2")
    data, meta = validate_paginated(api.list_stalls(HM, params={"food_hall_id": hall["id"]}))
    assert len(data) == 2
    assert meta["total_count"] == 2
    assert meta["has_more"] is False


def test_lease_create_nonexistent_stall_not_found(api):
    """PRD §2.9: "The same existence rule applies to foreign keys carried in a create
    request body — a `food_hall_id`, `stall_id`, `vendor_id`, `lease_id`, or
    `order_id` that does not resolve is rejected as not found."

    Design: Corner/entities/lease_create_nonexistent_stall_not_found
    """
    hall = create_food_hall()
    vendor = validate_success(api.create_vendor(
        {"legal_name": "V", "contact_email": "v@x.com"}, HM), 201)
    res = api.create_lease(create_lease_payload(NON_EXISTENT_UUID, vendor["id"]), HM)
    validate_error(res, "ERR_STALL_NOT_FOUND")


def test_vendor_cannot_accept_other_vendors_order(api):
    """PRD §2.1: "Ownership checks compare `X-User-ID` to the relevant vendor foreign
    key on the target resource: for accepting, fulfilling, or rejecting an order, the
    acting vendor must equal the `current_vendor_id` of the order's stall; for
    disputing a settlement, the acting vendor must equal the `vendor_id` of the
    settlement's lease. A mismatch is an `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/vendor_cannot_accept_other_vendors_order
    """
    ctx = open_stall(clock="2026-06-15T18:00:00Z")
    other_vendor = create_active_vendor(legal_name="V2", contact_email="v2@x.com")
    order = validate_success(api.create_order(
        create_order_payload(ctx["food_hall_id"], ctx["stall_id"]), POS), 201)

    res = api.accept_order(order["id"], make_vendor_headers(other_vendor["id"]))
    validate_error(res, "ERR_UNAUTHORIZED")

    order_after = validate_success(api.get_order(order["id"], HM), 200)
    assert order_after["status"] == "ROUTED"


def test_stale_lease_version_settlement_create_rejected(api):
    """PRD §2.8: "The create request must carry `expected_lease_version`, holding the
    `version` of the lease the client last observed. If that value does not match the
    lease's current `version`, the request is rejected with `ERR_STALE_LEASE_VERSION`
    and HTTP status 412. On a successful create the endpoint bumps the lease's
    `version`, so a subsequent create issued off the earlier, now-stale view of the
    lease will fail this check."

    Design: Corner/cross_cutting/occ_stale_lease_version_settlement_create
    """
    ctx = open_stall(clock="2026-06-15T18:00:00Z")
    stale_version = ctx["lease_version"]
    # First create succeeds and bumps the lease version.
    create_provisional_settlement(ctx["lease_id"], stale_version)
    # Second create still carrying the pre-bump version is rejected.
    res = api.create_settlement(
        create_settlement_payload(ctx["lease_id"], stale_version), HM)
    validate_error(res, "ERR_STALE_LEASE_VERSION")
