"""Claim adjudication / reversal engine (PRD §3.7, §3.8, §3.9)."""
import db
import errors
from services import calculations


def linked_copay_link(claim_id):
    """Return the single LINKED CopayLink referencing this claim, or None."""
    for link in db.copay_links.values():
        if link.get("claim_id") == claim_id and link["status"] == "LINKED":
            return link
    return None


def applied_copay_link(claim_id):
    """Return the APPLIED CopayLink referencing this claim, or None."""
    for link in db.copay_links.values():
        if link.get("claim_id") == claim_id and link["status"] == "APPLIED":
            return link
    return None


def adjudicate(claim):
    """SUBMITTED -> ADJUDICATED. Runs savings + copay offset + cascades."""
    card = db.discount_cards[claim["discount_card_id"]]
    pharmacy = db.pharmacies[claim["pharmacy_id"]]
    drug_id = card["drug_id"]

    quote = calculations.resolve_quote(card["pharmacy_id"], drug_id)
    if quote is None:
        # No active quote to price against — treat as a business validation failure.
        raise errors.validation("No active price quote to adjudicate against.")

    quantity = claim["quantity"]
    dispense = pharmacy["dispense_fee_cents"]
    bprice = calculations.basis_price(quote, card["pricing_basis"])

    gross = quantity * quote["cash_price_cents"] + dispense
    discounted = quantity * bprice + dispense

    # copay offset (if a LINKED link references this claim)
    link = linked_copay_link(claim["id"])
    offset = 0
    if link is not None:
        copay_card = db.copay_cards[link["copay_card_id"]]
        offset = calculations.copay_offset(copay_card, discounted)

    net = discounted - offset
    if net < 0:
        net = 0
    savings = gross - net

    claim["gross_cents"] = gross
    claim["net_cents"] = net
    claim["savings_cents"] = savings
    claim["copay_offset_cents"] = offset
    claim["status"] = "ADJUDICATED"
    db.touch(claim)

    # copay cascade: claim -> link -> copay card
    if link is not None:
        copay_card = db.copay_cards[link["copay_card_id"]]
        link["applied_offset_cents"] = offset
        link["status"] = "APPLIED"
        db.touch(link)
        copay_card["remaining_benefit_cents"] = copay_card["remaining_benefit_cents"] - offset
        if copay_card["remaining_benefit_cents"] <= 0 and copay_card["status"] == "ACTIVE":
            copay_card["status"] = "EXHAUSTED"
        db.touch(copay_card)

    # cascade: card ISSUED -> REDEEMED
    card["status"] = "REDEEMED"
    db.touch(card)

    # derived-field reconciliation
    calculations.recompute_lifetime_savings(card["member_id"])


def reject(claim):
    """SUBMITTED -> REJECTED. No pricing fields set."""
    claim["status"] = "REJECTED"
    db.touch(claim)


def reverse(claim):
    """ADJUDICATED -> REVERSED. Compensates copay draw, re-issues card, recomputes savings."""
    card = db.discount_cards[claim["discount_card_id"]]

    # compensation: copay link APPLIED -> RELEASED, restore copay card benefit
    link = applied_copay_link(claim["id"])
    if link is not None and link.get("applied_offset_cents", 0) > 0:
        copay_card = db.copay_cards[link["copay_card_id"]]
        restored = link["applied_offset_cents"]
        copay_card["remaining_benefit_cents"] = copay_card["remaining_benefit_cents"] + restored
        if copay_card["status"] == "EXHAUSTED" and copay_card["remaining_benefit_cents"] > 0:
            copay_card["status"] = "ACTIVE"
        db.touch(copay_card)
        link["status"] = "RELEASED"
        link["applied_offset_cents"] = 0
        db.touch(link)

    # claim ADJUDICATED -> REVERSED
    claim["status"] = "REVERSED"
    # cascade: card REDEEMED -> ISSUED (re-adjudicable)
    if card["status"] == "REDEEMED":
        card["status"] = "ISSUED"
        db.touch(card)

    # recompute lifetime savings (reversed claim no longer counts) — uses claim's
    # status which is now REVERSED, so it is excluded.
    db.touch(claim)  # version bump happens here (counts as the +1 on reverse)
    calculations.recompute_lifetime_savings(card["member_id"])
