"""Assignment-create guards: held/discipline/agency/unit-availability/duplicate,
validation-priority conflicts, cross-entity state dependencies, and temporal
overlap.

Queue A (Difficulty): priority_pair_validation_conflict, cross_entity_state_dependency,
resource_temporal_overlap.
Queue B (Corner): validations section (discipline mismatch, reference not found).
"""
from test_helpers import (
    validate_success, validate_error, validate_error_is_one_of,
    set_clock, setup_agency_station_unit, create_incident,
    advance_assignment, get_incident_version, setup_onscene_incident,
    setup_dispatched_incident,
    SUP, DISP,
)


# =====================================================================
# Queue A — priority_pair_validation_conflict
# =====================================================================
def test_held_incident_beats_discipline_mismatch(api):
    """PRD §2.6: "then the held-incident guard (priority eight,
    `ERR_INCIDENT_HELD`); then discipline match (priority nine,
    `ERR_DISCIPLINE_MISMATCH`)".
    PRD §3.4: "If the incident is currently `HELD`, no new unit may be committed
    and the request is rejected with `ERR_INCIDENT_HELD`."

    A wrong-discipline (POLICE) unit assigned to a HELD (EMS) incident returns
    ERR_INCIDENT_HELD — the state guard precedes the discipline guard.

    Design: Difficulty/priority_pair_validation_conflict/held_beats_discipline_mismatch
    """
    set_clock("2026-06-08T12:00:00Z")
    _, _, med, incident, asg = setup_onscene_incident(
        discipline="EMS", capability="MEDIC_ALS",
        incident_type="MEDICAL_EMERGENCY", grid=15, ani="5125550080")
    _, _, pol = setup_agency_station_unit(
        discipline="POLICE", capability="PATROL", grid_x=15, grid_y=15,
        call_sign="PH1", name_prefix="PD H")
    validate_success(api.hold_incident(incident["id"], {"reason": "scene_unsafe"}, SUP), 200)
    v_held = get_incident_version(incident["id"])

    res = api.create_assignment(incident["id"], {
        "expected_incident_version": v_held, "unit_id": pol["id"]}, DISP)
    validate_error(res, "ERR_INCIDENT_HELD")


def test_unit_not_available_beats_referential_close_check(api):
    """PRD §2.6: "then unit availability (priority eleven,
    `ERR_UNIT_NOT_AVAILABLE`)".
    PRD §3.4: "The unit must be `AVAILABLE`; a unit already `DISPATCHED`,
    `ENROUTE`, `ONSCENE`, `CLEARING`, or `OUT_OF_SERVICE` is rejected with
    `ERR_UNIT_NOT_AVAILABLE`."

    Dispatching an already-committed unit to a second incident returns
    ERR_UNIT_NOT_AVAILABLE (the unit-availability constraint fires).

    Design: Difficulty/priority_pair_validation_conflict/open_assignments_beats_report_standard_on_close_then_report
    """
    set_clock("2026-06-09T13:00:00Z")
    _, _, unit, incA, asgA = setup_dispatched_incident(
        discipline="POLICE", capability="PATROL",
        incident_type="ASSAULT_IN_PROGRESS", grid=25, ani="5125550090")
    incB = create_incident(incident_type="ASSAULT_IN_PROGRESS",
                           ali_grid_x=26, ali_grid_y=25, ani="5125550091")
    res = api.create_assignment(incB["id"], {
        "expected_incident_version": incB["version"], "unit_id": unit["id"]}, DISP)
    validate_error(res, "ERR_UNIT_NOT_AVAILABLE")


def test_held_incident_blocks_any_new_commit_regardless_of_unit(api):
    """PRD §3.4: "If the incident is currently `HELD`, no new unit may be
    committed and the request is rejected with `ERR_INCIDENT_HELD`."

    Even a correct-discipline (EMS) AVAILABLE unit is rejected with
    ERR_INCIDENT_HELD when the incident is HELD — the held guard fires ahead of
    the otherwise-passing discipline check.

    Design: Difficulty/priority_pair_validation_conflict/held_beats_discipline_mismatch
    """
    set_clock("2026-06-08T13:00:00Z")
    agency, station, med, incident, asg = setup_onscene_incident(
        discipline="EMS", capability="MEDIC_ALS",
        incident_type="MEDICAL_EMERGENCY", grid=16, ani="5125550081")
    # a second correct-discipline EMS unit, AVAILABLE
    med2 = validate_success(api.create_unit({
        "agency_id": agency["id"], "station_id": station["id"],
        "call_sign": "MH2", "capability": "MEDIC_BLS",
        "grid_x": 16, "grid_y": 16}, SUP), 201)
    validate_success(api.hold_incident(incident["id"], {"reason": "unsafe"}, SUP), 200)
    v_held = get_incident_version(incident["id"])
    res = api.create_assignment(incident["id"], {
        "expected_incident_version": v_held, "unit_id": med2["id"]}, DISP)
    validate_error(res, "ERR_INCIDENT_HELD")


def test_committed_unit_rejected_on_second_distinct_incident(api):
    """PRD §3.4: "The unit must be `AVAILABLE`; a unit already `DISPATCHED`,
    `ENROUTE`, `ONSCENE`, `CLEARING`, or `OUT_OF_SERVICE` is rejected with
    `ERR_UNIT_NOT_AVAILABLE`."

    A unit ONSCENE on incident A is rejected with ERR_UNIT_NOT_AVAILABLE when a
    dispatcher tries to commit it to a fresh incident B.

    Design: Difficulty/priority_pair_validation_conflict/open_assignments_beats_report_standard_on_close_then_report
    """
    set_clock("2026-06-09T14:00:00Z")
    _, _, unit, incA, asgA = setup_onscene_incident(
        discipline="POLICE", capability="PATROL",
        incident_type="ASSAULT_IN_PROGRESS", grid=27, ani="5125550092")
    incB = create_incident(incident_type="ASSAULT_IN_PROGRESS",
                           ali_grid_x=28, ali_grid_y=27, ani="5125550093")
    res = api.create_assignment(incB["id"], {
        "expected_incident_version": incB["version"], "unit_id": unit["id"]}, DISP)
    validate_error(res, "ERR_UNIT_NOT_AVAILABLE")


# =====================================================================
# Queue A — cross_entity_state_dependency
# =====================================================================
def test_dispatch_blocked_when_unit_enroute_on_another_incident(api):
    """PRD §3.4: "The unit must be `AVAILABLE`; a unit already `DISPATCHED`,
    `ENROUTE`, `ONSCENE`, `CLEARING`, or `OUT_OF_SERVICE` is rejected with
    `ERR_UNIT_NOT_AVAILABLE`."

    A unit ENROUTE on incident A cannot be dispatched to incident B.

    Design: Difficulty/cross_entity_state_dependency/dispatch_blocked_when_unit_not_available
    """
    set_clock("2026-06-12T00:00:00Z")
    _, _, unit, incA, asgA = setup_dispatched_incident(
        discipline="POLICE", capability="PATROL",
        incident_type="ASSAULT_IN_PROGRESS", grid=35, ani="5125550120")
    advance_assignment(asgA["id"], unit["id"], "ENROUTE")
    incB = create_incident(incident_type="ASSAULT_IN_PROGRESS",
                           ali_grid_x=36, ali_grid_y=35, ani="5125550121")
    res = api.create_assignment(incB["id"], {
        "expected_incident_version": incB["version"], "unit_id": unit["id"]}, DISP)
    validate_error(res, "ERR_UNIT_NOT_AVAILABLE")


def test_dispatch_blocked_when_agency_offline(api):
    """PRD §3.4: "The unit's agency must be `ONLINE` for an in-jurisdiction
    dispatch, or `MUTUAL_AID_ONLY` only when no `ONLINE` unit of that discipline
    exists; an agency that is `OFFLINE`, or `MUTUAL_AID_ONLY` while an `ONLINE`
    unit of that discipline still exists, is rejected with
    `ERR_AGENCY_UNAVAILABLE`."

    The unit is AVAILABLE but its agency is OFFLINE → ERR_AGENCY_UNAVAILABLE.

    Design: Difficulty/cross_entity_state_dependency/dispatch_blocked_when_agency_unavailable
    """
    set_clock("2026-06-13T00:00:00Z")
    agency, _, unit = setup_agency_station_unit(
        discipline="POLICE", capability="PATROL", grid_x=45, grid_y=45,
        call_sign="PO1", name_prefix="PD Off")
    incident = create_incident(incident_type="ASSAULT_IN_PROGRESS",
                               ali_grid_x=45, ali_grid_y=45, ani="5125550130")
    validate_success(api.set_agency_status(agency["id"], "MUTUAL_AID_ONLY", SUP), 200)
    validate_success(api.set_agency_status(agency["id"], "OFFLINE", SUP), 200)
    res = api.create_assignment(incident["id"], {
        "expected_incident_version": incident["version"], "unit_id": unit["id"]}, DISP)
    validate_error(res, "ERR_AGENCY_UNAVAILABLE")


def test_dispatch_blocked_when_unit_dispatched_on_another_incident(api):
    """PRD §3.4: "The unit must be `AVAILABLE`; a unit already `DISPATCHED`,
    `ENROUTE`, `ONSCENE`, `CLEARING`, or `OUT_OF_SERVICE` is rejected with
    `ERR_UNIT_NOT_AVAILABLE`."

    A unit DISPATCHED (committed but not yet enroute) on incident A blocks a
    fresh dispatch to incident B — the incident B PENDING->DISPATCHED transition
    depends on the referenced Unit being AVAILABLE.

    Design: Difficulty/cross_entity_state_dependency/dispatch_blocked_when_unit_not_available
    """
    set_clock("2026-06-12T01:00:00Z")
    _, _, unit, incA, asgA = setup_dispatched_incident(
        discipline="POLICE", capability="PATROL",
        incident_type="ASSAULT_IN_PROGRESS", grid=37, ani="5125550122")
    incB = create_incident(incident_type="ASSAULT_IN_PROGRESS",
                           ali_grid_x=38, ali_grid_y=37, ani="5125550123")
    res = api.create_assignment(incB["id"], {
        "expected_incident_version": incB["version"], "unit_id": unit["id"]}, DISP)
    validate_error(res, "ERR_UNIT_NOT_AVAILABLE")
    incB_after = validate_success(api.get_incident(incB["id"], DISP), 200)
    assert incB_after["lifecycle_status"] == "PENDING"


def test_dispatch_blocked_when_agency_mutual_aid_only_with_online_alternative(api):
    """PRD §3.4: "The unit's agency must be `ONLINE` for an in-jurisdiction
    dispatch, or `MUTUAL_AID_ONLY` only when no `ONLINE` unit of that discipline
    exists; an agency that is `OFFLINE`, or `MUTUAL_AID_ONLY` while an `ONLINE`
    unit of that discipline still exists, is rejected with
    `ERR_AGENCY_UNAVAILABLE`."

    A MUTUAL_AID_ONLY agency's unit is rejected with ERR_AGENCY_UNAVAILABLE while
    an ONLINE POLICE unit of the same discipline still exists.

    Design: Difficulty/cross_entity_state_dependency/dispatch_blocked_when_agency_unavailable
    """
    set_clock("2026-06-13T01:00:00Z")
    mutual_agency, _, mutual_unit = setup_agency_station_unit(
        discipline="POLICE", capability="PATROL", grid_x=46, grid_y=46,
        call_sign="PM1", name_prefix="PD Mutual")
    # an ONLINE POLICE unit of the same discipline still exists
    setup_agency_station_unit(
        discipline="POLICE", capability="PATROL", grid_x=90, grid_y=90,
        call_sign="PN1", name_prefix="PD Online")
    incident = create_incident(incident_type="ASSAULT_IN_PROGRESS",
                               ali_grid_x=46, ali_grid_y=46, ani="5125550131")
    validate_success(api.set_agency_status(mutual_agency["id"], "MUTUAL_AID_ONLY", SUP), 200)
    res = api.create_assignment(incident["id"], {
        "expected_incident_version": incident["version"], "unit_id": mutual_unit["id"]}, DISP)
    validate_error(res, "ERR_AGENCY_UNAVAILABLE")


# =====================================================================
# Queue A — resource_temporal_overlap
# =====================================================================
def test_unit_single_open_commitment_blocks_second_dispatch(api):
    """PRD §3.4: "The unit must be `AVAILABLE`; a unit already `DISPATCHED`,
    `ENROUTE`, `ONSCENE`, `CLEARING`, or `OUT_OF_SERVICE` is rejected with
    `ERR_UNIT_NOT_AVAILABLE`."

    A unit DISPATCHED to incident A (commitment interval open) cannot be
    dispatched to incident B.

    Design: Difficulty/resource_temporal_overlap/unit_single_commitment_no_overlap
    """
    set_clock("2026-06-14T00:00:00Z")
    _, _, unit, incA, asgA = setup_dispatched_incident(
        discipline="POLICE", capability="PATROL",
        incident_type="ASSAULT_IN_PROGRESS", grid=55, ani="5125550140")
    incB = create_incident(incident_type="ASSAULT_IN_PROGRESS",
                           ali_grid_x=56, ali_grid_y=55, ani="5125550141")
    res = api.create_assignment(incB["id"], {
        "expected_incident_version": incB["version"], "unit_id": unit["id"]}, DISP)
    validate_error(res, "ERR_UNIT_NOT_AVAILABLE")


def test_redispatch_same_unit_after_clear_on_same_incident_duplicate(api):
    """PRD §3.4: "A unit may not be committed to the same incident twice through
    a non-cancelled assignment, which is rejected with
    `ERR_DUPLICATE_ASSIGNMENT`."

    After the unit's assignment on this incident is CLEARED (a non-cancelled
    assignment) the unit is AVAILABLE again, so the availability guard passes;
    re-dispatching it to the same incident is then cleanly rejected with
    ERR_DUPLICATE_ASSIGNMENT.

    Design: Difficulty/resource_temporal_overlap/incident_unit_duplicate_assignment_no_self_overlap
    """
    set_clock("2026-06-15T00:00:00Z")
    _, _, unit, incident, asg1 = setup_dispatched_incident(
        discipline="POLICE", capability="PATROL",
        incident_type="ASSAULT_IN_PROGRESS", grid=60, ani="5125550150")
    advance_assignment(asg1["id"], unit["id"], "ENROUTE")
    advance_assignment(asg1["id"], unit["id"], "CLEAR")
    unit_after = validate_success(api.get_unit(unit["id"], DISP), 200)
    assert unit_after["status"] == "AVAILABLE"  # availability guard now passes
    v1 = get_incident_version(incident["id"])
    res = api.create_assignment(incident["id"], {
        "expected_incident_version": v1, "unit_id": unit["id"]}, DISP)
    validate_error(res, "ERR_DUPLICATE_ASSIGNMENT")


def test_same_unit_redispatch_blocked_after_enroute_on_same_incident(api):
    """PRD §3.4: "A unit may not be committed to the same incident twice through
    a non-cancelled assignment, which is rejected with
    `ERR_DUPLICATE_ASSIGNMENT`."
    PRD §3.4: "The unit must be `AVAILABLE`; a unit already `DISPATCHED`,
    `ENROUTE`, `ONSCENE`, `CLEARING`, or `OUT_OF_SERVICE` is rejected with
    `ERR_UNIT_NOT_AVAILABLE`."

    A unit driven ENROUTE on this incident cannot be re-committed to the same
    incident; both the availability guard (priority 11) and the duplicate guard
    (priority 12) name this rejection, so accept either.

    Design: Difficulty/resource_temporal_overlap/incident_unit_duplicate_assignment_no_self_overlap
    """
    set_clock("2026-06-15T01:00:00Z")
    _, _, unit, incident, asg1 = setup_dispatched_incident(
        discipline="POLICE", capability="PATROL",
        incident_type="ASSAULT_IN_PROGRESS", grid=61, ani="5125550151")
    advance_assignment(asg1["id"], unit["id"], "ENROUTE")
    v1 = get_incident_version(incident["id"])
    res = api.create_assignment(incident["id"], {
        "expected_incident_version": v1, "unit_id": unit["id"]}, DISP)
    validate_error_is_one_of(res, ["ERR_DUPLICATE_ASSIGNMENT", "ERR_UNIT_NOT_AVAILABLE"])


def test_unit_single_commitment_second_test_get_state(api):
    """PRD §3.4: "drives the unit's `status` to `DISPATCHED`, and sets the unit's
    `active_incident_id` to this incident."

    A unit DISPATCHED to A holds active_incident_id == A; the overlap rejection
    on B leaves that commitment intact (exclusive single-occupancy).

    Design: Difficulty/resource_temporal_overlap/unit_single_commitment_no_overlap
    """
    set_clock("2026-06-14T02:00:00Z")
    _, _, unit, incA, asgA = setup_dispatched_incident(
        discipline="POLICE", capability="PATROL",
        incident_type="ASSAULT_IN_PROGRESS", grid=57, ani="5125550142")
    incB = create_incident(incident_type="ASSAULT_IN_PROGRESS",
                           ali_grid_x=58, ali_grid_y=55, ani="5125550143")
    res = api.create_assignment(incB["id"], {
        "expected_incident_version": incB["version"], "unit_id": unit["id"]}, DISP)
    validate_error(res, "ERR_UNIT_NOT_AVAILABLE")
    unit_after = validate_success(api.get_unit(unit["id"], DISP), 200)
    assert unit_after["status"] == "DISPATCHED"
    assert unit_after["active_incident_id"] == incA["id"]
