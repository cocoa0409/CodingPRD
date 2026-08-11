from flask import Blueprint, request
from middleware import get_caller, require_role, get_json_body
from services.common import (require_string, optional_enum, optional_int,
                             optional_bool, parse_pagination)
from response import success_object, success_list
from errors import ApiError
from db import db, new_common
from services.serialize import serialize

bp = Blueprint("landlords", __name__)
REPORT_CHANNELS = {"EMAIL", "MAIL", "PORTAL"}
READ_ROLES = {"FarmManager", "Landlord", "Tenant"}


@bp.route("/landlords", methods=["POST"])
def create_landlord():
    _, role = get_caller()
    require_role(role, {"FarmManager"})
    body = get_json_body()
    name = require_string(body, "name")
    email = require_string(body, "contact_email")
    absentee = optional_bool(body, "absentee", default=False)
    channel = optional_enum(body, "report_channel", REPORT_CHANNELS, default="EMAIL")
    ack_days = optional_int(body, "ack_required_days", minimum=1, default=14)

    rec = new_common()
    rec.update({
        "name": name,
        "contact_email": email,
        "absentee": absentee,
        "report_channel": channel,
        "ack_required_days": ack_days,
        "total_received_cents": 0,
        "pending_receivable_cents": 0,
    })
    db.landlords[rec["id"]] = rec
    return success_object(serialize("landlord", rec), status=201)


@bp.route("/landlords/<landlordId>", methods=["GET"])
def get_landlord(landlordId):
    _, role = get_caller()
    require_role(role, READ_ROLES)
    rec = db.landlords.get(landlordId)
    if rec is None:
        raise ApiError("ERR_NOT_FOUND", 404, f"Landlord {landlordId} not found")
    return success_object(serialize("landlord", rec))


@bp.route("/landlords", methods=["GET"])
def list_landlords():
    _, role = get_caller()
    require_role(role, READ_ROLES)
    limit, offset = parse_pagination(request.args)
    items = sorted(db.landlords.values(), key=lambda r: r["created_at"])
    absentee_q = request.args.get("absentee")
    if absentee_q is not None:
        if absentee_q.lower() in ("true", "1"):
            items = [r for r in items if r.get("absentee") is True]
        elif absentee_q.lower() in ("false", "0"):
            items = [r for r in items if r.get("absentee") is False]
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serialize("landlord", r) for r in page], limit, offset, total)
