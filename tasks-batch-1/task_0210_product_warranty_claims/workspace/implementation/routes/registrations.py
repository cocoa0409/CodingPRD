"""Registration endpoints: create/get/list, transfer lifecycle, void, ledger, transfers.

PRD §3.2 (create), §3.11 (transfer), §3.12 (transfer fee), §3.13 (void/expiry).
"""
from __future__ import annotations

from flask import Blueprint, g, request

import db
from errors import (
    APIError,
    ERR_DUPLICATE_SERIAL,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_NOT_FOUND,
    ERR_NOT_OWNER,
    ERR_STALE_VERSION,
)
from middleware import require_roles
from response import ok_array, ok_object
from services import calc, common
from services.registration_svc import (
    active_extensions,
    base_tier_for_product,
    bump,
    ledger_for,
    make_ledger_entry,
    mint_common,
    mint_lean,
    public,
    public_registration,
    reconcile,
    recompute_remaining_coverage,
)
from services.timeutil import parse_iso, whole_months_between

bp = Blueprint("registrations", __name__)


def _get_reg_or_404(rid):
    reg = db.registrations.get(rid)
    if reg is None:
        raise APIError(ERR_NOT_FOUND, 404, "Registration not found")
    return reg


# ---- create -----------------------------------------------------------------

@bp.post("/registrations")
def create_registration():
    require_roles(["Owner", "WarrantyAdmin"])
    body = common.get_json_body()
    common.require_fields(body, ["product_id", "serial_number", "owner_user_id",
                                 "purchase_date", "purchase_price_cents"])
    product_id = common.require_str(body, "product_id")
    serial_number = common.require_str(body, "serial_number")
    owner_user_id = common.require_str(body, "owner_user_id")
    purchase_date = common.require_str(body, "purchase_date")
    purchase_price_cents = common.require_int(body, "purchase_price_cents", minimum=1)
    try:
        parse_iso(purchase_date)
    except Exception:
        raise APIError(ERR_INVALID_REQUEST, 400, "purchase_date must be ISO 8601")

    # existence of body-referenced resources (PRD §2.5)
    if product_id not in db.products:
        raise APIError(ERR_NOT_FOUND, 404, "Product not found")
    if owner_user_id not in db.owners:
        raise APIError(ERR_NOT_FOUND, 404, "Owner not found")

    # serial unique per product (ERR_DUPLICATE_SERIAL, 409)
    for r in db.registrations.values():
        if r["product_id"] == product_id and r["serial_number"] == serial_number:
            raise APIError(ERR_DUPLICATE_SERIAL, 409,
                           "serial_number already registered for this product")

    base = base_tier_for_product(product_id)

    reg = {
        "product_id": product_id,
        "serial_number": serial_number,
        "owner_user_id": owner_user_id,
        "purchase_date": purchase_date,
        "purchase_price_cents": purchase_price_cents,
        "proof_status": "UNVERIFIED",
        "status": "REGISTERED",
        "active_tier_id": base["id"] if base is not None else None,
        "warranty_end_date": None,
        "remaining_coverage_cents": 0,
    }
    mint_common(reg)
    db.registrations[reg["id"]] = reg
    # derive warranty_end_date + remaining_coverage from base tier / ledger (empty)
    reconcile(reg)
    return ok_object(public(reg), 201)


# ---- read -------------------------------------------------------------------

@bp.get("/registrations/<rid>")
def get_registration(rid):
    require_roles(["WarrantyAdmin", "Owner", "ClaimsProcessor"])
    reg = _get_reg_or_404(rid)
    return ok_object(public_registration(reg))


@bp.get("/registrations")
def list_registrations():
    require_roles(["WarrantyAdmin", "Owner", "ClaimsProcessor"])
    limit, offset = common.parse_pagination()
    owner_user_id = request.args.get("owner_user_id")
    product_id = request.args.get("product_id")
    active_tier_id = request.args.get("active_tier_id")
    rows = list(db.registrations.values())
    # recompute derived fields so active_tier_id filter is accurate
    for r in rows:
        reconcile(r)
    if owner_user_id is not None:
        rows = [r for r in rows if r["owner_user_id"] == owner_user_id]
    if product_id is not None:
        rows = [r for r in rows if r["product_id"] == product_id]
    if active_tier_id is not None:
        rows = [r for r in rows if r.get("active_tier_id") == active_tier_id]
    page, total = common.paginate(rows, limit, offset)
    return ok_array([public(r) for r in page], limit, offset, total)


# ---- transfer initiation ----------------------------------------------------

@bp.post("/registrations/<rid>/transfer")
def initiate_transfer(rid):
    require_roles(["Owner"])
    # path existence
    reg = _get_reg_or_404(rid)
    body = common.get_json_body()
    common.require_fields(body, ["to_owner_user_id", "expected_registration_version"])
    to_owner_user_id = common.require_str(body, "to_owner_user_id")
    expected_version = common.require_int(body, "expected_registration_version")

    # body existence (PRD §2.5): to_owner must exist
    if to_owner_user_id not in db.owners:
        raise APIError(ERR_NOT_FOUND, 404, "Owner not found")

    # state (priority 4): must be ACTIVE
    if reg["status"] != "ACTIVE":
        raise APIError(ERR_INVALID_STATE, 409,
                       "Registration must be ACTIVE to initiate transfer")

    # OCC (priority 5)
    if expected_version != reg["version"]:
        raise APIError(ERR_STALE_VERSION, 412,
                       "expected_registration_version does not match current version")

    # ownership (priority 6): acting owner must be current owner
    if reg["owner_user_id"] != g.user_id:
        raise APIError(ERR_NOT_OWNER, 403, "Caller is not the registration owner")

    # business: no claim in RMA_ISSUED/ADJUDICATED
    for c in db.claims.values():
        if c["registration_id"] == rid and c["status"] in ("RMA_ISSUED", "ADJUDICATED"):
            raise APIError(ERR_INVALID_STATE, 409,
                           "Registration has an in-flight claim; cannot transfer")

    # business: to_owner distinct from current owner
    if to_owner_user_id == reg["owner_user_id"]:
        raise APIError(ERR_INVALID_REQUEST, 400,
                       "to_owner_user_id must differ from current owner")

    # compute transfer fee against current ledger remaining coverage
    recompute_remaining_coverage(reg)
    product = db.products[reg["product_id"]]
    now = parse_iso(db.system_clock["current_utc"])
    elapsed = whole_months_between(parse_iso(reg["purchase_date"]), now)
    fee = calc.transfer_fee(product["category"], elapsed, reg["remaining_coverage_cents"])

    transfer = {
        "registration_id": rid,
        "from_owner_user_id": reg["owner_user_id"],
        "to_owner_user_id": to_owner_user_id,
        "transfer_fee_cents": fee,
        "status": "COMPLETED",
    }
    mint_lean(transfer)
    db.warranty_transfers[transfer["id"]] = transfer

    make_ledger_entry(rid, "DEBIT", "TRANSFER_FEE", fee, claim_id=None)

    reg["status"] = "TRANSFER_PENDING"
    reconcile(reg)
    bump(reg)
    return ok_object(public(transfer), 201)


@bp.post("/registrations/<rid>/transfer/accept")
def accept_transfer(rid):
    require_roles(["Owner"])
    reg = _get_reg_or_404(rid)
    if reg["status"] != "TRANSFER_PENDING":
        raise APIError(ERR_INVALID_STATE, 409, "Registration is not TRANSFER_PENDING")
    transfer = _latest_transfer(rid)
    if transfer is None or transfer["to_owner_user_id"] != g.user_id:
        raise APIError(ERR_NOT_OWNER, 403, "Caller is not the named transfer recipient")
    reg["owner_user_id"] = transfer["to_owner_user_id"]
    reg["status"] = "ACTIVE"
    reconcile(reg)
    bump(reg)
    return ok_object(public_registration(reg))


@bp.post("/registrations/<rid>/transfer/reject")
def reject_transfer(rid):
    require_roles(["Owner"])
    reg = _get_reg_or_404(rid)
    if reg["status"] != "TRANSFER_PENDING":
        raise APIError(ERR_INVALID_STATE, 409, "Registration is not TRANSFER_PENDING")
    transfer = _latest_transfer(rid)
    if transfer is None or transfer["to_owner_user_id"] != g.user_id:
        raise APIError(ERR_NOT_OWNER, 403, "Caller is not the named transfer recipient")
    transfer["status"] = "REVERSED"
    # compensating CREDIT for the transfer fee
    make_ledger_entry(rid, "CREDIT", "REVERSAL", transfer["transfer_fee_cents"], claim_id=None)
    reg["status"] = "ACTIVE"  # owner unchanged
    reconcile(reg)
    bump(reg)
    return ok_object(public_registration(reg))


def _latest_transfer(rid):
    rows = [t for t in db.warranty_transfers.values() if t["registration_id"] == rid]
    if not rows:
        return None
    rows.sort(key=lambda t: t["_seq"])
    return rows[-1]


# ---- void -------------------------------------------------------------------

@bp.post("/registrations/<rid>/void")
def void_registration(rid):
    require_roles(["WarrantyAdmin"])
    reg = _get_reg_or_404(rid)
    if reg["status"] not in ("REGISTERED", "ACTIVE"):
        raise APIError(ERR_INVALID_STATE, 409,
                       "Registration must be REGISTERED or ACTIVE to void")
    for c in db.claims.values():
        if c["registration_id"] == rid and c["status"] in ("RMA_ISSUED", "ADJUDICATED", "FULFILLED"):
            raise APIError(ERR_INVALID_STATE, 409,
                           "Registration has an in-flight/fulfilled claim; cannot void")
    # cancel all ACTIVE extended warranties
    for ext in active_extensions(rid):
        ext["status"] = "CANCELLED"
        bump(ext)
    reg["status"] = "VOIDED"
    reconcile(reg)
    bump(reg)
    return ok_object(public_registration(reg))


# ---- ledger / transfers listings -------------------------------------------

@bp.get("/registrations/<rid>/ledger")
def list_ledger(rid):
    require_roles(["WarrantyAdmin", "Owner", "ClaimsProcessor"])
    _get_reg_or_404(rid)
    limit, offset = common.parse_pagination()
    rows = ledger_for(rid)
    page, total = common.paginate(rows, limit, offset)
    return ok_array([public(e) for e in page], limit, offset, total)


@bp.get("/registrations/<rid>/transfers")
def list_transfers(rid):
    require_roles(["WarrantyAdmin", "Owner"])
    _get_reg_or_404(rid)
    limit, offset = common.parse_pagination()
    rows = [t for t in db.warranty_transfers.values() if t["registration_id"] == rid]
    page, total = common.paginate(rows, limit, offset)
    return ok_array([public(t) for t in page], limit, offset, total)
