"""Composite setup helpers — multi-step preambles tests can reuse.

The 529 pipeline is long: state rule → donor → beneficiary → account
open → contribution create → contribution settle → withdrawal create →
withdrawal disburse → education-expense attach → withdrawal classify →
tax-report create → tax-report finalize. Many test claims need the
system in a late-pipeline state.

IDENTITY THREADING — PRD §2.1:

- Donor is ENTITY-BACKED. Every ownership-gated Donor call (open
  account, close account, contribute, create/pause/resume/cancel
  recurring plan, request/disburse/classify withdrawal, attach
  expenses, submit beneficiary change) MUST mint headers via
  make_donor_headers(donor["id"]) — never via the shared
  DONOR_FALLBACK_ID constant.

- Beneficiary is ENTITY-BACKED. The read-only views available to a
  beneficiary are restricted to accounts whose beneficiary_id equals
  X-User-ID, so any beneficiary call MUST use
  make_beneficiary_headers(beneficiary["id"]).

- PlanAdministrator is OPAQUE — the shared admin_headers constant is
  the canonical form for every administrator-only call.

Setup calls use get_success_data (a lenient 2xx validator), so a
failed setup surfaces as "Setup failed" rather than a confusing test
assertion failure downstream.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    CADENCE_MONTHLY_DAYS,
    SECONDS_PER_DAY,
    TEST_DEFAULTS,
)
from .factories import (
    attach_education_expense_payload,
    clock_advance_payload,
    create_account_payload,
    create_beneficiary_change_request_payload,
    create_beneficiary_payload,
    create_contribution_payload,
    create_donor_payload,
    create_recurring_plan_payload,
    create_state_rule_payload,
    create_tax_report_payload,
    create_withdrawal_payload,
    date_in_year,
    iso_offset,
    iso_utc,
    random_suffix,
    utcnow,
)
from .test_users import (
    TEST_USERS,
    make_beneficiary_headers,
    make_donor_headers,
)


# ===========================================================================
# Clock helpers — PRD §3.8 (PlanAdministrator only)
# ===========================================================================
def advance_clock_to(to_iso8601: str,
                     headers: Optional[Dict[str, str]] = None
                     ) -> Dict[str, Any]:
    """POST /_clock/advance with the supplied ISO 8601 instant.
    PRD §3.8: PlanAdministrator only.
    """
    headers = headers or TEST_USERS["admin_headers"]
    resp = api_client.clock_advance(
        clock_advance_payload(to_iso8601=to_iso8601), headers,
    )
    return get_success_data(resp)


def server_now_iso(headers: Optional[Dict[str, str]] = None) -> str:
    """Return the server's current logical-clock time as ISO 8601.

    PRD §2.2: every response meta carries `api_request_timestamp`
    set to the server's logical clock. We invoke a cheap, side-effect-
    free GET to read it out. The list_state_rules call is permitted to
    both Donor and PlanAdministrator and never mutates state.
    """
    headers = headers or TEST_USERS["admin_headers"]
    resp = api_client.list_state_rules(headers, params={"limit": 1})
    body = resp.json()
    return body["meta"]["api_request_timestamp"]


def server_now_date(headers: Optional[Dict[str, str]] = None) -> str:
    """Return the server's current logical-clock date as ISO 8601
    YYYY-MM-DD. Helper for incurred_on defaults so tests stay aligned
    with the server clock (which the test harness drives via
    /_clock/advance) rather than wall-clock.
    """
    iso = server_now_iso(headers)
    return iso[:10]


# ===========================================================================
# Tier 1: State rule, donor, beneficiary
# ===========================================================================
def create_state_rule(
    *,
    state_code: Optional[str] = None,
    deduction_cap_cents: int = TEST_DEFAULTS["DEDUCTION_CAP_CENTS"],
    parity: str = "PARITY",
    lifetime_aggregate_cap_cents: int = TEST_DEFAULTS[
        "LIFETIME_AGGREGATE_CAP_CENTS"
    ],
    k12_qualified: bool = True,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /state-rules — PlanAdministrator only per PRD §3.1.

    `state_code` defaults to a random two-letter combination so multiple
    fixtures can run concurrently without colliding on the state_code
    unique constraint. Pass an explicit code (e.g., "NY") when the
    state code must match a donor's state_of_residence.
    """
    headers = headers or TEST_USERS["admin_headers"]
    if state_code is None:
        suffix = random_suffix(2)
        state_code = suffix
    resp = api_client.create_state_rule(
        create_state_rule_payload(
            state_code=state_code,
            deduction_cap_cents=deduction_cap_cents,
            parity=parity,
            lifetime_aggregate_cap_cents=lifetime_aggregate_cap_cents,
            k12_qualified=k12_qualified,
        ),
        headers,
    )
    return get_success_data(resp)


def create_donor(
    *,
    state_of_residence: str = "NY",
    full_name: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /donors — PlanAdministrator only per PRD §3.1."""
    headers = headers or TEST_USERS["admin_headers"]
    resp = api_client.create_donor(
        create_donor_payload(
            state_of_residence=state_of_residence,
            full_name=full_name,
        ),
        headers,
    )
    return get_success_data(resp)


def create_beneficiary(
    *,
    relationship_family_code: str = "CHILD",
    date_of_birth: Optional[str] = None,
    full_name: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /beneficiaries — Donor or PlanAdministrator per PRD §3.1.

    Defaults to PlanAdministrator-minted headers, which is allowed and
    keeps fixtures simple.
    """
    headers = headers or TEST_USERS["admin_headers"]
    resp = api_client.create_beneficiary(
        create_beneficiary_payload(
            relationship_family_code=relationship_family_code,
            date_of_birth=date_of_birth,
            full_name=full_name,
        ),
        headers,
    )
    return get_success_data(resp)


def ensure_state_rule(state_code: str,
                      headers: Optional[Dict[str, str]] = None,
                      **overrides: Any) -> Dict[str, Any]:
    """Create a state rule for an explicit two-letter code only if it
    does not already exist. PRD §3.1: replacing a state rule is allowed
    and increments version, so unconditional re-creation is safe in
    PRD terms — this helper just avoids the extra version bump when
    tests do not need it.
    """
    headers = headers or TEST_USERS["admin_headers"]
    get_resp = api_client.get_state_rule(state_code, headers)
    if get_resp.status_code == 200:
        return get_resp.json()["data"]
    return create_state_rule(
        state_code=state_code, headers=headers, **overrides,
    )


# ===========================================================================
# Tier 2: Account opening
# ===========================================================================
def open_account(
    *,
    donor: Dict[str, Any],
    beneficiary: Dict[str, Any],
    state_plan_code: str = "NY",
    ensure_plan_rule: bool = True,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /accounts — Donor-only per PRD §3.2.

    `ensure_plan_rule` will create a permissive StateRule for
    `state_plan_code` if one does not already exist. Note that
    Account.lifetime_contribution_cap_cents is pinned at open from the
    rule's lifetime_aggregate_cap_cents (PRD §3.2).

    Identity threading: PRD §2.1 — Donor is entity-backed, so the
    acting donor's id IS the X-User-ID. We mint per-instance headers
    here via make_donor_headers.
    """
    if ensure_plan_rule:
        ensure_state_rule(state_plan_code)
    headers = headers or make_donor_headers(donor["id"])
    resp = api_client.create_account(
        create_account_payload(
            primary_donor_id=donor["id"],
            beneficiary_id=beneficiary["id"],
            state_plan_code=state_plan_code,
        ),
        headers,
    )
    return get_success_data(resp)


def setup_donor_beneficiary_account(
    *,
    donor_state: str = "NY",
    plan_state: str = "NY",
    parity: str = "PARITY",
    deduction_cap_cents: int = TEST_DEFAULTS["DEDUCTION_CAP_CENTS"],
    lifetime_aggregate_cap_cents: int = TEST_DEFAULTS[
        "LIFETIME_AGGREGATE_CAP_CENTS"
    ],
    k12_qualified: bool = True,
    relationship_family_code: str = "CHILD",
    beneficiary_dob: Optional[str] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Bundle: ensure StateRule for plan_state and donor_state, mint a
    donor in donor_state, mint a beneficiary, and open an OPEN account
    in plan_state.

    Returns (donor, beneficiary, account).
    """
    ensure_state_rule(
        donor_state,
        deduction_cap_cents=deduction_cap_cents,
        parity=parity,
        lifetime_aggregate_cap_cents=lifetime_aggregate_cap_cents,
        k12_qualified=k12_qualified,
    )
    if plan_state != donor_state:
        ensure_state_rule(
            plan_state,
            deduction_cap_cents=deduction_cap_cents,
            parity=parity,
            lifetime_aggregate_cap_cents=lifetime_aggregate_cap_cents,
            k12_qualified=k12_qualified,
        )
    donor = create_donor(state_of_residence=donor_state)
    beneficiary = create_beneficiary(
        relationship_family_code=relationship_family_code,
        date_of_birth=beneficiary_dob,
    )
    account = open_account(
        donor=donor, beneficiary=beneficiary,
        state_plan_code=plan_state,
        ensure_plan_rule=False,
    )
    return donor, beneficiary, account


# ===========================================================================
# Tier 3: Contribution lifecycle
# ===========================================================================
def create_pending_contribution(
    *,
    account: Dict[str, Any],
    donor: Dict[str, Any],
    amount_cents: int = 100_000,
    contribution_kind: str = "LUMP_SUM",
    recurring_plan_id: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /accounts/{id}/contributions — Donor only per PRD §3.3.

    Identity threading: the caller is the acting donor. Tests of
    third-party contributions can override `headers` and `donor` so the
    payload's donor_id differs from the account's primary_donor_id.
    """
    # The acting role per PRD §4 is `Donor`. For first-party
    # contributions (the common case), the donor is also the account
    # owner; we use that identity.
    headers = headers or make_donor_headers(account["primary_donor_id"])
    resp = api_client.create_contribution(
        account["id"],
        create_contribution_payload(
            donor_id=donor["id"],
            amount_cents=amount_cents,
            contribution_kind=contribution_kind,
            recurring_plan_id=recurring_plan_id,
        ),
        headers,
    )
    return get_success_data(resp)


def settle_contribution(contribution_id: str,
                        headers: Optional[Dict[str, str]] = None
                        ) -> Dict[str, Any]:
    """POST /contributions/{id}/settle — PlanAdministrator only per
    PRD §3.3."""
    headers = headers or TEST_USERS["admin_headers"]
    return get_success_data(
        api_client.settle_contribution(contribution_id, headers),
    )


def settle_lump_sum(
    *,
    account: Dict[str, Any],
    donor: Dict[str, Any],
    amount_cents: int = 100_000,
) -> Dict[str, Any]:
    """Create a PENDING lump-sum contribution and immediately settle it.
    Returns the SETTLED Contribution.
    """
    pending = create_pending_contribution(
        account=account, donor=donor, amount_cents=amount_cents,
    )
    return settle_contribution(pending["id"])


def top_up_account(
    *,
    account: Dict[str, Any],
    amount_cents: int,
    donor_state: str = "NY",
) -> Dict[str, Any]:
    """Add `amount_cents` to the account's balance using a fresh
    third-party donor — PRD §3.3 explicitly permits third-party gifts so
    each top-up call uses a brand-new donor that has not yet contributed
    in the calendar year. Splits the amount into 1,500,000-cent chunks
    each backed by its own fresh donor to stay under the annual gift
    exclusion (1,800,000 cents per donor per year).
    """
    GIFT_EX = 1_800_000
    chunk = 1_500_000
    remaining = amount_cents
    while remaining > 0:
        take = min(chunk, remaining, GIFT_EX)
        fresh = create_donor(state_of_residence=donor_state)
        settle_lump_sum(account=account, donor=fresh, amount_cents=take)
        remaining -= take
    # Re-read the account to obtain updated balances.
    refreshed = get_success_data(
        api_client.get_account(
            account["id"],
            make_donor_headers(account["primary_donor_id"]),
        ),
    )
    return refreshed


def setup_account_with_balance(
    *,
    target_total_cents: int,
    donor_state: str = "NY",
    plan_state: str = "NY",
    parity: str = "PARITY",
    deduction_cap_cents: int = TEST_DEFAULTS["DEDUCTION_CAP_CENTS"],
    lifetime_aggregate_cap_cents: int = TEST_DEFAULTS[
        "LIFETIME_AGGREGATE_CAP_CENTS"
    ],
    k12_qualified: bool = True,
    relationship_family_code: str = "CHILD",
    contributions_split: Optional[List[int]] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """End-to-end bundle: donor + beneficiary + open account, then
    settle one or more contributions to drive Account.total_balance_cents
    up to `target_total_cents`.

    The contributions are sized so no single contribution trips the IRS
    annual gift exclusion (1,800,000 cents per PRD §3.3). Use
    `contributions_split` to control exact sizing for boundary tests.

    Returns (donor, beneficiary, account).

    NOTE on basis vs. earnings: every contribution increases
    basis_balance_cents (PRD §3.3 state machine side effects). The PRD
    does not specify a market-growth mechanism — there is no way to
    drive earnings_balance_cents > 0 through PRD endpoints. So after
    this setup, basis == total and earnings == 0.
    """
    donor, beneficiary, account = setup_donor_beneficiary_account(
        donor_state=donor_state, plan_state=plan_state, parity=parity,
        deduction_cap_cents=deduction_cap_cents,
        lifetime_aggregate_cap_cents=lifetime_aggregate_cap_cents,
        k12_qualified=k12_qualified,
        relationship_family_code=relationship_family_code,
    )
    if contributions_split is None:
        # Split into contributions of at most 1,500,000 cents each so we
        # stay below the 1,800,000-cent annual gift exclusion (PRD §3.3).
        if target_total_cents > 0:
            chunk = 1_500_000
            contributions_split = []
            remaining = target_total_cents
            while remaining > 0:
                take = min(chunk, remaining)
                contributions_split.append(take)
                remaining -= take
        else:
            contributions_split = []
    # Use multiple donors when the sum of contributions for the primary
    # donor would exceed the IRS annual gift exclusion (PRD §3.3:
    # 1,800,000 cents per donor per calendar year). PRD §3.3 explicitly
    # permits third-party donors. We accumulate against the primary donor
    # first, then mint fresh third-party donors as needed.
    GIFT_EX = 1_800_000
    used_for_primary = 0
    for amt in contributions_split:
        if used_for_primary + amt <= GIFT_EX:
            settle_lump_sum(account=account, donor=donor, amount_cents=amt)
            used_for_primary += amt
        else:
            third_party = create_donor(state_of_residence=donor_state)
            settle_lump_sum(
                account=account, donor=third_party, amount_cents=amt,
            )
    # Re-read the account after the settlements to obtain fresh
    # computed balances and version.
    refreshed = get_success_data(
        api_client.get_account(account["id"], make_donor_headers(donor["id"])),
    )
    return donor, beneficiary, refreshed


# ===========================================================================
# Tier 4: Withdrawal lifecycle (create → disburse → expenses → classify)
# ===========================================================================
def create_withdrawal(
    *,
    account: Dict[str, Any],
    requested_amount_cents: int,
    expense_category: str = "POST_SECONDARY_TUITION",
    donor_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /accounts/{id}/withdrawals — Donor only per PRD §3.5."""
    headers = donor_headers or make_donor_headers(
        account["primary_donor_id"],
    )
    resp = api_client.create_withdrawal(
        account["id"],
        create_withdrawal_payload(
            requested_amount_cents=requested_amount_cents,
            expense_category=expense_category,
        ),
        headers,
    )
    return get_success_data(resp)


def disburse_withdrawal(
    withdrawal: Dict[str, Any],
    *,
    account: Dict[str, Any],
    donor_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /withdrawals/{id}/disburse — Donor only per PRD §3.5."""
    headers = donor_headers or make_donor_headers(
        account["primary_donor_id"],
    )
    return get_success_data(
        api_client.disburse_withdrawal(withdrawal["id"], headers),
    )


def attach_expense(
    withdrawal: Dict[str, Any],
    *,
    account: Dict[str, Any],
    amount_cents: int,
    category: str,
    incurred_on: Optional[str] = None,
    institution_name: Optional[str] = None,
    donor_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /withdrawals/{id}/expenses — Donor only per PRD §3.5.

    `incurred_on` defaults to a date in the withdrawal's disbursement
    year (PRD §3.5 requires incurred_on to fall in the same calendar
    year as the disbursement, UTC). Tests that span calendar-year
    boundaries should pass an explicit date.
    """
    headers = donor_headers or make_donor_headers(
        account["primary_donor_id"],
    )
    if incurred_on is None:
        # Default to server-clock date — the test harness drives the
        # server's logical clock via /_clock/advance, so wall-clock today
        # may diverge from the disbursement year. PRD §3.5 requires
        # incurred_on to match the disbursement year (UTC).
        incurred_on = server_now_date(headers)
    resp = api_client.attach_education_expense(
        withdrawal["id"],
        attach_education_expense_payload(
            institution_name=institution_name,
            category=category,
            amount_cents=amount_cents,
            incurred_on=incurred_on,
        ),
        headers,
    )
    return get_success_data(resp)


def classify_withdrawal(
    withdrawal: Dict[str, Any],
    *,
    account: Dict[str, Any],
    donor_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /withdrawals/{id}/classify — Donor only per PRD §3.5."""
    headers = donor_headers or make_donor_headers(
        account["primary_donor_id"],
    )
    return get_success_data(
        api_client.classify_withdrawal(withdrawal["id"], headers),
    )


def withdraw_and_classify(
    *,
    account: Dict[str, Any],
    requested_amount_cents: int,
    expense_category: str,
    receipt_amount_cents: Optional[int] = None,
    receipt_incurred_on: Optional[str] = None,
) -> Dict[str, Any]:
    """End-to-end Withdrawal: create REQUESTED → disburse → attach
    receipt (when expense_category != NON_QUALIFIED) → classify.

    Returns the CLASSIFIED Withdrawal.
    """
    w = create_withdrawal(
        account=account,
        requested_amount_cents=requested_amount_cents,
        expense_category=expense_category,
    )
    disburse_withdrawal(w, account=account)
    if expense_category != "NON_QUALIFIED":
        recv_amt = (
            receipt_amount_cents
            if receipt_amount_cents is not None
            else requested_amount_cents
        )
        attach_expense(
            w, account=account,
            amount_cents=recv_amt,
            category=expense_category,
            incurred_on=receipt_incurred_on,
        )
    return classify_withdrawal(w, account=account)


# ===========================================================================
# Tier 5: K-12 cap accumulation (target Beneficiary.k12_ytd_qualified_cents)
# ===========================================================================
def accumulate_k12_qualified(
    *,
    beneficiary: Dict[str, Any],
    target_cents: int,
    donor_state: str = "NY",
    plan_state: str = "NY",
) -> Dict[str, Any]:
    """Drive `Beneficiary.k12_ytd_qualified_cents` up to `target_cents`
    by creating one or more K-12 withdrawals on a dedicated account for
    this beneficiary, then classifying them with matching receipts.

    PRD §3.5: the federal K-12 cap is per beneficiary per calendar
    year, applied cumulatively across every account whose
    beneficiary_id is this beneficiary. So a sibling account works
    here.

    Returns the up-to-date beneficiary row after accumulation.
    """
    if target_cents <= 0:
        return beneficiary
    # Open a dedicated account with sufficient balance + cap.
    donor = create_donor(state_of_residence=donor_state)
    ensure_state_rule(
        plan_state,
        deduction_cap_cents=TEST_DEFAULTS["DEDUCTION_CAP_CENTS"],
        parity="PARITY",
        lifetime_aggregate_cap_cents=TEST_DEFAULTS[
            "LIFETIME_AGGREGATE_CAP_CENTS"
        ],
        k12_qualified=True,
    )
    account = open_account(
        donor=donor, beneficiary=beneficiary,
        state_plan_code=plan_state, ensure_plan_rule=False,
    )
    # Seed the account with enough basis to cover the target.
    # Use small contributions to stay under the gift exclusion.
    chunk = 1_500_000
    funded = 0
    while funded < target_cents:
        take = min(chunk, target_cents - funded)
        if take <= 0:
            break
        settle_lump_sum(
            account=account, donor=donor, amount_cents=max(take, 1),
        )
        funded += take
    # Re-read the account to get the current total_balance_cents.
    account = get_success_data(
        api_client.get_account(
            account["id"], make_donor_headers(donor["id"]),
        ),
    )
    # Create K-12 withdrawals totaling `target_cents`.
    # PRD §3.5: per-classify, K-12 qualified is bounded by
    # min(requested, receipts_total, cap_room). To accumulate cleanly,
    # we issue per-withdrawal amounts strictly within remaining cap room
    # (so cap_room is never the binding constraint here).
    remaining = target_cents
    # Use a single withdrawal up to remaining; if that exceeds account
    # balance, split.
    available = account["total_balance_cents"]
    per_w = min(remaining, available)
    if per_w <= 0:
        return beneficiary
    w = withdraw_and_classify(
        account=account,
        requested_amount_cents=per_w,
        expense_category="K_12",
        receipt_amount_cents=per_w,
    )
    # Re-read beneficiary.
    refreshed = get_success_data(
        api_client.get_beneficiary(
            beneficiary["id"], TEST_USERS["admin_headers"],
        ),
    )
    return refreshed


# ===========================================================================
# Tier 6: Recurring plan setup
# ===========================================================================
def create_recurring_plan(
    *,
    account: Dict[str, Any],
    donor: Dict[str, Any],
    amount_cents: int = 50_000,
    cadence_days: int = CADENCE_MONTHLY_DAYS,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /accounts/{id}/recurring-plans — Donor only per PRD §3.3."""
    headers = headers or make_donor_headers(donor["id"])
    resp = api_client.create_recurring_plan(
        account["id"],
        create_recurring_plan_payload(
            donor_id=donor["id"],
            amount_cents=amount_cents,
            cadence_days=cadence_days,
        ),
        headers,
    )
    return get_success_data(resp)


# ===========================================================================
# Tier 7: TaxReport
# ===========================================================================
def create_tax_report(
    *,
    account: Dict[str, Any],
    tax_year: int,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /tax-reports — PlanAdministrator only per PRD §3.7."""
    headers = headers or TEST_USERS["admin_headers"]
    resp = api_client.create_tax_report(
        create_tax_report_payload(
            account_id=account["id"], tax_year=tax_year,
        ),
        headers,
    )
    return get_success_data(resp)


def finalize_tax_report(report_id: str,
                        headers: Optional[Dict[str, str]] = None,
                        ) -> Dict[str, Any]:
    """POST /tax-reports/{id}/finalize — PlanAdministrator only per
    PRD §3.7."""
    headers = headers or TEST_USERS["admin_headers"]
    return get_success_data(
        api_client.finalize_tax_report(report_id, headers),
    )


# ===========================================================================
# Tier 8: BeneficiaryChangeRequest
# ===========================================================================
def submit_beneficiary_change(
    *,
    account: Dict[str, Any],
    proposed_beneficiary: Dict[str, Any],
    donor_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /accounts/{id}/beneficiary-change-requests — Donor only per
    PRD §3.6."""
    headers = donor_headers or make_donor_headers(
        account["primary_donor_id"],
    )
    resp = api_client.create_beneficiary_change_request(
        account["id"],
        create_beneficiary_change_request_payload(
            proposed_beneficiary_id=proposed_beneficiary["id"],
        ),
        headers,
    )
    return get_success_data(resp)


def approve_beneficiary_change(request_id: str,
                               headers: Optional[Dict[str, str]] = None,
                               ) -> Dict[str, Any]:
    """POST /beneficiary-change-requests/{id}/approve — PlanAdministrator
    only per PRD §3.6."""
    headers = headers or TEST_USERS["admin_headers"]
    return get_success_data(
        api_client.approve_beneficiary_change_request(request_id, headers),
    )


# ===========================================================================
# Tier 9: Account restriction / closure
# ===========================================================================
def restrict_account(account_id: str,
                     headers: Optional[Dict[str, str]] = None,
                     ) -> Dict[str, Any]:
    """POST /accounts/{id}/restrict — PlanAdministrator only per
    PRD §3.2."""
    headers = headers or TEST_USERS["admin_headers"]
    return get_success_data(
        api_client.restrict_account(account_id, headers),
    )


def release_account(account_id: str,
                    headers: Optional[Dict[str, str]] = None,
                    ) -> Dict[str, Any]:
    """POST /accounts/{id}/release — PlanAdministrator only per
    PRD §3.2."""
    headers = headers or TEST_USERS["admin_headers"]
    return get_success_data(
        api_client.release_account(account_id, headers),
    )


__all__ = [
    "advance_clock_to",
    "server_now_iso",
    "server_now_date",
    "create_state_rule",
    "ensure_state_rule",
    "create_donor",
    "create_beneficiary",
    "open_account",
    "setup_donor_beneficiary_account",
    "create_pending_contribution",
    "settle_contribution",
    "settle_lump_sum",
    "top_up_account",
    "setup_account_with_balance",
    "create_withdrawal",
    "disburse_withdrawal",
    "attach_expense",
    "classify_withdrawal",
    "withdraw_and_classify",
    "accumulate_k12_qualified",
    "create_recurring_plan",
    "create_tax_report",
    "finalize_tax_report",
    "submit_beneficiary_change",
    "approve_beneficiary_change",
    "restrict_account",
    "release_account",
]
