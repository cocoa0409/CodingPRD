"""The fee/refund pair and the append-only cost ledger (PRD 3.8, 2.10)."""

import constants as C
from db import db, new_row
from numeric import round_half_up
from services.derive import postings_of_case


def restocking_tier_bp(gross_line_cents):
    """Tiered on the line's gross, never on the refund."""
    if gross_line_cents < C.RESTOCK_TIER_1_CENTS:
        return 0
    if gross_line_cents < C.RESTOCK_TIER_2_CENTS:
        return 1000
    return 1500


def compute_fee_and_refund(case, line, policy, customer, refunded):
    """``(restocking_fee_cents, refund_amount_cents)`` for this resolution."""
    if not refunded:
        # a denied outcome short-circuits the whole computation
        return 0, 0

    gross = line["gross_line_cents"]
    base_fee = round_half_up(restocking_tier_bp(gross) * gross, 10000)

    fee = 0
    if (case["reason_family"] == "CHANGE_OF_MIND"
            and policy is not None
            and policy["restocking_applies"]):
        multiplier_bp = (C.ABUSE_FEE_MULTIPLIER_BP
                         if customer["abuse_status"] == "RESTRICTED" else 10000)
        fee = round_half_up(base_fee * multiplier_bp, 10000)

    withheld_shipping = 0
    if policy is not None and policy["non_refundable_shipping"]:
        withheld_shipping = line["shipping_allocated_cents"]

    refund = gross - fee - withheld_shipping
    if refund < 0:
        refund = 0
    return fee, refund


def _components(case, line, item, item_condition, refund_amount_cents, refunded):
    """The ORIGINAL rows to write, in the fixed component order of PRD 3.8."""
    gross = line["gross_line_cents"]
    rows = [
        ("FREIGHT_INBOUND", C.FREIGHT_INBOUND_CENTS[item["category_code"]]),
        ("PROCESSING_LABOR", round_half_up(
            C.LABOR_RATE_CENTS_PER_MIN * C.HANDLING_MINUTES[case["reason_family"]])),
    ]
    if not refunded:
        # a denied case writes only freight and labor
        return rows
    rows.append(("REFURB_REPACK",
                 round_half_up(C.REFURB_PCT_BP[item_condition] * gross, 10000)))
    rows.append(("MARKDOWN_LOSS",
                 round_half_up(C.MARKDOWN_PCT_BP[item_condition] * gross, 10000)))
    rows.append(("PAYMENT_FEE_UNRECOVERED",
                 round_half_up(C.PAYMENT_FEE_BP * refund_amount_cents, 10000)))
    if case["reason_family"] == "QUALITY":
        rows.append(("VENDOR_CHARGEBACK_CREDIT",
                     -round_half_up(C.VENDOR_CHARGEBACK_PCT_BP * gross, 10000)))
    return rows


def write_original_postings(case, line, item, item_condition,
                            refund_amount_cents, refunded):
    """Write one ORIGINAL row per component; return their integer sum."""
    total = 0
    for component, amount_cents in _components(
            case, line, item, item_condition, refund_amount_cents, refunded):
        posting = new_row({
            "return_case_id": case["id"],
            "component": component,
            "amount_cents": amount_cents,
            "posting_kind": "ORIGINAL",
            "reversed_component": None,
        }, with_common=False)
        db.postings[posting["id"]] = posting
        total += amount_cents
    return total


def write_reversal_postings(case):
    """Exactly one negating REVERSAL row per ORIGINAL row of the case."""
    originals = [p for p in postings_of_case(case["id"])
                 if p["posting_kind"] == "ORIGINAL"]
    for original in originals:
        posting = new_row({
            "return_case_id": case["id"],
            "component": original["component"],
            "amount_cents": -original["amount_cents"],
            "posting_kind": "REVERSAL",
            "reversed_component": original["component"],
        }, with_common=False)
        db.postings[posting["id"]] = posting
    return len(originals)
