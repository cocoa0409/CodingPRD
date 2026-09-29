"""Consignors and buyers (PRD 3.1) plus the payout disbursement (PRD 3.9)."""

from flask import Blueprint

import auth
import calc
import envelope
import serializers as ser
import services
import store
import validation as v
from errors import fail
from store import db

bp = Blueprint("standing", __name__)

PAYOUT_METHODS = ("ACH", "CHECK", "STORE_CREDIT")


# ---------------------------------------------------------------------------
# consignors
# ---------------------------------------------------------------------------
@bp.post("/consignors")
def create_consignor():
    auth.require("GalleryManager", "IntakeAppraiser")
    data = v.body()
    display_name = v.req_str(data, "display_name")
    email = v.req_str(data, "email")
    address_line = v.req_str(data, "address_line")
    floor_number = v.req_int(data, "floor_number", minimum=1)
    has_elevator = v.req_bool(data, "has_elevator")
    payout_method = v.opt_enum(data, "payout_method", PAYOUT_METHODS, "ACH")

    for row in db.consignors.values():
        if row["email"] == email:
            fail("ERR_DUPLICATE_EMAIL")

    row = store.new_row(
        db.consignors,
        {
            "display_name": display_name,
            "email": email,
            "address_line": address_line,
            "floor_number": floor_number,
            "has_elevator": has_elevator,
            "payout_method": payout_method,
            "status": "ACTIVE",
            "last_activity_at": store.now(),
            "escheat_state": "NONE",
        },
    )
    return envelope.created(ser.consignor(row))


@bp.get("/consignors/<consignor_id>")
def get_consignor(consignor_id):
    user_id, role = auth.require(
        "GalleryManager",
        "IntakeAppraiser",
        "LogisticsCoordinator",
        "FloorOperator",
        "Consignor",
        "SystemOperator",
    )
    row = v.lookup(db.consignors, consignor_id, "ERR_CONSIGNOR_NOT_FOUND")
    auth.scope_consignor(role, user_id, row["id"])
    return envelope.ok(ser.consignor(row))


@bp.get("/consignors")
def list_consignors():
    auth.require("GalleryManager", "SystemOperator")
    limit, offset = v.pagination()
    status = v.q("status")
    escheat_state = v.q("escheat_state")
    rows = store.ordered(db.consignors)
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if escheat_state is not None:
        rows = [r for r in rows if r["escheat_state"] == escheat_state]
    page = v.window(rows, limit, offset)
    return envelope.listing(ser.many(ser.consignor, page), limit, offset, len(rows))


@bp.patch("/consignors/<consignor_id>")
def patch_consignor(consignor_id):
    auth.require("GalleryManager")
    row = v.lookup(db.consignors, consignor_id, "ERR_CONSIGNOR_NOT_FOUND")
    data = v.body()
    address_line = v.opt_str(data, "address_line")
    floor_number = v.opt_int(data, "floor_number", minimum=1)
    has_elevator = v.opt_bool(data, "has_elevator")
    payout_method = v.opt_enum(data, "payout_method", PAYOUT_METHODS)

    changed = False
    for field, value in (
        ("address_line", address_line),
        ("floor_number", floor_number),
        ("has_elevator", has_elevator),
        ("payout_method", payout_method),
    ):
        if value is not None and row[field] != value:
            row[field] = value
            changed = True
    if changed:
        store.touch(row)
    return envelope.ok(ser.consignor(row))


@bp.get("/consignors/<consignor_id>/ledger-entries")
def consignor_ledger(consignor_id):
    user_id, role = auth.require("GalleryManager", "Consignor", "SystemOperator")
    row = v.lookup(db.consignors, consignor_id, "ERR_CONSIGNOR_NOT_FOUND")
    auth.scope_consignor(role, user_id, row["id"])
    limit, offset = v.pagination()
    entry_type = v.q("entry_type")
    rows = services.ledger_of_consignor(row["id"])
    if entry_type is not None:
        rows = [e for e in rows if e["entry_type"] == entry_type]
    page = v.window(rows, limit, offset)
    return envelope.listing(ser.many(ser.ledger_entry, page), limit, offset, len(rows))


@bp.post("/consignors/<consignor_id>/payouts")
def create_payout(consignor_id):
    user_id, role = auth.require("GalleryManager")
    row = v.lookup(db.consignors, consignor_id, "ERR_CONSIGNOR_NOT_FOUND")
    data = v.body()
    expected = v.req_int(data, "expected_consignor_version")

    # ladder 7
    if expected != row["version"]:
        fail("ERR_STALE_CONSIGNOR_VERSION")
    # ladder 11
    if row["escheat_state"] == "ESCHEATED":
        fail("ERR_CONSIGNOR_ESCHEATED")
    available = services.unclaimed_balance_cents(row["id"])
    # ladder 38 then 39
    if available <= 0:
        fail("ERR_INSUFFICIENT_BALANCE")
    if available < calc.MIN_PAYOUT_CENTS:
        fail("ERR_PAYOUT_BELOW_MINIMUM")

    withholding, processing_fee, net = calc.payout_disbursement(available, row["payout_method"])
    services.mint_entry(
        row,
        "PAYOUT_DISBURSEMENT_DEBIT",
        -available,
        "payout disbursement of %d cents by %s" % (available, user_id),
        item_id=None,
        withholding_cents=withholding,
        processing_fee_cents=processing_fee,
        net_payout_cents=net,
    )
    return envelope.ok(ser.consignor(row))


# ---------------------------------------------------------------------------
# buyers
# ---------------------------------------------------------------------------
@bp.post("/buyers")
def create_buyer():
    auth.require("GalleryManager", "FloorOperator")
    data = v.body()
    display_name = v.req_str(data, "display_name")
    email = v.req_str(data, "email")
    address_line = v.req_str(data, "address_line")
    floor_number = v.req_int(data, "floor_number", minimum=1)
    has_elevator = v.req_bool(data, "has_elevator")

    for row in db.buyers.values():
        if row["email"] == email:
            fail("ERR_DUPLICATE_EMAIL")

    row = store.new_row(
        db.buyers,
        {
            "display_name": display_name,
            "email": email,
            "address_line": address_line,
            "floor_number": floor_number,
            "has_elevator": has_elevator,
            "status": "ACTIVE",
        },
    )
    return envelope.created(ser.buyer(row))


@bp.get("/buyers/<buyer_id>")
def get_buyer(buyer_id):
    user_id, role = auth.require(
        "GalleryManager", "FloorOperator", "LogisticsCoordinator", "Buyer"
    )
    row = v.lookup(db.buyers, buyer_id, "ERR_BUYER_NOT_FOUND")
    auth.scope_buyer(role, user_id, row["id"])
    return envelope.ok(ser.buyer(row))


@bp.get("/buyers")
def list_buyers():
    auth.require("GalleryManager", "FloorOperator")
    limit, offset = v.pagination()
    status = v.q("status")
    rows = store.ordered(db.buyers)
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page = v.window(rows, limit, offset)
    return envelope.listing(ser.many(ser.buyer, page), limit, offset, len(rows))


@bp.post("/buyers/<buyer_id>/block")
def block_buyer(buyer_id):
    auth.require("GalleryManager")
    row = v.lookup(db.buyers, buyer_id, "ERR_BUYER_NOT_FOUND")
    if row["status"] == "BLOCKED":
        fail("ERR_BUYER_BLOCKED")
    row["status"] = "BLOCKED"
    store.touch(row)
    return envelope.ok(ser.buyer(row))
