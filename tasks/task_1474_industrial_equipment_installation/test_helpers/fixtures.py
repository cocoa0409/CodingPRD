"""Composite setup helpers.

The interesting claims in this PRD require the system to be in a specific
state that takes many API calls to reach (a project cannot book a crane until
it is INSTALLING with an approved rigging plan, and reaching INSTALLING
requires an active safety plan plus a cured, accepted site survey). These
helpers encapsulate those multi-step preambles so tests can focus on
assertions.

All helpers use get_success_data() so a broken precondition surfaces as a
clear "Setup step failed" error rather than a confusing assertion mismatch.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    CLOCK_CURED,
    CLOCK_IN_LIFT_WINDOW,
    DEFAULT_CRANE_REF,
    DEFAULT_LIFT_END,
    DEFAULT_LIFT_START,
)
from .factories import (
    create_alignment_record_payload,
    create_checklist_payload,
    create_invoice_payload,
    create_labor_entry_payload,
    create_lift_permit_payload,
    create_lockout_window_payload,
    create_project_payload,
    create_rigging_plan_payload,
    create_safety_plan_payload,
    create_site_survey_payload,
)
from .test_users import (
    TEST_USERS,
    make_customer_rep_headers,
    make_payroll_clerk_headers,
    make_site_supervisor_headers,
)

PM = TEST_USERS["project_manager_headers"]
SUP = TEST_USERS["site_supervisor_headers"]
SO = TEST_USERS["safety_officer_headers"]
PAY = TEST_USERS["payroll_clerk_headers"]
CUST = TEST_USERS["customer_rep_headers"]


# ---------------------------------------------------------------------------
# Tier 0: primitive single-call helpers
# ---------------------------------------------------------------------------

def set_clock(to_iso8601: str) -> dict:
    """Move the logical clock; drives automatic time-based transitions."""
    return get_success_data(api_client.set_current_utc({"to_iso8601": to_iso8601}, PM))


def get_project(project_id: str) -> dict:
    return get_success_data(api_client.get_project(project_id, PM))


def create_project(**overrides) -> dict:
    """Create a project with defaults for anything not overridden."""
    return get_success_data(api_client.create_project(create_project_payload(**overrides), PM))


def advance_project(project_id: str) -> dict:
    """Advance one hop in the work-phase chain. Returns the updated project."""
    return get_success_data(api_client.advance_project(project_id, PM))


# ---------------------------------------------------------------------------
# Tier 1: single-entity state progression
# ---------------------------------------------------------------------------

def create_active_safety_plan(project_id: str, **overrides) -> dict:
    """Create the project's safety plan and activate it. Returns the plan."""
    plan = get_success_data(
        api_client.create_safety_plan(
            create_safety_plan_payload(project_id=project_id, **overrides), SO
        )
    )
    return get_success_data(api_client.activate_safety_plan(plan["id"], SO))


def create_accepted_site_survey(project_id: str, cure_clock: str = CLOCK_CURED, **overrides) -> dict:
    """Create a passing survey, submit it, cure the foundation via the logical
    clock, and review-accept it. Returns the ACCEPTED survey."""
    survey = get_success_data(
        api_client.create_site_survey(
            create_site_survey_payload(project_id=project_id, **overrides), SUP
        )
    )
    get_success_data(api_client.submit_site_survey(survey["id"], SUP))
    set_clock(cure_clock)
    return get_success_data(
        api_client.review_site_survey(survey["id"], {"outcome": "ACCEPTED"}, PM)
    )


def create_approved_rigging_plan(project_id: str, **overrides) -> dict:
    """Create -> submit -> review-APPROVED a rigging plan. Reads the current
    project version for the optimistic-concurrency field. Returns the plan."""
    version = get_project(project_id)["version"]
    plan = get_success_data(
        api_client.create_rigging_plan(
            create_rigging_plan_payload(
                project_id=project_id, expected_project_version=version, **overrides
            ),
            SUP,
        )
    )
    get_success_data(api_client.submit_rigging_plan(plan["id"], SUP))
    return get_success_data(
        api_client.review_rigging_plan(plan["id"], {"outcome": "APPROVED"}, PM)
    )


def create_approved_labor_entry(
    project_id: str,
    submitter_id: str = "sup-1",
    approver_id: str = "pay-1",
    **overrides,
) -> dict:
    """Create -> submit -> approve a labor entry. Returns the APPROVED entry."""
    entry = get_success_data(
        api_client.create_labor_entry(
            create_labor_entry_payload(project_id=project_id, **overrides), SUP
        )
    )
    get_success_data(
        api_client.submit_labor_entry(entry["id"], make_site_supervisor_headers(submitter_id))
    )
    return get_success_data(
        api_client.approve_labor_entry(entry["id"], make_payroll_clerk_headers(approver_id))
    )


# ---------------------------------------------------------------------------
# Tier 2: project phase progression (the work-phase chain)
# ---------------------------------------------------------------------------

def setup_project_mobilized(**project_overrides) -> dict:
    """Project + ACTIVE safety plan + advance to MOBILIZED."""
    project = create_project(**project_overrides)
    plan = create_active_safety_plan(project["id"])
    project = advance_project(project["id"])
    return {"project": project, "safety_plan": plan}


def setup_project_installing(**project_overrides) -> dict:
    """MOBILIZED + ACCEPTED site survey + advance to INSTALLING."""
    ctx = setup_project_mobilized(**project_overrides)
    survey = create_accepted_site_survey(ctx["project"]["id"])
    project = advance_project(ctx["project"]["id"])
    ctx["project"] = project
    ctx["site_survey"] = survey
    return ctx


def setup_project_with_approved_rigging(**project_overrides) -> dict:
    """INSTALLING + one APPROVED rigging plan pinned on the project."""
    ctx = setup_project_installing(**project_overrides)
    plan = create_approved_rigging_plan(ctx["project"]["id"])
    ctx["rigging_plan"] = plan
    ctx["project"] = get_project(ctx["project"]["id"])
    return ctx


def create_executed_lift_permit(
    project_id: str,
    crane_ref: str = DEFAULT_CRANE_REF,
    lift_starts_at: str = DEFAULT_LIFT_START,
    lift_ends_at: str = DEFAULT_LIFT_END,
    execute_at: str = CLOCK_IN_LIFT_WINDOW,
    **overrides,
) -> dict:
    """Book a crane window, move the clock inside it, and execute the lift.
    Returns the EXECUTED permit (equipment_charge_cents computed)."""
    permit = get_success_data(
        api_client.create_lift_permit(
            create_lift_permit_payload(
                project_id=project_id,
                crane_ref=crane_ref,
                lift_starts_at=lift_starts_at,
                lift_ends_at=lift_ends_at,
                **overrides,
            ),
            SUP,
        )
    )
    set_clock(execute_at)
    return get_success_data(api_client.execute_lift_permit(permit["id"], SUP))


def setup_project_commissioning(**project_overrides) -> dict:
    """INSTALLING + approved rigging plan + one EXECUTED lift + advance to
    COMMISSIONING."""
    ctx = setup_project_with_approved_rigging(**project_overrides)
    permit = create_executed_lift_permit(ctx["project"]["id"])
    project = advance_project(ctx["project"]["id"])
    ctx["project"] = project
    ctx["lift_permit"] = permit
    return ctx


# ---------------------------------------------------------------------------
# Tier 3: commissioning checklist lifecycle
# ---------------------------------------------------------------------------

def create_checklist(project_id: str, items=None, **overrides) -> dict:
    if items is not None:
        overrides["items"] = items
    return get_success_data(
        api_client.create_commissioning_checklist(
            create_checklist_payload(project_id=project_id, **overrides), PM
        )
    )


def check_all_items(checklist: dict, checker_id: str = "sup-1") -> dict:
    """Check every item on the checklist. Returns the updated checklist."""
    data = checklist
    headers = make_site_supervisor_headers(checker_id)
    for item in checklist["items"]:
        data = get_success_data(
            api_client.check_checklist_item(
                checklist["id"], {"item_key": item["item_key"]}, headers
            )
        )
    return data


def create_accepted_passing_alignment(project_id: str, **overrides) -> dict:
    """Record an alignment measurement that passes its tolerance class and
    review-accept it. Returns the ACCEPTED record."""
    record = get_success_data(
        api_client.create_alignment_record(
            create_alignment_record_payload(project_id=project_id, **overrides), SUP
        )
    )
    return get_success_data(
        api_client.review_alignment_record(record["id"], {"outcome": "ACCEPTED"}, PM)
    )


def setup_submitted_checklist(project_id: str, items=None, signer_id: str = "cust-1") -> dict:
    """Checklist with every required item checked, the alignment gate
    satisfied (one ACCEPTED PASS record, none pending), then submitted."""
    checklist = create_checklist(project_id, items=items)
    alignment = create_accepted_passing_alignment(project_id)
    checklist = check_all_items(checklist)
    checklist = get_success_data(api_client.submit_commissioning_checklist(checklist["id"], PM))
    return {"checklist": checklist, "alignment_record": alignment}


def setup_signed_off_checklist(project_id: str, signer_id: str = "cust-1") -> dict:
    """Full checklist lifecycle through customer sign-off."""
    ctx = setup_submitted_checklist(project_id)
    checklist = get_success_data(
        api_client.sign_off_checklist(
            ctx["checklist"]["id"], {}, make_customer_rep_headers(signer_id)
        )
    )
    ctx["checklist"] = checklist
    return ctx


# ---------------------------------------------------------------------------
# Tier 5: terminal-state setups
# ---------------------------------------------------------------------------

def setup_project_completed(**project_overrides) -> dict:
    """Full lifecycle through COMPLETED: mobilized -> installing -> approved
    rigging -> executed lift -> commissioning -> signed-off checklist ->
    completed."""
    ctx = setup_project_commissioning(**project_overrides)
    checklist_ctx = setup_signed_off_checklist(ctx["project"]["id"])
    ctx.update(checklist_ctx)
    ctx["project"] = advance_project(ctx["project"]["id"])
    return ctx


# ---------------------------------------------------------------------------
# Tier 4: billing helpers
# ---------------------------------------------------------------------------

def setup_tm_billable_scenario(
    contract_amount_cents=5_000_000,
    labor_hours=8,
    work_date="2026-08-09",
    with_lift=True,
    **project_overrides,
) -> dict:
    """TM project in INSTALLING carrying one APPROVED labor entry (default 8h
    MW_JOURNEYMAN DAY on 2026-08-09, total_cost_cents 84800) and, when
    with_lift, one EXECUTED four-hour lift on 2026-08-10 (charge 180000 at the
    default equipment rate). Used by invoice-amount tests."""
    project_overrides.setdefault("billing_mode", "TM")
    project_overrides.setdefault("contract_amount_cents", contract_amount_cents)
    ctx = setup_project_installing(**project_overrides)
    entry = create_approved_labor_entry(
        ctx["project"]["id"], work_date=work_date, hours_worked=labor_hours
    )
    ctx["labor_entry"] = entry
    if with_lift:
        create_approved_rigging_plan(ctx["project"]["id"])
        ctx["lift_permit"] = create_executed_lift_permit(ctx["project"]["id"])
    ctx["project"] = get_project(ctx["project"]["id"])
    return ctx


def create_invoice(project_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_invoice(create_invoice_payload(project_id=project_id, **overrides), PM)
    )


def create_lockout_window(project_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_lockout_window(
            create_lockout_window_payload(project_id=project_id, **overrides), SO
        )
    )


def list_labor_entries(project_id: str, params=None) -> list:
    data, _meta = _paginated(api_client.list_labor_entries(project_id, PM, params=params))
    return data


def list_lift_permits(project_id: str, params=None) -> list:
    data, _meta = _paginated(api_client.list_lift_permits(project_id, PM, params=params))
    return data


def list_lockout_windows(project_id: str, params=None) -> list:
    data, _meta = _paginated(api_client.list_lockout_windows(project_id, PM, params=params))
    return data


def list_rigging_plans(project_id: str, params=None) -> list:
    data, _meta = _paginated(api_client.list_rigging_plans(project_id, PM, params=params))
    return data


def list_invoices(project_id: str, params=None) -> list:
    data, _meta = _paginated(api_client.list_invoices(project_id, PM, params=params))
    return data


def _paginated(response):
    from prd_bench_local_runner.testing import validate_paginated

    return validate_paginated(response)


def find_labor_entry(project_id: str, entry_id: str) -> dict:
    """Read back a single labor entry through the project listing."""
    for entry in list_labor_entries(project_id):
        if entry["id"] == entry_id:
            return entry
    raise AssertionError(f"Labor entry {entry_id} not found in project listing")


def find_lift_permit(project_id: str, permit_id: str) -> dict:
    for permit in list_lift_permits(project_id):
        if permit["id"] == permit_id:
            return permit
    raise AssertionError(f"Lift permit {permit_id} not found in project listing")


def find_lockout_window(project_id: str, window_id: str) -> dict:
    for window in list_lockout_windows(project_id):
        if window["id"] == window_id:
            return window
    raise AssertionError(f"Lockout window {window_id} not found in project listing")


def find_rigging_plan(project_id: str, plan_id: str) -> dict:
    for plan in list_rigging_plans(project_id):
        if plan["id"] == plan_id:
            return plan
    raise AssertionError(f"Rigging plan {plan_id} not found in project listing")
