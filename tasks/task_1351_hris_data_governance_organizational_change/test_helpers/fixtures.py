"""Composite setup helpers for the HRIS data-governance workflows.

Every fixture builds its preconditions from scratch via PRD-declared endpoints
(each test runs against a freshly restarted server). All setup calls use the
lenient get_success_data() validator so a broken precondition surfaces as a
clear "Setup failed" error rather than a confusing assertion failure.
"""
from typing import Optional

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    DEFAULT_HIRE_DATE,
    create_batch_line_payload,
    create_batch_payload,
    create_data_field_payload,
    create_dq_rule_payload,
    create_grant_payload,
    create_position_payload,
    create_worker_payload,
    create_worker_change_request_payload,
)
from .test_users import (
    TEST_USERS,
    make_analyst_headers,
    make_approver_headers,
    make_security_admin_headers,
)

ANALYST = TEST_USERS["analyst_headers"]
STEWARD = TEST_USERS["steward_headers"]
APPROVER = TEST_USERS["approver_headers"]
OPERATOR = TEST_USERS["operator_headers"]
SECADMIN = TEST_USERS["security_admin_headers"]

ANALYST_USER_ID = ANALYST["X-User-ID"]
SECADMIN_USER_ID = SECADMIN["X-User-ID"]


# ---------------------------------------------------------------------------
# Tier 1/2: base entity builders
# ---------------------------------------------------------------------------

def create_position_record(title="Eng", department="ENG", headcount_budget=5,
                           parent_position_id=None):
    """Create an ACTIVE position. Returns the position dict."""
    payload = create_position_payload(
        title=title, department=department, headcount_budget=headcount_budget,
    )
    if parent_position_id is not None:
        payload["parent_position_id"] = parent_position_id
    resp = api_client.create_position(payload, ANALYST)
    data = get_success_data(resp)
    assert resp.status_code == 201, f"Setup failed: create position -> {resp.text}"
    return data


def create_worker_record(position_id, worker_number="W1", hire_date=DEFAULT_HIRE_DATE,
                         salary=10000, legal_name="Test Worker",
                         initial_pay_grade=None, initial_location_code=None):
    """Hire a worker (ACTIVE, version 1) seeding the initial assignment row."""
    payload = create_worker_payload(
        legal_name=legal_name, worker_number=worker_number, hire_date=hire_date,
        initial_position_id=position_id, initial_salary_cents=salary,
    )
    if initial_pay_grade is not None:
        payload["initial_pay_grade"] = initial_pay_grade
    if initial_location_code is not None:
        payload["initial_location_code"] = initial_location_code
    resp = api_client.create_worker(payload, ANALYST)
    data = get_success_data(resp)
    assert resp.status_code == 201, f"Setup failed: create worker -> {resp.text}"
    return data


def create_data_field_record(field_key="assignment.salary_cents", sensitivity="INTERNAL",
                             history_policy="CORRECTABLE", channels=None, activate=True,
                             owner_team="comp", display_name=None):
    """Create a DataField (optionally activating it). Returns the field dict."""
    payload = create_data_field_payload(
        field_key=field_key, display_name=display_name or field_key,
        sensitivity=sensitivity, history_policy=history_policy, owner_team=owner_team,
    )
    if channels is not None:
        payload["downstream_channels"] = channels
    resp = api_client.create_data_field(payload, STEWARD)
    data = get_success_data(resp)
    assert resp.status_code == 201, f"Setup failed: create data field -> {resp.text}"
    if activate:
        resp = api_client.activate_data_field(data["id"], STEWARD)
        data = get_success_data(resp)
        assert resp.status_code == 200, f"Setup failed: activate data field -> {resp.text}"
    return data


def create_dq_rule_record(field_id, rule_type="RANGE", severity="WARNING",
                          param_min=5000, param_max=20000, param_pattern=None):
    """Create an ACTIVE data-quality rule on a field."""
    payload = create_dq_rule_payload(
        target_field_id=field_id, rule_type=rule_type, severity=severity,
    )
    if rule_type == "RANGE":
        payload["param_min"] = param_min
        payload["param_max"] = param_max
    if param_pattern is not None:
        payload["param_pattern"] = param_pattern
    resp = api_client.create_data_quality_rule(payload, STEWARD)
    data = get_success_data(resp)
    assert resp.status_code == 201, f"Setup failed: create DQ rule -> {resp.text}"
    return data


# ---------------------------------------------------------------------------
# Grants
# ---------------------------------------------------------------------------

def create_grant_record(user_id, role_code, valid_from="2026-08-01",
                        valid_until="2027-08-01", creator_headers=None):
    """Request a security role grant (REQUESTED)."""
    payload = create_grant_payload(
        user_id=user_id, role_code=role_code,
        valid_from=valid_from, valid_until=valid_until,
    )
    resp = api_client.create_security_role_assignment(payload, creator_headers or SECADMIN)
    data = get_success_data(resp)
    assert resp.status_code == 201, f"Setup failed: create grant -> {resp.text}"
    return data


def approve_grant_record(grant_id, approver_user_id="secadmin-2"):
    """Approve a grant as a specific SecurityAdmin (self-approval is forbidden)."""
    resp = api_client.approve_security_role_assignment(
        grant_id, make_security_admin_headers(approver_user_id)
    )
    data = get_success_data(resp)
    assert resp.status_code == 200, f"Setup failed: approve grant -> {resp.text}"
    return data


def provision_grant(user_id, role_code="CHANGE_APPROVER", valid_from="2026-08-01",
                    valid_until="2027-08-01", approver_user_id="secadmin-2"):
    """Create + approve a grant whose window already covers the default clock,
    leaving it PROVISIONED. Returns the grant dict."""
    grant = create_grant_record(user_id, role_code, valid_from, valid_until)
    grant = approve_grant_record(grant["id"], approver_user_id)
    assert grant["status"] == "PROVISIONED", (
        f"Setup failed: grant expected PROVISIONED, got {grant['status']}"
    )
    return grant


# ---------------------------------------------------------------------------
# ChangeRequest lifecycle (Tier 3)
# ---------------------------------------------------------------------------

def create_worker_change_request_record(worker_id, worker_version, field_id,
                                        new_value="12000", effective_date="2026-09-01",
                                        correction_mode=None, target_row_id=None,
                                        propagate_correction=None,
                                        creator_user_id=ANALYST_USER_ID):
    """Propose a worker-field change (PENDING_APPROVAL). Returns the request."""
    payload = create_worker_change_request_payload(
        target_field_id=field_id, new_value=new_value, effective_date=effective_date,
        expected_worker_version=worker_version,
    )
    if correction_mode is not None:
        payload["correction_mode"] = correction_mode
    if target_row_id is not None:
        payload["target_row_id"] = target_row_id
    if propagate_correction is not None:
        payload["propagate_correction"] = propagate_correction
    resp = api_client.create_worker_change_request(
        worker_id, payload, make_analyst_headers(creator_user_id),
    )
    data = get_success_data(resp)
    assert resp.status_code == 201, f"Setup failed: create change request -> {resp.text}"
    return data


def approve_change_request_record(change_request_id, approver_user_id="appr-1"):
    """Approve a change request as a specific provisioned approver."""
    resp = api_client.approve_change_request(
        change_request_id, make_approver_headers(approver_user_id)
    )
    data = get_success_data(resp)
    assert resp.status_code == 200, f"Setup failed: approve change request -> {resp.text}"
    return data


def apply_change_request_record(change_request_id):
    """Apply an APPROVED change request as the analyst."""
    resp = api_client.apply_change_request(change_request_id, ANALYST)
    data = get_success_data(resp)
    assert resp.status_code == 200, f"Setup failed: apply change request -> {resp.text}"
    return data


def create_approved_worker_change(worker_id, worker_version, field_id, new_value="12000",
                                  effective_date="2026-09-01", approver_user_id="appr-1",
                                  **kwargs):
    """Create + approve a worker-field change. Returns the request dict."""
    cr = create_worker_change_request_record(
        worker_id, worker_version, field_id, new_value=new_value,
        effective_date=effective_date, **kwargs
    )
    return approve_change_request_record(cr["id"], approver_user_id)


def create_applied_worker_change(worker_id, worker_version, field_id, new_value="12000",
                                 effective_date="2026-09-01", approver_user_id="appr-1",
                                 **kwargs):
    """Create + approve + apply a worker-field change. Returns the request dict."""
    cr = create_approved_worker_change(
        worker_id, worker_version, field_id, new_value=new_value,
        effective_date=effective_date, approver_user_id=approver_user_id, **kwargs
    )
    return apply_change_request_record(cr["id"])


def list_assignment_rows(worker_id, headers=None, **params):
    """List assignment rows for a worker, ascending by effective_start_date."""
    params = {"worker_id": worker_id, **params}
    resp = api_client.list_position_assignments(headers or ANALYST, params=params)
    data = get_success_data(resp)
    assert resp.status_code == 200, f"Setup failed: list assignments -> {resp.text}"
    assert isinstance(data, list)
    return sorted(data, key=lambda r: r["effective_start_date"])


def list_events(headers=None, **params):
    resp = api_client.list_integration_events(headers or OPERATOR, params=params)
    data = get_success_data(resp)
    assert resp.status_code == 200, f"Setup failed: list events -> {resp.text}"
    assert isinstance(data, list)
    return data


def list_audit_entries(headers=None, **params):
    resp = api_client.list_audit_entries(headers or STEWARD, params=params)
    data = get_success_data(resp)
    assert resp.status_code == 200, f"Setup failed: list audit entries -> {resp.text}"
    assert isinstance(data, list)
    return data


def list_exceptions(headers=None, **params):
    resp = api_client.list_exception_records(headers or STEWARD, params=params)
    data = get_success_data(resp)
    assert resp.status_code == 200, f"Setup failed: list exceptions -> {resp.text}"
    assert isinstance(data, list)
    return data


# ---------------------------------------------------------------------------
# Tier 2 composite: worker + field + provisioned approver
# ---------------------------------------------------------------------------

def setup_worker_with_field(worker_number="W1", salary=10000,
                            hire_date=DEFAULT_HIRE_DATE,
                            field_key="assignment.salary_cents",
                            sensitivity="INTERNAL", history_policy="CORRECTABLE",
                            channels=None, approver_user_id="appr-1",
                            initial_pay_grade=None, initial_location_code=None):
    """Position + worker + ACTIVE data field + PROVISIONED CHANGE_APPROVER grant.

    Returns dict(position, worker, field, approver_grant).
    """
    position = create_position_record()
    worker = create_worker_record(
        position["id"], worker_number=worker_number, hire_date=hire_date, salary=salary,
        initial_pay_grade=initial_pay_grade, initial_location_code=initial_location_code,
    )
    field = create_data_field_record(
        field_key=field_key, sensitivity=sensitivity,
        history_policy=history_policy, channels=channels,
    )
    grant = provision_grant(approver_user_id, "CHANGE_APPROVER")
    return {"position": position, "worker": worker, "field": field, "approver_grant": grant}


# ---------------------------------------------------------------------------
# MassChangeBatch lifecycle (Tier 3)
# ---------------------------------------------------------------------------

def create_batch_record(name="reorg"):
    resp = api_client.create_batch(create_batch_payload(name=name), ANALYST)
    data = get_success_data(resp)
    assert resp.status_code == 201, f"Setup failed: create batch -> {resp.text}"
    return data


def add_batch_line_record(batch_id, worker_id, field_id, new_value, line_index=1,
                          effective_date="2026-09-01"):
    payload = create_batch_line_payload(
        line_index=line_index, target_worker_id=worker_id, target_field_id=field_id,
        new_value=new_value, effective_date=effective_date,
    )
    resp = api_client.add_batch_line(batch_id, payload, ANALYST)
    data = get_success_data(resp)
    assert resp.status_code == 201, f"Setup failed: add batch line -> {resp.text}"
    return data


def get_batch_version(batch_id):
    resp = api_client.get_batch(batch_id, ANALYST)
    data = get_success_data(resp)
    assert resp.status_code == 200, f"Setup failed: get batch -> {resp.text}"
    return data["version"]


def submit_batch_record(batch_id):
    """Submit at the batch's current version. Returns the batch dict."""
    version = get_batch_version(batch_id)
    resp = api_client.submit_batch(batch_id, {"expected_batch_version": version}, ANALYST)
    data = get_success_data(resp)
    assert resp.status_code == 200, f"Setup failed: submit batch -> {resp.text}"
    return data


def schedule_batch_record(batch_id, scheduled_effective_date="2026-08-15"):
    resp = api_client.schedule_batch(
        batch_id, {"scheduled_effective_date": scheduled_effective_date}, ANALYST
    )
    data = get_success_data(resp)
    assert resp.status_code == 200, f"Setup failed: schedule batch -> {resp.text}"
    return data


def execute_batch_record(batch_id):
    resp = api_client.execute_batch(batch_id, ANALYST)
    data = get_success_data(resp)
    assert resp.status_code == 200, f"Setup failed: execute batch -> {resp.text}"
    return data


def create_scheduled_batch(lines, name="reorg", scheduled_effective_date="2026-08-15"):
    """Create a batch, add lines [(worker_id, field_id, new_value, effective_date?)...],
    submit and schedule it. Returns (batch, lines_responses)."""
    batch = create_batch_record(name=name)
    line_dicts = []
    for i, line in enumerate(lines, start=1):
        worker_id, field_id, new_value = line[0], line[1], line[2]
        effective_date = line[3] if len(line) > 3 else "2026-09-01"
        line_dicts.append(
            add_batch_line_record(batch["id"], worker_id, field_id, new_value,
                                  line_index=i, effective_date=effective_date)
        )
    batch = submit_batch_record(batch["id"])
    assert batch["status"] == "VALIDATED", (
        f"Setup failed: batch expected VALIDATED, got {batch['status']}"
    )
    batch = schedule_batch_record(batch["id"], scheduled_effective_date)
    return batch, line_dicts


# ---------------------------------------------------------------------------
# Integration event queue helpers
# ---------------------------------------------------------------------------

def dispatch_event(event_id, outcome):
    resp = api_client.dispatch_integration_event(event_id, {"outcome": outcome}, OPERATOR)
    data = get_success_data(resp)
    assert resp.status_code == 200, f"Setup failed: dispatch event -> {resp.text}"
    return data


def retry_event(event_id):
    resp = api_client.retry_integration_event(event_id, OPERATOR)
    data = get_success_data(resp)
    assert resp.status_code == 200, f"Setup failed: retry event -> {resp.text}"
    return data


def drive_event_to_dead_letter(event_id):
    """Dispatch FAILED / retry until the event dead-letters at retry_count 3."""
    last = None
    for _ in range(3):
        last = dispatch_event(event_id, "FAILED")
        if last["status"] == "DEAD_LETTERED":
            return last
        retry_event(event_id)
    assert last is not None and last["status"] == "DEAD_LETTERED", (
        f"Setup failed: event did not dead-letter, final {last and last['status']}"
    )
    return last


# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------

def advance_clock(to_iso8601):
    resp = api_client.set_clock({"to_iso8601": to_iso8601}, SECADMIN)
    data = get_success_data(resp)
    assert resp.status_code == 200, f"Setup failed: set clock -> {resp.text}"
    return data
