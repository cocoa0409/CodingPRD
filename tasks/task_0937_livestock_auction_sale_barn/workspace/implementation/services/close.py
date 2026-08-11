"""The five-hop settlement cascade of POST /sale-days/{id}/close (PRD 3.10)."""
from clock import clock
from money import q2
from store import db, get, insert_versioned, touch
from services import invoices as inv_svc
from services import saleday
from services.charges import add_charge_line
from services.settlements import price_settlement

UNFINISHED_SALE_STATUSES = ("DRAFT", "PENNED", "READY", "IN_RING")


def close_sale_day(sale_day):
    close_instant = clock.now()
    sid = sale_day["id"]

    # ---- Hop 1: the day settles. ------------------------------------------
    sale_day["status"] = "SETTLED"
    touch(sale_day)

    # ---- Hop 2: unfinished lots are finalized (caused by hop 1). ----------
    for lot in saleday.day_lots(sid):
        if lot["sale_status"] not in UNFINISHED_SALE_STATUSES:
            continue
        lot["sale_status"] = "NO_SALE"
        touch(lot)
        # rering_count is deliberately NOT touched: closing the day is not a
        # re-ring and must not consume a lot's retry budget.
        for bid in sorted(db["bids"].values(), key=lambda b: b["_seq"]):
            if bid["lot_id"] == lot["id"] and bid["status"] == "WINNING":
                bid["status"] = "VOIDED"
                touch(bid)

    # ---- Hop 3: consignments reconcile (caused by hop 2). -----------------
    reconciled = []
    for consignment in saleday.day_consignments(sid):
        if consignment["status"] in ("CHECKED_IN", "SORTED"):
            consignment["status"] = "RECONCILED"
            touch(consignment)
            reconciled.append(consignment)

    # ---- The interposed invoicing step, before hop 4. ---------------------
    for invoice in saleday.day_invoices(sid):
        if invoice["status"] != "DRAFT":
            continue
        invoice["status"] = "ISSUED"
        invoice["subtotal"] = inv_svc.subtotal(invoice)
        invoice["buyer_fee"] = inv_svc.buyer_side_fee(invoice)
        inv_svc.recompute_totals(invoice)
        reg = get("buyer_registrations", invoice["buyer_registration_id"])
        add_charge_line("BUYER_FEE", sid, invoice["buyer_fee"],
                        buyer_invoice_id=invoice["id"],
                        head=inv_svc.invoiced_head(invoice),
                        unit_rate=_buyer_fee_unit_rate(reg))
        for purchase in inv_svc.invoice_purchases(invoice["id"]):
            if purchase["status"] == "CONFIRMED":
                purchase["status"] = "INVOICED"
                touch(purchase)

    # ---- Hop 4: settlements are opened (caused by hop 3). -----------------
    opened = []
    for consignment in reconciled:
        held = bool(consignment["hold_until_funds"])
        settlement = insert_versioned("settlements", {
            "consignment_id": consignment["id"],
            "consignor_party_id": consignment["consignor_party_id"],
            "gross_amount": q2(0),
            "commission_amount": q2(0),
            "yardage_amount": q2(0),
            "feed_amount": q2(0),
            "statutory_amount": q2(0),
            "brand_fee_amount": q2(0),
            "indemnity_fee_amount": q2(0),
            "advances_amount": q2(consignment["advances_amount"]),
            "offset_applied": q2(0),
            "adjustment_total": q2(0),
            "net_amount": q2(0),
            "status": "HELD" if held else "DRAFT",
            "hold_reason": "AWAITING_FUNDS" if held else "NONE",
        })
        opened.append(settlement)

    # ---- Hop 5: the settlement is priced (caused by hop 4). ---------------
    for settlement in opened:
        price_settlement(settlement, close_instant)

    return sale_day


def _buyer_fee_unit_rate(reg):
    import config
    if reg is not None and reg["bond_type"] == "CASH_ONLY":
        return config.CASH_HANDLING_PER_HEAD
    return config.BOND_PROCESSING_PCT
