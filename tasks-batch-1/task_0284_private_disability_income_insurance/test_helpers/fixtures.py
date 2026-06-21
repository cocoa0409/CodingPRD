"""Composite setup helpers.

Every fixture builds its preconditions from scratch using only PRD-declared
endpoints, because the harness restarts the server (empty database) before each
test. Fixtures use get_success_data() internally so setup failures surface as
clear "Setup step failed" errors.

Identity threading: the Policyholder role is entity-backed, so all ownership-
gated calls (file claim, submit, income-report, disability-proof) use
make_policyholder_headers(policyholder["id"]). Underwriter / ClaimsAdjudicator /
SystemOperator are opaque, so their shared header constants are used.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .test_users import (
    TEST_USERS,
    make_policyholder_headers,
)
from . import factories as f

UW = TEST_USERS["underwriter_headers"]
ADJ = TEST_USERS["claims_adjudicator_headers"]
OPR = TEST_USERS["system_operator_headers"]


# ─── Tier 0: primitives ───────────────────────────────

def create_insurer(name="Test Insurer"):
    resp = api_client.create_insurer(f.create_insurer_payload(name=name), UW)
    return get_success_data(resp)


def advance_clock(insurer_id, by_months):
    resp = api_client.advance_clock(
        insurer_id, f.advance_clock_payload(by_months=by_months), OPR
    )
    return get_success_data(resp)


def create_occupation_class(insurer_id, **overrides):
    resp = api_client.create_occupation_class(
        f.create_occupation_class_payload(insurer_id, **overrides), UW
    )
    return get_success_data(resp)


def create_policyholder(insurer_id, **overrides):
    resp = api_client.create_policyholder(
        f.create_policyholder_payload(insurer_id, **overrides), UW
    )
    return get_success_data(resp)


def create_policy(insurer_id, policyholder_id, occupation_class_id, **overrides):
    resp = api_client.create_policy(
        f.create_policy_payload(insurer_id, policyholder_id, occupation_class_id, **overrides), UW
    )
    return get_success_data(resp)


# ─── Tier 1: book + active policy ─────────────────────

def setup_book(clock_months=0, occ_overrides=None, ph_overrides=None):
    """Insurer (optionally advanced), one occupation class, one policyholder.
    Returns dict: insurer, occupation_class, policyholder."""
    occ_overrides = occ_overrides or {}
    ph_overrides = ph_overrides or {}
    insurer = create_insurer()
    if clock_months:
        advance_clock(insurer["id"], clock_months)
        insurer = get_success_data(api_client.get_insurer(insurer["id"], UW))
    occ = create_occupation_class(insurer["id"], **occ_overrides)
    ph = create_policyholder(insurer["id"], **ph_overrides)
    return {"insurer": insurer, "occupation_class": occ, "policyholder": ph}


def setup_active_policy(clock_months=0, policy_overrides=None,
                        occ_overrides=None, ph_overrides=None):
    """Active policy with its supporting book. Returns dict:
    insurer, occupation_class, policyholder, policy (ACTIVE)."""
    policy_overrides = policy_overrides or {}
    book = setup_book(clock_months=clock_months, occ_overrides=occ_overrides,
                      ph_overrides=ph_overrides)
    policy = create_policy(
        book["insurer"]["id"], book["policyholder"]["id"],
        book["occupation_class"]["id"], **policy_overrides
    )
    get_success_data(api_client.activate_policy(policy["id"], UW))
    policy = get_success_data(api_client.get_policy(policy["id"], UW))
    book["policy"] = policy
    return book


def setup_pending_policy(policy_overrides=None, occ_overrides=None, ph_overrides=None):
    """Issued but NOT activated policy (PENDING/CURRENT). Returns dict with policy."""
    policy_overrides = policy_overrides or {}
    book = setup_book(occ_overrides=occ_overrides, ph_overrides=ph_overrides)
    policy = create_policy(
        book["insurer"]["id"], book["policyholder"]["id"],
        book["occupation_class"]["id"], **policy_overrides
    )
    book["policy"] = policy
    return book


# ─── Tier 2: claims at chosen lifecycle stage ─────────

def file_claim(insurer_id, policy_id, policyholder_id,
               disability_onset_month=0, claimed_disability_type="TOTAL"):
    """File a DRAFT claim as the owning policyholder. Returns claim data."""
    resp = api_client.create_claim(
        f.create_claim_payload(
            insurer_id, policy_id,
            disability_onset_month=disability_onset_month,
            claimed_disability_type=claimed_disability_type,
        ),
        make_policyholder_headers(policyholder_id),
    )
    return get_success_data(resp)


def add_income_report(claim_id, policyholder_id, effective_month,
                      current_monthly_income_cents, expected_claim_version):
    resp = api_client.create_income_report(
        claim_id,
        f.create_income_report_payload(
            effective_month, current_monthly_income_cents, expected_claim_version
        ),
        make_policyholder_headers(policyholder_id),
    )
    return get_success_data(resp)


def setup_submitted_claim(clock_months=5, policy_overrides=None, occ_overrides=None,
                          disability_onset_month=0, claimed_disability_type="TOTAL",
                          income_reports=None):
    """Book + active policy + a SUBMITTED claim.
    income_reports: optional list of (effective_month, current_monthly_income_cents)
    tuples added (in order) before submission, for RESIDUAL claims.
    Returns dict: insurer, occupation_class, policyholder, policy, claim."""
    book = setup_active_policy(clock_months=clock_months, policy_overrides=policy_overrides,
                               occ_overrides=occ_overrides)
    ph_id = book["policyholder"]["id"]
    claim = file_claim(book["insurer"]["id"], book["policy"]["id"], ph_id,
                       disability_onset_month=disability_onset_month,
                       claimed_disability_type=claimed_disability_type)
    if income_reports:
        cur_ver = claim["version"]
        for eff_month, income in income_reports:
            add_income_report(claim["id"], ph_id, eff_month, income, cur_ver)
            cur_ver += 1
    get_success_data(api_client.submit_claim(claim["id"], make_policyholder_headers(ph_id)))
    claim = get_success_data(api_client.get_claim(claim["id"], ADJ))
    book["claim"] = claim
    return book


def setup_under_review_claim(**kwargs):
    """As setup_submitted_claim, then begin-review. Returns dict with UNDER_REVIEW claim."""
    book = setup_submitted_claim(**kwargs)
    get_success_data(api_client.begin_review(book["claim"]["id"], ADJ))
    book["claim"] = get_success_data(api_client.get_claim(book["claim"]["id"], ADJ))
    return book


def setup_approved_claim(**kwargs):
    """As setup_under_review_claim, then approve. Requires clock_months >=
    elimination_satisfied_month. Returns dict with APPROVED claim."""
    book = setup_under_review_claim(**kwargs)
    get_success_data(api_client.approve_claim(book["claim"]["id"], ADJ))
    book["claim"] = get_success_data(api_client.get_claim(book["claim"]["id"], ADJ))
    return book


# ─── Tier 3: accrual / threshold targeting ────────────

def accrue_benefit_period(claim_id, coverage_month):
    resp = api_client.create_benefit_period(
        claim_id, f.create_benefit_period_payload(coverage_month), ADJ
    )
    return get_success_data(resp)


def setup_approved_total_with_periods(coverage_months, clock_months=6,
                                      policy_overrides=None):
    """Approved TOTAL claim with one accrued BenefitPeriod per coverage_month.
    Returns dict: insurer, occupation_class, policyholder, policy, claim,
    benefit_periods (list aligned with coverage_months)."""
    book = setup_approved_claim(clock_months=clock_months,
                                policy_overrides=policy_overrides,
                                claimed_disability_type="TOTAL")
    bps = [accrue_benefit_period(book["claim"]["id"], m) for m in coverage_months]
    book["benefit_periods"] = bps
    book["claim"] = get_success_data(api_client.get_claim(book["claim"]["id"], ADJ))
    return book


def setup_approved_residual_with_report(effective_month, current_monthly_income_cents,
                                        clock_months=5, policy_overrides=None,
                                        occ_overrides=None, disability_onset_month=0):
    """Approved RESIDUAL claim carrying one IncomeReport. Returns dict:
    insurer, occupation_class, policyholder, policy, claim."""
    return setup_approved_claim(
        clock_months=clock_months,
        policy_overrides=policy_overrides,
        occ_overrides=occ_overrides,
        disability_onset_month=disability_onset_month,
        claimed_disability_type="RESIDUAL",
        income_reports=[(effective_month, current_monthly_income_cents)],
    )


# ─── Tier 4: offsets on an approved claim ─────────────

def add_offset_award(claim_id, offset_source, monthly_offset_cents, start_month, end_month):
    resp = api_client.create_offset_award(
        claim_id,
        f.create_offset_award_payload(offset_source, monthly_offset_cents, start_month, end_month),
        ADJ,
    )
    return get_success_data(resp)


def finalize_offset(offset_award_id, final_monthly_offset_cents=None):
    payload = (
        f.finalize_offset_award_payload(final_monthly_offset_cents=final_monthly_offset_cents)
        if final_monthly_offset_cents is not None
        else f.finalize_offset_award_payload()
    )
    resp = api_client.finalize_offset_award(offset_award_id, payload, ADJ)
    return get_success_data(resp)


def setup_total_claim_with_period_and_estimated_offset(
        offset_source="SSDI", monthly_offset_cents=120000,
        offset_window=(3, 5), coverage_month=3, clock_months=5,
        policy_overrides=None):
    """Approved TOTAL claim, one accrued BenefitPeriod, one ESTIMATED OffsetAward.
    Returns dict: ..., claim, benefit_period, offset_award."""
    book = setup_approved_total_with_periods(
        [coverage_month], clock_months=clock_months, policy_overrides=policy_overrides
    )
    oa = add_offset_award(
        book["claim"]["id"], offset_source, monthly_offset_cents,
        offset_window[0], offset_window[1]
    )
    book["benefit_period"] = book["benefit_periods"][0]
    book["offset_award"] = oa
    return book


# ─── Tier 5: premium lifecycle staging ────────────────

def drive_premium_to_grace(policy_id):
    """One missed premium: CURRENT -> GRACE. Returns updated policy data."""
    return get_success_data(api_client.premium_miss(policy_id, UW))


def drive_premium_to_default(policy_id):
    """Two missed premiums: CURRENT -> GRACE -> DEFAULT (lapses lifecycle).
    Returns updated policy data after the second miss."""
    get_success_data(api_client.premium_miss(policy_id, UW))
    return get_success_data(api_client.premium_miss(policy_id, UW))
