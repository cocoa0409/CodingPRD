"""Calculation rules (PRD 3.7, 3.8; scaffold 1.3)."""
from util import mul_round


def prize_payout_calc(ticket, game, payout_option):
    """
    Returns dict with gross_payout_cents, federal_withholding_cents,
    state_withholding_cents, net_payout_cents, annual_installment_cents.

    STEP 1 — gross_payout (taxable basis):
      CASH + JACKPOT  -> round_half_up(G * cash_option_factor)
      CASH + non-JCK  -> G
      ANNUITY (JCK)   -> G
    STEP 2 — withholding gate on the ADVERTISED gross G (not on gross_payout):
      G >= T -> federal = round_half_up(gross_payout * rf)
                state   = round_half_up(gross_payout * rs)
      else   -> 0, 0
    STEP 3 — net = gross_payout - (federal + state)   [pinned order]
    STEP 4 — ANNUITY: annual = floor(net / annuity_years); CASH: 0
    """
    G = ticket["gross_prize_cents"]
    game_type = game["game_type"]
    F = game["cash_option_factor"]
    Y = game["annuity_years"]
    T = game["federal_withholding_threshold_cents"]
    rf = game["federal_withholding_rate"]
    rs = game["state_withholding_rate"]

    # STEP 1
    if payout_option == "CASH":
        if game_type == "JACKPOT":
            gross_payout = mul_round(G, F)
        else:
            gross_payout = G
    else:  # ANNUITY (jackpot only)
        gross_payout = G

    # STEP 2 — threshold gate on advertised G
    if G >= T:
        federal = mul_round(gross_payout, rf)
        state = mul_round(gross_payout, rs)
    else:
        federal = 0
        state = 0

    # STEP 3 — net (subtract summed withholding once)
    total_withheld = federal + state
    net = gross_payout - total_withheld

    # STEP 4 — annuity installment (floor)
    if payout_option == "ANNUITY":
        annual = net // Y  # floor division; net is non-negative in practice
    else:
        annual = 0

    return {
        "gross_payout_cents": gross_payout,
        "federal_withholding_cents": federal,
        "state_withholding_cents": state,
        "net_payout_cents": net,
        "annual_installment_cents": annual,
    }


def commission_settlement_calc(retailer, window_tickets):
    """
    PRD 3.8 settlement snapshot.

    gross_commission_cents =
        round_half_up( SUM(price_cents over ALL window tickets) * commission_rate )   # sum-then-round
      + SUM( round_half_up(gross_prize_cents * cashing_bonus_rate)                      # round-then-sum
             for PAID_AT_COUNTER window tickets )

    clawback_cents =
        SUM( round_half_up(gross_prize_cents * cashing_bonus_rate)
             for COUNTER_REVERSED window tickets )

    net_settlement_cents = max(0, gross - clawback)
    """
    commission_rate = retailer["commission_rate"]
    cashing_bonus_rate = retailer["cashing_bonus_rate"]

    # Sales-commission half: sum first, then round once.
    total_price = sum(t["price_cents"] for t in window_tickets)
    sales_commission = mul_round(total_price, commission_rate)

    # Cashing-bonus half: round per ticket, then sum.
    bonus_sum = 0
    for t in window_tickets:
        if t["validation_status"] == "PAID_AT_COUNTER":
            bonus_sum += mul_round(t["gross_prize_cents"], cashing_bonus_rate)

    gross_commission = sales_commission + bonus_sum

    clawback = 0
    for t in window_tickets:
        if t["validation_status"] == "COUNTER_REVERSED":
            clawback += mul_round(t["gross_prize_cents"], cashing_bonus_rate)

    net = max(0, gross_commission - clawback)

    return {
        "gross_commission_cents": gross_commission,
        "clawback_cents": clawback,
        "net_settlement_cents": net,
    }
