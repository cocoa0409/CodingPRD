"""Composite setup helpers.

Every test starts against an empty database (the harness restarts the server
before each test), so these helpers build complete precondition chains —
manager bootstrap, employee qualification, machine + approved survey + active
procedure, sessions in a given lifecycle state, audits, permits — using only
PRD-declared endpoints.

Identity threading: all three roles are employee-backed (PRD §2.1), so every
call uses make_*_headers(employee["id"]) built from the actual entity id.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import DEFAULT_CLOCK_ISO, OPERATOR_ID
from .factories import (
    create_contractor_permit_payload,
    create_employee_lock_payload,
    create_employee_payload,
    create_energy_survey_payload,
    create_incident_report_payload,
    create_lockout_procedure_payload,
    create_lockout_session_payload,
    create_machine_modification_payload,
    create_machine_payload,
    create_minor_servicing_exception_payload,
    create_procedure_audit_payload,
    create_training_record_payload,
    default_energy_sources,
    default_steps,
)
from .test_users import (
    make_authorized_employee_headers,
    make_ehs_auditor_headers,
    make_ehs_manager_headers,
)


# ---------------------------------------------------------------------------
# Tier 0: bootstrap, employees, training, clock
# ---------------------------------------------------------------------------

def bootstrap_manager(employee_no="E-MGR-1", full_name="EHS Manager"):
    """Register the EHS manager's own Employee record (first call, empty DB).

    The bootstrap call carries the conventional operator id (no ownership or
    segregation-of-duties check involves the caller of POST /employees).
    """
    resp = api_client.create_employee(
        create_employee_payload(employee_no=employee_no, full_name=full_name),
        make_ehs_manager_headers(OPERATOR_ID))
    return get_success_data(resp)


def register_employee(mgr, employee_no, full_name=None, qualification="AUTHORIZED"):
    resp = api_client.create_employee(
        create_employee_payload(employee_no=employee_no,
                                full_name=full_name or employee_no,
                                qualification=qualification),
        make_ehs_manager_headers(mgr["id"]))
    return get_success_data(resp)


def complete_authorized_training(mgr, employee, course_code="LOTO_AUTHORIZED_INITIAL",
                                 delivery_mode="IN_PERSON"):
    """Assign + complete a course; returns the COMPLETED TrainingRecord."""
    headers = make_ehs_manager_headers(mgr["id"])
    record = get_success_data(api_client.create_training_record(
        create_training_record_payload(employee["id"], course_code=course_code,
                                       delivery_mode=delivery_mode), headers))
    return get_success_data(api_client.complete_training_record(record["id"], headers))


def register_qualified_employee(mgr, employee_no, full_name=None):
    """AUTHORIZED employee with a completed IN_PERSON initial course —
    is_currently_qualified true (PRD §3.4)."""
    employee = register_employee(mgr, employee_no, full_name)
    complete_authorized_training(mgr, employee)
    return get_success_data(api_client.get_employee(
        employee["id"], make_ehs_manager_headers(mgr["id"])))


def set_logical_clock(mgr, to_iso8601):
    resp = api_client.set_clock(to_iso8601, make_ehs_manager_headers(mgr["id"]))
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 1: machine + survey + procedure chains
# ---------------------------------------------------------------------------

def create_machine(mgr, asset_tag="A-100", name="Test Press", area="Line 1",
                   risk_window_policy="ROLLING_12MO"):
    resp = api_client.create_machine(
        create_machine_payload(asset_tag=asset_tag, name=name, area=area,
                               risk_window_policy=risk_window_policy),
        make_ehs_manager_headers(mgr["id"]))
    return get_success_data(resp)


def create_approved_survey(mgr, surveyor, machine_id, energy_sources=None):
    """Surveyor creates + submits; the manager approves. Returns APPROVED survey."""
    surveyor_headers = make_authorized_employee_headers(surveyor["id"])
    survey = get_success_data(api_client.create_energy_survey(
        create_energy_survey_payload(
            machine_id, energy_sources=energy_sources or default_energy_sources(1)),
        surveyor_headers))
    survey = get_success_data(api_client.submit_energy_survey(
        survey["id"], surveyor_headers))
    return get_success_data(api_client.approve_energy_survey(
        survey["id"], make_ehs_manager_headers(mgr["id"])))


def create_draft_procedure(mgr, machine_id, survey_id, steps=None):
    resp = api_client.create_lockout_procedure(
        create_lockout_procedure_payload(machine_id, survey_id,
                                         steps=steps or default_steps(1)),
        make_ehs_manager_headers(mgr["id"]))
    return get_success_data(resp)


def create_active_procedure(mgr, machine_id, survey_id, steps=None):
    """Create + activate (first activation). Returns the ACTIVE procedure."""
    procedure = create_draft_procedure(mgr, machine_id, survey_id, steps=steps)
    return get_success_data(api_client.activate_lockout_procedure(
        procedure["id"], {}, make_ehs_manager_headers(mgr["id"])))


def setup_machine_with_active_procedure(mgr, surveyor, asset_tag="A-100",
                                        name="Test Press", area="Line 1",
                                        risk_window_policy="ROLLING_12MO",
                                        isolation_points=1):
    """Machine + APPROVED survey + ACTIVE procedure. Returns (machine, survey, procedure)."""
    machine = create_machine(mgr, asset_tag=asset_tag, name=name, area=area,
                             risk_window_policy=risk_window_policy)
    survey = create_approved_survey(mgr, surveyor, machine["id"],
                                    energy_sources=default_energy_sources(isolation_points))
    procedure = create_active_procedure(mgr, machine["id"], survey["id"],
                                        steps=default_steps(isolation_points))
    return machine, survey, procedure


def register_modification(mgr, machine_id, description="Replaced guard interlock"):
    """OCC-guarded modification registration (PRD §2.7): reads the machine's
    current version first, then posts with expected_machine_version."""
    headers = make_ehs_manager_headers(mgr["id"])
    machine = get_success_data(api_client.get_machine(machine_id, headers))
    return get_success_data(api_client.create_machine_modification(
        machine_id,
        create_machine_modification_payload(
            description=description, expected_machine_version=machine["version"]),
        headers))


# ---------------------------------------------------------------------------
# Tier 2: sessions and locks in a given lifecycle state
# ---------------------------------------------------------------------------

def create_session(primary, machine_id, procedure_id, session_type="INDIVIDUAL"):
    resp = api_client.create_lockout_session(
        create_lockout_session_payload(machine_id, procedure_id,
                                       session_type=session_type),
        make_authorized_employee_headers(primary["id"]))
    return get_success_data(resp)


def issue_lock(employee, session_id, lock_no="L-1", tag_no="T-1"):
    resp = api_client.create_employee_lock(
        create_employee_lock_payload(session_id, lock_no=lock_no, tag_no=tag_no),
        make_authorized_employee_headers(employee["id"]))
    return get_success_data(resp)


def apply_lock(employee, lock_id):
    return get_success_data(api_client.apply_employee_lock(
        lock_id, make_authorized_employee_headers(employee["id"])))


def lock_session(primary, session_id, zero_energy_verified=True):
    return get_success_data(api_client.lock_lockout_session(
        session_id, {"zero_energy_verified": zero_energy_verified},
        make_authorized_employee_headers(primary["id"])))


def setup_session_in_setup(asset_tag="A-SES-1", name="Press", area="Line 1",
                           isolation_points=1, session_type="INDIVIDUAL",
                           risk_window_policy="ROLLING_12MO"):
    """Full chain: manager, qualified primary employee, machine with ACTIVE
    procedure, session in SETUP. Returns a context dict."""
    mgr = bootstrap_manager()
    primary = register_qualified_employee(mgr, "E-W1-1", "Worker One")
    machine, survey, procedure = setup_machine_with_active_procedure(
        mgr, primary, asset_tag=asset_tag, name=name, area=area,
        risk_window_policy=risk_window_policy, isolation_points=isolation_points)
    session = create_session(primary, machine["id"], procedure["id"], session_type)
    return {"mgr": mgr, "primary": primary, "machine": machine,
            "survey": survey, "procedure": procedure, "session": session}


def setup_session_locked(asset_tag="A-LCK-1", name="Press", area="Line 1",
                         isolation_points=1, session_type="INDIVIDUAL",
                         lock_no="L-1", tag_no="T-1"):
    """Session walked to LOCKED with one APPLIED lock owned by the primary."""
    ctx = setup_session_in_setup(asset_tag=asset_tag, name=name, area=area,
                                 isolation_points=isolation_points,
                                 session_type=session_type)
    lock = issue_lock(ctx["primary"], ctx["session"]["id"], lock_no, tag_no)
    lock = apply_lock(ctx["primary"], lock["id"])
    ctx["session"] = lock_session(ctx["primary"], ctx["session"]["id"])
    ctx["lock"] = lock
    return ctx


def run_session_to_released(primary, session_id, lock_id):
    """From LOCKED with the given lock APPLIED: remove -> clear -> release."""
    headers = make_authorized_employee_headers(primary["id"])
    get_success_data(api_client.remove_employee_lock(lock_id, headers))
    get_success_data(api_client.clear_lockout_session(session_id, headers))
    return get_success_data(api_client.release_lockout_session(session_id, headers))


def setup_session_released(asset_tag="A-REL-1"):
    """Session walked through its full lifecycle to RELEASED."""
    ctx = setup_session_locked(asset_tag=asset_tag)
    ctx["session"] = run_session_to_released(
        ctx["primary"], ctx["session"]["id"], ctx["lock"]["id"])
    return ctx


# ---------------------------------------------------------------------------
# Tier 3: audits
# ---------------------------------------------------------------------------

def schedule_audit(auditor, procedure_id, scheduled_start="2026-08-10T09:00:00Z",
                   scheduled_end="2026-08-10T12:00:00Z"):
    resp = api_client.create_procedure_audit(
        create_procedure_audit_payload(procedure_id,
                                       scheduled_start=scheduled_start,
                                       scheduled_end=scheduled_end),
        make_ehs_auditor_headers(auditor["id"]))
    return get_success_data(resp)


def complete_audit(auditor, audit_id, result, employees_sampled):
    return get_success_data(api_client.complete_procedure_audit(
        audit_id, {"result": result, "employees_sampled": employees_sampled},
        make_ehs_auditor_headers(auditor["id"])))


def setup_procedure_failed_audit(with_applied_lock=True, asset_tag="A-AF-1"):
    """Session in SETUP (optionally holding one APPLIED lock by the primary);
    an independent auditor completes a FAIL audit, driving the procedure to
    UNDER_REVISION without cancelling the session (PRD §3.7)."""
    mgr = bootstrap_manager()
    primary = register_qualified_employee(mgr, "E-W1-AF", "Worker One")
    auditor = register_qualified_employee(mgr, "E-W2-AF", "Auditor Two")
    machine, survey, procedure = setup_machine_with_active_procedure(
        mgr, primary, asset_tag=asset_tag)
    session = create_session(primary, machine["id"], procedure["id"], "INDIVIDUAL")
    lock = None
    sample = []
    if with_applied_lock:
        lock = issue_lock(primary, session["id"], "L-AF-1", "T-AF-1")
        lock = apply_lock(primary, lock["id"])
        sample = [primary["id"]]
    audit = schedule_audit(auditor, procedure["id"])
    audit = complete_audit(auditor, audit["id"], "FAIL", sample)
    procedure = get_success_data(api_client.get_lockout_procedure(
        procedure["id"], make_ehs_manager_headers(mgr["id"])))
    return {"mgr": mgr, "primary": primary, "auditor": auditor,
            "machine": machine, "survey": survey, "procedure": procedure,
            "session": session, "lock": lock, "audit": audit}


def setup_pinned_capacity_scenario():
    """Session pinned to revision 1 (max_locks 2) survives its procedure going
    UNDER_REVISION (audit FAIL) and then SUPERSEDED by a 1-isolation-point
    revision (PRD §3.5 pinning)."""
    mgr = bootstrap_manager()
    primary = register_qualified_employee(mgr, "E-W1-PC", "W1 PC")
    auditor = register_qualified_employee(mgr, "E-W2-PC", "W2 PC")
    member3 = register_qualified_employee(mgr, "E-W3-PC", "W3 PC")
    member4 = register_qualified_employee(mgr, "E-W4-PC", "W4 PC")
    machine, survey1, p1 = setup_machine_with_active_procedure(
        mgr, primary, asset_tag="A-PC-100", name="Mill M", area="Line 3",
        isolation_points=2)
    session = create_session(primary, machine["id"], p1["id"], "GROUP")
    audit = schedule_audit(auditor, p1["id"])
    complete_audit(auditor, audit["id"], "FAIL", [])
    survey2 = create_approved_survey(mgr, primary, machine["id"],
                                     energy_sources=default_energy_sources(1))
    p2 = create_active_procedure(mgr, machine["id"], survey2["id"],
                                 steps=default_steps(1))
    headers = make_ehs_manager_headers(mgr["id"])
    return {"mgr": mgr, "primary": primary, "auditor": auditor,
            "member3": member3, "member4": member4, "machine": machine,
            "p1": get_success_data(api_client.get_lockout_procedure(p1["id"], headers)),
            "p2": p2,
            "session": get_success_data(api_client.get_lockout_session(
                session["id"], headers))}


# ---------------------------------------------------------------------------
# Tier 4: incidents and risk
# ---------------------------------------------------------------------------

def report_incident(reporter, machine_id, kind="NEAR_MISS",
                    occurred_at="2026-07-01T00:00:00Z", severity=1,
                    session_id=None, description=None, role="EHSManager"):
    if role == "EHSManager":
        headers = make_ehs_manager_headers(reporter["id"])
    elif role == "EHSAuditor":
        headers = make_ehs_auditor_headers(reporter["id"])
    else:
        headers = make_authorized_employee_headers(reporter["id"])
    payload = create_incident_report_payload(
        machine_id, kind=kind, occurred_at=occurred_at, severity=severity)
    if session_id is not None:
        payload["session_id"] = session_id
    if description is not None:
        payload["description"] = description
    return get_success_data(api_client.create_incident_report(payload, headers))


def link_incident(mgr, incident_id):
    return get_success_data(api_client.link_incident_report(
        incident_id, make_ehs_manager_headers(mgr["id"])))


def dismiss_incident(mgr, incident_id):
    return get_success_data(api_client.dismiss_incident_report(
        incident_id, make_ehs_manager_headers(mgr["id"])))


# ---------------------------------------------------------------------------
# Tier 5: contractor permits and minor-servicing exceptions
# ---------------------------------------------------------------------------

def create_approved_permit(mgr, coordinator, machine_id,
                           company_name="Acme Rigging",
                           insurance_valid_until="2027-01-01T00:00:00Z",
                           coordination_meeting_at="2026-07-15T00:00:00Z"):
    """REQUESTED -> APPROVED permit (insurance and meeting valid vs default clock)."""
    permit = get_success_data(api_client.create_contractor_permit(
        create_contractor_permit_payload(
            machine_id, company_name=company_name,
            insurance_valid_until=insurance_valid_until),
        make_authorized_employee_headers(coordinator["id"])))
    return get_success_data(api_client.approve_contractor_permit(
        permit["id"], {"coordination_meeting_at": coordination_meeting_at},
        make_ehs_manager_headers(mgr["id"])))


def setup_bound_active_permit(asset_tag="A-CP-1"):
    """Full contractor lifecycle up to permit ACTIVE: machine + procedure +
    APPROVED permit + LOCKED CONTRACTOR session + permit bound (PRD §3.9)."""
    mgr = bootstrap_manager()
    coordinator = register_qualified_employee(mgr, "E-W1-CP", "Coordinator One")
    machine, survey, procedure = setup_machine_with_active_procedure(
        mgr, coordinator, asset_tag=asset_tag, name="Oven", area="Bay 15")
    permit = create_approved_permit(mgr, coordinator, machine["id"])
    session = create_session(coordinator, machine["id"], procedure["id"], "CONTRACTOR")
    lock = issue_lock(coordinator, session["id"], "L-CP-1", "T-CP-1")
    lock = apply_lock(coordinator, lock["id"])
    session = lock_session(coordinator, session["id"])
    permit = get_success_data(api_client.activate_contractor_permit(
        permit["id"], {"session_id": session["id"]},
        make_authorized_employee_headers(coordinator["id"])))
    return {"mgr": mgr, "coordinator": coordinator, "machine": machine,
            "procedure": procedure, "session": session, "lock": lock,
            "permit": permit}


def create_exception(employee, machine_id, **overrides):
    resp = api_client.create_minor_servicing_exception(
        create_minor_servicing_exception_payload(machine_id, **overrides),
        make_authorized_employee_headers(employee["id"]))
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Read helpers (all roles may read; manager headers used uniformly)
# ---------------------------------------------------------------------------

def get_machine(mgr, machine_id):
    return get_success_data(api_client.get_machine(
        machine_id, make_ehs_manager_headers(mgr["id"])))


def get_employee(mgr, employee_id):
    return get_success_data(api_client.get_employee(
        employee_id, make_ehs_manager_headers(mgr["id"])))


def get_survey(mgr, survey_id):
    return get_success_data(api_client.get_energy_survey(
        survey_id, make_ehs_manager_headers(mgr["id"])))


def get_procedure(mgr, procedure_id):
    return get_success_data(api_client.get_lockout_procedure(
        procedure_id, make_ehs_manager_headers(mgr["id"])))


def get_session(mgr, session_id):
    return get_success_data(api_client.get_lockout_session(
        session_id, make_ehs_manager_headers(mgr["id"])))


def get_lock(mgr, lock_id):
    return get_success_data(api_client.get_employee_lock(
        lock_id, make_ehs_manager_headers(mgr["id"])))


def get_audit(mgr, audit_id):
    return get_success_data(api_client.get_procedure_audit(
        audit_id, make_ehs_manager_headers(mgr["id"])))


def get_incident(mgr, incident_id):
    return get_success_data(api_client.get_incident_report(
        incident_id, make_ehs_manager_headers(mgr["id"])))


def get_permit(mgr, permit_id):
    return get_success_data(api_client.get_contractor_permit(
        permit_id, make_ehs_manager_headers(mgr["id"])))


def get_exception(mgr, exception_id):
    return get_success_data(api_client.get_minor_servicing_exception(
        exception_id, make_ehs_manager_headers(mgr["id"])))


DEFAULT_CLOCK = DEFAULT_CLOCK_ISO
