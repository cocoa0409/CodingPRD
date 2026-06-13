"""Top-level reload and loyalty-ledger read endpoints (PRD §4)."""
from flask import Blueprint, request

from db import db
from middleware import get_identity, require_roles
from response import object_response, array_response
from services.common import parse_pagination, paginate, get_or_404
from services.serialize import view

bp = Blueprint("transactions", __name__)


# ---- Reloads ----------------------------------------------------------------
@bp.get("/reloads")
def list_reloads():
    _, role = get_identity()
    require_roles(role, {"Manager", "Attendant", "Member"})
    limit, offset = parse_pagination()
    member_id = request.args.get("member_id")
    shift_id = request.args.get("shift_id")
    tender = request.args.get("tender")
    status = request.args.get("status")
    items = list(db.reloads.values())
    if member_id is not None:
        items = [r for r in items if r["member_id"] == member_id]
    if shift_id is not None:
        items = [r for r in items if r.get("shift_id") == shift_id]
    if tender is not None:
        items = [r for r in items if r["tender"] == tender]
    if status is not None:
        items = [r for r in items if r["status"] == status]
    window, total = paginate(items, limit, offset)
    return array_response([view(r) for r in window], limit, offset, total)


@bp.get("/reloads/<reload_id>")
def get_reload(reload_id):
    _, role = get_identity()
    require_roles(role, {"Manager", "Attendant", "Member"})
    reload_txn = get_or_404(db.reloads, reload_id, "ReloadTransaction")
    return object_response(view(reload_txn))


# ---- Loyalty ledger ---------------------------------------------------------
@bp.get("/loyalty-ledger")
def list_loyalty_ledger():
    _, role = get_identity()
    require_roles(role, {"Manager", "Attendant", "Member"})
    limit, offset = parse_pagination()
    member_id = request.args.get("member_id")
    vend_id = request.args.get("vend_id")
    entry_type = request.args.get("entry_type")
    items = list(db.loyalty_ledger.values())
    if member_id is not None:
        items = [e for e in items if e["member_id"] == member_id]
    if vend_id is not None:
        items = [e for e in items if e.get("vend_id") == vend_id]
    if entry_type is not None:
        items = [e for e in items if e["entry_type"] == entry_type]
    window, total = paginate(items, limit, offset)
    return array_response([view(e) for e in window], limit, offset, total)


@bp.get("/loyalty-ledger/<entry_id>")
def get_loyalty_ledger_entry(entry_id):
    _, role = get_identity()
    require_roles(role, {"Manager", "Attendant", "Member"})
    entry = get_or_404(db.loyalty_ledger, entry_id, "LoyaltyLedgerEntry")
    return object_response(view(entry))
