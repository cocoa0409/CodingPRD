"""Institution routes and the test-driving logical clock."""
from flask import Blueprint

import db
from errors import err
from middleware import get_user_context, require_role
from response import success
from services import dates, validate
from services.serialize import institution_view

bp = Blueprint("institutions", __name__)

ALL_ROLES = ("Registrar", "Bursar", "Student")


@bp.route("/institutions", methods=["POST"])
def create_institution():
    _, role = get_user_context()
    require_role(role, ("Registrar",))
    body = validate.get_body()
    name = validate.require_string(body, "name")

    currency = body.get("currency", "USD")
    if not isinstance(currency, str) or currency.strip() == "":
        raise err("ERR_INVALID_REQUEST", "currency must be a string")

    refund_policy = body.get("refund_policy", "DATE_BASED")
    if refund_policy not in ("DATE_BASED", "SCHEDULE_BASED"):
        raise err("ERR_INVALID_REQUEST", "invalid refund_policy")

    record = db.stamp_new({
        "name": name,
        "currency": currency,
        "refund_policy": refund_policy,
        # clock_utc begins at the Unix epoch (PRD §2.4).
        "clock_utc": dates.to_iso(dates.EPOCH),
    })
    db.institutions[record["id"]] = record
    return success(institution_view(record), status=201)


@bp.route("/institutions/<institution_id>", methods=["GET"])
def get_institution(institution_id):
    _, role = get_user_context()
    require_role(role, ALL_ROLES)
    record = db.institutions.get(institution_id)
    if record is None:
        raise err("ERR_NOT_FOUND", "Institution not found")
    return success(institution_view(record), status=200)


@bp.route("/institutions/<institution_id>/_clock/set_current_utc", methods=["POST"])
def set_clock(institution_id):
    _, role = get_user_context()
    require_role(role, ("Registrar",))
    record = db.institutions.get(institution_id)
    if record is None:
        raise err("ERR_NOT_FOUND", "Institution not found")
    body = validate.get_body()
    to_iso8601 = body.get("to_iso8601")
    parsed = dates.parse_iso(to_iso8601)
    if parsed is None:
        raise err("ERR_INVALID_REQUEST", "to_iso8601 must be a valid ISO 8601 instant")
    record["clock_utc"] = dates.to_iso(parsed)
    db.touch(record)
    return success(institution_view(record), status=200)
