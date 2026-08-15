"""Succession notice endpoints."""
from flask import Blueprint, g, request

import db
import utils
from errors import ApiError
from middleware import ANY_ROLE, body, paginate, require_roles
from response import ok
from services import domain

bp = Blueprint("succession", __name__)


def get_notice_or_404(notice_id):
    r = db.succession_notices.get(notice_id)
    if r is None:
        raise ApiError("ERR_SUCCESSION_NOTICE_NOT_FOUND", "SuccessionNotice id does not exist.", 404)
    return r


@bp.route("/stewardship/succession-notices", methods=["POST"])
@require_roles("Landowner")
def create_notice():
    b = body()
    easement_id = b.get("easement_id")
    if easement_id is not None and easement_id not in db.easements:
        raise ApiError("ERR_EASEMENT_NOT_FOUND", "Easement id does not exist.", 404)
    e = db.easements.get(easement_id)
    if e is not None and e["status"] != "RECORDED":
        raise ApiError("ERR_EASEMENT_NOT_RECORDED", "Child operational create requires a RECORDED easement.", 409)
    successor_name = b.get("successor_owner_name")
    successor_email = b.get("successor_contact_email")
    transfer_on = utils.parse_date(b.get("transfer_on"))
    if (
        e is None
        or not isinstance(successor_name, str)
        or not isinstance(successor_email, str)
        or transfer_on is None
    ):
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "easement_id, successor_owner_name, successor_contact_email and transfer_on are required.",
            400,
        )
    # Temporal (priority 10): transfer at least 30 days after the clock date.
    if transfer_on < utils.add_days(utils.today(), 30):
        raise ApiError(
            "ERR_NOTICE_WINDOW_VIOLATION",
            "transfer_on must be at least 30 days after the notice date.",
            422,
        )
    # Referential (priority 11).
    if g.user_id != e["current_landowner_id"]:
        raise ApiError("ERR_NOT_CURRENT_LANDOWNER", "Caller is not the easement's current landowner.", 403)
    today = utils.today()
    now = utils.now_iso()
    successor = {
        "id": utils.new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "easement_id": easement_id,
        "predecessor_landowner_id": e["current_landowner_id"],
        "owner_name": successor_name,
        "contact_email": successor_email,
        "status": "PENDING_SUCCESSION",
        "acquired_on": None,
    }
    db.landowners[successor["id"]] = successor
    r = {
        "id": utils.new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "easement_id": easement_id,
        "successor_landowner_id": successor["id"],
        "predecessor_landowner_id": e["current_landowner_id"],
        "transfer_on": transfer_on,
        "notice_given_on": today,
        "ack_deadline_on": utils.add_days(today, 45),
        "recorded_on": None,
        "status": "NOTICE_GIVEN",
    }
    db.succession_notices[r["id"]] = r
    return ok(domain.succession_json(r), 201)


@bp.route("/stewardship/succession-notices", methods=["GET"])
@require_roles(*ANY_ROLE)
def list_notices():
    filters = {}
    for key in ("easement_id", "successor_landowner_id", "predecessor_landowner_id", "status"):
        v = request.args.get(key)
        if v is not None:
            filters[key] = v
    return paginate(list(db.succession_notices.values()), domain.succession_json, filters)


@bp.route("/stewardship/succession-notices/<successionNoticeId>", methods=["GET"])
@require_roles(*ANY_ROLE)
def get_notice(successionNoticeId):
    return ok(domain.succession_json(get_notice_or_404(successionNoticeId)))


@bp.route("/stewardship/succession-notices/<successionNoticeId>/acknowledge", methods=["POST"])
@require_roles("TrustAdmin")
def acknowledge_notice(successionNoticeId):
    r = get_notice_or_404(successionNoticeId)
    if r["status"] != "NOTICE_GIVEN":
        raise ApiError("ERR_INVALID_NOTICE_STATE", "Acknowledge requires NOTICE_GIVEN.", 409)
    r["status"] = "ACKNOWLEDGED"
    domain.bump(r)
    return ok(domain.succession_json(r))


@bp.route("/stewardship/succession-notices/<successionNoticeId>/record", methods=["POST"])
@require_roles("TrustAdmin")
def record_notice(successionNoticeId):
    r = get_notice_or_404(successionNoticeId)
    if r["status"] != "ACKNOWLEDGED":
        raise ApiError("ERR_INVALID_NOTICE_STATE", "Record requires ACKNOWLEDGED.", 409)
    e = db.easements[r["easement_id"]]
    b = body()
    expected = b.get("expected_easement_version")
    # OCC (priority 6): compare when present and well-typed.
    if utils.is_int(expected) and expected != e["version"]:
        raise ApiError(
            "ERR_STALE_EASEMENT_VERSION",
            "expected_easement_version does not match the easement version.",
            412,
        )
    if not utils.is_int(expected):
        raise ApiError("ERR_INVALID_REQUEST", "expected_easement_version is required.", 400)
    today = utils.today()
    r["recorded_on"] = today
    r["status"] = "RECORDED"
    domain.bump(r)
    successor = db.landowners[r["successor_landowner_id"]]
    successor["status"] = "ACTIVE"
    successor["acquired_on"] = today
    domain.bump(successor)
    predecessor = db.landowners[r["predecessor_landowner_id"]]
    predecessor["status"] = "SUPERSEDED"
    domain.bump(predecessor)
    e["current_landowner_id"] = successor["id"]
    domain.bump(e)
    return ok(domain.succession_json(r))
