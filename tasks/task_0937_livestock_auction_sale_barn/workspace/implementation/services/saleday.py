"""Sale-day roll-ups and the three sale-day conservation invariants
(PRD 2.10, 3.10). Every figure is derived from live rows, so a read always
shows the books as they stand."""
from money import D, q2
from store import db, get


def day_consignments(sale_day_id):
    return sorted([c for c in db["consignments"].values()
                   if c["sale_day_id"] == sale_day_id],
                  key=lambda c: (c["created_at"], c["_seq"]))


def day_lots(sale_day_id):
    return sorted([l for l in db["lots"].values()
                   if l["sale_day_id"] == sale_day_id],
                  key=lambda l: (l["created_at"], l["_seq"]))


def day_invoices(sale_day_id):
    return sorted([i for i in db["buyer_invoices"].values()
                   if i["sale_day_id"] == sale_day_id],
                  key=lambda i: (i["created_at"], i["_seq"]))


def day_settlements(sale_day_id):
    ids = {c["id"] for c in day_consignments(sale_day_id)}
    return sorted([s for s in db["settlements"].values()
                   if s["consignment_id"] in ids],
                  key=lambda s: (s["created_at"], s["_seq"]))


def day_charge_lines(sale_day_id):
    return sorted([c for c in db["charge_lines"].values()
                   if c["sale_day_id"] == sale_day_id],
                  key=lambda c: (c["created_at"], c["_seq"]))


def rollups(sale_day):
    sid = sale_day["id"]
    consignments = day_consignments(sid)
    lots = day_lots(sid)
    invoices = day_invoices(sid)
    settlements = day_settlements(sid)
    lines = day_charge_lines(sid)

    head_received_total = sum(c["head_received"] for c in consignments)
    head_sold_total = sum(l["head_count"] for l in lots if l["sale_status"] == "SOLD")
    head_no_sale_total = sum(l["head_count"] for l in lots if l["sale_status"] == "NO_SALE")
    head_withdrawn_total = sum(c["head_withdrawn"] for c in consignments)
    head_dead_total = sum(c["head_dead"] + c["head_condemned"] for c in consignments)
    head_in_process_total = sum(l["head_count"] for l in lots
                                if l["sale_status"] in ("DRAFT", "PENNED", "READY", "IN_RING"))
    head_unassigned_total = sum(c["head_unassigned"] for c in consignments)

    total_gross_sale_value = q2(sum(D(l.get("extended_amount") or 0)
                                    for l in lots if l["sale_status"] == "SOLD"))
    total_buyer_invoiced = q2(sum(D(i["total_due"]) for i in invoices
                                  if i["status"] != "VOIDED"))
    total_seller_net = q2(sum(D(s["net_amount"]) for s in settlements))
    total_barn_revenue = q2(sum(D(c["amount"]) for c in lines
                                if c["revenue_class"] == "BARN_REVENUE"))
    total_statutory_collected = q2(sum(D(c["amount"]) for c in lines
                                       if c["revenue_class"] == "STATUTORY_REMITTANCE"))

    invoice_subtotal = q2(sum(D(i["subtotal"]) for i in invoices))
    settlement_gross = q2(sum(D(s["gross_amount"]) for s in settlements))
    gross_match_ok = invoice_subtotal == settlement_gross

    invoice_total_due = q2(sum(D(i["total_due"]) for i in invoices))
    charge_sum = q2(sum(D(c["amount"]) for c in lines
                        if c["charge_type"] != "DOA_CREDIT"))
    advances_sum = q2(sum(D(s["advances_amount"]) for s in settlements))
    offset_sum = q2(sum(D(s["offset_applied"]) for s in settlements))
    memo_sum = q2(sum(D(i["credit_memo_total"]) for i in invoices))
    money_right = q2(D(total_seller_net) + D(charge_sum) + D(advances_sum)
                     + D(offset_sum) - D(memo_sum))
    money_reconciliation_ok = invoice_total_due == money_right

    head_reconciliation_ok = head_received_total == (
        head_sold_total + head_no_sale_total + head_withdrawn_total
        + head_dead_total + head_in_process_total + head_unassigned_total)

    return {
        "head_received_total": head_received_total,
        "head_sold_total": head_sold_total,
        "head_no_sale_total": head_no_sale_total,
        "head_withdrawn_total": head_withdrawn_total,
        "head_dead_total": head_dead_total,
        "head_in_process_total": head_in_process_total,
        "head_unassigned_total": head_unassigned_total,
        "total_gross_sale_value": total_gross_sale_value,
        "total_buyer_invoiced": total_buyer_invoiced,
        "total_seller_net": total_seller_net,
        "total_barn_revenue": total_barn_revenue,
        "total_statutory_collected": total_statutory_collected,
        "gross_match_ok": gross_match_ok,
        "money_reconciliation_ok": money_reconciliation_ok,
        "head_reconciliation_ok": head_reconciliation_ok,
    }


def sale_day_of_lot(lot):
    return get("sale_days", lot["sale_day_id"])
