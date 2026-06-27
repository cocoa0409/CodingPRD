"""Business-rule validations, report-generation guards, and the report computed
read.

Queue B (Corner): validations section, endpoints (report computed read).
"""
from test_helpers import (
    validate_success, validate_error,
    set_clock, setup_agency_station_unit, create_incident, dispatch_unit,
    advance_assignment, setup_onscene_incident, setup_closed_incident,
    create_agency, create_station, create_unit_payload,
    SUP, DISP, REC,
)


def test_duplicate_call_sign_within_agency_rejected(api):
    """PRD §3.1: "the `call_sign` must be unique within the unit's agency — a
    collision is rejected with `ERR_DUPLICATE_CALL_SIGN`".

    Design: Corner/validations/duplicate_call_sign_within_agency_rejected
    """
    agency, station, _ = setup_agency_station_unit(
        discipline="POLICE", capability="PATROL", grid_x=10, grid_y=10,
        call_sign="P1", name_prefix="PD Cs")
    res = api.create_unit(create_unit_payload(
        agency["id"], station["id"], call_sign="P1", capability="K9"), SUP)
    validate_error(res, "ERR_DUPLICATE_CALL_SIGN")


def test_station_agency_mismatch_on_unit_create_rejected(api):
    """PRD §3.1: "the referenced station must belong to the same agency as the
    unit, or the request is rejected with `ERR_STATION_AGENCY_MISMATCH`."

    Design: Corner/validations/station_agency_mismatch_on_unit_create_rejected
    """
    agA = create_agency(discipline="POLICE", name="PD A")
    agB = create_agency(discipline="POLICE", name="PD B")
    stnA = create_station(agA["id"], grid_x=10, grid_y=10, name="SA")
    res = api.create_unit(create_unit_payload(
        agB["id"], stnA["id"], call_sign="B1", capability="PATROL"), SUP)
    validate_error(res, "ERR_STATION_AGENCY_MISMATCH")


def test_close_with_open_assignment_rejected(api):
    """PRD §3.8: "Closing requires that the incident be `DISPATCHED`, `ACTIVE`,
    or `HELD`, and that every assignment on the incident already be `CLEARED` or
    `CANCELLED`; if any assignment is still `DISPATCHED`, `ENROUTE`, or
    `ONSCENE`, the close is rejected with `ERR_OPEN_ASSIGNMENTS`".

    Posting a disposition while an assignment is still ONSCENE →
    ERR_OPEN_ASSIGNMENTS.

    Design: Corner/validations/close_with_open_assignment_rejected
    """
    set_clock("2026-06-21T10:00:00Z")
    _, _, unit, incident, asg = setup_onscene_incident(
        discipline="EMS", capability="MEDIC_ALS",
        incident_type="MEDICAL_EMERGENCY", grid=10, ani="5125559017")
    res = api.create_disposition(incident["id"], {
        "disposition_code": "TRANSPORT", "narrative": "x"}, SUP)
    validate_error(res, "ERR_OPEN_ASSIGNMENTS")


def test_discipline_mismatch_on_explicit_assignment_rejected(api):
    """PRD §3.4: "The committed unit's agency `discipline` must be one of the
    incident's `required_disciplines`, or the request is rejected with
    `ERR_DISCIPLINE_MISMATCH`."

    Assigning a POLICE unit to a MEDICAL_EMERGENCY (required [EMS]) →
    ERR_DISCIPLINE_MISMATCH.

    Design: Corner/validations/discipline_mismatch_on_explicit_assignment_rejected
    """
    set_clock("2026-06-21T11:00:00Z")
    _, _, unit = setup_agency_station_unit(
        discipline="POLICE", capability="PATROL", grid_x=10, grid_y=10,
        call_sign="PDm1", name_prefix="PD Dm")
    incident = create_incident(incident_type="MEDICAL_EMERGENCY",
                               ali_grid_x=10, ali_grid_y=10, ani="5125559018")
    res = api.create_assignment(incident["id"], {
        "expected_incident_version": incident["version"], "unit_id": unit["id"]}, DISP)
    validate_error(res, "ERR_DISCIPLINE_MISMATCH")


def test_assignment_with_unknown_unit_id_reference_not_found(api):
    """PRD §2.6: "for operations that carry foreign-key references in their body,
    each referenced resource must exist or the request is rejected with
    `ERR_REFERENCE_NOT_FOUND`; this applies to creating an assignment".

    Assignment create with a unit_id that does not exist →
    ERR_REFERENCE_NOT_FOUND (404).

    Design: Corner/validations/reference_not_found_on_assignment_unknown_unit
    """
    set_clock("2026-06-21T12:00:00Z")
    incident = create_incident(incident_type="ASSAULT_IN_PROGRESS",
                               ali_grid_x=10, ali_grid_y=10, ani="5125559019")
    res = api.create_assignment(incident["id"], {
        "expected_incident_version": incident["version"],
        "unit_id": "00000000-0000-0000-0000-000000000999"}, DISP)
    validate_error(res, "ERR_REFERENCE_NOT_FOUND")


def test_nfirs_report_on_non_fire_incident_rejected(api):
    """PRD §3.9: "an `NFIRS` report may only be generated for an incident that
    required `FIRE` discipline — the requested standard must match the incident's
    disciplines — so requesting `NFIRS` for a non-fire incident, or a standard
    incompatible with the incident's disciplines, is rejected with
    `ERR_REPORT_STANDARD_MISMATCH`."

    NFIRS for a CLOSED MEDICAL incident (no FIRE discipline) →
    ERR_REPORT_STANDARD_MISMATCH.

    Design: Corner/validations/report_standard_mismatch_nfirs_on_non_fire_rejected
    """
    set_clock("2026-06-21T13:00:00Z")
    _, _, _, incident, _, _ = setup_closed_incident(
        discipline="EMS", capability="MEDIC_ALS",
        incident_type="MEDICAL_EMERGENCY", grid=10, ani="5125559020")
    res = api.create_report(incident["id"], {"report_standard": "NFIRS"}, REC)
    validate_error(res, "ERR_REPORT_STANDARD_MISMATCH")


def test_report_on_non_closed_incident_rejected(api):
    """PRD §3.9: "A report may only be generated for a `CLOSED` incident; a
    request against an incident in any other lifecycle state is rejected with
    `ERR_INCIDENT_NOT_CLOSED`."

    Report for a PENDING incident → ERR_INCIDENT_NOT_CLOSED.

    Design: Corner/validations/report_on_non_closed_incident_rejected
    """
    set_clock("2026-06-21T14:00:00Z")
    inc = create_incident(incident_type="WELFARE_CHECK", ali_grid_x=10,
                          ali_grid_y=10, ani="5125559021")
    res = api.create_report(inc["id"], {"report_standard": "NENA"}, REC)
    validate_error(res, "ERR_INCIDENT_NOT_CLOSED")


# =====================================================================
# Queue B — endpoints (report computed read)
# =====================================================================
def test_report_snapshots_metrics_and_unit_count(api):
    """PRD §3.9: "It also computes the report's `unit_count` as the number of
    assignments on the incident whose `status` is `ONSCENE` or `CLEARED`".
    PRD §3.9: "at generation the platform copies the incident's
    `response_time_seconds`, `total_handle_seconds`, `sla_breached`, and
    `disposition_code` into the report".

    Closed MEDICAL incident, received 08:00, dispatched 08:01, onscene 08:08,
    cleared 08:10: response=420, handle=480, not breached, one CLEARED unit.

    Design: Corner/endpoints/report_computed_read_snapshots_metrics
    """
    set_clock("2026-06-22T08:00:00Z")
    _, _, unit = setup_agency_station_unit(
        discipline="EMS", capability="MEDIC_ALS", response_sla_seconds=600,
        grid_x=10, grid_y=10, call_sign="MSn1", name_prefix="EMS Snap")
    incident = create_incident(incident_type="MEDICAL_EMERGENCY",
                               ali_grid_x=10, ali_grid_y=10, ani="5125559027")
    set_clock("2026-06-22T08:01:00Z")
    asg = dispatch_unit(incident["id"], incident["version"], unit_id=unit["id"])
    advance_assignment(asg["id"], unit["id"], "ENROUTE")
    set_clock("2026-06-22T08:08:00Z")
    advance_assignment(asg["id"], unit["id"], "ONSCENE")
    set_clock("2026-06-22T08:10:00Z")
    advance_assignment(asg["id"], unit["id"], "CLEAR")
    validate_success(api.create_disposition(incident["id"], {
        "disposition_code": "TRANSPORT", "narrative": "done"}, SUP), 201)

    rep = validate_success(api.create_report(incident["id"], {"report_standard": "NENA"}, REC), 201)
    assert rep["unit_count"] == 1
    assert rep["response_time_seconds"] == 420
    assert rep["total_handle_seconds"] == 480
    assert rep["sla_breached"] is False
    assert rep["disposition_code"] == "TRANSPORT"
