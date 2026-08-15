"""Equity dual-basis divergence, maintenance concentration add-ons, buying power."""
from test_helpers import (
    api_client,
    create_security_profile,
    deposit,
    get_account,
    place_order,
    post_mark,
    post_marks_both,
    setup_funded_account,
    TEST_USERS,
)


def test_equity_realtime_vs_official_diverge_on_realtime_move(api):
    """PRD §2.6: "Identical positions can therefore yield two different
    equities when realtime and official marks diverge — an account can look
    healthy intraday and still be called at the close."
    PRD §3.5: "Equity is the same formula on both bases: `cash_balance_cents`,
    plus the sum of long market values, minus the sum of the absolute values of
    short market values ..."

    Design: Difficulty/dual_variant_calc/equity_realtime_vs_official_close_diverge_on_same_positions
    """
    security = create_security_profile(symbol="ABC")
    post_marks_both(security["id"], 10_000)
    customer, account_id = setup_funded_account(1_000_000)
    place_order(account_id, customer["id"], security["id"], "BUY", 200)

    post_mark(security["id"], "REALTIME", 9_000)
    account = get_account(account_id)
    # cash -1000000 + 200*9000 = 800000 realtime; cash -1000000 + 200*10000
    # = 1000000 official.
    assert account["equity_realtime_cents"] == 800_000
    assert account["equity_official_cents"] == 1_000_000
    assert account["equity_realtime_cents"] != account["equity_official_cents"]


def test_equity_realtime_uses_latest_realtime_mark_only(api):
    """PRD §2.6: "The current mark for a security on a given basis is the mark
    of that type with the latest `marked_at`; if two marks of the same type
    share a `marked_at`, the one with the earlier `created_at` wins."
    PRD §3.5: "The realtime variant is stored as `equity_realtime_cents` and
    serves trade gating, buying power, and realtime reads; the official variant
    is stored as `equity_official_cents` and is the basis of every call
    decision."

    Design: Difficulty/dual_variant_calc/equity_realtime_vs_official_close_diverge_on_same_positions
    """
    security = create_security_profile(symbol="ABC")
    post_marks_both(security["id"], 10_000)
    customer, account_id = setup_funded_account(1_000_000)
    place_order(account_id, customer["id"], security["id"], "BUY", 200)

    # A second REALTIME mark supersedes the first for the realtime basis.
    post_mark(security["id"], "REALTIME", 11_000)
    account = get_account(account_id)
    assert account["equity_realtime_cents"] == 1_200_000  # -1000000 + 200*11000
    assert account["equity_official_cents"] == 1_000_000  # unchanged


def test_maintenance_concentration_high_band_adds_2000bps(api):
    """PRD §3.5: "A concentrated long adds 1,000 basis points when its share
    stays at or under seventy-five percent of gross long market value ... and
    adds 2,000 basis points when strictly above that band. The position's house
    percentage is `house_maint_long_bps` or `house_maint_short_bps`, chosen by
    side, plus the add-on; its house requirement line uses the greater of the
    regulatory percentage and that house percentage, rounded half up per line
    in the same way."

    Design: Difficulty/combinatorial_formula/maintenance_requirement_mode_a_tiered_concentration_nesting
    """
    # Single long position = 100% share of gross long -> strictly above 75%
    # band -> +2000bps addon; house 3000 + 2000 = 5000bps on mv 1000000.
    ctx_security = create_security_profile(symbol="ABC", concentration_threshold_bps=6000)
    post_marks_both(ctx_security["id"], 10_000)
    customer, account_id = setup_funded_account(1_000_000)
    place_order(account_id, customer["id"], ctx_security["id"], "BUY", 100)
    account = get_account(account_id)
    assert account["house_req_official_cents"] == 500_000
    assert account["reg_req_official_cents"] == 250_000


def test_maintenance_concentration_mid_band_adds_1000bps(api):
    """PRD §3.5: "A long position is "concentrated" when its market value
    multiplied by ten thousand strictly exceeds the security's
    `concentration_threshold_bps` multiplied by the account's gross long market
    value on the same basis ... A concentrated long adds 1,000 basis points when
    its share stays at or under seventy-five percent of gross long market value
    — precisely, when its market value times ten thousand is less than or equal
    to 7,500 times the gross long market value — and adds 2,000 basis points
    when strictly above that band."

    Design: Difficulty/combinatorial_formula/maintenance_requirement_mode_a_tiered_concentration_nesting
    """
    # Two positions with shares 70% / 30% of gross long: the 70% position is
    # above the 6000bps threshold but at-or-under 75% -> +1000bps addon.
    abc = create_security_profile(symbol="ABC", concentration_threshold_bps=6000)
    xyz = create_security_profile(symbol="XYZ", concentration_threshold_bps=6000)
    post_marks_both(abc["id"], 10_000)
    post_marks_both(xyz["id"], 10_000)
    customer, account_id = setup_funded_account(1_200_000)
    place_order(account_id, customer["id"], abc["id"], "BUY", 70)   # mv 700000
    place_order(account_id, customer["id"], xyz["id"], "BUY", 30)   # mv 300000
    account = get_account(account_id)
    # ABC line: 700000 * 4000/10000 = 280000; XYZ line: 300000 * 3000/10000 = 90000.
    assert account["house_req_official_cents"] == 370_000
    # Reg flat 2500bps on each line: 175000 + 75000.
    assert account["reg_req_official_cents"] == 250_000


def test_buying_power_zero_for_fully_margined_non_pdt_account(api):
    """PRD §3.5: "When the flag is false, `buying_power_cents` is twice the
    amount by which `equity_realtime_cents` exceeds the Regulation T initial
    requirement on realtime marks — 5,000 basis points of the combined gross
    long and gross short realtime market value, rounded half up — again floored
    at zero."

    Design: Corner/calculations/buying_power_doubles_non_pdt_reg_t_excess
    """
    security = create_security_profile(symbol="ABC")
    post_marks_both(security["id"], 10_000)
    customer, account_id = setup_funded_account(1_000_000)
    place_order(account_id, customer["id"], security["id"], "BUY", 200)
    account = get_account(account_id)
    assert account["equity_realtime_cents"] == 1_000_000
    # Reg T initial = 50% of 2000000 = 1000000; excess 0 -> buying power 0.
    assert account["buying_power_cents"] == 0


def test_buying_power_positive_when_equity_exceeds_initial_requirement(api):
    """PRD §3.5: "When the flag is false, `buying_power_cents` is twice the
    amount by which `equity_realtime_cents` exceeds the Regulation T initial
    requirement on realtime marks — 5,000 basis points of the combined gross
    long and gross short realtime market value, rounded half up — again floored
    at zero."

    Design: Corner/calculations/buying_power_doubles_non_pdt_reg_t_excess
    """
    security = create_security_profile(symbol="ABC")
    post_marks_both(security["id"], 10_000)
    customer, account_id = setup_funded_account(2_000_000)
    place_order(account_id, customer["id"], security["id"], "BUY", 200)
    account = get_account(account_id)
    # equity = 2000000; initial req = 1000000; bp = 2 * 1000000.
    assert account["equity_realtime_cents"] == 2_000_000
    assert account["buying_power_cents"] == 2_000_000
