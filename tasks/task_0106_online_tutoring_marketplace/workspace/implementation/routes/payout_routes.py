"""Payout batch routes."""

from flask import Blueprint, g, request

from db import db, init_link_or_batch_fields, touch
from errors import APIError
from middleware import require_auth
from response import list_response, success_response
from services.pagination import get_pagination, slice_items
from services.validators import require_body, require_string

payout_bp = Blueprint("payout", __name__)


def _settled_sessions_not_in_batch(tutor_id):
    """SETTLED sessions for tutor not attached to any REQUESTED or PAID batch."""
    attached = set()
    for b in db.payout_batches.values():
        if b["status"] in ("REQUESTED", "PAID"):
            for sid in b.get("session_ids", []):
                attached.add(sid)
    out = []
    for s in db.sessions.values():
        if s["tutor_id"] != tutor_id:
            continue
        if s["status"] != "SETTLED":
            continue
        if s["id"] in attached:
            continue
        out.append(s)
    out.sort(key=lambda r: r["id"])
    return out


@payout_bp.route("/payouts", methods=["POST"])
@require_auth({"PlatformAdmin"})
def create_payout():
    body = request.get_json(silent=True) or {}
    require_body(body)
    tutor_id = require_string(body, "tutor_id")
    tutor = db.tutors.get(tutor_id)
    if tutor is None:
        raise APIError("ERR_NOT_FOUND")

    sessions = _settled_sessions_not_in_batch(tutor_id)
    summed = sum(s.get("tutor_payout_cents", 0) for s in sessions)
    current_balance = tutor.get("payout_balance_cents", 0)
    if summed != current_balance:
        # Should not happen (invariant) but enforce ERR_PAYOUT_STALE
        raise APIError("ERR_PAYOUT_STALE")

    batch = init_link_or_batch_fields({
        "tutor_id": tutor_id,
        "status": "REQUESTED",
        "amount_cents": current_balance,
        "session_ids": [s["id"] for s in sessions],
        "requested_by": g.user_id,
    })
    db.payout_batches[batch["id"]] = batch
    return success_response(batch, status=201)


@payout_bp.route("/payouts/<payout_id>/mark-paid", methods=["POST"])
@require_auth({"PlatformAdmin"})
def mark_paid(payout_id):
    batch = db.payout_batches.get(payout_id)
    if batch is None:
        raise APIError("ERR_NOT_FOUND")
    if batch["status"] != "REQUESTED":
        raise APIError("ERR_INVALID_STATE")
    if g.user_id == batch["requested_by"]:
        raise APIError("ERR_SEGREGATION_VIOLATION")
    tutor = db.tutors.get(batch["tutor_id"])
    if tutor is None:
        raise APIError("ERR_NOT_FOUND")
    if tutor.get("payout_balance_cents", 0) != batch["amount_cents"]:
        raise APIError("ERR_PAYOUT_STALE")
    tutor["payout_balance_cents"] -= batch["amount_cents"]
    touch(tutor)
    batch["status"] = "PAID"
    return success_response(batch, status=200)


@payout_bp.route("/payouts/<payout_id>/reverse", methods=["POST"])
@require_auth({"PlatformAdmin"})
def reverse_payout(payout_id):
    batch = db.payout_batches.get(payout_id)
    if batch is None:
        raise APIError("ERR_NOT_FOUND")
    if batch["status"] != "REQUESTED":
        raise APIError("ERR_INVALID_STATE")
    batch["status"] = "REVERSED"
    return success_response(batch, status=200)


@payout_bp.route("/payouts", methods=["GET"])
@require_auth({"PlatformAdmin", "Tutor"})
def list_payouts():
    limit, offset = get_pagination()
    tutor_id_filter = request.args.get("tutor_id")
    status_filter = request.args.get("status")
    items = list(db.payout_batches.values())
    if g.user_role == "Tutor":
        items = [b for b in items if b["tutor_id"] == g.user_id]
    if tutor_id_filter:
        items = [b for b in items if b["tutor_id"] == tutor_id_filter]
    if status_filter:
        items = [b for b in items if b["status"] == status_filter]
    items.sort(key=lambda r: r["created_at"])
    total = len(items)
    page = slice_items(items, limit, offset)
    return list_response(page, total, limit, offset, status=200)
