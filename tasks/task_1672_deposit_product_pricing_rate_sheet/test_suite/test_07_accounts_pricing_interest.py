"""Account opening, tiered pricing variants and boundaries, lifecycle rules,
and interest accrual/posting arithmetic (PRD §2.6, §3.5)."""
from test_helpers import (
    ApiErrorId,
    assert_deposit_account,
    assert_rate_quote,
    create_effective_sheet,
    create_product,
    open_account,
    patch_balance,
    set_clock,
    single_tier,
    tier,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS

BANKER = TEST_USERS["banker_headers"]

BOUNDARY_TIERS = [tier(0, 0, 2_500_000, 120), tier(1, 2_500_000, -1, 185)]
DIVERGENCE_TIERS = [tier(0, 0, 2_500_000, 120), tier(1, 2_500_000, 10_000_000, 185),
                    tier(2, 10_000_000, -1, 240)]


def test_account_open_without_effective_sheet_fails(api, banker_headers):
    """PRD §3.5: "At open, the account's `sheet_id` is resolved to the unique
    `EFFECTIVE` sheet for the pair — uniqueness holds because activation
    atomically supersedes the incumbent — and when no effective sheet exists
    the open fails with `ERR_SHEET_NOT_FOUND`."

    Design: Corner/entities/account_open_without_effective_sheet_fails
    """
    product = create_product(product_code="NOS")
    resp = api.create_deposit_account(
        {"customer_ref": "CN", "product_id": product["id"], "market_code": "US-WEST",
         "opening_balance_cents": 1_000_000, "channel": "ONLINE"},
        banker_headers)
    validate_error(resp, ApiErrorId.ERR_SHEET_NOT_FOUND, 422)


def test_immutable_system_fields_on_create(api, banker_headers):
    """PRD §3.5: "The account is born with `lifecycle` `OPEN` and
    `rate_source` `SHEET`; `opened_at` records the logical date of opening,
    `last_accrual_date` initializes to the opened date, and both
    `unposted_accrual_milli` and `posted_interest_cents` start at zero."
    PRD §2.5: "`version` (integer): starts at 1 on creation and increments by
    exactly one on every mutation."
    PRD §3.5: "Pricing is computed immediately: `base_rate_bp` from the
    sheet's tiers at the opening balance, the bundle bonus evaluated per
    §3.7, and `current_rate_bp` stacked and capped."

    Design: Corner/entities/immutable_system_fields_on_create
    """
    setup = create_effective_sheet(effective_date="2026-08-15",
                                   tiers=single_tier(123),
                                   product_overrides={"product_code": "SYS"})
    resp = api.create_deposit_account(
        {"customer_ref": "CS", "product_id": setup["product_id"],
         "market_code": "US-WEST", "opening_balance_cents": 1_000_000,
         "channel": "ONLINE"},
        banker_headers)
    account = validate_success(resp, 201)
    assert_deposit_account(account)
    assert account["lifecycle"] == "OPEN"
    assert account["rate_source"] == "SHEET"
    assert account["posted_interest_cents"] == 0
    assert account["unposted_accrual_milli"] == 0
    assert account["version"] == 1
    assert account["current_rate_bp"] == 123
    assert account["sheet_id"] == setup["sheet"]["id"]
    assert account["last_accrual_date"] == "2026-08-15"
    assert account["opened_at"] == "2026-08-15"


def _divergence_pair(api):
    """Two products sharing one tier structure: P-MMA selects MARGINAL, P-SAV
    selects WHOLE_BALANCE; each with an EFFECTIVE sheet and an account holding
    exactly 7,500,000 cents."""
    p_mma = create_product(product_code="MMA", product_class="MONEY_MARKET",
                           term_months=0, tier_application="MARGINAL", rate_cap_bp=500)
    create_effective_sheet(product_id=p_mma["id"], effective_date="2026-08-15",
                           tiers=DIVERGENCE_TIERS)
    p_sav = create_product(product_code="SAV", product_class="SAVINGS", term_months=0,
                           tier_application="WHOLE_BALANCE", rate_cap_bp=500)
    create_effective_sheet(product_id=p_sav["id"], effective_date="2026-09-01",
                           tiers=DIVERGENCE_TIERS)
    a_mma = open_account(p_mma["id"], opening_balance_cents=7_500_000, customer_ref="C1")
    a_sav = open_account(p_sav["id"], opening_balance_cents=7_500_000, customer_ref="C2")
    return a_mma, a_sav


def test_tiered_rate_marginal_vs_whole_balance_diverge(api, banker_headers):
    """PRD §3.5: "Under `MARGINAL`, each tier's rate applies only to the slice
    of the balance inside that tier, and the blended rate is the sum over
    tiers of slice size multiplied by tier rate, divided by the balance,
    rounded half up to a whole basis point. Under `WHOLE_BALANCE`, the rate of
    the single tier containing the balance applies to the entire balance."

    Design: Difficulty/dual_variant_calc/tiered_rate_marginal_vs_whole_balance
    """
    a_mma, a_sav = _divergence_pair(api)
    q_mma = validate_success(api.get_rate_quote(a_mma["id"], banker_headers))
    q_sav = validate_success(api.get_rate_quote(a_sav["id"], banker_headers))
    # MARGINAL: (2,500,000*120 + 5,000,000*185) / 7,500,000 = 163.33... -> 163.
    assert q_mma["base_rate_bp"] == 163
    assert q_mma["current_rate_bp"] == 163
    # WHOLE_BALANCE: 7,500,000 lies in the 185 bp tier.
    assert q_sav["base_rate_bp"] == 185
    assert q_sav["current_rate_bp"] == 185
    assert q_mma["base_rate_bp"] != q_sav["base_rate_bp"]


def test_tiered_rate_marginal_quote_breakdown(api, banker_headers):
    """PRD §3.5: "a rate-quote read exposes the full breakdown — `account_id`,
    `rate_source`, `base_rate_bp`, `bundle_bonus_bp`, `exception_rate_bp`,
    `cap_applied` (whether the cap clamped the stack), and `current_rate_bp`."

    Design: Difficulty/dual_variant_calc/tiered_rate_marginal_vs_whole_balance
    """
    a_mma, _ = _divergence_pair(api)
    quote = validate_success(api.get_rate_quote(a_mma["id"], banker_headers))
    assert_rate_quote(quote)
    assert quote["account_id"] == a_mma["id"]
    assert quote["rate_source"] == "SHEET"
    assert quote["base_rate_bp"] == 163
    assert quote["bundle_bonus_bp"] == 0
    assert quote["cap_applied"] is False
    assert quote["current_rate_bp"] == 163


def test_tier_boundary_exact_lower_bound_inclusive(api, banker_headers):
    """PRD §3.5: "Tiers are half-open intervals: each covers balances from its
    `lower_bound_cents` up to but not including its `upper_bound_cents`, so a
    balance landing exactly on a boundary belongs to the tier whose lower
    bound equals it."

    Design: Difficulty/boundary_precision_check/tier_boundary_balance_exact_lower_inclusive
    """
    product = create_product(product_code="BND")
    create_effective_sheet(product_id=product["id"], effective_date="2026-08-15",
                           tiers=BOUNDARY_TIERS)
    account = open_account(product["id"], opening_balance_cents=2_500_000,
                           customer_ref="CB")
    quote = validate_success(api.get_rate_quote(account["id"], banker_headers))
    assert quote["base_rate_bp"] == 185


def test_tier_boundary_one_cent_below(api, banker_headers):
    """PRD §3.5: "Tiers are half-open intervals: each covers balances from its
    `lower_bound_cents` up to but not including its `upper_bound_cents`, so a
    balance landing exactly on a boundary belongs to the tier whose lower
    bound equals it."
    PRD §3.5: "A successful adjustment recomputes the account's tier base and
    current rate, refreshes `qualifying_balance_cents` on the customer's
    `ENROLLED` bundle enrollments, and bumps the account version."

    Design: Difficulty/boundary_precision_check/tier_boundary_balance_exact_lower_inclusive
    """
    product = create_product(product_code="BND")
    create_effective_sheet(product_id=product["id"], effective_date="2026-08-15",
                           tiers=BOUNDARY_TIERS)
    account = open_account(product["id"], opening_balance_cents=2_500_000,
                           customer_ref="CB")
    patched = patch_balance(account["id"], account["version"], 2_499_999)
    assert patched["balance_cents"] == 2_499_999
    quote = validate_success(api.get_rate_quote(account["id"], banker_headers))
    assert quote["base_rate_bp"] == 120


def test_account_lifecycle_invalid_transitions(api, banker_headers):
    """PRD §3.5: "Any incompatible combination — closing a `CLOSED` account,
    freezing a frozen one, or attempting a promo enrollment on a `FROZEN` or
    non-`SHEET` account — is rejected with `ERR_ACCOUNT_INVALID_STATE`."
    PRD §3.5: "`FREEZE` moves `OPEN → FROZEN`, `UNFREEZE` moves `FROZEN →
    OPEN`, and `CLOSE` moves `OPEN` or `FROZEN` to the terminal `CLOSED`."
    PRD §3.5: "posting on a `CLOSED` account is rejected with
    `ERR_ACCOUNT_INVALID_STATE`."

    Design: Corner/state_machines/account_lifecycle_invalid_transitions
    """
    product = create_product(product_code="IV6")
    create_effective_sheet(product_id=product["id"], effective_date="2026-08-15",
                           tiers=single_tier(100))
    open_acc = open_account(product["id"], customer_ref="CO6")
    closed_acc = open_account(product["id"], customer_ref="CC6")
    closed = validate_success(api.deposit_account_action(closed_acc["id"],
                                                         {"action": "CLOSE"}, banker_headers))
    assert closed["lifecycle"] == "CLOSED"

    # UNFREEZE is defined only from FROZEN; an OPEN account rejects it.
    resp = api.deposit_account_action(open_acc["id"], {"action": "UNFREEZE"}, banker_headers)
    validate_error(resp, ApiErrorId.ERR_ACCOUNT_INVALID_STATE, 409)

    # CLOSED is terminal.
    resp = api.deposit_account_action(closed_acc["id"], {"action": "CLOSE"}, banker_headers)
    validate_error(resp, ApiErrorId.ERR_ACCOUNT_INVALID_STATE, 409)

    # Posting on CLOSED.
    resp = api.post_interest(closed_acc["id"], banker_headers)
    validate_error(resp, ApiErrorId.ERR_ACCOUNT_INVALID_STATE, 409)


def _accrual_scenario(api, product_code="CHK", product_class="INTEREST_CHECKING",
                      rate_cap=900, rate=400, balance=1_000_069):
    """EFFECTIVE single-tier sheet at `rate`; one account opened at
    2026-08-15 with `balance`."""
    product = create_product(product_code=product_code, product_class=product_class,
                             term_months=0, tier_application="WHOLE_BALANCE",
                             rate_cap_bp=rate_cap, allows_promos=False,
                             allows_exceptions=False)
    create_effective_sheet(product_id=product["id"], effective_date="2026-08-15",
                           tiers=single_tier(rate))
    return open_account(product["id"], opening_balance_cents=balance, customer_ref="C5",
                        channel="BRANCH")


def test_interest_accrues_daily_with_floor(api, banker_headers):
    """PRD §3.5: "Each elapsed day of the clock sweep, every account whose
    lifecycle is not `CLOSED` accrues the whole milli-cents obtained by
    multiplying its posted `balance_cents` by its `current_rate_bp` and
    dividing by 3,650 — a division floored to whole milli-cents, reflecting a
    365-day year and the basis-point denominator — and that amount accumulates
    into `unposted_accrual_milli`."

    Design: Difficulty/combinatorial_formula/interest_posting_sum_then_round_order
    """
    account = _accrual_scenario(api)
    set_clock("2026-09-15")  # 31 elapsed days
    data = validate_success(api.get_deposit_account(account["id"], banker_headers))
    # Per day: floor(1,000,069 * 400 / 3,650) = 109,596 milli-cents.
    # 31 * 109,596 = 3,397,476.
    assert data["unposted_accrual_milli"] == 3_397_476
    assert data["posted_interest_cents"] == 0


def test_interest_posting_sums_then_rounds_once(api, banker_headers):
    """PRD §2.6: "The server never rounds each day's accrual to cents before
    summing — summing first and rounding once at posting is the pinned
    behavior, because per-day rounding to cents yields a different posted
    total."
    PRD §3.5: "Posting, invoked by a `BranchBanker` through the
    interest-posting capability, converts the accumulated accrual to cents
    exactly once: `unposted_accrual_milli` divided by one thousand and rounded
    half up yields the posted delta, which is added to `posted_interest_cents`;
    the accrual then resets to zero and `last_accrual_date` becomes logical
    today."
    PRD §3.5: "The posting operation returns the updated account with a 201
    status, since a posting record is created."

    Design: Difficulty/combinatorial_formula/interest_posting_sum_then_round_order
    """
    account = _accrual_scenario(api)
    set_clock("2026-09-15")
    resp = api.post_interest(account["id"], banker_headers)
    posted = validate_success(resp, 201)
    # round_half_up(3,397,476 / 1,000) = 3,397 — not 3,410, the value daily
    # cent-rounding would produce (110 * 31).
    assert posted["posted_interest_cents"] == 3_397
    assert posted["posted_interest_cents"] != 3_410
    assert posted["unposted_accrual_milli"] == 0
    assert posted["last_accrual_date"] == "2026-09-15"


def test_interest_posting_same_day_noop(api, banker_headers):
    """PRD §3.5: "Posting when nothing has accrued is a no-op that posts a
    delta of zero; posting on a `CLOSED` account is rejected with
    `ERR_ACCOUNT_INVALID_STATE`."

    Design: Corner/calculations/interest_posting_same_day_noop
    """
    account = _accrual_scenario(api, product_code="NOP", product_class="SAVINGS",
                                rate_cap=500)
    set_clock("2026-08-16")  # exactly one elapsed day: 109,596 milli-cents
    first = validate_success(api.post_interest(account["id"], banker_headers), 201)
    assert first["posted_interest_cents"] == 110  # round_half_up(109.596)
    second = validate_success(api.post_interest(account["id"], banker_headers), 201)
    assert second["posted_interest_cents"] == 110  # unchanged: the delta was zero
    assert second["unposted_accrual_milli"] == 0
