"""Gating of the SETUP -> OPEN transition: quorum, equipment, safety/fiscal precedence.

Queue A (difficulty): boundary_precision_check, cross_entity_state_dependency,
priority_pair_validation_conflict. Queue B (validations): voting-not-open.
"""
from test_helpers import (
    TEST_USERS,
    validate_success, validate_error, get_success_data, ApiErrorId,
    create_election, create_place, deploy_equipment, create_kit_at_place,
    create_certified_worker, create_active_assignment,
    create_incident_payload,
)

ADMIN = TEST_USERS["election_admin_headers"]
CAPTAIN = TEST_USERS["precinct_captain_headers"]
CUSTODY = TEST_USERS["custody_officer_headers"]
SUPPORT = TEST_USERS["support_agent_headers"]


def _open_ready_place(api, *, min_workers_required=1, staffing_capacity=5, num_active_workers=1):
    """Election VOTING_OPEN + place + deployed scanner + kit AT_PLACE + N active workers.
    Place left in SETUP. Returns (election, place)."""
    el = create_election(api, open_voting=True)
    pp = create_place(api, election_id=el["id"], min_workers_required=min_workers_required,
                      staffing_capacity=staffing_capacity, station_capacity=5)
    deploy_equipment(api, place_id=pp["id"])
    create_kit_at_place(api, election_id=el["id"], place_id=pp["id"])
    for i in range(num_active_workers):
        w = create_certified_worker(api, full_name=f"W{i}", email=f"w{i}@x.com")
        create_active_assignment(api, worker_id=w["id"], place_id=pp["id"])
    return el, pp


# ---- boundary_precision_check / quorum_open_ge_boundary ----

def test_open_below_quorum_is_understaffed(api):
    """PRD §3.2: "and finally that `slots_filled` be greater than or equal to
    `min_workers_required` (otherwise `ERR_UNDERSTAFFED`, 422)."

    Design: Difficulty/boundary_precision_check/quorum_open_ge_boundary
    """
    el, pp = _open_ready_place(api, min_workers_required=2, num_active_workers=1)
    resp = api.open_place(pp["id"], CAPTAIN)
    validate_error(resp, ApiErrorId.ERR_UNDERSTAFFED)
    place = get_success_data(api.get_polling_place(pp["id"], ADMIN))
    assert place["slots_filled"] == 1, f"expected slots_filled 1 (below quorum 2), got {place['slots_filled']}"


def test_open_at_quorum_boundary_succeeds(api):
    """PRD §3.2: "and finally that `slots_filled` be greater than or equal to
    `min_workers_required` (otherwise `ERR_UNDERSTAFFED`, 422). When all pass,
    `readiness_posture` is set to `OPEN` and the place's `version` increments."

    Design: Difficulty/boundary_precision_check/quorum_open_ge_boundary
    """
    el, pp = _open_ready_place(api, min_workers_required=2, num_active_workers=2)
    data = validate_success(api.open_place(pp["id"], CAPTAIN))
    assert data["readiness_posture"] == "OPEN", (
        f"slots_filled==min_workers_required==2 should open at the boundary, "
        f"got posture {data['readiness_posture']}"
    )


# ---- cross_entity_state_dependency / open_requires_equipment_operational ----

def _place_with_out_of_service_scanner(api):
    """Staffed, kit AT_PLACE, quorum met; scanner driven OUT_OF_SERVICE via an escalated
    equipment incident. Place still SETUP. Returns (place, equipment)."""
    el = create_election(api, open_voting=True)
    pp = create_place(api, election_id=el["id"], min_workers_required=1)
    eq = deploy_equipment(api, place_id=pp["id"])
    create_kit_at_place(api, election_id=el["id"], place_id=pp["id"])
    w = create_certified_worker(api)
    create_active_assignment(api, worker_id=w["id"], place_id=pp["id"])
    inc = get_success_data(
        api.create_incident(
            create_incident_payload(pp["id"], "EQUIPMENT", "DOA scanner",
                                    equipment_unit_id=eq["id"]),
            SUPPORT,
        )
    )
    get_success_data(api.escalate_incident(inc["id"], SUPPORT))  # -> equipment OUT_OF_SERVICE
    return pp, eq


def test_open_with_out_of_service_equipment_is_rejected(api):
    """PRD §3.2: "that no equipment unit assigned to the place be `OUT_OF_SERVICE` and that
    at least one supply kit for the place be in custody state `AT_PLACE` (otherwise
    `ERR_EQUIPMENT_NOT_OPERATIONAL`, 409)".

    Design: Difficulty/cross_entity_state_dependency/open_requires_equipment_operational
    """
    pp, eq = _place_with_out_of_service_scanner(api)
    resp = api.open_place(pp["id"], CAPTAIN)
    validate_error(resp, ApiErrorId.ERR_EQUIPMENT_NOT_OPERATIONAL)


def test_escalated_equipment_incident_takes_unit_out_of_service(api):
    """PRD §3.3: "when an equipment-related incident is escalated, the referenced unit is
    driven `OPERATIONAL → OUT_OF_SERVICE`, and if its owning place is `OPEN` that place is
    forced `OPEN → SUSPENDED`".

    Design: Difficulty/cross_entity_state_dependency/open_requires_equipment_operational
    """
    pp, eq = _place_with_out_of_service_scanner(api)
    equipment = get_success_data(api.get_equipment(eq["id"], ADMIN))
    assert equipment["status"] == "OUT_OF_SERVICE"
    place = get_success_data(api.get_polling_place(pp["id"], ADMIN))
    assert place["readiness_posture"] == "SETUP", (
        "a place never opened stays SETUP even when its equipment goes out of service"
    )


# ---- priority_pair_validation_conflict / open_safety_beats_fiscal ----

def _place_compromised_kit_no_staff(api):
    """min_workers_required=1 with slots_filled=0 (no active assignment); the only kit is
    driven AT_PLACE then COMPROMISED via SEAL_BREAK. Place SETUP. Returns place."""
    el = create_election(api, open_voting=True)
    pp = create_place(api, election_id=el["id"], min_workers_required=1)
    deploy_equipment(api, place_id=pp["id"])
    kit = create_kit_at_place(api, election_id=el["id"], place_id=pp["id"])
    get_success_data(api.create_custody_event(kit["id"], {"event_type": "SEAL_BREAK"}, CUSTODY))
    return pp


def test_open_with_compromised_kit_and_no_staff_reports_kit_compromised(api):
    """PRD §3.2: "It requires, in this evaluation order after the standard existence check:
    that the place currently be in a posture from which opening is defined, i.e. `SETUP`
    (otherwise `ERR_INVALID_STATE`, 409); that the place's election be in `VOTING_OPEN`
    (otherwise `ERR_VOTING_NOT_OPEN`, 409); that no supply kit for the place be in custody
    state `COMPROMISED` (otherwise `ERR_KIT_COMPROMISED`, 409); that no equipment unit
    assigned to the place be `OUT_OF_SERVICE` and that at least one supply kit for the place
    be in custody state `AT_PLACE` (otherwise `ERR_EQUIPMENT_NOT_OPERATIONAL`, 409); and
    finally that `slots_filled` be greater than or equal to `min_workers_required` (otherwise
    `ERR_UNDERSTAFFED`, 422)."

    Design: Difficulty/priority_pair_validation_conflict/open_safety_beats_fiscal
    """
    pp = _place_compromised_kit_no_staff(api)
    resp = api.open_place(pp["id"], CAPTAIN)
    validate_error(resp, ApiErrorId.ERR_KIT_COMPROMISED)


def test_open_blocked_by_safety_leaves_place_in_setup(api):
    """PRD §3.2: "that no supply kit for the place be in custody state `COMPROMISED`
    (otherwise `ERR_KIT_COMPROMISED`, 409)".

    Design: Difficulty/priority_pair_validation_conflict/open_safety_beats_fiscal
    """
    pp = _place_compromised_kit_no_staff(api)
    validate_error(api.open_place(pp["id"], CAPTAIN), ApiErrorId.ERR_KIT_COMPROMISED)
    place = get_success_data(api.get_polling_place(pp["id"], ADMIN))
    assert place["readiness_posture"] == "SETUP", "a rejected open must not change posture"


# ---- validations / error_voting_not_open_on_open_place ----

def test_open_place_when_election_not_voting_open(api):
    """PRD §3.2: "that the place's election be in `VOTING_OPEN` (otherwise
    `ERR_VOTING_NOT_OPEN`, 409)".

    Design: Corner/validations/error_voting_not_open_on_open_place
    """
    el = create_election(api)  # PLANNING, never opened
    pp = create_place(api, election_id=el["id"])
    resp = api.open_place(pp["id"], CAPTAIN)
    validate_error(resp, ApiErrorId.ERR_VOTING_NOT_OPEN)
