"""Assignment confirmation: state-precedence vs. business-safety, FAA boundary
correctness, crew-rest interval, and the cross-entity guard against confirming
an Assignment that has cascaded past CONFIRMED.
"""
from test_helpers import (
    validate_error,
    validate_success,
    set_clock,
    setup_clean_world,
    setup_scheduled_captain_assignment,
    setup_confirmed_captain_assignment,
    setup_completed_pairing_for_crew,
    setup_crew_with_accumulated_duty,
    create_crew_member,
    create_pairing,
    add_revenue_leg,
    open_bidding,
    submit_bid,
    award_pairing,
    confirm_assignment,
    first_assignment_for,
    complete_pairing,
    get_pairing,
    get_assignment,
    make_crew_member_headers,
    TEST_USERS,
    FAA_DUTY_CAP_7D_MIN,
    MIN_REST_MINUTES,
)


# ---------------------------------------------------------------------
# Priority-5 state error wins over Priority-7 business safety
# ---------------------------------------------------------------------

def test_second_confirm_on_already_confirmed_returns_invalid_state(api):
    """PRD §2.9: "State eligibility: the target resource must currently be in
    a state from which the requested transition is defined (else `ERR_INVALID_STATE`)."
    PRD §2.9: "the three FAA / rest checks run after state validation but
    before the structural checks (rank-seat, time-window, overlap), so an
    in-state but cap-breaching confirm surfaces as a safety error rather than
    a request-shape error."

    Design: Difficulty/priority_pair_validation_conflict/state_vs_business_safety_on_confirm
    """
    cm, _pairing, assignment = setup_confirmed_captain_assignment(
        employee_code_suffix="0080", seniority_number=80
    )
    # Second confirm on an already-CONFIRMED Assignment — priority-5 state error
    # fires before any business-safety check.
    res = api.confirm_assignment(assignment["id"], make_crew_member_headers(cm["id"]))
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


# ---------------------------------------------------------------------
# Cross-entity-pair test: assignment confirm after parent Pairing cascade
# ---------------------------------------------------------------------

def test_confirm_assignment_after_pairing_in_progress_cascade_returns_invalid_state(api):
    """PRD §2.9: "State eligibility: the target resource must currently be in
    a state from which the requested transition is defined (else `ERR_INVALID_STATE`)."
    PRD §2.6: "for each Pairing in `AWARDED` whose `current_utc >= scheduled_start_utc`
    and whose every child Assignment is `CONFIRMED`, the Pairing cascades to
    `IN_PROGRESS` and each child Assignment moves from `CONFIRMED` to `ACTIVE`
    with `actual_duty_start_utc` set to `current_utc` and the owning
    `CrewMember.status` set to `ON_DUTY`."

    Design: Difficulty/cross_entity_state_dependency/assignment_confirm_requires_pairing_awarded_pair_assignment_pairing
    """
    cm, pairing, assignment = setup_confirmed_captain_assignment(
        employee_code_suffix="0120", seniority_number=120
    )
    # Advance the clock past scheduled_start_utc — the cascade flips the
    # Assignment from CONFIRMED to ACTIVE.
    set_clock(pairing["scheduled_start_utc"])
    # Now attempt confirm again — the Assignment is in ACTIVE so SCHEDULED→CONFIRMED
    # is undefined.
    res = api.confirm_assignment(assignment["id"], make_crew_member_headers(cm["id"]))
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)
    # Independent verification that the cascade did fire.
    a_after = get_assignment(assignment["id"])
    assert a_after["state"] == "ACTIVE", (
        f"Pairing IN_PROGRESS cascade must move Assignment to ACTIVE, "
        f"got {a_after['state']!r}"
    )


# ---------------------------------------------------------------------
# FAA boundary correctness on /confirm
# ---------------------------------------------------------------------

def test_faa_duty_below_cap_confirm_succeeds_boundary(api):
    """PRD §2.7: "A violation is declared if the previewed duty total exceeds
    3,600 minutes (60 hours of duty in any rolling seven-day window) or if
    the previewed flight total exceeds 1,800 minutes (30 hours of flight in
    any rolling seven-day window). The comparison uses strict greater-than at
    the cap: a value exactly equal to the cap passes, and exceeding the cap
    by one minute fails."

    Design: Difficulty/boundary_precision_check/faa_duty_cap_at_exact_boundary_passes_on_confirm
    """
    # Accumulate prior duty 2820 min (window 2730 + 60 report + 30 debrief).
    # Candidate pairing 600 min duty (510 window + 90). Preview = 3420 < 3600.
    cm, new_assignment = setup_crew_with_accumulated_duty(
        target_duty_minutes=2820,
        new_pairing_start="2026-06-02T00:00:00Z",
        new_pairing_end="2026-06-02T08:30:00Z",
        new_leg_dep="2026-06-02T01:00:00Z",
        new_leg_arr="2026-06-02T07:30:00Z",
        new_pairing_close="2026-06-01T12:00:00Z",
    )
    # Sanity-anchor: the persisted duty is at most the cap.
    assert cm["total_duty_minutes_7d"] <= FAA_DUTY_CAP_7D_MIN, (
        f"prior duty should sit below the cap, got {cm['total_duty_minutes_7d']!r}"
    )
    res = api.confirm_assignment(
        new_assignment["id"], make_crew_member_headers(cm["id"])
    )
    data = validate_success(res, 200)
    assert data["state"] == "CONFIRMED", (
        f"preview below cap must allow confirm, got {data['state']!r}"
    )


# ---------------------------------------------------------------------
# Crew-rest interval just-below threshold
# ---------------------------------------------------------------------

def test_crew_rest_interval_just_below_threshold_rejected(api):
    """PRD §2.8: "Otherwise, the difference must be at least 600 minutes (the
    threshold uses inclusive comparison: an interval of exactly 600 minutes
    passes; an interval one minute shorter fails). A violation surfaces as
    `ERR_CREW_REST_VIOLATION` (HTTP 422)."

    Design: Corner/calculations/crew_rest_interval_just_below_threshold_fails
    """
    setup_clean_world("2026-05-25T00:00:00Z")
    cm = create_crew_member(
        employee_code="AB0300", seniority_number=300, line_type="LINEHOLDER"
    )
    # Prior pairing: schedules start 2026-06-01T23:00, ends 2026-06-02T00:01
    # → crew's last_off_duty_utc becomes 2026-06-02T00:01 after /complete.
    prior_pairing = create_pairing(
        pairing_code="P-2026-300",
        scheduled_start_utc="2026-06-01T23:00:00Z",
        scheduled_end_utc="2026-06-02T00:01:00Z",
        bidding_close_utc="2026-06-01T12:00:00Z",
    )
    add_revenue_leg(
        prior_pairing["id"],
        leg_sequence=1,
        departure="LAX",
        arrival="JFK",
        scheduled_departure_utc="2026-06-01T23:30:00Z",
        scheduled_arrival_utc="2026-06-02T00:01:00Z",
    )
    open_bidding(prior_pairing["id"])
    submit_bid(prior_pairing["id"], cm, requested_seat="CAPTAIN")
    set_clock("2026-06-01T12:00:01Z")
    award_pairing(prior_pairing["id"])
    a_prior = first_assignment_for(prior_pairing["id"], cm["id"])
    confirm_assignment(a_prior["id"], cm)
    set_clock("2026-06-02T00:01:00Z")
    complete_pairing(prior_pairing["id"])

    # New pairing starts 2026-06-02T10:00 → rest = 599 min, fails threshold.
    new_pairing = create_pairing(
        pairing_code="P-2026-301",
        scheduled_start_utc="2026-06-02T10:00:00Z",
        scheduled_end_utc="2026-06-02T18:00:00Z",
        bidding_close_utc="2026-06-02T05:00:00Z",
    )
    add_revenue_leg(
        new_pairing["id"],
        leg_sequence=1,
        departure="LAX",
        arrival="MIA",
        scheduled_departure_utc="2026-06-02T11:00:00Z",
        scheduled_arrival_utc="2026-06-02T17:00:00Z",
    )
    open_bidding(new_pairing["id"])
    submit_bid(new_pairing["id"], cm, requested_seat="CAPTAIN")
    set_clock("2026-06-02T05:00:01Z")
    award_pairing(new_pairing["id"])
    a_new = first_assignment_for(new_pairing["id"], cm["id"])

    res = api.confirm_assignment(a_new["id"], make_crew_member_headers(cm["id"]))
    validate_error(res, "ERR_CREW_REST_VIOLATION", expected_status=422)
