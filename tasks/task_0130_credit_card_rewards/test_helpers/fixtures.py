"""Composite setup helpers — multi-step preambles tests can reuse.

The credit-card-rewards pipeline is long: clock advance -> cardholder
create -> account open (mints opened_at, signup_bonus_deadline_at,
signup_bonus_state=PENDING, points_balance=0) -> category register ->
purchase post (earns points via calc_points_provisional, may upgrade
tier, may qualify signup bonus). Many tests need the system in a late
pipeline state — a PLATINUM-tier account with a known points balance,
or an account that has crossed the signup deadline, or two accounts
with mirroring transaction histories for boundary comparison.

IDENTITY THREADING — PRD §2.1:

- PlatformAdmin is OPAQUE. Shared admin_headers constants are canonical
  for every operator-only call (account open, category register,
  partner register, mark-delinquent, clear-delinquency, transfer
  confirm, credit reverse, clock advance, sweeps).

- Cardholder is ENTITY-BACKED. Every Cardholder-driven call whose
  success depends on owning the targeted Account / Transaction /
  PointsTransfer / StatementCredit / QuarterlyActivation MUST mint
  headers via make_cardholder_headers(cardholder["id"]) — never via the
  shared CARDHOLDER_FALLBACK_ID constant. The fixtures here return the
  actual Cardholder row so consumer tests can route ownership-gated
  reads through this header builder.

Setup calls use get_success_data (a lenient 2xx validator), so a failed
setup surfaces as "Setup failed" rather than a confusing test assertion
failure downstream.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    SIGNUP_MIN_SPEND_CENTS,
    TEST_DEFAULTS,
    TIER_GOLD_THRESHOLD_CENTS,
    TIER_PLATINUM_THRESHOLD_CENTS,
)
from .factories import (
    clock_advance_payload,
    create_account_payload,
    create_activation_payload,
    create_amount_first_redemption_payload,
    create_cardholder_payload,
    create_cashback_category_payload,
    create_points_first_redemption_payload,
    create_points_transfer_payload,
    create_purchase_payload,
    create_refund_payload,
    create_transfer_partner_payload,
    iso_instant_utc,
    random_category_code,
    random_partner_code,
)
from .test_users import TEST_USERS, make_cardholder_headers


# ===========================================================================
# Clock helpers — PRD §3.8 (PlatformAdmin only)
# ===========================================================================
def advance_clock_to(to_iso: str) -> Dict[str, Any]:
    """POST /_clock/advance.

    PRD §3.8: 'The clock capability accepts a single to_timestamp and
    advances the simulated clock to that ISO 8601 instant'.
    """
    resp = api_client.clock_advance(
        clock_advance_payload(to_timestamp=to_iso),
        TEST_USERS["admin_headers"],
    )
    return get_success_data(resp)


def setup_clock_at(year: int, month: int, day: int,
                   hour: int = 0, minute: int = 0,
                   second: int = 0) -> str:
    """Pin the simulated clock at a deterministic UTC instant. Returns
    the ISO timestamp.
    """
    ts = iso_instant_utc(year, month, day, hour, minute, second)
    advance_clock_to(ts)
    return ts


def run_sweep() -> Dict[str, Any]:
    """POST /_sweep/run — PRD §3.8.

    PRD §3.8: 'The general sweep walks three independent buckets in a
    single pass'.
    """
    resp = api_client.sweep_run(None, TEST_USERS["admin_headers"])
    return get_success_data(resp)


def run_year_rollover() -> Dict[str, Any]:
    """POST /_sweep/year-rollover — PRD §3.8.

    PRD §3.8: 'at the instant the logical clock crosses January 1 at
    00:00:00 UTC, the rollover sweep resets ytd_qualifying_spend_cents
    to zero on every account and resets spending_tier to STANDARD on
    every GOLD or PLATINUM account'.
    """
    resp = api_client.sweep_year_rollover(
        None, TEST_USERS["admin_headers"],
    )
    return get_success_data(resp)


# ===========================================================================
# Tier 1: Cardholder & Account intake — PRD §3.1
# ===========================================================================
def create_cardholder(
    *,
    email: Optional[str] = None,
    display_name: Optional[str] = None,
) -> Dict[str, Any]:
    """POST /cardholders — PlatformAdmin only per PRD §4."""
    resp = api_client.create_cardholder(
        create_cardholder_payload(email=email, display_name=display_name),
        TEST_USERS["admin_headers"],
    )
    return get_success_data(resp)


def open_account(cardholder_id: str) -> Dict[str, Any]:
    """POST /accounts — PlatformAdmin only.

    PRD §3.1: 'A PlatformAdmin provisions a Cardholder ... With a
    cardholder on file, the same operator opens an Account by supplying
    the cardholder_id.'
    """
    resp = api_client.create_account(
        create_account_payload(cardholder_id=cardholder_id),
        TEST_USERS["admin_headers"],
    )
    return get_success_data(resp)


def create_cardholder_and_account() -> Tuple[Dict[str, Any],
                                             Dict[str, Any]]:
    """Cardholder + Account in one step. Returns (cardholder, account).

    Both are minted; the account inherits ACTIVE lifecycle, STANDARD
    tier, PENDING signup_bonus_state, points_balance=0 per PRD §3.1.

    The returned cardholder["id"] is the value that
    make_cardholder_headers must wrap when the consumer test issues a
    Cardholder-acting call against the account (PRD §2.1).
    """
    ch = create_cardholder()
    acc = open_account(ch["id"])
    return ch, acc


def re_get_account(account_id: str) -> Dict[str, Any]:
    """GET /accounts/{id} as PlatformAdmin (always permitted per PRD §4)."""
    resp = api_client.get_account(
        account_id, TEST_USERS["admin_headers"],
    )
    return get_success_data(resp)


def re_get_transaction(transaction_id: str) -> Dict[str, Any]:
    """GET /transactions/{id} as PlatformAdmin."""
    resp = api_client.get_transaction(
        transaction_id, TEST_USERS["admin_headers"],
    )
    return get_success_data(resp)


def get_ledger(account_id: str,
               *,
               entry_type: Optional[str] = None,
               limit: int = 100,
               offset: int = 0) -> List[Dict[str, Any]]:
    """GET /accounts/{id}/ledger as PlatformAdmin. Paginates greedily
    until total_count is fetched (up to `limit * 10` rows).
    """
    params: Dict[str, Any] = {"limit": limit, "offset": offset}
    if entry_type is not None:
        params["entry_type"] = entry_type
    all_rows: List[Dict[str, Any]] = []
    while True:
        resp = api_client.list_ledger(
            account_id, TEST_USERS["admin_headers"], params=params,
        )
        body = resp.json()
        data = body["data"]
        meta = body["meta"]
        all_rows.extend(data)
        if not meta.get("has_more"):
            break
        params["offset"] = params["offset"] + len(data)
        if len(all_rows) >= 1000:
            break
    return all_rows


def get_account_activations(account_id: str,
                            quarter_label: Optional[str] = None
                            ) -> List[Dict[str, Any]]:
    """GET /accounts/{id}/activations as PlatformAdmin."""
    params: Dict[str, Any] = {}
    if quarter_label is not None:
        params["quarter_label"] = quarter_label
    resp = api_client.list_activations(
        account_id, TEST_USERS["admin_headers"], params=params,
    )
    body = resp.json()
    return body["data"]


# ===========================================================================
# Tier 1: Category & Partner catalogue — PRD §3.2 / §3.3
# ===========================================================================
def register_category(
    *,
    code: Optional[str] = None,
    category_type: str = "FIXED_BONUS",
    base_rate_bps: int = 500,
) -> Dict[str, Any]:
    """POST /cashback-categories — PlatformAdmin only."""
    resp = api_client.create_cashback_category(
        create_cashback_category_payload(
            code=code, category_type=category_type,
            base_rate_bps=base_rate_bps,
        ),
        TEST_USERS["admin_headers"],
    )
    return get_success_data(resp)


def register_baseline_category(base_rate_bps: int = 100) -> Dict[str, Any]:
    """Convenience: a BASELINE category at 1% (default fallback rate).
    PRD §3.2: code must be uppercase A-Z plus underscore.
    """
    return register_category(
        code=random_category_code("BASE"),
        category_type="BASELINE", base_rate_bps=base_rate_bps,
    )


def register_fixed_bonus_category(
    base_rate_bps: int = 500,
    code_prefix: str = "BONUS",
) -> Dict[str, Any]:
    """Convenience: a FIXED_BONUS category at the supplied rate.
    PRD §3.2: code must be uppercase A-Z plus underscore.
    """
    return register_category(
        code=random_category_code(code_prefix),
        category_type="FIXED_BONUS", base_rate_bps=base_rate_bps,
    )


def register_rotating_category(
    base_rate_bps: int = 500,
    code_prefix: str = "ROT",
) -> Dict[str, Any]:
    """Convenience: a ROTATING_QUARTERLY category at the supplied rate.
    PRD §3.2: code must be uppercase A-Z plus underscore.
    """
    return register_category(
        code=random_category_code(code_prefix),
        category_type="ROTATING_QUARTERLY", base_rate_bps=base_rate_bps,
    )


def register_partner(
    *,
    code: Optional[str] = None,
    partner_type: str = "AIRLINE",
    conversion_ratio_points_per_unit: int = 2,
    min_transfer_increment: int = 1000,
    is_active: Optional[bool] = None,
) -> Dict[str, Any]:
    """POST /transfer-partners — PlatformAdmin only."""
    resp = api_client.create_transfer_partner(
        create_transfer_partner_payload(
            code=code, partner_type=partner_type,
            conversion_ratio_points_per_unit=(
                conversion_ratio_points_per_unit
            ),
            min_transfer_increment=min_transfer_increment,
            is_active=is_active,
        ),
        TEST_USERS["admin_headers"],
    )
    return get_success_data(resp)


# ===========================================================================
# Tier 2: Transactions — PRD §3.4
# Cardholder-acting; identity threaded via make_cardholder_headers.
# ===========================================================================
def post_purchase(
    *,
    cardholder_id: str,
    account_id: str,
    category_id: str,
    amount_cents: int,
) -> Dict[str, Any]:
    """POST /transactions PURCHASE — Cardholder.

    PRD §2.1 ownership-gated: identity is the actual cardholder_id, not
    a shared constant. Identity threading is mandatory.
    """
    headers = make_cardholder_headers(cardholder_id)
    resp = api_client.create_transaction(
        create_purchase_payload(
            account_id=account_id, category_id=category_id,
            amount_cents=amount_cents,
        ),
        headers,
    )
    return get_success_data(resp)


def post_refund(
    *,
    cardholder_id: str,
    account_id: str,
    category_id: str,
    amount_cents: int,
    original_transaction_id: str,
) -> Dict[str, Any]:
    """POST /transactions REFUND — Cardholder.

    PRD §3.4: 'amount_cents must equal the original's amount_cents
    (partial refunds are not supported)'.
    """
    headers = make_cardholder_headers(cardholder_id)
    resp = api_client.create_transaction(
        create_refund_payload(
            account_id=account_id, category_id=category_id,
            amount_cents=amount_cents,
            original_transaction_id=original_transaction_id,
        ),
        headers,
    )
    return get_success_data(resp)


# ===========================================================================
# Tier 2: Activation — PRD §3.2
# Cardholder-acting; identity threaded.
# ===========================================================================
def activate_category(
    *,
    cardholder_id: str,
    account_id: str,
    category_id: str,
    quarter_label: str,
) -> Dict[str, Any]:
    """POST /accounts/{id}/activate-category — Cardholder only per PRD §4."""
    headers = make_cardholder_headers(cardholder_id)
    resp = api_client.activate_category(
        account_id,
        create_activation_payload(
            category_id=category_id, quarter_label=quarter_label,
        ),
        headers,
    )
    return get_success_data(resp)


# ===========================================================================
# Tier 2: PointsTransfer — PRD §3.7
# Cardholder-acting; identity threaded.
# ===========================================================================
def initiate_points_transfer(
    *,
    cardholder_id: str,
    account_id: str,
    partner_id: str,
    requested_partner_units: int,
) -> Dict[str, Any]:
    """POST /points-transfers — Cardholder."""
    headers = make_cardholder_headers(cardholder_id)
    resp = api_client.create_points_transfer(
        create_points_transfer_payload(
            account_id=account_id, partner_id=partner_id,
            requested_partner_units=requested_partner_units,
        ),
        headers,
    )
    return get_success_data(resp)


def confirm_points_transfer(transfer_id: str) -> Dict[str, Any]:
    """POST /points-transfers/{id}/confirm — PlatformAdmin only.

    PRD §3.7: 'A PlatformAdmin confirms the transfer by acknowledging on
    behalf of the simulated partner'.
    """
    resp = api_client.confirm_points_transfer(
        transfer_id, None, TEST_USERS["admin_headers"],
    )
    return get_success_data(resp)


def reverse_points_transfer(*,
                            transfer_id: str,
                            cardholder_id: Optional[str] = None
                            ) -> Dict[str, Any]:
    """POST /points-transfers/{id}/reverse — Cardholder or
    PlatformAdmin. Default to admin if cardholder_id is not supplied.
    """
    if cardholder_id is not None:
        headers = make_cardholder_headers(cardholder_id)
    else:
        headers = TEST_USERS["admin_headers"]
    resp = api_client.reverse_points_transfer(
        transfer_id, None, headers,
    )
    return get_success_data(resp)


# ===========================================================================
# Tier 2: StatementCredit — PRD §3.6
# Cardholder-acting; identity threaded.
# ===========================================================================
def redeem_points_first(
    *,
    cardholder_id: str,
    account_id: str,
    requested_points: int,
) -> Dict[str, Any]:
    """POST /statement-credits with POINTS_FIRST mode — Cardholder."""
    headers = make_cardholder_headers(cardholder_id)
    resp = api_client.create_statement_credit(
        create_points_first_redemption_payload(
            account_id=account_id, requested_points=requested_points,
        ),
        headers,
    )
    return get_success_data(resp)


def redeem_amount_first(
    *,
    cardholder_id: str,
    account_id: str,
    requested_amount_cents: int,
) -> Dict[str, Any]:
    """POST /statement-credits with AMOUNT_FIRST mode — Cardholder."""
    headers = make_cardholder_headers(cardholder_id)
    resp = api_client.create_statement_credit(
        create_amount_first_redemption_payload(
            account_id=account_id,
            requested_amount_cents=requested_amount_cents,
        ),
        headers,
    )
    return get_success_data(resp)


def reverse_statement_credit(credit_id: str) -> Dict[str, Any]:
    """POST /statement-credits/{id}/reverse — PlatformAdmin only."""
    resp = api_client.reverse_statement_credit(
        credit_id, None, TEST_USERS["admin_headers"],
    )
    return get_success_data(resp)


# ===========================================================================
# Tier 3: Account-lifecycle shortcuts — PRD §3.1
# ===========================================================================
def mark_account_delinquent(account_id: str) -> Dict[str, Any]:
    """POST /accounts/{id}/mark-delinquent — PlatformAdmin only."""
    resp = api_client.mark_delinquent(
        account_id, None, TEST_USERS["admin_headers"],
    )
    return get_success_data(resp)


def clear_account_delinquency(account_id: str) -> Dict[str, Any]:
    """POST /accounts/{id}/clear-delinquency — PlatformAdmin only."""
    resp = api_client.clear_delinquency(
        account_id, None, TEST_USERS["admin_headers"],
    )
    return get_success_data(resp)


def close_account(*,
                  account_id: str,
                  cardholder_id: Optional[str] = None,
                  ) -> Dict[str, Any]:
    """POST /accounts/{id}/close — Cardholder or PlatformAdmin per PRD §4.

    PRD §3.1: 'Account closure is initiated by either the cardholder
    themselves or by a PlatformAdmin'.
    """
    if cardholder_id is not None:
        headers = make_cardholder_headers(cardholder_id)
    else:
        headers = TEST_USERS["admin_headers"]
    resp = api_client.close_account(account_id, None, headers)
    return get_success_data(resp)


# ===========================================================================
# Tier 4: Threshold-targeting setups — PRD §3.5 / §3.6 / §3.1
# These are CRITICAL: most calculation tests require the account to be
# in a specific tier or have a specific points_balance. Without these,
# tests would repeat 5-10 step preambles each.
# ===========================================================================
def setup_active_account_at(
    *,
    year: int = 2026,
    month: int = 1,
    day: int = 2,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Pin clock at the given date, then mint Cardholder + Account.
    Returns (cardholder, account). The account is ACTIVE / STANDARD /
    signup_bonus_state=PENDING with opened_at == the clock instant per
    PRD §3.1.
    """
    setup_clock_at(year, month, day)
    return create_cardholder_and_account()


def setup_account_with_baseline_category(
    *,
    year: int = 2026,
    month: int = 1,
    day: int = 2,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Active account + a BASELINE category (1% rate). Returns
    (cardholder, account, category).
    """
    ch, acc = setup_active_account_at(year=year, month=month, day=day)
    cat = register_baseline_category(base_rate_bps=100)
    return ch, acc, cat


def setup_account_with_fixed_bonus_category(
    *,
    base_rate_bps: int = 500,
    year: int = 2026,
    month: int = 1,
    day: int = 2,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Active account + a FIXED_BONUS category at the supplied rate.
    Returns (cardholder, account, category).
    """
    ch, acc = setup_active_account_at(year=year, month=month, day=day)
    cat = register_fixed_bonus_category(base_rate_bps=base_rate_bps)
    return ch, acc, cat


def setup_account_with_rotating_category(
    *,
    base_rate_bps: int = 500,
    year: int = 2026,
    month: int = 1,
    day: int = 2,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Active account + a ROTATING_QUARTERLY category.

    The category requires activation for the rotating quarter; tests
    that want activation should call activate_category afterwards.
    """
    ch, acc = setup_active_account_at(year=year, month=month, day=day)
    cat = register_rotating_category(base_rate_bps=base_rate_bps)
    return ch, acc, cat


def setup_account_on_gold(
    *,
    rate_bps: int = 500,
    open_year: int = 2026,
    open_month: int = 1,
    open_day: int = 2,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Pin clock, mint Cardholder/Account, register a FIXED_BONUS
    category at rate_bps, then post ONE purchase whose amount_cents is
    TIER_GOLD_THRESHOLD_CENTS (600,000) so the post crosses the GOLD
    threshold and the tier upgrades STANDARD -> GOLD. Returns
    (cardholder, account_after_upgrade, category).

    PRD §3.5: 'The transition from STANDARD to GOLD fires when the post
    brings the counter to at-or-above six hundred thousand cents'.

    NOTE: The single 600,000-cent purchase ALSO crosses the signup-bonus
    threshold (300,000) inside the signup window, so account leaves with
    signup_bonus_state == AWARDED. Tests that want signup_bonus_state ==
    PENDING on GOLD should use setup_account_on_gold_without_bonus.
    """
    ch, acc, cat = setup_account_with_fixed_bonus_category(
        base_rate_bps=rate_bps,
        year=open_year, month=open_month, day=open_day,
    )
    post_purchase(
        cardholder_id=ch["id"], account_id=acc["id"],
        category_id=cat["id"],
        amount_cents=TIER_GOLD_THRESHOLD_CENTS,
    )
    acc_now = re_get_account(acc["id"])
    return ch, acc_now, cat


def setup_account_on_platinum(
    *,
    rate_bps: int = 500,
    open_year: int = 2026,
    open_month: int = 1,
    open_day: int = 2,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Pin clock, mint Cardholder/Account, register a FIXED_BONUS
    category at rate_bps, then post ONE purchase whose amount_cents is
    TIER_PLATINUM_THRESHOLD_CENTS (1,500,000) so the post crosses both
    the GOLD threshold (600,000) and the PLATINUM threshold (1,500,000),
    leaving the account on PLATINUM. Returns (cardholder, account, cat).

    PRD §3.5: 'The transition from GOLD to PLATINUM fires when the post
    brings the counter to at-or-above one million five hundred thousand
    cents'.

    Note: per PRD §3.5 the pre-post tier must be GOLD to enter PLATINUM,
    but the calculation evaluates the threshold after the post; an
    implementation that fires both transitions in sequence on the same
    post is the PRD-faithful behavior. We avoid asserting on whether
    BOTH transitions are emitted; we only check the final state.
    """
    ch, acc, cat = setup_account_with_fixed_bonus_category(
        base_rate_bps=rate_bps,
        year=open_year, month=open_month, day=open_day,
    )
    # First purchase: 600,000 to cross STANDARD->GOLD.
    post_purchase(
        cardholder_id=ch["id"], account_id=acc["id"],
        category_id=cat["id"],
        amount_cents=TIER_GOLD_THRESHOLD_CENTS,
    )
    # Second purchase: 900,000 more to take ytd from 600,000 to
    # 1,500,000 and cross GOLD->PLATINUM.
    post_purchase(
        cardholder_id=ch["id"], account_id=acc["id"],
        category_id=cat["id"],
        amount_cents=TIER_PLATINUM_THRESHOLD_CENTS - TIER_GOLD_THRESHOLD_CENTS,
    )
    acc_now = re_get_account(acc["id"])
    return ch, acc_now, cat


def setup_account_with_balance_via_signup(
    *,
    spend_cents: int = SIGNUP_MIN_SPEND_CENTS,
    rate_bps: int = 500,
    open_year: int = 2026,
    open_month: int = 1,
    open_day: int = 2,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Pin clock, mint Cardholder/Account, register a FIXED_BONUS
    category at rate_bps, then post one purchase of spend_cents inside
    the signup window. If spend_cents >= SIGNUP_MIN_SPEND_CENTS this
    awards the 60,000-point signup bonus on top of regular earn.

    Returns (cardholder, account_after_bonus, category).
    """
    ch, acc, cat = setup_account_with_fixed_bonus_category(
        base_rate_bps=rate_bps,
        year=open_year, month=open_month, day=open_day,
    )
    post_purchase(
        cardholder_id=ch["id"], account_id=acc["id"],
        category_id=cat["id"], amount_cents=spend_cents,
    )
    acc_now = re_get_account(acc["id"])
    return ch, acc_now, cat


def setup_platinum_with_high_balance(
    *,
    extra_spend_cents: int = 0,
    rate_bps: int = 500,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """PLATINUM-tier account with a known points balance suitable for
    redemption tests. Returns (cardholder, account, category).

    Walks the system to PLATINUM via two purchases summing to 1,500,000
    cents (= $15,000). At 5% category rate, the PLATINUM-backfilled
    earn is:

      Provisional on purchase 1 (STANDARD): floor(600000 * 500 / 10000)
        = 30000 points. Provisional on purchase 2 (GOLD, after upgrade
        at end of purchase 1): combined_bps = floor(500*12500/10000) =
        625; points = floor(900000 * 625 / 10000) = 56250 points.
      After purchase 2 the tier reaches PLATINUM and EARN_ADJUST
        backfills both same-month transactions at PLATINUM (mult 15000):
        p1: floor(600000 * floor(500*15000/10000) / 10000) =
            floor(600000 * 750 / 10000) = 45000; delta = +15000.
        p2: floor(900000 * 750 / 10000) = 67500; delta = +11250.

    Total balance after both purchases and backfills:
      30000 + 56250 + 15000 + 11250 = 112,500 points.

    Plus a SIGNUP_BONUS of 60,000 (the 600,000-cent first purchase
    crosses the 300,000-cent signup threshold inside the 90-day window).
    Total: 172,500 points.

    Tests should NOT rely on this exact number — instead read
    account["points_balance"] from the returned account row.

    If extra_spend_cents > 0, that amount is posted as an additional
    PURCHASE (under PLATINUM tier) before the account is re-read, so
    callers can shape the post-PLATINUM balance further.
    """
    ch, acc, cat = setup_account_on_platinum(rate_bps=rate_bps)
    if extra_spend_cents > 0:
        post_purchase(
            cardholder_id=ch["id"], account_id=acc["id"],
            category_id=cat["id"], amount_cents=extra_spend_cents,
        )
        acc = re_get_account(acc["id"])
    return ch, acc, cat


def setup_account_with_pending_transfer(
    *,
    requested_partner_units: int = 1000,
    conversion_ratio: int = 10,
    min_increment: int = 1000,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any],
           Dict[str, Any]]:
    """Account on PLATINUM with one PENDING PointsTransfer. Returns
    (cardholder, account, partner, transfer).
    """
    ch, acc, _cat = setup_account_on_platinum()
    partner = register_partner(
        conversion_ratio_points_per_unit=conversion_ratio,
        min_transfer_increment=min_increment,
    )
    transfer = initiate_points_transfer(
        cardholder_id=ch["id"], account_id=acc["id"],
        partner_id=partner["id"],
        requested_partner_units=requested_partner_units,
    )
    return ch, acc, partner, transfer


# ===========================================================================
# Tier 5: Terminal-state setups — PRD §3.1
# ===========================================================================
def setup_closed_account(
    *,
    pre_close_spend_cents: int = 0,
    rate_bps: int = 500,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Cardholder + Account walked to CLOSED. Returns (cardholder,
    closed_account). Optionally posts pre_close_spend_cents before
    close so the FORFEIT entry has a non-zero balance to forfeit.

    PRD §3.1: 'The transition from ACTIVE to CLOSED first appends a
    single FORFEIT ledger entry whose delta_points is the negation of
    the current points_balance, then recomputes points_balance to zero'.
    """
    ch, acc, cat = setup_account_with_fixed_bonus_category(
        base_rate_bps=rate_bps,
    )
    if pre_close_spend_cents > 0:
        post_purchase(
            cardholder_id=ch["id"], account_id=acc["id"],
            category_id=cat["id"], amount_cents=pre_close_spend_cents,
        )
    closed = close_account(
        account_id=acc["id"], cardholder_id=ch["id"],
    )
    return ch, closed


def setup_delinquent_account(
    *,
    pre_delinquent_spend_cents: int = 0,
    rate_bps: int = 500,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Cardholder + Account moved to DELINQUENT. Returns (cardholder,
    delinquent_account, category).
    """
    ch, acc, cat = setup_account_with_fixed_bonus_category(
        base_rate_bps=rate_bps,
    )
    if pre_delinquent_spend_cents > 0:
        post_purchase(
            cardholder_id=ch["id"], account_id=acc["id"],
            category_id=cat["id"],
            amount_cents=pre_delinquent_spend_cents,
        )
    delinquent = mark_account_delinquent(acc["id"])
    return ch, delinquent, cat


__all__ = [
    # Clock & sweeps
    "advance_clock_to",
    "setup_clock_at",
    "run_sweep",
    "run_year_rollover",
    # Tier 1: cardholder / account / catalogue
    "create_cardholder",
    "open_account",
    "create_cardholder_and_account",
    "re_get_account",
    "re_get_transaction",
    "get_ledger",
    "get_account_activations",
    "register_category",
    "register_baseline_category",
    "register_fixed_bonus_category",
    "register_rotating_category",
    "register_partner",
    # Tier 2: cardholder-acting operations
    "post_purchase",
    "post_refund",
    "activate_category",
    "initiate_points_transfer",
    "confirm_points_transfer",
    "reverse_points_transfer",
    "redeem_points_first",
    "redeem_amount_first",
    "reverse_statement_credit",
    # Tier 3: account-lifecycle shortcuts
    "mark_account_delinquent",
    "clear_account_delinquency",
    "close_account",
    # Tier 4: threshold-targeting composites
    "setup_active_account_at",
    "setup_account_with_baseline_category",
    "setup_account_with_fixed_bonus_category",
    "setup_account_with_rotating_category",
    "setup_account_on_gold",
    "setup_account_on_platinum",
    "setup_account_with_balance_via_signup",
    "setup_platinum_with_high_balance",
    "setup_account_with_pending_transfer",
    # Tier 5: terminal-state setups
    "setup_closed_account",
    "setup_delinquent_account",
]
