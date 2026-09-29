"""Thresholds probed one unit either side of the value that just qualifies."""

from test_helpers import (
    CLERK,
    FUN_SLIDE,
    GIANT_WHEEL,
    KIDDIE_CARS,
    LOT_BOSS,
    TILT_A_WHIRL,
    ApiErrorId,
    assert_instant_equals,
    assert_lot_ledgers,
    assert_ride_allocation,
    assert_settlement,
    assert_settlement_amounts,
    build_settlement,
    create_ride_allocation_payload,
    current_stop_version,
    dispute_settlement,
    file_permit,
    read_route_stop,
    reconcile_settlement,
    record_sale,
    register_ride,
    reserve_allocation,
    set_logical_clock,
    setup_planned_lot,
    setup_planned_lot_with_allocations,
    setup_open_lot_with_sales,
    validate_error,
    validate_paginated,
    validate_success,
)

HOOSIER_STATE = {
    "state_code": "IN",
    "name": "Indiana",
    "permit_lead_days": 0,
    "amusement_tax_pct": 0,
    "permit_fee_cents": 0,
    "max_consecutive_work_days": 6,
    "requires_state_ride_inspection": False,
}
HOOSIER_LOT = {"name": "Hoosier Fairgrounds", "city": "Indianapolis"}
PLAIN_TILT = dict(TILT_A_WHIRL, requires_state_inspection=False)
BOONE_OPERATOR = {
    "full_name": "Boone Operator",
    "employment_type": "PERMANENT",
    "hourly_rate_cents": 2000,
    "certified_ride_classes": ["FLAT"],
    "housing_required": False,
}
TIER_EDGE_DEAL = {
    "counterparty_name": "Indiana State Fair Board",
    "revenue_split_pct_operator": 65,
    "guarantee_cents": 0,
    "ride_minimum_count": 0,
    "exclusivity": "NONE",
    "settlement_basis": "SPLIT_ONLY",
}
ONE_CENT_UNDER_THE_TIER = [
    {
        "channel": "WRISTBAND",
        "units": 400,
        "unit_price_cents": 4999,
        "business_date": "2026-09-04T18:00:00Z",
    },
    {
        "channel": "SINGLE",
        "units": 399,
        "unit_price_cents": 1,
        "business_date": "2026-09-04T19:00:00Z",
    },
]
DISPUTE_REASON = "One single-admission scan was rung after the drawer close."

TRANSPORT_VALID_FROM = "2026-09-01T00:00:00Z"
TRANSPORT_VALID_UNTIL = "2026-09-09T00:00:00Z"
EVENT_VALID_FROM = "2026-09-04T00:00:00Z"
EVENT_VALID_UNTIL = "2026-09-08T00:00:00Z"
CLOCK_EXACTLY_TEN_DAYS_OUT = "2026-08-25T12:00:00Z"
CLOCK_ONE_SECOND_LATER = "2026-08-25T12:00:01Z"

WIDE_SERVICE_LOT = {
    "name": "Union County Fairgrounds",
    "city": "Marysville",
    "lot_area_sqft": 200000,
    "power_amps_available": 1000,
    "expected_attendance": 10001,
    "lot_surface": "PAVED",
    "housing_pads_available": 2,
}
POWER_LADDER = [GIANT_WHEEL, TILT_A_WHIRL]


def _settlement_one_cent_under_the_tier():
    """An OPEN lot in a tax-free state whose takings land one cent short of a tier."""
    ctx = setup_open_lot_with_sales(
        sale_specs=ONE_CENT_UNDER_THE_TIER,
        contract_overrides=TIER_EDGE_DEAL,
        ride_specs=[PLAIN_TILT],
        worker_specs=[BOONE_OPERATOR],
        jurisdiction_overrides=HOOSIER_STATE,
        venue_overrides=HOOSIER_LOT,
    )
    ctx["settlement"] = build_settlement(ctx["contract"]["id"])
    return ctx


def _two_draft_permits_on_a_planned_lot():
    """A PLANNED lot in a ten-day state carrying two DRAFT permits."""
    ctx = setup_planned_lot()
    ctx["transport_permit"] = file_permit(
        ctx["stop"]["id"],
        "TRANSPORT",
        TRANSPORT_VALID_FROM,
        TRANSPORT_VALID_UNTIL,
        axles_declared=4,
    )
    ctx["event_permit"] = file_permit(
        ctx["stop"]["id"], "EVENT", EVENT_VALID_FROM, EVENT_VALID_UNTIL
    )
    return ctx


def _lot_drawing_five_hundred_and_thirteen_amps():
    """A wide-service lot carrying a major and a flat unit, well under both budgets."""
    return setup_planned_lot_with_allocations(
        ride_specs=POWER_LADDER, venue_overrides=WIDE_SERVICE_LOT
    )


def test_a_net_one_cent_short_of_the_tier_earns_no_bonus(api):
    """PRD §3.8: "**Volume tier on the post-tax net.** The tier bonus is measured
    against the taxable net, with inclusive lower bounds: a net of at least 5,000,000
    cents earns a bonus of 5.0 percentage points; otherwise a net of at least 2,000,000
    cents earns 2.5 percentage points; otherwise the bonus is 0.
    `effective_operator_pct` is the deal's `revenue_split_pct_operator` plus that bonus,
    capped at 72.5 — whichever is smaller."

    PRD §3.8: "**Split share.** `split_share_cents` is `taxable_net_cents` multiplied
    by `effective_operator_pct` divided by 100, rounded half-up to whole cents."

    Design: Difficulty/boundary_precision_check/split_tier_lower_bound_is_inclusive_at_exactly_two_million_net_cents
    """
    ctx = _settlement_one_cent_under_the_tier()
    settlement = ctx["settlement"]
    assert_settlement(settlement)

    assert settlement["effective_operator_pct"] == 65
    assert settlement["effective_operator_pct"] != 72.5, (
        "a single tier bonus never reaches the operator cap"
    )
    assert_settlement_amounts(
        settlement,
        gross_cents=1999999,
        tax_cents=0,
        taxable_net_cents=1999999,
        split_share_cents=1299999,
        settlement_due_cents=1299999,
    )


def test_the_tier_fires_on_a_net_exactly_equal_to_its_lower_bound(api):
    """PRD §3.8: "**Volume tier on the post-tax net.** The tier bonus is measured
    against the taxable net, with inclusive lower bounds: a net of at least 5,000,000
    cents earns a bonus of 5.0 percentage points; otherwise a net of at least 2,000,000
    cents earns 2.5 percentage points; otherwise the bonus is 0.
    `effective_operator_pct` is the deal's `revenue_split_pct_operator` plus that bonus,
    capped at 72.5 — whichever is smaller."

    PRD §3.8: "A `TicketingAuditor` then reconciles it (`DISPUTED → PROVISIONAL`),
    re-running the provisional variant over the sales rows as they now stand,
    overwriting every computed amount on the same row and clearing `dispute_reason`
    back to null."

    Design: Difficulty/boundary_precision_check/split_tier_lower_bound_is_inclusive_at_exactly_two_million_net_cents
    """
    ctx = _settlement_one_cent_under_the_tier()
    settlement_id = ctx["settlement"]["id"]

    dispute_settlement(settlement_id, DISPUTE_REASON)
    record_sale(ctx["stop"]["id"], "SINGLE", 1, 1, "2026-09-04T19:05:00Z")

    reconciled = reconcile_settlement(settlement_id)
    assert reconciled["id"] == settlement_id
    assert reconciled["taxable_net_cents"] == 2000000
    assert reconciled["effective_operator_pct"] == 67.5
    assert_settlement_amounts(
        reconciled,
        gross_cents=2000000,
        tax_cents=0,
        taxable_net_cents=2000000,
        split_share_cents=1350000,
        settlement_due_cents=1350000,
    )
    assert reconciled["effective_operator_pct"] != 72.5


def test_a_permit_filed_exactly_the_required_days_out_is_admitted(api):
    """PRD §3.4: "**Submitting** a permit (`DRAFT → SUBMITTED`) is also a
    `ComplianceClerk` action, admitted while the lot is `PLANNED`, `CONFIRMED` or
    `SETUP`, and it is where the lead-time rule bites. The number of whole days from
    the logical clock to the lot's `open_date` — the elapsed seconds divided by one day
    and rounded **down** to a whole number — must be at least the jurisdiction's
    `permit_lead_days`; filing exactly that many whole days ahead is admitted, and
    filing any later is refused with `ERR_PERMIT_LEAD_TIME_VIOLATION`."

    PRD §3.4: "Submission stamps `submitted_at` from the logical clock."

    Design: Difficulty/boundary_precision_check/permit_lead_time_floor_admits_exact_equality_then_fails_one_second_later
    """
    ctx = _two_draft_permits_on_a_planned_lot()
    assert ctx["transport_permit"]["status"] == "DRAFT"

    set_logical_clock(CLOCK_EXACTLY_TEN_DAYS_OUT)
    admitted = validate_success(
        api.submit_permit_application(ctx["transport_permit"]["id"], CLERK)
    )
    assert admitted["status"] == "SUBMITTED"
    assert_instant_equals(
        admitted["submitted_at"], CLOCK_EXACTLY_TEN_DAYS_OUT, "submitted_at"
    )


def test_one_second_past_the_floor_drops_the_whole_day_count_and_refuses(api):
    """PRD §3.4: "The number of whole days from the logical clock to the lot's
    `open_date` — the elapsed seconds divided by one day and rounded **down** to a whole
    number — must be at least the jurisdiction's `permit_lead_days`; filing exactly that
    many whole days ahead is admitted, and filing any later is refused with
    `ERR_PERMIT_LEAD_TIME_VIOLATION`."

    PRD §3.4: "A new permit sits in `DRAFT` with `submitted_at`, `decided_at` and
    `denial_reason` all null."

    Design: Difficulty/boundary_precision_check/permit_lead_time_floor_admits_exact_equality_then_fails_one_second_later
    """
    ctx = _two_draft_permits_on_a_planned_lot()
    stop_id = ctx["stop"]["id"]

    set_logical_clock(CLOCK_EXACTLY_TEN_DAYS_OUT)
    validate_success(api.submit_permit_application(ctx["transport_permit"]["id"], CLERK))

    set_logical_clock(CLOCK_ONE_SECOND_LATER)
    validate_error(
        api.submit_permit_application(ctx["event_permit"]["id"], CLERK),
        ApiErrorId.ERR_PERMIT_LEAD_TIME_VIOLATION.value,
        expected_status=422,
    )

    rows, _meta = validate_paginated(
        api.list_route_stop_permit_applications(stop_id, CLERK)
    )
    refused = next(row for row in rows if row["id"] == ctx["event_permit"]["id"])
    assert refused["status"] == "DRAFT"
    assert refused["submitted_at"] is None

    _submitted, submitted_meta = validate_paginated(
        api.list_route_stop_permit_applications(
            stop_id, CLERK, params={"status": "SUBMITTED"}
        )
    )
    assert submitted_meta["total_count"] == 1


def test_the_amperage_budget_admits_a_total_exactly_on_the_ceiling(api):
    """PRD §3.3: "The amperage budget is 90 percent of `power_amps_available`, rounded
    half-up to one decimal place, and if the lot's existing `power_amps_used` plus the
    candidate's charged amperage exceeds it the reservation is refused with
    `ERR_LOT_POWER_EXCEEDED`, again with exact equality admitted."

    PRD §3.3: "Its **charged amperage**, `power_charged_amps`, is its `power_amps`
    inflated by a startup surge of 25 percent for `MAJOR`, 15 percent for `FLAT` and
    none at all for `KIDDIE`, rounded half-up to one decimal place."

    Design: Difficulty/boundary_precision_check/lot_power_headroom_admits_exact_equality_then_rejects_one_more_amp
    """
    ctx = _lot_drawing_five_hundred_and_thirteen_amps()
    stop_id = ctx["stop"]["id"]
    assert_lot_ledgers(read_route_stop(stop_id), 7818, 513.0)

    slide = register_ride(FUN_SLIDE)
    on_the_ceiling = reserve_allocation(slide["id"], stop_id)
    assert_ride_allocation(on_the_ceiling)
    assert on_the_ceiling["power_charged_amps"] == 387.0
    assert on_the_ceiling["footprint_charged_sqft"] == 552

    assert_lot_ledgers(read_route_stop(stop_id), 8370, 900.0)


def test_one_more_amp_over_the_ceiling_is_refused_on_power_not_footprint(api):
    """PRD §3.3: "The amperage budget is 90 percent of `power_amps_available`, rounded
    half-up to one decimal place, and if the lot's existing `power_amps_used` plus the
    candidate's charged amperage exceeds it the reservation is refused with
    `ERR_LOT_POWER_EXCEEDED`, again with exact equality admitted."

    PRD §3.3: "If the lot's existing `allocated_sqft_used` plus the candidate's charged
    footprint exceeds that usable area, the reservation is refused with
    `ERR_LOT_CAPACITY_EXCEEDED`; a total exactly equal to the usable area is admitted."

    PRD §2.10: "The **power ledger**, `power_amps_used`, is the sum of
    `power_charged_amps` over that same status set, rounded to one decimal place."

    Design: Difficulty/boundary_precision_check/lot_power_headroom_admits_exact_equality_then_rejects_one_more_amp
    """
    ctx = _lot_drawing_five_hundred_and_thirteen_amps()
    stop_id = ctx["stop"]["id"]
    slide = register_ride(FUN_SLIDE)
    reserve_allocation(slide["id"], stop_id)

    one_amp = register_ride(KIDDIE_CARS)
    validate_error(
        api.create_ride_allocation(
            create_ride_allocation_payload(
                one_amp["id"], stop_id, current_stop_version(stop_id)
            ),
            LOT_BOSS,
        ),
        ApiErrorId.ERR_LOT_POWER_EXCEEDED.value,
        expected_status=422,
    )

    assert_lot_ledgers(read_route_stop(stop_id), 8370, 900.0)
    _rows, meta = validate_paginated(
        api.list_ride_allocations(LOT_BOSS, params={"ride_id": one_amp["id"]})
    )
    assert meta["total_count"] == 0
