"""Bidder registration, bonds, credit and payments (PRD 3.7, 3.11)."""
from flask import Blueprint

import config
import serialize
from auth import actor
from bodyval import body, check_min, enum_field, fields, path_row, reference
from envelope import filter_arg, ok, paginate
from errors import fail
from gates import run_gates
from money import D, q2
from services import invoices as inv_svc
from services.bidding import restore_highest_outbid
from services.buyers import effective_limit
from store import db, get, insert_versioned, touch

bp = Blueprint("buyer_registrations", __name__)
ALL = config.ALL_ROLES


@bp.post("/sale-barn/buyer-registrations")
def create_registration():
    actor(["BarnAdmin"])
    data = body()
    v = fields(data, required=[
        ("party_id", "string"),
        ("sale_day_id", "string"),
        ("buyer_number", "integer"),
        ("bond_type", "string"),
        ("credit_limit", "number"),
    ], optional=[("cash_deposit_amount", "number")])
    bond_type = enum_field(data, "bond_type", config.BOND_TYPES)
    check_min(v["buyer_number"], 1, "buyer_number")
    check_min(v["credit_limit"], 0, "credit_limit")
    cash_deposit = v["cash_deposit_amount"] if v["cash_deposit_amount"] is not None else 0
    check_min(cash_deposit, 0, "cash_deposit_amount")

    party = reference("parties", v["party_id"], "Party")
    sale_day = reference("sale_days", v["sale_day_id"], "SaleDay")
    run_gates("buyer_registrations.create", sale_day=sale_day, party=party)

    # Rung 17 - bidder numbers are unique within a sale day.
    for row in db["buyer_registrations"].values():
        if row["sale_day_id"] == sale_day["id"] \
                and row["buyer_number"] == v["buyer_number"]:
            fail("ERR_DUPLICATE_BUYER_NUMBER")

    reg = insert_versioned("buyer_registrations", {
        "party_id": party["id"],
        "sale_day_id": sale_day["id"],
        "buyer_number": v["buyer_number"],
        "bond_type": bond_type,
        "credit_limit": D(v["credit_limit"]),
        "cash_deposit_amount": D(cash_deposit),
        "override_limit": q2(0),
        "status": "PENDING",
        "payments_applied": q2(0),
        "effective_limit": q2(0),
    })
    return ok(serialize.buyer_registration(reg), 201)


@bp.get("/sale-barn/buyer-registrations/<reg_id>")
def read_registration(reg_id):
    actor(ALL)
    return ok(serialize.buyer_registration(
        path_row("buyer_registrations", reg_id, "BuyerRegistration")))


@bp.get("/sale-barn/buyer-registrations")
def list_registrations():
    actor(ALL)
    rows = list(db["buyer_registrations"].values())
    for key in ("party_id", "sale_day_id", "status"):
        value = filter_arg(key)
        if value is not None:
            rows = [r for r in rows if r.get(key) == value]
    return paginate(rows, serialize.buyer_registration)


def _context(reg):
    return (get("sale_days", reg["sale_day_id"]), get("parties", reg["party_id"]))


@bp.post("/sale-barn/buyer-registrations/<reg_id>/approve")
def approve(reg_id):
    actor(["BarnAdmin"])
    reg = path_row("buyer_registrations", reg_id, "BuyerRegistration")
    sale_day, party = _context(reg)
    # A suspended party is refused by gate G4 before the state check.
    run_gates("buyer_registrations.approve", sale_day=sale_day, party=party)
    if reg["status"] != "PENDING":
        fail("ERR_INVALID_STATE")
    reg["status"] = "APPROVED"
    reg["effective_limit"] = effective_limit(reg)
    touch(reg)
    return ok(serialize.buyer_registration(reg))


@bp.post("/sale-barn/buyer-registrations/<reg_id>/credit-hold")
def credit_hold(reg_id):
    actor(["BarnAdmin"])
    reg = path_row("buyer_registrations", reg_id, "BuyerRegistration")
    data = body()
    v = fields(data, required=[("hold", "boolean")])
    sale_day, party = _context(reg)
    run_gates("buyer_registrations.credit_hold", sale_day=sale_day, party=party)
    if v["hold"]:
        if reg["status"] != "APPROVED":
            fail("ERR_INVALID_STATE")
        reg["status"] = "CREDIT_HOLD"
    else:
        if reg["status"] != "CREDIT_HOLD":
            fail("ERR_INVALID_STATE")
        reg["status"] = "APPROVED"
    # Freezing does not cancel prior purchases: they stay in the exposure.
    touch(reg)
    return ok(serialize.buyer_registration(reg))


@bp.post("/sale-barn/buyer-registrations/<reg_id>/revoke")
def revoke(reg_id):
    actor(["BarnAdmin"])
    reg = path_row("buyer_registrations", reg_id, "BuyerRegistration")
    sale_day, party = _context(reg)
    run_gates("buyer_registrations.revoke", sale_day=sale_day, party=party)
    if reg["status"] not in ("PENDING", "APPROVED", "CREDIT_HOLD"):
        fail("ERR_INVALID_STATE")
    reg["status"] = "REVOKED"
    touch(reg)

    touched_lots = []
    for bid in sorted(db["bids"].values(), key=lambda b: b["_seq"]):
        if bid["buyer_registration_id"] != reg["id"]:
            continue
        if bid["status"] == "WINNING":
            bid["status"] = "VOIDED"
            touch(bid)
            touched_lots.append(bid["lot_id"])
        elif bid["status"] == "OUTBID":
            # An OUTBID bid of the revoked registration is voided too, so it
            # can never be restored.
            bid["status"] = "VOIDED"
            touch(bid)
    for lot_id in touched_lots:
        restore_highest_outbid(lot_id)
    return ok(serialize.buyer_registration(reg))


@bp.post("/sale-barn/buyer-registrations/<reg_id>/credit-override")
def credit_override(reg_id):
    actor(["BarnAdmin"])
    reg = path_row("buyer_registrations", reg_id, "BuyerRegistration")
    data = body()
    v = fields(data, required=[("override_limit", "number"),
                               ("expected_buyer_registration_version", "integer")])
    check_min(v["override_limit"], 0, "override_limit")
    # Rung 10 - OCC, before all five gates.
    if v["expected_buyer_registration_version"] != reg["version"]:
        fail("ERR_STALE_VERSION")
    sale_day, party = _context(reg)
    run_gates("buyer_registrations.credit_override", sale_day=sale_day, party=party)
    # The new value REPLACES the prior override rather than accumulating.
    reg["override_limit"] = D(v["override_limit"])
    reg["effective_limit"] = effective_limit(reg)
    touch(reg)
    return ok(serialize.buyer_registration(reg))


@bp.post("/sale-barn/buyer-registrations/<reg_id>/payments")
def payments(reg_id):
    actor(["SettlementClerk"])
    reg = path_row("buyer_registrations", reg_id, "BuyerRegistration")
    data = body()
    v = fields(data, required=[("buyer_invoice_id", "string"), ("amount", "number")])
    check_min(v["amount"], 0, "amount", inclusive=False)
    invoice = reference("buyer_invoices", v["buyer_invoice_id"], "BuyerInvoice")
    sale_day, party = _context(reg)
    run_gates("buyer_registrations.payments", sale_day=sale_day, party=party)

    if invoice["status"] not in ("ISSUED", "PARTIALLY_PAID"):
        fail("ERR_INVALID_STATE")
    amount = D(v["amount"])
    if amount > D(invoice["balance_due"]):
        fail("ERR_AMOUNT_EXCEEDS_BALANCE")

    invoice["amount_paid"] = q2(D(invoice["amount_paid"]) + amount)
    inv_svc.recompute_totals(invoice)
    reg["payments_applied"] = q2(D(reg["payments_applied"]) + amount)
    touch(reg)

    if D(invoice["balance_due"]) <= 0:
        invoice["status"] = "PAID"
        for purchase in inv_svc.invoice_purchases(invoice["id"]):
            if purchase["status"] in ("INVOICED", "ADJUSTED"):
                purchase["status"] = "PAID"
                touch(purchase)
    else:
        if invoice["status"] == "ISSUED":
            invoice["status"] = "PARTIALLY_PAID"
        for purchase in inv_svc.invoice_purchases(invoice["id"]):
            if purchase["status"] == "ADJUSTED":
                # ADJUSTED is durable until a payment lands; the purchase then
                # returns to plain billed state and is creditable again.
                purchase["status"] = "INVOICED"
                touch(purchase)
    touch(invoice)
    return ok(serialize.buyer_invoice(invoice))
