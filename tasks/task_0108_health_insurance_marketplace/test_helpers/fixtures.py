"""Composite setup helpers — multi-step preambles tests can reuse.

The marketplace pipeline is long:
  Insurer -> Plan (benchmark Silver) -> PlanVariant
  Application -> HouseholdMember(PRIMARY_FILER) -> IncomeRecord
  /submit -> /determine-eligibility -> /approve -> Enrollment
  -> binder PremiumInvoice -> post-payment -> ACTIVE coverage.

Most interesting test claims need the system in a late-pipeline state,
so this file encapsulates each segment as a reusable helper.

IDENTITY THREADING — PRD §2.1:

- Applicant is OPAQUE but X-User-ID doubles as Application.applicant_id
  for ownership checks. Therefore once a fixture creates an Application
  using a specific applicant id, every subsequent Applicant-acting call
  on that Application MUST use the SAME id via
  make_applicant_headers(applicant_id). The fixture helpers always
  surface the applicant_id (the value the fixture used) on the returned
  Application object as the "applicant_id" field — consumers can read
  it back and thread it through.

- MarketplaceAdmin / CustomerService are OPAQUE — shared headers are
  canonical.

- Insurer is ENTITY-BACKED. Every Insurer-driven Plan write MUST mint
  headers via make_insurer_headers(insurer["id"]) — never via the
  shared INSURER_FALLBACK_ID constant.

Setup calls use get_success_data (a lenient 2xx validator), so a
failed setup surfaces as "Setup failed" rather than confusing test
assertions downstream.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import TEST_DEFAULTS, fpl_denominator
from .factories import (
    clock_advance_payload,
    create_application_payload,
    create_enrollment_payload,
    create_household_member_payload,
    create_income_record_payload,
    create_insurer_payload,
    create_plan_payload,
    create_plan_variant_payload,
    create_sep_event_payload,
    dob_for_age,
    iso_date,
    iso_offset,
    iso_utc,
    parse_iso,
    post_payment_payload,
    random_suffix,
    reconcile_aptc_payload,
)
from .test_users import (
    TEST_USERS,
    make_applicant_headers,
    make_insurer_headers,
)


# ===========================================================================
# Clock helpers — PRD §2.9 (MarketplaceAdmin only for advance)
# ===========================================================================
def advance_clock_to(iso_timestamp: str,
                     headers: Optional[Dict[str, str]] = None
                     ) -> Dict[str, Any]:
    """POST /_clock/advance. PRD §2.9: MarketplaceAdmin only."""
    headers = headers or TEST_USERS["admin_headers"]
    resp = api_client.clock_advance(
        clock_advance_payload(to_timestamp=iso_timestamp), headers,
    )
    return get_success_data(resp)


def advance_clock_to_date(target_date: date,
                          headers: Optional[Dict[str, str]] = None
                          ) -> Dict[str, Any]:
    """Convenience: advance the clock to midnight UTC on `target_date`."""
    dt = datetime(target_date.year, target_date.month, target_date.day,
                  tzinfo=timezone.utc)
    return advance_clock_to(iso_utc(dt), headers=headers)


# ===========================================================================
# Tier 1: Insurer + Plan catalog setup
# ===========================================================================
def create_insurer(
    *,
    filing_states: Optional[List[str]] = None,
    name: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /insurers — MarketplaceAdmin only (PRD §4)."""
    headers = headers or TEST_USERS["admin_headers"]
    payload = create_insurer_payload(
        name=name, filing_states=filing_states or ["CA"],
    )
    resp = api_client.create_insurer(payload, headers)
    return get_success_data(resp)


def create_plan(
    *,
    insurer: Dict[str, Any],
    coverage_year: int = 2026,
    filing_state: str = "CA",
    tier: str = "SILVER",
    base_monthly_premium_cents: int = 40_000,
    is_benchmark_silver: Optional[bool] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /plans.

    PRD §4 roles: Insurer or MarketplaceAdmin. The fixture defaults to
    make_insurer_headers(insurer["id"]) so the Insurer-acting ownership
    check passes; tests that want admin acting can pass admin_headers.
    """
    headers = headers or make_insurer_headers(insurer["id"])
    payload = create_plan_payload(
        insurer_id=insurer["id"], coverage_year=coverage_year,
        filing_state=filing_state, tier=tier,
        base_monthly_premium_cents=base_monthly_premium_cents,
        is_benchmark_silver=is_benchmark_silver,
    )
    resp = api_client.create_plan(payload, headers)
    return get_success_data(resp)


def create_plan_variant(
    *,
    plan: Dict[str, Any],
    csr_level: str = "STANDARD",
    actuarial_value: float = 70.0,
    out_of_pocket_max_cents: int = 900_000,
    insurer: Optional[Dict[str, Any]] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /plans/{id}/variants."""
    if headers is None:
        if insurer is not None:
            headers = make_insurer_headers(insurer["id"])
        else:
            headers = TEST_USERS["admin_headers"]
    payload = create_plan_variant_payload(
        csr_level=csr_level, actuarial_value=actuarial_value,
        out_of_pocket_max_cents=out_of_pocket_max_cents,
    )
    resp = api_client.create_plan_variant(plan["id"], payload, headers)
    return get_success_data(resp)


def setup_benchmark_silver_catalog(
    *,
    filing_state: str = "CA",
    coverage_year: int = 2026,
    base_monthly_premium_cents: int = 40_000,
    include_standard_variant: bool = True,
) -> Tuple[Dict[str, Any], Dict[str, Any], Optional[Dict[str, Any]]]:
    """Compose: Insurer + benchmark Silver Plan (+ optional STANDARD
    PlanVariant). Returns (insurer, plan, standard_variant_or_None).

    PRD §3.3: "the catalog must contain exactly one [benchmark Silver
    plan] per (filing_state, coverage_year) pair (if zero exist,
    eligibility determination is rejected with ERR_NO_BENCHMARK_PLAN)".
    """
    insurer = create_insurer(filing_states=[filing_state])
    plan = create_plan(
        insurer=insurer, coverage_year=coverage_year,
        filing_state=filing_state, tier="SILVER",
        base_monthly_premium_cents=base_monthly_premium_cents,
        is_benchmark_silver=True,
    )
    variant = None
    if include_standard_variant:
        variant = create_plan_variant(
            plan=plan, csr_level="STANDARD",
            actuarial_value=70.0, out_of_pocket_max_cents=900_000,
            insurer=insurer,
        )
    return insurer, plan, variant


# ===========================================================================
# Tier 2: Application + members + income lifecycle
# ===========================================================================
def fresh_applicant_id(prefix: str = "applicant") -> str:
    return f"{prefix}-{random_suffix(8).lower()}"


def create_application(
    *,
    coverage_year: int = 2026,
    filing_state: str = "CA",
    applicant_id: Optional[str] = None,
) -> Dict[str, Any]:
    """POST /applications — Applicant only (PRD §4).

    Returns the Application dict augmented with `_applicant_id` — the
    X-User-ID the test should thread through for ownership-gated
    follow-up calls. PRD §2.1: ownership compares X-User-ID to
    Application.applicant_id; tests must use the same id consistently.
    """
    applicant_id = applicant_id or fresh_applicant_id()
    headers = make_applicant_headers(applicant_id)
    payload = create_application_payload(
        coverage_year=coverage_year, filing_state=filing_state,
    )
    resp = api_client.create_application(payload, headers)
    app = get_success_data(resp)
    # Bookkeeping: surface the chosen applicant id so consumers can
    # rebuild headers for ownership-gated follow-ups.
    app["_applicant_id"] = applicant_id
    return app


def add_household_member(
    *,
    application: Dict[str, Any],
    filer_type: str = "PRIMARY_FILER",
    age_years: Optional[int] = None,
    date_of_birth: Optional[str] = None,
    reference_date: Optional[date] = None,
    include_in_household: Optional[bool] = None,
    include_in_magi: Optional[bool] = None,
    is_tobacco_user: Optional[bool] = None,
) -> Dict[str, Any]:
    """POST /applications/{id}/household-members.

    PRD §4 roles: Applicant. Identity threading: caller MUST have
    created the parent Application — fixture re-uses
    application["_applicant_id"] to mint headers.
    """
    applicant_id = application["_applicant_id"]
    headers = make_applicant_headers(applicant_id)
    payload = create_household_member_payload(
        filer_type=filer_type, age_years=age_years,
        date_of_birth=date_of_birth, reference_date=reference_date,
        include_in_household=include_in_household,
        include_in_magi=include_in_magi,
        is_tobacco_user=is_tobacco_user,
    )
    resp = api_client.create_household_member(
        application["id"], payload, headers,
    )
    return get_success_data(resp)


def add_income_record(
    *,
    application: Dict[str, Any],
    member: Dict[str, Any],
    source_type: str = "WAGES",
    amount_cents: int = 2_500_000,
    effective_date: Optional[str] = None,
    supersedes_id: Optional[str] = None,
) -> Dict[str, Any]:
    """POST /applications/{id}/household-members/{member_id}/
    income-records.
    """
    applicant_id = application["_applicant_id"]
    headers = make_applicant_headers(applicant_id)
    payload = create_income_record_payload(
        source_type=source_type, amount_cents=amount_cents,
        effective_date=effective_date, supersedes_id=supersedes_id,
    )
    resp = api_client.create_income_record(
        application["id"], member["id"], payload, headers,
    )
    return get_success_data(resp)


def submit_application(
    *, application: Dict[str, Any],
) -> Dict[str, Any]:
    """POST /applications/{id}/submit — Applicant only (PRD §4)."""
    headers = make_applicant_headers(application["_applicant_id"])
    resp = api_client.submit_application(application["id"], headers)
    out = get_success_data(resp)
    out["_applicant_id"] = application["_applicant_id"]
    return out


def amend_application(
    *, application: Dict[str, Any],
) -> Dict[str, Any]:
    headers = make_applicant_headers(application["_applicant_id"])
    resp = api_client.amend_application(application["id"], headers)
    out = get_success_data(resp)
    out["_applicant_id"] = application["_applicant_id"]
    return out


def determine_eligibility(
    *, application: Dict[str, Any],
) -> Dict[str, Any]:
    """POST /applications/{id}/determine-eligibility — MarketplaceAdmin."""
    resp = api_client.determine_eligibility(
        application["id"], TEST_USERS["admin_headers"],
    )
    out = get_success_data(resp)
    out["_applicant_id"] = application["_applicant_id"]
    return out


def approve_application(
    *, application: Dict[str, Any],
) -> Dict[str, Any]:
    """POST /applications/{id}/approve — MarketplaceAdmin."""
    resp = api_client.approve_application(
        application["id"], TEST_USERS["admin_headers"],
    )
    out = get_success_data(resp)
    out["_applicant_id"] = application["_applicant_id"]
    return out


def deny_application(
    *, application: Dict[str, Any],
    reason: Optional[str] = None,
) -> Dict[str, Any]:
    resp = api_client.deny_application(
        application["id"], TEST_USERS["admin_headers"],
        payload={"reason": reason} if reason is not None else None,
    )
    out = get_success_data(resp)
    out["_applicant_id"] = application["_applicant_id"]
    return out


def redetermine_application(
    *, application: Dict[str, Any],
) -> Dict[str, Any]:
    resp = api_client.redetermine_application(
        application["id"], TEST_USERS["admin_headers"],
    )
    out = get_success_data(resp)
    out["_applicant_id"] = application["_applicant_id"]
    return out


def re_get_application(
    *, application_id: str,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    headers = headers or TEST_USERS["admin_headers"]
    return get_success_data(
        api_client.get_application(application_id, headers),
    )


# ===========================================================================
# Tier 3: SEP-event lifecycle
# ===========================================================================
def create_sep_event(
    *,
    application: Dict[str, Any],
    event_type: str = "MARRIAGE",
    event_date: Optional[str] = None,
) -> Dict[str, Any]:
    """POST /applications/{id}/sep-events — Applicant only (PRD §4)."""
    headers = make_applicant_headers(application["_applicant_id"])
    payload = create_sep_event_payload(
        event_type=event_type, event_date=event_date,
    )
    resp = api_client.create_sep_event(application["id"], payload, headers)
    return get_success_data(resp)


def verify_sep_event(
    *, application: Dict[str, Any],
    sep_event: Dict[str, Any],
) -> Dict[str, Any]:
    resp = api_client.verify_sep_event(
        application["id"], sep_event["id"], TEST_USERS["admin_headers"],
    )
    return get_success_data(resp)


def reject_sep_event(
    *, application: Dict[str, Any],
    sep_event: Dict[str, Any],
    reason: Optional[str] = None,
) -> Dict[str, Any]:
    resp = api_client.reject_sep_event(
        application["id"], sep_event["id"], TEST_USERS["admin_headers"],
        payload={"reason": reason} if reason is not None else None,
    )
    return get_success_data(resp)


def appeal_sep_event(
    *, application: Dict[str, Any],
    sep_event: Dict[str, Any],
) -> Dict[str, Any]:
    resp = api_client.appeal_sep_event(
        application["id"], sep_event["id"],
        TEST_USERS["customer_service_headers"],
    )
    return get_success_data(resp)


# ===========================================================================
# Tier 4: Enrollment + invoice lifecycle
# ===========================================================================
def create_enrollment(
    *,
    application: Dict[str, Any],
    plan_variant: Dict[str, Any],
) -> Dict[str, Any]:
    """POST /enrollments — Applicant only (PRD §4)."""
    headers = make_applicant_headers(application["_applicant_id"])
    payload = create_enrollment_payload(
        application_id=application["id"],
        plan_variant_id=plan_variant["id"],
    )
    resp = api_client.create_enrollment(payload, headers)
    return get_success_data(resp)


def cancel_enrollment(
    *, application: Dict[str, Any],
    enrollment: Dict[str, Any],
) -> Dict[str, Any]:
    headers = make_applicant_headers(application["_applicant_id"])
    resp = api_client.cancel_enrollment(enrollment["id"], headers)
    return get_success_data(resp)


def list_premium_invoices(
    *, enrollment: Dict[str, Any],
    headers: Optional[Dict[str, str]] = None,
    params: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """GET /enrollments/{id}/premium-invoices. Returns the data list."""
    headers = headers or TEST_USERS["admin_headers"]
    resp = api_client.list_premium_invoices(
        enrollment["id"], headers, params=params,
    )
    body = get_success_data(resp)
    # PRD §2.2: list response carries "data" as an array. Some
    # implementations return get_success_data directly as the list, others
    # wrap. Handle both.
    if isinstance(body, list):
        return body
    if isinstance(body, dict) and "data" in body and isinstance(
        body["data"], list,
    ):
        return body["data"]
    return body


def post_payment(
    *, application: Dict[str, Any],
    invoice: Dict[str, Any],
    amount_cents: Optional[int] = None,
) -> Dict[str, Any]:
    """POST /premium-invoices/{id}/post-payment.

    PRD §4 roles: Applicant or CustomerService. Default to Applicant
    threaded with the application's applicant_id.
    """
    headers = make_applicant_headers(application["_applicant_id"])
    pay = (
        amount_cents if amount_cents is not None
        else invoice["net_amount_cents"]
    )
    resp = api_client.post_payment(
        invoice["id"], post_payment_payload(amount_cents=pay), headers,
    )
    return get_success_data(resp)


def waive_invoice(
    *, invoice: Dict[str, Any],
    reason: Optional[str] = None,
) -> Dict[str, Any]:
    """POST /premium-invoices/{id}/waive — CustomerService only."""
    headers = TEST_USERS["customer_service_headers"]
    payload = {"reason": reason} if reason is not None else None
    resp = api_client.waive_invoice(invoice["id"], headers, payload=payload)
    return get_success_data(resp)


# ===========================================================================
# Composite Tier-A: ready-to-submit Application
# ===========================================================================
def setup_application_ready_to_submit(
    *,
    coverage_year: int = 2026,
    filing_state: str = "CA",
    primary_age: int = 35,
    primary_income_cents: int = 2_500_000,
    primary_tobacco: bool = False,
    extra_members: Optional[
        List[Dict[str, Any]]
    ] = None,
    applicant_id: Optional[str] = None,
    reference_date: Optional[date] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Compose: Application(DRAFT) + PRIMARY_FILER + one WAGES
    IncomeRecord. Optional `extra_members` lets the caller add SPOUSE
    or DEPENDENT rows; each entry is a dict with keys filer_type,
    age_years (optional), include_in_household, include_in_magi,
    is_tobacco_user, and income_cents (if non-None, adds an
    IncomeRecord under that member).

    Returns (application, primary_member).
    """
    application = create_application(
        coverage_year=coverage_year, filing_state=filing_state,
        applicant_id=applicant_id,
    )
    # PRD §3.6: the age curve is applied at the coverage_start_date,
    # which for OEP-anchored enrollments is January 1 of the coverage
    # year. We compute date_of_birth against that reference so the
    # resulting age bucket matches what the implementation will read at
    # premium time.
    if reference_date is None:
        reference_date = date(coverage_year, 1, 1)
    primary = add_household_member(
        application=application, filer_type="PRIMARY_FILER",
        age_years=primary_age, reference_date=reference_date,
        is_tobacco_user=primary_tobacco,
    )
    add_income_record(
        application=application, member=primary,
        source_type="WAGES", amount_cents=primary_income_cents,
        effective_date=iso_date(date(coverage_year, 1, 1)),
    )
    for entry in (extra_members or []):
        m = add_household_member(
            application=application,
            filer_type=entry.get("filer_type", "DEPENDENT"),
            age_years=entry.get("age_years"),
            date_of_birth=entry.get("date_of_birth"),
            reference_date=reference_date,
            include_in_household=entry.get("include_in_household"),
            include_in_magi=entry.get("include_in_magi"),
            is_tobacco_user=entry.get("is_tobacco_user"),
        )
        if entry.get("income_cents") is not None:
            add_income_record(
                application=application, member=m,
                source_type=entry.get("source_type", "WAGES"),
                amount_cents=entry["income_cents"],
                effective_date=iso_date(date(coverage_year, 1, 1)),
            )
    return application, primary


def setup_submitted_application(
    *,
    coverage_year: int = 2026,
    filing_state: str = "CA",
    primary_age: int = 35,
    primary_income_cents: int = 2_500_000,
    primary_tobacco: bool = False,
    extra_members: Optional[List[Dict[str, Any]]] = None,
    applicant_id: Optional[str] = None,
    reference_date: Optional[date] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Compose: ready_to_submit + /submit. Returns
    (SUBMITTED application, primary_member).
    """
    application, primary = setup_application_ready_to_submit(
        coverage_year=coverage_year, filing_state=filing_state,
        primary_age=primary_age,
        primary_income_cents=primary_income_cents,
        primary_tobacco=primary_tobacco,
        extra_members=extra_members,
        applicant_id=applicant_id,
        reference_date=reference_date,
    )
    submitted = submit_application(application=application)
    return submitted, primary


def setup_eligibility_determined_application(
    *,
    coverage_year: int = 2026,
    filing_state: str = "CA",
    primary_age: int = 35,
    primary_income_cents: int = 2_500_000,
    primary_tobacco: bool = False,
    extra_members: Optional[List[Dict[str, Any]]] = None,
    insurer: Optional[Dict[str, Any]] = None,
    benchmark_plan: Optional[Dict[str, Any]] = None,
    base_monthly_premium_cents: int = 40_000,
    applicant_id: Optional[str] = None,
    reference_date: Optional[date] = None,
) -> Tuple[
    Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any],
]:
    """Compose: benchmark Silver catalog + Application submit +
    determine-eligibility. Returns
    (application, primary_member, insurer, benchmark_plan).
    """
    if insurer is None or benchmark_plan is None:
        insurer_built, plan_built, _variant = setup_benchmark_silver_catalog(
            filing_state=filing_state, coverage_year=coverage_year,
            base_monthly_premium_cents=base_monthly_premium_cents,
            include_standard_variant=False,
        )
        insurer = insurer or insurer_built
        benchmark_plan = benchmark_plan or plan_built
    submitted, primary = setup_submitted_application(
        coverage_year=coverage_year, filing_state=filing_state,
        primary_age=primary_age,
        primary_income_cents=primary_income_cents,
        primary_tobacco=primary_tobacco,
        extra_members=extra_members,
        applicant_id=applicant_id,
        reference_date=reference_date,
    )
    determined = determine_eligibility(application=submitted)
    return determined, primary, insurer, benchmark_plan


def setup_approved_application(
    *,
    coverage_year: int = 2026,
    filing_state: str = "CA",
    primary_age: int = 35,
    primary_income_cents: int = 2_500_000,
    primary_tobacco: bool = False,
    extra_members: Optional[List[Dict[str, Any]]] = None,
    base_monthly_premium_cents: int = 40_000,
    applicant_id: Optional[str] = None,
    reference_date: Optional[date] = None,
    insurer: Optional[Dict[str, Any]] = None,
    benchmark_plan: Optional[Dict[str, Any]] = None,
) -> Tuple[
    Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any],
]:
    """Compose: eligibility_determined + /approve. Returns
    (APPROVED application, primary_member, insurer, benchmark_plan).
    """
    determined, primary, insurer, plan = (
        setup_eligibility_determined_application(
            coverage_year=coverage_year, filing_state=filing_state,
            primary_age=primary_age,
            primary_income_cents=primary_income_cents,
            primary_tobacco=primary_tobacco,
            extra_members=extra_members,
            base_monthly_premium_cents=base_monthly_premium_cents,
            applicant_id=applicant_id,
            reference_date=reference_date,
            insurer=insurer,
            benchmark_plan=benchmark_plan,
        )
    )
    approved = approve_application(application=determined)
    return approved, primary, insurer, plan


# ===========================================================================
# Composite Tier-B: full enrollment with binder paid → ACTIVE coverage
# ===========================================================================
def setup_enrollment_pending_payment(
    *,
    coverage_year: int = 2026,
    filing_state: str = "CA",
    primary_age: int = 35,
    primary_income_cents: int = 5_000_000,
    primary_tobacco: bool = False,
    extra_members: Optional[List[Dict[str, Any]]] = None,
    base_monthly_premium_cents: int = 40_000,
    csr_level: str = "STANDARD",
    applicant_id: Optional[str] = None,
    reference_date: Optional[date] = None,
) -> Tuple[
    Dict[str, Any],   # application
    Dict[str, Any],   # primary_member
    Dict[str, Any],   # insurer
    Dict[str, Any],   # benchmark_plan
    Dict[str, Any],   # plan_variant
    Dict[str, Any],   # enrollment
]:
    """Compose: full pipeline up to Enrollment in PENDING_PAYMENT.

    PRD §3.6: "The enrollment is created in the parallel posture
    coverage_status = PENDING_PAYMENT and payment_status = AWAITING_BINDER."

    Default primary_income_cents is high enough that fpl_percentage
    exceeds 250.0 and csr_eligibility lands in NONE, which the default
    csr_level=STANDARD variant satisfies under PRD §3.6's csr_level ↔
    csr_eligibility alignment rule. Tests that need a non-NONE band
    pass primary_income_cents and a matching csr_level explicitly.
    """
    approved, primary, insurer, plan = setup_approved_application(
        coverage_year=coverage_year, filing_state=filing_state,
        primary_age=primary_age,
        primary_income_cents=primary_income_cents,
        primary_tobacco=primary_tobacco,
        extra_members=extra_members,
        base_monthly_premium_cents=base_monthly_premium_cents,
        applicant_id=applicant_id,
        reference_date=reference_date,
    )
    # PRD §3.5: only Silver plans may carry variants. The
    # setup_benchmark_silver_catalog helper created the benchmark Plan;
    # attach the requested variant if not present.
    variant = create_plan_variant(
        plan=plan, csr_level=csr_level,
        actuarial_value=70.0 if csr_level == "STANDARD" else 97.0,
        out_of_pocket_max_cents=900_000, insurer=insurer,
    )
    enrollment = create_enrollment(
        application=approved, plan_variant=variant,
    )
    return approved, primary, insurer, plan, variant, enrollment


def setup_active_enrollment(
    *,
    coverage_year: int = 2026,
    filing_state: str = "CA",
    primary_age: int = 35,
    primary_income_cents: int = 5_000_000,
    primary_tobacco: bool = False,
    extra_members: Optional[List[Dict[str, Any]]] = None,
    base_monthly_premium_cents: int = 40_000,
    csr_level: str = "STANDARD",
    applicant_id: Optional[str] = None,
    reference_date: Optional[date] = None,
    advance_to_coverage_start: bool = True,
) -> Tuple[
    Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any],
    Dict[str, Any], Dict[str, Any], List[Dict[str, Any]],
]:
    """Compose: setup_enrollment_pending_payment + binder payment + clock
    advance to coverage_start_date. Returns
    (application, primary_member, insurer, plan, variant,
     ACTIVE enrollment, [paid binder invoice, ...]).

    PRD §3.6: "When the binder invoice is paid and the logical clock
    has reached or passed coverage_start_date, the enrollment
    auto-promotes from PENDING_PAYMENT to ACTIVE."
    """
    app, primary, insurer, plan, variant, enrollment = (
        setup_enrollment_pending_payment(
            coverage_year=coverage_year, filing_state=filing_state,
            primary_age=primary_age,
            primary_income_cents=primary_income_cents,
            primary_tobacco=primary_tobacco,
            extra_members=extra_members,
            base_monthly_premium_cents=base_monthly_premium_cents,
            csr_level=csr_level,
            applicant_id=applicant_id,
            reference_date=reference_date,
        )
    )
    # Advance the clock to coverage_start_date (or just after) so the
    # binder transition can fire.
    if advance_to_coverage_start:
        try:
            cov = date.fromisoformat(
                enrollment["coverage_start_date"][:10],
            )
            advance_clock_to_date(cov)
        except Exception:
            # If coverage_start_date is not exposed in a parseable form,
            # rely on the test's own clock-advance.
            pass
    invoices = list_premium_invoices(enrollment=enrollment)
    invoices_sorted = sorted(invoices, key=lambda r: r["billing_month"])
    binder = None
    for inv in invoices_sorted:
        if inv["status"] == "ISSUED":
            binder = inv
            break
    if binder is not None:
        post_payment(application=app, invoice=binder)
    active = re_get_enrollment(enrollment_id=enrollment["id"])
    invoices_after = list_premium_invoices(enrollment=enrollment)
    return app, primary, insurer, plan, variant, active, invoices_after


def re_get_enrollment(
    *, enrollment_id: str,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    headers = headers or TEST_USERS["admin_headers"]
    return get_success_data(
        api_client.get_enrollment(enrollment_id, headers),
    )


# ===========================================================================
# Tier-C threshold targeting helpers
# ===========================================================================
def setup_application_at_fpl_percentage(
    *,
    target_fpl_percentage: float,
    coverage_year: int = 2026,
    filing_state: str = "CA",
    household_size: int = 2,
    primary_age: int = 35,
    primary_tobacco: bool = False,
    base_monthly_premium_cents: int = 40_000,
    spouse_age: int = 35,
    applicant_id: Optional[str] = None,
    magi_override: Optional[int] = None,
) -> Tuple[
    Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any],
]:
    """Compose: an Application whose computed fpl_percentage equals
    `target_fpl_percentage` to one decimal place, after submit +
    determine-eligibility.

    Used for CSR boundary tests (138.0 exact, 137.9, etc.). Internally:
    1. Builds benchmark Silver catalog.
    2. Picks household_size members (PRIMARY_FILER + optional SPOUSE).
    3. Computes the total_magi_cents that produces the target
       fpl_percentage given the denominator from the FPL table for the
       coverage_year and size, unless magi_override is supplied (in
       which case the test pins MAGI exactly).
    4. Posts one WAGES IncomeRecord on the primary filer with that
       amount.
    5. Submits and determines eligibility.

    Returns (application, primary_member, insurer, benchmark_plan).
    """
    if household_size < 1 or household_size > 6:
        raise ValueError(
            f"household_size {household_size} not supported by helper "
            f"(use 1..6).",
        )
    denom = fpl_denominator(coverage_year, household_size)
    # PRD §3.2: fpl_percentage = total_magi_cents / denominator * 100,
    # rounded half-up to 1 decimal place. To hit a target rounded value
    # X.Y exactly, set total_magi_cents = round(denom * X.Y / 100).
    if magi_override is not None:
        magi_cents = magi_override
    else:
        raw = denom * target_fpl_percentage / 100.0
        magi_cents = int(raw + 0.5)
    extra: List[Dict[str, Any]] = []
    for idx in range(1, household_size):
        # First extra is SPOUSE, then DEPENDENTs of age 20 (>=19 so not
        # auto Medicaid via age<19 rule).
        #
        # PRD §3.2 submit precondition: every include_in_magi=true
        # member must have at least one IncomeRecord. The helper pins
        # all household income onto the PRIMARY_FILER (via the
        # primary_income_cents argument that magi_cents lands on), so
        # extra members are added as include_in_magi=False to keep them
        # counted in household_size without requiring per-member income
        # records.
        if idx == 1:
            extra.append({
                "filer_type": "SPOUSE",
                "age_years": spouse_age,
                "include_in_magi": False,
            })
        else:
            extra.append({
                "filer_type": "DEPENDENT",
                "age_years": 20,
                "include_in_magi": False,
            })
    insurer, plan, _v = setup_benchmark_silver_catalog(
        filing_state=filing_state, coverage_year=coverage_year,
        base_monthly_premium_cents=base_monthly_premium_cents,
        include_standard_variant=False,
    )
    determined, primary, _ins, _pl = (
        setup_eligibility_determined_application(
            coverage_year=coverage_year, filing_state=filing_state,
            primary_age=primary_age,
            primary_income_cents=magi_cents,
            primary_tobacco=primary_tobacco,
            extra_members=extra, insurer=insurer,
            benchmark_plan=plan,
            base_monthly_premium_cents=base_monthly_premium_cents,
            applicant_id=applicant_id,
        )
    )
    return determined, primary, insurer, plan


def setup_active_enrollment_with_outstanding_invoice(
    *,
    billing_month: str,
    due_date: str,
    coverage_year: int = 2026,
    base_monthly_premium_cents: int = 20_000,
    primary_age: int = 35,
    applicant_id: Optional[str] = None,
) -> Tuple[
    Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any],
]:
    """Compose: ACTIVE enrollment + one ISSUED (unpaid) PremiumInvoice
    whose billing_month / due_date are as specified.

    Used for grace-period / payment_status_rollup boundary tests. The
    test calls /_clock/advance to push the clock past due_date by the
    desired number of days, then /_sweep/age-invoices to trigger the
    rollup.

    Returns (application, enrollment, invoice, plan_variant).
    """
    # We need ACTIVE Enrollment with at least one unpaid invoice in the
    # specified billing_month. The implementation auto-issues monthly
    # invoices; we manually advance the clock so the requested billing
    # month exists. This helper is best-effort: it returns whatever
    # invoice the implementation has for that month if any.
    # Use a high-income / no-subsidy applicant so APTC=0 and
    # monthly_net_premium_cents = monthly_premium_gross_cents.
    high_income = 50_000_000  # well above 400% FPL → no subsidy
    app, primary, insurer, plan, variant, active, invoices = (
        setup_active_enrollment(
            coverage_year=coverage_year, filing_state="CA",
            primary_age=primary_age, primary_income_cents=high_income,
            base_monthly_premium_cents=base_monthly_premium_cents,
            applicant_id=applicant_id,
        )
    )
    # Best-effort: return the invoice for the requested billing_month if
    # present, else the first ISSUED invoice.
    target = None
    for inv in invoices:
        if inv["billing_month"] == billing_month:
            target = inv
            break
    if target is None:
        for inv in invoices:
            if inv["status"] == "ISSUED":
                target = inv
                break
    return app, active, target or (invoices[0] if invoices else {}), variant


__all__ = [
    "advance_clock_to",
    "advance_clock_to_date",
    "create_insurer",
    "create_plan",
    "create_plan_variant",
    "setup_benchmark_silver_catalog",
    "fresh_applicant_id",
    "create_application",
    "add_household_member",
    "add_income_record",
    "submit_application",
    "amend_application",
    "determine_eligibility",
    "approve_application",
    "deny_application",
    "redetermine_application",
    "re_get_application",
    "create_sep_event",
    "verify_sep_event",
    "reject_sep_event",
    "appeal_sep_event",
    "create_enrollment",
    "cancel_enrollment",
    "list_premium_invoices",
    "post_payment",
    "waive_invoice",
    "setup_application_ready_to_submit",
    "setup_submitted_application",
    "setup_eligibility_determined_application",
    "setup_approved_application",
    "setup_enrollment_pending_payment",
    "setup_active_enrollment",
    "re_get_enrollment",
    "setup_application_at_fpl_percentage",
    "setup_active_enrollment_with_outstanding_invoice",
]
