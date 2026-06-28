"""Non-linear state machines, cascade chains, and compensating invariants.

Queue A (Difficulty): non_linear_state_machine, transitive_cascade,
compensating_invariant.
"""
from test_helpers import (
    validate_success, validate_paginated,
    set_clock, setup_agency_station_unit, create_incident, dispatch_unit,
    advance_assignment, setup_onscene_incident,
    setup_dispatched_incident, make_field_unit_headers,
    SUP, DISP,
)


# =====================================================================
# Queue A — non_linear_state_machine
# =====================================================================
def test_onscene_revert_to_enroute_keeps_incident_active(api):
    """PRD §3.5: "A unit pulled back off scene may **re-stage** from
    `ONSCENE → ENROUTE`; this clears the assignment's `onscene_at` and returns
    the unit's `status` to `ENROUTE`, but it does not undo the incident's
    `first_onscene_at` — the incident remains `ACTIVE`."

    Design: Difficulty/non_linear_state_machine/assignment_onscene_revert_to_enroute_cycle
    """
    set_clock("2026-06-04T09:00:00Z")
    _, _, unit, incident, asg = setup_onscene_incident(
        discipline="EMS", capability="MEDIC_ALS",
        incident_type="MEDICAL_EMERGENCY", grid=20, ani="5125550040")
    advance_assignment(asg["id"], unit["id"], "ENROUTE")

    asg_after = validate_success(api.get_assignment(asg["id"], DISP), 200)
    unit_after = validate_success(api.get_unit(unit["id"], DISP), 200)
    inc_after = validate_success(api.get_incident(incident["id"], DISP), 200)
    assert asg_after["status"] == "ENROUTE"
    assert asg_after["onscene_at"] is None
    assert unit_after["status"] == "ENROUTE"
    assert inc_after["lifecycle_status"] == "ACTIVE"


def test_onscene_revert_then_back_onscene_cycles_assignment(api):
    """PRD §3.5: "A unit pulled back off scene may **re-stage** from
    `ONSCENE → ENROUTE`; this clears the assignment's `onscene_at` and returns
    the unit's `status` to `ENROUTE`, but it does not undo the incident's
    `first_onscene_at` — the incident remains `ACTIVE`."
    PRD §3.5: "From `ENROUTE`, going **onscene** moves the assignment
    `ENROUTE → ONSCENE`, stamps its `onscene_at`, drives the unit's `status` to
    `ONSCENE`".

    Re-stage ENROUTE then ONSCENE again — the cycle is permitted and re-stamps
    onscene_at; incident stays ACTIVE throughout.

    Design: Difficulty/non_linear_state_machine/assignment_onscene_revert_to_enroute_cycle
    """
    set_clock("2026-06-04T09:30:00Z")
    _, _, unit, incident, asg = setup_onscene_incident(
        discipline="EMS", capability="MEDIC_ALS",
        incident_type="MEDICAL_EMERGENCY", grid=21, ani="5125550041")
    advance_assignment(asg["id"], unit["id"], "ENROUTE")
    re_onscene = validate_success(api.set_assignment_status(asg["id"], "ONSCENE",
                                  make_field_unit_headers(unit["id"])), 200)
    assert re_onscene["status"] == "ONSCENE"
    assert re_onscene["onscene_at"] is not None
    inc_after = validate_success(api.get_incident(incident["id"], DISP), 200)
    assert inc_after["lifecycle_status"] == "ACTIVE"


def test_priority_cyclic_escalation_independent_of_lifecycle(api):
    """PRD §3.7: "**Escalation** — invoked manually by a supervisor, or by the
    timer-driven system actor when an incident has gone too long without a first
    dispatch past its SLA grace — raises urgency by one step: the `priority_level`
    is decremented by one toward 1, the `escalation_count` is incremented by one,
    and the incident's `version` is incremented."
    PRD §3.7: "Because priority is cyclic, an incident may escalate repeatedly
    over its life."

    ALARM (base 4), never dispatched: two escalations → priority 2,
    escalation_count 2, lifecycle still PENDING.

    Design: Difficulty/non_linear_state_machine/incident_priority_cyclic_escalation_parallel_dimension
    """
    set_clock("2026-06-05T00:00:00Z")
    incident = create_incident(incident_type="ALARM", ali_grid_x=400,
                               ali_grid_y=400, ani="5125550050")
    validate_success(api.escalate_incident(incident["id"], {"reason": "no_unit_yet"}, SUP), 200)
    validate_success(api.escalate_incident(incident["id"], {"reason": "no_unit_yet"}, SUP), 200)
    inc = validate_success(api.get_incident(incident["id"], DISP), 200)
    assert inc["priority_level"] == 2
    assert inc["escalation_count"] == 2
    assert inc["lifecycle_status"] == "PENDING"


def test_single_escalation_decrements_priority_and_bumps_count(api):
    """PRD §3.7: "the `priority_level` is decremented by one toward 1, the
    `escalation_count` is incremented by one, and the incident's `version` is
    incremented."

    One escalation on an ALARM (base 4, lifecycle PENDING) → priority 3,
    escalation_count 1, version incremented, lifecycle unchanged.

    Design: Difficulty/non_linear_state_machine/incident_priority_cyclic_escalation_parallel_dimension
    """
    set_clock("2026-06-05T01:00:00Z")
    incident = create_incident(incident_type="ALARM", ali_grid_x=401,
                               ali_grid_y=401, ani="5125550051")
    before_v = incident["version"]
    validate_success(api.escalate_incident(incident["id"], {"reason": "timer"}, SUP), 200)
    inc = validate_success(api.get_incident(incident["id"], DISP), 200)
    assert inc["priority_level"] == 3
    assert inc["escalation_count"] == 1
    assert inc["version"] == before_v + 1
    assert inc["lifecycle_status"] == "PENDING"


# =====================================================================
# Queue A — transitive_cascade
# =====================================================================
def test_close_cascades_assignment_cleared_and_unit_freed(api):
    """PRD §3.8: "Closing requires that the incident be `DISPATCHED`, `ACTIVE`,
    or `HELD`, and that every assignment on the incident already be `CLEARED` or
    `CANCELLED`".
    PRD §3.8: "On a successful close the platform sets the incident's
    `closed_at`, copies the disposition's outcome into the incident's
    `disposition_code`".
    PRD §3.5: "from `ONSCENE`, clearing moves it `ONSCENE → CLEARED`, stamps
    `cleared_at`, and walks the unit's `status` through `CLEARING` and on to
    `AVAILABLE` while clearing the unit's `active_incident_id`".

    Clear the on-scene assignment (legal close precondition), then close the
    ACTIVE incident: incident CLOSED, assignment CLEARED, unit AVAILABLE with
    active_incident_id cleared.

    Design: Difficulty/transitive_cascade/close_cascades_assignment_then_unit_depth3
    """
    set_clock("2026-06-06T10:00:00Z")
    _, _, unit, incident, asg = setup_onscene_incident(
        discipline="EMS", capability="MEDIC_ALS",
        incident_type="MEDICAL_EMERGENCY", grid=30, ani="5125550060")
    advance_assignment(asg["id"], unit["id"], "CLEAR")
    validate_success(api.create_disposition(incident["id"], {
        "disposition_code": "TRANSPORT", "narrative": "Patient transported"}, SUP), 201)

    inc = validate_success(api.get_incident(incident["id"], DISP), 200)
    asg_after = validate_success(api.get_assignment(asg["id"], DISP), 200)
    unit_after = validate_success(api.get_unit(unit["id"], DISP), 200)
    assert inc["lifecycle_status"] == "CLOSED"
    assert asg_after["status"] == "CLEARED"
    assert unit_after["status"] == "AVAILABLE"
    assert unit_after["active_incident_id"] is None


def test_close_sets_closed_at_and_disposition_code(api):
    """PRD §3.8: "On a successful close the platform sets the incident's
    `closed_at`, copies the disposition's outcome into the incident's
    `disposition_code`, increments the incident's `version`".
    PRD §3.8: "Closing requires ... that every assignment on the incident already
    be `CLEARED` or `CANCELLED`".

    Clear the on-scene assignment (legal close precondition), then a close records
    closed_at, propagates the disposition_code onto the incident, and increments
    its version.

    Design: Difficulty/transitive_cascade/close_cascades_assignment_then_unit_depth3
    """
    set_clock("2026-06-06T11:00:00Z")
    _, _, unit, incident, asg = setup_onscene_incident(
        discipline="EMS", capability="MEDIC_ALS",
        incident_type="MEDICAL_EMERGENCY", grid=31, ani="5125550061")
    advance_assignment(asg["id"], unit["id"], "CLEAR")
    before = validate_success(api.get_incident(incident["id"], DISP), 200)
    validate_success(api.create_disposition(incident["id"], {
        "disposition_code": "REPORT_TAKEN", "narrative": "done"}, SUP), 201)
    inc = validate_success(api.get_incident(incident["id"], DISP), 200)
    assert inc["closed_at"] is not None
    assert inc["disposition_code"] == "REPORT_TAKEN"
    assert inc["version"] == before["version"] + 1


def test_cancel_only_dispatched_assignment_reverts_incident_to_pending(api):
    """PRD §3.5: "A cancellation from `DISPATCHED` carries one further cascade:
    if the cancelled assignment was the only non-terminal assignment on the
    incident and it had carried the incident's first dispatch with no unit ever
    having reached the scene, the incident reverts `DISPATCHED → PENDING` and its
    `first_dispatch_at` is cleared, returning the incident to an undispatched
    state."

    Design: Difficulty/transitive_cascade/cancel_only_assignment_reverts_incident_depth2
    """
    set_clock("2026-06-07T11:00:00Z")
    _, _, unit, incident, asg = setup_dispatched_incident(
        discipline="POLICE", capability="PATROL",
        incident_type="ASSAULT_IN_PROGRESS", grid=40, ani="5125550070")
    validate_success(api.set_assignment_status(asg["id"], "CANCEL", DISP), 200)

    asg_after = validate_success(api.get_assignment(asg["id"], DISP), 200)
    unit_after = validate_success(api.get_unit(unit["id"], DISP), 200)
    inc = validate_success(api.get_incident(incident["id"], DISP), 200)
    assert asg_after["status"] == "CANCELLED"
    assert unit_after["status"] == "AVAILABLE"
    assert inc["lifecycle_status"] == "PENDING"
    assert inc["first_dispatch_at"] is None


def test_cancel_dispatched_assignment_frees_unit_active_incident(api):
    """PRD §3.5: "from `DISPATCHED`, cancelling moves it `DISPATCHED → CANCELLED`
    and returns the unit to `AVAILABLE` with `active_incident_id` cleared".

    The cancel of the sole DISPATCHED assignment frees the unit's
    active_incident_id back to null (the unit-level hop of the revert cascade).

    Design: Difficulty/transitive_cascade/cancel_only_assignment_reverts_incident_depth2
    """
    set_clock("2026-06-07T12:00:00Z")
    _, _, unit, incident, asg = setup_dispatched_incident(
        discipline="POLICE", capability="PATROL",
        incident_type="ASSAULT_IN_PROGRESS", grid=41, ani="5125550071")
    assert validate_success(api.get_unit(unit["id"], DISP), 200)["active_incident_id"] == incident["id"]
    validate_success(api.set_assignment_status(asg["id"], "CANCEL", DISP), 200)
    unit_after = validate_success(api.get_unit(unit["id"], DISP), 200)
    assert unit_after["status"] == "AVAILABLE"
    assert unit_after["active_incident_id"] is None


# =====================================================================
# Queue A — compensating_invariant
# =====================================================================
def test_dispatch_then_cancel_conserves_available_unit_count(api):
    """PRD §3.5: "from `DISPATCHED`, cancelling moves it `DISPATCHED → CANCELLED`
    and returns the unit to `AVAILABLE` with `active_incident_id` cleared".

    Available-unit count is the conserved quantity: one AVAILABLE PATROL unit
    before dispatch; after dispatch+cancel it is AVAILABLE again, count unchanged.

    Design: Difficulty/compensating_invariant/dispatch_then_cancel_conserves_available_unit_count
    """
    set_clock("2026-06-16T00:00:00Z")
    agency, _, unit, incident, asg = setup_dispatched_incident(
        discipline="POLICE", capability="PATROL",
        incident_type="ASSAULT_IN_PROGRESS", grid=65, ani="5125550160")
    validate_success(api.set_assignment_status(asg["id"], "CANCEL", DISP), 200)
    unit_after = validate_success(api.get_unit(unit["id"], DISP), 200)
    assert unit_after["status"] == "AVAILABLE"
    assert unit_after["active_incident_id"] is None

    units, _ = validate_paginated(
        api.list_units(DISP, params={"agency_id": agency["id"], "status": "AVAILABLE"}))
    assert len([u for u in units if u["agency_id"] == agency["id"]]) == 1


def test_dispatch_removes_unit_from_available_then_cancel_restores(api):
    """PRD §3.4: "drives the unit's `status` to `DISPATCHED`, and sets the unit's
    `active_incident_id` to this incident."
    PRD §3.5: "from `DISPATCHED`, cancelling moves it `DISPATCHED → CANCELLED`
    and returns the unit to `AVAILABLE` with `active_incident_id` cleared".

    Forward (dispatch) removes the unit from AVAILABLE; compensating (cancel)
    returns it — the count is identical before dispatch and after cancel.

    Design: Difficulty/compensating_invariant/dispatch_then_cancel_conserves_available_unit_count
    """
    set_clock("2026-06-16T01:00:00Z")
    agency, station, unit = setup_agency_station_unit(
        discipline="POLICE", capability="PATROL", grid_x=66, grid_y=66,
        call_sign="PI2", name_prefix="PD Inv2")

    def avail_count():
        units, _ = validate_paginated(
            api.list_units(DISP, params={"agency_id": agency["id"], "status": "AVAILABLE"}))
        return len([u for u in units if u["agency_id"] == agency["id"]])

    before = avail_count()
    incident = create_incident(incident_type="ASSAULT_IN_PROGRESS",
                               ali_grid_x=66, ali_grid_y=66, ani="5125550161")
    asg = dispatch_unit(incident["id"], incident["version"], unit_id=unit["id"])
    assert avail_count() == before - 1
    validate_success(api.set_assignment_status(asg["id"], "CANCEL", DISP), 200)
    assert avail_count() == before


def test_hold_then_resume_conserves_onscene_assignment_count(api):
    """PRD §3.7: "Holding moves the `lifecycle_status` `ACTIVE → HELD` and is
    permitted only when the incident is `ACTIVE` and at least one assignment on
    it is `ONSCENE`".
    PRD §3.7: "**Resuming** moves the incident `HELD → ACTIVE`, unfreezing it".

    HOLD freezes without touching assignment status; RESUME thaws — the
    ONSCENE-assignment count is identical before HOLD and after RESUME.

    Design: Difficulty/compensating_invariant/hold_then_resume_conserves_onscene_assignment_count
    """
    set_clock("2026-06-17T00:00:00Z")
    _, _, unit, incident, asg = setup_onscene_incident(
        discipline="EMS", capability="MEDIC_ALS",
        incident_type="MEDICAL_EMERGENCY", grid=75, ani="5125550170")
    validate_success(api.hold_incident(incident["id"], {"reason": "scene_safety"}, SUP), 200)
    validate_success(api.resume_incident(incident["id"], SUP), 200)

    inc = validate_success(api.get_incident(incident["id"], DISP), 200)
    asg_after = validate_success(api.get_assignment(asg["id"], DISP), 200)
    assert inc["lifecycle_status"] == "ACTIVE"
    assert asg_after["status"] == "ONSCENE"
    onscene, _ = validate_paginated(
        api.list_assignments(DISP, params={"incident_id": incident["id"], "status": "ONSCENE"}))
    assert len([a for a in onscene if a["incident_id"] == incident["id"]]) == 1


def test_hold_freezes_incident_without_draining_assignment(api):
    """PRD §3.7: "Holding moves the `lifecycle_status` `ACTIVE → HELD`".
    PRD §3.7: "While an incident is `HELD` no new units may be committed to it".

    The HOLD step leaves the single ONSCENE assignment untouched (it is the
    freeze that conserves field state, not a drain) — the count is 1 while HELD.

    Design: Difficulty/compensating_invariant/hold_then_resume_conserves_onscene_assignment_count
    """
    set_clock("2026-06-17T01:00:00Z")
    _, _, unit, incident, asg = setup_onscene_incident(
        discipline="EMS", capability="MEDIC_ALS",
        incident_type="MEDICAL_EMERGENCY", grid=76, ani="5125550171")
    validate_success(api.hold_incident(incident["id"], {"reason": "scene_safety"}, SUP), 200)
    inc = validate_success(api.get_incident(incident["id"], DISP), 200)
    asg_after = validate_success(api.get_assignment(asg["id"], DISP), 200)
    assert inc["lifecycle_status"] == "HELD"
    assert asg_after["status"] == "ONSCENE"
