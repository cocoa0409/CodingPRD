"""Composite setup helpers — multi-step preambles tests can reuse.

The HSA/FSA pipeline is long: clock advance -> account holder create
-> dependent (optional) -> account open -> plan year open -> qualified
expense seed -> contribution post -> claim create -> submit -> approve
(with SoD) -> pay -> potential reverse, or year-end OpsRun closure.

IDENTITY THREADING — PRD §2.1:

- PlanAdministrator / ClaimAdjudicator / Auditor are OPAQUE. Shared
  constants (plan_admin_headers, adjudicator_headers, auditor_headers)
  are canonical for every operator-only call.

- AccountHolder is ENTITY-BACKED. PRD §2.1: 'access to any resource
  whose owning AccountHolder.id does not equal X-User-ID is rejected
  with ERR_NOT_FOUND'. Every AccountHolder-driven call whose success
  depends on owning the targeted resource MUST mint headers via
  make_account_holder_headers(account_holder["id"]) — never via the
  shared ACCOUNT_HOLDER_FALLBACK_ID. The fixtures here return the
  actual AccountHolder row so consumer tests / consumer fixtures can
  route account-holder-acting calls through this header builder.

SEGREGATION OF DUTIES — PRD §2.9: Approval and denial of a SUBMITTED
claim cannot be made by the same X-User-ID that wrote the
CLAIM_SUBMITTED audit event. The default adjudicator id used in these
fixtures is adjudicator-001, which never equals any AccountHolder.id;
fixtures that intentionally trigger ERR_SEGREGATION_OF_DUTIES pass
make_adjudicator_headers(account_holder["id"]) explicitly.

Setup calls use get_success_data (a lenient 2xx validator), so a
failed setup surfaces as 'Setup failed' rather than a confusing test
assertion failure downstream.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    clock_advance_payload,
    create_account_holder_payload,
    create_account_payload,
    create_claim_payload,
    create_contribution_payload,
    create_dependent_payload,
    create_ops_run_payload,
    create_plan_year_payload,
    create_qualified_expense_payload,
    deny_claim_payload,
    iso_datetime_utc,
)
from .test_users import (
    TEST_USERS,
    make_account_holder_headers,
)


# ===========================================================================
# Clock helpers — PRD §2.7
# ===========================================================================
def get_clock_state(headers: Optional[Dict[str, str]] = None
                    ) -> Dict[str, Any]:
    """GET /_clock. Returns the parsed data payload with 'now' field."""
    headers = headers or TEST_USERS["auditor_headers"]
    resp = api_client.get_clock(headers)
    return get_success_data(resp)


def advance_clock_to(to_instant: str,
                     headers: Optional[Dict[str, str]] = None
                     ) -> Dict[str, Any]:
    """POST /_clock/advance to=<ISO instant>. Returns the ClockState
    dict carrying 'now'."""
    headers = headers or TEST_USERS["plan_admin_headers"]
    resp = api_client.clock_advance(
        clock_advance_payload(to=to_instant), headers,
    )
    return get_success_data(resp)


def advance_clock_to_date(year: int, month: int, day: int,
                          headers: Optional[Dict[str, str]] = None
                          ) -> Dict[str, Any]:
    """Convenience: advance to YYYY-MM-DDT00:00:00Z."""
    return advance_clock_to(
        iso_datetime_utc(year, month, day), headers=headers,
    )


# ===========================================================================
# AccountHolder + Dependent — PRD §3.1
# ===========================================================================
def create_account_holder(
    *,
    full_name: Optional[str] = None,
    ssn_last4: Optional[str] = None,
    tax_filing_status: str = "SINGLE",
    birth_date: Optional[str] = None,
    plan_admin_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /account-holders. Returns the created AccountHolder dict.

    PRD §4: only PlanAdministrator may create an AccountHolder.
    """
    plan_admin_headers = (
        plan_admin_headers or TEST_USERS["plan_admin_headers"]
    )
    payload = create_account_holder_payload(
        full_name=full_name,
        ssn_last4=ssn_last4,
        tax_filing_status=tax_filing_status,
        birth_date=birth_date,
    )
    resp = api_client.create_account_holder(payload, plan_admin_headers)
    return get_success_data(resp)


def create_dependent(
    *,
    account_holder: Dict[str, Any],
    full_name: Optional[str] = None,
    birth_date: Optional[str] = None,
    relationship: str = "CHILD",
    use_holder_headers: bool = False,
) -> Dict[str, Any]:
    """POST /account-holders/{id}/dependents.

    PRD §4: AccountHolder and PlanAdministrator may add a dependent.
    Defaults to PlanAdministrator (opaque, no ownership burden); to
    exercise the AccountHolder pathway pass use_holder_headers=True so
    the call goes through make_account_holder_headers.
    """
    if use_holder_headers:
        headers = make_account_holder_headers(account_holder["id"])
    else:
        headers = TEST_USERS["plan_admin_headers"]
    payload = create_dependent_payload(
        full_name=full_name,
        birth_date=birth_date,
        relationship=relationship,
    )
    resp = api_client.create_dependent(
        account_holder["id"], payload, headers,
    )
    return get_success_data(resp)


def deactivate_dependent(dependent_id: str,
                         plan_admin_headers: Optional[Dict[str, str]] = None
                         ) -> Dict[str, Any]:
    """POST /dependents/{id}/deactivate (PlanAdministrator only)."""
    plan_admin_headers = (
        plan_admin_headers or TEST_USERS["plan_admin_headers"]
    )
    resp = api_client.deactivate_dependent(dependent_id, plan_admin_headers)
    return get_success_data(resp)


# ===========================================================================
# Account — PRD §3.1
# ===========================================================================
def open_account(
    account_holder: Dict[str, Any],
    *,
    account_type: str = "HSA",
    coverage_tier: Optional[str] = "SELF_ONLY",
    year_end_policy: str = "NONE",
    account_holder_birth_date: Optional[str] = None,
    plan_admin_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /accounts. PlanAdministrator only per PRD §4."""
    plan_admin_headers = (
        plan_admin_headers or TEST_USERS["plan_admin_headers"]
    )
    payload = create_account_payload(
        account_holder_id=account_holder["id"],
        account_type=account_type,
        coverage_tier=coverage_tier,
        year_end_policy=year_end_policy,
        account_holder_birth_date=(
            account_holder_birth_date
            or account_holder.get("birth_date")
        ),
    )
    resp = api_client.create_account(payload, plan_admin_headers)
    return get_success_data(resp)


def get_account(account_id: str,
                headers: Optional[Dict[str, str]] = None
                ) -> Dict[str, Any]:
    """GET /accounts/{id}. Defaults to PlanAdministrator to avoid
    ownership burden in setup paths."""
    headers = headers or TEST_USERS["plan_admin_headers"]
    resp = api_client.get_account(account_id, headers)
    return get_success_data(resp)


def freeze_account(account_id: str,
                   plan_admin_headers: Optional[Dict[str, str]] = None
                   ) -> Dict[str, Any]:
    plan_admin_headers = (
        plan_admin_headers or TEST_USERS["plan_admin_headers"]
    )
    resp = api_client.freeze_account(account_id, plan_admin_headers)
    return get_success_data(resp)


def unfreeze_account(account_id: str,
                     plan_admin_headers: Optional[Dict[str, str]] = None
                     ) -> Dict[str, Any]:
    plan_admin_headers = (
        plan_admin_headers or TEST_USERS["plan_admin_headers"]
    )
    resp = api_client.unfreeze_account(account_id, plan_admin_headers)
    return get_success_data(resp)


def close_account(account_id: str,
                  plan_admin_headers: Optional[Dict[str, str]] = None
                  ) -> Dict[str, Any]:
    plan_admin_headers = (
        plan_admin_headers or TEST_USERS["plan_admin_headers"]
    )
    resp = api_client.close_account(account_id, plan_admin_headers)
    return get_success_data(resp)


# ===========================================================================
# PlanYear — PRD §3.2
# ===========================================================================
def open_plan_year(
    account_id: str,
    *,
    calendar_year: int,
    plan_admin_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /accounts/{accountId}/plan-years. PlanAdministrator only."""
    plan_admin_headers = (
        plan_admin_headers or TEST_USERS["plan_admin_headers"]
    )
    payload = create_plan_year_payload(calendar_year=calendar_year)
    resp = api_client.create_plan_year(
        account_id, payload, plan_admin_headers,
    )
    return get_success_data(resp)


def get_plan_year(account_id: str, plan_year_id: str,
                  headers: Optional[Dict[str, str]] = None
                  ) -> Dict[str, Any]:
    headers = headers or TEST_USERS["plan_admin_headers"]
    resp = api_client.get_plan_year(account_id, plan_year_id, headers)
    return get_success_data(resp)


# ===========================================================================
# Contribution — PRD §3.3
# ===========================================================================
def post_contribution(
    plan_year_id: str,
    *,
    amount_cents: int,
    source: str = "PAYROLL",
    plan_admin_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /plan-years/{planYearId}/contributions.

    PRD §4: AccountHolder and PlanAdministrator may post. Defaults to
    PlanAdministrator (opaque) so setup paths skip the ownership
    threading burden. Tests that explicitly want an AccountHolder-
    acting contribution should call api_client.create_contribution
    directly with make_account_holder_headers(account_holder['id']).
    """
    plan_admin_headers = (
        plan_admin_headers or TEST_USERS["plan_admin_headers"]
    )
    payload = create_contribution_payload(
        amount_cents=amount_cents, source=source,
    )
    resp = api_client.create_contribution(
        plan_year_id, payload, plan_admin_headers,
    )
    return get_success_data(resp)


def reverse_contribution(contribution_id: str,
                         plan_admin_headers: Optional[Dict[str, str]] = None
                         ) -> Dict[str, Any]:
    """POST /contributions/{id}/reverse. PlanAdministrator only."""
    plan_admin_headers = (
        plan_admin_headers or TEST_USERS["plan_admin_headers"]
    )
    resp = api_client.reverse_contribution(
        contribution_id, plan_admin_headers,
    )
    return get_success_data(resp)


# ===========================================================================
# QualifiedExpense — PRD §3.4
# ===========================================================================
def seed_qualified_expense(
    *,
    code: Optional[str] = None,
    category: str = "MEDICAL",
    eligible_account_types: Optional[List[str]] = None,
    requires_dependent: bool = False,
    plan_admin_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /qualified-expenses (PlanAdministrator only)."""
    plan_admin_headers = (
        plan_admin_headers or TEST_USERS["plan_admin_headers"]
    )
    payload = create_qualified_expense_payload(
        code=code,
        category=category,
        eligible_account_types=eligible_account_types,
        requires_dependent=requires_dependent,
    )
    resp = api_client.create_qualified_expense(payload, plan_admin_headers)
    return get_success_data(resp)


# ===========================================================================
# Claim lifecycle — PRD §3.5
# ===========================================================================
def create_claim(
    *,
    account_holder: Dict[str, Any],
    account: Dict[str, Any],
    service_date: str,
    expense_code: str,
    amount_cents: int,
    dependent_id: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /accounts/{accountId}/claims.

    PRD §4 + §2.1: only AccountHolder may create a claim, and that
    holder must own the account (ownership-gated). Headers default to
    make_account_holder_headers(account_holder['id']) — never the
    shared fallback.
    """
    headers = headers or make_account_holder_headers(account_holder["id"])
    payload = create_claim_payload(
        service_date=service_date,
        expense_code=expense_code,
        amount_cents=amount_cents,
        dependent_id=dependent_id,
    )
    resp = api_client.create_claim(account["id"], payload, headers)
    return get_success_data(resp)


def submit_claim(
    claim_id: str,
    *,
    account_holder: Dict[str, Any],
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /claims/{claimId}/submit.

    PRD §4: only AccountHolder may submit, and ownership applies.
    Headers default to make_account_holder_headers(account_holder['id'])
    so the call passes ownership scope.
    """
    headers = headers or make_account_holder_headers(account_holder["id"])
    resp = api_client.submit_claim(claim_id, headers)
    return get_success_data(resp)


def approve_claim(
    claim_id: str,
    *,
    adjudicator_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /claims/{claimId}/approve. ClaimAdjudicator only.

    Defaults to a shared adjudicator whose X-User-ID never equals any
    AccountHolder.id (adjudicator-001). Tests that intentionally
    trigger ERR_SEGREGATION_OF_DUTIES must pass an adjudicator headers
    dict whose X-User-ID equals the submitting AccountHolder.id.
    """
    adjudicator_headers = (
        adjudicator_headers or TEST_USERS["adjudicator_headers"]
    )
    resp = api_client.approve_claim(claim_id, adjudicator_headers)
    return get_success_data(resp)


def pay_claim(
    claim_id: str,
    *,
    adjudicator_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /claims/{claimId}/pay. ClaimAdjudicator only."""
    adjudicator_headers = (
        adjudicator_headers or TEST_USERS["adjudicator_headers"]
    )
    resp = api_client.pay_claim(claim_id, adjudicator_headers)
    return get_success_data(resp)


def deny_claim(
    claim_id: str,
    *,
    denial_reason: str,
    adjudicator_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /claims/{claimId}/deny. ClaimAdjudicator only."""
    adjudicator_headers = (
        adjudicator_headers or TEST_USERS["adjudicator_headers"]
    )
    payload = deny_claim_payload(denial_reason=denial_reason)
    resp = api_client.deny_claim(claim_id, payload, adjudicator_headers)
    return get_success_data(resp)


def reverse_claim(
    claim_id: str,
    *,
    adjudicator_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /claims/{claimId}/reverse. ClaimAdjudicator only."""
    adjudicator_headers = (
        adjudicator_headers or TEST_USERS["adjudicator_headers"]
    )
    resp = api_client.reverse_claim(claim_id, adjudicator_headers)
    return get_success_data(resp)


def get_claim(claim_id: str,
              headers: Optional[Dict[str, str]] = None
              ) -> Dict[str, Any]:
    headers = headers or TEST_USERS["plan_admin_headers"]
    resp = api_client.get_claim(claim_id, headers)
    return get_success_data(resp)


# ===========================================================================
# OpsRun — PRD §3.7
# ===========================================================================
def post_ops_run(
    *,
    kind: str,
    as_of_date: str,
    plan_admin_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /ops-runs (PlanAdministrator only)."""
    plan_admin_headers = (
        plan_admin_headers or TEST_USERS["plan_admin_headers"]
    )
    payload = create_ops_run_payload(kind=kind, as_of_date=as_of_date)
    resp = api_client.create_ops_run(payload, plan_admin_headers)
    return get_success_data(resp)


def list_audit_events(account_id: str,
                      *,
                      plan_year_id: Optional[str] = None,
                      event_type: Optional[str] = None,
                      headers: Optional[Dict[str, str]] = None
                      ) -> List[Dict[str, Any]]:
    """GET /accounts/{accountId}/audit-events. Returns the data list."""
    headers = headers or TEST_USERS["auditor_headers"]
    params: Dict[str, Any] = {}
    if plan_year_id is not None:
        params["plan_year_id"] = plan_year_id
    if event_type is not None:
        params["event_type"] = event_type
    resp = api_client.list_audit_events(
        account_id, headers, params=params or None,
    )
    data = get_success_data(resp)
    if isinstance(data, list):
        return data
    return []


# ===========================================================================
# Composite setups driven by SCAFFOLD_DIFFICULTY_DESIGN test recipes
# ===========================================================================
def setup_holder_and_account(
    *,
    account_type: str = "HSA",
    coverage_tier: Optional[str] = "SELF_ONLY",
    year_end_policy: str = "NONE",
    tax_filing_status: str = "SINGLE",
    birth_date: Optional[str] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Create a single AccountHolder + Account pair. PRD §3.1 layout."""
    holder = create_account_holder(
        tax_filing_status=tax_filing_status,
        birth_date=birth_date,
    )
    acct = open_account(
        holder,
        account_type=account_type,
        coverage_tier=coverage_tier,
        year_end_policy=year_end_policy,
        account_holder_birth_date=holder.get("birth_date"),
    )
    return holder, acct


def setup_active_plan_year(
    *,
    account_type: str = "HSA",
    coverage_tier: Optional[str] = "SELF_ONLY",
    year_end_policy: str = "NONE",
    tax_filing_status: str = "SINGLE",
    birth_date: Optional[str] = None,
    calendar_year: int = 2025,
    clock_anchor: Optional[str] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Advance clock if needed, then create holder + account +
    PlanYear. Returns (holder, account, plan_year).

    PRD §3.2: 'The pair (account_id, calendar_year) is unique per
    account ... A newly opened PlanYear starts in status ACTIVE.'
    """
    if clock_anchor is None:
        # Anchor late in the year so claims with default mid-year
        # service_date (e.g., 6/15) are not future-dated relative to
        # the logical clock (PRD §3.5: service_date must be <= clock).
        clock_anchor = iso_datetime_utc(calendar_year, 12, 1)
    advance_clock_to(clock_anchor)
    holder, acct = setup_holder_and_account(
        account_type=account_type,
        coverage_tier=coverage_tier,
        year_end_policy=year_end_policy,
        tax_filing_status=tax_filing_status,
        birth_date=birth_date,
    )
    py = open_plan_year(acct["id"], calendar_year=calendar_year)
    return holder, acct, py


def setup_funded_plan_year(
    *,
    account_type: str = "HSA",
    coverage_tier: Optional[str] = "SELF_ONLY",
    year_end_policy: str = "NONE",
    tax_filing_status: str = "SINGLE",
    birth_date: Optional[str] = None,
    calendar_year: int = 2025,
    contribution_cents: int = 100_000,
    clock_anchor: Optional[str] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Setup an ACTIVE plan year and post a single contribution. Returns
    (holder, account, plan_year_after_contribution).

    The plan year row returned is re-read so denormalized counters
    reflect the post-contribution state.
    """
    holder, acct, py = setup_active_plan_year(
        account_type=account_type,
        coverage_tier=coverage_tier,
        year_end_policy=year_end_policy,
        tax_filing_status=tax_filing_status,
        birth_date=birth_date,
        calendar_year=calendar_year,
        clock_anchor=clock_anchor,
    )
    if contribution_cents > 0:
        post_contribution(py["id"], amount_cents=contribution_cents,
                          source="PAYROLL")
        py = get_plan_year(acct["id"], py["id"])
    return holder, acct, py


def setup_paid_claim(
    *,
    account_type: str = "HSA",
    coverage_tier: Optional[str] = "SELF_ONLY",
    year_end_policy: str = "NONE",
    expense_category: str = "MEDICAL",
    requires_dependent: bool = False,
    eligible_account_types: Optional[List[str]] = None,
    calendar_year: int = 2025,
    contribution_cents: int = 100_000,
    claim_cents: int = 20_000,
    service_month: int = 6,
    service_day: int = 15,
    tax_filing_status: str = "SINGLE",
    birth_date: Optional[str] = None,
    clock_anchor: Optional[str] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any],
           Dict[str, Any], Dict[str, Any]]:
    """Full happy-path: holder + account + plan year + contribution +
    qualified-expense seed + claim through PAID state. Returns
    (holder, account, plan_year_after_pay, qualified_expense, claim_after_pay).

    SoD: submit goes through make_account_holder_headers(holder['id']);
    approve and pay go through the default shared adjudicator_headers
    (whose X-User-ID never equals the holder's id).
    """
    holder, acct, py = setup_funded_plan_year(
        account_type=account_type,
        coverage_tier=coverage_tier,
        year_end_policy=year_end_policy,
        tax_filing_status=tax_filing_status,
        birth_date=birth_date,
        calendar_year=calendar_year,
        contribution_cents=contribution_cents,
        clock_anchor=clock_anchor,
    )
    if eligible_account_types is None:
        eligible_account_types = [account_type]
    qe = seed_qualified_expense(
        category=expense_category,
        eligible_account_types=eligible_account_types,
        requires_dependent=requires_dependent,
    )
    service_date = iso_datetime_utc(calendar_year, service_month, service_day)
    claim = create_claim(
        account_holder=holder, account=acct,
        service_date=service_date,
        expense_code=qe["code"],
        amount_cents=claim_cents,
    )
    submit_claim(claim["id"], account_holder=holder)
    approve_claim(claim["id"])
    pay_claim(claim["id"])
    claim_after_pay = get_claim(claim["id"])
    py_after_pay = get_plan_year(acct["id"], py["id"])
    return holder, acct, py_after_pay, qe, claim_after_pay


def setup_approved_claim(
    *,
    account_type: str = "HSA",
    coverage_tier: Optional[str] = "SELF_ONLY",
    year_end_policy: str = "NONE",
    expense_category: str = "MEDICAL",
    eligible_account_types: Optional[List[str]] = None,
    calendar_year: int = 2025,
    contribution_cents: int = 100_000,
    claim_cents: int = 20_000,
    tax_filing_status: str = "SINGLE",
    birth_date: Optional[str] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any],
           Dict[str, Any], Dict[str, Any]]:
    """Holder + account + plan year + contribution + expense + claim
    advanced through APPROVED (but NOT yet PAID). Returns
    (holder, account, plan_year, qualified_expense, claim_after_approve).
    """
    holder, acct, py = setup_funded_plan_year(
        account_type=account_type,
        coverage_tier=coverage_tier,
        year_end_policy=year_end_policy,
        tax_filing_status=tax_filing_status,
        birth_date=birth_date,
        calendar_year=calendar_year,
        contribution_cents=contribution_cents,
    )
    if eligible_account_types is None:
        eligible_account_types = [account_type]
    qe = seed_qualified_expense(
        category=expense_category,
        eligible_account_types=eligible_account_types,
    )
    service_date = iso_datetime_utc(calendar_year, 6, 15)
    claim = create_claim(
        account_holder=holder, account=acct,
        service_date=service_date,
        expense_code=qe["code"],
        amount_cents=claim_cents,
    )
    submit_claim(claim["id"], account_holder=holder)
    approve_claim(claim["id"])
    return holder, acct, py, qe, get_claim(claim["id"])


def setup_submitted_claim(
    *,
    account_type: str = "HSA",
    coverage_tier: Optional[str] = "SELF_ONLY",
    year_end_policy: str = "NONE",
    expense_category: str = "MEDICAL",
    eligible_account_types: Optional[List[str]] = None,
    calendar_year: int = 2025,
    contribution_cents: int = 100_000,
    claim_cents: int = 20_000,
    tax_filing_status: str = "SINGLE",
    requires_dependent: bool = False,
    dependent: Optional[Dict[str, Any]] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any],
           Dict[str, Any], Dict[str, Any]]:
    """Holder + account + plan year + contribution + expense + claim
    submitted (status SUBMITTED). Returns
    (holder, account, plan_year, qualified_expense, claim_after_submit).
    """
    holder, acct, py = setup_funded_plan_year(
        account_type=account_type,
        coverage_tier=coverage_tier,
        year_end_policy=year_end_policy,
        tax_filing_status=tax_filing_status,
        calendar_year=calendar_year,
        contribution_cents=contribution_cents,
    )
    if eligible_account_types is None:
        eligible_account_types = [account_type]
    qe = seed_qualified_expense(
        category=expense_category,
        eligible_account_types=eligible_account_types,
        requires_dependent=requires_dependent,
    )
    service_date = iso_datetime_utc(calendar_year, 6, 15)
    claim = create_claim(
        account_holder=holder, account=acct,
        service_date=service_date,
        expense_code=qe["code"],
        amount_cents=claim_cents,
        dependent_id=dependent["id"] if dependent else None,
    )
    submit_claim(claim["id"], account_holder=holder)
    return holder, acct, py, qe, get_claim(claim["id"])


# ===========================================================================
# Difficulty-design composite fixtures
# ===========================================================================
def setup_two_health_fsa_policy_variants(
    *,
    calendar_year: int = 2025,
    contribution_cents: int = 300_000,
    paid_claim_cents: int = 220_000,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any],
           Dict[str, Any], Dict[str, Any]]:
    """Mirror of difficulty instance
    forfeiture_grace_vs_carryover_health_fsa.

    Creates one AccountHolder with two HEALTH_FSA accounts:
      A1: year_end_policy=GRACE_PERIOD
      A2: year_end_policy=CARRYOVER
    Each gets a PlanYear for 2025 with $3,000 contribution and a
    qualified medical claim of $2,200 paid out.

    Returns (holder, account_grace, plan_year_grace, account_carryover,
             plan_year_carryover).
    """
    # Anchor clock early in the year so we can do later claim dates
    # in chronological order (clock is non-decreasing per PRD §2.7).
    advance_clock_to(iso_datetime_utc(calendar_year, 4, 2))
    holder = create_account_holder(birth_date="1980-01-01")
    a1 = open_account(
        holder, account_type="HEALTH_FSA", coverage_tier=None,
        year_end_policy="GRACE_PERIOD",
        account_holder_birth_date="1980-01-01",
    )
    a2 = open_account(
        holder, account_type="HEALTH_FSA", coverage_tier=None,
        year_end_policy="CARRYOVER",
        account_holder_birth_date="1980-01-01",
    )
    y1 = open_plan_year(a1["id"], calendar_year=calendar_year)
    y2 = open_plan_year(a2["id"], calendar_year=calendar_year)
    post_contribution(y1["id"], amount_cents=contribution_cents,
                      source="PAYROLL")
    post_contribution(y2["id"], amount_cents=contribution_cents,
                      source="PAYROLL")
    qe = seed_qualified_expense(
        category="MEDICAL",
        eligible_account_types=["HEALTH_FSA"],
        requires_dependent=False,
    )
    # First claim against a1 — service_date 4/1 is on or before the
    # clock (which is at 4/2 from the anchor above).
    c1 = create_claim(
        account_holder=holder, account=a1,
        service_date=iso_datetime_utc(calendar_year, 4, 1),
        expense_code=qe["code"], amount_cents=paid_claim_cents,
    )
    submit_claim(c1["id"], account_holder=holder)
    approve_claim(c1["id"])
    pay_claim(c1["id"])
    c2 = create_claim(
        account_holder=holder, account=a2,
        service_date=iso_datetime_utc(calendar_year, 4, 1),
        expense_code=qe["code"], amount_cents=paid_claim_cents,
    )
    submit_claim(c2["id"], account_holder=holder)
    approve_claim(c2["id"])
    pay_claim(c2["id"])
    y1_after = get_plan_year(a1["id"], y1["id"])
    y2_after = get_plan_year(a2["id"], y2["id"])
    return holder, a1, y1_after, a2, y2_after


def setup_hsa_non_qualified_for_chronological_tax_form(
    *,
    calendar_year: int = 2025,
    contribution_one_cents: int = 200_000,
    non_qual_claim_cents: int = 200_000,
    contribution_two_cents: int = 200_000,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Mirror of difficulty instance
    tax_basis_chronological_vs_forward_looking_hsa.

    Sequence:
      contribute 200_000 at t1 (enough to fund the non-qual claim)
      pay non-qualified claim 200_000 at t2 (with 20% HSA penalty)
      contribute 200_000 at t3
    Returns (holder, account, plan_year_after_all).

    PRD §3.5 enforces the pay-precondition that
    amount_cents <= available_balance — so t1 must fund t2 in full.
    """
    advance_clock_to(iso_datetime_utc(calendar_year, 1, 1))
    qe = seed_qualified_expense(
        category="NON_QUALIFIED",
        eligible_account_types=["HSA"],
        requires_dependent=False,
    )
    holder = create_account_holder(birth_date="1980-01-01",
                                   tax_filing_status="SINGLE")
    acct = open_account(
        holder, account_type="HSA", coverage_tier="SELF_ONLY",
        year_end_policy="NONE",
        account_holder_birth_date="1980-01-01",
    )
    py = open_plan_year(acct["id"], calendar_year=calendar_year)
    # t1: contribute first chunk
    advance_clock_to(iso_datetime_utc(calendar_year, 2, 1))
    post_contribution(py["id"], amount_cents=contribution_one_cents,
                      source="PAYROLL")
    # t2: non-qualified claim paid
    advance_clock_to(iso_datetime_utc(calendar_year, 3, 1))
    claim = create_claim(
        account_holder=holder, account=acct,
        service_date=iso_datetime_utc(calendar_year, 3, 1),
        expense_code=qe["code"], amount_cents=non_qual_claim_cents,
    )
    submit_claim(claim["id"], account_holder=holder)
    approve_claim(claim["id"])
    pay_claim(claim["id"])
    # t3: contribute second chunk (skip when zero so we don't hit
    # the PRD §3.3 amount_cents >= 1 validation).
    advance_clock_to(iso_datetime_utc(calendar_year, 4, 1))
    if contribution_two_cents > 0:
        post_contribution(py["id"], amount_cents=contribution_two_cents,
                          source="PAYROLL")
    return holder, acct, get_plan_year(acct["id"], py["id"])


def setup_health_fsa_grace_predecessor_with_successor(
    *,
    predecessor_year: int = 2025,
    successor_year: int = 2026,
    predecessor_contribution_cents: int = 100_000,
    successor_contribution_cents: int = 50_000,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any],
           Dict[str, Any], Dict[str, Any]]:
    """Mirror of plan_year_resolution_circular_year_routing instance.

    Creates HEALTH_FSA with GRACE_PERIOD policy, plan years for
    predecessor_year and successor_year. Year-end-closes the
    predecessor into GRACE_PERIOD via OpsRun.

    Returns (holder, account, predecessor_plan_year_in_GRACE,
             successor_plan_year_ACTIVE, qualified_expense).
    """
    advance_clock_to(iso_datetime_utc(predecessor_year, 6, 1))
    holder, acct = setup_holder_and_account(
        account_type="HEALTH_FSA", coverage_tier=None,
        year_end_policy="GRACE_PERIOD", birth_date="1980-01-01",
    )
    y_pred = open_plan_year(acct["id"], calendar_year=predecessor_year)
    post_contribution(y_pred["id"],
                      amount_cents=predecessor_contribution_cents,
                      source="PAYROLL")
    qe = seed_qualified_expense(
        category="MEDICAL",
        eligible_account_types=["HEALTH_FSA"],
        requires_dependent=False,
    )
    # Year-end close pred -> GRACE_PERIOD.
    advance_clock_to(iso_datetime_utc(successor_year, 1, 2))
    post_ops_run(
        kind="YEAR_END_CLOSE",
        as_of_date=iso_datetime_utc(successor_year, 1, 2),
    )
    y_succ = open_plan_year(acct["id"], calendar_year=successor_year)
    post_contribution(y_succ["id"],
                      amount_cents=successor_contribution_cents,
                      source="PAYROLL")
    return (
        holder, acct,
        get_plan_year(acct["id"], y_pred["id"]),
        get_plan_year(acct["id"], y_succ["id"]),
        qe,
    )


def setup_carryover_chain_with_successor(
    *,
    predecessor_year: int = 2025,
    successor_year: int = 2026,
    contribution_cents: int = 100_000,
    pay_claim_cents: int = 20_000,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any],
           Dict[str, Any]]:
    """Mirror of year_end_close_to_carryover_to_successor instance.

    HEALTH_FSA with year_end_policy=CARRYOVER. Open Y2025, contribute
    $1,000, pay $200 qualified, leftover $800. Year-end close moves
    Y2025 to CARRYOVER_PENDING. Successor Y2026 opened triggers
    transfer of min($800, $640) = $640 to successor.carryover_in_cents.

    Returns (holder, account, predecessor_after_close,
             successor_after_creation).
    """
    # Anchor late in predecessor_year so the service_date 6/15 is past.
    advance_clock_to(iso_datetime_utc(predecessor_year, 12, 1))
    holder, acct = setup_holder_and_account(
        account_type="HEALTH_FSA", coverage_tier=None,
        year_end_policy="CARRYOVER", birth_date="1980-01-01",
    )
    y_pred = open_plan_year(acct["id"], calendar_year=predecessor_year)
    post_contribution(y_pred["id"], amount_cents=contribution_cents,
                      source="PAYROLL")
    qe = seed_qualified_expense(
        category="MEDICAL",
        eligible_account_types=["HEALTH_FSA"],
        requires_dependent=False,
    )
    # Pay a claim of $200 to make leftover $800.
    c = create_claim(
        account_holder=holder, account=acct,
        service_date=iso_datetime_utc(predecessor_year, 6, 15),
        expense_code=qe["code"], amount_cents=pay_claim_cents,
    )
    submit_claim(c["id"], account_holder=holder)
    approve_claim(c["id"])
    pay_claim(c["id"])
    # Year-end close: Y_pred -> CARRYOVER_PENDING.
    advance_clock_to(iso_datetime_utc(successor_year, 1, 2))
    post_ops_run(
        kind="YEAR_END_CLOSE",
        as_of_date=iso_datetime_utc(successor_year, 1, 2),
    )
    # Open successor — triggers carryover transfer + predecessor close.
    y_succ = open_plan_year(acct["id"], calendar_year=successor_year)
    # Advance clock late into the successor year so subsequent test
    # bodies can issue claims with mid-year service_dates.
    advance_clock_to(iso_datetime_utc(successor_year, 12, 1))
    return (
        holder, acct,
        get_plan_year(acct["id"], y_pred["id"]),
        get_plan_year(acct["id"], y_succ["id"]),
    )


def setup_dcfsa_with_inactive_dependent_at_submit_time(
    *,
    calendar_year: int = 2025,
    contribution_cents: int = 100_000,
    claim_cents: int = 10_000,
    tax_filing_status: str = "SINGLE",
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any],
           Dict[str, Any], Dict[str, Any]]:
    """Setup a DCFSA account with a Dependent that is created ACTIVE,
    used to create a DRAFT claim, then deactivated before /submit.

    Returns (holder, account, plan_year, dependent_now_inactive, claim_in_draft).
    """
    holder, acct, py = setup_funded_plan_year(
        account_type="DEPENDENT_CARE_FSA",
        coverage_tier=None,
        year_end_policy="NONE",
        tax_filing_status=tax_filing_status,
        calendar_year=calendar_year,
        contribution_cents=contribution_cents,
    )
    dep = create_dependent(
        account_holder=holder, relationship="CHILD",
        birth_date="2015-01-01",
    )
    qe = seed_qualified_expense(
        category="DEPENDENT_CARE",
        eligible_account_types=["DEPENDENT_CARE_FSA"],
        requires_dependent=True,
    )
    service_date = iso_datetime_utc(calendar_year, 6, 15)
    claim = create_claim(
        account_holder=holder, account=acct,
        service_date=service_date,
        expense_code=qe["code"],
        amount_cents=claim_cents,
        dependent_id=dep["id"],
    )
    # Deactivate dependent BEFORE the test issues /submit. The
    # response of deactivate_dependent is the updated Dependent row.
    dep_after = deactivate_dependent(dep["id"])
    return holder, acct, py, dep_after, claim


def setup_health_fsa_grace_one_day_past(
    *,
    predecessor_year: int = 2025,
    successor_year: int = 2026,
    contribution_cents: int = 100_000,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any],
           Dict[str, Any]]:
    """Setup for grace_period_service_date_inclusive_boundary instance.

    HEALTH_FSA with GRACE_PERIOD, PlanYear predecessor_year with
    $1,000 contribution, NO successor PlanYear. Year-end-closes pred
    into GRACE_PERIOD via OpsRun. Advances clock to YYYY-03-20 so the
    boundary tests can pick service_date = YYYY-03-15 (inclusive) and
    YYYY-03-16 (one day past).

    Returns (holder, account, predecessor_in_GRACE, qualified_expense).
    """
    advance_clock_to(iso_datetime_utc(predecessor_year, 6, 1))
    holder, acct = setup_holder_and_account(
        account_type="HEALTH_FSA", coverage_tier=None,
        year_end_policy="GRACE_PERIOD",
        birth_date="1980-01-01",
    )
    y_pred = open_plan_year(acct["id"], calendar_year=predecessor_year)
    post_contribution(y_pred["id"], amount_cents=contribution_cents,
                      source="PAYROLL")
    qe = seed_qualified_expense(
        category="MEDICAL",
        eligible_account_types=["HEALTH_FSA"],
        requires_dependent=False,
    )
    # Year-end close pred -> GRACE_PERIOD.
    advance_clock_to(iso_datetime_utc(successor_year, 1, 2))
    post_ops_run(
        kind="YEAR_END_CLOSE",
        as_of_date=iso_datetime_utc(successor_year, 1, 2),
    )
    # Roll clock to just past the grace boundary so both service_date
    # candidates (03-15 and 03-16) are not future-dated.
    advance_clock_to(iso_datetime_utc(successor_year, 3, 20))
    return holder, acct, get_plan_year(acct["id"], y_pred["id"]), qe


def setup_hsa_self_only_at_cap_boundary(
    *,
    calendar_year: int = 2025,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Setup an HSA SELF_ONLY account (cap 412,500) with no contributions
    yet. Used for the contribution-cap exact-limit boundary test."""
    holder, acct, py = setup_active_plan_year(
        account_type="HSA",
        coverage_tier="SELF_ONLY",
        year_end_policy="NONE",
        tax_filing_status="SINGLE",
        birth_date="1980-01-01",
        calendar_year=calendar_year,
    )
    return holder, acct, py


def setup_two_health_fsa_carryover_balance_test(
    *,
    predecessor_year: int = 2025,
    successor_year: int = 2026,
    pred_contribution_cents: int = 100_000,
    pred_pay_claim_cents: int = 20_000,
    succ_contribution_cents: int = 100_000,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any],
           Dict[str, Any], Dict[str, Any]]:
    """Setup for claim_pay_then_reverse_preserves_carryover_consumed_invariant.

    Builds a HEALTH_FSA CARRYOVER chain where the successor PlanYear
    Y2026 starts with carryover_in_cents = 50_000 and contributions
    of $1,000, then we add the second contribution; we leave the
    actual pay/reverse to the test body so the test can capture
    before/after counter snapshots cleanly.

    Returns (holder, account, predecessor_after_close,
             successor_funded, qualified_expense).
    """
    holder, acct, pred, succ, qe = setup_health_fsa_carryover_full_chain(
        predecessor_year=predecessor_year,
        successor_year=successor_year,
        pred_contribution_cents=pred_contribution_cents,
        pred_pay_claim_cents=pred_pay_claim_cents,
    )
    # Add additional current-year contribution on top of carryover.
    if succ_contribution_cents > 0:
        post_contribution(succ["id"],
                          amount_cents=succ_contribution_cents,
                          source="PAYROLL")
    succ_fresh = get_plan_year(acct["id"], succ["id"])
    return holder, acct, pred, succ_fresh, qe


def setup_health_fsa_carryover_full_chain(
    *,
    predecessor_year: int = 2025,
    successor_year: int = 2026,
    pred_contribution_cents: int = 100_000,
    pred_pay_claim_cents: int = 20_000,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any],
           Dict[str, Any], Dict[str, Any]]:
    """Same as setup_carryover_chain_with_successor but also returns
    the seeded QualifiedExpense so tests can submit fresh claims
    against the successor without re-seeding."""
    advance_clock_to(iso_datetime_utc(predecessor_year, 12, 1))
    holder, acct = setup_holder_and_account(
        account_type="HEALTH_FSA", coverage_tier=None,
        year_end_policy="CARRYOVER", birth_date="1980-01-01",
    )
    y_pred = open_plan_year(acct["id"], calendar_year=predecessor_year)
    post_contribution(y_pred["id"], amount_cents=pred_contribution_cents,
                      source="PAYROLL")
    qe = seed_qualified_expense(
        category="MEDICAL",
        eligible_account_types=["HEALTH_FSA"],
        requires_dependent=False,
    )
    c = create_claim(
        account_holder=holder, account=acct,
        service_date=iso_datetime_utc(predecessor_year, 6, 15),
        expense_code=qe["code"], amount_cents=pred_pay_claim_cents,
    )
    submit_claim(c["id"], account_holder=holder)
    approve_claim(c["id"])
    pay_claim(c["id"])
    advance_clock_to(iso_datetime_utc(successor_year, 1, 2))
    post_ops_run(
        kind="YEAR_END_CLOSE",
        as_of_date=iso_datetime_utc(successor_year, 1, 2),
    )
    y_succ = open_plan_year(acct["id"], calendar_year=successor_year)
    # Advance the clock late into the successor year so tests can issue
    # claims against the successor year with mid-year service dates
    # (PRD §3.5: service_date must be <= clock).
    advance_clock_to(iso_datetime_utc(successor_year, 12, 1))
    return (
        holder, acct,
        get_plan_year(acct["id"], y_pred["id"]),
        get_plan_year(acct["id"], y_succ["id"]),
        qe,
    )


__all__ = [
    "get_clock_state",
    "advance_clock_to",
    "advance_clock_to_date",
    "create_account_holder",
    "create_dependent",
    "deactivate_dependent",
    "open_account",
    "get_account",
    "freeze_account",
    "unfreeze_account",
    "close_account",
    "open_plan_year",
    "get_plan_year",
    "post_contribution",
    "reverse_contribution",
    "seed_qualified_expense",
    "create_claim",
    "submit_claim",
    "approve_claim",
    "pay_claim",
    "deny_claim",
    "reverse_claim",
    "get_claim",
    "post_ops_run",
    "list_audit_events",
    "setup_holder_and_account",
    "setup_active_plan_year",
    "setup_funded_plan_year",
    "setup_paid_claim",
    "setup_approved_claim",
    "setup_submitted_claim",
    "setup_two_health_fsa_policy_variants",
    "setup_hsa_non_qualified_for_chronological_tax_form",
    "setup_health_fsa_grace_predecessor_with_successor",
    "setup_carryover_chain_with_successor",
    "setup_dcfsa_with_inactive_dependent_at_submit_time",
    "setup_health_fsa_grace_one_day_past",
    "setup_hsa_self_only_at_cap_boundary",
    "setup_health_fsa_carryover_full_chain",
    "setup_two_health_fsa_carryover_balance_test",
]
