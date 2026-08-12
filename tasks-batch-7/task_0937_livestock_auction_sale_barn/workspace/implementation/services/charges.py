"""ChargeLine creation (PRD 2.11). Side and revenue_class come from the fixed
classification table; no other combination is ever produced."""
import config
from money import D, q2
from store import db, insert


def add_charge_line(charge_type, sale_day_id, amount, settlement_id=None,
                    buyer_invoice_id=None, lot_id=None, head=0, days=0,
                    unit_rate=0):
    side, revenue_class = config.CHARGE_CLASSIFICATION[charge_type]
    row = {
        "sale_day_id": sale_day_id,
        "settlement_id": settlement_id,
        "buyer_invoice_id": buyer_invoice_id,
        "lot_id": lot_id,
        "charge_type": charge_type,
        "side": side,
        "revenue_class": revenue_class,
        "head": head,
        "days": days,
        # The rate constant used, recorded verbatim so the line is auditable
        # without re-reading the constant table (PRD 2.11).
        "unit_rate": D(unit_rate) if unit_rate is not None else D(0),
        "amount": q2(amount),
    }
    # ChargeLine is lean: id and created_at only, no updated_at, no version.
    return insert("charge_lines", row)


def delete_settlement_lines(settlement_id):
    for line_id in [lid for lid, row in db["charge_lines"].items()
                    if row.get("settlement_id") == settlement_id]:
        del db["charge_lines"][line_id]


def settlement_lines(settlement_id):
    return [row for row in db["charge_lines"].values()
            if row.get("settlement_id") == settlement_id]
