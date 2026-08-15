"""Blackout window CRUD."""
from flask import Blueprint, request

from db import db
from errors import ERR_INVALID_REQUEST, ERR_NOT_FOUND, ERR_BLACKOUT_WINDOW_OVERLAP, ApiError
from middleware import require_role, get_auth
from response import success_object, success_list
from utils import BLACKOUT_FIELDS, serialize, stamp_created, parse_pagination, paginate, parse_date

blackout_bp = Blueprint("blackout_windows", __name__)


@blackout_bp.route("/blackout-windows", methods=["POST"])
def create_blackout():
    user_id, role = require_role("ComplianceOfficer")
    body = request.get_json(force=True) or {}

    for f in ["issuer_id", "start_date", "end_date"]:
        if f not in body or body[f] is None:
            raise ApiError(ERR_INVALID_REQUEST, f"{f} is required.", 400)

    if body["issuer_id"] not in db.issuers:
        raise ApiError(ERR_INVALID_REQUEST, f"issuer_id {body['issuer_id']} not found.", 400)

    try:
        sd = parse_date(body["start_date"])
        ed = parse_date(body["end_date"])
    except (ValueError, TypeError):
        raise ApiError(ERR_INVALID_REQUEST, "start_date and end_date must be YYYY-MM-DD.", 400)

    if sd > ed:
        raise ApiError(ERR_INVALID_REQUEST, "start_date must not be later than end_date.", 400)

    # Overlap check: same issuer, share at least one calendar date
    for w in db.blackout_windows.values():
        if w["issuer_id"] != body["issuer_id"]:
            continue
        wsd = parse_date(w["start_date"])
        wed = parse_date(w["end_date"])
        if sd <= wed and wsd <= ed:
            raise ApiError(ERR_BLACKOUT_WINDOW_OVERLAP, "Blackout window overlaps an existing window.", 409)

    window = {
        "issuer_id": body["issuer_id"],
        "start_date": body["start_date"],
        "end_date": body["end_date"],
        "reason": body.get("reason"),
    }
    stamp_created(window)
    db.blackout_windows[window["id"]] = window
    return success_object(serialize(window, BLACKOUT_FIELDS), 201)


@blackout_bp.route("/blackout-windows", methods=["GET"])
def list_blackouts():
    get_auth()
    limit, offset = parse_pagination(request.args)
    issuer_id = request.args.get("issuer_id")
    items = sorted(db.blackout_windows.values(), key=lambda x: x["created_at"])
    if issuer_id:
        items = [w for w in items if w["issuer_id"] == issuer_id]
    page, total = paginate(items, limit, offset)
    return success_list([serialize(w, BLACKOUT_FIELDS) for w in page], limit, offset, total)


@blackout_bp.route("/blackout-windows/<blackoutWindowId>", methods=["GET"])
def get_blackout(blackoutWindowId):
    get_auth()
    w = db.blackout_windows.get(blackoutWindowId)
    if not w:
        raise ApiError(ERR_NOT_FOUND, f"BlackoutWindow {blackoutWindowId} not found.", 404)
    return success_object(serialize(w, BLACKOUT_FIELDS))
