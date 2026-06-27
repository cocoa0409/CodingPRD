"""Odds conversion, combined-odds rounding, payout floor, and the dual-variant
cash-out vs settlement valuations.

Covers difficulty rules dual_variant_calc and combinatorial_formula, plus the
corner calculation claims that are not owned by a difficulty stub.
"""
import math

from test_helpers import (
    fixtures as fx,
    factories as f,
    make_bettor_headers,
    validate_success, validate_error,
    ApiErrorId,
)


# ---------------------------------------------------------------------------
# Difficulty/dual_variant_calc/cashout_value_diverges_from_settlement_payout
# ---------------------------------------------------------------------------
def test_cashout_uses_current_line_not_locked_placement_odds(api):
    """PRD §3.9: "The cash-out offer is valued against current prices, not the
    locked placement odds, which is what makes it a different number from a
    settlement payout on the same ticket." and "It multiplies the stake_cents by
    that current product to get a gross expected value, then applies a book
    retention factor of 0.92 and takes the floor, yielding the cash-out value in
    integer cents. That amount becomes the bet's actual_payout_cents".

    Bet placed @+200; line moved to +150 (decimal 2.5); cash-out =
    floor(5000 * 2.5 * 0.92) = 11500, distinct from a settlement WON payout of
    floor(5000 * 3.0) = 15000.

    Design: Difficulty/dual_variant_calc/cashout_value_diverges_from_settlement_payout
    """
    acct, ev, mkt, sel, bet, v = fx.setup_single_bet(stake_cents=5000, american_odds=200,
                                                      liability_cap_cents=9_000_000)
    # Move the current line to +150 before cashing out.
    validate_success(api.reprice_selection(sel["id"], f.reprice_payload(150), fx.OPS))
    v = fx.get_account(acct["id"])["version"]

    resp = api.cash_out_bet(bet["id"], {"expected_account_version": v}, make_bettor_headers(acct["id"]))
    data = validate_success(resp, 200)
    assert data["status"] == "CASHED_OUT", f"expected CASHED_OUT, got {data['status']}"
    assert data["actual_payout_cents"] == 11500, (
        f"cash-out at current +150 (2.5)*0.92 should be 11500, got {data['actual_payout_cents']}")


def test_settlement_payout_uses_locked_placement_odds(api):
    """PRD §3.10: "This settlement payout is deliberately distinct from a
    cash-out: settlement evaluates locked placement odds over the real graded
    results, whereas cash-out used live current odds and the retention discount,
    so the two produce different numbers on an identical stake."
    PRD §3.10: "If every leg resolved to WON, PUSH, or VOID with at least one
    WON, the bet is WON and is paid."

    The same SINGLE @+200 (locked decimal 3.0) settled WON pays
    floor(5000 * 3.0) = 15000 — the divergent counterpart to the 11500 cash-out.

    Design: Difficulty/dual_variant_calc/cashout_value_diverges_from_settlement_payout
    """
    acct, ev, mkt, sel, bet, v = fx.setup_single_bet(stake_cents=5000, american_odds=200,
                                                      liability_cap_cents=90_000_000)
    fx.take_event_live(ev["id"])
    # AWAY @+200 wins when away_score > home_score.
    fx.settle_event(ev["id"], home_score=90, away_score=110)
    data = validate_success(api.get_bet(bet["id"], make_bettor_headers(acct["id"])), 200)
    assert data["status"] == "WON", f"expected WON, got {data['status']}"
    assert data["actual_payout_cents"] == 15000, (
        f"settlement at locked +200 (3.0) should pay 15000, got {data['actual_payout_cents']}")


# ---------------------------------------------------------------------------
# Difficulty/dual_variant_calc/net_loss_limit_diverges_from_gross_wager_limit
# ---------------------------------------------------------------------------
def test_net_loss_limit_accepts_stake_after_prior_winning_bet(api):
    """PRD §3.7: "If the account holds an ACTIVE NET_LOSS_LIMIT control, the
    platform instead computes a net figure: over every bet of the account that
    has settled within the window, it sums each bet's stake_cents minus its
    actual_payout_cents — a positive contribution for a net loss, a negative one
    for a net win, so a winning settled bet reduces the running loss — then adds
    the about-to-be-placed stake as worst-case prospective loss; if that
    projected total exceeds the control's limit_cents, the placement is rejected
    with ERR_NET_LOSS_LIMIT_EXCEEDED."
    PRD §3.7: "Both limit boundaries are strict greater-than, so a figure exactly
    at the limit is allowed."

    NET_LOSS_LIMIT 10000; prior bet stake 6000 settled WON (payout 18000) →
    running net = -12000; new 5000 stake → projected -7000 <= 10000 → ACCEPTED.

    Design: Difficulty/dual_variant_calc/net_loss_limit_diverges_from_gross_wager_limit
    """
    acct, v = fx.create_funded_bettor(deposit_cents=100_000)
    # ACTIVE NET_LOSS_LIMIT DAILY 10000.
    ctrl = fx.set_rg_control(acct["id"], "NET_LOSS_LIMIT", v, period="DAILY", limit_cents=10000)
    v = fx.get_account(acct["id"])["version"]

    ev1, mkt1, sel1 = fx.create_board(american_odds=200, liability_cap_cents=90_000_000)
    fx.place_bet(acct["id"], "SINGLE", 6000, [sel1["id"]], v)
    fx.take_event_live(ev1["id"])
    fx.settle_event(ev1["id"], home_score=90, away_score=110)  # AWAY @+200 wins, pays 18000
    v = fx.get_account(acct["id"])["version"]
    fx.submit_geo_check(acct["id"])

    ev2, mkt2, sel2 = fx.create_board(american_odds=200, liability_cap_cents=90_000_000,
                                      starts_at="2026-02-02T18:00:00Z")
    resp = api.create_bet(
        f.bet_payload(acct["id"], "SINGLE", 5000, [sel2["id"]], v),
        make_bettor_headers(acct["id"]))
    data = validate_success(resp, 201)
    assert data["status"] == "PLACED", (
        f"net-loss running -12000 + 5000 = -7000 <= 10000 must be accepted, got {data['status']}")


def test_wager_limit_rejects_gross_stake_over_limit(api):
    """PRD §3.7: "If the account holds an ACTIVE WAGER_LIMIT control, the
    platform sums the gross stake_cents of every bet placed within the rolling
    window ... and rejects the placement with ERR_WAGER_LIMIT_EXCEEDED if that
    gross window total plus the new stake would exceed the control's limit_cents.
    This gross wager tally ignores winnings entirely."

    Same betting shape as the net-loss case but a WAGER_LIMIT of 10000: prior
    placed stake 6000 + new 5000 = 11000 gross > 10000 → rejected. The gross tally
    diverges from the net figure.

    Design: Difficulty/dual_variant_calc/net_loss_limit_diverges_from_gross_wager_limit
    """
    acct, v = fx.create_funded_bettor(deposit_cents=100_000)
    fx.set_rg_control(acct["id"], "WAGER_LIMIT", v, period="DAILY", limit_cents=10000)
    v = fx.get_account(acct["id"])["version"]

    ev1, mkt1, sel1 = fx.create_board(american_odds=200, liability_cap_cents=90_000_000)
    fx.place_bet(acct["id"], "SINGLE", 6000, [sel1["id"]], v)
    v = fx.get_account(acct["id"])["version"]
    fx.submit_geo_check(acct["id"])

    ev2, mkt2, sel2 = fx.create_board(american_odds=200, liability_cap_cents=90_000_000,
                                      starts_at="2026-02-02T18:00:00Z")
    resp = api.create_bet(
        f.bet_payload(acct["id"], "SINGLE", 5000, [sel2["id"]], v),
        make_bettor_headers(acct["id"]))
    validate_error(resp, ApiErrorId.ERR_WAGER_LIMIT_EXCEEDED.value)


# ---------------------------------------------------------------------------
# Difficulty/combinatorial_formula/parlay_combined_odds_round_once_not_per_partial_product
# ---------------------------------------------------------------------------
def test_parlay_combined_odds_rounded_once_at_the_end(api):
    """PRD §3.7: "for a parlay or same-game parlay, it is the product of every
    leg's decimal_odds_at_placement taken in ascending created_at order, where
    each per-leg factor is already rounded to four places and only the final
    product is rounded half-up to four places — intermediate partial products are
    never re-rounded."
    PRD §3.7: "The potential_payout_cents — the gross return if every leg wins —
    is the floor of stake_cents multiplied by combined_decimal_odds."

    2-leg PARLAY of -150 (1.6667) and +200 (3.0): 1.6667 * 3.0 = 5.0001 rounded
    once; potential_payout for stake 2000 = floor(2000 * 5.0001) = 10000.

    Design: Difficulty/combinatorial_formula/parlay_combined_odds_round_once_not_per_partial_product
    """
    acct, v = fx.create_funded_bettor(deposit_cents=100_000)
    ev1, mkt1, sel1 = fx.create_board(sport="NFL", selection_name="HOME", american_odds=-150,
                                      liability_cap_cents=90_000_000)
    ev2, mkt2, sel2 = fx.create_board(sport="NFL", selection_name="AWAY", american_odds=200,
                                      liability_cap_cents=90_000_000,
                                      starts_at="2026-02-01T20:00:00Z")
    resp = api.create_bet(
        f.bet_payload(acct["id"], "PARLAY", 2000, [sel1["id"], sel2["id"]], v),
        make_bettor_headers(acct["id"]))
    data = validate_success(resp, 201)
    assert data["combined_decimal_odds"] == 5.0001, (
        f"1.6667*3.0 rounded once == 5.0001, got {data['combined_decimal_odds']}")
    assert data["potential_payout_cents"] == 10000, (
        f"floor(2000*5.0001) == 10000, got {data['potential_payout_cents']}")


def test_parlay_combined_odds_consistent_with_single_leg_factors(api):
    """PRD §2.8: "American odds are converted to decimal odds with a fixed rule.
    For positive American odds, the decimal odds equal one plus the American odds
    divided by 100. For non-positive American odds (which always have magnitude at
    least 100), the decimal odds equal one plus 100 divided by the absolute value
    of the American odds. The resulting decimal odds are rounded half-up to four
    decimal places."

    A second 2-leg PARLAY built from the same -150 and +200 factors must again
    produce 5.0001 — confirming the once-rounded product and not 5.0000 from
    re-rounding partials.

    Design: Difficulty/combinatorial_formula/parlay_combined_odds_round_once_not_per_partial_product
    """
    acct, v = fx.create_funded_bettor(deposit_cents=100_000)
    ev1, mkt1, sel1 = fx.create_board(sport="MLB", selection_name="HOME", american_odds=-150,
                                      liability_cap_cents=90_000_000)
    ev2, mkt2, sel2 = fx.create_board(sport="MLB", selection_name="AWAY", american_odds=200,
                                      liability_cap_cents=90_000_000,
                                      starts_at="2026-02-03T20:00:00Z")
    resp = api.create_bet(
        f.bet_payload(acct["id"], "PARLAY", 1000, [sel1["id"], sel2["id"]], v),
        make_bettor_headers(acct["id"]))
    data = validate_success(resp, 201)
    assert data["combined_decimal_odds"] == 5.0001, (
        f"product rounded once must be 5.0001, got {data['combined_decimal_odds']}")
    assert data["potential_payout_cents"] == math.floor(1000 * 5.0001) == 5000, (
        f"floor(1000*5.0001)==5000, got {data['potential_payout_cents']}")


# ---------------------------------------------------------------------------
# Difficulty/combinatorial_formula/settlement_effective_odds_drop_push_legs_then_apply
# ---------------------------------------------------------------------------
def test_settlement_drops_push_legs_then_multiplies_won_legs(api):
    """PRD §3.10: "The winning payout is computed by first dropping the
    non-winning legs — each PUSH or VOID leg is treated as decimal 1.0 and
    effectively removed from the parlay while each WON leg keeps its
    decimal_odds_at_placement — multiplying the surviving factors in ascending
    created_at leg order, rounding that effective odds half-up to four places, and
    taking the floor of stake_cents multiplied by that effective figure as the
    actual_payout_cents".
    PRD §3.10: "If every leg resolved to WON, PUSH, or VOID with at least one WON,
    the bet is WON and is paid."

    PARLAY (HOME -150 WON, OVER +200 PUSH on a TOTAL landing exactly on the line):
    effective = 1.6667, payout = floor(2000 * 1.6667) = 3333.

    Design: Difficulty/combinatorial_formula/settlement_effective_odds_drop_push_legs_then_apply
    """
    acct, v = fx.create_funded_bettor(deposit_cents=100_000)
    ev1, mkt1, sel1 = fx.create_board(selection_name="HOME", american_odds=-150,
                                      liability_cap_cents=90_000_000)
    ev2 = fx.create_event(sport="NBA", starts_at="2026-02-01T20:00:00Z")
    mkt2 = fx.create_market(ev2["id"], market_type="TOTAL", line=50.0, liability_cap_cents=90_000_000)
    sel2 = fx.create_selection(mkt2["id"], "OVER", 200)

    bet = fx.place_bet(acct["id"], "PARLAY", 2000, [sel1["id"], sel2["id"]], v)

    fx.take_event_live(ev1["id"])
    fx.settle_event(ev1["id"], home_score=100, away_score=90)   # HOME -150 WON
    fx.take_event_live(ev2["id"])
    fx.settle_event(ev2["id"], home_score=25, away_score=25)    # total 50 → OVER 50.0 PUSH

    data = validate_success(api.get_bet(bet["id"], make_bettor_headers(acct["id"])), 200)
    assert data["status"] == "WON", f"expected WON, got {data['status']}"
    assert data["actual_payout_cents"] == 3333, (
        f"effective 1.6667 (push leg dropped) floor*2000 == 3333, got {data['actual_payout_cents']}")


def test_settlement_won_payout_after_dropped_push_distinct_from_full_parlay(api):
    """PRD §3.10: "each PUSH or VOID leg is treated as decimal 1.0 and effectively
    removed from the parlay while each WON leg keeps its decimal_odds_at_placement"

    The dropped-push payout (3333) is neither the full 2-leg parlay return nor 0:
    a settled losing leg would give 0, but a pushed leg is removed and the bet is
    paid on the surviving WON leg's locked odds only.

    Design: Difficulty/combinatorial_formula/settlement_effective_odds_drop_push_legs_then_apply
    """
    acct, v = fx.create_funded_bettor(deposit_cents=100_000)
    ev1, mkt1, sel1 = fx.create_board(selection_name="HOME", american_odds=-150,
                                      liability_cap_cents=90_000_000)
    ev2 = fx.create_event(sport="NBA", starts_at="2026-02-01T21:00:00Z")
    mkt2 = fx.create_market(ev2["id"], market_type="TOTAL", line=50.0, liability_cap_cents=90_000_000)
    sel2 = fx.create_selection(mkt2["id"], "OVER", 200)

    bet = fx.place_bet(acct["id"], "PARLAY", 2000, [sel1["id"], sel2["id"]], v)

    fx.take_event_live(ev1["id"])
    fx.settle_event(ev1["id"], home_score=100, away_score=90)
    fx.take_event_live(ev2["id"])
    fx.settle_event(ev2["id"], home_score=25, away_score=25)

    data = validate_success(api.get_bet(bet["id"], make_bettor_headers(acct["id"])), 200)
    assert data["actual_payout_cents"] == 3333, (
        f"expected 3333 from the single surviving WON leg, got {data['actual_payout_cents']}")
    assert data["actual_payout_cents"] != 0, "a pushed leg must not grade the bet LOST"


# ---------------------------------------------------------------------------
# Corner/calculations/american_to_decimal_negative_odds_correct
# ---------------------------------------------------------------------------
def test_negative_american_odds_decimal_in_single_payout(api):
    """PRD §2.8: "For non-positive American odds (which always have magnitude at
    least 100), the decimal odds equal one plus 100 divided by the absolute value
    of the American odds. The resulting decimal odds are rounded half-up to four
    decimal places."

    Selection -150 → decimal 1.6667; a SINGLE stake 5000 yields
    floor(5000 * 1.6667) = 8333, exposing the conversion through the payout path.

    Design: Corner/calculations/american_to_decimal_negative_odds_correct
    """
    acct, v = fx.create_funded_bettor(deposit_cents=100_000)
    ev, mkt, sel = fx.create_board(selection_name="HOME", american_odds=-150,
                                   liability_cap_cents=90_000_000)
    resp = api.create_bet(
        f.bet_payload(acct["id"], "SINGLE", 5000, [sel["id"]], v),
        make_bettor_headers(acct["id"]))
    data = validate_success(resp, 201)
    assert data["combined_decimal_odds"] == 1.6667, (
        f"-150 → 1.6667, got {data['combined_decimal_odds']}")
    assert data["potential_payout_cents"] == 8333, (
        f"floor(5000*1.6667) == 8333, got {data['potential_payout_cents']}")


# ---------------------------------------------------------------------------
# Corner/calculations/potential_payout_floor_not_round_up
# ---------------------------------------------------------------------------
def test_potential_payout_floors_never_rounds_up(api):
    """PRD §2.8: "Wherever the platform pays out, it computes the integer cents
    return by taking the floor of the product of stake and the applicable decimal
    odds — that is, it truncates any fractional cent rather than rounding up, so
    the book never rounds a potential return upward in the bettor's favor."

    SINGLE stake 5000 @-150 (1.6667): floor(5000*1.6667)=8333, never 8334.

    Design: Corner/calculations/potential_payout_floor_not_round_up
    """
    acct, v = fx.create_funded_bettor(deposit_cents=100_000)
    ev, mkt, sel = fx.create_board(selection_name="HOME", american_odds=-150,
                                   liability_cap_cents=90_000_000)
    resp = api.create_bet(
        f.bet_payload(acct["id"], "SINGLE", 5000, [sel["id"]], v),
        make_bettor_headers(acct["id"]))
    data = validate_success(resp, 201)
    assert data["combined_decimal_odds"] == 1.6667
    assert data["potential_payout_cents"] == 8333, (
        f"floor must give 8333, not 8334, got {data['potential_payout_cents']}")
