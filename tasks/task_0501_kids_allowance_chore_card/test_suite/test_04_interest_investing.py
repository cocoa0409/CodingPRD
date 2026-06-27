"""Interest match accrual and the teen investing add-on.

Covers difficulty queue (dual_variant_calc interest, boundary_precision interest cap,
resource_temporal_overlap accrual, combinatorial_formula investment rounding) and corner queue
(calculations, validations, state_machines, entities) instances rooted in PRD Sections 3.7, 3.8, 2.7.
"""
from test_helpers import (
    validate_success, validate_error,
    setup_enabled_interest, setup_teen_investment_account, setup_family_with_child,
    set_clock, get_interest_config_id,
)
from test_helpers.factories import accrue_payload, order_payload


# ─── dual_variant_calc: interest WHOLE_PERIOD accrual ───────────────────────
def test_whole_period_accrual_credits_986(api):
    """PRD 3.7: "The raw interest in cents is the base balance multiplied by `annual_rate_bps`, multiplied by `period_days`, divided by the product of ten thousand and three hundred sixty-five, with that single division rounded half up to whole cents."
    PRD 3.7: "Under `WHOLE_PERIOD`, the base is the save jar's `balance_cents` observed at accrual time — a period-end snapshot."

    Base 120000, rate 1000 bps, 30 days -> round_half_up(120000*1000*30/(10000*365)) = 986.

    Design: Difficulty/dual_variant_calc/interest_whole_period_vs_daily_average_diverge
    """
    fam, child, save_jar_id, cfg_id, ph = setup_enabled_interest(
        save_cents=120_000, annual_rate_bps=1000, monthly_cap_cents=0,
        accrual_method="WHOLE_PERIOD", clock_iso="2026-03-01T00:00:00Z", deposit_cents=200_000)

    accr = validate_success(api.accrue(cfg_id, accrue_payload(30), ph), 201)
    assert accr["matched_cents"] == 986

    jar_after = validate_success(api.get_jar(save_jar_id, ph), 200)
    assert jar_after["balance_cents"] == 120_986


def test_whole_period_accrual_debits_family_wallet(api):
    """PRD 3.7: "The resulting `matched_cents` is credited to the save jar's `balance_cents` and debited from the family's `funding_balance_cents"
    PRD 3.2: "Funding a jar names a `jar_type` and an `amount_cents`; the server debits the family's `funding_balance_cents` and credits the target jar's `balance_cents`"

    Family funded 200000; seeding the SAVE jar with 120000 debits the wallet to 80000
    (PRD 3.2 fund-jar), then the accrual match of 986 debits it again -> wallet 79014.

    Design: Difficulty/dual_variant_calc/interest_whole_period_vs_daily_average_diverge
    """
    fam, child, save_jar_id, cfg_id, ph = setup_enabled_interest(
        save_cents=120_000, annual_rate_bps=1000, monthly_cap_cents=0,
        accrual_method="WHOLE_PERIOD", clock_iso="2026-03-01T00:00:00Z", deposit_cents=200_000)

    validate_success(api.accrue(cfg_id, accrue_payload(30), ph), 201)
    fam_after = validate_success(api.get_family(fam["id"], ph), 200)
    assert fam_after["funding_balance_cents"] == 79_014


# ─── boundary_precision: interest monthly cap exact boundary ────────────────
def test_interest_cap_below_raw_clamps(api):
    """PRD 3.7: "The matched amount equals that raw interest, except that when `monthly_cap_cents` is greater than zero the matched amount is the smaller of the raw interest and `monthly_cap_cents`."

    Raw interest is 986; with monthly_cap_cents=985 the match clamps to 985.

    Design: Difficulty/boundary_precision_check/interest_cap_exact_boundary
    """
    fam, child, save_jar_id, cfg_id, ph = setup_enabled_interest(
        save_cents=120_000, annual_rate_bps=1000, monthly_cap_cents=985,
        accrual_method="WHOLE_PERIOD", clock_iso="2026-03-01T00:00:00Z", deposit_cents=200_000)

    accr = validate_success(api.accrue(cfg_id, accrue_payload(30), ph), 201)
    assert accr["matched_cents"] == 985
    jar_after = validate_success(api.get_jar(save_jar_id, ph), 200)
    assert jar_after["balance_cents"] == 120_985


def test_interest_cap_equal_to_raw_passes_through(api):
    """PRD 3.7: "The matched amount equals that raw interest, except that when `monthly_cap_cents` is greater than zero the matched amount is the smaller of the raw interest and `monthly_cap_cents`."

    Raw interest is 986; with monthly_cap_cents=986 the match equals the raw 986 (cap == raw is not
    a clamp because min(986, 986) == 986).

    Design: Difficulty/boundary_precision_check/interest_cap_exact_boundary
    """
    fam, child, save_jar_id, cfg_id, ph = setup_enabled_interest(
        save_cents=120_000, annual_rate_bps=1000, monthly_cap_cents=986,
        accrual_method="WHOLE_PERIOD", clock_iso="2026-03-01T00:00:00Z", deposit_cents=200_000)

    accr = validate_success(api.accrue(cfg_id, accrue_payload(30), ph), 201)
    assert accr["matched_cents"] == 986


# ─── resource_temporal_overlap: accrual half-open back-cover ────────────────
def test_accrual_back_dating_into_prior_window_rejected(api):
    """PRD 3.7: "If the new window's start falls strictly before the latest prior `accrued_at`, the accrual would back-date into an already-covered period and is rejected with `ERR_ACCRUAL_PERIOD_OVERLAP`; a new window whose start lands exactly on the prior accrual's `accrued_at` is adjacent and is allowed."

    First accrual at 2026-02-01 covers (2026-01-02, 2026-02-01]. A second at 2026-02-20 with
    period_days=30 starts 2026-01-21 < 2026-02-01 -> overlap.

    Design: Difficulty/resource_temporal_overlap/interest_accrual_half_open_back_cover_rejected
    """
    set_clock("2026-02-01T00:00:00Z")
    fam, child, save_jar_id, cfg_id, ph = setup_enabled_interest(
        save_cents=120_000, annual_rate_bps=1000, monthly_cap_cents=0,
        accrual_method="WHOLE_PERIOD", clock_iso=None, deposit_cents=200_000)
    validate_success(api.accrue(cfg_id, accrue_payload(30), ph), 201)

    set_clock("2026-02-20T00:00:00Z")
    res = api.accrue(cfg_id, accrue_payload(30), ph)
    validate_error(res, "ERR_ACCRUAL_PERIOD_OVERLAP")


def test_accrual_adjacent_window_allowed(api):
    """PRD 3.7: "Against the latest prior accrual on the same configuration ... the new window's start must be at or after that prior accrual's `accrued_at`."
    PRD 3.7: "a new window whose start lands exactly on the prior accrual's `accrued_at` is adjacent and is allowed."

    First accrual at 2026-02-01 covers (2026-01-02, 2026-02-01]. A second at 2026-03-03 with
    period_days=30 starts exactly 2026-02-01 -> adjacent -> allowed.

    Design: Difficulty/resource_temporal_overlap/interest_accrual_half_open_back_cover_rejected
    """
    set_clock("2026-02-01T00:00:00Z")
    fam, child, save_jar_id, cfg_id, ph = setup_enabled_interest(
        save_cents=120_000, annual_rate_bps=1000, monthly_cap_cents=0,
        accrual_method="WHOLE_PERIOD", clock_iso=None, deposit_cents=200_000)
    validate_success(api.accrue(cfg_id, accrue_payload(30), ph), 201)

    set_clock("2026-03-03T00:00:00Z")  # 30 days before is 2026-02-01 == prior accrued_at
    accr2 = validate_success(api.accrue(cfg_id, accrue_payload(30), ph), 201)
    assert accr2["matched_cents"] >= 0


# ─── corner validations: accrue on disabled config ──────────────────────────
def test_accrue_on_disabled_config_rejected(api):
    """PRD 3.7: "an enabled configuration is required before any accrual, and accruing on a disabled configuration is rejected with `ERR_INTEREST_DISABLED`."

    Design: Corner/validations/accrue_on_disabled_config_returns_interest_disabled
    """
    set_clock("2026-03-01T00:00:00Z")
    fam, child, ph = setup_family_with_child(deposit_cents=50_000)
    cfg_id = get_interest_config_id(child["id"], ph)  # never configured -> DISABLED

    res = api.accrue(cfg_id, accrue_payload(30), ph)
    validate_error(res, "ERR_INTEREST_DISABLED")


# ─── combinatorial_formula: investment order round-once ─────────────────────
def test_buy_order_rounds_gross_once(api):
    """PRD 3.8: "The order's notional, `gross_cents`, is computed by multiplying `shares_milli` by `price_cents_per_share`, dividing by one thousand, and rounding half up to whole cents; the rounding is done exactly once over the whole order, never per share and then summed."
    PRD 3.8: "on success reduces `cash_cents` by `gross_cents` and increases the symbol's `shares_milli` in `holdings` by the ordered `shares_milli`."

    2500 milli at 1001 cents/share -> round_half_up(2500*1001/1000) = round_half_up(2502.5) = 2503.

    Design: Difficulty/combinatorial_formula/investment_order_rounding_order_round_once
    """
    fam, child, inv, ph = setup_teen_investment_account(
        cash_cents=10_000, save_seed_cents=20_000, clock_iso="2026-06-26T00:00:00Z",
        deposit_cents=50_000)

    order = validate_success(api.place_order(
        inv["id"], order_payload("BUY", "ZZZ", 2500, 1001), ph), 201)
    assert order["gross_cents"] == 2503
    assert order["status"] == "FILLED"

    inv_after = validate_success(api.get_investment_account(inv["id"], ph), 200)
    assert inv_after["cash_cents"] == 7497


def test_buy_order_adds_shares_to_holdings(api):
    """PRD 3.8: "on success reduces `cash_cents` by `gross_cents` and increases the symbol's `shares_milli` in `holdings` by the ordered `shares_milli`."

    Design: Difficulty/combinatorial_formula/investment_order_rounding_order_round_once
    """
    fam, child, inv, ph = setup_teen_investment_account(
        cash_cents=10_000, save_seed_cents=20_000, clock_iso="2026-06-26T00:00:00Z",
        deposit_cents=50_000)

    validate_success(api.place_order(inv["id"], order_payload("BUY", "ZZZ", 2500, 1001), ph), 201)
    inv_after = validate_success(api.get_investment_account(inv["id"], ph), 200)
    assert inv_after["holdings"]["ZZZ"]["shares_milli"] == 2500


# ─── corner calculations: sell round-once ───────────────────────────────────
def test_sell_order_credits_cash_round_once(api):
    """PRD 3.8: "A `SELL` requires the symbol's held `shares_milli` to be at least the ordered `shares_milli ... and on success reduces the symbol's `shares_milli` by the ordered amount and increases `cash_cents` by `gross_cents`."

    Buy 2000 milli ZZZ at 18050 -> gross round_half_up(2000*18050/1000) = 36100, leaving
    cash 37100-36100 = 1000. Then sell 1500 milli at 18050:
    gross = round_half_up(1500*18050/1000) = 27075 credited to cash -> 1000+27075 = 28075.

    Design: Corner/calculations/investment_sell_increases_cash_round_once
    """
    fam, child, inv, ph = setup_teen_investment_account(
        cash_cents=37_100, save_seed_cents=60_000, clock_iso="2026-06-26T00:00:00Z",
        deposit_cents=100_000)
    validate_success(api.place_order(inv["id"], order_payload("BUY", "ZZZ", 2000, 18050), ph), 201)

    order = validate_success(api.place_order(inv["id"], order_payload("SELL", "ZZZ", 1500, 18050), ph), 201)
    assert order["gross_cents"] == 27_075
    assert order["status"] == "FILLED"
    inv_after = validate_success(api.get_investment_account(inv["id"], ph), 200)
    assert inv_after["cash_cents"] == 28_075


# ─── corner validations: insufficient invest cash on buy ────────────────────
def test_insufficient_invest_cash_on_buy(api):
    """PRD 3.8: "A `BUY` requires the account's `cash_cents` to be at least `gross_cents` — otherwise it is rejected with `ERR_INSUFFICIENT_INVEST_CASH"

    Design: Corner/validations/insufficient_invest_cash_on_buy
    """
    fam, child, inv, ph = setup_teen_investment_account(
        cash_cents=5000, save_seed_cents=8000, clock_iso="2026-06-26T00:00:00Z",
        deposit_cents=20_000)

    res = api.place_order(inv["id"], order_payload("BUY", "BBB", 1000, 10000), ph)  # gross 10000 > 5000
    validate_error(res, "ERR_INSUFFICIENT_INVEST_CASH")
    inv_after = validate_success(api.get_investment_account(inv["id"], ph), 200)
    assert inv_after["cash_cents"] == 5000


# ─── corner validations: sell more shares than held ─────────────────────────
def test_sell_more_shares_than_held(api):
    """PRD 3.8: "A `SELL` requires the symbol's held `shares_milli` to be at least the ordered `shares_milli` — otherwise it is rejected with `ERR_INSUFFICIENT_SHARES"

    Design: Corner/validations/sell_more_shares_than_held
    """
    fam, child, inv, ph = setup_teen_investment_account(
        cash_cents=10_000, save_seed_cents=30_000, clock_iso="2026-06-26T00:00:00Z",
        deposit_cents=50_000)
    validate_success(api.place_order(inv["id"], order_payload("BUY", "CCC", 1000, 5000), ph), 201)

    res = api.place_order(inv["id"], order_payload("SELL", "CCC", 2000, 5000), ph)
    validate_error(res, "ERR_INSUFFICIENT_SHARES")


# ─── corner validations: duplicate investing add-on ─────────────────────────
def test_duplicate_investment_account_rejected(api):
    """PRD 3.8: "a second attempt to enable investing for the same child is rejected with `ERR_DUPLICATE_INVEST_ACCOUNT`."

    Design: Corner/validations/duplicate_investment_account_returns_duplicate_error
    """
    set_clock("2026-06-26T00:00:00Z")
    fam, child, ph = setup_family_with_child(deposit_cents=0, birthdate="2010-01-01")
    validate_success(api.enable_investing(child["id"], ph), 201)

    res = api.enable_investing(child["id"], ph)
    validate_error(res, "ERR_DUPLICATE_INVEST_ACCOUNT")


# ─── corner validations: under-13 not teen eligible ─────────────────────────
def test_enable_investing_under_13_rejected(api):
    """PRD 3.8: "A child under thirteen is rejected with `ERR_NOT_TEEN_ELIGIBLE"

    Design: Corner/validations/enable_investing_under_13_returns_not_teen_eligible
    """
    set_clock("2026-06-26T00:00:00Z")
    fam, child, ph = setup_family_with_child(deposit_cents=0, birthdate="2015-01-01")  # 11 yrs old

    res = api.enable_investing(child["id"], ph)
    validate_error(res, "ERR_NOT_TEEN_ELIGIBLE")


# ─── corner state_machines: closed account rejects orders ───────────────────
def test_closed_investment_account_rejects_orders(api):
    """PRD 3.8: "an order on a closed account is rejected with `ERR_ACCOUNT_CLOSED`."
    PRD 3.8: "On close the account's `status` becomes `CLOSED`, any remaining `cash_cents` is swept back into the child's save jar `balance_cents"

    Design: Corner/state_machines/investment_close_terminal_lockdown_rejects_orders
    """
    fam, child, inv, ph = setup_teen_investment_account(
        cash_cents=5000, save_seed_cents=8000, clock_iso="2026-06-26T00:00:00Z",
        deposit_cents=20_000)
    validate_success(api.close_investment_account(inv["id"], ph), 200)

    res = api.place_order(inv["id"], order_payload("BUY", "AAA", 1000, 100), ph)
    validate_error(res, "ERR_ACCOUNT_CLOSED")


# ─── corner validations: close with holdings ────────────────────────────────
def test_close_with_holdings_rejected(api):
    """PRD 3.8: "It is permitted only when the account is `ACTIVE` and every symbol in `holdings` is empty — that is, every symbol's `shares_milli` is zero; an attempt to close with any non-empty holding is rejected with `ERR_HOLDINGS_NOT_EMPTY`."

    Design: Corner/validations/close_with_holdings_returns_holdings_not_empty
    """
    fam, child, inv, ph = setup_teen_investment_account(
        cash_cents=10_000, save_seed_cents=20_000, clock_iso="2026-06-26T00:00:00Z",
        deposit_cents=50_000)
    validate_success(api.place_order(inv["id"], order_payload("BUY", "DDD", 1000, 5000), ph), 201)

    res = api.close_investment_account(inv["id"], ph)
    validate_error(res, "ERR_HOLDINGS_NOT_EMPTY")
    inv_after = validate_success(api.get_investment_account(inv["id"], ph), 200)
    assert inv_after["status"] == "ACTIVE"


# ─── corner entities: is_teen computed at exactly 13 ────────────────────────
def test_is_teen_true_at_exactly_13_years(api):
    """PRD 3.2: "from it the server derives `is_teen`, a boolean that is true once the difference between the logical clock's current instant and the `birthdate` is at least thirteen years"

    Design: Corner/entities/is_teen_computed_true_at_exact_13_years
    """
    set_clock("2026-06-26T00:00:00Z")
    fam, child, ph = setup_family_with_child(deposit_cents=0, birthdate="2013-06-26")  # exactly 13

    read = validate_success(api.get_child_account(child["id"], ph), 200)
    assert read["is_teen"] is True
