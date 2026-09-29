"""Quote construction (PRD 3.5) and cancellation settlement (PRD 3.9)."""
from decimal import Decimal

from db import store, touch, clock_date
from validation import round_half_up, round_up
from services import constants as C
from services import derive


def surcharge_rate(raw_subtotal_cents):
    """The band is resolved exactly once, from the pre-surcharge subtotal."""
    if raw_subtotal_cents < C.SURCHARGE_BAND_1_MAX:
        return C.SURCHARGE_RATE_LOW_BAND
    if raw_subtotal_cents < C.SURCHARGE_BAND_2_MAX:
        return C.SURCHARGE_RATE_MID_BAND
    return C.SURCHARGE_RATE_HIGH_BAND


def run_quote(booking):
    client = store.group_clients[booking["group_client_id"]]
    billable = derive.billable_head_count(booking)

    lines = [b for b in derive.blocks_of_booking(booking["id"]) if b["status"] != "ABANDONED"]

    discount = C.TIER_DISCOUNT_PCT[client["tier"]]
    factor = Decimal(1) - discount

    raw_subtotal = 0
    high_element_total = 0
    for block in lines:
        gross = Decimal(C.PHASE_RATE_CENTS[block["phase"]] * billable)
        # Round half up once per line, before the line enters the running sum.
        line_cents = round_half_up(gross * factor)
        raw_subtotal += line_cents
        if block["phase"] == "HIGH_ELEMENT":
            high_element_total += line_cents

    rate = surcharge_rate(raw_subtotal)
    surcharge = round_up(Decimal(high_element_total) * rate)
    quoted_total = raw_subtotal + surcharge
    deposit_required = round_up(Decimal(quoted_total) * C.DEPOSIT_PCT)

    booking["billable_head_count"] = billable
    booking["raw_subtotal_cents"] = raw_subtotal
    booking["high_element_surcharge_cents"] = surcharge
    booking["quoted_total_cents"] = quoted_total
    booking["deposit_required_cents"] = deposit_required
    booking["required_chaperone_count"] = derive.required_chaperone_count(booking)
    booking["quote_index"] = booking["quote_index"] + 1
    booking["status"] = "QUOTED"
    touch(booking)


def client_initiated_pct(notice_days):
    if notice_days >= 30:
        return C.CANCEL_TIER_30_PLUS_PCT
    if notice_days >= 14:
        return C.CANCEL_TIER_14_29_PCT
    if notice_days >= 7:
        return C.CANCEL_TIER_7_13_PCT
    return C.CANCEL_TIER_UNDER_7_PCT


def settle_cancellation(booking):
    """Records the notice, picks the variant, prices and caps the fee, then moves
    the ledger in one settled step."""
    notice_days = (booking["program_date"] - clock_date()).days
    variant = ("OPERATOR_WEATHER_INITIATED" if booking["status"] == "WEATHER_HOLD"
               else "CLIENT_INITIATED")

    allocated = booking["deposit_allocated_cents"]
    if variant == "OPERATOR_WEATHER_INITIATED":
        gross_fee = C.WEATHER_ADMIN_FEE_CENTS
    else:
        gross_fee = round_half_up(Decimal(allocated) * client_initiated_pct(notice_days))

    fee = min(gross_fee, allocated)
    refund = allocated - fee

    booking["notice_days_at_cancel"] = notice_days
    booking["cancellation_variant"] = variant
    booking["cancellation_fee_cents"] = fee
    booking["retained_cents"] = fee
    booking["deposit_allocated_cents"] = 0
    booking["refund_cents"] = refund
    booking["status"] = "CANCELLED"

    client = store.group_clients.get(booking["group_client_id"])
    if client is not None and refund:
        client["credit_balance_cents"] = client["credit_balance_cents"] + refund
    return client
