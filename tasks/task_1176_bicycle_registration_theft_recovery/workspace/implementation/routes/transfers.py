"""Ownership transfers / sale reporting (PRD §3.3)."""
from datetime import timedelta

from flask import Blueprint, g, request

import db
from errors import fail
from middleware import body, require_roles
from models import transfer_view
from response import list_response, ok_object
from routes.common import field, load

bp = Blueprint("transfers", __name__)

TRANSFER_FEE_CENTS = 300


@bp.post("/registry/transfers")
@require_roles("Owner")
def create_transfer():
    data = body()
    bicycle_id = field(data, "bicycle_id", "string", required=True)
    to_owner_email = field(data, "to_owner_email", "string", required=True)
    sale_price_cents = field(data, "sale_price_cents", "integer", required=True, min_value=0)

    bicycle = load(db.bicycles, bicycle_id, "ERR_BICYCLE_NOT_FOUND")
    # Seller must be the bicycle's current owner.
    if bicycle["current_owner_id"] != g.user_id:
        fail("ERR_FORBIDDEN_RESOURCE_ACCESS", "Only the current owner may sell this bicycle")
    buyer = next((o for o in db.owners.values()
                  if o["email"].lower() == to_owner_email.lower()), None)
    if buyer is None:
        fail("ERR_OWNER_NOT_FOUND", "to_owner_email does not resolve to an owner")

    # Stage 9: bicycle transferability / merge guard.
    if bicycle["integrity_status"] == "MERGED":
        fail("ERR_BICYCLE_MERGED", "Merged bicycles cannot be transferred")
    if bicycle["registry_status"] != "REGISTERED":
        fail("ERR_BICYCLE_NOT_TRANSFERABLE",
             "Only a REGISTERED bicycle can be sold through the registry")
    # Stage 11: duplicate-suspect safety hold.
    if bicycle["integrity_status"] == "DUPLICATE_SUSPECT":
        fail("ERR_DUPLICATE_HOLD", "Bicycle is under a duplicate-suspect safety hold")
    # Stage 12: one pending transfer per bicycle; seller != buyer.
    if any(t["bicycle_id"] == bicycle_id and t["status"] == "PENDING_ACCEPTANCE"
           for t in db.transfers.values()):
        fail("ERR_TRANSFER_ALREADY_PENDING", "A pending transfer already exists for this bicycle")
    if buyer["id"] == g.user_id:
        fail("ERR_SELF_TRANSFER", "Seller and buyer must be different owners")

    rec = db.new_record({
        "bicycle_id": bicycle_id,
        "from_owner_id": g.user_id,
        "to_owner_id": buyer["id"],
        "to_owner_email": to_owner_email,
        "sale_price_cents": sale_price_cents,
        "status": "PENDING_ACCEPTANCE",
        "expires_at": db.now() + timedelta(days=7),
    })
    db.transfers[rec["id"]] = rec
    return ok_object(transfer_view(rec), status=201)


@bp.get("/registry/transfers")
@require_roles("Owner", "Registrar", "Admin")
def list_transfers():
    recs = list(db.transfers.values())
    if g.role == "Owner":
        recs = [t for t in recs
                if t["from_owner_id"] == g.user_id or t["to_owner_id"] == g.user_id]
    for param, key in (("bicycle_id", "bicycle_id"), ("from_owner_id", "from_owner_id"),
                       ("to_owner_id", "to_owner_id"), ("status", "status")):
        value = request.args.get(param)
        if value is not None:
            recs = [t for t in recs if t[key] == value]
    return list_response(recs, transfer_view)


@bp.get("/registry/transfers/<transfer_id>")
@require_roles("Owner", "Registrar", "Admin")
def read_transfer(transfer_id):
    rec = load(db.transfers, transfer_id, "ERR_TRANSFER_NOT_FOUND")
    if g.role == "Owner" and g.user_id not in (rec["from_owner_id"], rec["to_owner_id"]):
        fail("ERR_FORBIDDEN_RESOURCE_ACCESS", "Only participant owners may read a transfer")
    return ok_object(transfer_view(rec))


def _lazy_expire_if_needed(rec):
    """Accept/cancel past expiry: auto-transition to EXPIRED, then fail."""
    if db.now() > rec["expires_at"]:
        rec["status"] = "EXPIRED"
        db.bump(rec)
        fail("ERR_TRANSFER_EXPIRED", "The acceptance window has closed")


@bp.post("/registry/transfers/<transfer_id>/accept")
@require_roles("Owner")
def accept_transfer(transfer_id):
    rec = load(db.transfers, transfer_id, "ERR_TRANSFER_NOT_FOUND")
    if rec["to_owner_id"] != g.user_id:
        fail("ERR_FORBIDDEN_RESOURCE_ACCESS", "Only the buyer may accept a transfer")
    if rec["status"] != "PENDING_ACCEPTANCE":
        fail("ERR_TRANSFER_NOT_PENDING", "Transfer is not pending acceptance")
    _lazy_expire_if_needed(rec)

    # Re-verify at accept time that the bicycle is REGISTERED and CLEAR.
    bicycle = db.bicycles.get(rec["bicycle_id"])
    if bicycle is None:
        fail("ERR_BICYCLE_NOT_FOUND", "Transfer bicycle no longer exists")
    if bicycle["integrity_status"] == "MERGED":
        fail("ERR_BICYCLE_MERGED", "Merged bicycles cannot be transferred")
    if bicycle["registry_status"] != "REGISTERED":
        fail("ERR_BICYCLE_NOT_TRANSFERABLE", "Bicycle is no longer REGISTERED")
    if bicycle["integrity_status"] != "CLEAR":
        fail("ERR_DUPLICATE_HOLD", "Bicycle is under a duplicate-suspect safety hold")

    bicycle["current_owner_id"] = rec["to_owner_id"]
    db.bump(bicycle)
    db.post_ledger("TRANSFER_FEE", "DEBIT", "OWNER", TRANSFER_FEE_CENTS,
                   owner_id=rec["to_owner_id"], bicycle_id=bicycle["id"],
                   reference_note=f"Transfer {rec['id']} acceptance fee")
    db.post_ledger("TRANSFER_FEE", "CREDIT", "PROGRAM", TRANSFER_FEE_CENTS,
                   bicycle_id=bicycle["id"],
                   reference_note=f"Transfer {rec['id']} acceptance fee")
    db.notify(rec["from_owner_id"], "TRANSFER_COMPLETED",
              "Your bicycle transfer was completed.",
              related_entity_type="OwnershipTransfer", related_entity_id=rec["id"])
    rec["status"] = "COMPLETED"
    db.bump(rec)
    return ok_object(transfer_view(rec))


@bp.post("/registry/transfers/<transfer_id>/reject")
@require_roles("Owner")
def reject_transfer(transfer_id):
    rec = load(db.transfers, transfer_id, "ERR_TRANSFER_NOT_FOUND")
    if rec["to_owner_id"] != g.user_id:
        fail("ERR_FORBIDDEN_RESOURCE_ACCESS", "Only the buyer may reject a transfer")
    if rec["status"] != "PENDING_ACCEPTANCE":
        fail("ERR_TRANSFER_NOT_PENDING", "Transfer is not pending acceptance")
    rec["status"] = "REJECTED"
    db.bump(rec)
    return ok_object(transfer_view(rec))


@bp.post("/registry/transfers/<transfer_id>/cancel")
@require_roles("Owner")
def cancel_transfer(transfer_id):
    rec = load(db.transfers, transfer_id, "ERR_TRANSFER_NOT_FOUND")
    if rec["from_owner_id"] != g.user_id:
        fail("ERR_FORBIDDEN_RESOURCE_ACCESS", "Only the seller may cancel a transfer")
    if rec["status"] != "PENDING_ACCEPTANCE":
        fail("ERR_TRANSFER_NOT_PENDING", "Transfer is not pending acceptance")
    _lazy_expire_if_needed(rec)
    rec["status"] = "CANCELLED"
    db.bump(rec)
    return ok_object(transfer_view(rec))
