"""Cascade chains: sick-call → reserve callup → assignment recovery → sick-call close;
and pairing complete → assignment complete → crew status & rolling totals.
"""
from test_helpers import (
    validate_success,
    set_clock,
    setup_completed_pairing_for_crew,
    setup_sick_call_with_reserve_offered,
    get_assignment,
    get_sick_call,
    get_crew_member,
    list_assignments_for,
    make_crew_member_headers,
    TEST_USERS,
)


# ---------------------------------------------------------------------
# Depth-3 cascade: sick-call acknowledge → reserve accept → assignment recovered
# → sick-call closed
# ---------------------------------------------------------------------

def test_sick_call_acknowledge_to_reserve_accept_cascade(api):
    """PRD §2.11: "Accepting that callup cascades the original Assignment
    from `CONFIRMED` to `RECOVERED`, creates a replacement Assignment in
    `CONFIRMED` with `source` set to `RESERVE_CALLUP`, populates the
    callup's `replacement_assignment_id` with the new assignment's id, and
    cascades the SickCall from `ACKNOWLEDGED` to `CLOSED`."
    PRD §3.4: "On success a chain of cascades fires atomically: the original
    Assignment moves from `CONFIRMED` to `RECOVERED`; a replacement Assignment
    is created in `state` `CONFIRMED` with `source` `RESERVE_CALLUP`,
    `crew_member_id` set to the reserve's id (i.e., to `selected_reserve_id`),
    and `seat` copied from the original Assignment; the ReserveCallup's
    `replacement_assignment_id` is set to the new Assignment's id; and the
    SickCall transitions from `ACKNOWLEDGED` to terminal `CLOSED`."

    Design: Difficulty/transitive_cascade/sick_call_acknowledge_to_reserve_accept_to_assignment_recovered_chain
    """
    cm_l, cm_r, pairing, sick_call, callup, a_orig, _cm_r2 = (
        setup_sick_call_with_reserve_offered()
    )
    res = api.accept_reserve_callup(callup["id"], make_crew_member_headers(cm_r["id"]))
    callup_after = validate_success(res, 200)
    assert callup_after["state"] == "ACCEPTED"

    # Original Assignment cascaded to RECOVERED.
    a_orig_after = get_assignment(a_orig["id"])
    assert a_orig_after["state"] == "RECOVERED", (
        f"original Assignment must cascade to RECOVERED, got {a_orig_after['state']!r}"
    )

    # SickCall cascaded to CLOSED.
    sc_after = get_sick_call(sick_call["id"])
    assert sc_after["state"] == "CLOSED", (
        f"SickCall must cascade to CLOSED, got {sc_after['state']!r}"
    )

    # Replacement Assignment exists for reserve, in CONFIRMED, source RESERVE_CALLUP,
    # same pairing and seat.
    reserve_assignments = list_assignments_for(pairing["id"], cm_r["id"])
    assert reserve_assignments, "replacement Assignment must exist for reserve crew"
    replacement = reserve_assignments[0]
    assert replacement["state"] == "CONFIRMED", (
        f"replacement Assignment must be CONFIRMED, got {replacement['state']!r}"
    )
    assert replacement["source"] == "RESERVE_CALLUP", (
        f"replacement Assignment must have source RESERVE_CALLUP, got {replacement['source']!r}"
    )
    assert replacement["seat"] == a_orig["seat"], (
        f"replacement Assignment must carry original seat, "
        f"got {replacement['seat']!r}, expected {a_orig['seat']!r}"
    )
    # ReserveCallup must record the new replacement_assignment_id.
    assert callup_after["replacement_assignment_id"] == replacement["id"], (
        f"ReserveCallup.replacement_assignment_id must point to the new Assignment"
    )


# ---------------------------------------------------------------------
# Depth-2 cascade: pairing complete → assignment complete + crew status
# ---------------------------------------------------------------------

def test_pairing_complete_cascades_assignment_and_crew_status(api):
    """PRD §3.1: "the Pairing's `state` flips to `COMPLETED`, each `ACTIVE`
    Assignment cascades to `COMPLETED` with `actual_duty_end_utc` set to
    `current_utc`, the Assignment's `flight_minutes_credited` and
    `duty_minutes_credited` are locked from the parent Pairing's
    `total_flight_minutes` and `total_duty_minutes`, the owning
    `CrewMember.status` becomes `ON_REST`, `last_off_duty_utc` is set to
    `current_utc`, and the rolling seven-day totals on that crew member are
    recomputed."

    Design: Difficulty/transitive_cascade/pairing_complete_to_assignment_complete_to_crew_member_status_chain
    """
    crew_after, pairing_after, assignment_after = setup_completed_pairing_for_crew(
        employee_code_suffix="0070", seniority_number=70
    )
    assert pairing_after["state"] == "COMPLETED"
    assert assignment_after["state"] == "COMPLETED", (
        f"child Assignment must cascade to COMPLETED, got {assignment_after['state']!r}"
    )
    # Locked-at-completion snapshot.
    assert assignment_after["duty_minutes_credited"] == pairing_after["total_duty_minutes"], (
        f"Assignment.duty_minutes_credited must equal Pairing.total_duty_minutes"
    )
    # Crew status flips to ON_REST.
    assert crew_after["status"] == "ON_REST", (
        f"crew must flip to ON_REST after Pairing COMPLETED, got {crew_after['status']!r}"
    )
    # last_off_duty_utc is set to the clock at /complete (the pairing's scheduled_end).
    assert crew_after["last_off_duty_utc"] is not None, (
        "last_off_duty_utc must be set after Pairing COMPLETED"
    )
    # Rolling 7d total is recomputed and equals the completed Pairing.total_duty_minutes.
    assert crew_after["total_duty_minutes_7d"] == pairing_after["total_duty_minutes"], (
        f"crew.total_duty_minutes_7d ({crew_after['total_duty_minutes_7d']}) must equal "
        f"completed Pairing.total_duty_minutes ({pairing_after['total_duty_minutes']})"
    )
