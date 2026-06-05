"""Composite setup helpers for Benefits Open Enrollment tests.

Each helper rebuilds its preconditions from scratch using only PRD-declared endpoints,
because the harness restarts the server (empty DB) before every test. Helpers use the
lenient get_success_data() so setup failures surface as clear "Setup step failed" errors.

All four operator roles are opaque (PRD Section 2.1); the segregation-of-duties helpers
thread explicit X-User-IDs where the workflow records and compares them.
"""
from prd_bench_local_runner.testing import get_success_data, build_user_headers

from .api_client import api_client as _api
from .test_users import TEST_USERS

_ADMIN = TEST_USERS["benefits_admin_headers"]
_VERIFIER = TEST_USERS["dependent_verifier_headers"]
_PAYROLL = TEST_USERS["payroll_officer_headers"]
_COMPLIANCE = TEST_USERS["compliance_officer_headers"]


# ─── Low-level building blocks ────────────────────────

def advance_clock(to_iso8601: str):
    """Set the server clock to an absolute instant (PRD Section 2.7)."""
    get_success_data(_api.advance_clock({"to_iso8601": to_iso8601}, _ADMIN))


def create_employee(full_name="Test Employee", hire_date="2026-01-01",
                    employment_type="FULL_TIME", payroll_schedule="SEMI_MONTHLY",
                    monthly_household_income_cents=500000) -> dict:
    return get_success_data(_api.create_employee({
        "full_name": full_name,
        "hire_date": hire_date,
        "employment_type": employment_type,
        "payroll_schedule": payroll_schedule,
        "monthly_household_income_cents": monthly_household_income_cents,
    }, _ADMIN))


def create_waiting_period(employee_id, window_type="INITIAL",
                          start_date="2026-01-01", end_date="2026-02-01") -> dict:
    return get_success_data(_api.create_waiting_period(employee_id, {
        "window_type": window_type,
        "start_date": start_date,
        "end_date": end_date,
    }, _ADMIN))


def create_offering(benefit_type="MEDICAL", name="Gold PPO",
                    requires_eoi=None, guaranteed_issue_amount_cents=None) -> dict:
    payload = {"benefit_type": benefit_type, "name": name}
    if requires_eoi is not None:
        payload["requires_eoi"] = requires_eoi
    if guaranteed_issue_amount_cents is not None:
        payload["guaranteed_issue_amount_cents"] = guaranteed_issue_amount_cents
    return get_success_data(_api.create_plan_offering(payload, _ADMIN))


def create_tier(offering_id, coverage_level="EMPLOYEE_ONLY",
                monthly_premium_cents=60000, employer_contribution_pct=0.70,
                rate_per_1000_monthly_cents=None, is_lowest_cost_self_only=None) -> dict:
    payload = {
        "plan_offering_id": offering_id,
        "coverage_level": coverage_level,
        "monthly_premium_cents": monthly_premium_cents,
        "employer_contribution_pct": employer_contribution_pct,
    }
    if rate_per_1000_monthly_cents is not None:
        payload["rate_per_1000_monthly_cents"] = rate_per_1000_monthly_cents
    if is_lowest_cost_self_only is not None:
        payload["is_lowest_cost_self_only"] = is_lowest_cost_self_only
    return get_success_data(_api.create_plan_tier(payload, _ADMIN))


def create_draft_enrollment(employee_id, tier_id, coverage_start_date="2026-02-01",
                            coverage_amount_cents=None) -> dict:
    payload = {"plan_tier_id": tier_id, "coverage_start_date": coverage_start_date}
    if coverage_amount_cents is not None:
        payload["coverage_amount_cents"] = coverage_amount_cents
    return get_success_data(_api.create_enrollment(employee_id, payload, _ADMIN))


def employee_version(employee_id) -> int:
    return get_success_data(_api.get_employee(employee_id, _ADMIN))["version"]


def activate_enrollment(enrollment_id, employee_id) -> dict:
    """Activate using the employee's current (freshly-observed) version (PRD Section 2.8)."""
    ev = employee_version(employee_id)
    return get_success_data(_api.activate_enrollment(
        enrollment_id, {"expected_employee_version": ev}, _ADMIN))


def run_payroll(employee_id) -> dict:
    return get_success_data(_api.run_payroll({"employee_id": employee_id}, _PAYROLL))


# ─── Tier 1/2: eligible employee with catalog ─────────

def setup_eligible_employee(payroll_schedule="SEMI_MONTHLY",
                            monthly_household_income_cents=500000,
                            hire_date="2026-01-01",
                            wp_start="2026-01-01", wp_end="2026-02-01",
                            clock_after="2026-02-01T00:00:00Z",
                            clock_before="2026-01-01T00:00:00Z") -> dict:
    """Create a FULL_TIME employee, attach an INITIAL waiting period, advance the clock
    past its end_date so the employee becomes ELIGIBLE (PRD Sections 2.7, 3.1).
    Returns the eligible Employee dict (refreshed)."""
    advance_clock(clock_before)
    emp = create_employee(payroll_schedule=payroll_schedule,
                          hire_date=hire_date,
                          monthly_household_income_cents=monthly_household_income_cents)
    create_waiting_period(emp["id"], start_date=wp_start, end_date=wp_end)
    advance_clock(clock_after)
    return get_success_data(_api.get_employee(emp["id"], _ADMIN))


def setup_active_medical_enrollment(payroll_schedule="SEMI_MONTHLY",
                                    monthly_premium_cents=60000,
                                    employer_contribution_pct=0.70,
                                    coverage_level="EMPLOYEE_ONLY",
                                    coverage_start_date="2026-02-01",
                                    clock_after="2026-02-01T00:00:00Z") -> dict:
    """Eligible employee + MEDICAL offering/tier + one ACTIVE enrollment.
    Returns {employee, offering, tier, enrollment}."""
    emp = setup_eligible_employee(payroll_schedule=payroll_schedule,
                                  clock_after=clock_after)
    off = create_offering(benefit_type="MEDICAL", name="Gold PPO")
    tier = create_tier(off["id"], coverage_level=coverage_level,
                       monthly_premium_cents=monthly_premium_cents,
                       employer_contribution_pct=employer_contribution_pct)
    enr = create_draft_enrollment(emp["id"], tier["id"],
                                  coverage_start_date=coverage_start_date)
    enr = activate_enrollment(enr["id"], emp["id"])
    return {"employee": emp, "offering": off, "tier": tier, "enrollment": enr}


# ─── Tier 3: voluntary-life / EOI lifecycle ───────────

def setup_pending_eoi_enrollment(coverage_amount_cents=30000000,
                                 guaranteed_issue_amount_cents=15000000,
                                 rate_per_1000_monthly_cents=25,
                                 make_eligible=True,
                                 coverage_start_date="2026-02-01") -> dict:
    """Eligible (or WAITING) employee + VOLUNTARY_LIFE offering requiring EOI + a DRAFT
    enrollment with coverage above GI, submitted for EOI (PENDING_EOI) with its
    PENDING EOIRequest created. Returns {employee, offering, tier, enrollment, eoi_request}."""
    if make_eligible:
        emp = setup_eligible_employee()
    else:
        emp = create_employee()
    off = create_offering(benefit_type="VOLUNTARY_LIFE", name="Voluntary Life",
                          requires_eoi=True,
                          guaranteed_issue_amount_cents=guaranteed_issue_amount_cents)
    tier = create_tier(off["id"], coverage_level="EMPLOYEE_ONLY",
                       monthly_premium_cents=1, employer_contribution_pct=0.0,
                       rate_per_1000_monthly_cents=rate_per_1000_monthly_cents)
    enr = create_draft_enrollment(emp["id"], tier["id"],
                                  coverage_start_date=coverage_start_date,
                                  coverage_amount_cents=coverage_amount_cents)
    get_success_data(_api.submit_eoi_enrollment(enr["id"], _ADMIN))
    eoi_list, _ = _list_data(_api.list_eoi_requests(_COMPLIANCE, params={"enrollment_id": enr["id"]}))
    eoi = eoi_list[0]
    return {"employee": emp, "offering": off, "tier": tier, "enrollment": enr, "eoi_request": eoi}


# ─── Tier 4: life-event / retro deduction setups ──────

def setup_silver_active_with_payrolls(num_payrolls=3,
                                      silver_premium=30000,
                                      gold_premium=90000,
                                      employer_pct=0.70) -> dict:
    """Eligible SEMI_MONTHLY employee with an ACTIVE SILVER EMPLOYEE_ONLY enrollment, then
    N payroll runs posting REGULAR deduction lines; plus a GOLD EMPLOYEE_PLUS_SPOUSE tier
    ready for a life-event move (PRD Sections 3.5-3.7).

    SILVER per_paycheck (SEMI): round(((30000 - round(30000*0.70))*12)/24) = 4500.
    GOLD  per_paycheck (SEMI): round(((90000 - round(90000*0.70))*12)/24) = 13500.

    Returns {employee, silver_tier, gold_tier, enrollment}.
    """
    advance_clock("2026-01-01T00:00:00Z")
    emp = create_employee(payroll_schedule="SEMI_MONTHLY")
    create_waiting_period(emp["id"], start_date="2026-01-01", end_date="2026-02-01")
    silver_off = create_offering(benefit_type="MEDICAL", name="Silver PPO")
    silver_tier = create_tier(silver_off["id"], coverage_level="EMPLOYEE_ONLY",
                              monthly_premium_cents=silver_premium,
                              employer_contribution_pct=employer_pct)
    gold_off = create_offering(benefit_type="MEDICAL", name="Gold PPO")
    gold_tier = create_tier(gold_off["id"], coverage_level="EMPLOYEE_PLUS_SPOUSE",
                            monthly_premium_cents=gold_premium,
                            employer_contribution_pct=employer_pct)
    advance_clock("2026-02-10T00:00:00Z")
    enr = create_draft_enrollment(emp["id"], silver_tier["id"], coverage_start_date="2026-02-01")
    enr = activate_enrollment(enr["id"], emp["id"])
    for _ in range(num_payrolls):
        run_payroll(emp["id"])
    return {"employee": emp, "silver_tier": silver_tier, "gold_tier": gold_tier, "enrollment": enr}


def submit_life_event(employee_id, requested_plan_tier_id, adjustment_mode,
                      event_date="2026-02-01", event_type="MARRIAGE",
                      submitter_user_id="submitter") -> dict:
    """Submit a life event under a BenefitsAdmin with an explicit X-User-ID (recorded as
    submitted_by_user_id). Returns the LifeEvent dict."""
    headers = build_user_headers(submitter_user_id, "BenefitsAdmin")
    return get_success_data(_api.create_life_event(employee_id, {
        "event_type": event_type,
        "event_date": event_date,
        "requested_plan_tier_id": requested_plan_tier_id,
        "adjustment_mode": adjustment_mode,
    }, headers))


def approve_life_event(life_event_id, employee_id, approver_user_id="approver") -> dict:
    """Approve a life event under a different BenefitsAdmin X-User-ID, with a freshly
    observed expected_employee_version (PRD Sections 2.8-2.9, 3.6)."""
    headers = build_user_headers(approver_user_id, "BenefitsAdmin")
    ev = employee_version(employee_id)
    return get_success_data(_api.approve_life_event(
        life_event_id, {"expected_employee_version": ev}, headers))


# ─── Dependent setups ─────────────────────────────────

def setup_pending_dependent(relationship="CHILD") -> dict:
    """Employee + one PENDING dependent. Returns {employee, dependent}."""
    emp = create_employee()
    dep = get_success_data(_api.create_dependent(emp["id"], {
        "relationship": relationship,
        "full_name": "Test Dependent",
        "date_of_birth": "2020-01-01",
    }, _ADMIN))
    return {"employee": emp, "dependent": dep}


def setup_verified_dependent_on_active_enrollment(coverage_level="EMPLOYEE_PLUS_CHILDREN",
                                                  monthly_premium_cents=90000) -> dict:
    """Eligible employee + ACTIVE MEDICAL enrollment + a VERIFIED CHILD dependent
    (verified by a DependentVerifier whose X-User-ID differs from the employee id).
    Returns {employee, tier, enrollment, dependent}."""
    advance_clock("2026-01-01T00:00:00Z")
    emp = create_employee()
    create_waiting_period(emp["id"], start_date="2026-01-01", end_date="2026-02-01")
    off = create_offering(benefit_type="MEDICAL", name="Gold PPO")
    tier = create_tier(off["id"], coverage_level=coverage_level,
                       monthly_premium_cents=monthly_premium_cents,
                       employer_contribution_pct=0.70)
    advance_clock("2026-02-01T00:00:00Z")
    enr = create_draft_enrollment(emp["id"], tier["id"], coverage_start_date="2026-02-01")
    enr = activate_enrollment(enr["id"], emp["id"])
    dep = get_success_data(_api.create_dependent(emp["id"], {
        "relationship": "CHILD", "full_name": "Kid Test", "date_of_birth": "2021-03-03",
    }, _ADMIN))
    verifier = build_user_headers("verifier_z", "DependentVerifier")
    dep = get_success_data(_api.verify_dependent(dep["id"], verifier))
    return {"employee": emp, "tier": tier, "enrollment": enr, "dependent": dep}


# ─── 1095-C setup ─────────────────────────────────────

def setup_lowest_cost_medical_for_employee(monthly_household_income_cents=100000,
                                           monthly_premium_cents=30000,
                                           employer_contribution_pct=0.70) -> dict:
    """Employee + a MEDICAL EMPLOYEE_ONLY tier flagged is_lowest_cost_self_only, ready for
    1095-C generation (PRD Section 3.10). Returns {employee, tier}."""
    emp = create_employee(monthly_household_income_cents=monthly_household_income_cents)
    off = create_offering(benefit_type="MEDICAL", name="Silver PPO")
    tier = create_tier(off["id"], coverage_level="EMPLOYEE_ONLY",
                       monthly_premium_cents=monthly_premium_cents,
                       employer_contribution_pct=employer_contribution_pct,
                       is_lowest_cost_self_only=True)
    return {"employee": emp, "tier": tier}


# ─── helpers ──────────────────────────────────────────

def _list_data(response):
    """Return (data_list, meta) from a paginated list response, lenient on status."""
    data = get_success_data(response)
    body = response.json()
    return data, body.get("meta", {})


def list_deduction_lines(employee_id, line_type=None):
    params = {"employee_id": employee_id}
    if line_type is not None:
        params["line_type"] = line_type
    data, meta = _list_data(_api.list_deduction_lines(_PAYROLL, params=params))
    return data, meta


def list_carrier_feed_records(enrollment_id=None, employee_id=None, transaction_set=None):
    params = {}
    if enrollment_id is not None:
        params["enrollment_id"] = enrollment_id
    if employee_id is not None:
        params["employee_id"] = employee_id
    if transaction_set is not None:
        params["transaction_set"] = transaction_set
    data, meta = _list_data(_api.list_carrier_feed_records(_ADMIN, params=params))
    return data, meta
