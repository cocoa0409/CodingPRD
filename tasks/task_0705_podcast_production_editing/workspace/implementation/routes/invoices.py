"""Invoice endpoints (PRD §3.9). Invoices are created by side effects (publish,
cycle close), never via a create endpoint."""
from flask import Blueprint, request

import errors
import middleware as mw
from db import db
from response import array_response, object_response
from routes.common import assert_show_owner, get_or_404
from serialize import serialize, serialize_list
from services import show_state

bp = Blueprint("invoices", __name__)


@bp.get("/invoices")
def list_invoices():
    auth = mw.authenticate()
    mw.require_role(auth, {"PlatformAdmin", "ShowOwner"})
    limit, offset = mw.parse_pagination()
    records = db.invoices.all()
    show_id = request.args.get("show_id")
    episode_id = request.args.get("episode_id")
    cycle_id = request.args.get("retainer_cycle_id")
    status = request.args.get("status")
    if show_id is not None:
        records = [r for r in records if r["show_id"] == show_id]
    if episode_id is not None:
        records = [r for r in records if r["episode_id"] == episode_id]
    if cycle_id is not None:
        records = [r for r in records if r["retainer_cycle_id"] == cycle_id]
    if status is not None:
        records = [r for r in records if r["status"] == status]
    if auth.role == "ShowOwner":
        records = [r for r in records if r["show_id"] == auth.user_id]
    page, meta = mw.paginate(records, limit, offset)
    return array_response(serialize_list(page), meta)


@bp.get("/invoices/<rid>")
def get_invoice(rid):
    auth = mw.authenticate()
    mw.require_role(auth, {"PlatformAdmin", "ShowOwner"})
    rec = get_or_404(db.invoices, rid)
    assert_show_owner(auth, rec["show_id"])
    return object_response(serialize(rec))


def _recompute(rec):
    show = db.shows.get(rec["show_id"])
    if show is not None:
        show_state.recompute_posture(show)


@bp.post("/invoices/<rid>/pay")
def pay_invoice(rid):
    auth = mw.authenticate()
    mw.require_role(auth, {"ShowOwner"})
    rec = get_or_404(db.invoices, rid)
    assert_show_owner(auth, rec["show_id"])
    if rec["status"] not in {"ISSUED", "OVERDUE", "DISPUTED"}:
        raise errors.err(errors.ERR_INVALID_STATE, "Invoice cannot be paid in this state")
    rec["status"] = "PAID"
    db.invoices.touch(rec)
    _recompute(rec)
    return object_response(serialize(rec))


@bp.post("/invoices/<rid>/mark-overdue")
def mark_overdue(rid):
    auth = mw.authenticate()
    mw.require_role(auth, {"PlatformAdmin"})
    rec = get_or_404(db.invoices, rid)
    if rec["status"] != "ISSUED":
        raise errors.err(errors.ERR_INVALID_STATE, "Invoice is not ISSUED")
    rec["status"] = "OVERDUE"
    db.invoices.touch(rec)
    _recompute(rec)
    return object_response(serialize(rec))


@bp.post("/invoices/<rid>/dispute")
def dispute_invoice(rid):
    auth = mw.authenticate()
    mw.require_role(auth, {"ShowOwner"})
    rec = get_or_404(db.invoices, rid)
    assert_show_owner(auth, rec["show_id"])
    if rec["status"] != "ISSUED":
        raise errors.err(errors.ERR_INVALID_STATE, "Invoice is not ISSUED")
    rec["status"] = "DISPUTED"
    db.invoices.touch(rec)
    _recompute(rec)
    return object_response(serialize(rec))


@bp.post("/invoices/<rid>/void")
def void_invoice(rid):
    auth = mw.authenticate()
    mw.require_role(auth, {"PlatformAdmin"})
    rec = get_or_404(db.invoices, rid)
    if rec["status"] != "DISPUTED":
        raise errors.err(errors.ERR_INVALID_STATE, "Invoice is not DISPUTED")
    rec["status"] = "VOID"
    db.invoices.touch(rec)
    # reverse the original billing (PRD §3.9) before posture recompute
    show = db.shows.get(rec["show_id"])
    if show is not None:
        show["lifetime_billed_cents"] = show["lifetime_billed_cents"] - rec["total_cents"]
        db.shows.touch(show)
        show_state.recompute_posture(show)
    return object_response(serialize(rec))
