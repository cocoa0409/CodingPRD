"""State-machine transitions: illegal moves, preconditions, and divergent branches."""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    create_shift_payload,
    make_lifeguard_headers,
    TEST_USERS,
    setup_scheduled_shift, clock_in, setup_open_incident,
    setup_beach_zone, new_sample, new_advisory, zone_version, new_lifeguard,
    setup_lot, new_parking_pass, new_zone, new_tower, new_incident,
)

CAPTAIN = TEST_USERS["beach_captain_headers"]
INSPECTOR = TEST_USERS["inspector_headers"]
CLERK = TEST_USERS["parking_clerk_headers"]


def test_clock_out_from_scheduled_is_invalid_state(api):
    """PRD §2.5: "Any attempt to drive a state machine from a state that has no legal
    transition for the requested action is rejected with `ERR_INVALID_STATE` (409)."
    PRD §3.3: "Clocking out ends the shift, moving it from either `ON_DUTY` or `ON_BREAK` to
    the terminal `OFF_DUTY`."

    Design: Corner/state_machines/corner_shift_clockout_from_scheduled_invalid
    """
    beach, zone, tower, guard, shift = setup_scheduled_shift(api)
    resp = api.transition_shift(shift["id"], {"action": "CLOCK_OUT"}, make_lifeguard_headers(guard["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_second_clock_in_is_invalid_state(api):
    """PRD §2.5: "Any attempt to drive a state machine from a state that has no legal
    transition for the requested action is rejected with `ERR_INVALID_STATE` (409)."
    PRD §3.3: "The guard clocks in, advancing the shift from `SCHEDULED` to `ON_DUTY`; this is
    refused when the tower is `OFFLINE` with `ERR_TOWER_OFFLINE`."

    Design: Corner/state_machines/corner_shift_double_clockin_invalid
    """
    beach, zone, tower, guard, shift = setup_scheduled_shift(api)
    clock_in(api, shift["id"], guard["id"])
    resp = api.transition_shift(shift["id"], {"action": "CLOCK_IN"}, make_lifeguard_headers(guard["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_close_incident_from_open_is_invalid_state(api):
    """PRD §2.5: "Any attempt to drive a state machine from a state that has no legal
    transition for the requested action is rejected with `ERR_INVALID_STATE` (409)."
    PRD §3.6: "From any of `RESOLVED_ON_SCENE`, `ESCALATED_EMS`, or `REUNITED`, the guard
    closes the incident, moving it to the terminal `CLOSED`."

    Design: Corner/state_machines/corner_incident_close_from_open_invalid
    """
    beach, zone, guard, incident = setup_open_incident(api, incident_type="RESCUE")
    resp = api.transition_incident(incident["id"], {"action": "CLOSE"}, make_lifeguard_headers(guard["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_reunite_non_lost_child_is_type_mismatch(api):
    """PRD §3.6: "Reuniting a lost child moves the incident to `REUNITED`, but is allowed only
    when the incident's `type` is `LOST_CHILD`; attempting it on any other type is rejected
    with `ERR_INCIDENT_TYPE_MISMATCH` (422)."

    Design: Corner/state_machines/corner_incident_reunite_non_lostchild_mismatch
    """
    beach, zone, guard, incident = setup_open_incident(api, incident_type="RESCUE")
    resp = api.transition_incident(incident["id"], {"action": "REUNITE"}, make_lifeguard_headers(guard["id"]))
    validate_error(resp, ApiErrorId.ERR_INCIDENT_TYPE_MISMATCH.value)


def test_lift_superseded_advisory_is_not_active(api):
    """PRD §3.5: "Lifting is permitted only while the advisory is still `ACTIVE`; lifting
    anything else fails with `ERR_ADVISORY_NOT_ACTIVE` (409)."

    Design: Corner/state_machines/corner_advisory_lift_when_not_active_invalid
    """
    beach, zone = setup_beach_zone(api, clock="2026-07-15T09:00:00Z")
    new_sample(api, zone["id"], 40, "2026-07-15T08:00:00Z")
    adv1 = new_advisory(api, zone["id"], "SINGLE_SAMPLE", zone["version"])
    new_advisory(api, zone["id"], "SINGLE_SAMPLE", zone_version(api, zone["id"]))  # supersedes adv1
    resp = api.lift_advisory(adv1["id"], {}, INSPECTOR)
    validate_error(resp, ApiErrorId.ERR_ADVISORY_NOT_ACTIVE.value)


def test_revoke_already_revoked_pass_is_not_active(api):
    """PRD §3.7: "A clerk may revoke a pass that is currently `ACTIVE`, moving it to the
    terminal `REVOKED`; revoking a pass that is not `ACTIVE` fails with `ERR_PASS_NOT_ACTIVE`
    (409)."

    Design: Corner/state_machines/corner_pass_revoke_twice_invalid
    """
    beach, lot = setup_lot(api, total_spaces=10, daily_rate_cents=1000)
    pass_ = new_parking_pass(api, lot["id"])
    validate_success(api.revoke_parking_pass(pass_["id"], {}, CLERK), 200)
    resp = api.revoke_parking_pass(pass_["id"], {}, CLERK)
    validate_error(resp, ApiErrorId.ERR_PASS_NOT_ACTIVE.value)


def test_shift_end_before_start_rejected(api):
    """PRD §3.3: "The planned end must be strictly after the planned start, or the request
    fails with `ERR_SHIFT_WINDOW_INVALID` (422)."

    Design: Corner/validations/corner_shift_window_invalid_end_before_start
    """
    beach, zone, tower, guard, shift = setup_scheduled_shift(api)
    payload = create_shift_payload(
        guard["id"], tower["id"], "2026-07-15T17:00:00Z", "2026-07-15T09:00:00Z",
    )
    resp = api.create_shift(payload, CAPTAIN)
    validate_error(resp, ApiErrorId.ERR_SHIFT_WINDOW_INVALID.value)


def test_escalate_ems_without_details_rejected(api):
    """PRD §3.6: "Escalating to EMS moves it to `ESCALATED_EMS`, but only if the escalation
    payload supplies all four handoff details — `ems_hospital`, `ems_unit`, `ems_narrative`,
    and `ems_transported` — otherwise the escalation is rejected with `ERR_EMS_DETAILS_REQUIRED`
    (422)."

    Design: Corner/validations/corner_escalate_ems_missing_details_returns_error
    """
    beach, zone, guard, incident = setup_open_incident(api, incident_type="MEDICAL")
    resp = api.transition_incident(incident["id"], {"action": "ESCALATE_EMS"}, make_lifeguard_headers(guard["id"]))
    validate_error(resp, ApiErrorId.ERR_EMS_DETAILS_REQUIRED.value)


def test_issuing_advisory_supersedes_prior_active(api):
    """PRD §3.5: "Any advisory for the same zone that was previously `ACTIVE` is moved to
    `SUPERSEDED`."
    PRD §3.5: "The new advisory records its computed `level` and `assessed_value`, is stamped
    with an `issued_at` from the logical clock, and enters `ACTIVE` status."

    Design: Corner/state_machines/corner_advisory_supersede_marks_prior
    """
    beach, zone = setup_beach_zone(api, clock="2026-07-15T09:00:00Z")
    new_sample(api, zone["id"], 40, "2026-07-15T08:00:00Z")
    adv1 = new_advisory(api, zone["id"], "SINGLE_SAMPLE", zone["version"])
    adv2 = new_advisory(api, zone["id"], "SINGLE_SAMPLE", zone_version(api, zone["id"]))
    assert adv2["status"] == "ACTIVE", f"new advisory must be ACTIVE, got {adv2['status']}"
    adv1_after = validate_success(api.get_advisory(adv1["id"], INSPECTOR), 200)
    assert adv1_after["status"] == "SUPERSEDED", f"prior advisory must be SUPERSEDED, got {adv1_after['status']}"


def test_incident_resolve_on_scene_sets_no_ems_fields(api):
    """PRD §3.6: "Resolving on scene moves it to `RESOLVED_ON_SCENE` and sets no EMS fields."

    Design: Difficulty/non_linear_state_machine/incident_branch_resolve_vs_escalate
    """
    beach, zone, guard, incident = setup_open_incident(api, incident_type="MEDICAL")
    resp = api.transition_incident(incident["id"], {"action": "RESOLVE_ON_SCENE"}, make_lifeguard_headers(guard["id"]))
    data = validate_success(resp, 200)
    assert data["status"] == "RESOLVED_ON_SCENE"
    assert data.get("ems_transported") is None, "resolve-on-scene must set no EMS fields"


def test_incident_escalate_ems_populates_fields(api):
    """PRD §3.6: "on success those four values are written onto the incident, where
    `ems_transported` records whether the patient was transported, `ems_hospital` the
    receiving hospital, `ems_unit` the responding EMS unit, and `ems_narrative` the handoff
    narrative."

    Design: Difficulty/non_linear_state_machine/incident_branch_resolve_vs_escalate
    """
    beach, zone, guard, incident = setup_open_incident(api, incident_type="MEDICAL")
    resp = api.transition_incident(
        incident["id"],
        {"action": "ESCALATE_EMS", "ems_transported": True, "ems_hospital": "Mercy",
         "ems_unit": "M12", "ems_narrative": "transported"},
        make_lifeguard_headers(guard["id"]),
    )
    data = validate_success(resp, 200)
    assert data["status"] == "ESCALATED_EMS"
    assert data["ems_transported"] is True, f"ems_transported must be True, got {data.get('ems_transported')}"
