"""Composite setup helpers.

Every test runs against a freshly restarted server with an empty database, so
each helper builds its preconditions from scratch using only public endpoints.
All setup calls use get_success_data() so failures surface as clear
"Setup step failed" errors.
"""
from prd_bench_local_runner.testing import get_success_data, validate_paginated

from . import factories
from .api_client import api_client
from .constants import T0, TEST_DEFAULTS
from .test_users import TEST_USERS, make_employee_headers, make_manager_headers

ADMIN = TEST_USERS["compliance_admin_headers"]
HR = TEST_USERS["hr_admin_headers"]
AUDITOR = TEST_USERS["auditor_headers"]


# --------------------------------------------------------------------------
# Tier 0: clock / sweep drivers
# --------------------------------------------------------------------------

def set_clock(to_iso8601: str) -> dict:
    """Advance the logical clock; returns {current_utc: ...}."""
    resp = api_client.set_clock({"to_iso8601": to_iso8601}, ADMIN)
    return get_success_data(resp, 200)


def run_sweep() -> dict:
    """Run the deterministic five-step sweep; returns the counter block."""
    resp = api_client.run_sweep(ADMIN)
    return get_success_data(resp, 200)


# --------------------------------------------------------------------------
# Tier 1: single-resource creators
# --------------------------------------------------------------------------

def create_regulator(code="REG-1", name="Test Regulator", deadline_mode="CALENDAR",
                     recordkeeping_years=TEST_DEFAULTS["RECORDKEEPING_YEARS"],
                     escalation_interval_days=None, reminder_days_before_due=None) -> dict:
    payload = factories.create_regulator_payload(
        code=code, name=name, deadline_mode=deadline_mode,
        recordkeeping_years=recordkeeping_years,
    )
    if escalation_interval_days is not None:
        payload["escalation_interval_days"] = escalation_interval_days
    if reminder_days_before_due is not None:
        payload["reminder_days_before_due"] = reminder_days_before_due
    resp = api_client.create_regulator(payload, ADMIN)
    return get_success_data(resp, 201)


def create_role(code="R-1", name="Test Role") -> dict:
    resp = api_client.create_role(factories.create_role_payload(code=code, name=name), ADMIN)
    return get_success_data(resp, 201)


def create_curriculum(regulator_id, code="CUR-1", title="Test Course",
                      passing_score_pct=TEST_DEFAULTS["PASSING_SCORE_PCT"],
                      validity_months=TEST_DEFAULTS["VALIDITY_MONTHS"],
                      evidence_requirement="NONE", max_attempts=None,
                      recordkeeping_years_override=None) -> dict:
    """Create a curriculum (born DRAFT)."""
    overrides = {}
    if max_attempts is not None:
        overrides["max_attempts"] = max_attempts
    if recordkeeping_years_override is not None:
        overrides["recordkeeping_years_override"] = recordkeeping_years_override
    payload = factories.create_curriculum_payload(
        regulator_id, code=code, title=title, passing_score_pct=passing_score_pct,
        validity_months=validity_months, evidence_requirement=evidence_requirement,
        **overrides,
    )
    resp = api_client.create_curriculum(payload, ADMIN)
    return get_success_data(resp, 201)


def add_curriculum_version(curriculum_id, version_no=1,
                           effective_from="2026-08-01T00:00:00Z",
                           effective_to=None, content_uri="uri://content-v1") -> dict:
    payload = factories.create_version_payload(
        version_no=version_no, effective_from=effective_from, content_uri=content_uri,
    )
    if effective_to is not None:
        payload["effective_to"] = effective_to
    resp = api_client.create_curriculum_version(curriculum_id, payload, ADMIN)
    return get_success_data(resp, 201)


def activate_curriculum(curriculum_id) -> dict:
    """PATCH status=ACTIVE under OCC, using the curriculum's current version."""
    current = get_success_data(api_client.get_curriculum(curriculum_id, ADMIN), 200)
    resp = api_client.update_curriculum(
        curriculum_id,
        {"status": "ACTIVE", "expected_curriculum_version": current["version"]},
        ADMIN,
    )
    return get_success_data(resp, 200)


def create_active_curriculum(regulator_id, code="CUR-1", **kwargs) -> dict:
    """Curriculum with an effective version, activated. Returns the ACTIVE curriculum."""
    cur = create_curriculum(regulator_id, code=code, **kwargs)
    add_curriculum_version(cur["id"])
    return activate_curriculum(cur["id"])


def add_requirement(role_id, curriculum_id, recurrence="INITIAL_ONLY",
                    due_in_days=TEST_DEFAULTS["DUE_IN_DAYS"], criticality="SOFT") -> dict:
    payload = factories.create_requirement_payload(
        curriculum_id, recurrence=recurrence, due_in_days=due_in_days,
        criticality=criticality,
    )
    resp = api_client.create_requirement(role_id, payload, ADMIN)
    return get_success_data(resp, 201)


def create_employee(employee_no, current_role_id, full_name=None, manager_id=None,
                    hired_at="2026-08-03T09:00:00Z") -> dict:
    overrides = {}
    if manager_id is not None:
        overrides["manager_id"] = manager_id
    payload = factories.create_employee_payload(
        current_role_id, employee_no=employee_no,
        full_name=full_name or f"Employee {employee_no}", hired_at=hired_at,
        **overrides,
    )
    resp = api_client.create_employee(payload, HR)
    return get_success_data(resp, 201)


def create_leave(employee_id, start_date="2026-08-03T00:00:00Z",
                 end_date="2026-08-07T23:59:59Z", reason="Medical") -> dict:
    payload = factories.create_leave_payload(
        start_date=start_date, end_date=end_date, reason=reason,
    )
    resp = api_client.create_leave(employee_id, payload, HR)
    return get_success_data(resp, 201)


def create_role_change(employee_id, to_role_id, effective_at) -> dict:
    payload = factories.create_role_change_payload(to_role_id, effective_at=effective_at)
    resp = api_client.create_role_change(employee_id, payload, HR)
    return get_success_data(resp, 201)


# --------------------------------------------------------------------------
# Tier 2: composite stacks
# --------------------------------------------------------------------------

def setup_curriculum_stack(prefix, deadline_mode="CALENDAR", recordkeeping_years=7,
                           escalation_interval_days=None, reminder_days_before_due=None,
                           passing_score_pct=80, validity_months=12,
                           evidence_requirement="NONE", max_attempts=None,
                           recurrence="INITIAL_ONLY",
                           due_in_days=TEST_DEFAULTS["DUE_IN_DAYS"],
                           criticality="SOFT") -> dict:
    """Regulator + ACTIVE curriculum (with effective version) + role + requirement."""
    reg = create_regulator(
        code=f"REG-{prefix}", name=f"{prefix} Regulator", deadline_mode=deadline_mode,
        recordkeeping_years=recordkeeping_years,
        escalation_interval_days=escalation_interval_days,
        reminder_days_before_due=reminder_days_before_due,
    )
    cur = create_active_curriculum(
        reg["id"], code=f"CUR-{prefix}", title=f"{prefix} Course",
        passing_score_pct=passing_score_pct, validity_months=validity_months,
        evidence_requirement=evidence_requirement, max_attempts=max_attempts,
    )
    role = create_role(code=f"R-{prefix}", name=f"{prefix} Role")
    req = add_requirement(
        role["id"], cur["id"], recurrence=recurrence,
        due_in_days=due_in_days, criticality=criticality,
    )
    return {"regulator": reg, "curriculum": cur, "role": role, "requirement": req}


def find_assignment(employee_id, curriculum_id=None, role_requirement_id=None) -> dict:
    """First assignment matching the given filters (creation order)."""
    params = {"employee_id": employee_id}
    if curriculum_id is not None:
        params["curriculum_id"] = curriculum_id
    if role_requirement_id is not None:
        params["role_requirement_id"] = role_requirement_id
    resp = api_client.list_assignments(ADMIN, params=params)
    data, meta = validate_paginated(resp)
    assert meta["total_count"] >= 1, (
        f"expected at least one assignment for employee {employee_id}, got none"
    )
    return data[0]


def list_assignments(params=None) -> tuple:
    resp = api_client.list_assignments(ADMIN, params=params)
    return validate_paginated(resp)


def setup_employee_with_assignment(prefix, set_clock_to=T0, **stack_kwargs) -> dict:
    """Full stack + one employee holding the NEW_HIRE assignment."""
    if set_clock_to is not None:
        set_clock(set_clock_to)
    stack = setup_curriculum_stack(prefix, **stack_kwargs)
    emp = create_employee(f"E-{prefix}-1", stack["role"]["id"])
    asg = find_assignment(emp["id"], curriculum_id=stack["curriculum"]["id"])
    return {**stack, "employee": emp, "assignment": asg}


def setup_managed_employee_with_assignment(prefix, set_clock_to=T0, **stack_kwargs) -> dict:
    """Full stack + a manager (in a requirement-free role) + a managed employee
    holding the NEW_HIRE assignment."""
    if set_clock_to is not None:
        set_clock(set_clock_to)
    stack = setup_curriculum_stack(prefix, **stack_kwargs)
    mgr_role = create_role(code=f"R-{prefix}M", name=f"{prefix} Mgr Role")
    mgr = create_employee(f"M-{prefix}-1", mgr_role["id"])
    emp = create_employee(f"E-{prefix}-1", stack["role"]["id"], manager_id=mgr["id"])
    asg = find_assignment(emp["id"], curriculum_id=stack["curriculum"]["id"])
    return {**stack, "manager_role": mgr_role, "manager": mgr,
            "employee": emp, "assignment": asg}


# --------------------------------------------------------------------------
# Tier 3: workflow shortcuts
# --------------------------------------------------------------------------

def submit_completion(assignment_id, employee_id, score_pct=90,
                      evidence_type="NONE", evidence_uri=None) -> dict:
    payload = factories.submit_completion_payload(
        score_pct=score_pct, evidence_type=evidence_type,
    )
    if evidence_uri is not None:
        payload["evidence_uri"] = evidence_uri
    resp = api_client.submit_completion(
        assignment_id, payload, make_employee_headers(employee_id),
    )
    return get_success_data(resp, 201)


def accept_completion(completion_id, review_note=None) -> dict:
    payload = {}
    if review_note is not None:
        payload["review_note"] = review_note
    resp = api_client.accept_completion(completion_id, payload, ADMIN)
    return get_success_data(resp, 200)


def reject_completion(completion_id, review_note="evidence insufficient") -> dict:
    resp = api_client.reject_completion(completion_id, {"review_note": review_note}, ADMIN)
    return get_success_data(resp, 200)


def void_completion(completion_id, reason="Evidence audit failure") -> dict:
    resp = api_client.void_completion(completion_id, {"reason": reason}, ADMIN)
    return get_success_data(resp, 200)


def verify_assignment(assignment_id, employee_id, score_pct=90) -> dict:
    """Submit + accept; returns the ACCEPTED completion record."""
    comp = submit_completion(assignment_id, employee_id, score_pct=score_pct)
    return accept_completion(comp["id"])


def get_assignment(assignment_id) -> dict:
    return get_success_data(api_client.get_assignment(assignment_id, ADMIN), 200)


def get_employee(employee_id) -> dict:
    return get_success_data(api_client.get_employee(employee_id, ADMIN), 200)


def get_role_change_data(role_change_id) -> dict:
    return get_success_data(api_client.get_role_change(role_change_id, ADMIN), 200)


def list_completions(assignment_id) -> tuple:
    resp = api_client.list_completions(assignment_id, ADMIN)
    return validate_paginated(resp)


def list_assignment_escalations(assignment_id) -> tuple:
    resp = api_client.list_assignment_escalations(assignment_id, ADMIN)
    return validate_paginated(resp)


# --------------------------------------------------------------------------
# Tier 4: campaigns / attestations
# --------------------------------------------------------------------------

def create_campaign(regulator_id, year=2026,
                    window_open_at=TEST_DEFAULTS["CAMPAIGN_WINDOW_OPEN"],
                    window_close_at=TEST_DEFAULTS["CAMPAIGN_WINDOW_CLOSE"],
                    statement_version="STMT-2026-08") -> dict:
    payload = factories.create_campaign_payload(
        regulator_id, year=year, window_open_at=window_open_at,
        window_close_at=window_close_at, statement_version=statement_version,
    )
    resp = api_client.create_campaign(payload, ADMIN)
    return get_success_data(resp, 201)


def open_campaign(campaign_id) -> dict:
    resp = api_client.open_campaign(campaign_id, ADMIN)
    return get_success_data(resp, 200)


def find_attestation(employee_id) -> dict:
    resp = api_client.list_employee_attestations(employee_id, ADMIN)
    data, meta = validate_paginated(resp)
    assert meta["total_count"] >= 1, (
        f"expected at least one attestation for employee {employee_id}, got none"
    )
    return data[0]


def get_attestation_data(attestation_id) -> dict:
    return get_success_data(api_client.get_attestation(attestation_id, ADMIN), 200)


def list_employee_escalations(employee_id) -> tuple:
    resp = api_client.list_employee_escalations(employee_id, ADMIN)
    return validate_paginated(resp)


def setup_open_campaign_with_attestation(prefix, set_clock_to=T0, **stack_kwargs) -> dict:
    """Managed-employee stack + OPEN campaign + the employee's attestation."""
    ctx = setup_managed_employee_with_assignment(prefix, set_clock_to=set_clock_to, **stack_kwargs)
    camp = create_campaign(ctx["regulator"]["id"])
    open_campaign(camp["id"])
    att = find_attestation(ctx["employee"]["id"])
    return {**ctx, "campaign": camp, "attestation": att}


def request_exception(attestation_id, manager_id, reason_code="MEDICAL_LEAVE",
                      detail="Scheduled surgery in August") -> dict:
    payload = factories.request_exception_payload(reason_code=reason_code, detail=detail)
    resp = api_client.request_exception(
        attestation_id, payload, make_manager_headers(manager_id),
    )
    return get_success_data(resp, 201)


def attest(attestation_id, employee_id) -> dict:
    resp = api_client.attest(attestation_id, make_employee_headers(employee_id))
    return get_success_data(resp, 200)


# --------------------------------------------------------------------------
# Tier 5: audit reports
# --------------------------------------------------------------------------

def create_audit_report(regulator_id, metric_variant="STRICT", population_spec=None) -> dict:
    spec = population_spec if population_spec is not None else {"regulator_id": regulator_id}
    payload = {"population_spec": spec, "metric_variant": metric_variant}
    resp = api_client.create_audit_report(payload, AUDITOR)
    return get_success_data(resp, 201)
