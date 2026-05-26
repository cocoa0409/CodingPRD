"""Dual-variant calculations: rolling_duty_window's persisted vs preview form
on a CrewMember, pairing_credit_block's scheduled vs actual on a Pairing, and
the actual_block_minutes averaging order.
"""
from test_helpers import (
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
    complete_pairing,
    first_assignment_for,
    get_crew_member,
    get_pairing,
    make_crew_member_headers,
    TEST_USERS,
)


# ---------------------------------------------------------------------
# Rolling-duty-window completed_actual vs preview_with_candidate
# ---------------------------------------------------------------------

def test_completed_actual_persisted_after_pairing_complete(api):
    """PRD §2.7: "`total_duty_minutes_7d` is the analogous sum of
    `duty_minutes_credited` over the same set of completed assignments."
    PRD §3.1: "the rolling seven-day totals on that crew member are recomputed".

    Design: Difficulty/dual_variant_calc/rolling_duty_window_completed_vs_preview_on_crew_member
    """
    # Prior pairing: window 510 min flight (06:00 LAX-JFK), 8.5h duty window
    # Actually setup_completed_pairing_for_crew uses default 10h window → 600+90 = 690.
    cm_after, pairing, assignment = setup_completed_pairing_for_crew(
        employee_code_suffix="0001", seniority_number=1
    )
    # After completion, the crew's total_duty_minutes_7d should equal the
    # parent pairing's total_duty_minutes (locked into Assignment.duty_minutes_credited
    # and summed onto the crew).
    assert cm_after["total_duty_minutes_7d"] == pairing["total_duty_minutes"], (
        f"crew total_duty_minutes_7d ({cm_after['total_duty_minutes_7d']}) must equal "
        f"the completed pairing's total_duty_minutes ({pairing['total_duty_minutes']})"
    )
    # Assignment.duty_minutes_credited is locked from the parent (PRD §3.1).
    assert assignment["duty_minutes_credited"] == pairing["total_duty_minutes"], (
        f"Assignment.duty_minutes_credited ({assignment['duty_minutes_credited']}) must "
        f"equal parent Pairing.total_duty_minutes ({pairing['total_duty_minutes']})"
    )


def test_preview_variant_admits_candidate_when_under_cap(api):
    """PRD §2.7: "When a crew member is about to take on a new commitment —
    confirming an assignment, accepting a reserve callup, or being approved
    as the new owner under a trip trade — the system runs a **preview form**
    of the rolling calculation: it adds the candidate Pairing's
    `total_duty_minutes` and `total_flight_minutes` to the persisted seven-day
    totals as if the assignment had already completed, without writing the
    preview back to the `CrewMember`."

    Design: Difficulty/dual_variant_calc/rolling_duty_window_completed_vs_preview_on_crew_member
    """
    # Prior pairing total_duty_minutes is 600 + 90 = 690 (default 10h window).
    # Candidate pairing is the same shape → preview = 690 + 690 = 1380 ≪ 3600 cap.
    cm_with_totals, new_assignment = setup_crew_with_accumulated_duty(
        target_duty_minutes=690,
        new_pairing_start="2026-06-02T00:00:00Z",
        new_pairing_end="2026-06-02T11:30:00Z",
        new_leg_dep="2026-06-02T01:00:00Z",
        new_leg_arr="2026-06-02T10:00:00Z",
        new_pairing_close="2026-06-01T12:00:00Z",
    )
    persisted_before = cm_with_totals["total_duty_minutes_7d"]
    # Confirming should succeed because preview is well below the cap.
    res = api.confirm_assignment(
        new_assignment["id"], make_crew_member_headers(cm_with_totals["id"])
    )
    data = validate_success(res, 200)
    assert data["state"] == "CONFIRMED", (
        f"preview below cap must allow confirm, got {data['state']!r}"
    )
    # Re-read crew — preview must NOT be written back to the persisted total.
    cm_after = get_crew_member(cm_with_totals["id"])
    assert cm_after["total_duty_minutes_7d"] == persisted_before, (
        f"preview must not be written to CrewMember.total_duty_minutes_7d: "
        f"before={persisted_before}, after={cm_after['total_duty_minutes_7d']}"
    )


# ---------------------------------------------------------------------
# Pairing.scheduled_block_minutes vs actual_block_minutes
# ---------------------------------------------------------------------

def test_scheduled_block_locked_at_award_actual_block_locked_at_complete(api):
    """PRD §3.1: "At the same moment the Pairing's `scheduled_block_minutes` is
    computed and locked: it equals the difference in whole minutes between
    `scheduled_end_utc` and `scheduled_start_utc`, minus the 60-minute report
    buffer and minus the 30-minute debrief buffer (i.e., the planned duty
    window less the 90 minutes of buffer time)."
    PRD §3.1: "In the same atomic step the Pairing's `actual_block_minutes` is
    locked: it is the floor of the sum, over each `COMPLETED` Assignment on
    this Pairing, of the difference in minutes between that Assignment's
    `actual_duty_end_utc` and `actual_duty_start_utc`, divided by the count
    of such Assignments."

    Design: Difficulty/dual_variant_calc/pairing_credit_block_scheduled_vs_actual_on_pairing
    """
    setup_clean_world("2026-06-01T00:00:00Z")
    cm = create_crew_member(employee_code="AB0010", seniority_number=10)
    # Scheduled duty window 10h → scheduled_block = 600 - 90 = 510 min.
    pairing = create_pairing(
        pairing_code="P-2026-010",
        scheduled_start_utc="2026-06-02T00:00:00Z",
        scheduled_end_utc="2026-06-02T10:00:00Z",
        bidding_close_utc="2026-06-01T12:00:00Z",
    )
    add_revenue_leg(
        pairing["id"],
        leg_sequence=1,
        departure="LAX",
        arrival="JFK",
        scheduled_departure_utc="2026-06-02T01:00:00Z",
        scheduled_arrival_utc="2026-06-02T07:00:00Z",
    )
    open_bidding(pairing["id"])
    submit_bid(pairing["id"], cm, requested_seat="CAPTAIN")
    set_clock("2026-06-01T12:00:01Z")
    p_after_award = award_pairing(pairing["id"])
    assert p_after_award["scheduled_block_minutes"] == 510, (
        f"scheduled_block_minutes locked at AWARDED must equal 600 - 60 - 30 = 510, "
        f"got {p_after_award['scheduled_block_minutes']}"
    )
    a = first_assignment_for(pairing["id"], cm["id"])
    confirm_assignment(a["id"], cm)
    # Push clock past scheduled_start, then past scheduled_end, then complete.
    set_clock("2026-06-02T01:00:00Z")  # cascade to IN_PROGRESS
    set_clock("2026-06-02T11:00:00Z")  # 1h past scheduled_end
    p_after_complete = complete_pairing(pairing["id"])
    # actual_block uses sum-of-per-assignment-minutes // count.
    # Single assignment: duration = 11:00 - 01:00 = 600 min → actual_block = 600.
    assert p_after_complete["actual_block_minutes"] == 600, (
        f"actual_block_minutes locked at COMPLETED must equal 600 "
        f"(duration {600} min, 1 assignment), got {p_after_complete['actual_block_minutes']}"
    )
    # scheduled remains locked.
    assert p_after_complete["scheduled_block_minutes"] == 510, (
        f"scheduled_block_minutes must remain 510 after COMPLETED, "
        f"got {p_after_complete['scheduled_block_minutes']}"
    )


def test_actual_block_minutes_averages_across_two_captains(api):
    """PRD §3.1: "it is the floor of the sum, over each `COMPLETED` Assignment
    on this Pairing, of the difference in minutes between that Assignment's
    `actual_duty_end_utc` and `actual_duty_start_utc`, divided by the count
    of such Assignments."

    Design: Difficulty/combinatorial_formula/pairing_credit_block_rounding_order_mode_b
    """
    setup_clean_world("2026-06-01T00:00:00Z")
    cm1 = create_crew_member(employee_code="AB0030", seniority_number=30)
    cm2 = create_crew_member(employee_code="AB0031", seniority_number=31)
    # Two captain seats; scheduled window is 10h.
    pairing = create_pairing(
        pairing_code="P-2026-030",
        scheduled_start_utc="2026-06-02T00:00:00Z",
        scheduled_end_utc="2026-06-02T10:00:00Z",
        required_captains=2,
        required_first_officers=0,
        required_cabin_crew=0,
        bidding_close_utc="2026-06-01T12:00:00Z",
    )
    add_revenue_leg(
        pairing["id"],
        leg_sequence=1,
        departure="LAX",
        arrival="JFK",
        scheduled_departure_utc="2026-06-02T01:00:00Z",
        scheduled_arrival_utc="2026-06-02T07:00:00Z",
    )
    open_bidding(pairing["id"])
    submit_bid(pairing["id"], cm1, requested_seat="CAPTAIN")
    submit_bid(pairing["id"], cm2, requested_seat="CAPTAIN")
    set_clock("2026-06-01T12:00:01Z")
    award_pairing(pairing["id"])
    a1 = first_assignment_for(pairing["id"], cm1["id"])
    a2 = first_assignment_for(pairing["id"], cm2["id"])
    confirm_assignment(a1["id"], cm1)
    confirm_assignment(a2["id"], cm2)
    set_clock("2026-06-02T01:00:00Z")  # cascade to IN_PROGRESS → both ACTIVE
    set_clock("2026-06-02T11:30:00Z")  # 90 min past scheduled_end
    p_after_complete = complete_pairing(pairing["id"])
    # Each assignment duration = 11:30 - 01:00 = 630 min.
    # actual_block = (630 + 630) // 2 = 630.
    assert p_after_complete["actual_block_minutes"] == 630, (
        f"actual_block_minutes for two-assignment pairing must be "
        f"(630 + 630) // 2 = 630, got {p_after_complete['actual_block_minutes']}"
    )
    assert p_after_complete["state"] == "COMPLETED"


# ---------------------------------------------------------------------
# Combinatorial-formula mode (a): threshold-branch selection on confirm
# ---------------------------------------------------------------------

def test_faa_duty_cap_exceeded_threshold_branch_on_confirm(api):
    """PRD §2.7: "A violation is declared if the previewed duty total exceeds
    3,600 minutes (60 hours of duty in any rolling seven-day window) or if
    the previewed flight total exceeds 1,800 minutes (30 hours of flight in
    any rolling seven-day window). [...] A duty-cap violation surfaces as
    `ERR_FAA_DUTY_CAP_EXCEEDED` (HTTP 422)".
    PRD §2.9: "FAA duty cap, then 8. FAA flight cap, then 9. crew-rest interval
    (the three business-safety checks of §2.7–§2.8, evaluated in this order
    so that a duty-cap breach surfaces before a flight-cap breach, and both
    surface before a rest-interval breach)."

    Design: Difficulty/combinatorial_formula/rolling_duty_window_threshold_branches_mode_a
    """
    # Prior duty 3000 min via prior pairing (window 2910 + 90).
    # Candidate pairing total_duty_minutes 690 → preview = 3690 > 3600 → duty trips.
    cm, new_assignment = setup_crew_with_accumulated_duty(
        target_duty_minutes=3000,
        new_pairing_start="2026-06-02T00:00:00Z",
        new_pairing_end="2026-06-02T10:00:00Z",
        new_leg_dep="2026-06-02T01:00:00Z",
        new_leg_arr="2026-06-02T07:00:00Z",
        new_pairing_close="2026-06-01T12:00:00Z",
    )
    from test_helpers import validate_error
    res = api.confirm_assignment(
        new_assignment["id"], make_crew_member_headers(cm["id"])
    )
    validate_error(res, "ERR_FAA_DUTY_CAP_EXCEEDED", expected_status=422)
