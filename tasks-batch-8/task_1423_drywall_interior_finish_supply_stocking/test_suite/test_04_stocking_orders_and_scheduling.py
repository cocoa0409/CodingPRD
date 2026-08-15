"""Stocking window gates, boom-truck scheduling guards, slot overlap, lead-time
windows, and order cancellation (PRD §2.8, §3.3, §3.6, §3.7)."""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, TEST_USERS,
    create_account, create_boom_truck, create_product, create_project,
    create_takeoff_with_lines, submit_takeoff, lock_takeoff, open_stocking,
    create_stocking_order_with_drops, schedule_order, set_logical_clock,
    setup_locked_takeoff_scenario, setup_stocking_open_scenario,
    setup_draft_order_scenario, setup_scheduled_order_scenario,
)
from test_helpers import api_client

CM = TEST_USERS["credit_manager_headers"]
EST = TEST_USERS["estimator_headers"]
DISP = TEST_USERS["dispatcher_headers"]
FORE = TEST_USERS["foreman_headers"]

FIRE_PRODUCT = {
    "sku": "FIRE-4x8-5/8", "board_kind": "FIRE_RATED", "thickness_in": "5/8",
    "sheets_per_bundle": 16, "unit_price_cents_per_sheet": 2400, "lead_time_days": 7,
}


# ─── Framing threshold boundary on open-stocking (PRD §3.3) ──────────

def _project_with_locked_takeoff(account_id, product_id, framing_pct):
    project = create_project(account_id, framing_pct_complete=framing_pct)
    takeoff, _ = create_takeoff_with_lines(project["id"], [(product_id, 20)])
    submit_takeoff(takeoff["id"])
    lock_takeoff(takeoff["id"])
    return project


def test_framing_49_blocks_stocking_open(api):
    """PRD §3.3: "Three preconditions guard that transition:
    `framing_pct_complete` must be at least 50 (otherwise
    `ERR_FRAMING_NOT_READY`), the account must be `ACTIVE` (otherwise
    `ERR_ACCOUNT_SUSPENDED`), and the project must already have at least one
    takeoff in `LOCKED` status (otherwise `ERR_NO_LOCKED_TAKEOFF`)."

    49 is one below the inclusive threshold; the locked-takeoff precondition is
    satisfied so the framing rule is isolated.

    Design: Difficulty/boundary_precision_check/framing_pct_50_opens_stocking_49_blocks
    """
    account = create_account(company_name="Boundary Co")
    product = create_product()
    p49 = _project_with_locked_takeoff(account["id"], product["id"], 49)

    res = api_client.open_stocking(p49["id"], FORE)
    validate_error(res, ApiErrorId.ERR_FRAMING_NOT_READY)


def test_framing_50_opens_stocking(api):
    """PRD §3.3: "Three preconditions guard that transition:
    `framing_pct_complete` must be at least 50 (otherwise
    `ERR_FRAMING_NOT_READY`), the account must be `ACTIVE` (otherwise
    `ERR_ACCOUNT_SUSPENDED`), and the project must already have at least one
    takeoff in `LOCKED` status (otherwise `ERR_NO_LOCKED_TAKEOFF`)."

    50 meets the inclusive threshold.

    Design: Difficulty/boundary_precision_check/framing_pct_50_opens_stocking_49_blocks
    """
    account = create_account(company_name="Boundary Co 2")
    product = create_product()
    p50 = _project_with_locked_takeoff(account["id"], product["id"], 50)

    res = api_client.open_stocking(p50["id"], FORE)
    opened = validate_success(res, 200)
    assert opened["status"] == "STOCKING_OPEN"


# ─── Cross-entity gate: schedule requires STOCKING_OPEN (PRD §3.6) ───

def test_schedule_blocked_while_project_in_planning(api):
    """PRD §3.6: "The project must be in `STOCKING_OPEN`
    (`ERR_PROJECT_NOT_STOCKING_OPEN`); the takeoff referenced by the order's
    `takeoff_id` must be `LOCKED` and must belong to the same project
    (`ERR_TAKEOFF_NOT_LOCKED`); the referenced truck must exist and be active
    (`ERR_TRUCK_INACTIVE`); the order must contain at least one drop
    (`ERR_EMPTY_ORDER`); the sum of `bundle_count` across all drops must not
    exceed the truck's `max_bundle_capacity` (`ERR_CAPACITY_EXCEEDED`); and the
    sum of `sheet_weight_lbs` across all drops must not exceed the truck's
    `max_weight_lbs` (`ERR_WEIGHT_EXCEEDED`)."

    The project (framing 60) is otherwise ready but the Foreman never opened
    the stocking window.

    Design: Difficulty/cross_entity_state_dependency/stocking_order_schedule_blocked_when_project_not_open
    """
    set_logical_clock()
    ctx = setup_locked_takeoff_scenario(
        account_overrides={"company_name": "Gate Co"})
    truck = create_boom_truck(truck_code="BT-01")
    order, _drops = create_stocking_order_with_drops(
        ctx["project"]["id"], ctx["takeoff"]["id"], truck["id"],
        [(ctx["product"]["id"], 1)])

    res = api_client.schedule_stocking_order(order["id"], DISP)
    validate_error(res, ApiErrorId.ERR_PROJECT_NOT_STOCKING_OPEN)


def test_schedule_succeeds_after_stocking_opened(api):
    """PRD §3.6: "Scheduling moves the order from `DRAFT` to `SCHEDULED` and is
    the most heavily guarded transition in the system."
    PRD §3.3: "Opening stocking unblocks stocking-order creation for the
    project."

    Once the Foreman opens the window, the same schedule call succeeds.

    Design: Difficulty/cross_entity_state_dependency/stocking_order_schedule_blocked_when_project_not_open
    """
    set_logical_clock()
    ctx = setup_locked_takeoff_scenario(
        account_overrides={"company_name": "Gate Co 2"})
    truck = create_boom_truck(truck_code="BT-01")
    order, _drops = create_stocking_order_with_drops(
        ctx["project"]["id"], ctx["takeoff"]["id"], truck["id"],
        [(ctx["product"]["id"], 1)])

    open_stocking(ctx["project"]["id"])
    scheduled = schedule_order(order["id"])
    assert scheduled["status"] == "SCHEDULED"


# ─── Half-day slot overlap (PRD §3.6) ────────────────────────────────

def test_same_truck_same_date_same_shift_rejected(api):
    """PRD §3.6: "First, the half-day slot must be free: no other stocking
    order in `SCHEDULED` or `DISPATCHED` may hold the same combination of
    `boom_truck_id`, `scheduled_date`, and `shift_window` — each reservation
    occupies the half-open interval from shift start to shift end, so
    back-to-back `AM` and `PM` bookings on one truck are legal but overlapping
    ones are rejected with `ERR_SHIFT_DOUBLE_BOOKED`."

    Design: Difficulty/resource_temporal_overlap/same_truck_same_shift_rejected
    """
    ctx = setup_scheduled_order_scenario(
        account_overrides={"company_name": "Overlap Co", "credit_limit_cents": 9000000},
        truck_overrides={"truck_code": "BT-01"})
    assert ctx["order"]["status"] == "SCHEDULED"

    order2, _ = create_stocking_order_with_drops(
        ctx["project"]["id"], ctx["takeoff"]["id"], ctx["truck"]["id"],
        [(ctx["product"]["id"], 1)], scheduled_date="2026-08-02", shift_window="AM")
    res = api_client.schedule_stocking_order(order2["id"], DISP)
    validate_error(res, ApiErrorId.ERR_SHIFT_DOUBLE_BOOKED)


def test_same_truck_same_date_pm_shift_allowed(api):
    """PRD §3.6: "First, the half-day slot must be free: no other stocking
    order in `SCHEDULED` or `DISPATCHED` may hold the same combination of
    `boom_truck_id`, `scheduled_date`, and `shift_window` — each reservation
    occupies the half-open interval from shift start to shift end, so
    back-to-back `AM` and `PM` bookings on one truck are legal but overlapping
    ones are rejected with `ERR_SHIFT_DOUBLE_BOOKED`."

    The PM window on the same truck and date is a disjoint half-open interval.

    Design: Difficulty/resource_temporal_overlap/same_truck_same_shift_rejected
    """
    ctx = setup_scheduled_order_scenario(
        account_overrides={"company_name": "Overlap Co 2", "credit_limit_cents": 9000000},
        truck_overrides={"truck_code": "BT-01"})

    order3, _ = create_stocking_order_with_drops(
        ctx["project"]["id"], ctx["takeoff"]["id"], ctx["truck"]["id"],
        [(ctx["product"]["id"], 1)], scheduled_date="2026-08-02", shift_window="PM")
    scheduled = schedule_order(order3["id"])
    assert scheduled["status"] == "SCHEDULED"


# ─── Rated-product lead-time window (PRD §3.6) ───────────────────────

def _setup_rated_order_ctx(scheduled_date):
    return setup_draft_order_scenario(
        account_overrides={"company_name": "Lead Co", "credit_limit_cents": 9000000},
        product_overrides=dict(FIRE_PRODUCT),
        sheet_count=32, bundle_count=2,
        truck_overrides={"truck_code": "BT-01"},
        scheduled_date=scheduled_date)


def test_rated_order_scheduled_before_lead_time_rejected(api):
    """PRD §3.6: "Second, the `scheduled_date` must respect procurement lead
    time: it must fall no earlier than today plus the maximum `lead_time_days`
    among the products on the order's drops that are `FIRE_RATED` or
    `MOISTURE_RATED`, while an order carrying only `REGULAR` product merely
    requires a `scheduled_date` of today or later — violations are rejected
    with `ERR_LEAD_TIME_VIOLATION`."

    Clock at 2026-08-01, FIRE_RATED lead time 7 days: 2026-08-06 is today + 5,
    inside the procurement window.

    Design: Difficulty/resource_temporal_overlap/lead_time_window_blocks_early_schedule_for_rated_product
    """
    ctx = _setup_rated_order_ctx("2026-08-06")
    res = api_client.schedule_stocking_order(ctx["order"]["id"], DISP)
    validate_error(res, ApiErrorId.ERR_LEAD_TIME_VIOLATION)


def test_rated_order_scheduled_at_lead_time_boundary_allowed(api):
    """PRD §3.6: "Second, the `scheduled_date` must respect procurement lead
    time: it must fall no earlier than today plus the maximum `lead_time_days`
    among the products on the order's drops that are `FIRE_RATED` or
    `MOISTURE_RATED`, while an order carrying only `REGULAR` product merely
    requires a `scheduled_date` of today or later — violations are rejected
    with `ERR_LEAD_TIME_VIOLATION`."

    Clock at 2026-08-01, FIRE_RATED lead time 7 days: 2026-08-08 is exactly
    today + 7, the inclusive lower bound of the legal window.

    Design: Difficulty/resource_temporal_overlap/lead_time_window_blocks_early_schedule_for_rated_product
    """
    ctx = _setup_rated_order_ctx("2026-08-08")
    scheduled = schedule_order(ctx["order"]["id"])
    assert scheduled["status"] == "SCHEDULED"


# ─── Priority pair: state guard vs business-temporal (PRD §2.8) ──────

def test_schedule_cancelled_order_with_lead_time_violation_reports_state_error(api):
    """PRD §2.8: "The order is: authentication (`ERR_UNAUTHENTICATED`) first,
    then authorization (`ERR_FORBIDDEN`), then path resolution
    (`ERR_NOT_FOUND`), then the account-posture guard
    (`ERR_ACCOUNT_SUSPENDED`), then generic state guards
    (`ERR_INVALID_STATE`), and only then the business rules."

    The order is CANCELLED (state guard fails) AND its 2026-08-01 date violates
    the 7-day rated lead time (business-temporal fails); the state guard
    reports first.

    Design: Difficulty/priority_pair_validation_conflict/state_vs_business_temporal_on_schedule
    """
    ctx = _setup_rated_order_ctx("2026-08-01")
    validate_success(api_client.cancel_stocking_order(ctx["order"]["id"], DISP), 200)

    res = api_client.schedule_stocking_order(ctx["order"]["id"], DISP)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)


def test_schedule_cancelled_order_reports_state_error_regardless_of_business_rules(api):
    """PRD §2.8: "The order is: authentication (`ERR_UNAUTHENTICATED`) first,
    then authorization (`ERR_FORBIDDEN`), then path resolution
    (`ERR_NOT_FOUND`), then the account-posture guard
    (`ERR_ACCOUNT_SUSPENDED`), then generic state guards
    (`ERR_INVALID_STATE`), and only then the business rules."

    Same pair, different margin: the CANCELLED order carries a FIRE_RATED drop
    dated today + 3 (still inside the 7-day lead window), so the
    business-temporal rule fails too — the state guard still wins.

    Design: Difficulty/priority_pair_validation_conflict/state_vs_business_temporal_on_schedule
    """
    ctx = _setup_rated_order_ctx("2026-08-04")
    validate_success(api_client.cancel_stocking_order(ctx["order"]["id"], DISP), 200)

    res = api_client.schedule_stocking_order(ctx["order"]["id"], DISP)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)


# ─── Order cancellation releases the slot (PRD §3.6) ─────────────────

def test_scheduled_order_cancel_lands_in_cancelled(api):
    """PRD §3.6: "Cancelling an order is a `DispatcherUser` action available
    from `DRAFT` or `SCHEDULED`. Cancelling a draft releases nothing — the
    reservation is a no-op because none exists yet — while cancelling a
    scheduled order releases its truck-date-shift reservation for others to
    claim. Both land the order in terminal `CANCELLED`."

    Design: Difficulty/non_linear_state_machine/stocking_order_cancel_from_scheduled_releases_slot
    """
    ctx = setup_scheduled_order_scenario(
        account_overrides={"company_name": "SM2 Co"},
        truck_overrides={"truck_code": "BT-01"})
    res = api_client.cancel_stocking_order(ctx["order"]["id"], DISP)
    cancelled = validate_success(res, 200)
    assert cancelled["status"] == "CANCELLED"


def test_cancelled_scheduled_order_slot_can_be_reused(api):
    """PRD §3.6: "Cancelling an order is a `DispatcherUser` action available
    from `DRAFT` or `SCHEDULED`. Cancelling a draft releases nothing — the
    reservation is a no-op because none exists yet — while cancelling a
    scheduled order releases its truck-date-shift reservation for others to
    claim. Both land the order in terminal `CANCELLED`."

    After the SCHEDULED order is cancelled, a fresh order takes the identical
    (truck, date, shift) slot.

    Design: Difficulty/non_linear_state_machine/stocking_order_cancel_from_scheduled_releases_slot
    """
    ctx = setup_scheduled_order_scenario(
        account_overrides={"company_name": "SM2 Co 2"},
        truck_overrides={"truck_code": "BT-01"})
    validate_success(api_client.cancel_stocking_order(ctx["order"]["id"], DISP), 200)

    order2, _ = create_stocking_order_with_drops(
        ctx["project"]["id"], ctx["takeoff"]["id"], ctx["truck"]["id"],
        [(ctx["product"]["id"], 1)], scheduled_date="2026-08-02", shift_window="AM")
    scheduled = schedule_order(order2["id"])
    assert scheduled["status"] == "SCHEDULED"


# ─── Scheduling guard violations (PRD §3.6) ──────────────────────────

def test_schedule_with_excess_bundles_rejected(api):
    """PRD §3.6: "The project must be in `STOCKING_OPEN`
    (`ERR_PROJECT_NOT_STOCKING_OPEN`); the takeoff referenced by the order's
    `takeoff_id` must be `LOCKED` and must belong to the same project
    (`ERR_TAKEOFF_NOT_LOCKED`); the referenced truck must exist and be active
    (`ERR_TRUCK_INACTIVE`); the order must contain at least one drop
    (`ERR_EMPTY_ORDER`); the sum of `bundle_count` across all drops must not
    exceed the truck's `max_bundle_capacity` (`ERR_CAPACITY_EXCEEDED`); and the
    sum of `sheet_weight_lbs` across all drops must not exceed the truck's
    `max_weight_lbs` (`ERR_WEIGHT_EXCEEDED`)."

    Truck capacity 2 bundles; the order drops total 3 bundles.

    Design: Corner/validations/capacity_exceeded_rejected
    """
    ctx = setup_draft_order_scenario(
        account_overrides={"company_name": "Cap Co"},
        truck_overrides={"truck_code": "BT-SM", "max_bundle_capacity": 2},
        bundle_count=3)
    res = api_client.schedule_stocking_order(ctx["order"]["id"], DISP)
    validate_error(res, ApiErrorId.ERR_CAPACITY_EXCEEDED)


def test_schedule_empty_order_rejected(api):
    """PRD §3.6: "The project must be in `STOCKING_OPEN`
    (`ERR_PROJECT_NOT_STOCKING_OPEN`); the takeoff referenced by the order's
    `takeoff_id` must be `LOCKED` and must belong to the same project
    (`ERR_TAKEOFF_NOT_LOCKED`); the referenced truck must exist and be active
    (`ERR_TRUCK_INACTIVE`); the order must contain at least one drop
    (`ERR_EMPTY_ORDER`); the sum of `bundle_count` across all drops must not
    exceed the truck's `max_bundle_capacity` (`ERR_CAPACITY_EXCEEDED`); and the
    sum of `sheet_weight_lbs` across all drops must not exceed the truck's
    `max_weight_lbs` (`ERR_WEIGHT_EXCEEDED`)."

    The order carries zero drops.

    Design: Corner/validations/empty_order_schedule_rejected
    """
    ctx = setup_stocking_open_scenario(
        account_overrides={"company_name": "EO Co"})
    res_order = api_client.create_stocking_order(
        {"project_id": ctx["project"]["id"], "takeoff_id": ctx["takeoff"]["id"],
         "scheduled_date": "2026-08-02", "shift_window": "AM",
         "boom_truck_id": ctx["truck"]["id"]}, DISP)
    order = validate_success(res_order, 201)

    res = api_client.schedule_stocking_order(order["id"], DISP)
    validate_error(res, ApiErrorId.ERR_EMPTY_ORDER)


def test_schedule_against_inactive_truck_rejected(api):
    """PRD §3.2: "Trucks are created with `active` true, and capacity figures
    or the `active` flag can be patched later; an inactive truck cannot be
    reserved for any new order."
    PRD §3.6: "The project must be in `STOCKING_OPEN`
    (`ERR_PROJECT_NOT_STOCKING_OPEN`); the takeoff referenced by the order's
    `takeoff_id` must be `LOCKED` and must belong to the same project
    (`ERR_TAKEOFF_NOT_LOCKED`); the referenced truck must exist and be active
    (`ERR_TRUCK_INACTIVE`); the order must contain at least one drop
    (`ERR_EMPTY_ORDER`); the sum of `bundle_count` across all drops must not
    exceed the truck's `max_bundle_capacity` (`ERR_CAPACITY_EXCEEDED`); and the
    sum of `sheet_weight_lbs` across all drops must not exceed the truck's
    `max_weight_lbs` (`ERR_WEIGHT_EXCEEDED`)."

    Design: Corner/errors/err_truck_inactive_on_schedule
    """
    ctx = setup_stocking_open_scenario(
        account_overrides={"company_name": "Inact Co"})
    validate_success(api_client.update_boom_truck(ctx["truck"]["id"], {"active": False}, DISP), 200)
    order, _ = create_stocking_order_with_drops(
        ctx["project"]["id"], ctx["takeoff"]["id"], ctx["truck"]["id"],
        [(ctx["product"]["id"], 1)])

    res = api_client.schedule_stocking_order(order["id"], DISP)
    validate_error(res, ApiErrorId.ERR_TRUCK_INACTIVE)


# ─── Dispatch guards (PRD §3.7) ──────────────────────────────────────

def test_dispatch_from_draft_rejected(api):
    """PRD §3.7: "The order must be `SCHEDULED`, today per the logical clock
    must equal the order's `scheduled_date` (dispatching on any other date is
    rejected with `ERR_NOT_DISPATCH_DAY`), and the project must still be
    `STOCKING_OPEN`."
    PRD §2.8: "The order is: authentication (`ERR_UNAUTHENTICATED`) first, then
    authorization (`ERR_FORBIDDEN`), then path resolution (`ERR_NOT_FOUND`),
    then the account-posture guard (`ERR_ACCOUNT_SUSPENDED`), then generic
    state guards (`ERR_INVALID_STATE`), and only then the business rules."

    A DRAFT order cannot jump straight to DISPATCHED; the generic state guard
    reports before the dispatch-day business rule.

    Design: Corner/state_machines/invalid_transition_dispatch_from_draft
    """
    ctx = setup_draft_order_scenario(
        account_overrides={"company_name": "IT Co"})
    res = api_client.dispatch_stocking_order(ctx["order"]["id"], DISP)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)


def test_dispatch_on_wrong_day_rejected(api):
    """PRD §3.7: "The order must be `SCHEDULED`, today per the logical clock
    must equal the order's `scheduled_date` (dispatching on any other date is
    rejected with `ERR_NOT_DISPATCH_DAY`), and the project must still be
    `STOCKING_OPEN`."

    Order scheduled for 2026-08-05; the clock stands at 2026-08-03.

    Design: Corner/validations/dispatch_wrong_day_rejected
    """
    ctx = setup_scheduled_order_scenario(
        account_overrides={"company_name": "DD Co"},
        scheduled_date="2026-08-05")
    set_logical_clock("2026-08-03T08:00:00Z")

    res = api_client.dispatch_stocking_order(ctx["order"]["id"], DISP)
    validate_error(res, ApiErrorId.ERR_NOT_DISPATCH_DAY)


# ─── Sub-resource drop listing (PRD §4) ──────────────────────────────

def test_list_drops_on_order_without_drops_returns_empty_array(api, dispatcher_headers):
    """PRD §2.2: "The `response_type` is either "object" for a single resource
    or "array" for a list of resources."
    PRD §2.3: "All list endpoints accept two query parameters, `limit` and
    `offset`. The `limit` parameter defaults to 10, must be at least 1, and may
    not exceed 100. The `offset` parameter defaults to 0."

    The drops sub-resource list of a freshly created order is an empty array.

    Design: Corner/endpoints/sub_resource_list_drops_on_order
    """
    ctx = setup_stocking_open_scenario(
        account_overrides={"company_name": "Sub Co"})
    res_order = api_client.create_stocking_order(
        {"project_id": ctx["project"]["id"], "takeoff_id": ctx["takeoff"]["id"],
         "scheduled_date": "2026-08-02", "shift_window": "AM",
         "boom_truck_id": ctx["truck"]["id"]}, DISP)
    order = validate_success(res_order, 201)

    res = api_client.list_order_drops(order["id"], dispatcher_headers)
    data, _meta = validate_paginated(res)
    assert data == [], f"Expected an empty drop list, got {data}"
