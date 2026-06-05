"""Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() (lenient validator) internally so setup failures surface as
clear "setup failed" errors rather than confusing assertion failures.

Ownership note: an Applicant's X-User-ID becomes the household's applicant_user_id.
Every ownership-gated call on a household subtree therefore threads the SAME user_id
that created the household, via make_applicant_headers(user_id).
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_household_payload,
    create_member_payload,
    create_application_payload,
    create_health_plan_payload,
    create_sep_request_payload,
    create_enrollment_payload,
)
from .test_users import make_applicant_headers, TEST_USERS


# ─── Tier 0: primitives ────────────────────────────────────────────────

def set_clock(iso: str):
    """Set the server clock (MarketplaceAdmin-only)."""
    return get_success_data(api_client.set_clock(iso, TEST_USERS["admin_headers"]))


def register_benchmark_plan(rating_area="RA01", coverage_year=2026, gross_premium_cents=50_000):
    """Register the single benchmark SILVER plan for an area/year. Returns the plan."""
    res = api_client.create_health_plan(
        create_health_plan_payload(
            rating_area=rating_area, coverage_year=coverage_year,
            metal_tier="SILVER", gross_premium_cents=gross_premium_cents,
            is_slcsp_benchmark=True),
        TEST_USERS["admin_headers"])
    return get_success_data(res)


def register_plan(rating_area="RA01", coverage_year=2026, metal_tier="GOLD",
                  gross_premium_cents=60_000, is_slcsp_benchmark=False):
    """Register a non-benchmark plan. Returns the plan."""
    res = api_client.create_health_plan(
        create_health_plan_payload(
            rating_area=rating_area, coverage_year=coverage_year,
            metal_tier=metal_tier, gross_premium_cents=gross_premium_cents,
            is_slcsp_benchmark=is_slcsp_benchmark),
        TEST_USERS["admin_headers"])
    return get_success_data(res)


def household_version(household_id, user_id):
    """Read the current Household.version (the value clients pass as expected_household_version)."""
    hh = get_success_data(api_client.get_household(household_id, make_applicant_headers(user_id)))
    return hh["version"]


# ─── Tier 1: Household construction ─────────────────────────────────────

def create_household(user_id, rating_area="RA01", coverage_year=2026):
    """Create a household owned by `user_id`. Returns the household."""
    res = api_client.create_household(
        create_household_payload(rating_area=rating_area, coverage_year=coverage_year),
        make_applicant_headers(user_id))
    return get_success_data(res)


def add_member(household_id, user_id, **member_overrides):
    """Add a member to a household. Returns the member."""
    res = api_client.create_member(
        household_id, create_member_payload(**member_overrides),
        make_applicant_headers(user_id))
    return get_success_data(res)


def create_household_with_primary(user_id, rating_area="RA01", coverage_year=2026,
                                  income_cents=3_000_000, full_name="Primary P"):
    """Household + one PRIMARY FILER member. Returns (household, member)."""
    hh = create_household(user_id, rating_area=rating_area, coverage_year=coverage_year)
    mem = add_member(hh["id"], user_id, full_name=full_name, relationship="PRIMARY",
                     tax_filing_status="FILER", annual_income_cents=income_cents,
                     applies_for_coverage=True)
    return hh, mem


# ─── Tier 2: Application progression ────────────────────────────────────

def create_application(household_id, user_id, enrollment_window="OEP"):
    """Create a DRAFT application. Returns the application."""
    res = api_client.create_application(
        create_application_payload(household_id, enrollment_window=enrollment_window),
        make_applicant_headers(user_id))
    return get_success_data(res)


def submit_application(application_id, household_id, user_id):
    """Submit a DRAFT application carrying the current household version. Returns the application."""
    v = household_version(household_id, user_id)
    res = api_client.submit_application(
        application_id, {"expected_household_version": v}, make_applicant_headers(user_id))
    return get_success_data(res)


def determine_application(application_id):
    """Run the eligibility determination (MarketplaceAdmin). Returns the determination."""
    res = api_client.determine_application(application_id, TEST_USERS["admin_headers"])
    return get_success_data(res)


def setup_determined_application(user_id, rating_area="RA01", coverage_year=2026,
                                 income_cents=3_000_000, enrollment_window="OEP",
                                 benchmark_gross=50_000, clock="2026-01-10T00:00:00Z"):
    """Full chain to a DETERMINED application for an OEP household.

    clock set -> benchmark plan -> household -> primary member -> application ->
    submit -> determine.
    Returns dict(household, member, application, determination, plan).
    """
    set_clock(clock)
    plan = register_benchmark_plan(rating_area=rating_area, coverage_year=coverage_year,
                                   gross_premium_cents=benchmark_gross)
    hh, mem = create_household_with_primary(
        user_id, rating_area=rating_area, coverage_year=coverage_year, income_cents=income_cents)
    app = create_application(hh["id"], user_id, enrollment_window=enrollment_window)
    submit_application(app["id"], hh["id"], user_id)
    det = determine_application(app["id"])
    return {"household": hh, "member": mem, "application": app,
            "determination": det, "plan": plan}


def setup_submitted_application(user_id, rating_area="RA01", coverage_year=2026,
                                income_cents=3_000_000, enrollment_window="OEP",
                                benchmark_gross=50_000, clock="2026-01-10T00:00:00Z",
                                register_plan_first=True):
    """Chain to a SUBMITTED (not determined) application.
    Returns dict(household, member, application, plan).
    """
    set_clock(clock)
    plan = None
    if register_plan_first:
        plan = register_benchmark_plan(rating_area=rating_area, coverage_year=coverage_year,
                                       gross_premium_cents=benchmark_gross)
    hh, mem = create_household_with_primary(
        user_id, rating_area=rating_area, coverage_year=coverage_year, income_cents=income_cents)
    app = create_application(hh["id"], user_id, enrollment_window=enrollment_window)
    submit_application(app["id"], hh["id"], user_id)
    return {"household": hh, "member": mem, "application": app, "plan": plan}


# ─── Tier 3: SEP chains ─────────────────────────────────────────────────

def create_sep_request(application_id, user_id, qualifying_event_type="BIRTH",
                       event_date="2026-06-16"):
    """File a PENDING SepRequest. Returns the sep request."""
    res = api_client.create_sep_request(
        create_sep_request_payload(application_id,
                                   qualifying_event_type=qualifying_event_type,
                                   event_date=event_date),
        make_applicant_headers(user_id))
    return get_success_data(res)


def approve_sep_request(sep_id):
    res = api_client.approve_sep_request(sep_id, TEST_USERS["admin_headers"])
    return get_success_data(res)


def setup_determined_sep_application(user_id, qualifying_event_type="BIRTH",
                                     event_date="2026-06-16",
                                     event_clock="2026-06-18T00:00:00Z",
                                     submit_clock="2026-06-20T00:00:00Z",
                                     rating_area="RA01", coverage_year=2026,
                                     income_cents=3_000_000, benchmark_gross=50_000):
    """Full chain to a DETERMINED SEP application with an APPROVED SepRequest.

    clock(event) -> benchmark plan -> household -> primary -> SEP application ->
    sep request -> approve -> clock(submit) -> submit -> determine.
    Returns dict(household, member, application, sep_request, determination, plan).
    """
    set_clock(event_clock)
    plan = register_benchmark_plan(rating_area=rating_area, coverage_year=coverage_year,
                                   gross_premium_cents=benchmark_gross)
    hh, mem = create_household_with_primary(
        user_id, rating_area=rating_area, coverage_year=coverage_year, income_cents=income_cents)
    app = create_application(hh["id"], user_id, enrollment_window="SEP")
    sep = create_sep_request(app["id"], user_id,
                             qualifying_event_type=qualifying_event_type, event_date=event_date)
    approve_sep_request(sep["id"])
    set_clock(submit_clock)
    submit_application(app["id"], hh["id"], user_id)
    det = determine_application(app["id"])
    return {"household": hh, "member": mem, "application": app,
            "sep_request": sep, "determination": det, "plan": plan}


# ─── Tier 4: Enrollment chains ──────────────────────────────────────────

def create_enrollment(application_id, household_id, plan_id, user_id,
                      elected_aptc_monthly_cents=0):
    """Create an enrollment carrying the current household version. Returns the enrollment."""
    v = household_version(household_id, user_id)
    res = api_client.create_enrollment(
        create_enrollment_payload(application_id, plan_id, v,
                                  elected_aptc_monthly_cents=elected_aptc_monthly_cents),
        make_applicant_headers(user_id))
    return get_success_data(res)


def setup_enrollment(user_id, rating_area="RA01", coverage_year=2026, income_cents=3_000_000,
                     elected_aptc_monthly_cents=45_000, benchmark_gross=50_000,
                     clock="2026-01-10T00:00:00Z"):
    """Full chain to a created Enrollment (PENDING_EFFECTUATION / AWAITING_BINDER).
    Returns dict(household, member, application, determination, plan, enrollment).
    """
    ctx = setup_determined_application(
        user_id, rating_area=rating_area, coverage_year=coverage_year,
        income_cents=income_cents, enrollment_window="OEP",
        benchmark_gross=benchmark_gross, clock=clock)
    enr = create_enrollment(ctx["application"]["id"], ctx["household"]["id"],
                            ctx["plan"]["id"], user_id,
                            elected_aptc_monthly_cents=elected_aptc_monthly_cents)
    ctx["enrollment"] = enr
    return ctx


def setup_paid_enrollment(user_id, **kwargs):
    """Enrollment with the binder PAID (lifecycle still PENDING_EFFECTUATION)."""
    ctx = setup_enrollment(user_id, **kwargs)
    enr = get_success_data(
        api_client.pay_binder(ctx["enrollment"]["id"], make_applicant_headers(user_id)))
    ctx["enrollment"] = enr
    return ctx


def setup_active_enrollment(user_id, **kwargs):
    """Enrollment paid + effectuated (lifecycle ACTIVE, payment PAID)."""
    ctx = setup_paid_enrollment(user_id, **kwargs)
    enr = get_success_data(
        api_client.effectuate(ctx["enrollment"]["id"], TEST_USERS["admin_headers"]))
    ctx["enrollment"] = enr
    return ctx


def setup_reconciliation(user_id, actual_annual_magi_cents, months_enrolled=12,
                         income_cents=3_000_000, elected_aptc_monthly_cents=45_000,
                         benchmark_gross=50_000, clock="2026-01-10T00:00:00Z"):
    """Full chain through a ReconciliationRecord.
    Returns dict(... , enrollment, reconciliation).
    """
    ctx = setup_enrollment(user_id, income_cents=income_cents,
                           elected_aptc_monthly_cents=elected_aptc_monthly_cents,
                           benchmark_gross=benchmark_gross, clock=clock)
    res = api_client.create_reconciliation(
        {"enrollment_id": ctx["enrollment"]["id"],
         "actual_annual_magi_cents": actual_annual_magi_cents,
         "months_enrolled": months_enrolled},
        TEST_USERS["admin_headers"])
    ctx["reconciliation"] = get_success_data(res)
    return ctx
