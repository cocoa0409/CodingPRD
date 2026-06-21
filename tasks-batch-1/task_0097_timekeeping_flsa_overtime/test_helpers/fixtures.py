"""Composite setup helpers.

Each fixture builds its preconditions from scratch (the server DB is empty before
every test). Fixtures use get_success_data() so setup failures surface as clear
"Setup step failed" errors. Employee-acting calls (punch open/close, own tip
declarations) always thread the real Employee.id through make_employee_headers().

Date convention: workweeks below start 2026-06-01 (a Monday), matching the
employer default workweek_start_dow = MON.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .test_users import (
    make_payroll_admin_headers, make_supervisor_headers, make_employee_headers,
)
from . import factories as f

ADMIN = make_payroll_admin_headers()
SUP1 = make_supervisor_headers("sup-1")
SUP2 = make_supervisor_headers("sup-2")
SUP9 = make_supervisor_headers("sup-9")

__all__ = [
    "ADMIN", "SUP1", "SUP2", "SUP9",
    "create_employer", "create_wage_ruleset", "create_worksite", "create_employee",
    "setup_ca_employer", "setup_tx_employer",
    "create_scheduled_shift", "open_punch", "close_punch",
    "create_closed_punch", "create_open_punch",
    "setup_ca_worker_with_closed_punch",
    "create_draft_week", "submit_week", "approve_week",
    "setup_submitted_week", "setup_approved_week",
    "create_payroll_run", "include_week", "setup_locked_week_in_run",
    "create_tip_pool", "declare_tip", "setup_tip_pool_with_contributions",
    "setup_multi_day_worker",
]


# ─── Tier 0: configuration primitives ─────────────────

def create_employer(api=api_client, **overrides) -> dict:
    return get_success_data(api.create_employer(f.create_employer_payload(**overrides), ADMIN))


def create_wage_ruleset(api, employer_id, state_code="CA", **overrides) -> dict:
    return get_success_data(
        api.create_wage_ruleset(
            f.create_wage_ruleset_payload(employer_id, state_code, **overrides), ADMIN)
    )


def create_worksite(api, employer_id, state_code="CA", **overrides) -> dict:
    return get_success_data(
        api.create_worksite(f.create_worksite_payload(employer_id, state_code, **overrides), ADMIN)
    )


def create_employee(api, employer_id, worksite_id, classification="NON_EXEMPT", **overrides) -> dict:
    return get_success_data(
        api.create_employee(
            f.create_employee_payload(employer_id, worksite_id, classification, **overrides), ADMIN)
    )


def setup_ca_employer(api=api_client, ruleset_overrides=None, employer_overrides=None):
    """Employer + a CA WageRuleSet (daily OT enabled, DT threshold 12, both break
    premiums + seventh-day rule available) + a CA worksite.
    Returns (employer, ruleset, worksite)."""
    ruleset_overrides = ruleset_overrides or {}
    employer_overrides = employer_overrides or {}
    base_ruleset = {
        "daily_ot_enabled": True,
        "daily_ot_threshold_hours": 8,
        "daily_dt_threshold_hours": 12,
        "weekly_ot_threshold_hours": 40,
    }
    base_ruleset.update(ruleset_overrides)
    employer = create_employer(api, **employer_overrides)
    ruleset = create_wage_ruleset(api, employer["id"], "CA", **base_ruleset)
    worksite = create_worksite(api, employer["id"], "CA")
    return employer, ruleset, worksite


def setup_tx_employer(api=api_client, ruleset_overrides=None, employer_overrides=None):
    """Employer + a TX WageRuleSet (weekly-only FLSA) + a TX worksite.
    Returns (employer, ruleset, worksite)."""
    ruleset_overrides = ruleset_overrides or {}
    employer_overrides = employer_overrides or {}
    base_ruleset = {"daily_ot_enabled": False, "weekly_ot_threshold_hours": 40}
    base_ruleset.update(ruleset_overrides)
    employer = create_employer(api, **employer_overrides)
    ruleset = create_wage_ruleset(api, employer["id"], "TX", **base_ruleset)
    worksite = create_worksite(api, employer["id"], "TX")
    return employer, ruleset, worksite


# ─── Tier 1: shift + punch lifecycle ──────────────────

def create_scheduled_shift(api, employee_id, worksite_id, scheduled_start, scheduled_end) -> dict:
    return get_success_data(
        api.create_shift(
            f.create_shift_payload(employee_id, worksite_id, scheduled_start, scheduled_end), SUP1)
    )


def open_punch(api, shift_id, employee_id, clock_in) -> dict:
    return get_success_data(
        api.open_punch(shift_id, f.open_punch_payload(clock_in), make_employee_headers(employee_id))
    )


def close_punch(api, punch_id, employee_id, clock_out) -> dict:
    return get_success_data(
        api.close_punch(punch_id, f.close_punch_payload(clock_out), make_employee_headers(employee_id))
    )


def create_closed_punch(api, employee_id, worksite_id, scheduled_start,
                        scheduled_end, clock_in, clock_out):
    """Schedule a shift, open a punch, close it. Returns (shift, punch_closed).
    `shift` is the SCHEDULED snapshot; re-GET if the post-close state is needed."""
    shift = create_scheduled_shift(api, employee_id, worksite_id, scheduled_start, scheduled_end)
    open_p = open_punch(api, shift["id"], employee_id, clock_in)
    closed = close_punch(api, open_p["id"], employee_id, clock_out)
    return shift, closed


def create_open_punch(api, employee_id, worksite_id, scheduled_start, scheduled_end, clock_in):
    """Schedule a shift and open a punch on it (left OPEN). Returns (shift, punch_open)."""
    shift = create_scheduled_shift(api, employee_id, worksite_id, scheduled_start, scheduled_end)
    open_p = open_punch(api, shift["id"], employee_id, clock_in)
    return shift, open_p


# ─── Tier 2: single-day CA/TX worker with one closed punch ────

def setup_ca_worker_with_closed_punch(api=api_client, base_rate_cents=2000,
                                      clock_in="2026-06-01T08:00:00Z",
                                      clock_out="2026-06-01T16:00:00Z",
                                      classification="NON_EXEMPT",
                                      employee_overrides=None,
                                      ruleset_overrides=None):
    """CA employer/worksite + one employee with one CLOSED punch over the given
    interval, plus a DRAFT timesheet week for 2026-06-01.
    Returns dict(employer, ruleset, worksite, employee, shift, punch, week)."""
    employee_overrides = employee_overrides or {}
    employer, ruleset, worksite = setup_ca_employer(api, ruleset_overrides=ruleset_overrides)
    employee = create_employee(api, employer["id"], worksite["id"], classification,
                               base_rate_cents=base_rate_cents, **employee_overrides)
    shift, punch = create_closed_punch(api, employee["id"], worksite["id"],
                                       clock_in, clock_out, clock_in, clock_out)
    week = create_draft_week(api, employee["id"], "2026-06-01")
    return {"employer": employer, "ruleset": ruleset, "worksite": worksite,
            "employee": employee, "shift": shift, "punch": punch, "week": week}


# ─── Tier 3: timesheet week lifecycle ─────────────────

def create_draft_week(api, employee_id, workweek_start="2026-06-01") -> dict:
    return get_success_data(
        api.create_timesheet_week(
            f.create_timesheet_week_payload(employee_id, workweek_start), SUP1)
    )


def submit_week(api, week_id, supervisor_headers=SUP1) -> dict:
    return get_success_data(api.submit_timesheet_week(week_id, supervisor_headers))


def approve_week(api, week_id, expected_version, supervisor_headers=SUP2) -> dict:
    return get_success_data(
        api.approve_timesheet_week(week_id, f.approve_week_payload(expected_version),
                                   supervisor_headers)
    )


def setup_submitted_week(api=api_client, base_rate_cents=2000,
                         clock_in="2026-06-01T08:00:00Z",
                         clock_out="2026-06-01T16:00:00Z",
                         classification="NON_EXEMPT",
                         submitter=SUP1, ruleset_overrides=None):
    """CA worker with one CLOSED punch, week DRAFT -> SUBMITTED by `submitter`.
    Returns dict(..., week=submitted-week-snapshot)."""
    ctx = setup_ca_worker_with_closed_punch(
        api, base_rate_cents=base_rate_cents, clock_in=clock_in, clock_out=clock_out,
        classification=classification, ruleset_overrides=ruleset_overrides)
    ctx["week"] = submit_week(api, ctx["week"]["id"], submitter)
    return ctx


def setup_approved_week(api=api_client, base_rate_cents=2000,
                        clock_in="2026-06-01T08:00:00Z",
                        clock_out="2026-06-01T16:00:00Z",
                        submitter=SUP1, approver=SUP2,
                        workweek_start="2026-06-01"):
    """CA worker, week SUBMITTED then APPROVED. Returns dict(..., week=approved snapshot)."""
    employer, ruleset, worksite = setup_ca_employer(api)
    employee = create_employee(api, employer["id"], worksite["id"], "NON_EXEMPT",
                               base_rate_cents=base_rate_cents)
    shift, punch = create_closed_punch(api, employee["id"], worksite["id"],
                                       clock_in, clock_out, clock_in, clock_out)
    week = create_draft_week(api, employee["id"], workweek_start)
    submitted = submit_week(api, week["id"], submitter)
    approved = approve_week(api, week["id"], submitted["version"], approver)
    return {"employer": employer, "ruleset": ruleset, "worksite": worksite,
            "employee": employee, "shift": shift, "punch": punch, "week": approved}


# ─── Tier 4: payroll run lifecycle ────────────────────

def create_payroll_run(api, employer_id, period_start="2026-06-01",
                       period_end="2026-06-07") -> dict:
    return get_success_data(
        api.create_payroll_run(
            f.create_payroll_run_payload(employer_id, period_start, period_end), ADMIN)
    )


def include_week(api, run_id, week_id, expected_version) -> dict:
    return get_success_data(
        api.include_week_in_run(run_id, f.include_week_payload(week_id, expected_version), ADMIN)
    )


def setup_locked_week_in_run(api=api_client, base_rate_cents=2000,
                             period_start="2026-06-01", period_end="2026-06-07"):
    """CA worker, week APPROVED then LOCKED into an OPEN payroll run.
    Returns dict(employer, ruleset, worksite, employee, shift, punch, week, run)
    where `week` is the approved snapshot (pre-lock) and `run` is the post-include
    run snapshot."""
    ctx = setup_approved_week(api, base_rate_cents=base_rate_cents)
    run = create_payroll_run(api, ctx["employer"]["id"], period_start, period_end)
    run_after = include_week(api, run["id"], ctx["week"]["id"], ctx["week"]["version"])
    ctx["run"] = run_after
    return ctx


# ─── Tier 5: tip pool setups ──────────────────────────

def create_tip_pool(api, worksite_id, workday_date="2026-06-01") -> dict:
    return get_success_data(
        api.create_tip_pool(f.create_tip_pool_payload(worksite_id, workday_date), SUP1)
    )


def declare_tip(api, employee_id, workday_date, declared_cents, pool_id=None) -> dict:
    overrides = {}
    if pool_id is not None:
        overrides["pool_id"] = pool_id
    return get_success_data(
        api.create_tip_declaration(
            f.create_tip_declaration_payload(employee_id, workday_date, declared_cents, **overrides),
            make_employee_headers(employee_id))
    )


def setup_tip_pool_with_contributions(api=api_client, contributions=None,
                                      workday_date="2026-06-01"):
    """CA worksite + N tipped employees, each with a CLOSED punch of a given length
    and a tip declaration contributed to one OPEN pool.

    `contributions` is a list of dicts:
      {"name": str, "clock_out": iso, "declared_cents": int}
    Each employee clocks in at 08:00 and out at the given clock_out on workday_date,
    establishing worked_minutes as the allocation weight.
    Returns dict(employer, worksite, pool, employees=[...], declarations=[...])."""
    contributions = contributions or []
    employer, ruleset, worksite = setup_ca_employer(api)
    pool = create_tip_pool(api, worksite["id"], workday_date)
    employees, declarations = [], []
    clock_in = f"{workday_date}T08:00:00Z"
    for c in contributions:
        emp = create_employee(api, employer["id"], worksite["id"], "NON_EXEMPT",
                              full_name=c["name"], base_rate_cents=1600, is_tipped=True)
        create_closed_punch(api, emp["id"], worksite["id"], clock_in, c["clock_out"],
                            clock_in, c["clock_out"])
        decl = declare_tip(api, emp["id"], workday_date, c["declared_cents"], pool["id"])
        employees.append(emp)
        declarations.append(decl)
    pool_after = get_success_data(api.get_tip_pool(pool["id"], SUP1))
    return {"employer": employer, "worksite": worksite, "pool": pool_after,
            "employees": employees, "declarations": declarations}


# ─── Tier 6: multi-day worker (for weekly OT cases) ───

def setup_multi_day_worker(api, employer, worksite, base_rate_cents, days):
    """Create a NON_EXEMPT employee under `employer`/`worksite` who works one CLOSED
    punch per entry in `days`. Each entry is (clock_in_iso, clock_out_iso).
    Returns (employee, [closed_punches...])."""
    employee = create_employee(api, employer["id"], worksite["id"], "NON_EXEMPT",
                               base_rate_cents=base_rate_cents)
    punches = []
    for clock_in, clock_out in days:
        _, punch = create_closed_punch(api, employee["id"], worksite["id"],
                                       clock_in, clock_out, clock_in, clock_out)
        punches.append(punch)
    return employee, punches
