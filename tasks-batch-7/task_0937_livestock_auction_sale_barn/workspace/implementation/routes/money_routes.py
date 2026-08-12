"""Purchases, buyer invoices, settlements and charge lines (PRD 3.10, 3.11)."""
from flask import Blueprint

import config
import serialize
from auth import actor
from bodyval import body, check_min, fields, path_row, reference
from envelope import filter_arg, ok, paginate
from errors import fail
from gates import run_gates
from money import D, q2
from services import invoices as inv_svc
from services import settlements as settle_svc
from services.charges import add_charge_line
from services.voids import void_purchase
from store import db, get, touch

bp = Blueprint("money", __name__)
ALL = config.ALL_ROLES


# ------------------------------------------------------------- purchases ---
@bp.get("/sale-barn/purchases/<purchase_id>")
def read_purchase(purchase_id):
    actor(ALL)
    return ok(serialize.purchase(path_row("purchases", purchase_id, "Purchase")))


@bp.get("/sale-barn/purchases")
def list_purchases():
    actor(ALL)
    rows = list(db["purchases"].values())
    for key in ("lot_id", "buyer_registration_id", "winning_bid_id",
                "buyer_invoice_id", "status"):
        value = filter_arg(key)
        if value is not None:
            rows = [r for r in rows if r.get(key) == value]
    return paginate(rows, serialize.purchase)


@bp.post("/sale-barn/purchases/<purchase_id>/void")
def void(purchase_id):
    actor(["SettlementClerk"])
    purchase = path_row("purchases", purchase_id, "Purchase")
    data = body()
    fields(data, optional=[("reason", "string")])
    lot = get("lots", purchase["lot_id"])
    sale_day = get("sale_days", lot["sale_day_id"]) if lot else None
    reg = get("buyer_registrations", purchase["buyer_registration_id"])
    party = get("parties", reg["party_id"]) if reg else None
    run_gates("purchases.void", sale_day=sale_day, lot=lot, party=party)
    if purchase["status"] not in ("CONFIRMED", "INVOICED", "ADJUSTED"):
        fail("ERR_INVALID_STATE")
    void_purchase(purchase)
    return ok(serialize.purchase(purchase))


# --------------------------------------------------------- buyer invoices --
@bp.get("/sale-barn/buyer-invoices/<invoice_id>")
def read_invoice(invoice_id):
    actor(ALL)
    return ok(serialize.buyer_invoice(
        path_row("buyer_invoices", invoice_id, "BuyerInvoice")))


@bp.get("/sale-barn/buyer-invoices")
def list_invoices():
    actor(ALL)
    rows = list(db["buyer_invoices"].values())
    for key in ("buyer_registration_id", "sale_day_id", "status"):
        value = filter_arg(key)
        if value is not None:
            rows = [r for r in rows if r.get(key) == value]
    return paginate(rows, serialize.buyer_invoice)


@bp.post("/sale-barn/buyer-invoices/<invoice_id>/credit-memo")
def credit_memo(invoice_id):
    actor(["SettlementClerk"])
    invoice = path_row("buyer_invoices", invoice_id, "BuyerInvoice")
    data = body()
    v = fields(data, required=[("amount", "number")],
               optional=[("purchase_id", "string"), ("doa_head", "integer")])
    check_min(v["amount"], 0, "amount")
    if v["doa_head"] is not None:
        check_min(v["doa_head"], 1, "doa_head")

    purchase = None
    if v["purchase_id"] is not None:
        purchase = reference("purchases", v["purchase_id"], "Purchase")

    reg = get("buyer_registrations", invoice["buyer_registration_id"])
    sale_day = get("sale_days", invoice["sale_day_id"])
    party = get("parties", reg["party_id"]) if reg else None
    run_gates("buyer_invoices.credit_memo", sale_day=sale_day, party=party)

    doa_head = v["doa_head"] or 0
    if purchase is not None:
        if purchase["status"] != "INVOICED":
            fail("ERR_INVALID_STATE")
        if doa_head > purchase["head_count"]:
            fail("ERR_INVALID_STATE")

    # Rung 43 - the memo may not exceed total_due reduced by the memos already
    # recorded in credit_memo_total (PRD 3.11 states this reduction verbatim,
    # even though total_due already nets those memos out).
    amount = D(v["amount"])
    cap = q2(D(invoice["total_due"]) - D(invoice["credit_memo_total"]))
    if amount > cap:
        fail("ERR_AMOUNT_EXCEEDS_BALANCE")

    # Adjudication of friction 4: credit_memo_total rises by the SUPPLIED
    # amount, never by the computed DOA credit. That keeps the plain-memo and
    # dead-on-arrival paths uniform, keeps rung 43's cap policing the very
    # number that lands on the invoice, and leaves the computed credit visible
    # on the purchase and on its DOA_CREDIT charge line.
    invoice["credit_memo_total"] = q2(D(invoice["credit_memo_total"]) + amount)
    inv_svc.recompute_totals(invoice)

    if purchase is not None and doa_head > 0:
        purchase["doa_head"] = purchase["doa_head"] + doa_head
        per_head = _doa_per_head(purchase)
        purchase["doa_credit_amount"] = q2(per_head * D(purchase["doa_head"]))
        purchase["status"] = "ADJUSTED"
        touch(purchase)
        add_charge_line("DOA_CREDIT", invoice["sale_day_id"],
                        q2(-D(purchase["doa_credit_amount"])),
                        buyer_invoice_id=invoice["id"],
                        lot_id=purchase["lot_id"],
                        head=purchase["doa_head"],
                        unit_rate=per_head)
    return ok(serialize.buyer_invoice(invoice))


def _doa_per_head(purchase):
    if purchase["bid_basis"] == "PER_CWT":
        return q2(D(purchase["extended_amount"]) / D(purchase["head_count"]))
    return D(purchase["unit_price"])


# ----------------------------------------------------------- settlements ---
@bp.get("/sale-barn/settlements/<settlement_id>")
def read_settlement(settlement_id):
    actor(ALL)
    return ok(serialize.settlement(
        path_row("settlements", settlement_id, "Settlement")))


@bp.get("/sale-barn/settlements")
def list_settlements():
    actor(ALL)
    rows = list(db["settlements"].values())
    for key in ("consignment_id", "consignor_party_id", "status"):
        value = filter_arg(key)
        if value is not None:
            rows = [r for r in rows if r.get(key) == value]
    return paginate(rows, serialize.settlement)


def _settlement_context(settlement):
    consignment = get("consignments", settlement["consignment_id"])
    sale_day = get("sale_days", consignment["sale_day_id"]) if consignment else None
    party = get("parties", settlement["consignor_party_id"])
    return consignment, sale_day, party


@bp.post("/sale-barn/settlements/<settlement_id>/release")
def release_settlement(settlement_id):
    actor(["SettlementClerk"])
    settlement = path_row("settlements", settlement_id, "Settlement")
    consignment, sale_day, party = _settlement_context(settlement)
    # Rung 15 - gate G5 answers here, before the state rung, which is exactly
    # why a released settlement returns ERR_SETTLEMENT_RELEASED rather than
    # ERR_INVALID_STATE.
    run_gates("settlements.release", sale_day=sale_day, party=party,
              settlement=settlement)
    if settlement["status"] not in ("DRAFT", "HELD", "ADJUSTED"):
        fail("ERR_INVALID_STATE")
    if not settle_svc.balance_ok(settlement):
        fail("ERR_INVALID_STATE")
    if settlement["status"] == "HELD":
        # Rung 42 - a held settlement is released only once every covering
        # invoice is PAID.
        for invoice in settle_svc.covering_invoices(settlement):
            if invoice["status"] != "PAID":
                fail("ERR_FUNDS_NOT_CLEARED")
    settlement["status"] = "RELEASED"
    settlement["hold_reason"] = "NONE"
    touch(settlement)
    if consignment is not None and consignment["status"] == "RECONCILED":
        consignment["status"] = "SETTLED"
        touch(consignment)
    return ok(serialize.settlement(settlement))


@bp.post("/sale-barn/settlements/<settlement_id>/adjust")
def adjust_settlement(settlement_id):
    actor(["SettlementClerk"])
    settlement = path_row("settlements", settlement_id, "Settlement")
    data = body()
    v = fields(data, required=[("adjustment_amount", "number"),
                               ("reason", "string")])
    check_min(v["adjustment_amount"], 0, "adjustment_amount", inclusive=False)
    consignment, sale_day, party = _settlement_context(settlement)
    # The single exemption gate G5 permits.
    run_gates("settlements.adjust", sale_day=sale_day, party=party,
              settlement=settlement)
    if settlement["status"] != "RELEASED":
        fail("ERR_INVALID_STATE")
    amount = D(v["adjustment_amount"])
    if abs(amount) > D(settlement["net_amount"]):
        fail("ERR_AMOUNT_EXCEEDS_BALANCE")
    settlement["status"] = "ADJUSTED"
    settlement["adjustment_total"] = q2(D(settlement["adjustment_total"]) + amount)
    settlement["net_amount"] = settle_svc.settlement_net(settlement)
    touch(settlement)
    return ok(serialize.settlement(settlement))


# ---------------------------------------------------------- charge lines ---
@bp.get("/sale-barn/charge-lines/<line_id>")
def read_charge_line(line_id):
    actor(ALL)
    return ok(serialize.charge_line(path_row("charge_lines", line_id, "ChargeLine")))


@bp.get("/sale-barn/charge-lines")
def list_charge_lines():
    actor(ALL)
    rows = list(db["charge_lines"].values())
    for key in ("sale_day_id", "settlement_id", "buyer_invoice_id", "lot_id",
                "charge_type", "side"):
        value = filter_arg(key)
        if value is not None:
            rows = [r for r in rows if r.get(key) == value]
    return paginate(rows, serialize.charge_line)
