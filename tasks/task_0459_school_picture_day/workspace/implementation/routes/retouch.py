"""RetouchOrder routes: create (with retouch_cost calc), approve/complete/
reject/cancel, with RETAKE photo lifecycle and credit reservation."""
from flask import Blueprint, request

import db
import store
from common import (
    BASE_RETOUCH_FEE,
    COMP_PCT,
    PER_ADJUSTMENT_FEE,
    get_body,
    paginate,
    parse_pagination,
    require_enum,
    require_fields,
    require_int,
    require_str,
    round_half_up,
    sort_by_creation,
)
from errors import err
from middleware import get_user_context, require_role
from response import array_response, object_response
from services import ledger

bp = Blueprint("retouch", __name__)


def _premium_linked(photo):
    """True if the photo's matched student has a PAID order with has_premium_line."""
    sid = photo.get("matched_student_id")
    if sid is None:
        return False
    for o in db.photo_orders.values():
        if o["student_id"] == sid and o["status"] == "PAID" and o["has_premium_line"]:
            return True
    return False


@bp.route("/api/retouch-orders", methods=["POST"])
def create_retouch():
    _uid, role = get_user_context()
    require_role(role, ["StudioPhotographer"])
    body = get_body()
    require_fields(body, ["photo_id", "kind"])
    photo_id = require_str(body, "photo_id")
    kind = require_enum(body, "kind", {"RETOUCH", "RETAKE"})
    if "adjustment_count" in body and body["adjustment_count"] is not None:
        adjustment_count = require_int(body, "adjustment_count")
        if adjustment_count < 0:
            raise err("ERR_INVALID_REQUEST", "adjustment_count must be >= 0")
    else:
        adjustment_count = 0

    with db.LOCK:
        photo = store.get_photo(photo_id)
        session = store.get_session(photo["picture_day_session_id"])

        # For RETAKE: session must be CAPTURE_OPEN/GALLERY_OPEN, photo MATCHED.
        if kind == "RETAKE":
            if session["status"] not in ("CAPTURE_OPEN", "GALLERY_OPEN"):
                raise err("ERR_SESSION_NOT_RETAKEABLE", "Session not retakeable")
            if photo["status"] != "MATCHED":
                raise err("ERR_PHOTO_NOT_RETAKEABLE", "Photo not in MATCHED state")

        # retouch_cost (pinned evaluation order).
        gross = BASE_RETOUCH_FEE + PER_ADJUSTMENT_FEE * adjustment_count
        premium_linked = _premium_linked(photo)
        comp_discount = round_half_up(gross * COMP_PCT) if premium_linked else 0
        net_cost = gross - comp_discount

        row = store.new_row("retouch", {
            "photo_id": photo_id,
            "kind": kind,
            "adjustment_count": adjustment_count,
            "premium_linked": premium_linked,
            "gross_cost_cents": gross,
            "comp_discount_cents": comp_discount,
            "net_cost_cents": net_cost,
            "replacement_photo_id": None,
            "status": "REQUESTED",
        })
        db.retouch_orders[row["id"]] = row

        # Side effect for RETAKE: photo MATCHED -> RETAKE_REQUESTED.
        if kind == "RETAKE":
            photo["status"] = "RETAKE_REQUESTED"
            store.touch(photo)
    return object_response(store.serialize(row), 201)


@bp.route("/api/retouch-orders", methods=["GET"])
def list_retouch():
    _uid, role = get_user_context()
    require_role(role, ["SchoolCoordinator", "StudioPhotographer"])
    limit, offset = parse_pagination()
    photo_id = request.args.get("photo_id")
    replacement_photo_id = request.args.get("replacement_photo_id")
    status = request.args.get("status")
    rows = list(db.retouch_orders.values())
    if photo_id is not None:
        rows = [r for r in rows if r["photo_id"] == photo_id]
    if replacement_photo_id is not None:
        rows = [r for r in rows if r["replacement_photo_id"] == replacement_photo_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    rows = sort_by_creation(rows)
    page, total = paginate(rows, limit, offset)
    return array_response([store.serialize(r) for r in page], limit, offset, total)


@bp.route("/api/retouch-orders/<rid>", methods=["GET"])
def get_retouch(rid):
    _uid, role = get_user_context()
    require_role(role, ["SchoolCoordinator", "StudioPhotographer"])
    return object_response(store.serialize(store.get_retouch(rid)))


@bp.route("/api/retouch-orders/<rid>/approve", methods=["POST"])
def approve_retouch(rid):
    _uid, role = get_user_context()
    require_role(role, ["StudioPhotographer"])
    with db.LOCK:
        r = store.get_retouch(rid)
        if r["status"] != "REQUESTED":
            raise err("ERR_RETOUCH_NOT_REQUESTED", "Retouch order is not REQUESTED")
        photo = store.get_photo(r["photo_id"])
        session = store.get_session(photo["picture_day_session_id"])
        if r["net_cost_cents"] > session["retouch_credit_balance_cents"]:
            raise err("ERR_INSUFFICIENT_RETOUCH_CREDIT", "Net cost exceeds retouch credit balance")
        r["status"] = "APPROVED"
        store.touch(r)
        ledger.reserve_retouch_credit(session, r["net_cost_cents"])
    return object_response(store.serialize(r))


@bp.route("/api/retouch-orders/<rid>/complete", methods=["POST"])
def complete_retouch(rid):
    _uid, role = get_user_context()
    require_role(role, ["StudioPhotographer"])
    with db.LOCK:
        r = store.get_retouch(rid)
        if r["status"] != "APPROVED":
            raise err("ERR_RETOUCH_NOT_APPROVED", "Retouch order is not APPROVED")
        r["status"] = "DONE"
        # For RETAKE: drive photo RETAKE_REQUESTED -> RETAKEN; create replacement.
        if r["kind"] == "RETAKE":
            old_photo = store.get_photo(r["photo_id"])
            old_photo["status"] = "RETAKEN"
            store.touch(old_photo)
            replacement = store.new_row("photo", {
                "picture_day_session_id": old_photo["picture_day_session_id"],
                "matched_student_id": old_photo["matched_student_id"],
                "retake_of_photo_id": old_photo["id"],
                "candidate_grade": old_photo["candidate_grade"],
                "candidate_homeroom": old_photo["candidate_homeroom"],
                "candidate_name": old_photo["candidate_name"],
                "match_confidence_score": old_photo["match_confidence_score"],
                "yearbook_exported": False,
                "status": "MATCHED",
            })
            db.photos[replacement["id"]] = replacement
            r["replacement_photo_id"] = replacement["id"]
        store.touch(r)
    return object_response(store.serialize(r))


@bp.route("/api/retouch-orders/<rid>/reject", methods=["POST"])
def reject_retouch(rid):
    _uid, role = get_user_context()
    require_role(role, ["StudioPhotographer"])
    with db.LOCK:
        r = store.get_retouch(rid)
        if r["status"] != "REQUESTED":
            raise err("ERR_RETOUCH_NOT_REQUESTED", "Retouch order is not REQUESTED")
        r["status"] = "REJECTED"
        store.touch(r)
        # For RETAKE: revert photo RETAKE_REQUESTED -> MATCHED.
        if r["kind"] == "RETAKE":
            photo = db.photos.get(r["photo_id"])
            if photo is not None and photo["status"] == "RETAKE_REQUESTED":
                photo["status"] = "MATCHED"
                store.touch(photo)
    return object_response(store.serialize(r))


@bp.route("/api/retouch-orders/<rid>/cancel", methods=["POST"])
def cancel_retouch(rid):
    _uid, role = get_user_context()
    require_role(role, ["StudioPhotographer"])
    with db.LOCK:
        r = store.get_retouch(rid)
        if r["status"] not in ("REQUESTED", "APPROVED"):
            raise err("ERR_RETOUCH_NOT_CANCELLABLE", "Retouch order is not cancellable")
        was_approved = r["status"] == "APPROVED"
        r["status"] = "CANCELLED"
        store.touch(r)
        # Release reserved credit if it was APPROVED.
        if was_approved:
            photo = store.get_photo(r["photo_id"])
            session = store.get_session(photo["picture_day_session_id"])
            ledger.release_retouch_credit(session, r["net_cost_cents"])
        # For RETAKE: revert photo RETAKE_REQUESTED -> MATCHED.
        if r["kind"] == "RETAKE":
            photo = db.photos.get(r["photo_id"])
            if photo is not None and photo["status"] == "RETAKE_REQUESTED":
                photo["status"] = "MATCHED"
                store.touch(photo)
    return object_response(store.serialize(r))
