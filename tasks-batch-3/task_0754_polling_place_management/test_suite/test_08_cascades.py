"""Multi-hop cascade chains (queue A: transitive_cascade)."""
from test_helpers import (
    TEST_USERS,
    validate_success, get_success_data,
    setup_shift_scheduled, setup_open_place,
    create_incident_payload,
)

ADMIN = TEST_USERS["election_admin_headers"]
CAPTAIN = TEST_USERS["precinct_captain_headers"]
SUPPORT = TEST_USERS["support_agent_headers"]


def _close_voting_over_checked_in_shift(api):
    """Place OPEN, worker CHECKED_IN on a 06:00-17:00 shift (checked in at 06:00, clock at
    15:30), then close the election's voting window. Returns ctx with refreshed resources."""
    ctx = setup_shift_scheduled(api, scheduled_start="2026-11-03T06:00:00Z",
                                scheduled_end="2026-11-03T17:00:00Z")
    sid = ctx["shift"]["id"]
    get_success_data(api.set_clock("2026-11-03T06:00:00Z", ADMIN))
    get_success_data(api.check_in(sid, CAPTAIN))
    get_success_data(api.set_clock("2026-11-03T15:30:00Z", ADMIN))
    get_success_data(api.close_voting(ctx["election"]["id"], ADMIN))
    ctx["shift"] = get_success_data(api.get_shift(sid, ADMIN))
    ctx["place"] = get_success_data(api.get_polling_place(ctx["place"]["id"], ADMIN))
    ctx["worker"] = get_success_data(api.get_poll_worker(ctx["worker"]["id"], ADMIN))
    return ctx


# ---- transitive_cascade / election_close_cascades_place_shift_payroll_depth3 ----

def test_close_voting_cascades_place_and_shift(api):
    """PRD §2.5: "When an election closes its voting window, every child polling place still
    in posture `OPEN` is transitioned `OPEN → CLOSED`. Each such place-close in turn
    auto-checks-out every one of its shifts in status `CHECKED_IN` (`CHECKED_IN →
    CHECKED_OUT`, stamping `check_out_time` from the logical clock), and each auto-check-out
    computes pay and accrues it to the worker exactly as a manual check-out would."

    Design: Difficulty/transitive_cascade/election_close_cascades_place_shift_payroll_depth3
    """
    ctx = _close_voting_over_checked_in_shift(api)
    assert ctx["place"]["readiness_posture"] == "CLOSED"
    assert ctx["shift"]["status"] == "CHECKED_OUT"


def test_close_voting_cascade_accrues_payroll_and_stipend(api):
    """PRD §2.5: "each auto-check-out computes pay and accrues it to the worker exactly as a
    manual check-out would."
    PRD §3.5: "`gross_pay_cents` is added to the worker's `accrued_payroll_cents`, and if the
    worker's `stipend_paid` flag is still false, a one-time training stipend of 5000 cents is
    additionally added to `accrued_payroll_cents` and `stipend_paid` is set to true."

    Design: Difficulty/transitive_cascade/election_close_cascades_place_shift_payroll_depth3
    """
    ctx = _close_voting_over_checked_in_shift(api)
    assert ctx["shift"]["gross_pay_cents"] == 18706, (
        f"9.5h worked = 18706 gross, got {ctx['shift']['gross_pay_cents']}"
    )
    assert ctx["worker"]["accrued_payroll_cents"] == 23706, (
        f"18706 gross + 5000 one-time stipend = 23706, got {ctx['worker']['accrued_payroll_cents']}"
    )


# ---- transitive_cascade / incident_escalate_cascades_equipment_place_depth2 ----

def _escalate_equipment_incident_at_open_place(api):
    """Open place with an OPERATIONAL scanner; an EQUIPMENT incident on that scanner is
    OPEN -> ACKNOWLEDGED -> ESCALATED. Returns (incident, equipment, place) refreshed."""
    ctx = setup_open_place(api)
    eq_id = ctx["equipment"]["id"]
    inc = get_success_data(
        api.create_incident(
            create_incident_payload(ctx["place"]["id"], "EQUIPMENT", "scanner jammed",
                                    equipment_unit_id=eq_id),
            SUPPORT,
        )
    )
    get_success_data(api.acknowledge_incident(inc["id"], SUPPORT))
    inc = get_success_data(api.escalate_incident(inc["id"], SUPPORT))
    eq = get_success_data(api.get_equipment(eq_id, ADMIN))
    place = get_success_data(api.get_polling_place(ctx["place"]["id"], ADMIN))
    return inc, eq, place


def test_escalate_marks_incident_critical(api):
    """PRD §3.8: "Escalating takes it to `ESCALATED` from either `OPEN` or `ACKNOWLEDGED`,
    sets `severity` to `CRITICAL`, and — when the incident's `category` is `EQUIPMENT` and an
    `equipment_unit_id` is set — drives that equipment unit `OPERATIONAL → OUT_OF_SERVICE`,
    which in turn suspends the unit's owning place if it was open (the cascade of Section
    2.5)."

    Design: Difficulty/transitive_cascade/incident_escalate_cascades_equipment_place_depth2
    """
    inc, eq, place = _escalate_equipment_incident_at_open_place(api)
    assert inc["status"] == "ESCALATED"
    assert inc["severity"] == "CRITICAL"


def test_escalate_cascade_disables_equipment_and_suspends_place(api):
    """PRD §2.5: "Escalating an equipment-related incident takes the referenced equipment unit
    `OPERATIONAL → OUT_OF_SERVICE`; if that unit's owning place is `OPEN`, the loss of its
    operational guarantee forces the place `OPEN → SUSPENDED`."

    Design: Difficulty/transitive_cascade/incident_escalate_cascades_equipment_place_depth2
    """
    inc, eq, place = _escalate_equipment_incident_at_open_place(api)
    assert eq["status"] == "OUT_OF_SERVICE"
    assert place["readiness_posture"] == "SUSPENDED"
