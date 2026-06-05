"""Work authorization endpoints: record (base / STEM extension), list, get."""

from flask import Blueprint, request

from errors import err
from db import db, stamp_create, touch
from middleware import require_roles, require_read_role, parse_pagination
from response import object_response
from listing import sorted_collection, paginate_and_respond
from validation import (get_json_body, require_str, require_enum, require_datetime,
                        optional_bool, optional_str, optional_int)
from clock import now, format_iso8601, parse_iso8601
import serializers
from services import calculations

bp = Blueprint("work_authorizations", __name__)

AUTH_TYPE = {"EAD", "F1_OPT", "F1_STEM_OPT", "TPS", "OTHER"}


@bp.route("/work-authorizations", methods=["POST"])
def create_work_auth():
    require_roles({"HRReviewer"})
    body = get_json_body()

    onboarding_id = require_str(body, "onboarding_id")
    # priority 4: existence, left-to-right (onboarding then supersedes).
    if onboarding_id not in db.onboardings:
        raise err("ERR_NOT_FOUND", "Onboarding not found")

    auth_type = require_enum(body, "auth_type", AUTH_TYPE)
    valid_from_dt = require_datetime(body, "valid_from")
    valid_until_dt = require_datetime(body, "valid_until")
    stem_extension_applied = optional_bool(body, "stem_extension_applied", False)
    supersedes_id = optional_str(body, "supersedes_id", None)
    requested_gap_days = optional_int(body, "requested_gap_days", None)

    base = None
    if supersedes_id is not None:
        base = db.work_authorizations.get(supersedes_id)
        if base is None:
            raise err("ERR_NOT_FOUND", "Superseded WorkAuthorization not found")

    valid_until_iso = format_iso8601(valid_until_dt)
    cap_gap_days = 0
    effective_valid_until_iso = valid_until_iso

    if stem_extension_applied:
        # priority 11: STEM filing window (calc stem_extension_window).
        if base is None:
            raise err("ERR_STEM_WINDOW_MISSED",
                      "STEM extension requires a supersedes_id base authorization")
        filing_clock = now()
        base_valid_until = parse_iso8601(base["valid_until"])
        timely = filing_clock <= base_valid_until  # inclusive <=
        if not (base.get("auth_type") == "F1_OPT"
                and base.get("status") == "ACTIVE"
                and timely):
            raise err("ERR_STEM_WINDOW_MISSED",
                      "STEM extension filed late or base is not an active F1_OPT")
        cap_gap_days = calculations.stem_cap_gap_days(requested_gap_days)
        effective_valid_until_iso = format_iso8601(
            calculations.effective_valid_until(base["valid_until"], cap_gap_days))

    record = {
        "onboarding_id": onboarding_id,
        "auth_type": auth_type,
        "valid_from": format_iso8601(valid_from_dt),
        "valid_until": valid_until_iso,
        "stem_extension_applied": stem_extension_applied,
        "cap_gap_days": cap_gap_days,
        "effective_valid_until": effective_valid_until_iso,
        "supersedes_id": supersedes_id,
        "status": "ACTIVE",
    }
    stamp_create(record)
    db.work_authorizations[record["id"]] = record

    # side effect: filing a timely STEM extension moves the base ACTIVE->EXTENDED.
    if stem_extension_applied and base is not None:
        base["status"] = "EXTENDED"
        touch(base)

    return object_response(serializers.work_authorization(record), status=201)


@bp.route("/work-authorizations", methods=["GET"])
def list_work_auths():
    require_read_role()
    limit, offset = parse_pagination()
    records = sorted_collection(db.work_authorizations)
    onboarding_id = request.args.get("onboarding_id")
    supersedes_id = request.args.get("supersedes_id")
    status = request.args.get("status")
    if onboarding_id is not None:
        records = [r for r in records if r.get("onboarding_id") == onboarding_id]
    if supersedes_id is not None:
        records = [r for r in records if r.get("supersedes_id") == supersedes_id]
    if status is not None:
        records = [r for r in records if r.get("status") == status]
    return paginate_and_respond(records, limit, offset,
                                serializers.work_authorization)


@bp.route("/work-authorizations/<auth_id>", methods=["GET"])
def get_work_auth(auth_id):
    require_read_role()
    record = db.work_authorizations.get(auth_id)
    if record is None:
        raise err("ERR_NOT_FOUND", "WorkAuthorization not found")
    return object_response(serializers.work_authorization(record))
