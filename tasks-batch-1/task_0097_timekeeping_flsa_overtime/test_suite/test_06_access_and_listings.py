"""Role-based access control, ownership, authentication, the wage-rule-set
existence/uniqueness validations, and the reverse-reachability listing endpoints.

Covers Queue B rbac, the remaining validations (no-wage-ruleset, duplicate
ruleset), and the endpoint listing instances.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId,
    create_employer_payload, create_wage_ruleset_payload,
    create_shift_payload, create_payroll_run_payload,
    create_break_record_payload,
    create_employer, create_worksite, create_wage_ruleset, setup_ca_employer,
    create_employee as mk_employee,
    create_scheduled_shift, create_closed_punch, create_open_punch,
    edit_punch_payload,
    make_employee_headers, make_supervisor_headers,
    ADMIN, SUP1, SUP9,
)


# ─── Wage rule set existence + uniqueness (Queue B validations) ──

def test_submit_without_wage_ruleset_rejected(api):
    """PRD §3.6: "Before any wage math runs, a governing wage rule set must exist
    for the employer-and-state of the work; if none does, submit (and shift
    creation) is rejected with ERR_NO_WAGE_RULESET."

    Design: Corner/validations/submit_without_wage_ruleset_rejected
    """
    employer = create_employer(api)
    worksite = create_worksite(api, employer["id"], "NV")  # no NV ruleset
    employee = mk_employee(api, employer["id"], worksite["id"], "NON_EXEMPT", base_rate_cents=2000)
    # No CLOSED punch is seeded: shift creation itself requires a governing rule
    # set (PRD §3.6), so the punchless DRAFT week below is the only reachable
    # precondition. The ruleset gate (precedence 5) fires on submit before the
    # open-punch guard, so an empty week still surfaces ERR_NO_WAGE_RULESET.
    from test_helpers import create_draft_week
    week = create_draft_week(api, employee["id"], "2026-06-01")
    resp = api.submit_timesheet_week(week["id"], SUP1)
    validate_error(resp, ApiErrorId.ERR_NO_WAGE_RULESET.value, 422)


def test_duplicate_wage_ruleset_rejected(api):
    """PRD §3.1: "a state code must be unique within an employer, and a second rule
    set for the same employer-and-state pair is rejected with ERR_DUPLICATE_RULESET."

    Design: Corner/validations/duplicate_wage_ruleset_rejected
    """
    employer = create_employer(api)
    create_wage_ruleset(api, employer["id"], "CA", daily_ot_enabled=True)
    resp = api.create_wage_ruleset(
        create_wage_ruleset_payload(employer["id"], "CA", daily_ot_enabled=False), ADMIN)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_RULESET.value, 409)


# ─── RBAC: exclusive operations denied (Queue B rbac) ──

def test_employee_cannot_create_shift(api):
    """PRD §2.1: "Once authenticated, a caller may only invoke the operations their
    role permits; any attempt outside that grant is rejected with ERR_FORBIDDEN
    (HTTP 403)."

    Design: Corner/rbac/employee_cannot_create_shift
    """
    employer, ruleset, worksite = setup_ca_employer(api)
    employee = mk_employee(api, employer["id"], worksite["id"], "NON_EXEMPT", base_rate_cents=2000)
    resp = api.create_shift(
        create_shift_payload(employee["id"], worksite["id"],
                             "2026-06-01T08:00:00Z", "2026-06-01T16:00:00Z"),
        make_employee_headers(employee["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value, 403)


def test_supervisor_cannot_open_payroll_run(api):
    """PRD §2.1: "Once authenticated, a caller may only invoke the operations their
    role permits; any attempt outside that grant is rejected with ERR_FORBIDDEN
    (HTTP 403)."

    Design: Corner/rbac/supervisor_cannot_open_payroll_run
    """
    employer = create_employer(api)
    resp = api.create_payroll_run(
        create_payroll_run_payload(employer["id"], "2026-06-01", "2026-06-07"), SUP1)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value, 403)


def test_employee_cannot_punch_other_employees_shift(api):
    """PRD §2.1: "Ownership checks on any resource that references an employee
    compare that resource's employee_id to the caller's X-User-ID; a mismatch where
    ownership is required is rejected with ERR_NOT_RESOURCE_OWNER (HTTP 403)."

    Design: Corner/rbac/employee_cannot_punch_other_employees_shift
    """
    employer, ruleset, worksite = setup_ca_employer(api)
    e_a = mk_employee(api, employer["id"], worksite["id"], "NON_EXEMPT",
                      full_name="A", base_rate_cents=2000)
    e_b = mk_employee(api, employer["id"], worksite["id"], "NON_EXEMPT",
                      full_name="B", base_rate_cents=2000)
    shift_b = create_scheduled_shift(api, e_b["id"], worksite["id"],
                                     "2026-06-01T08:00:00Z", "2026-06-01T16:00:00Z")
    from test_helpers import open_punch_payload
    resp = api.open_punch(shift_b["id"], open_punch_payload("2026-06-01T08:00:00Z"),
                          make_employee_headers(e_a["id"]))
    validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value, 403)


def test_missing_role_header_unauthenticated(api):
    """PRD §2.1: "A request missing the role header, or carrying a role the system
    does not recognize, is rejected with ERR_UNAUTHENTICATED (HTTP 401)."

    Design: Corner/rbac/missing_role_header_unauthenticated
    """
    employer = create_employer(api)
    # No X-User-Role header.
    resp = api.get_employer(employer["id"], {"Content-Type": "application/json"})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)


# ─── Reverse-reachability listings (Queue B endpoints) ──

def test_list_punches_for_shift_subresource(api):
    """PRD §2.7: "Listing endpoints that expose a parent's children — an employer's
    wage rule sets, a shift's punches, a punch's edit trail, and the like — first
    confirm the parent exists, then return the matching children."

    Design: Corner/endpoints/list_punches_for_shift_subresource
    """
    employer, ruleset, worksite = setup_ca_employer(api)
    employee = mk_employee(api, employer["id"], worksite["id"], "NON_EXEMPT", base_rate_cents=2000)
    shift, punch = create_open_punch(api, employee["id"], worksite["id"],
                                     "2026-06-01T08:00:00Z", "2026-06-01T16:00:00Z",
                                     "2026-06-01T08:00:00Z")
    data, meta = validate_paginated(api.list_shift_punches(shift["id"], SUP1))
    ids = [p["id"] for p in data]
    assert punch["id"] in ids
    assert len([p for p in data if p["shift_id"] == shift["id"]]) == 1


def test_list_punch_edits_audit_trail(api):
    """PRD §2.7: "Listing endpoints that expose a parent's children — an employer's
    wage rule sets, a shift's punches, a punch's edit trail, and the like — first
    confirm the parent exists, then return the matching children."

    Design: Corner/endpoints/list_punch_edits_audit_trail
    """
    employer, ruleset, worksite = setup_ca_employer(api)
    employee = mk_employee(api, employer["id"], worksite["id"], "NON_EXEMPT", base_rate_cents=2000)
    _, punch = create_closed_punch(api, employee["id"], worksite["id"],
                                   "2026-06-01T08:00:00Z", "2026-06-01T16:00:00Z",
                                   "2026-06-01T08:00:00Z", "2026-06-01T16:00:00Z")
    edit = validate_success(api.edit_punch(
        punch["id"], edit_punch_payload("CLOCK_OUT", "2026-06-01T17:00:00Z",
                                        reason="correction"), SUP9), 201)
    data, meta = validate_paginated(api.list_punch_edits(punch["id"], SUP1))
    ids = [e["id"] for e in data]
    assert edit["id"] in ids
    assert len([e for e in data if e["punch_id"] == punch["id"]]) == 1


def test_list_break_records_filtered_by_employee(api):
    """PRD §3.4: "A break is logged against a shift through a break record naming its
    shift_id, the employee_id, the kind (MEAL or REST), and whether it was taken".
    PRD §2.3: "every list endpoint returns its resources sorted by creation
    timestamp (created_at) in ascending order."

    Design: Corner/endpoints/list_break_records_filtered_by_employee
    """
    employer, ruleset, worksite = setup_ca_employer(
        api, ruleset_overrides={"meal_break_premium_enabled": True})
    employee = mk_employee(api, employer["id"], worksite["id"], "NON_EXEMPT", base_rate_cents=2000)
    shift = create_scheduled_shift(api, employee["id"], worksite["id"],
                                   "2026-06-01T08:00:00Z", "2026-06-01T16:00:00Z")
    br = validate_success(api.create_break_record(
        create_break_record_payload(shift["id"], employee["id"], "MEAL", False), SUP1), 201)
    data, meta = validate_paginated(
        api.list_break_records(SUP1, params={"employee_id": employee["id"]}))
    ids = [b["id"] for b in data]
    assert br["id"] in ids
    assert all(b["employee_id"] == employee["id"] for b in data)
