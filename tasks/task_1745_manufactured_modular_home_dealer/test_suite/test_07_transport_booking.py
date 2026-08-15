"""Transport booking: quotes, escorts, crew capability and window capacity (PRD §2.8, §3.6)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_booked_dates,
    assert_transport_job,
    book_transport,
    canonical_community_scenario,
    create_application,
    create_crew,
    create_transport_job_payload,
    create_unit,
    decide_application,
    get_success_data,
    new_order_scenario,
    progress_to_financing_approved,
    progress_to_site_approved,
    set_clock,
    submit_application,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
CONSULTANT = TEST_USERS["consultant_headers"]
COORDINATOR = TEST_USERS["coordinator_headers"]


def _financing_approved_scenario(price=4_200_000, placement="PRIVATE_LAND", double_wide=False, model_overrides=None, options=None):
    scn = new_order_scenario(
        placement_type=placement,
        agreed_home_price_cents=price,
        double_wide=double_wide,
        model_overrides=model_overrides,
        options=options,
    )
    progress_to_financing_approved(scn)
    return scn


# --- quote composition --------------------------------------------------------

def test_transport_quote_multiwide_with_escorts_and_overage(api, consultant_headers):
    """PRD §3.6: "The quote is computed at booking into `quoted_cost_cents` and
    copied onto the order's `transport_charge_cents`, always in exact integer
    cents: the base haul is `sections_count` times `distance_miles` times $2.50
    per mile per section (250 cents); the escort term is `escort_vehicle_count`
    times `distance_miles` times $1.50 per mile (150 cents), charged only when
    `escort_required` is true; a multiwide flat of $1,500.00 (150,000 cents)
    applies when the job has two or more sections; mileage beyond the first 100
    free miles is charged at $0.90 per mile (90 cents); and a weekend flat of
    $500.00 (50,000 cents) applies when the `scheduled_start_date` falls on a
    Saturday or Sunday."

    Design: Difficulty/combinatorial_formula/transport_quote_conditional_multi_input
    """
    scn = _financing_approved_scenario(9_200_000, "COMMUNITY_LOT", double_wide=True, options=[
        {"option_code": "OPT-APP", "description": "Appliance package", "unit_price_cents": 125_050, "quantity": 2},
        {"option_code": "OPT-EXT", "description": "Exterior package", "unit_price_cents": 89_999, "quantity": 1},
    ])
    crew, job = book_transport(scn, distance_miles=180, scheduled_start_date="2026-08-20T08:00:00Z")
    assert_transport_job(job)
    # 2 x 180 x 250 = 90,000 base; 2 x 180 x 150 = 54,000 escort; 150,000
    # multiwide; (180 - 100) x 90 = 7,200 overage; Thursday start -> no weekend.
    assert job["quoted_cost_cents"] == 301_200, f"got {job['quoted_cost_cents']}"
    assert job["escort_required"] is True and job["sections_count"] == 2
    order = get_success_data(api.get_sales_order(scn["order"]["id"], consultant_headers))
    assert order["transport_charge_cents"] == 301_200, "the quote is copied onto the order"


def test_transport_quote_single_wide_weekend_no_overage(api):
    """PRD §3.6: "mileage beyond the first 100 free miles is charged at $0.90 per
    mile (90 cents); and a weekend flat of $500.00 (50,000 cents) applies when
    the `scheduled_start_date` falls on a Saturday or Sunday. The quote is the
    sum of those five terms."

    Design: Difficulty/combinatorial_formula/transport_quote_conditional_multi_input
    """
    scn = _financing_approved_scenario(4_200_000, "PRIVATE_LAND")
    crew, job = book_transport(scn, distance_miles=60, scheduled_start_date="2026-08-22T08:00:00Z")
    # 1 x 60 x 250 = 15,000 base; 60 <= 100 free miles -> no overage; width 13.9
    # -> no escort; 1 section -> no multiwide; Saturday start -> +50,000.
    assert job["quoted_cost_cents"] == 65_000, f"got {job['quoted_cost_cents']}"
    assert job["escort_required"] is False


# --- escort boundary ------------------------------------------------------------

def test_escort_width_exactly_14_requires_one(api):
    """PRD §3.6: "The escort rule is a hard boundary on the model's `width_ft`:
    under 14.0 feet requires no escort; at least 14.0 but under 16.0 requires one
    escort vehicle; 16.0 or more requires two — a width of exactly 14.0 feet
    therefore does require one escort. If the booked `escort_vehicle_count` falls
    short of the required count, booking fails with `ERR_ESCORT_REQUIRED`."

    Design: Difficulty/boundary_precision_check/escort_width_exactly_14
    """
    scn = _financing_approved_scenario(5_500_000, "PRIVATE_LAND", model_overrides={"width_ft": 14.0, "length_ft": 70})
    crew = create_crew(can_set_multiwide=False, max_sections_per_window=2)
    payload = create_transport_job_payload(
        scn["unit"]["id"], crew["id"],
        distance_miles=80, scheduled_start_date="2026-08-20T08:00:00Z", escort_vehicle_count=0,
    )
    resp = api.create_transport_job(scn["order"]["id"], payload, COORDINATOR)
    validate_error(resp, ApiErrorId.ERR_ESCORT_REQUIRED)


def test_escort_width_13_9_exempt_and_quotes(api):
    """PRD §3.6: "under 14.0 feet requires no escort; at least 14.0 but under
    16.0 requires one escort vehicle; 16.0 or more requires two — a width of
    exactly 14.0 feet therefore does require one escort."

    Design: Difficulty/boundary_precision_check/escort_width_exactly_14
    """
    scn = _financing_approved_scenario(4_200_000, "PRIVATE_LAND")  # default model width 13.9
    crew = create_crew(can_set_multiwide=False, max_sections_per_window=2)
    _, job = book_transport(scn, crew=crew, distance_miles=80, scheduled_start_date="2026-08-20T08:00:00Z")
    assert job["escort_required"] is False, "13.9 ft is under the 14.0 threshold"
    # 1 x 80 x 250 = 20,000; no escort term; no multiwide; no overage; Thursday.
    assert job["quoted_cost_cents"] == 20_000, f"got {job['quoted_cost_cents']}"


# --- crew capability and window capacity -----------------------------------------

def test_multiwide_job_requires_certified_crew(api):
    """PRD §3.6: "A crew whose `can_set_multiwide` is false cannot take a job of
    two or more sections (`ERR_CREW_CAPABILITY_INSUFFICIENT`)."

    Design: Corner/validations/multiwide_job_requires_certified_crew
    """
    scn = _financing_approved_scenario(9_200_000, "COMMUNITY_LOT", double_wide=True, options=[
        {"option_code": "OPT-APP", "description": "Appliance package", "unit_price_cents": 125_050, "quantity": 2},
        {"option_code": "OPT-EXT", "description": "Exterior package", "unit_price_cents": 89_999, "quantity": 1},
    ])
    uncertified = create_crew(name="Crew Narrow", crew_size=6, can_set_multiwide=False, max_sections_per_window=4)
    payload = create_transport_job_payload(
        scn["unit"]["id"], uncertified["id"],
        distance_miles=180, scheduled_start_date="2026-08-20T08:00:00Z", escort_vehicle_count=2,
    )
    resp = api.create_transport_job(scn["order"]["id"], payload, COORDINATOR)
    validate_error(resp, ApiErrorId.ERR_CREW_CAPABILITY_INSUFFICIENT)

    certified = create_crew(name="Crew Alpha", can_set_multiwide=True, max_sections_per_window=2)
    _, job = book_transport(scn, crew=certified)
    assert job["status"] == "SCHEDULED", "the certified crew accepts the two-section job"


def test_crew_halfopen_windows_allow_adjacency(api):
    """PRD §3.6: "Crew capacity is enforced per calendar date across a half-open
    move window: the job occupies every date from `scheduled_start_date` up to
    but not including `scheduled_start_date` plus `sections_count` days."
    PRD §3.6: "Because the window is half-open, adjacency is allowed: a job
    ending on a date and another starting that same date do not overlap."

    Design: Difficulty/resource_temporal_overlap/crew_halfopen_weighted_window
    """
    scn_a = _financing_approved_scenario()
    scn_b = _financing_approved_scenario()
    crew = create_crew(can_set_multiwide=False, max_sections_per_window=1)

    _, job_a = book_transport(scn_a, crew=crew, distance_miles=50, scheduled_start_date="2026-08-20T08:00:00Z")
    assert job_a["status"] == "SCHEDULED"
    # Job A occupies [08-20, 08-21): the single section fills 08-20 to capacity 1.
    _, job_b = book_transport(scn_b, crew=crew, distance_miles=50, scheduled_start_date="2026-08-21T08:00:00Z")
    assert job_b["status"] == "SCHEDULED", "adjacent half-open windows do not overlap"


def test_crew_window_conflict_on_overlapping_date(api):
    """PRD §3.6: "For each date in that window, the crew's load is the sum of
    `sections_count` over its other active jobs — statuses `SCHEDULED`,
    `DELAYED`, and `EN_ROUTE` consume capacity — covering that date; if any
    date's load plus the new job's sections exceeds `max_sections_per_window`,
    booking fails with `ERR_CREW_WINDOW_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/crew_halfopen_weighted_window
    """
    scn_a = _financing_approved_scenario()
    scn_c = _financing_approved_scenario()
    crew = create_crew(can_set_multiwide=False, max_sections_per_window=1)

    _, job_a = book_transport(scn_a, crew=crew, distance_miles=50, scheduled_start_date="2026-08-20T08:00:00Z")
    assert job_a["status"] == "SCHEDULED"

    payload = create_transport_job_payload(
        scn_c["unit"]["id"], crew["id"],
        distance_miles=50, scheduled_start_date="2026-08-20T08:00:00Z", escort_vehicle_count=0,
    )
    resp = api.create_transport_job(scn_c["order"]["id"], payload, COORDINATOR)
    validate_error(resp, ApiErrorId.ERR_CREW_WINDOW_CONFLICT)


def test_booking_unit_mismatch_rejected(api):
    """PRD §3.6: "The booking names the `home_unit_id` (which must equal the
    order's own unit, else `ERR_UNIT_ORDER_MISMATCH`), the `crew_id`, an `origin`
    of `FACTORY` or `DEALER_LOT`, the one-way `distance_miles`, a
    `scheduled_start_date` that must not precede the current clock date
    (`ERR_SCHEDULE_IN_PAST`), and the `escort_vehicle_count` booked."

    Design: Corner/validations/booking_unit_mismatch_rejected
    """
    scn = _financing_approved_scenario(9_200_000, "COMMUNITY_LOT", double_wide=True)
    other_unit = create_unit(scn["model"]["id"])
    crew = create_crew()
    payload = create_transport_job_payload(
        other_unit["id"], crew["id"],
        distance_miles=180, scheduled_start_date="2026-08-20T08:00:00Z", escort_vehicle_count=2,
    )
    resp = api.create_transport_job(scn["order"]["id"], payload, COORDINATOR)
    validate_error(resp, ApiErrorId.ERR_UNIT_ORDER_MISMATCH)


# --- order-state gate -------------------------------------------------------------

def test_booking_requires_financing_approved_rejects_early(api):
    """PRD §3.6: "Booking a transport job is a `TransportCoordinator` act against
    an order whose `deal_status` is exactly `FINANCING_APPROVED` — booking in any
    other deal state fails with `ERR_INVALID_STATE`."

    Design: Difficulty/cross_entity_state_dependency/transport_booking_requires_order_financing_approved
    """
    scn = canonical_community_scenario()
    progress_to_site_approved(scn, deposit_cents=473_600)
    create_application(scn)
    submit_application(scn)
    assert scn["order"]["deal_status"] == "PENDING_FINANCING"
    crew = create_crew()

    payload = create_transport_job_payload(
        scn["unit"]["id"], crew["id"],
        distance_miles=180, scheduled_start_date="2026-08-20T08:00:00Z", escort_vehicle_count=2,
    )
    resp = api.create_transport_job(scn["order"]["id"], payload, COORDINATOR)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_booking_succeeds_after_lender_approval(api, consultant_headers):
    """PRD §3.5: "on approval the application moves to `APPROVED`, records the
    agreed `apr_bps`, computes `monthly_payment_cents` as the annuity at that
    approved rate, sets `rate_lock_expires_at` to exactly 14 days after the
    approval instant, stamps `decided_by` with the lender's `X-User-ID`, and
    bubbles the order `PENDING_FINANCING` → `FINANCING_APPROVED`."
    PRD §3.6: "Booking a transport job is a `TransportCoordinator` act against an
    order whose `deal_status` is exactly `FINANCING_APPROVED` — booking in any
    other deal state fails with `ERR_INVALID_STATE`."

    Design: Difficulty/cross_entity_state_dependency/transport_booking_requires_order_financing_approved
    """
    scn = canonical_community_scenario()
    progress_to_site_approved(scn, deposit_cents=473_600)
    create_application(scn)
    submit_application(scn)
    decide_application(scn, "APPROVE", 725)
    assert scn["order"]["deal_status"] == "FINANCING_APPROVED"

    _, job = book_transport(scn, distance_miles=180, scheduled_start_date="2026-08-20T08:00:00Z")
    assert job["status"] == "SCHEDULED"
    assert job["quoted_cost_cents"] == 301_200
    order = get_success_data(api.get_sales_order(scn["order"]["id"], consultant_headers))
    assert order["transport_charge_cents"] == 301_200


# --- validation priority pair: escort (safety) before unit-match (referential) ----

def test_escort_violation_beats_unit_mismatch(api):
    """PRD §2.8: "Incoming requests are validated against the following checks in
    the stated order; the first failing check determines the response."
    PRD §2.8: "`escort_vehicle_count` must meet or exceed the required count for
    the model's width, else `ERR_ESCORT_REQUIRED` (HTTP 422)."
    PRD §2.8: "the job's `home_unit_id` must equal the order's unit, else
    `ERR_UNIT_ORDER_MISMATCH` (HTTP 422)."

    Design: Difficulty/priority_pair_validation_conflict/booking_safety_before_referential
    """
    scn = _financing_approved_scenario(9_200_000, "COMMUNITY_LOT", double_wide=True)
    other_unit = create_unit(scn["model"]["id"])
    crew = create_crew()

    payload = create_transport_job_payload(
        other_unit["id"], crew["id"],
        distance_miles=180, scheduled_start_date="2026-08-20T08:00:00Z", escort_vehicle_count=0,
    )
    resp = api.create_transport_job(scn["order"]["id"], payload, COORDINATOR)
    validate_error(resp, ApiErrorId.ERR_ESCORT_REQUIRED)

    rows, meta = validate_paginated(api.list_order_transport_jobs(scn["order"]["id"], COORDINATOR))
    assert meta["total_count"] == 0 and rows == [], "a rejected booking creates no transport job"


def test_unit_mismatch_surfaces_once_escort_satisfied(api):
    """PRD §2.8: "29. **Unit–order coherence**
    (`POST /api/sales-orders/{id}/transport-jobs`): the job's `home_unit_id` must
    equal the order's unit, else `ERR_UNIT_ORDER_MISMATCH` (HTTP 422)."

    Design: Difficulty/priority_pair_validation_conflict/booking_safety_before_referential
    """
    scn = _financing_approved_scenario(9_200_000, "COMMUNITY_LOT", double_wide=True)
    other_unit = create_unit(scn["model"]["id"])
    crew = create_crew()

    payload = create_transport_job_payload(
        other_unit["id"], crew["id"],
        distance_miles=180, scheduled_start_date="2026-08-20T08:00:00Z", escort_vehicle_count=2,
    )
    resp = api.create_transport_job(scn["order"]["id"], payload, COORDINATOR)
    validate_error(resp, ApiErrorId.ERR_UNIT_ORDER_MISMATCH)


# --- capacity conservation across cancel --------------------------------------------

def test_booking_consumes_crew_window_dates(api):
    """PRD §3.6: "The crew's `booked_dates` is a computed, sorted list of
    calendar dates on which at least one non-terminal transport job consumes
    capacity."

    Design: Difficulty/compensating_invariant/crew_capacity_conservation_across_cancel
    """
    scn = _financing_approved_scenario(9_200_000, "COMMUNITY_LOT", double_wide=True)
    crew, job = book_transport(scn, distance_miles=180, scheduled_start_date="2026-08-20T08:00:00Z")
    assert job["sections_count"] == 2
    crew_view = get_success_data(api.get_transport_crew(crew["id"], ADMIN))
    assert_booked_dates(crew_view, ["2026-08-20", "2026-08-21"])


def test_cancel_restores_capacity_and_allows_rebooking(api):
    """PRD §3.6: "A job still in `SCHEDULED` or `DELAYED` may instead be
    cancelled outright — by the coordinator, or by the order-cancellation
    cascade — landing in `CANCELLED` with the crew's `booked_dates` recomputed so
    its sections stop consuming capacity."

    Design: Difficulty/compensating_invariant/crew_capacity_conservation_across_cancel
    """
    scn = _financing_approved_scenario(9_200_000, "COMMUNITY_LOT", double_wide=True)
    crew, job = book_transport(scn, distance_miles=180, scheduled_start_date="2026-08-20T08:00:00Z")

    cancelled = validate_success(api.cancel_transport_job(job["id"], COORDINATOR))
    assert cancelled["status"] == "CANCELLED"
    crew_view = get_success_data(api.get_transport_crew(crew["id"], ADMIN))
    assert_booked_dates(crew_view, [])

    _, job2 = book_transport(scn, crew=crew, distance_miles=180, scheduled_start_date="2026-08-20T08:00:00Z")
    assert job2["status"] == "SCHEDULED", "the cancelled job consumes nothing; identical re-booking succeeds"


# --- dispatch window ------------------------------------------------------------------

def test_dispatch_outside_window_rejected_then_inside(api):
    """PRD §3.6: "Execution begins with dispatch: the coordinator starts the
    move, `SCHEDULED` → `EN_ROUTE`, only while the current clock date falls
    inside the move window (from the start date up to but not including start
    plus `sections_count` days), else `ERR_INVALID_STATE`; dispatch moves the
    unit `RESERVED` → `IN_TRANSIT`."

    Design: Corner/endpoints/dispatch_outside_window_rejected_then_inside
    """
    scn = canonical_community_scenario()
    progress_to_financing_approved(scn)
    _, job = book_transport(scn, scheduled_start_date="2026-08-20T08:00:00Z")

    set_clock("2026-08-19T10:00:00Z")
    resp = api.dispatch_transport_job(job["id"], COORDINATOR)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    set_clock("2026-08-20T10:00:00Z")
    dispatched = validate_success(api.dispatch_transport_job(job["id"], COORDINATOR))
    assert dispatched["status"] == "EN_ROUTE"
    unit = get_success_data(api.get_home_unit(scn["unit"]["id"], ADMIN))
    assert unit["status"] == "IN_TRANSIT", "dispatch moves the unit RESERVED -> IN_TRANSIT"
