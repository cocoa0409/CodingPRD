"""Entity creation, defaults, computed/system fields, immutability, not-found,
and state-machine invalid-transition / initial-state coverage.

Queue B (Corner): entities section, state_machines section.
"""
from test_helpers import (
    validate_success, validate_error,
    set_clock, create_incident,
    setup_closed_incident, setup_dispatched_incident, make_field_unit_headers,
    create_agency_payload, create_incident_payload,
    create_station_payload, create_unit_payload, assert_cfs_report,
    NON_EXISTENT_UUID,
    SUP, CALL, DISP, REC,
)


# =====================================================================
# Queue B — entities
# =====================================================================
def test_create_agency_returns_201_with_default_status_and_version(api):
    """PRD §3.1: "A newly created agency comes up with its `status` set to
    `ONLINE`."
    PRD §2.4: "an integer that begins at its initial value and increments by one
    on every mutation of the resource."

    Design: Corner/entities/create_agency_returns_201_with_defaults
    """
    res = api.create_agency(create_agency_payload(
        name="Metro PD", discipline="POLICE", response_sla_seconds=600), SUP)
    ag = validate_success(res, 201)
    assert ag["status"] == "ONLINE"
    assert ag["version"] == 1
    assert ag["discipline"] == "POLICE"


def test_intake_missing_incident_type_rejected(api):
    """PRD §2.6: "the body itself is validated for well-formedness — required
    fields present, enumerated values legal, integers within range, the `ani`
    exactly ten digits, and every grid coordinate within the inclusive range
    from 0 to 1000 — with violations yielding `ERR_INVALID_REQUEST`."

    POST /incidents missing incident_type → ERR_INVALID_REQUEST (422).

    Design: Corner/entities/create_incident_required_field_missing_returns_invalid_request
    """
    set_clock("2026-06-20T00:00:00Z")
    res = api.create_incident({
        "ani": "5125559001", "ali_grid_x": 10, "ali_grid_y": 10}, CALL)
    validate_error(res, "ERR_INVALID_REQUEST")


def test_intake_ani_not_ten_digits_rejected(api):
    """PRD §2.6: "Fifth, the body itself is validated for well-formedness —
    required fields present, enumerated values legal, integers within range, the
    `ani` exactly ten digits, and every grid coordinate within the inclusive
    range from 0 to 1000 — with violations yielding `ERR_INVALID_REQUEST`."

    ani with fewer than 10 digits → ERR_INVALID_REQUEST (422).

    Design: Corner/entities/incident_ani_not_ten_digits_returns_invalid_request
    """
    set_clock("2026-06-20T01:00:00Z")
    res = api.create_incident(create_incident_payload(
        ani="12345", ali_grid_x=10, ali_grid_y=10,
        incident_type="WELFARE_CHECK"), CALL)
    validate_error(res, "ERR_INVALID_REQUEST")


def test_intake_grid_out_of_range_rejected(api):
    """PRD §2.6: "every grid coordinate within the inclusive range from 0 to
    1000 — with violations yielding `ERR_INVALID_REQUEST`."

    ali_grid_x > 1000 → ERR_INVALID_REQUEST (422).

    Design: Corner/entities/incident_grid_out_of_range_returns_invalid_request
    """
    set_clock("2026-06-20T02:00:00Z")
    res = api.create_incident(create_incident_payload(
        ani="5125559002", ali_grid_x=5000, ali_grid_y=10,
        incident_type="WELFARE_CHECK"), CALL)
    validate_error(res, "ERR_INVALID_REQUEST")


def test_intake_invalid_enum_incident_type_rejected(api):
    """PRD §2.6: "Fifth, the body itself is validated for well-formedness —
    required fields present, enumerated values legal, integers within range, the
    `ani` exactly ten digits, and every grid coordinate within the inclusive
    range from 0 to 1000 — with violations yielding `ERR_INVALID_REQUEST`."

    Unknown incident_type enum value → ERR_INVALID_REQUEST (422).

    Design: Corner/entities/incident_invalid_enum_type_returns_invalid_request
    """
    set_clock("2026-06-20T03:00:00Z")
    res = api.create_incident(create_incident_payload(
        ani="5125559003", ali_grid_x=10, ali_grid_y=10,
        incident_type="CAT_IN_TREE"), CALL)
    validate_error(res, "ERR_INVALID_REQUEST")


def test_intake_default_ali_confidence_high(api):
    """PRD §3.3: "an optional `ali_confidence` that defaults to `HIGH`."
    PRD §3.3: "a `WELFARE_CHECK` has base 5".

    Omitting ali_confidence applies HIGH (no priority-2 confidence clamp):
    WELFARE_CHECK with no premise alert keeps priority 5.

    Design: Corner/entities/incident_default_ali_confidence_high
    """
    set_clock("2026-06-20T04:00:00Z")
    inc = validate_success(api.create_incident(create_incident_payload(
        ani="5125559004", ali_grid_x=200, ali_grid_y=200,
        incident_type="WELFARE_CHECK"), CALL), 201)
    assert inc["ali_confidence"] == "HIGH"
    assert inc["priority_level"] == 5


def test_intake_computes_required_disciplines_and_mints_number(api):
    """PRD §3.3: "a `STRUCTURE_FIRE` requires `FIRE` and `EMS`".
    PRD §3.3: "a `STRUCTURE_FIRE` and an `ASSAULT_IN_PROGRESS` each have base 1".
    PRD §3.3: "On acceptance the platform mints a human-readable
    `incident_number` in the format `CFS-YYYY-NNNNNN`, assigned monotonically".

    Design: Corner/entities/incident_computed_required_disciplines_and_number_minted
    """
    set_clock("2026-06-20T05:00:00Z")
    inc = validate_success(api.create_incident(create_incident_payload(
        ani="5125559005", ali_grid_x=100, ali_grid_y=100,
        incident_type="STRUCTURE_FIRE"), CALL), 201)
    assert inc["required_disciplines"] == ["FIRE", "EMS"]
    assert inc["base_priority_level"] == 1
    assert inc["priority_level"] == 1
    assert isinstance(inc["incident_number"], str) and inc["incident_number"]


def test_intake_ignores_client_supplied_system_fields(api):
    """PRD §3.3: "brings the incident up with `lifecycle_status` set to
    `PENDING`."
    PRD §3.3: "a `WELFARE_CHECK` has base 5".

    Client-supplied lifecycle_status/priority_level are ignored: server sets
    PENDING and computes priority 5 for a WELFARE_CHECK.

    Design: Corner/entities/incident_system_fields_input_ignored
    """
    set_clock("2026-06-20T06:00:00Z")
    payload = create_incident_payload(
        ani="5125559006", ali_grid_x=100, ali_grid_y=100,
        incident_type="WELFARE_CHECK")
    payload["lifecycle_status"] = "CLOSED"
    payload["priority_level"] = 1
    inc = validate_success(api.create_incident(payload, CALL), 201)
    assert inc["lifecycle_status"] == "PENDING"
    assert inc["priority_level"] == 5


def test_get_nonexistent_agency_returns_not_found(api):
    """PRD §2.6: "every resource identifier named in the URL path is checked for
    existence, validated left to right, with the first missing identifier
    yielding `ERR_NOT_FOUND`."

    GET /agencies/{nonexistent} → ERR_NOT_FOUND (404).

    Design: Corner/entities/get_agency_not_found
    """
    res = api.get_agency(NON_EXISTENT_UUID, DISP)
    validate_error(res, "ERR_NOT_FOUND")


def test_cfs_report_is_immutable_no_version_field(api):
    """PRD §2.4: "A `CfsReport` therefore carries only `id` and `created_at`; it
    has no `updated_at` and no `version`, and once written it is never modified."

    Design: Corner/entities/cfsreport_immutable_no_version_field
    """
    set_clock("2026-06-21T00:00:00Z")
    _, _, _, incident, _, _ = setup_closed_incident(
        discipline="EMS", capability="MEDIC_ALS",
        incident_type="MEDICAL_EMERGENCY", grid=10, ani="5125559007")
    rep = validate_success(api.create_report(incident["id"], {"report_standard": "NENA"}, REC), 201)
    assert_cfs_report(rep)


# =====================================================================
# Queue B — state_machines
# =====================================================================
def test_escalate_at_priority_one_rejected(api):
    """PRD §3.7: "Escalation is permitted only while the incident's
    `lifecycle_status` is not `CLOSED` or `CANCELLED` and its `priority_level` is
    greater than 1; an incident already at top urgency or in a terminal
    lifecycle state cannot escalate and is rejected with `ERR_INVALID_STATE`."

    STRUCTURE_FIRE at priority_level 1 (base 1, no alert) cannot escalate.

    Design: Corner/state_machines/escalate_below_priority_one_returns_invalid_state
    """
    set_clock("2026-06-21T01:00:00Z")
    inc = create_incident(incident_type="STRUCTURE_FIRE", ali_grid_x=500,
                          ali_grid_y=500, ani="5125559008")
    assert inc["priority_level"] == 1
    res = api.escalate_incident(inc["id"], {"reason": "x"}, SUP)
    validate_error(res, "ERR_INVALID_STATE")


def test_resume_non_held_incident_rejected(api):
    """PRD §3.7: "**Resuming** moves the incident `HELD → ACTIVE`, unfreezing it;
    it is permitted only from `HELD` and is otherwise rejected with
    `ERR_INVALID_STATE`."

    Resume on a PENDING (never held) incident → ERR_INVALID_STATE.

    Design: Corner/state_machines/resume_non_held_incident_returns_invalid_state
    """
    set_clock("2026-06-21T02:00:00Z")
    inc = create_incident(incident_type="WELFARE_CHECK", ali_grid_x=10,
                          ali_grid_y=10, ani="5125559009")
    res = api.resume_incident(inc["id"], SUP)
    validate_error(res, "ERR_INVALID_STATE")


def test_onscene_directly_from_dispatched_rejected(api):
    """PRD §3.5: "an attempt to make a transition that the assignment's current
    state does not allow is rejected with `ERR_INVALID_STATE`."
    PRD §3.5: "From `ENROUTE`, going **onscene** moves the assignment
    `ENROUTE → ONSCENE`".

    ONSCENE directly from DISPATCHED (skipping ENROUTE) → ERR_INVALID_STATE.

    Design: Corner/state_machines/assignment_onscene_from_dispatched_skips_enroute_invalid_state
    """
    set_clock("2026-06-21T03:00:00Z")
    _, _, unit, incident, asg = setup_dispatched_incident(
        discipline="POLICE", capability="PATROL",
        incident_type="ASSAULT_IN_PROGRESS", grid=10, ani="5125559010")
    res = api.set_assignment_status(asg["id"], "ONSCENE", make_field_unit_headers(unit["id"]))
    validate_error(res, "ERR_INVALID_STATE")


def test_cancel_dispatched_incident_rejected(api):
    """PRD §3.8: "If the incident is not `PENDING`, or any assignment exists for
    it, the cancel is rejected with `ERR_INVALID_STATE`."

    Cancel on a DISPATCHED incident (already has an assignment) →
    ERR_INVALID_STATE.

    Design: Corner/state_machines/cancel_dispatched_incident_returns_invalid_state
    """
    set_clock("2026-06-21T04:00:00Z")
    _, _, unit, incident, asg = setup_dispatched_incident(
        discipline="POLICE", capability="PATROL",
        incident_type="ASSAULT_IN_PROGRESS", grid=10, ani="5125559011")
    res = api.cancel_incident(incident["id"], {"reason": "false_alarm"}, CALL)
    validate_error(res, "ERR_INVALID_STATE")


def test_terminal_cancelled_incident_rejects_escalate(api):
    """PRD §3.7: "an incident already at top urgency or in a terminal lifecycle
    state cannot escalate and is rejected with `ERR_INVALID_STATE`."
    PRD §3.8: "Cancellation moves the `lifecycle_status` `PENDING → CANCELLED`".

    A CANCELLED (terminal) incident cannot escalate.

    Design: Corner/state_machines/terminal_cancelled_incident_rejects_escalate
    """
    set_clock("2026-06-21T05:00:00Z")
    inc = create_incident(incident_type="WELFARE_CHECK", ali_grid_x=10,
                          ali_grid_y=10, ani="5125559012")
    validate_success(api.cancel_incident(inc["id"], {"reason": "resolved_by_phone"}, CALL), 200)
    res = api.escalate_incident(inc["id"], {"reason": "x"}, SUP)
    validate_error(res, "ERR_INVALID_STATE")


def test_new_unit_starts_available_with_station_grid(api):
    """PRD §3.1: "A new unit comes up with `status` set to `AVAILABLE` and
    `active_incident_id` set to nothing, since it is not yet committed to any
    incident."
    PRD §3.1: "A unit's starting position may be supplied as `grid_x` and
    `grid_y`, but when those are omitted the platform defaults the unit's grid to
    the home station's grid."

    Design: Corner/state_machines/new_unit_starts_available_initial_state
    """
    agency = validate_success(api.create_agency(create_agency_payload(
        name="PD Init", discipline="POLICE", response_sla_seconds=600), SUP), 201)
    station = validate_success(api.create_station(create_station_payload(
        agency["id"], name="PInit", grid_x=88, grid_y=88), SUP), 201)
    unit = validate_success(api.create_unit(create_unit_payload(
        agency["id"], station["id"], call_sign="PInit1", capability="PATROL"), SUP), 201)
    assert unit["status"] == "AVAILABLE"
    assert unit["active_incident_id"] is None
    assert unit["grid_x"] == 88
    assert unit["grid_y"] == 88


def test_hold_pending_incident_rejected(api):
    """PRD §3.7: "Holding moves the `lifecycle_status` `ACTIVE → HELD` and is
    permitted only when the incident is `ACTIVE` and at least one assignment on
    it is `ONSCENE`; otherwise the request is rejected with `ERR_INVALID_STATE`."

    Hold on a PENDING (not ACTIVE) incident → ERR_INVALID_STATE.

    Design: Corner/state_machines/hold_pending_incident_returns_invalid_state
    """
    set_clock("2026-06-21T06:00:00Z")
    inc = create_incident(incident_type="WELFARE_CHECK", ali_grid_x=10,
                          ali_grid_y=10, ani="5125559013")
    res = api.hold_incident(inc["id"], {"reason": "x"}, SUP)
    validate_error(res, "ERR_INVALID_STATE")
