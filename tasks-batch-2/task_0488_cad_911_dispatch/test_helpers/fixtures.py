"""
Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() (lenient validator) internally so setup failures produce
clear "Setup failed" errors rather than confusing assertion failures.

Ownership note: field-pipeline calls (ENROUTE/ONSCENE/CLEAR/re-stage by a
FieldUnit) are ownership-gated — they MUST be issued with
make_field_unit_headers(unit_id), never the shared field_unit_headers constant.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_agency_payload, create_station_payload, create_unit_payload,
    create_incident_payload, create_assignment_payload,
    create_disposition_payload, create_report_payload,
)
from .test_users import TEST_USERS, make_field_unit_headers

SUP = TEST_USERS["supervisor_headers"]
CALL = TEST_USERS["calltaker_headers"]
DISP = TEST_USERS["dispatcher_headers"]
REC = TEST_USERS["records_headers"]
CLOCK = TEST_USERS["system_clock_headers"]


# ─── Clock ────────────────────────────────────────────
def set_clock(iso_instant):
    """Advance the deterministic logical clock to the supplied instant."""
    return get_success_data(api_client.set_clock(iso_instant, CLOCK))


# ─── Tier 1 / Tier 2: Network standup ─────────────────
def create_agency(discipline="POLICE", response_sla_seconds=600, name=None):
    """Create one agency. Returns the agency entity."""
    name = name or f"{discipline} Agency"
    return get_success_data(api_client.create_agency(
        create_agency_payload(name=name, discipline=discipline,
                              response_sla_seconds=response_sla_seconds), SUP))


def create_station(agency_id, grid_x=10, grid_y=10, name="Station"):
    """Create one station under an agency. Returns the station entity."""
    return get_success_data(api_client.create_station(
        create_station_payload(agency_id, name=name, grid_x=grid_x, grid_y=grid_y),
        SUP))


def create_unit(agency_id, station_id, call_sign="U1", capability="PATROL",
                grid_x=None, grid_y=None):
    """Create one unit. Returns the unit entity."""
    overrides = {"call_sign": call_sign, "capability": capability}
    if grid_x is not None:
        overrides["grid_x"] = grid_x
    if grid_y is not None:
        overrides["grid_y"] = grid_y
    return get_success_data(api_client.create_unit(
        create_unit_payload(agency_id, station_id, **overrides), SUP))


def setup_agency_station_unit(discipline="POLICE", capability="PATROL",
                              response_sla_seconds=600, grid_x=10, grid_y=10,
                              call_sign="U1", name_prefix="N"):
    """
    Standup: one agency + one station + one AVAILABLE unit at (grid_x, grid_y).
    Returns (agency, station, unit).
    """
    agency = create_agency(discipline=discipline,
                           response_sla_seconds=response_sla_seconds,
                           name=f"{name_prefix} {discipline}")
    station = create_station(agency["id"], grid_x=grid_x, grid_y=grid_y,
                             name=f"{name_prefix} House")
    unit = create_unit(agency["id"], station["id"], call_sign=call_sign,
                       capability=capability, grid_x=grid_x, grid_y=grid_y)
    return agency, station, unit


# ─── Incident intake ──────────────────────────────────
def create_incident(incident_type="ASSAULT_IN_PROGRESS", ali_grid_x=10,
                    ali_grid_y=10, ani="5125550000", ali_confidence=None):
    """Intake an incident. Returns the incident entity (lifecycle PENDING)."""
    overrides = {"incident_type": incident_type, "ali_grid_x": ali_grid_x,
                 "ali_grid_y": ali_grid_y, "ani": ani}
    if ali_confidence is not None:
        overrides["ali_confidence"] = ali_confidence
    return get_success_data(api_client.create_incident(
        create_incident_payload(**overrides), CALL))


# ─── Tier 3: Dispatch + field-pipeline shortcuts ──────
def dispatch_unit(incident_id, expected_incident_version, unit_id=None,
                  auto_select=None, discipline=None):
    """
    Create an assignment (dispatch a unit). Returns the assignment entity.
    Caller supplies the current incident version for the OCC check.
    """
    overrides = {}
    if unit_id is not None:
        overrides["unit_id"] = unit_id
    if auto_select is not None:
        overrides["auto_select"] = auto_select
    if discipline is not None:
        overrides["discipline"] = discipline
    return get_success_data(api_client.create_assignment(
        incident_id,
        create_assignment_payload(expected_incident_version, **overrides), DISP))


def advance_assignment(assignment_id, unit_id, status):
    """Advance an assignment's field status as the owning FieldUnit."""
    return get_success_data(api_client.set_assignment_status(
        assignment_id, status, make_field_unit_headers(unit_id)))


def get_incident_version(incident_id):
    """Read the incident's current version (for re-reading after a bump)."""
    return get_success_data(api_client.get_incident(incident_id, DISP))["version"]


def setup_dispatched_incident(discipline="POLICE", capability="PATROL",
                              incident_type="ASSAULT_IN_PROGRESS",
                              grid=10, response_sla_seconds=600,
                              ani="5125550000"):
    """
    Standup agency/station/unit + intake incident + dispatch the unit.
    Returns (agency, station, unit, incident, assignment). Incident DISPATCHED,
    assignment DISPATCHED, unit DISPATCHED.
    """
    agency, station, unit = setup_agency_station_unit(
        discipline=discipline, capability=capability,
        response_sla_seconds=response_sla_seconds, grid_x=grid, grid_y=grid)
    incident = create_incident(incident_type=incident_type, ali_grid_x=grid,
                               ali_grid_y=grid, ani=ani)
    assignment = dispatch_unit(incident["id"], incident["version"],
                               unit_id=unit["id"])
    return agency, station, unit, incident, assignment


def setup_onscene_incident(discipline="EMS", capability="MEDIC_ALS",
                           incident_type="MEDICAL_EMERGENCY", grid=20,
                           response_sla_seconds=600, ani="5125550000"):
    """
    Full standup through ONSCENE: dispatch unit, drive ENROUTE then ONSCENE so
    the incident bubbles up to ACTIVE. Returns
    (agency, station, unit, incident, assignment). Assignment ONSCENE, unit
    ONSCENE, incident ACTIVE.
    """
    agency, station, unit, incident, assignment = setup_dispatched_incident(
        discipline=discipline, capability=capability,
        incident_type=incident_type, grid=grid,
        response_sla_seconds=response_sla_seconds, ani=ani)
    advance_assignment(assignment["id"], unit["id"], "ENROUTE")
    advance_assignment(assignment["id"], unit["id"], "ONSCENE")
    return agency, station, unit, incident, assignment


def setup_closed_incident(discipline="EMS", capability="MEDIC_ALS",
                          incident_type="MEDICAL_EMERGENCY", grid=10,
                          response_sla_seconds=600, ani="5125550000",
                          disposition_code="TRANSPORT", clear_first=True):
    """
    Full lifecycle through CLOSED: dispatch → enroute → onscene → (clear) →
    disposition. Returns (agency, station, unit, incident, assignment,
    disposition). Incident CLOSED.
    """
    agency, station, unit, incident, assignment = setup_dispatched_incident(
        discipline=discipline, capability=capability,
        incident_type=incident_type, grid=grid,
        response_sla_seconds=response_sla_seconds, ani=ani)
    advance_assignment(assignment["id"], unit["id"], "ENROUTE")
    advance_assignment(assignment["id"], unit["id"], "ONSCENE")
    if clear_first:
        advance_assignment(assignment["id"], unit["id"], "CLEAR")
    disposition = get_success_data(api_client.create_disposition(
        incident["id"],
        create_disposition_payload(disposition_code=disposition_code,
                                   narrative="done"), SUP))
    return agency, station, unit, incident, assignment, disposition


def setup_report(incident_id, report_standard="NENA"):
    """Generate a report against a CLOSED incident. Returns the report entity."""
    return get_success_data(api_client.create_report(
        incident_id, create_report_payload(report_standard=report_standard), REC))
