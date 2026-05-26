"""ThankYouNote routes: list, read, draft, send."""
from __future__ import annotations

from flask import Blueprint, request

import db
from errors import APIError, ERR_INVALID_REQUEST, ERR_INVALID_STATE
from middleware import require_auth, current_role, current_user_id, get_json_body
from response import ok_object, ok_array, paginate
from services.pagination import parse_pagination, sort_by_created
from services.wedding import (
    get_thank_you_or_404,
    assert_couple_owns,
    assert_not_archived,
)

bp = Blueprint("thank_you_notes", __name__)


@bp.route("/thank-you-notes", methods=["GET"])
def list_thank_you_notes():
    require_auth(["Couple", "PlatformAdmin"])()
    limit, offset = parse_pagination()
    w_id = request.args.get("wedding_id")
    p_id = request.args.get("purchase_id")
    status_f = request.args.get("status")
    rows = list(db.thank_you_notes.values())
    if current_role() == "Couple":
        owned = {w["id"] for w in db.weddings.values()
                 if w.get("couple_user_id") == current_user_id()}
        rows = [t for t in rows if t.get("wedding_id") in owned]
    if w_id is not None:
        rows = [t for t in rows if t.get("wedding_id") == w_id]
    if p_id is not None:
        rows = [t for t in rows if t.get("purchase_id") == p_id]
    if status_f is not None:
        rows = [t for t in rows if t.get("status") == status_f]
    rows = sort_by_created(rows)
    page, total = paginate(rows, limit, offset)
    return ok_array(page, limit, offset, total)


@bp.route("/thank-you-notes/<tid>", methods=["GET"])
def get_thank_you(tid):
    require_auth(["Couple", "PlatformAdmin"])()
    t = get_thank_you_or_404(tid)
    if current_role() == "Couple":
        w = db.weddings.get(t["wedding_id"])
        if w:
            assert_couple_owns(w)
    return ok_object(t)


@bp.route("/thank-you-notes/<tid>/draft", methods=["POST"])
def draft_thank_you(tid):
    require_auth(["Couple"])()
    t = get_thank_you_or_404(tid)
    w = db.weddings.get(t["wedding_id"])
    if w is None:
        raise APIError(ERR_INVALID_STATE, 409, "Wedding missing")
    assert_couple_owns(w)
    assert_not_archived(w)
    body = get_json_body()
    drafted_body = body.get("drafted_body")
    if not isinstance(drafted_body, str) or not drafted_body.strip():
        raise APIError(ERR_INVALID_REQUEST, 400, "drafted_body is required and must be non-empty")
    if t.get("status") != "PENDING":
        raise APIError(ERR_INVALID_STATE, 409, "ThankYouNote must be PENDING to draft")
    # Parent purchase must be CONFIRMED.
    p = db.purchases.get(t.get("purchase_id"))
    if p is None or p.get("status") != "CONFIRMED":
        raise APIError(ERR_INVALID_STATE, 409, "parent Purchase must be CONFIRMED")
    t["status"] = "DRAFTED"
    t["drafted_body"] = drafted_body
    db.bump(t)
    return ok_object(t)


@bp.route("/thank-you-notes/<tid>/send", methods=["POST"])
def send_thank_you(tid):
    require_auth(["Couple"])()
    t = get_thank_you_or_404(tid)
    w = db.weddings.get(t["wedding_id"])
    if w is None:
        raise APIError(ERR_INVALID_STATE, 409, "Wedding missing")
    assert_couple_owns(w)
    assert_not_archived(w)
    if t.get("status") != "DRAFTED":
        raise APIError(ERR_INVALID_STATE, 409, "ThankYouNote must be DRAFTED to send")
    if not isinstance(t.get("drafted_body"), str) or not t["drafted_body"].strip():
        raise APIError(ERR_INVALID_STATE, 409, "drafted_body must be non-empty before sending")
    p = db.purchases.get(t.get("purchase_id"))
    if p is None or p.get("status") != "CONFIRMED":
        raise APIError(ERR_INVALID_STATE, 409, "parent Purchase must be CONFIRMED")
    t["status"] = "SENT"
    t["sent_at"] = db.get_current_utc()
    db.bump(t)
    return ok_object(t)
