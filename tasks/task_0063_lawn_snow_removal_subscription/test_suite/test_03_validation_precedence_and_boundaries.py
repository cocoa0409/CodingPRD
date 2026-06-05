"""Depth tests: validation precedence, numeric/empty-set boundaries, temporal overlap.

Covers queue A rules: priority_pair_validation_conflict, boundary_precision_check,
resource_temporal_overlap.
"""
from test_helpers import (
    validate_error,
    NON_EXISTENT_UUID,
    ApiErrorId,
    TEST_USERS,
    fixtures as fx,
)


# =====================================================================
# priority_pair_validation_conflict / not_found_beats_invalid_state_on_dispatch
# =====================================================================

def test_dispatch_nonexistent_visit_returns_not_found(api):
    """PRD §2.9: "Existence of every referenced resource is checked next, left to right (`ERR_NOT_FOUND`). ... Only after those structural checks does the platform evaluate
    state legality (`ERR_INVALID_STATE`) and the domain-specific business rules described
    in Section 3."

    Dispatching a non-existent visit id yields ERR_NOT_FOUND (existence outranks state).

    Design: Difficulty/priority_pair_validation_conflict/not_found_beats_invalid_state_on_dispatch
    """
    resp = api.dispatch_visit(NON_EXISTENT_UUID, TEST_USERS["dispatcher_headers"])
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


def test_dispatch_nonexistent_visit_status_404(api):
    """PRD §2.9: "an unauthenticated caller never learns whether a resource exists" —
    and existence (ERR_NOT_FOUND) is evaluated before state legality.
    PRD §5 catalogue maps ERR_NOT_FOUND to HTTP 404.

    Confirms the 404 status for the missing-visit dispatch.

    Design: Difficulty/priority_pair_validation_conflict/not_found_beats_invalid_state_on_dispatch
    """
    resp = api.dispatch_visit("00000000-0000-4000-8000-000000000000",
                              TEST_USERS["dispatcher_headers"])
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value, expected_status=404)


# =====================================================================
# priority_pair_validation_conflict / contract_not_active_beats_no_equipment_on_dispatch
# =====================================================================

def test_contract_not_active_outranks_no_equipment(api):
    """PRD §3.5: "Dispatch is permitted only when the visit is `SCHEDULED` and the owning contract of the visit's stop is `ACTIVE` (otherwise `ERR_CONTRACT_NOT_ACTIVE`). Dispatch must then find a piece of equipment to assign ... If no equipment on the route is in `IDLE` or `IN_SERVICE` status ... dispatch is rejected with `ERR_NO_EQUIPMENT_AVAILABLE`."

    SUSPENDED contract with zero route equipment: the contract-active gate fires first,
    so the result is ERR_CONTRACT_NOT_ACTIVE, not ERR_NO_EQUIPMENT_AVAILABLE.

    Design: Difficulty/priority_pair_validation_conflict/contract_not_active_beats_no_equipment_on_dispatch
    """
    ctx, visit = fx.setup_scheduled_visit(
        zip="91019",
        contract_overrides={"contract_price_cents": 10000, "term_months": 3},
        visit_overrides={"service_type": "SNOW", "snow_depth_in": 3.0, "runtime_hours": 2},
        with_equipment=False,
    )
    api.suspend_contract(ctx["contract"]["id"], TEST_USERS["dispatcher_headers"])
    resp = api.dispatch_visit(visit["id"], TEST_USERS["dispatcher_headers"])
    validate_error(resp, ApiErrorId.ERR_CONTRACT_NOT_ACTIVE.value, expected_status=409)


def test_contract_not_active_on_dispatch_409(api):
    """PRD §3.4: "an attempt to dispatch against a contract that is not `ACTIVE` is
    rejected with `ERR_CONTRACT_NOT_ACTIVE`."
    PRD §5 catalogue maps ERR_CONTRACT_NOT_ACTIVE to HTTP 409.

    Design: Difficulty/priority_pair_validation_conflict/contract_not_active_beats_no_equipment_on_dispatch
    """
    ctx, visit = fx.setup_scheduled_visit(
        zip="91019",
        contract_overrides={"contract_price_cents": 10000, "term_months": 3},
        visit_overrides={"service_type": "SNOW", "snow_depth_in": 3.0, "runtime_hours": 2},
        with_equipment=False,
    )
    api.suspend_contract(ctx["contract"]["id"], TEST_USERS["dispatcher_headers"])
    resp = api.dispatch_visit(visit["id"], TEST_USERS["dispatcher_headers"])
    validate_error(resp, ApiErrorId.ERR_CONTRACT_NOT_ACTIVE.value, expected_status=409)


# =====================================================================
# boundary_precision_check / snow_depth_exactly_two_inches_no_dispatch
# =====================================================================

def test_snow_depth_exactly_two_inches_no_dispatch(api):
    """PRD §3.4: "The platform will dispatch only when the reading's measured depth is strictly greater than 2.0 inches — a reading whose `snow_depth_in` is at or below 2.0 produces no dispatch and is rejected with `ERR_SNOW_THRESHOLD_NOT_MET`."

    Depth exactly 2.0 is not > 2.0, so processing is rejected and the reading stays
    unprocessed.

    Design: Difficulty/boundary_precision_check/snow_depth_exactly_two_inches_no_dispatch
    """
    ctx = fx.setup_route_with_stop(zip="10101",
                                   contract_overrides={"contract_price_cents": 10000,
                                                       "term_months": 3})
    wr = fx.make_weather_reading(region_zip="10101", snow_depth_in=2.0,
                                 observed_at="2026-01-11T06:00:00Z")
    resp = api.process_weather_reading(wr["id"], {"route_id": ctx["route"]["id"]},
                                       TEST_USERS["dispatcher_headers"])
    validate_error(resp, ApiErrorId.ERR_SNOW_THRESHOLD_NOT_MET.value, expected_status=409)
    assert fx.get_weather_reading(wr["id"])["processed"] is False


def test_snow_depth_just_below_threshold_not_processed(api):
    """PRD §3.4: "a reading whose `snow_depth_in` is at or below 2.0 produces no dispatch and is rejected with `ERR_SNOW_THRESHOLD_NOT_MET`."

    A reading at exactly 2.0 leaves processed false (no state change on rejection).

    Design: Difficulty/boundary_precision_check/snow_depth_exactly_two_inches_no_dispatch
    """
    ctx = fx.setup_route_with_stop(zip="10101",
                                   contract_overrides={"contract_price_cents": 10000,
                                                       "term_months": 3})
    wr = fx.make_weather_reading(region_zip="10101", snow_depth_in=2.0)
    api.process_weather_reading(wr["id"], {"route_id": ctx["route"]["id"]},
                                TEST_USERS["dispatcher_headers"])
    assert fx.get_route(ctx["route"]["id"])["status"] == "OPEN"
    assert fx.get_weather_reading(wr["id"])["processed"] is False


# =====================================================================
# boundary_precision_check / dispatch_empty_equipment_pool_returns_no_equipment
# =====================================================================

def test_dispatch_empty_equipment_pool_rejected(api):
    """PRD §3.5: "If no equipment on the route is in `IDLE` or `IN_SERVICE` status — for instance, when the entire pool is `MAINTENANCE_DUE` or `UNDER_MAINTENANCE` — dispatch is rejected with `ERR_NO_EQUIPMENT_AVAILABLE`."

    ACTIVE contract, SCHEDULED visit, route with no equipment registered at all: the
    empty candidate pool yields ERR_NO_EQUIPMENT_AVAILABLE and the visit stays SCHEDULED.

    Design: Difficulty/boundary_precision_check/dispatch_empty_equipment_pool_returns_no_equipment
    """
    ctx, visit = fx.setup_scheduled_visit(
        zip="10202",
        contract_overrides={"contract_price_cents": 10000, "term_months": 3},
        visit_overrides={"service_type": "SNOW", "snow_depth_in": 3.0, "runtime_hours": 2},
        with_equipment=False,
    )
    resp = api.dispatch_visit(visit["id"], TEST_USERS["dispatcher_headers"])
    validate_error(resp, ApiErrorId.ERR_NO_EQUIPMENT_AVAILABLE.value, expected_status=409)
    assert fx.get_visit(visit["id"])["status"] == "SCHEDULED"


def test_dispatch_no_equipment_leaves_visit_scheduled(api):
    """PRD §3.5: "dispatch is rejected with `ERR_NO_EQUIPMENT_AVAILABLE`."

    Confirms the rejected dispatch performs no state change: the visit remains SCHEDULED.

    Design: Difficulty/boundary_precision_check/dispatch_empty_equipment_pool_returns_no_equipment
    """
    ctx, visit = fx.setup_scheduled_visit(
        zip="10202",
        contract_overrides={"contract_price_cents": 10000, "term_months": 3},
        visit_overrides={"service_type": "SNOW", "snow_depth_in": 3.0, "runtime_hours": 2},
        with_equipment=False,
    )
    api.dispatch_visit(visit["id"], TEST_USERS["dispatcher_headers"])
    assert fx.get_visit(visit["id"])["status"] == "SCHEDULED"


# =====================================================================
# resource_temporal_overlap / reading_double_process_rejected_same_route
# =====================================================================

def test_reading_double_process_rejected(api):
    """PRD §3.4: "A reading may be processed for dispatch at most once; a second attempt against an already-processed reading (its `processed` already true) is rejected with `ERR_READING_ALREADY_PROCESSED`."

    Process a depth-3.0 reading once (route -> DISPATCHED, reading processed), then a
    second process against the same already-processed reading is rejected.

    Design: Difficulty/resource_temporal_overlap/reading_double_process_rejected_same_route
    """
    ctx = fx.setup_full_dispatch_ready(
        zip="10505",
        contract_overrides={"contract_price_cents": 10000, "term_months": 3},
        equipment_overrides={"equipment_type": "PLOW", "age_months": 5},
    )
    wr = fx.make_weather_reading(region_zip="10505", snow_depth_in=3.0,
                                 observed_at="2026-01-12T06:00:00Z")
    api.process_weather_reading(wr["id"], {"route_id": ctx["route"]["id"]},
                                TEST_USERS["dispatcher_headers"])
    resp = api.process_weather_reading(wr["id"], {"route_id": ctx["route"]["id"]},
                                       TEST_USERS["dispatcher_headers"])
    validate_error(resp, ApiErrorId.ERR_READING_ALREADY_PROCESSED.value, expected_status=409)


def test_reading_stays_processed_after_double_attempt(api):
    """PRD §3.4: "The reading's `processed` flag is set to true, and the route's `status`
    becomes `DISPATCHED`."
    PRD §3.4: "a second attempt against an already-processed reading (its `processed`
    already true) is rejected with `ERR_READING_ALREADY_PROCESSED`."

    The reading remains processed == true after the rejected second attempt.

    Design: Difficulty/resource_temporal_overlap/reading_double_process_rejected_same_route
    """
    ctx = fx.setup_full_dispatch_ready(
        zip="10505",
        contract_overrides={"contract_price_cents": 10000, "term_months": 3},
        equipment_overrides={"equipment_type": "PLOW", "age_months": 5},
    )
    wr = fx.make_weather_reading(region_zip="10505", snow_depth_in=3.0)
    api.process_weather_reading(wr["id"], {"route_id": ctx["route"]["id"]},
                                TEST_USERS["dispatcher_headers"])
    api.process_weather_reading(wr["id"], {"route_id": ctx["route"]["id"]},
                                TEST_USERS["dispatcher_headers"])
    assert fx.get_weather_reading(wr["id"])["processed"] is True


# =====================================================================
# resource_temporal_overlap / route_reopen_blocked_while_dispatch_in_flight
# =====================================================================

def test_route_reopen_blocked_with_dispatched_visit(api):
    """PRD §3.3: "a route that has been dispatched can be reopened from `DISPATCHED` back to `OPEN` — but reopening is permitted only when no service visit on the route is still in `DISPATCHED` state."

    After weather processing fans out a still-DISPATCHED SNOW visit, reopen is rejected
    with ERR_INVALID_STATE and the route stays DISPATCHED.

    Design: Difficulty/resource_temporal_overlap/route_reopen_blocked_while_dispatch_in_flight
    """
    ctx = fx.setup_full_dispatch_ready(
        zip="10606",
        contract_overrides={"contract_price_cents": 10000, "term_months": 3},
        equipment_overrides={"equipment_type": "PLOW", "age_months": 5},
    )
    wr = fx.make_weather_reading(region_zip="10606", snow_depth_in=3.0,
                                 observed_at="2026-01-13T06:00:00Z")
    api.process_weather_reading(wr["id"], {"route_id": ctx["route"]["id"]},
                                TEST_USERS["dispatcher_headers"])
    resp = api.reopen_route(ctx["route"]["id"], TEST_USERS["dispatcher_headers"])
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    assert fx.get_route(ctx["route"]["id"])["status"] == "DISPATCHED"


def test_route_stays_dispatched_when_reopen_blocked(api):
    """PRD §3.3: "reopening is permitted only when no service visit on the route is still in `DISPATCHED` state."

    The blocked reopen leaves the route in DISPATCHED (no state change on rejection).

    Design: Difficulty/resource_temporal_overlap/route_reopen_blocked_while_dispatch_in_flight
    """
    ctx = fx.setup_full_dispatch_ready(
        zip="10606",
        contract_overrides={"contract_price_cents": 10000, "term_months": 3},
        equipment_overrides={"equipment_type": "PLOW", "age_months": 5},
    )
    wr = fx.make_weather_reading(region_zip="10606", snow_depth_in=3.0)
    api.process_weather_reading(wr["id"], {"route_id": ctx["route"]["id"]},
                                TEST_USERS["dispatcher_headers"])
    api.reopen_route(ctx["route"]["id"], TEST_USERS["dispatcher_headers"])
    assert fx.get_route(ctx["route"]["id"])["status"] == "DISPATCHED"
