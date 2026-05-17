"""Cost calculations for claim submission and adjudication.

Implements two variants of the same cost formula, per SCAFFOLD §1.3:

- estimated_member_cost (forward-looking, run at submission)
- adjudicated_member_cost (chronological, run at adjudication)

Both use integer cents end-to-end and round half-up at each multiplication
step (channel discount, coinsurance) per PRD §2.5.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Optional

from ..validation import round_half_up_cents


def _channel_adjusted_allowed(
    *,
    unit_allowed_cents: int,
    quantity: int,
    channel: str,
    mail_order_discount_rate: float,
) -> int:
    allowed = int(unit_allowed_cents) * int(quantity)
    if channel == "MAIL_ORDER_90":
        allowed = round_half_up_cents(Decimal(str(allowed)) * Decimal(str(mail_order_discount_rate)))
    return allowed


def compute_cost(
    *,
    drug: dict,
    plan: dict,
    formulary_entry: Optional[dict],
    member: dict,
    claim_channel: str,
    claim_quantity: int,
    copay_card: Optional[dict],
    claim_drug_id: str,
    claim_member_id: str,
) -> dict:
    """Compute the per-claim cost block.

    The two variants (estimated vs adjudicated) differ only in *when* the
    member's YTD counters are read. The caller passes the member with the
    right snapshot of counters; the math here is identical.

    Returns a dict with:
        allowed_cents, deductible_portion, member_share_after_ded,
        member_pre_card, card_payable,
        member_cost_cents (final post-card),
        plan_paid_cents.
    """
    allowed = _channel_adjusted_allowed(
        unit_allowed_cents=drug["unit_allowed_cents"],
        quantity=claim_quantity,
        channel=claim_channel,
        mail_order_discount_rate=plan["mail_order_discount_rate"],
    )

    ytd_ded = int(member["ytd_deductible_paid_cents"])
    ytd_oop = int(member["ytd_oop_paid_cents"])
    deductible = int(plan["deductible_cents"])
    oop_max = int(plan["oop_max_cents"])

    deductible_remaining = max(deductible - ytd_ded, 0)
    deductible_portion = min(allowed, deductible_remaining)
    post_ded = allowed - deductible_portion

    # tier-driven member share of post-deductible spend
    tier = int(formulary_entry["tier"]) if formulary_entry else 5
    copay_cents = int(formulary_entry["copay_cents"]) if formulary_entry else 0
    if tier <= 2:
        # flat formulary copay, capped at the post-deductible balance
        member_share_after_ded = min(copay_cents, post_ded)
    else:
        coinsurance = Decimal(str(plan["coinsurance_rate"]))
        member_share_after_ded = round_half_up_cents(Decimal(str(post_ded)) * coinsurance)

    member_pre_card = deductible_portion + member_share_after_ded

    # OOP cap
    oop_remaining = max(oop_max - ytd_oop, 0)
    member_pre_card = min(member_pre_card, oop_remaining)

    # Copay card application — only if matching + ACTIVE
    card_payable = 0
    if copay_card is not None:
        if (
            copay_card["status"] == "ACTIVE"
            and copay_card["drug_id"] == claim_drug_id
            and copay_card["member_id"] == claim_member_id
        ):
            remaining_lifetime = int(copay_card["max_benefit_cents"]) - int(copay_card["used_cents"])
            card_payable = min(
                int(copay_card["per_claim_cap_cents"]),
                max(remaining_lifetime, 0),
                member_pre_card,
            )

    member_cost_cents = member_pre_card - card_payable
    # plan_paid = allowed - member_pre_card  (card pays the member's share, not the plan's)
    plan_paid_cents = allowed - member_pre_card

    return {
        "allowed_cents": allowed,
        "deductible_portion": deductible_portion,
        "member_share_after_ded": member_share_after_ded,
        "member_pre_card": member_pre_card,
        "card_payable": card_payable,
        "member_cost_cents": member_cost_cents,
        "plan_paid_cents": plan_paid_cents,
    }
