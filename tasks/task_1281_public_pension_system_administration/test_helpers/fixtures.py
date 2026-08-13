"""Composite setup helpers for multi-step test prerequisites.

The harness restarts the server before every test, so every fixture builds
its preconditions from scratch using only PRD-declared endpoints. Uses
get_success_data() so setup failures surface as clear "Setup step failed"
errors rather than confusing assertion failures.

Identity threading: entity-backed roles always use the per-instance builders
(make_member_headers / make_employer_clerk_headers /
make_survivor_claimant_headers) with the real entity id.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import TEST_DEFAULTS, THRESHOLDS
from .factories import (
    create_beneficiary_payload,
    create_contribution_line_payload,
    create_contribution_report_payload,
    create_disability_application_payload,
    create_employer_payload,
    create_member_payload,
    create_pension_fund_payload,
    create_retirement_application_payload,
    create_service_purchase_payload,
)
from .test_users import (
    TEST_USERS,
    make_approver_headers,
    make_employer_clerk_headers,
    make_medical_reviewer_headers,
    make_member_headers,
    make_survivor_claimant_headers,
)

ADMIN = TEST_USERS["fund_admin_headers"]
ANALYST = TEST_USERS["analyst_headers"]  # X-User-ID "analyst-1"
APPROVER = TEST_USERS["approver_headers"]  # X-User-ID "approver-1"
REVIEWER = TEST_USERS["medical_reviewer_headers"]  # X-User-ID "reviewer-1"


# ─── Tier 0: clock / fund / employer / member primitives ────────────────────

def set_clock(to_iso8601: str = THRESHOLDS["DEFAULT_CLOCK_UTC"]):
    """Set the logical clock (FundAdmin). Defaults to the fixed startup instant."""
    return get_success_data(
        api_client.set_clock({"to_iso8601": to_iso8601}, ADMIN))


def create_fund(cola_rate_pct: float = TEST_DEFAULTS["COLA_RATE_PCT"],
                earnings_limit_annual_cents: int =
                TEST_DEFAULTS["EARNINGS_LIMIT_ANNUAL_CENTS"],
                fund_name: str = "State Retirement"):
    """Create a pension fund configuration."""
    return get_success_data(api_client.create_pension_fund(
        create_pension_fund_payload(
            fund_name=fund_name,
            cola_rate_pct=cola_rate_pct,
            earnings_limit_annual_cents=earnings_limit_annual_cents),
        ADMIN))


def create_employer(name: str = "City Hall", employer_code: str = "CH"):
    """Register an employer reporting unit."""
    return get_success_data(api_client.create_employer(
        create_employer_payload(name=name, employer_code=employer_code), ADMIN))


def setup_fund_and_employer(set_clock_to: str = THRESHOLDS["DEFAULT_CLOCK_UTC"],
                            **fund_overrides):
    """Clock (pinned) + fund + employer. Returns (fund, employer)."""
    if set_clock_to is not None:
        set_clock(set_clock_to)
    fund = create_fund(**fund_overrides)
    employer = create_employer()
    return fund, employer


def create_member(employer_id: str, full_name: str = "Member One",
                  date_of_birth: str = "1966-01-01",
                  hire_date: str = "2016-01-01", **extra):
    """Enroll a member (MemberServicesAnalyst)."""
    return get_success_data(api_client.create_member(
        create_member_payload(employer_id, full_name=full_name,
                              date_of_birth=date_of_birth,
                              hire_date=hire_date, **extra),
        ANALYST))


# ─── Tier 1: contribution reporting pipeline ────────────────────────────────

def create_report(employer_id: str, period_start: str, period_end: str,
                  declared_total_cents: int):
    """Create a DRAFT contribution report as the employer's own clerk."""
    return get_success_data(api_client.create_contribution_report(
        employer_id,
        create_contribution_report_payload(
            period_start=period_start, period_end=period_end,
            declared_total_cents=declared_total_cents),
        make_employer_clerk_headers(employer_id)))


def add_line(report_id: str, employer_id: str, member_id: str,
             fiscal_year: int, period_salary_cents: int,
             contribution_amount_cents=None, service_months=None):
    """Add a PENDING contribution line to a DRAFT report."""
    payload = create_contribution_line_payload(
        member_id, fiscal_year=fiscal_year,
        period_salary_cents=period_salary_cents,
        contribution_amount_cents=(contribution_amount_cents
                                   if contribution_amount_cents is not None
                                   else round(period_salary_cents * 0.08)))
    if service_months is not None:
        payload["service_months"] = service_months
    return get_success_data(api_client.create_contribution_line(
        report_id, payload, make_employer_clerk_headers(employer_id)))


def submit_report(report_id: str, employer_id: str):
    """Submit a DRAFT report (EmployerClerk of the owning employer)."""
    return get_success_data(api_client.submit_contribution_report(
        report_id, make_employer_clerk_headers(employer_id)))


def review_line(report_id: str, line_id: str, decision: str,
                review_note=None):
    """Analyst review of a line: decision ACCEPT or REJECT."""
    payload = {"decision": decision}
    if review_note is not None:
        payload["review_note"] = review_note
    return get_success_data(api_client.review_contribution_line(
        report_id, line_id, payload, ANALYST))


def finalize_report(report_id: str):
    """Analyst finalize of a SUBMITTED report."""
    return get_success_data(
        api_client.finalize_contribution_report(report_id, ANALYST))


def reconcile_member_history(employer_id: str, line_specs: list,
                             period_start: str = None,
                             period_end: str = None):
    """Full reporting pipeline over one report: create (declared total derived
    from the lines), add lines, submit, ACCEPT every line, finalize to
    RECONCILED.

    line_specs: list of dicts with keys member_id, fiscal_year, salary_cents;
    optional keys contribution_cents, service_months.
    Returns {"report": ..., "lines": [...]}.
    """
    years = [s["fiscal_year"] for s in line_specs]
    if period_start is None:
        period_start = f"{min(years)}-01-01"
    if period_end is None:
        period_end = f"{max(years) + 1}-01-01"
    declared = sum(
        s.get("contribution_cents", round(s["salary_cents"] * 0.08))
        for s in line_specs)
    report = create_report(employer_id, period_start, period_end, declared)
    lines = []
    for spec in line_specs:
        lines.append(add_line(
            report["id"], employer_id, spec["member_id"], spec["fiscal_year"],
            spec["salary_cents"], spec.get("contribution_cents"),
            spec.get("service_months")))
    submit_report(report["id"], employer_id)
    for line in lines:
        review_line(report["id"], line["id"], "ACCEPT")
    report = finalize_report(report["id"])
    return {"report": report, "lines": lines}


# ─── Tier 2: member with credited service ───────────────────────────────────

def six_year_line_specs(member_id: str, first_fy: int =
                        TEST_DEFAULTS["SIX_YEAR_FIRST_FY"],
                        salaries: list =
                        TEST_DEFAULTS["SIX_YEAR_SALARIES"]) -> list:
    """FY2018-2023 rising salaries: 6.0 service years, FAS 5,500,000."""
    return [{"member_id": member_id, "fiscal_year": first_fy + i,
             "salary_cents": s} for i, s in enumerate(salaries)]


def five_year_line_specs(member_id: str, first_fy: int = 2019,
                         salary_cents: int = 5_000_000) -> list:
    """FY2019-2023 flat salaries: 5.0 service years, FAS 5,000,000."""
    return [{"member_id": member_id, "fiscal_year": first_fy + i,
             "salary_cents": salary_cents} for i in range(5)]


def setup_vested_member(set_clock_to: str = THRESHOLDS["DEFAULT_CLOCK_UTC"],
                        date_of_birth: str = "1966-01-01",
                        hire_date: str = "2016-01-01",
                        full_name: str = "Vested Vera",
                        line_specs_fn=six_year_line_specs):
    """Fund + employer + member with a fully RECONCILED contribution history.

    Default: 6 ACCEPTED lines FY2018-2023 -> total_service_years 6.0,
    current_annual_salary_cents 6,000,000, FAS 5,500,000.
    Returns dict(fund, employer, member, report, lines).
    """
    fund, employer = setup_fund_and_employer(set_clock_to=set_clock_to)
    member = create_member(employer["id"], full_name=full_name,
                           date_of_birth=date_of_birth, hire_date=hire_date)
    ctx = reconcile_member_history(employer["id"], line_specs_fn(member["id"]))
    return {"fund": fund, "employer": employer, "member": member,
            "report": ctx["report"], "lines": ctx["lines"]}


# ─── Tier 3: retirement application lifecycle ───────────────────────────────

def create_retirement_app(member_id: str, option_election: str = "SINGLE_LIFE",
                          beneficiary_name=None, beneficiary_date_of_birth=None,
                          filed_by_analyst: bool = False):
    """Create a DRAFT retirement application (member self-service or analyst)."""
    payload = create_retirement_application_payload(
        option_election=option_election)
    if beneficiary_name is not None:
        payload["beneficiary_name"] = beneficiary_name
    if beneficiary_date_of_birth is not None:
        payload["beneficiary_date_of_birth"] = beneficiary_date_of_birth
    headers = ANALYST if filed_by_analyst else make_member_headers(member_id)
    return get_success_data(
        api_client.create_retirement_application(member_id, payload, headers))


def submit_retirement_app(application_id: str, member_id: str):
    """Submit a DRAFT application as the member."""
    return get_success_data(api_client.submit_retirement_application(
        application_id, make_member_headers(member_id)))


def review_retirement_app(application_id: str, outcome: str = "REVIEW_OK",
                          analyst_user_id: str = "analyst-1",
                          review_note=None):
    """Analyst review; REVIEW_OK records analyst_user_id as the reviewer."""
    from .test_users import make_analyst_headers
    payload = {"outcome": outcome}
    if review_note is not None:
        payload["review_note"] = review_note
    return get_success_data(api_client.review_retirement_application(
        application_id, payload, make_analyst_headers(analyst_user_id)))


def current_application_version(application_id: str) -> int:
    return get_success_data(
        api_client.get_retirement_application(application_id, ANALYST))["version"]


def approve_retirement_app(application_id: str, expected_version: int,
                           approver_user_id: str = "approver-1"):
    """BenefitApprover approval against the observed application version."""
    return get_success_data(api_client.approve_retirement_application(
        application_id, {"expected_application_version": expected_version},
        make_approver_headers(approver_user_id)))


def setup_approved_retirement(set_clock_to: str =
                              THRESHOLDS["DEFAULT_CLOCK_UTC"],
                              option_election: str = "SINGLE_LIFE",
                              beneficiary_name=None,
                              beneficiary_date_of_birth=None,
                              date_of_birth: str = "1966-01-01",
                              hire_date: str = "2016-01-01",
                              full_name: str = "Retiree Ray",
                              line_specs_fn=six_year_line_specs,
                              analyst_user_id: str = "analyst-1",
                              approver_user_id: str = "approver-1"):
    """Full pipeline through APPROVED: vested member -> create -> submit ->
    REVIEW_OK -> approve. Returns dict plus "application" and "benefit"
    (the single ACTIVE benefit created by the approval)."""
    ctx = setup_vested_member(set_clock_to=set_clock_to,
                              date_of_birth=date_of_birth, hire_date=hire_date,
                              full_name=full_name, line_specs_fn=line_specs_fn)
    member_id = ctx["member"]["id"]
    app = create_retirement_app(member_id, option_election, beneficiary_name,
                                beneficiary_date_of_birth)
    submit_retirement_app(app["id"], member_id)
    review_retirement_app(app["id"], "REVIEW_OK", analyst_user_id)
    version = current_application_version(app["id"])
    approved = approve_retirement_app(app["id"], version, approver_user_id)
    # fetch the created benefit (exactly one after a single approval)
    from prd_bench_local_runner.testing import validate_paginated
    benefits, _meta = validate_paginated(
        api_client.list_member_benefits(member_id, ANALYST))
    assert len(benefits) == 1, f"expected exactly one benefit, got {len(benefits)}"
    ctx["application"] = approved
    ctx["benefit"] = benefits[0]
    return ctx


# ─── Tier 4: service purchase lifecycle ─────────────────────────────────────

def create_purchase(member_id: str, purchase_type: str = "MILITARY",
                    period_start: str = "2005-01-01",
                    period_end: str = "2006-12-31", years_purchased: float = 2.0,
                    filed_by_analyst: bool = False):
    """Create a REQUESTED service purchase (member self-service or analyst)."""
    headers = ANALYST if filed_by_analyst else make_member_headers(member_id)
    return get_success_data(api_client.create_service_purchase(
        member_id,
        create_service_purchase_payload(
            purchase_type=purchase_type,
            service_period_start=period_start,
            service_period_end=period_end,
            years_purchased=years_purchased),
        headers))


def quote_purchase(purchase_id: str):
    """Analyst runs the cost quote: REQUESTED -> QUOTED."""
    return get_success_data(
        api_client.quote_service_purchase(purchase_id, ANALYST))


def accept_purchase(purchase_id: str, member_id: str, installment_count: int = 12,
                    by_analyst: bool = False):
    """Accept a QUOTED purchase; opens the installment plan (PLAN_ACTIVE)."""
    headers = ANALYST if by_analyst else make_member_headers(member_id)
    return get_success_data(api_client.accept_service_purchase(
        purchase_id, {"installment_count": installment_count}, headers))


def list_payments_sorted(purchase_id: str):
    """All installment payments of a purchase, ordered by sequence_number."""
    from prd_bench_local_runner.testing import validate_paginated
    data, _meta = validate_paginated(
        api_client.list_purchase_payments(purchase_id, ANALYST,
                                          params={"limit": 100}))
    return sorted(data, key=lambda p: p["sequence_number"])


def setup_plan_active_purchase(member_id: str, years_purchased: float = 2.0,
                               installment_count: int = 12,
                               purchase_type: str = "MILITARY",
                               period_start: str = "2005-01-01",
                               period_end: str = "2006-12-31"):
    """Create -> quote -> accept. Returns dict(purchase, payments)."""
    purchase = create_purchase(member_id, purchase_type, period_start,
                               period_end, years_purchased)
    purchase = quote_purchase(purchase["id"])
    purchase = accept_purchase(purchase["id"], member_id, installment_count)
    return {"purchase": purchase,
            "payments": list_payments_sorted(purchase["id"])}


def pay_installment(purchase_id: str, payment_id: str,
                    expected_purchase_version: int, member_id: str = None,
                    by_analyst: bool = False):
    """Apply one PENDING installment (OCC-guarded). Returns updated purchase."""
    headers = ANALYST if (by_analyst or member_id is None) \
        else make_member_headers(member_id)
    return get_success_data(api_client.apply_payment(
        purchase_id,
        {"payment_id": payment_id,
         "expected_purchase_version": expected_purchase_version},
        headers))


def get_purchase(purchase_id: str):
    return get_success_data(api_client.get_service_purchase(purchase_id, ANALYST))


# ─── Tier 5: disability lifecycle ───────────────────────────────────────────

def create_disability_app(member_id: str, disability_type: str = "DUTY",
                          description=None, filed_by_analyst: bool = True,
                          analyst_user_id: str = None):
    """File a disability application (enters UNDER_MEDICAL_REVIEW at once)."""
    payload = create_disability_application_payload(
        disability_type=disability_type)
    if description is not None:
        payload["description"] = description
    if filed_by_analyst:
        from .test_users import make_analyst_headers
        headers = (make_analyst_headers(analyst_user_id)
                   if analyst_user_id else ANALYST)
    else:
        headers = make_member_headers(member_id)
    return get_success_data(
        api_client.create_disability_application(member_id, payload, headers))


def decide_disability_app(application_id: str, outcome: str,
                          reviewer_user_id: str = "reviewer-1",
                          review_note=None):
    """MedicalReviewer decision: APPROVE or DENY."""
    payload = {"outcome": outcome}
    if review_note is not None:
        payload["review_note"] = review_note
    return get_success_data(api_client.decide_disability_application(
        application_id, payload,
        make_medical_reviewer_headers(reviewer_user_id)))


def appeal_disability_app(application_id: str, member_id: str):
    """Member appeals a DENIED decision."""
    return get_success_data(api_client.appeal_disability_application(
        application_id, make_member_headers(member_id)))


# ─── Tier 6: beneficiary / survivor lifecycle ───────────────────────────────

def create_beneficiary(member_id: str, full_name: str = "Spouse Sam",
                       relationship: str = "spouse",
                       date_of_birth: str = "1968-01-01"):
    """Designate a beneficiary (member self-service)."""
    return get_success_data(api_client.create_beneficiary(
        member_id,
        create_beneficiary_payload(full_name=full_name,
                                   relationship=relationship,
                                   date_of_birth=date_of_birth),
        make_member_headers(member_id)))


def record_death(member_id: str, deceased_at: str):
    """Record the member's death (fires the death cascade)."""
    return get_success_data(api_client.update_member(
        member_id, {"deceased_at": deceased_at}, ANALYST))


def setup_retiree_with_designation(option_election: str = "JOINT_100",
                                   beneficiary_dob: str = "1968-01-01",
                                   set_clock_to: str =
                                   THRESHOLDS["DEFAULT_CLOCK_UTC"],
                                   date_of_birth: str = "1966-01-01",
                                   hire_date: str = "2016-01-01",
                                   line_specs_fn=six_year_line_specs):
    """Approved retirement (option election as given) plus a live DESIGNATED
    Beneficiary designation created while the member is alive.
    Returns dict with fund/employer/member/application/benefit/beneficiary."""
    ctx = setup_approved_retirement(
        set_clock_to=set_clock_to,
        option_election=option_election,
        beneficiary_name="Spouse Sam",
        beneficiary_date_of_birth=beneficiary_dob,
        date_of_birth=date_of_birth, hire_date=hire_date,
        line_specs_fn=line_specs_fn)
    designation = create_beneficiary(ctx["member"]["id"],
                                     date_of_birth=beneficiary_dob)
    ctx["beneficiary"] = designation
    return ctx


def file_survivor_claim(beneficiary_id: str, by_analyst: bool = False):
    """SurvivorClaimant files on their own designation (or an analyst files)."""
    headers = ANALYST if by_analyst else \
        make_survivor_claimant_headers(beneficiary_id)
    return api_client.file_claim(beneficiary_id, headers)


def adjudicate_survivor_claim(beneficiary_id: str, outcome: str,
                              approver_user_id: str = "approver-1"):
    """BenefitApprover adjudicates a CLAIM_FILED designation."""
    return get_success_data(api_client.adjudicate_claim(
        beneficiary_id, {"outcome": outcome},
        make_approver_headers(approver_user_id)))
