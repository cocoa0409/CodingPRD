"""Composite setup helpers for multi-step test prerequisites.

Every helper builds preconditions from scratch using only PRD-declared
endpoints (each test runs against a freshly restarted server with an empty
database). Setup calls use get_success_data so failures surface as clear
"Setup failed" errors. Identity threading: entity-backed roles always act
through make_operator_headers(employee_id) / make_contractor_rep_headers(
contractor_id) with the real entity id created earlier in the same chain.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import TEST_DEFAULTS
from .factories import (
    create_charge_adjustment_payload,
    create_contractor_payload,
    create_corrective_action_payload,
    create_drill_event_payload,
    create_employee_payload,
    create_equipment_payload,
    create_facility_payload,
    create_hot_work_permit_payload,
    create_incident_payload,
    create_inspection_payload,
    create_leak_event_payload,
    create_psid_document_payload,
    create_system_payload,
    create_training_record_payload,
    set_clock_payload,
)
from .test_users import TEST_USERS, make_contractor_rep_headers, make_operator_headers

ADMIN = TEST_USERS["facility_admin_headers"]
PSC = TEST_USERS["ps_coordinator_headers"]
MLEAD = TEST_USERS["maintenance_lead_headers"]
CO = TEST_USERS["compliance_officer_headers"]


def _fail(step, resp):
    raise AssertionError(
        f"Setup failed at {step}: HTTP {resp.status_code} {resp.text}"
    )


def _ok(step, resp, expected_status=None):
    if expected_status is not None and resp.status_code != expected_status:
        _fail(step, resp)
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 1 — atomic creators (single-call building blocks)
# ---------------------------------------------------------------------------

def set_clock(to_iso8601, headers=None):
    """Set the logical clock (FacilityAdmin by default; ComplianceOfficer may too)."""
    resp = api_client.set_clock(set_clock_payload(to_iso8601), headers or ADMIN)
    return _ok("set_clock", resp, 200)


def create_facility(name=TEST_DEFAULTS["FACILITY_NAME"], threshold_lbs=None):
    payload = create_facility_payload(name=name)
    if threshold_lbs is not None:
        payload["threshold_lbs"] = threshold_lbs
    resp = api_client.create_facility(payload, ADMIN)
    return _ok("create_facility", resp, 201)


def get_facility(facility_id, headers=None):
    resp = api_client.get_facility(facility_id, headers or ADMIN)
    return _ok("get_facility", resp, 200)


def create_employee(facility_id, full_name, employment_status=None):
    payload = create_employee_payload(facility_id, full_name=full_name)
    if employment_status is not None:
        payload["employment_status"] = employment_status
    resp = api_client.create_employee(payload, ADMIN)
    return _ok("create_employee", resp, 201)


def create_system(facility_id, name=TEST_DEFAULTS["SYSTEM_NAME"],
                  design_charge_lbs=TEST_DEFAULTS["DESIGN_CHARGE_LBS"], **overrides):
    payload = create_system_payload(
        facility_id, name=name, design_charge_lbs=design_charge_lbs, **overrides)
    resp = api_client.create_refrigeration_system(payload, ADMIN)
    return _ok("create_refrigeration_system", resp, 201)


def get_system(system_id, headers=None):
    resp = api_client.get_refrigeration_system(system_id, headers or ADMIN)
    return _ok("get_refrigeration_system", resp, 200)


def create_equipment(system_id, tag_number="V-101", inspection_interval_days=180,
                     inspection_method="FIXED", equipment_type="VESSEL"):
    payload = create_equipment_payload(
        system_id, tag_number=tag_number,
        inspection_interval_days=inspection_interval_days,
        inspection_method=inspection_method, equipment_type=equipment_type)
    resp = api_client.create_equipment(payload, MLEAD)
    return _ok("create_equipment", resp, 201)


def schedule_inspection(equipment_id, due_at):
    resp = api_client.create_inspection(
        create_inspection_payload(equipment_id, due_at=due_at), MLEAD)
    return _ok("create_inspection", resp, 201)


def create_contractor(company_name=TEST_DEFAULTS["CONTRACTOR_NAME"],
                      safety_score=TEST_DEFAULTS["SAFETY_SCORE"]):
    resp = api_client.create_contractor(
        create_contractor_payload(company_name=company_name,
                                  safety_score=safety_score),
        MLEAD)
    return _ok("create_contractor", resp, 201)


def qualify_contractor(contractor_id,
                       qualified_until=TEST_DEFAULTS["QUALIFIED_UNTIL"]):
    resp = api_client.qualify_contractor(
        contractor_id, {"qualified_until": qualified_until}, MLEAD)
    return _ok("qualify_contractor", resp, 200)


def create_qualified_contractor(qualified_until=TEST_DEFAULTS["QUALIFIED_UNTIL"],
                                **kwargs):
    contractor = create_contractor(**kwargs)
    return qualify_contractor(contractor["id"], qualified_until)


def create_psid_document(system_id, doc_type="PID", revision_label="Rev A",
                         content_uri="s3://docs/pid-rev-a.pdf"):
    """Issue a CURRENT PSI document; reads the system's current version first
    to satisfy the expected_system_version OCC token (PRD section 2.8)."""
    system = get_system(system_id, PSC)
    payload = create_psid_document_payload(
        system_id, system["version"], doc_type=doc_type,
        revision_label=revision_label, content_uri=content_uri)
    resp = api_client.create_psid_document(payload, PSC)
    return _ok("create_psid_document", resp, 201)


# ---------------------------------------------------------------------------
# Tier 2 — common hierarchies
# ---------------------------------------------------------------------------

def setup_facility_with_operator(facility_name=TEST_DEFAULTS["FACILITY_NAME"],
                                 threshold_lbs=None,
                                 operator_name=TEST_DEFAULTS["OPERATOR_NAME"]):
    """Facility + one ACTIVE employee to act as the Operator identity.
    Returns (facility, employee, operator_headers)."""
    facility = create_facility(name=facility_name, threshold_lbs=threshold_lbs)
    employee = create_employee(facility["id"], operator_name)
    return facility, employee, make_operator_headers(employee["id"])


def setup_facility_with_system(facility_name=TEST_DEFAULTS["FACILITY_NAME"],
                               threshold_lbs=None,
                               design_charge_lbs=TEST_DEFAULTS["DESIGN_CHARGE_LBS"],
                               **system_overrides):
    """Facility + one IN_SERVICE refrigeration system. Returns (facility, system)."""
    facility = create_facility(name=facility_name, threshold_lbs=threshold_lbs)
    system = create_system(facility["id"], design_charge_lbs=design_charge_lbs,
                           **system_overrides)
    return facility, system


def setup_facility_system_operator(**kwargs):
    """Facility + system + operator employee.
    Returns (facility, system, employee, operator_headers)."""
    threshold_lbs = kwargs.pop("threshold_lbs", None)
    facility, employee, op_headers = setup_facility_with_operator(
        threshold_lbs=threshold_lbs)
    system = create_system(facility["id"], **kwargs)
    return facility, system, employee, op_headers


# ---------------------------------------------------------------------------
# Tier 3 — charge ledger (OCC-threaded postings)
# ---------------------------------------------------------------------------

def post_charge_adjustment(facility_id, adjustment_type, quantity_lbs, reason,
                           operator_headers, system_id=None):
    """Read the facility's current version, post the adjustment with that
    expected_facility_version, return (entry, facility_after)."""
    facility = get_facility(facility_id)
    payload = create_charge_adjustment_payload(
        facility_id, facility["version"], adjustment_type=adjustment_type,
        quantity_lbs=quantity_lbs, reason=reason)
    if system_id is not None:
        payload["system_id"] = system_id
    resp = api_client.create_charge_adjustment(payload, operator_headers)
    entry = _ok("create_charge_adjustment", resp, 201)
    return entry, get_facility(facility_id)


def post_gauge_reading(system_id, reading_lbs, operator_headers):
    resp = api_client.post_gauge_reading(system_id, {"reading_lbs": reading_lbs},
                                         operator_headers)
    return _ok("post_gauge_reading", resp, 200)


# ---------------------------------------------------------------------------
# Tier 4 — permits and contractors
# ---------------------------------------------------------------------------

def setup_requested_permit(qualify=True,
                           qualified_until=TEST_DEFAULTS["QUALIFIED_UNTIL"],
                           valid_from=TEST_DEFAULTS["PERMIT_VALID_FROM"],
                           valid_until=TEST_DEFAULTS["PERMIT_VALID_UNTIL"],
                           work_description="weld repair on discharge line"):
    """Facility + system + contractor + REQUESTED permit.
    Returns (facility, system, contractor, permit, rep_headers)."""
    facility, system = setup_facility_with_system()
    contractor = create_contractor()
    if qualify:
        contractor = qualify_contractor(contractor["id"], qualified_until)
    rep_headers = make_contractor_rep_headers(contractor["id"])
    resp = api_client.create_hot_work_permit(
        create_hot_work_permit_payload(
            facility["id"], system["id"], contractor["id"],
            work_description=work_description,
            valid_from=valid_from, valid_until=valid_until),
        rep_headers)
    permit = _ok("create_hot_work_permit", resp, 201)
    return facility, system, contractor, permit, rep_headers


def setup_issued_permit(**kwargs):
    """Requested permit driven to ISSUED.
    Returns (facility, system, contractor, permit, rep_headers)."""
    facility, system, contractor, permit, rep_headers = setup_requested_permit(
        **kwargs)
    resp = api_client.issue_permit(permit["id"], MLEAD)
    permit = _ok("issue_permit", resp, 200)
    return facility, system, contractor, permit, rep_headers


# ---------------------------------------------------------------------------
# Tier 5 — incidents and corrective actions
# ---------------------------------------------------------------------------

def setup_incident_cast(facility_name=TEST_DEFAULTS["FACILITY_NAME"]):
    """Facility with three ACTIVE employees: reporter, investigator, assignee.
    Returns (facility, reporter, investigator, assignee)."""
    facility = create_facility(name=facility_name)
    reporter = create_employee(facility["id"], TEST_DEFAULTS["REPORTER_NAME"])
    investigator = create_employee(facility["id"], TEST_DEFAULTS["INVESTIGATOR_NAME"])
    assignee = create_employee(facility["id"], TEST_DEFAULTS["ASSIGNEE_NAME"])
    return facility, reporter, investigator, assignee


def create_reported_incident(facility_id, reporter_id,
                             severity="RECORDABLE",
                             description="ammonia odor near valve",
                             equipment_id=None):
    """Incident reported by the reporter acting as Operator (self-attributed).
    Returns the REPORTED incident."""
    payload = create_incident_payload(
        facility_id, reporter_id, severity=severity, description=description)
    if equipment_id is not None:
        payload["equipment_id"] = equipment_id
    resp = api_client.create_incident(payload, make_operator_headers(reporter_id))
    return _ok("create_incident", resp, 201)


def create_under_investigation_incident(facility_id, reporter_id, investigator_id,
                                        **kwargs):
    """Incident REPORTED by reporter, investigator assigned.
    Returns the UNDER_INVESTIGATION incident."""
    incident = create_reported_incident(facility_id, reporter_id, **kwargs)
    resp = api_client.assign_investigator(
        incident["id"], {"investigator_employee_id": investigator_id}, CO)
    return _ok("assign_investigator", resp, 200)


def create_open_action(incident_id, assignee_id, description="replace gasket",
                       due_at="2026-08-20T00:00:00Z"):
    resp = api_client.create_corrective_action(
        create_corrective_action_payload(
            incident_id, assignee_id, description=description, due_at=due_at),
        CO)
    return _ok("create_corrective_action", resp, 201)


def setup_incident_with_action():
    """Incident under investigation with one OPEN corrective action (incident
    advanced to ACTIONS_ASSIGNED).
    Returns (facility, reporter, investigator, assignee, incident, action)."""
    facility, reporter, investigator, assignee = setup_incident_cast()
    incident = create_under_investigation_incident(
        facility["id"], reporter["id"], investigator["id"])
    action = create_open_action(incident["id"], assignee["id"])
    incident = get_incident(incident["id"])
    return facility, reporter, investigator, assignee, incident, action


def get_incident(incident_id, headers=None):
    resp = api_client.get_incident(incident_id, headers or CO)
    return _ok("get_incident", resp, 200)


# ---------------------------------------------------------------------------
# Tier 6 — leaks, drills, training
# ---------------------------------------------------------------------------

def create_suspected_leak(system_id, operator_headers, estimated_release_lbs=120.0,
                          source_description="compressor seal weep"):
    resp = api_client.create_leak_event(
        create_leak_event_payload(
            system_id, estimated_release_lbs=estimated_release_lbs,
            source_description=source_description),
        operator_headers)
    return _ok("create_leak_event", resp, 201)


def setup_suspected_leak(estimated_release_lbs=120.0, clock=None):
    """Facility + system + operator + SUSPECTED leak.
    Returns (facility, system, employee, operator_headers, leak)."""
    if clock is not None:
        set_clock(clock, CO)
    facility, system, employee, op_headers = setup_facility_system_operator()
    leak = create_suspected_leak(system["id"], op_headers,
                                 estimated_release_lbs=estimated_release_lbs)
    return facility, system, employee, op_headers, leak


def record_training(employee_id, topic="AMMONIA_OPERATOR",
                    completed_at="2026-01-01T00:00:00Z"):
    resp = api_client.create_training_record(
        create_training_record_payload(
            employee_id, topic=topic, completed_at=completed_at),
        PSC)
    return _ok("create_training_record", resp, 201)


def create_trained_employee(facility_id, full_name, topic="AMMONIA_OPERATOR",
                            completed_at="2026-01-01T00:00:00Z"):
    """Employee with a training record on the given topic.
    Returns (employee, training_record)."""
    employee = create_employee(facility_id, full_name)
    record = record_training(employee["id"], topic=topic, completed_at=completed_at)
    return employee, record


def schedule_drill(facility_id, drill_type="TABLETOP",
                   scheduled_start_at="2026-09-10T09:00:00Z",
                   scheduled_end_at="2026-09-10T11:00:00Z"):
    resp = api_client.create_drill_event(
        create_drill_event_payload(
            facility_id, drill_type=drill_type,
            scheduled_start_at=scheduled_start_at,
            scheduled_end_at=scheduled_end_at),
        PSC)
    return _ok("create_drill_event", resp, 201)


# ---------------------------------------------------------------------------
# Tier 7 — checkpoint / posture
# ---------------------------------------------------------------------------

def run_checkpoint():
    resp = api_client.run_checkpoint(CO)
    return _ok("run_checkpoint", resp, 200)
