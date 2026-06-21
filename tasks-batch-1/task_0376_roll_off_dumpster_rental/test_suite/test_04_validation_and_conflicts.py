"""Validation precedence, cross-entity state dependencies, resource/temporal
overlap, and single-validation violation->error cases.

Per the PRD's fixed validation order (§2.9), where two checks could both fail
the higher-priority (state) one is reported; each conflict test arranges both
violations and asserts the PRD-stated winner.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS, make_contractor_headers,
)
from test_helpers import fixtures
from test_helpers import factories


YARD_ADMIN = TEST_USERS["yard_admin_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]
PERMIT = TEST_USERS["permit_officer_headers"]
BILLING = TEST_USERS["billing_clerk_headers"]


# ===========================================================================
# Queue A — priority_pair_validation_conflict
# ===========================================================================
def test_dispatch_state_error_beats_permit_safety_error(api):
    """PRD §2.9: "Then the target resource's state suitability for the requested
    transition (the state-conflict errors at HTTP 409 ...). Then the
    operation-specific business checks: on a delivery dispatch, container-type
    match (ERR_CONTAINER_TYPE_MISMATCH) and then the permit requirement
    (ERR_PERMIT_NOT_APPROVED)".
    PRD §3.5: "The chosen container must be IN_YARD, else
    ERR_CONTAINER_NOT_AVAILABLE."

    The container is OUT_OF_SERVICE (state) AND the order needs an unapproved
    permit (business_safety); the state error wins.

    Design: Difficulty/priority_pair_validation_conflict/dispatch_state_beats_permit_safety
    """
    fixtures.set_clock("2026-06-01")
    ct = fixtures.create_container_type()
    account = fixtures.create_account(business_name="Pri1")
    container = fixtures.create_container(ct["id"])
    # retire the container -> OUT_OF_SERVICE, capture its new version
    retired = get_success_data(api.retire_asset(container["id"], YARD_ADMIN))
    order = fixtures.book_order(account["id"], ct["id"], site_address="8 Birch",
                                requested_delivery_date="2026-06-05", requires_street_permit=True)
    # permit only REQUESTED (not approved)
    fixtures.request_permit(order["id"], permit_fee_cents=10000,
                            valid_from="2026-06-01", valid_until="2026-06-30")
    resp = api.dispatch_delivery(
        order["id"],
        factories.dispatch_delivery_payload(container["id"], retired["version"]),
        DISPATCHER,
    )
    validate_error(resp, ApiErrorId.ERR_CONTAINER_NOT_AVAILABLE.value)


def test_dispatch_permit_safety_error_in_isolation(api):
    """PRD §3.5: "If the order has requires_street_permit set, there must exist an
    APPROVED StreetPermit for the order whose valid_from-valid_until window
    covers the order's requested_delivery_date, else ERR_PERMIT_NOT_APPROVED."

    Isolating the permit-safety violation (container IN_YARD and valid, only the
    permit is unapproved) yields ERR_PERMIT_NOT_APPROVED — the error that loses
    to the state error when both hold.

    Design: Difficulty/priority_pair_validation_conflict/dispatch_state_beats_permit_safety
    """
    fixtures.set_clock("2026-06-01")
    ct = fixtures.create_container_type()
    account = fixtures.create_account(business_name="Pri1b")
    container = fixtures.create_container(ct["id"])  # IN_YARD, valid
    order = fixtures.book_order(account["id"], ct["id"], site_address="8b Birch",
                                requested_delivery_date="2026-06-05", requires_street_permit=True)
    fixtures.request_permit(order["id"], permit_fee_cents=10000,
                            valid_from="2026-06-01", valid_until="2026-06-30")
    resp = api.dispatch_delivery(
        order["id"],
        factories.dispatch_delivery_payload(container["id"], container["version"]),
        DISPATCHER,
    )
    validate_error(resp, ApiErrorId.ERR_PERMIT_NOT_APPROVED.value)


def test_route_append_state_error_beats_capacity_error(api):
    """PRD §2.9: "Then the target resource's state suitability for the requested
    transition (the state-conflict errors at HTTP 409 ...). Then the
    operation-specific business checks: ... on a route append, capacity
    (ERR_ROUTE_AT_CAPACITY)".
    PRD §3.6: "the route must be PLANNING (ERR_ROUTE_NOT_PLANNING); the route
    must have room, meaning its stop_count is strictly less than its
    capacity_stops (ERR_ROUTE_AT_CAPACITY)".

    The route is DISPATCHED (state) AND at capacity (stop_count==capacity_stops);
    appending a second stop is rejected with the state error.

    Design: Difficulty/priority_pair_validation_conflict/route_append_state_beats_capacity_constraint
    """
    ct = fixtures.create_container_type(
        size_code="YD20", base_rate_cents=40000, overage_day_cents=1200,
        included_tonnage_lbs=3000, overage_rate_cents_per_lb=8)
    account = fixtures.create_account(business_name="Pri2", credit_limit_cents=1000000)
    order1 = fixtures.book_order(account["id"], ct["id"], site_address="10 Oak")
    stop1 = fixtures.get_delivery_stop(order1["id"])
    order2 = fixtures.book_order(account["id"], ct["id"], site_address="11 Oak")
    stop2 = fixtures.get_delivery_stop(order2["id"])

    route = fixtures.create_route(capacity_stops=1)
    get_success_data(api.append_stop(
        route["id"], factories.append_stop_payload(stop1["id"], route["version"]), DISPATCHER))
    get_success_data(api.dispatch_route(route["id"], DISPATCHER))
    # route is now DISPATCHED and full; read its live version to isolate state-vs-capacity
    route_now = get_success_data(api.get_route(route["id"], DISPATCHER))

    resp = api.append_stop(
        route["id"], factories.append_stop_payload(stop2["id"], route_now["version"]), DISPATCHER)
    validate_error(resp, ApiErrorId.ERR_ROUTE_NOT_PLANNING.value)


def test_route_append_capacity_error_in_isolation(api):
    """PRD §3.6: "the route must have room, meaning its stop_count is strictly
    less than its capacity_stops (ERR_ROUTE_AT_CAPACITY)".

    Isolating the capacity violation on a still-PLANNING route (so the state
    check passes) yields ERR_ROUTE_AT_CAPACITY — the error that loses to the
    state error when both hold.

    Design: Difficulty/priority_pair_validation_conflict/route_append_state_beats_capacity_constraint
    """
    ct = fixtures.create_container_type(
        size_code="YD20", base_rate_cents=40000, overage_day_cents=1200,
        included_tonnage_lbs=3000, overage_rate_cents_per_lb=8)
    account = fixtures.create_account(business_name="Pri2b", credit_limit_cents=1000000)
    order1 = fixtures.book_order(account["id"], ct["id"], site_address="10b Oak")
    stop1 = fixtures.get_delivery_stop(order1["id"])
    order2 = fixtures.book_order(account["id"], ct["id"], site_address="11b Oak")
    stop2 = fixtures.get_delivery_stop(order2["id"])

    route = fixtures.create_route(capacity_stops=1)
    appended = get_success_data(api.append_stop(
        route["id"], factories.append_stop_payload(stop1["id"], route["version"]), DISPATCHER))
    # route still PLANNING but now full; read live version for the OCC field
    route_now = get_success_data(api.get_route(route["id"], DISPATCHER))
    resp = api.append_stop(
        route["id"], factories.append_stop_payload(stop2["id"], route_now["version"]), DISPATCHER)
    validate_error(resp, ApiErrorId.ERR_ROUTE_AT_CAPACITY.value)


# ===========================================================================
# Queue A — cross_entity_state_dependency
# ===========================================================================
def test_dispatch_blocked_by_suspended_account(api):
    """PRD §3.5: "The order's account must be ACTIVE, else
    ERR_ACCOUNT_SUSPENDED."

    With the account SUSPENDED, dispatch-delivery is rejected; the order stays
    BOOKED.

    Design: Difficulty/cross_entity_state_dependency/dispatch_blocked_by_suspended_account
    """
    booked = fixtures.setup_booked_order_with_container(
        account_overrides={"business_name": "Susp"}, order_overrides={"site_address": "13 Oak"})
    validate_success(api.suspend_account(booked["account"]["id"], BILLING))
    resp = api.dispatch_delivery(
        booked["order"]["id"],
        factories.dispatch_delivery_payload(booked["container"]["id"], booked["container"]["version"]),
        DISPATCHER,
    )
    validate_error(resp, ApiErrorId.ERR_ACCOUNT_SUSPENDED.value)
    order = validate_success(api.get_rental_order(booked["order"]["id"], DISPATCHER))
    assert order["logistics_status"] == "BOOKED"


def test_dispatch_succeeds_after_account_reinstated(api):
    """PRD §3.2: "Suspending an account blocks it from taking on new orders;
    reinstating it returns it to ACTIVE."
    PRD §3.5: "The order's account must be ACTIVE, else ERR_ACCOUNT_SUSPENDED.
    ... When all conditions hold, the order moves BOOKED -> SCHEDULED on its
    logistics axis."

    Reinstating the account clears the cross-entity block, so the same dispatch
    that was rejected now succeeds.

    Design: Difficulty/cross_entity_state_dependency/dispatch_blocked_by_suspended_account
    """
    booked = fixtures.setup_booked_order_with_container(
        account_overrides={"business_name": "Susp2"}, order_overrides={"site_address": "13b Oak"})
    validate_success(api.suspend_account(booked["account"]["id"], BILLING))
    validate_success(api.reinstate_account(booked["account"]["id"], BILLING))
    resp = api.dispatch_delivery(
        booked["order"]["id"],
        factories.dispatch_delivery_payload(booked["container"]["id"], booked["container"]["version"]),
        DISPATCHER,
    )
    order = validate_success(resp)
    assert order["logistics_status"] == "SCHEDULED"


def test_complete_stop_blocked_by_planning_route(api):
    """PRD §3.7: "A completion always requires the stop to be ASSIGNED
    (ERR_STOP_NOT_ASSIGNED) and its route to be DISPATCHED
    (ERR_ROUTE_NOT_DISPATCHED)."

    Completing a stop whose route is still PLANNING is rejected; the stop stays
    ASSIGNED.

    Design: Difficulty/cross_entity_state_dependency/stop_complete_blocked_by_planning_route
    """
    sched = fixtures.setup_scheduled_order_planning_route(
        ct_overrides=factories.create_container_type_payload(
            size_code="YD20", base_rate_cents=40000, overage_day_cents=1200,
            included_tonnage_lbs=3000, overage_rate_cents_per_lb=8),
        account_overrides={"business_name": "Plan"},
        order_overrides={"site_address": "14 Oak"},
    )
    resp = api.complete_stop(sched["del_stop"]["id"], DISPATCHER)
    validate_error(resp, ApiErrorId.ERR_ROUTE_NOT_DISPATCHED.value)
    stop = validate_success(api.get_service_stop(sched["del_stop"]["id"], DISPATCHER))
    assert stop["status"] == "ASSIGNED"


def test_complete_stop_succeeds_once_route_dispatched(api):
    """PRD §3.6: "Stops on a route become completable only once the route is
    DISPATCHED."
    PRD §3.7: "Completing the DELIVERY stop advances the order from SCHEDULED to
    ON_SITE on its logistics axis ... On success the stop itself moves ASSIGNED
    -> COMPLETED."

    Once the route is DISPATCHED, the same DELIVERY stop completes (the
    cross-entity route-state precondition is now satisfied).

    Design: Difficulty/cross_entity_state_dependency/stop_complete_blocked_by_planning_route
    """
    sched = fixtures.setup_scheduled_order_planning_route(
        ct_overrides=factories.create_container_type_payload(
            size_code="YD20", base_rate_cents=40000, overage_day_cents=1200,
            included_tonnage_lbs=3000, overage_rate_cents_per_lb=8),
        account_overrides={"business_name": "Plan2"},
        order_overrides={"site_address": "14b Oak"},
    )
    validate_success(api.dispatch_route(sched["route"]["id"], DISPATCHER))
    validate_success(api.complete_stop(sched["del_stop"]["id"], DISPATCHER))
    stop = validate_success(api.get_service_stop(sched["del_stop"]["id"], DISPATCHER))
    assert stop["status"] == "COMPLETED"


# ===========================================================================
# Queue A — resource_temporal_overlap
# ===========================================================================
def test_same_truck_same_day_route_rejected(api):
    """PRD §2.10: "A route's truck_code must be unique among routes sharing the
    same service_date."
    PRD §3.6: "a `truck_code` (unique among routes on the same `service_date`)".

    A second route with the same (truck_code, service_date) is rejected with
    ERR_DUPLICATE_RESOURCE.

    Design: Difficulty/resource_temporal_overlap/truck_same_day_route_collision
    """
    fixtures.create_route(service_date="2026-06-01", truck_code="TRKP", capacity_stops=5)
    resp = api.create_route(
        {"service_date": "2026-06-01", "truck_code": "TRKP", "capacity_stops": 5}, DISPATCHER)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_RESOURCE.value)


def test_same_truck_different_day_route_allowed(api):
    """PRD §2.10: "A route's truck_code must be unique among routes sharing the
    same service_date."

    Changing the date removes the collision: the same truck_code on a different
    service_date is accepted.

    Design: Difficulty/resource_temporal_overlap/truck_same_day_route_collision
    """
    fixtures.create_route(service_date="2026-06-01", truck_code="TRKP2", capacity_stops=5)
    resp = api.create_route(
        {"service_date": "2026-06-02", "truck_code": "TRKP2", "capacity_stops": 5}, DISPATCHER)
    validate_success(resp, expected_status=201)


def test_permit_window_closed_interval_overlap_rejected(api):
    """PRD §3.4: "the order may not already hold another APPROVED permit whose
    closed window overlaps this one — two windows that share even a single
    calendar day overlap — and an overlapping approval is rejected with
    ERR_PERMIT_WINDOW_OVERLAP."

    First permit APPROVED for 2026-06-01..2026-06-10; approving a second permit
    2026-06-10..2026-06-15 shares the boundary day 2026-06-10 -> overlap; it
    stays REQUESTED.

    Design: Difficulty/resource_temporal_overlap/permit_window_closed_interval_overlap
    """
    fixtures.set_clock("2026-05-15")
    ct = fixtures.create_container_type()
    account = fixtures.create_account(business_name="Perm")
    order = fixtures.book_order(account["id"], ct["id"], site_address="15 Oak",
                                requested_delivery_date="2026-06-05", requires_street_permit=True)
    p1 = fixtures.request_permit(order["id"], permit_fee_cents=10000,
                                 valid_from="2026-06-01", valid_until="2026-06-10")
    p2 = fixtures.request_permit(order["id"], permit_fee_cents=10000,
                                 valid_from="2026-06-10", valid_until="2026-06-15")
    validate_success(api.approve_permit(p1["id"], PERMIT))
    resp = api.approve_permit(p2["id"], PERMIT)
    validate_error(resp, ApiErrorId.ERR_PERMIT_WINDOW_OVERLAP.value)
    permit2 = validate_success(api.get_street_permit(p2["id"], PERMIT))
    assert permit2["status"] == "REQUESTED"


def test_permit_non_overlapping_windows_both_approve(api):
    """PRD §3.4: "the order may not already hold another APPROVED permit whose
    closed window overlaps this one — two windows that share even a single
    calendar day overlap — and an overlapping approval is rejected with
    ERR_PERMIT_WINDOW_OVERLAP."

    Adjacent-but-disjoint windows (first ends 2026-06-09, second starts
    2026-06-10) share no calendar day, so both approvals succeed — the
    complement of the boundary-day overlap rejection.

    Design: Difficulty/resource_temporal_overlap/permit_window_closed_interval_overlap
    """
    fixtures.set_clock("2026-05-15")
    ct = fixtures.create_container_type()
    account = fixtures.create_account(business_name="Perm3")
    order = fixtures.book_order(account["id"], ct["id"], site_address="15b Oak",
                                requested_delivery_date="2026-06-05", requires_street_permit=True)
    p1 = fixtures.request_permit(order["id"], permit_fee_cents=10000,
                                 valid_from="2026-06-01", valid_until="2026-06-09")
    p2 = fixtures.request_permit(order["id"], permit_fee_cents=10000,
                                 valid_from="2026-06-10", valid_until="2026-06-15")
    validate_success(api.approve_permit(p1["id"], PERMIT))
    resp = api.approve_permit(p2["id"], PERMIT)
    approved2 = validate_success(resp)
    assert approved2["status"] == "APPROVED"


# ===========================================================================
# Queue B — validations
# ===========================================================================
def test_permit_reversed_date_range_rejected(api):
    """PRD §3.4: "The valid_until must be on or after valid_from; a reversed
    window is rejected with ERR_INVALID_DATE_RANGE (HTTP 422)."

    Design: Corner/validations/permit_invalid_date_range_rejected
    """
    ct = fixtures.create_container_type()
    account = fixtures.create_account(business_name="Dr")
    order = fixtures.book_order(account["id"], ct["id"], site_address="22 Main",
                                requested_delivery_date="2026-06-05", requires_street_permit=True)
    resp = api.create_street_permit(
        {"order_id": order["id"], "municipality": "Town", "permit_fee_cents": 10000,
         "valid_from": "2026-06-20", "valid_until": "2026-06-10"}, PERMIT)
    validate_error(resp, ApiErrorId.ERR_INVALID_DATE_RANGE.value)


def test_permit_approve_after_window_passed_rejected(api):
    """PRD §3.4: "the business clock's current_date must be on or before the
    permit's valid_until; approving a permit whose window has already passed is
    rejected with ERR_PERMIT_WINDOW_PASSED."

    current_date 2026-07-01 is after valid_until 2026-06-30.

    Design: Corner/validations/permit_approve_after_window_passed_rejected
    """
    fixtures.set_clock("2026-07-01")
    ct = fixtures.create_container_type()
    account = fixtures.create_account(business_name="Win")
    order = fixtures.book_order(account["id"], ct["id"], site_address="23 Main",
                                requested_delivery_date="2026-06-05", requires_street_permit=True)
    permit = fixtures.request_permit(order["id"], permit_fee_cents=10000,
                                     valid_from="2026-06-01", valid_until="2026-06-30")
    resp = api.approve_permit(permit["id"], PERMIT)
    validate_error(resp, ApiErrorId.ERR_PERMIT_WINDOW_PASSED.value)


def test_duplicate_asset_tag_rejected(api):
    """PRD §2.10: "A container's `asset_tag` must be unique across all containers."

    Design: Corner/validations/duplicate_asset_tag_rejected
    """
    ct = fixtures.create_container_type()
    fixtures.create_container(ct["id"], asset_tag="T-DUP")
    resp = api.create_container(
        {"container_type_id": ct["id"], "asset_tag": "T-DUP", "yard_code": "Y2"}, YARD_ADMIN)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_RESOURCE.value)


def test_dispatch_requires_approved_permit(api):
    """PRD §3.5: "If the order has requires_street_permit set, there must exist an
    APPROVED StreetPermit for the order whose valid_from-valid_until window
    covers the order's requested_delivery_date, else ERR_PERMIT_NOT_APPROVED."

    With only a REQUESTED (unapproved) permit and an otherwise-valid container,
    dispatch is rejected for the permit reason.

    Design: Corner/validations/dispatch_requires_approved_permit
    """
    fixtures.set_clock("2026-06-01")
    ct = fixtures.create_container_type()
    account = fixtures.create_account(business_name="Perm2")
    container = fixtures.create_container(ct["id"])
    order = fixtures.book_order(account["id"], ct["id"], site_address="24 Main",
                                requested_delivery_date="2026-06-05", requires_street_permit=True)
    fixtures.request_permit(order["id"], permit_fee_cents=10000,
                            valid_from="2026-06-01", valid_until="2026-06-30")
    resp = api.dispatch_delivery(
        order["id"],
        factories.dispatch_delivery_payload(container["id"], container["version"]),
        DISPATCHER,
    )
    validate_error(resp, ApiErrorId.ERR_PERMIT_NOT_APPROVED.value)


def test_container_type_mismatch_at_dispatch(api):
    """PRD §3.5: "The container's container_type_id must equal the order's
    container_type_id, else ERR_CONTAINER_TYPE_MISMATCH."

    A YD20 container dispatched to a YD30 order is rejected.

    Design: Corner/validations/container_type_mismatch_at_dispatch
    """
    ct30 = fixtures.create_container_type()  # YD30
    ct20 = fixtures.create_container_type(
        size_code="YD20", base_rate_cents=40000, overage_day_cents=1200,
        included_tonnage_lbs=3000, overage_rate_cents_per_lb=8)
    account = fixtures.create_account(business_name="Mis")
    container20 = fixtures.create_container(ct20["id"])
    order = fixtures.book_order(account["id"], ct30["id"], site_address="25 Main")
    resp = api.dispatch_delivery(
        order["id"],
        factories.dispatch_delivery_payload(container20["id"], container20["version"]),
        DISPATCHER,
    )
    validate_error(resp, ApiErrorId.ERR_CONTAINER_TYPE_MISMATCH.value)
