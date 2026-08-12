"""The seller settlement pricing engine (PRD 3.10)."""
import math

import config
from money import D, q2
from store import db, get, touch
from services.charges import add_charge_line, delete_settlement_lines
from services.consignments import consignment_lots

_FEED_RATE = {
    "NONE": D(0),
    "STARTER": config.FEED_RATE_STARTER,
    "GROWER": config.FEED_RATE_GROWER,
    "HAY": config.FEED_RATE_HAY,
}


def sold_lots(consignment_id):
    return [l for l in consignment_lots(consignment_id) if l["sale_status"] == "SOLD"]


def gross_amount(consignment_id):
    total = D(0)
    for lot in sold_lots(consignment_id):
        total += D(lot.get("extended_amount") or 0)
    return q2(total)


def sold_head(consignment_id):
    return sum(l["head_count"] for l in sold_lots(consignment_id))


# ------------------------------------------------------------- commission --
def seller_commission(consignment, gross, head):
    if consignment["commission_basis"] == "FLAT_PER_HEAD":
        return q2(config.COMMISSION_FLAT_PER_HEAD * D(head))
    gross = D(gross)
    if gross <= config.COMMISSION_TIER1_MAX:
        rate = config.COMMISSION_TIER1_PCT
    elif gross <= config.COMMISSION_TIER2_MAX:
        rate = config.COMMISSION_TIER2_PCT
    else:
        rate = config.COMMISSION_TIER3_PCT
    tiered = q2(gross * rate)
    floor = q2(config.MIN_COMMISSION_PER_HEAD * D(head))
    value = tiered if tiered > floor else floor
    return value if value < config.MAX_COMMISSION_PER_LOT else config.MAX_COMMISSION_PER_LOT


def commission_unit_rate(consignment, gross):
    if consignment["commission_basis"] == "FLAT_PER_HEAD":
        return config.COMMISSION_FLAT_PER_HEAD
    gross = D(gross)
    if gross <= config.COMMISSION_TIER1_MAX:
        return config.COMMISSION_TIER1_PCT
    if gross <= config.COMMISSION_TIER2_MAX:
        return config.COMMISSION_TIER2_PCT
    return config.COMMISSION_TIER3_PCT


# ----------------------------------------------------------- days on yard --
def lot_day_count(consignment, lot, close_instant):
    start = consignment.get("_checked_in_dt")
    if start is None:
        return config.YARDAGE_MIN_DAYS
    if lot is not None and lot["custody_status"] == "RELEASED" \
            and lot.get("_released_dt") is not None:
        end = lot["_released_dt"]
    else:
        end = close_instant
    seconds = (end - start).total_seconds()
    raw_days = seconds / 86400.0
    days = math.ceil(raw_days)
    return days if days > config.YARDAGE_MIN_DAYS else config.YARDAGE_MIN_DAYS


def days_on_yard(consignment, close_instant):
    """Adjudication of friction 1: the PRD does not pin which single day count
    a consignment-level yardage charge uses when its lots disagree. We take ONE
    consignment-level count from a representative end instant - the end instant
    of the consignment's earliest-created lot, the same ascending created_at
    ordering the feed charge walks - rather than summing per-lot counts.
    Summing would multiply the charge by the number of lots and make the
    stated formula (rate x billable head x day count) unreachable; one count
    keeps a single YARDAGE line with an observable `days` field, which is the
    reading that keeps the most declared behaviour reachable.
    """
    lots = consignment_lots(consignment["id"])
    representative = lots[0] if lots else None
    return lot_day_count(consignment, representative, close_instant)


# ---------------------------------------------------------------- yardage --
def billable_head(consignment):
    from services.consignments import head_in_lots
    return (head_in_lots(consignment["id"]) + consignment["head_withdrawn"]
            + consignment["head_dead"] + consignment["head_condemned"])


def yardage_charge(consignment, head, days):
    if consignment["yardage_basis"] == "PER_HEAD_DAY":
        return q2(config.YARDAGE_RATE_PER_HEAD_DAY * D(head) * D(days))
    return q2(config.YARDAGE_FLAT_PER_HEAD * D(head))


# ------------------------------------------------------------------- feed --
def feed_charge(consignment):
    """Rounding order is pinned: round EACH per-lot line, THEN sum."""
    rate = _FEED_RATE[consignment["ration_type"]]
    days = D(consignment["days_on_feed"])
    total = D(0)
    for lot in consignment_lots(consignment["id"]):
        if lot["sale_status"] == "WITHDRAWN":
            continue
        total += q2(rate * days * D(lot["head_count"]))
    return q2(total)


def feed_head(consignment):
    return sum(l["head_count"] for l in consignment_lots(consignment["id"])
               if l["sale_status"] != "WITHDRAWN")


# -------------------------------------------------------------- statutory --
def statutory_shares(head):
    state = q2(config.CHECKOFF_STATE_SHARE * D(head))
    national = q2(config.CHECKOFF_NATIONAL_SHARE * D(head))
    return state, national


def brand_fee(head):
    return q2(config.BRAND_FEE_PER_HEAD * D(head))


def indemnity_fee(gross):
    gross = D(gross)
    if gross <= 0:
        return q2(0)
    raw = q2(gross * config.INDEMNITY_PCT)
    value = raw if raw > config.INDEMNITY_MIN else config.INDEMNITY_MIN
    return value if value < config.INDEMNITY_MAX else config.INDEMNITY_MAX


# ----------------------------------------------------------------- offset --
def settlement_offset(settlement, sale_day_id, net_before_offset):
    """Pour the provisional net down the consignor's own unpaid invoices.

    Adjudication of friction 3: when two settlements of the same sale day
    belong to the same consignor and pour against the same candidate invoices,
    both pour against the SAME untouched balance_due. The PRD states plainly
    that "the pour does not itself change any invoice balance in this pass",
    so nothing a first pour did is visible to a second; reading balances as
    already reduced would contradict that sentence.
    """
    remaining = D(net_before_offset)
    if remaining <= 0:
        return q2(0)
    poured = D(0)
    candidates = []
    for invoice in sorted(db["buyer_invoices"].values(),
                          key=lambda r: (r["created_at"], r["_seq"])):
        if invoice["sale_day_id"] != sale_day_id:
            continue
        if invoice["status"] not in ("ISSUED", "PARTIALLY_PAID"):
            continue
        reg = get("buyer_registrations", invoice["buyer_registration_id"])
        if reg is None or reg["party_id"] != settlement["consignor_party_id"]:
            continue
        candidates.append(invoice)
    for invoice in candidates:
        if remaining <= 0:
            break
        balance = D(invoice["balance_due"])
        if balance <= 0:
            continue
        take = balance if balance < remaining else remaining
        poured += take
        remaining -= take
    return q2(poured)


# -------------------------------------------------------------------- net --
def settlement_net(settlement):
    return q2(D(settlement["gross_amount"])
              - D(settlement["commission_amount"])
              - D(settlement["yardage_amount"])
              - D(settlement["feed_amount"])
              - D(settlement["statutory_amount"])
              - D(settlement["brand_fee_amount"])
              - D(settlement["indemnity_fee_amount"])
              - D(settlement["advances_amount"])
              - D(settlement["offset_applied"])
              + D(settlement["adjustment_total"]))


def balance_ok(settlement):
    left = D(settlement["gross_amount"])
    right = (D(settlement["net_amount"])
             + D(settlement["commission_amount"])
             + D(settlement["yardage_amount"])
             + D(settlement["feed_amount"])
             + D(settlement["statutory_amount"])
             + D(settlement["brand_fee_amount"])
             + D(settlement["indemnity_fee_amount"])
             + D(settlement["advances_amount"])
             + D(settlement["offset_applied"])
             - D(settlement["adjustment_total"]))
    return q2(left) == q2(right)


# ------------------------------------------------------------- hop 5 body --
def price_settlement(settlement, close_instant, compute_offset=True):
    """Write the seller-side charge lines and compute every money field.

    Adjudication of friction 2: all seven seller-side lines are ALWAYS written,
    including a 0.00 FEED line on a NONE ration. The PRD says this hop
    "produces" lines of those seven types and leaves the zero case unstated;
    writing them unconditionally keeps every charge_type reachable and
    observable through the charge-line list filter, which is the reading that
    preserves the most declared behaviour.
    """
    consignment = get("consignments", settlement["consignment_id"])
    sale_day_id = consignment["sale_day_id"]
    gross = gross_amount(consignment["id"])
    head_sold = sold_head(consignment["id"])

    commission = seller_commission(consignment, gross, head_sold)
    days = settlement.get("_yardage_days")
    if days is None:
        days = days_on_yard(consignment, close_instant)
        settlement["_yardage_days"] = days
    bill_head = billable_head(consignment)
    yardage = yardage_charge(consignment, bill_head, days)
    feed = feed_charge(consignment)
    state_share, national_share = statutory_shares(head_sold)
    brand = brand_fee(head_sold)
    indemnity = indemnity_fee(gross)

    settlement["gross_amount"] = gross
    settlement["commission_amount"] = commission
    settlement["yardage_amount"] = yardage
    settlement["feed_amount"] = feed
    settlement["statutory_amount"] = q2(state_share + national_share)
    settlement["brand_fee_amount"] = brand
    settlement["indemnity_fee_amount"] = indemnity
    settlement["advances_amount"] = q2(consignment["advances_amount"])

    if compute_offset:
        net_before_offset = q2(D(gross) - D(commission) - D(yardage) - D(feed)
                               - D(settlement["statutory_amount"]) - D(brand)
                               - D(indemnity) - D(settlement["advances_amount"]))
        settlement["offset_applied"] = settlement_offset(
            settlement, sale_day_id, net_before_offset)

    settlement["net_amount"] = settlement_net(settlement)

    delete_settlement_lines(settlement["id"])
    sid = settlement["id"]
    add_charge_line("COMMISSION", sale_day_id, commission, settlement_id=sid,
                    head=head_sold,
                    unit_rate=commission_unit_rate(consignment, gross))
    add_charge_line("YARDAGE", sale_day_id, yardage, settlement_id=sid,
                    head=bill_head, days=days,
                    unit_rate=(config.YARDAGE_RATE_PER_HEAD_DAY
                               if consignment["yardage_basis"] == "PER_HEAD_DAY"
                               else config.YARDAGE_FLAT_PER_HEAD))
    add_charge_line("FEED", sale_day_id, feed, settlement_id=sid,
                    head=feed_head(consignment),
                    days=consignment["days_on_feed"],
                    unit_rate=_FEED_RATE[consignment["ration_type"]])
    add_charge_line("CHECKOFF_STATE", sale_day_id, state_share, settlement_id=sid,
                    head=head_sold, unit_rate=config.CHECKOFF_STATE_SHARE)
    add_charge_line("CHECKOFF_NATIONAL", sale_day_id, national_share,
                    settlement_id=sid, head=head_sold,
                    unit_rate=config.CHECKOFF_NATIONAL_SHARE)
    add_charge_line("BRAND_FEE", sale_day_id, brand, settlement_id=sid,
                    head=head_sold, unit_rate=config.BRAND_FEE_PER_HEAD)
    add_charge_line("INDEMNITY_FEE", sale_day_id, indemnity, settlement_id=sid,
                    head=0, unit_rate=config.INDEMNITY_PCT)
    touch(settlement)
    return settlement


def covering_invoices(settlement):
    """The buyer invoices covering a SOLD lot of this settlement's
    consignment."""
    lot_ids = {l["id"] for l in sold_lots(settlement["consignment_id"])}
    out = []
    for purchase in db["purchases"].values():
        if purchase["lot_id"] not in lot_ids:
            continue
        if purchase["status"] == "VOIDED":
            continue
        invoice = get("buyer_invoices", purchase.get("buyer_invoice_id"))
        if invoice is not None and invoice not in out:
            out.append(invoice)
    return out
