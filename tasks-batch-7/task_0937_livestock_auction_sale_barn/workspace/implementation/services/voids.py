"""The four-hop unwind of POST /purchases/{id}/void (PRD 3.11)."""
from clock import clock
from money import q2
from store import db, get, touch
from services import invoices as inv_svc
from services.bidding import restore_highest_outbid
from services.pens import recompute_pens
from services.settlements import price_settlement


def void_purchase(purchase):
    # ---- Hop 1: the purchase voids. ---------------------------------------
    purchase["status"] = "VOIDED"
    touch(purchase)

    # ---- Hop 2: the sale on the lot is reversed (caused by hop 1). --------
    lot = get("lots", purchase["lot_id"])
    if lot is not None:
        if lot["sale_status"] == "SOLD":
            lot["sale_status"] = "NO_SALE"
        if lot["custody_status"] == "BUYER_PEN":
            lot["custody_status"] = "BARN"
        lot["hammer_price"] = None
        lot["extended_amount"] = q2(0)
        touch(lot)
        recompute_pens(lot.get("pen_id"))
        hammered = get("bids", purchase.get("winning_bid_id"))
        if hammered is not None and hammered["status"] == "HAMMERED":
            hammered["status"] = "VOIDED"
            touch(hammered)
        # The next-highest OUTBID bid on that lot, if any, is restored.
        restore_highest_outbid(lot["id"])

    # ---- Hop 3: the consignment and its settlement react (from hop 2). ----
    settlement = None
    if lot is not None:
        consignment = get("consignments", lot["consignment_id"])
        if consignment is not None:
            # head_sold / head_no_saled / head_in_lots are derived on read, so
            # they follow the lot's new sale_status with no stored counter to
            # drift; the consignment row is still touched because the cascade
            # says it recomputes.
            touch(consignment)
            for row in sorted(db["settlements"].values(), key=lambda s: s["_seq"]):
                if row["consignment_id"] == consignment["id"]:
                    settlement = row
                    break
    if settlement is not None:
        # Adjudication of friction 8: hop 3 drives ANY existing settlement to
        # ADJUSTED, not only a RELEASED one. The PRD sentence is unqualified
        # ("when a settlement already exists ... transition to ADJUSTED"), and
        # restricting it to RELEASED settlements would make the hop dead on
        # the ordinary path, where the settlement is still DRAFT or HELD.
        settlement["status"] = "ADJUSTED"
        # ---- Hop 4: the settlement's charge lines are regenerated. --------
        price_settlement(settlement, clock.now(), compute_offset=False)

    # ---- Hop 4 (continued): the buyer invoice is recomputed. --------------
    invoice = get("buyer_invoices", purchase.get("buyer_invoice_id"))
    if invoice is not None:
        inv_svc.recompute_full(invoice)
        remaining = [p for p in inv_svc.invoice_purchases(invoice["id"])
                     if p["status"] != "VOIDED"]
        if not remaining and invoice["status"] in ("DRAFT", "ISSUED", "PARTIALLY_PAID"):
            invoice["status"] = "VOIDED"
            invoice["subtotal"] = q2(0)
            invoice["buyer_fee"] = q2(0)
            invoice["total_due"] = q2(0)
            invoice["balance_due"] = q2(0)
            # amount_paid stays on the row as a recorded overpayment.
            touch(invoice)
    return purchase
