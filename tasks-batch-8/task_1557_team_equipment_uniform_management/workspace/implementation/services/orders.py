"""Kit order derived state: committed units and pinned-order pricing (PRD §3.3)."""
from decimal import Decimal, ROUND_HALF_UP

from db import db

OPEN_STATUSES = ("SUBMITTED", "PARTIALLY_RECEIVED")


def units_committed_map(contract):
    """Committed units per capped garment type, derived on read (PRD §3.3):
    SUBMITTED/PARTIALLY_RECEIVED/RECEIVED orders contribute full line
    quantities; CANCELLED orders contribute only already-received quantities."""
    committed = {cap["garment_type"]: 0 for cap in contract["allocation_caps"]}
    for order in db.orders.values():
        if order["supplier_contract_id"] != contract["id"]:
            continue
        status = order["status"]
        if status in ("SUBMITTED", "PARTIALLY_RECEIVED", "RECEIVED"):
            for line in order["lines"]:
                gt = line["garment_type"]
                if gt in committed:
                    committed[gt] += line["quantity"]
        elif status == "CANCELLED":
            for rl in order["received_lines"]:
                gt = rl["garment_type"]
                if gt in committed:
                    committed[gt] += rl["received_quantity"]
    return committed


def units_committed_list(contract):
    committed = units_committed_map(contract)
    return [
        {"garment_type": cap["garment_type"], "committed_units": committed[cap["garment_type"]]}
        for cap in contract["allocation_caps"]
    ]


def _round_half_up_cents(value):
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def price_order(lines, rebate_pct):
    """Pinned rounding order (PRD §3.3): per-line round half-up, sum, then
    rebate round half-up."""
    subtotal = 0
    for line in lines:
        line_total = (
            Decimal(line["unit_price_cents"])
            * line["quantity"]
            * (Decimal(1) - Decimal(str(line.get("line_discount_pct", 0))))
        )
        subtotal += _round_half_up_cents(line_total)
    total = _round_half_up_cents(Decimal(subtotal) * (Decimal(1) - Decimal(str(rebate_pct))))
    return subtotal, total
