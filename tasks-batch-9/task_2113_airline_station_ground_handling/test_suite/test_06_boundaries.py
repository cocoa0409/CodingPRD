"""Boundary precision: on-time tolerance, endorsement expiry, staffing
coverage, the daily duty cap, the equipment selector and the charge clamp."""
from test_helpers import (
    ApiErrorId,
    add_agent_occupation,
    add_billing_line,
    add_gse_occupation,
    approve_staffing,
    assert_pct,
    complete_turn,
    create_agent,
    create_approved_subcontractor,
    create_billing_period,
    create_certified_agent,
    create_flight_bank,
    create_gse_unit,
    create_open_station,
    create_turn,
    finalize_period,
    get_agent,
    get_billing_line,
    get_billing_period,
    get_flight_bank,
    get_gse_unit,
    get_station,
    get_turn,
    get_turn_resource,
    issue_certification,
    make_duty_officer_headers,
    make_station_manager_headers,
    publish_and_approve_staffing,
    publish_bank,
    reject_staffing,
    revise_staffing,
    start_turn,
    submit_staffing,
    validate_error,
    validate_success,
)


# ---------------------------------------------------------------------------
# Queue A: boundary_precision_check / otp_tolerance_inclusive_boundary_15_vs_16_minutes
# ---------------------------------------------------------------------------

def _run_two_turns_either_side_of_the_tolerance():
    """One turn departs exactly 15 minutes late, the next 16 minutes late, at a
    station whose otp_tolerance_minutes is 15."""
    station = create_open_station(
        otp_target_pct=85.00, otp_tolerance_minutes=15,
        gse_reposition_buffer_minutes=20, penalty_cap_cents=5000000,
        damage_penalty_multiplier=1.00)
    bank = create_flight_bank(station["id"], planned_headcount=2)
    first = create_turn(station["id"], bank["id"], flight_number="LX301")
    second = create_turn(station["id"], bank["id"], flight_number="LX302",
                         scheduled_in="2026-04-10T08:00:00Z",
                         scheduled_out="2026-04-10T08:20:00Z")
    agent = create_certified_agent(station["id"])
    gse = create_gse_unit(station["id"], condition_score=95,
                          service_interval_cycles=25, cycles_since_service=0)
    publish_and_approve_staffing(bank["id"])

    add_agent_occupation(first["id"], agent["id"],
                         window_start="2026-04-10T05:50:00Z",
                         window_end="2026-04-10T06:40:00Z")
    add_gse_occupation(first["id"], gse_unit_id=gse["id"],
                       window_start="2026-04-10T05:55:00Z",
                       window_end="2026-04-10T06:40:00Z")
    start_turn(first["id"], actual_in="2026-04-10T06:00:00Z")
    first = complete_turn(first["id"], actual_out="2026-04-10T06:35:00Z",
                          delay_code="GH_STAFFING")

    add_agent_occupation(second["id"], agent["id"],
                         window_start="2026-04-10T07:50:00Z",
                         window_end="2026-04-10T08:45:00Z")
    add_gse_occupation(second["id"], gse_unit_id=gse["id"],
                       window_start="2026-04-10T07:50:00Z",
                       window_end="2026-04-10T08:45:00Z")
    start_turn(second["id"], actual_in="2026-04-10T08:00:00Z")
    second = complete_turn(second["id"], actual_out="2026-04-10T08:36:00Z",
                           delay_code="GH_STAFFING")
    return station, first, second, gse


def test_fifteen_minutes_late_is_on_time_and_sixteen_is_delayed(api):
    """PRD §3.1: "`otp_tolerance_minutes` is the departure delay, in whole
    minutes, that still counts as on time — the boundary is inclusive — and it
    defaults to 15 and may not be negative."
    PRD §3.4: "First, if `delay_minutes` is less than or equal to the station's
    `otp_tolerance_minutes`, the `otp_result` is `ON_TIME` — the boundary is
    inclusive, and because this test runs first, a turnaround inside tolerance
    is `ON_TIME` even when its `delay_code` is `WEATHER`."

    Design: Difficulty/boundary_precision_check/otp_tolerance_inclusive_boundary_15_vs_16_minutes
    """
    _station, first, second, _gse = _run_two_turns_either_side_of_the_tolerance()
    assert first["delay_minutes"] == 15
    assert first["otp_result"] == "ON_TIME", (
        "exactly at the inclusive tolerance boundary")
    assert second["delay_minutes"] == 16
    assert second["otp_result"] == "DELAYED", (
        "one minute past the boundary with a handler-attributed code")
    assert first["actual_ground_minutes"] == 35
    assert second["actual_ground_minutes"] == 36


def test_station_otp_rollup_counts_one_turn_on_each_side_of_the_boundary(api):
    """PRD §3.4: "The station's `completed_turn_count` then counts its
    turnarounds whose `status` is `COMPLETED` and whose `otp_result` is
    `ON_TIME` or `DELAYED`; its `on_time_turn_count` counts those whose
    `status` is `COMPLETED` and whose `otp_result` is `ON_TIME`."
    PRD §3.4: "The station's `otp_rolling_pct` is 100.00 when
    `completed_turn_count` is zero, and otherwise is 100 multiplied by
    `on_time_turn_count`, divided by `completed_turn_count`, rounded half up to
    two decimal places."

    Design: Difficulty/boundary_precision_check/otp_tolerance_inclusive_boundary_15_vs_16_minutes
    """
    station, _first, _second, gse = _run_two_turns_either_side_of_the_tolerance()
    station = get_station(station["id"])
    assert station["completed_turn_count"] == 2
    assert station["on_time_turn_count"] == 1
    assert_pct(station["otp_rolling_pct"], 50.00, "otp_rolling_pct")
    assert station["oversight_posture"] == "NORMAL", (
        "the OTP branch of ENHANCED needs at least 3 completed turnarounds")

    gse = get_gse_unit(gse["id"])
    assert gse["cycles_since_service"] == 2
    assert gse["committed_occupation_minutes"] == 0


# ---------------------------------------------------------------------------
# Queue A: boundary_precision_check /
#          certification_expiry_exclusive_bound_at_occupation_start
# ---------------------------------------------------------------------------

def _setup_endorsement_expiring_at_the_occupation_start():
    """The agent's RAMP_SAFETY endorsement expires at exactly
    2026-04-10T05:50:00Z, the instant the first occupation would start."""
    station = create_open_station()
    bank = create_flight_bank(station["id"], planned_headcount=1)
    turn = create_turn(station["id"], bank["id"])
    agent = create_agent(station["id"])
    issue_certification(agent["id"], station["id"],
                        issued_at="2026-01-01T00:00:00Z",
                        expires_at="2026-04-10T05:50:00Z")
    return station, turn, agent


def test_occupation_starting_exactly_at_expiry_is_refused(api):
    """PRD §3.5: "Whether an endorsement is *effective at a given instant* is
    the primitive that everything else is built on: the endorsement's `status`
    must be `VALID`, its `issued_at` must be at or before that instant, and its
    `expires_at` must be strictly after it. The upper bound is exclusive, so an
    endorsement whose `expires_at` falls exactly on the instant being tested is
    not effective."
    PRD §3.5: "When an agent is committed to a turnaround, each required
    endorsement is tested for effectiveness **at the occupation's own
    `window_start`**, not at the current logical clock."

    Design: Difficulty/boundary_precision_check/certification_expiry_exclusive_bound_at_occupation_start
    """
    _station, turn, agent = _setup_endorsement_expiring_at_the_occupation_start()

    resp = api.create_turn_resource(
        {"turn_id": turn["id"], "resource_kind": "AGENT",
         "agent_id": agent["id"], "role_on_turn": "RAMP",
         "window_start": "2026-04-10T05:50:00Z",
         "window_end": "2026-04-10T06:30:00Z",
         "expected_turn_version": turn["version"]},
        make_duty_officer_headers())
    validate_error(resp, ApiErrorId.ERR_CERT_NOT_CURRENT, 422)
    assert get_agent(agent["id"])["assigned_duty_minutes"] == 0


def test_occupation_starting_one_minute_earlier_is_admitted(api):
    """PRD §3.7: "An accepted occupation lands at `RESERVED`. Its
    `occupied_minutes` is the elapsed time from `window_start` to `window_end`
    in whole minutes, rounded down."
    PRD §3.5: "Every one of the required endorsements must be held by the agent
    at the turnaround's station and be effective at the occupation's start; if
    even one is missing, expired, not yet issued or revoked, the commitment is
    refused with `ERR_CERT_NOT_CURRENT` and HTTP 422."

    Design: Difficulty/boundary_precision_check/certification_expiry_exclusive_bound_at_occupation_start
    """
    _station, turn, agent = _setup_endorsement_expiring_at_the_occupation_start()

    accepted = validate_success(api.create_turn_resource(
        {"turn_id": turn["id"], "resource_kind": "AGENT",
         "agent_id": agent["id"], "role_on_turn": "RAMP",
         "window_start": "2026-04-10T05:49:00Z",
         "window_end": "2026-04-10T06:30:00Z",
         "expected_turn_version": turn["version"]},
        make_duty_officer_headers()), 201)
    assert accepted["status"] == "RESERVED"
    assert accepted["occupied_minutes"] == 41

    turn = get_turn(turn["id"])
    assert turn["assigned_agent_count"] == 1
    assert turn["status"] == "SCHEDULED"
    assert get_agent(agent["id"])["assigned_duty_minutes"] == 41


# ---------------------------------------------------------------------------
# Queue A: boundary_precision_check / staffing_coverage_inclusive_boundary_at_100_pct
# ---------------------------------------------------------------------------

def _setup_bank_submitted_at_two_thirds_coverage():
    """Three TOWING_ONLY turns against planned_headcount 2, i.e. coverage
    66.67 percent, with the plan already SUBMITTED."""
    station = create_open_station()
    bank = create_flight_bank(station["id"], planned_headcount=2)
    for index, flight_number in enumerate(("LX401", "LX402", "LX403")):
        hour = 6 + index * 2
        create_turn(station["id"], bank["id"], flight_number=flight_number,
                    scheduled_in=f"2026-04-10T{hour:02d}:00:00Z",
                    scheduled_out=f"2026-04-10T{hour:02d}:20:00Z")
    publish_bank(bank["id"])
    submitted = submit_staffing(bank["id"])
    return station, bank, submitted


def test_approval_at_sixty_six_percent_coverage_is_refused(api):
    """PRD §3.3: "A `StationManager` approves the plan with `APPROVE`, moving
    `staffing_status` `SUBMITTED → APPROVED`; approval requires the station to
    be `OPEN` and requires `staffing_coverage_pct` to be at least 100.00, with
    a shortfall refused as `ERR_STAFFING_COVERAGE_INSUFFICIENT`."
    PRD §3.3: "Otherwise `staffing_coverage_pct` is 100 multiplied by
    `planned_headcount`, divided by `required_headcount`, rounded half up to
    two decimal places."

    Design: Difficulty/boundary_precision_check/staffing_coverage_inclusive_boundary_at_100_pct
    """
    _station, bank, submitted = _setup_bank_submitted_at_two_thirds_coverage()
    assert submitted["required_headcount"] == 3
    assert_pct(submitted["staffing_coverage_pct"], 66.67, "staffing_coverage_pct")

    resp = api.staffing_transition(bank["id"], {"action": "APPROVE"},
                                   make_station_manager_headers("sm-01"))
    validate_error(resp, ApiErrorId.ERR_STAFFING_COVERAGE_INSUFFICIENT, 422)
    assert get_flight_bank(bank["id"])["staffing_status"] == "SUBMITTED"


def test_approval_at_exactly_one_hundred_percent_coverage_succeeds(api):
    """PRD §3.3: "A `StationManager` approves the plan with `APPROVE`, moving
    `staffing_status` `SUBMITTED → APPROVED`; approval requires the station to
    be `OPEN` and requires `staffing_coverage_pct` to be at least 100.00, with
    a shortfall refused as `ERR_STAFFING_COVERAGE_INSUFFICIENT`."
    PRD §3.3: "A `DutyOfficer` then revises with `REVISE`, moving
    `staffing_status` `REVISION_REQUIRED → DRAFT`; revision replaces
    `planned_headcount` when the field is supplied, leaves it untouched when it
    is omitted, and recomputes `staffing_coverage_pct` either way."

    Design: Difficulty/boundary_precision_check/staffing_coverage_inclusive_boundary_at_100_pct
    """
    _station, bank, _submitted = _setup_bank_submitted_at_two_thirds_coverage()
    api.staffing_transition(bank["id"], {"action": "APPROVE"},
                            make_station_manager_headers("sm-01"))
    reject_staffing(bank["id"], user_id="sm-01")

    revised = revise_staffing(bank["id"], planned_headcount=3)
    assert_pct(revised["staffing_coverage_pct"], 100.00, "staffing_coverage_pct")
    submit_staffing(bank["id"])
    approved = approve_staffing(bank["id"], user_id="sm-02")
    assert approved["staffing_status"] == "APPROVED"

    bank = get_flight_bank(bank["id"])
    assert bank["bank_status"] == "PUBLISHED"
    assert bank["last_staffing_decision_by_user_id"] == "sm-02"


# ---------------------------------------------------------------------------
# Queue B: calculations / agent_daily_duty_cap_admits_600_and_rejects_601
# ---------------------------------------------------------------------------

def test_daily_duty_cap_admits_exactly_600_minutes_and_refuses_601(api):
    """PRD §3.7: "The **daily duty cap** then looks at the UTC calendar date of
    the proposed `window_start`, adds up `occupied_minutes` across all of that
    agent's occupations at `RESERVED` or `COMMITTED` whose own `window_start`
    falls on that same UTC date, adds the proposed occupation's
    `occupied_minutes` to that sum, and refuses the request with
    `ERR_AGENT_DUTY_LIMIT_EXCEEDED` and HTTP 422 if the projected total is
    strictly greater than ten hours of duty in the day."
    PRD §3.7: "A projection landing on exactly 600 minutes is admissible; only
    a projection above it is refused."

    Design: Corner/calculations/agent_daily_duty_cap_admits_600_and_rejects_601
    """
    station = create_open_station()
    bank = create_flight_bank(station["id"], planned_headcount=2)
    first = create_turn(station["id"], bank["id"], flight_number="LX601")
    second = create_turn(station["id"], bank["id"], flight_number="LX602",
                         scheduled_in="2026-04-10T15:00:00Z",
                         scheduled_out="2026-04-10T15:20:00Z")
    agent = create_certified_agent(station["id"])
    long_duty = add_agent_occupation(first["id"], agent["id"],
                                     window_start="2026-04-10T05:00:00Z",
                                     window_end="2026-04-10T14:40:00Z")
    assert long_duty["occupied_minutes"] == 580

    second = get_turn(second["id"])
    over_cap = api.create_turn_resource(
        {"turn_id": second["id"], "resource_kind": "AGENT",
         "agent_id": agent["id"], "role_on_turn": "RAMP",
         "window_start": "2026-04-10T15:00:00Z",
         "window_end": "2026-04-10T15:21:00Z",
         "expected_turn_version": second["version"]},
        make_duty_officer_headers())
    validate_error(over_cap, ApiErrorId.ERR_AGENT_DUTY_LIMIT_EXCEEDED, 422)

    at_cap = validate_success(api.create_turn_resource(
        {"turn_id": second["id"], "resource_kind": "AGENT",
         "agent_id": agent["id"], "role_on_turn": "RAMP",
         "window_start": "2026-04-10T15:00:00Z",
         "window_end": "2026-04-10T15:20:00Z",
         "expected_turn_version": second["version"]},
        make_duty_officer_headers()), 201)
    assert at_cap["occupied_minutes"] == 20
    assert get_agent(agent["id"])["assigned_duty_minutes"] == 600
    assert get_turn_resource(long_duty["id"])["status"] == "RESERVED"
    assert get_turn_resource(at_cap["id"])["status"] == "RESERVED"


# ---------------------------------------------------------------------------
# Queue B: calculations /
#          gse_selector_ranks_remaining_cycles_then_condition_then_created_at
# ---------------------------------------------------------------------------

def test_selector_ranks_by_remaining_life_then_condition_then_created_at(api):
    """PRD §3.6: "Candidates are then ranked by remaining service life — that
    is, by `service_interval_cycles` minus `cycles_since_service`, largest
    first — then by `condition_score`, largest first, and finally by
    `created_at`, earliest first. The first candidate under that ranking is the
    one selected."
    PRD §3.6: "A unit's `id` plays no part in eligibility, in ranking, or in
    the tie-break; `created_at` is the only fallback."

    Design: Corner/calculations/gse_selector_ranks_remaining_cycles_then_condition_then_created_at
    """
    station = create_open_station(gse_reposition_buffer_minutes=20)
    bank = create_flight_bank(station["id"], planned_headcount=1)
    turn = create_turn(station["id"], bank["id"])
    first = create_gse_unit(station["id"], asset_tag="TUG-01", condition_score=80,
                            service_interval_cycles=25, cycles_since_service=5)
    second = create_gse_unit(station["id"], asset_tag="TUG-02", condition_score=70,
                             service_interval_cycles=30, cycles_since_service=5)
    third = create_gse_unit(station["id"], asset_tag="TUG-03", condition_score=90,
                            service_interval_cycles=25, cycles_since_service=0)
    fourth = create_gse_unit(station["id"], asset_tag="TUG-04", condition_score=90,
                             service_interval_cycles=25, cycles_since_service=0)

    chosen = add_gse_occupation(turn["id"], gse_type="PUSHBACK_TUG",
                                window_start="2026-04-10T05:55:00Z",
                                window_end="2026-04-10T06:25:00Z")
    assert chosen["gse_unit_id"] == third["id"], (
        "TUG-03 wins the 25-cycle, condition-90 tie on created_at")
    assert chosen["gse_unit_id"] != fourth["id"]
    assert chosen["occupied_minutes"] == 30

    assert get_gse_unit(third["id"])["committed_occupation_minutes"] == 30
    for loser in (first, second, fourth):
        assert get_gse_unit(loser["id"])["committed_occupation_minutes"] == 0
    assert get_turn(turn["id"])["assigned_gse_count"] == 1


# ---------------------------------------------------------------------------
# Queue B: calculations / gse_selector_with_empty_candidate_pool_returns_no_eligible_gse
# ---------------------------------------------------------------------------

def test_selector_with_no_candidate_of_the_requested_type_is_refused(api):
    """PRD §3.6: "If the candidate pool comes back empty, the request is
    refused with `ERR_NO_ELIGIBLE_GSE` and HTTP 409."
    PRD §3.6: "The candidate pool is every unit based at the turnaround's
    station whose `gse_type` matches the requested type, whose `status` is
    exactly `AVAILABLE`, which reports no conflict under the buffered
    occupation test, and which reports no conflict under the closed
    service-hold test; units in `IN_MAINTENANCE`, `QUARANTINED` or `RETIRED`
    are never candidates."

    Design: Corner/calculations/gse_selector_with_empty_candidate_pool_returns_no_eligible_gse
    """
    station = create_open_station()
    bank = create_flight_bank(station["id"], planned_headcount=1)
    turn = create_turn(station["id"], bank["id"])
    tug = create_gse_unit(station["id"])

    resp = api.create_turn_resource(
        {"turn_id": turn["id"], "resource_kind": "GSE", "gse_type": "DEICER",
         "window_start": "2026-04-10T05:55:00Z",
         "window_end": "2026-04-10T06:25:00Z",
         "expected_turn_version": turn["version"]},
        make_duty_officer_headers())
    validate_error(resp, ApiErrorId.ERR_NO_ELIGIBLE_GSE, 409)

    assert get_turn(turn["id"])["assigned_gse_count"] == 0
    assert get_gse_unit(tug["id"])["committed_occupation_minutes"] == 0


# ---------------------------------------------------------------------------
# Queue B: calculations / turn_service_charge_clamps_at_three_times_base_rate
# ---------------------------------------------------------------------------

def test_gross_charge_is_lowered_to_three_times_the_base_rate(api):
    """PRD §3.9: "That single rounded figure is then clamped: it is raised to
    the base rate if it fell below it, and lowered to three times the base rate
    if it exceeded that."
    PRD §3.9: "The line also publishes a `ground_time_tier` describing where it
    landed: `TIER_1` when `excess_minutes` is 15 or fewer, `TIER_2` when it is
    more than 15 but no more than 45, and `TIER_3` when it is more than 45."

    Design: Corner/calculations/turn_service_charge_clamps_at_three_times_base_rate
    """
    station = create_open_station(
        iata_code="GVA", name="Geneva", handler_code="MNZ",
        season_code="WINTER", otp_tolerance_minutes=15,
        penalty_cap_cents=5000000, damage_penalty_multiplier=1.00)
    subcontractor = create_approved_subcontractor(
        station["id"], legal_name="Jet Handling Sarl")
    bank = create_flight_bank(station["id"], bank_code="W1",
                              season_code="WINTER", planned_headcount=1)
    turn = create_turn(station["id"], bank["id"], flight_number="LX999")
    agent = create_certified_agent(station["id"], employee_code="E010",
                                   full_name="Cleo Marin",
                                   subcontractor_id=subcontractor["id"])
    gse = create_gse_unit(station["id"])
    publish_and_approve_staffing(bank["id"])
    add_agent_occupation(turn["id"], agent["id"],
                         window_start="2026-04-10T05:50:00Z",
                         window_end="2026-04-10T07:15:00Z")
    add_gse_occupation(turn["id"], gse_unit_id=gse["id"],
                       window_start="2026-04-10T05:55:00Z",
                       window_end="2026-04-10T07:10:00Z")
    start_turn(turn["id"], actual_in="2026-04-10T06:00:00Z")
    completed = complete_turn(turn["id"], actual_out="2026-04-10T07:05:00Z",
                              delay_code="WEATHER")
    assert completed["actual_ground_minutes"] == 65

    period = create_billing_period(station["id"], period_code="2026-04")
    line = add_billing_line(period["id"], turn["id"])
    finalized = finalize_period(period["id"], user_id="bc-01")

    line = get_billing_line(line["id"])
    assert line["excess_minutes"] == 45
    assert line["ground_time_tier"] == "TIER_2", (
        "45 excess minutes is still 'no more than 45'")
    # Raw (18000 + 55500) * 1.15 * 0.965 = 81566.625 -> 81567, clamped to 54000.
    assert line["gross_amount_cents"] == 54000
    assert line["net_amount_cents"] == 54000
    assert finalized["gross_total_cents"] == 54000
    assert finalized["rebate_tier"] == "NONE"


# ---------------------------------------------------------------------------
# Queue B: calculations / rebate_largest_remainder_tie_break_favours_earlier_created_line
# ---------------------------------------------------------------------------

def test_largest_remainder_leftover_cent_goes_to_the_earlier_line(api):
    """PRD §3.9: "Lines are then ranked by remainder, largest first; ties are
    broken by `gross_amount_cents`, largest first; any remaining tie is broken
    by `created_at`, earliest first. One extra cent is given to each of the
    first however-many lines the leftover covers, and each line's
    `rebate_alloc_cents` is its whole-number part plus that extra cent where it
    won one."
    PRD §3.9: "Rounding each line's share independently is forbidden, because
    it can make the allocations add up to one cent more or less than
    `rebate_cents` and break the ledger identity."

    Design: Corner/calculations/rebate_largest_remainder_tie_break_favours_earlier_created_line
    """
    station = create_open_station(
        iata_code="GVA", name="Geneva", handler_code="MNZ",
        season_code="WINTER", otp_tolerance_minutes=15,
        gse_reposition_buffer_minutes=20, penalty_cap_cents=5000000,
        damage_penalty_multiplier=1.00)
    bank = create_flight_bank(station["id"], bank_code="W1",
                              season_code="WINTER", planned_headcount=2)
    turn_x = create_turn(station["id"], bank["id"], flight_number="LX501")
    turn_y = create_turn(station["id"], bank["id"], flight_number="LX502",
                         scheduled_in="2026-04-10T08:00:00Z",
                         scheduled_out="2026-04-10T08:20:00Z")
    agent = create_certified_agent(station["id"])
    gse = create_gse_unit(station["id"])
    publish_and_approve_staffing(bank["id"])

    add_agent_occupation(turn_x["id"], agent["id"],
                         window_start="2026-04-10T05:40:00Z",
                         window_end="2026-04-10T06:25:00Z")
    add_gse_occupation(turn_x["id"], gse_unit_id=gse["id"],
                       window_start="2026-04-10T05:45:00Z",
                       window_end="2026-04-10T06:25:00Z")
    start_turn(turn_x["id"], actual_in="2026-04-10T05:51:00Z")
    complete_turn(turn_x["id"], actual_out="2026-04-10T06:20:00Z",
                  delay_code="NONE")

    add_agent_occupation(turn_y["id"], agent["id"],
                         window_start="2026-04-10T07:40:00Z",
                         window_end="2026-04-10T08:25:00Z")
    add_gse_occupation(turn_y["id"], gse_unit_id=gse["id"],
                       window_start="2026-04-10T07:45:00Z",
                       window_end="2026-04-10T08:25:00Z")
    start_turn(turn_y["id"], actual_in="2026-04-10T07:51:00Z")
    complete_turn(turn_y["id"], actual_out="2026-04-10T08:20:00Z",
                  delay_code="NONE")

    period = create_billing_period(station["id"], period_code="2026-04")
    line_x = add_billing_line(period["id"], turn_x["id"])
    line_y = add_billing_line(period["id"], turn_y["id"])
    finalized = finalize_period(period["id"], user_id="bc-01")

    line_x = get_billing_line(line_x["id"])
    line_y = get_billing_line(line_y["id"])
    assert line_x["gross_amount_cents"] == 30015
    assert line_y["gross_amount_cents"] == 30015
    assert finalized["gross_total_cents"] == 60030
    assert finalized["rebate_tier"] == "TIER_A"
    assert finalized["rebate_cents"] == 1801
    assert line_x["rebate_alloc_cents"] == 901, (
        "both exact shares are 900.5, so the leftover cent follows created_at")
    assert line_y["rebate_alloc_cents"] == 900
    assert line_x["net_amount_cents"] == 30916
    assert line_y["net_amount_cents"] == 30915

    period = get_billing_period(period["id"])
    assert period["accrued_cents"] == 61831
    assert period["net_total_cents"] == 61831
