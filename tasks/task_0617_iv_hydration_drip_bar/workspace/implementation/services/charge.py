"""Visit-charge waterfall (PRD §3.11 / scaffold calc visit_charge_waterfall).

Three stages over the drip line and the add-on lines (in addon_ids order):

  STEP 1  discount fraction by membership tier, only when a membership is
          present and its status == ACTIVE:
            NONE -> 0.000, GOLD -> 0.150, PLATINUM -> 0.225; else 0.

  STEP 2  credit waterfall (pinned order):
            drip_credit_used = 1 iff ACTIVE membership present AND
              covered_drip_tier == menu_item.tier AND drip_credits_remaining>0.
            addon_credits_used starts at 0; add-ons processed in order: each
              add-on is credit-covered iff addon_credits_remaining minus the
              add-on credits already used this visit > 0.

  STEP 3  cash lines = uncovered drip (if not credit-covered) + uncovered
          add-ons. Each cash line = round_half_up(list_price * (1 - disc)),
          rounded PER LINE then summed. Mobile surcharge of 9500 cents added
          for MOBILE (never discounted, never creditable).
"""
from decimal import Decimal, ROUND_HALF_UP

DISC = {"NONE": Decimal("0.000"), "GOLD": Decimal("0.150"), "PLATINUM": Decimal("0.225")}
MOBILE_SURCHARGE_CENTS = 9500


def _round_half_up(list_price_cents, disc):
    value = Decimal(list_price_cents) * (Decimal(1) - disc)
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def compute(appointment, menu_item, addon_records, membership):
    """Return dict: amount_charged_cents, drip_credit_used, addon_credits_used.

    membership is None for cash visits or a non-ACTIVE membership.
    """
    active_member = membership is not None and membership["status"] == "ACTIVE"

    # STEP 1 — discount fraction
    if active_member:
        disc = DISC.get(membership["tier"], Decimal("0.000"))
    else:
        disc = Decimal("0.000")

    # STEP 2 — credit waterfall
    drip_credit_used = 0
    addon_credits_used = 0
    drip_covered = False
    addon_covered = [False] * len(addon_records)

    if active_member:
        if (membership["covered_drip_tier"] == menu_item["tier"]
                and membership["drip_credits_remaining"] > 0):
            drip_credit_used = 1
            drip_covered = True

        for idx, _ao in enumerate(addon_records):
            if membership["addon_credits_remaining"] - addon_credits_used > 0:
                addon_covered[idx] = True
                addon_credits_used += 1
            # else stays a cash line

    # STEP 3 — cash lines, rounded per line then summed
    cash_subtotal = 0
    if not drip_covered:
        cash_subtotal += _round_half_up(menu_item["base_price_cents"], disc)
    for idx, ao in enumerate(addon_records):
        if not addon_covered[idx]:
            cash_subtotal += _round_half_up(ao["price_cents"], disc)

    surcharge = MOBILE_SURCHARGE_CENTS if appointment["location_type"] == "MOBILE" else 0
    amount = cash_subtotal + surcharge

    return {
        "amount_charged_cents": amount,
        "drip_credit_used": drip_credit_used,
        "addon_credits_used": addon_credits_used,
    }
