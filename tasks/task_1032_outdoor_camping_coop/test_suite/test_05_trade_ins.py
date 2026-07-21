"""Trade-in dual payout variants (instant vs consignment) and the offer/counter
negotiation cycle.

Queue-A depth: dual_variant_calc (trade-in), non_linear_state_machine (counter cycle).
"""
import pytest
from test_helpers import (
    new_member, new_gear_sku, submit_trade_in, appraise, respond, sell,
)


# ─── dual_variant_calc / trade_in_instant_vs_consignment_payout_diverge ────

def test_instant_credit_payout_at_accept(api):
    """PRD §3.4: "Appraisal computes two figures from that value: the
    instant_credit_cents, equal to the appraised value multiplied by forty percent
    and rounded to whole cents".
    PRD §3.4: "For INSTANT_CREDIT, the payout_cents is set to the instant_credit_cents
    and that amount is immediately added to the member's store_credit_cents."

    Appraised 20000 -> instant_credit 8000, paid at accept.

    Design: Difficulty/dual_variant_calc/trade_in_instant_vs_consignment_payout_diverge
    """
    member = new_member()
    sku = new_gear_sku(name="3P Tent", category="TENT", price_cents=30000)
    ti = submit_trade_in(member, sku["id"], condition="GOOD", method="INSTANT_CREDIT")
    appraise(ti["id"], 20000)
    accepted = respond(member, ti["id"], "ACCEPT")
    assert accepted["instant_credit_cents"] == 8000
    assert accepted["payout_cents"] == 8000


def test_consignment_payout_at_sell_diverges(api):
    """PRD §3.4: "The sale supplies resale_price_cents, moves the trade-in from
    LISTED to SOLD, sets payout_cents to the resale price multiplied by sixty-five
    percent and rounded to whole cents, and adds that payout_cents to the member's
    store_credit_cents."
    PRD §3.4: "the informational consignment_estimate_cents, equal to the appraised
    value multiplied by sixty-five percent and rounded to whole cents."

    Appraised 20000 -> consignment_estimate 13000; resale 24000 -> payout 15600.

    Design: Difficulty/dual_variant_calc/trade_in_instant_vs_consignment_payout_diverge
    """
    member = new_member()
    sku = new_gear_sku(name="3P Tent", category="TENT", price_cents=30000)
    ti = submit_trade_in(member, sku["id"], condition="GOOD", method="CONSIGNMENT")
    appraised = appraise(ti["id"], 20000)
    assert appraised["consignment_estimate_cents"] == 13000
    respond(member, ti["id"], "ACCEPT")   # CONSIGNMENT -> LISTED
    sold = sell(ti["id"], 24000)
    assert sold["payout_cents"] == 15600


# ─── non_linear_state_machine / trade_in_offer_counter_cycle ───────────────

def _countered_then_reappraised():
    member = new_member()
    sku = new_gear_sku(name="Down Bag", category="APPAREL", price_cents=25000)
    ti = submit_trade_in(member, sku["id"], condition="LIKE_NEW", method="CONSIGNMENT")
    appraise(ti["id"], 15000)                          # SUBMITTED -> OFFERED
    respond(member, ti["id"], "COUNTER", counter_cents=18000)  # OFFERED -> COUNTERED
    reappraised = appraise(ti["id"], 17000)            # COUNTERED -> OFFERED
    return reappraised


def test_counter_returns_to_offered_after_reappraisal(api):
    """PRD §3.4: "A COUNTER action requires a counter_cents value; it moves the
    trade-in from OFFERED to COUNTERED and records the member's member_counter_cents.
    Staff may then re-appraise a COUNTERED item, which moves it back to OFFERED and
    updates appraised_value_cents, recomputing instant_credit_cents and
    consignment_estimate_cents; this pair of edges forms the negotiation cycle and
    may repeat."

    Design: Difficulty/non_linear_state_machine/trade_in_offer_counter_cycle
    """
    ti = _countered_then_reappraised()
    assert ti["status"] == "OFFERED"
    assert ti["appraised_value_cents"] == 17000
    assert ti["member_counter_cents"] == 18000


def test_reappraisal_recomputes_payout_figures(api):
    """PRD §3.4: "Staff may then re-appraise a COUNTERED item, which moves it back to
    OFFERED and updates appraised_value_cents, recomputing instant_credit_cents and
    consignment_estimate_cents".

    Re-appraised 17000 -> instant_credit round(17000*.40)=6800,
    consignment_estimate round(17000*.65)=11050.

    Design: Difficulty/non_linear_state_machine/trade_in_offer_counter_cycle
    """
    ti = _countered_then_reappraised()
    assert ti["instant_credit_cents"] == 6800
    assert ti["consignment_estimate_cents"] == 11050
