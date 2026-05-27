"""Jurisdiction endpoints."""

from flask import Blueprint

from db import db
from errors import raise_api
from middleware import require_roles
from response import success, list_success
from util import (
    new_id, parse_pagination, page, sort_by_created_at,
    get_jurisdiction, get_json_body, require_fields,
)
from services.engine import FEDERAL_WAITING_DAY_FLOOR


bp = Blueprint("jurisdictions", __name__)


def _serialize(j):
    # Jurisdiction does NOT carry updated_at/version per scaffold (common_fields: false).
    return {
        "id": j["id"],
        "created_at": j["created_at"],
        "state_code": j["state_code"],
        "ban_the_box_enabled": j["ban_the_box_enabled"],
        "salary_history_ban_enabled": j["salary_history_ban_enabled"],
        "pre_adverse_waiting_days": j["pre_adverse_waiting_days"],
    }


@bp.route("/api/v1/jurisdictions", methods=["POST"])
@require_roles("PlatformAdmin")
def create_jurisdiction(_user_id, _role):
    body = get_json_body()
    require_fields(body, "state_code")
    state_code = body.get("state_code")
    if not isinstance(state_code, str) or len(state_code) != 2 or not state_code.isalpha() or state_code.upper() != state_code:
        raise_api("ERR_INVALID_REQUEST", "state_code must be a 2-letter uppercase US state code")
    ban_the_box = body.get("ban_the_box_enabled", False)
    salary_ban = body.get("salary_history_ban_enabled", False)
    waiting_days = body.get("pre_adverse_waiting_days", 5)
    if not isinstance(ban_the_box, bool):
        raise_api("ERR_INVALID_REQUEST", "ban_the_box_enabled must be boolean")
    if not isinstance(salary_ban, bool):
        raise_api("ERR_INVALID_REQUEST", "salary_history_ban_enabled must be boolean")
    if not isinstance(waiting_days, int) or isinstance(waiting_days, bool):
        raise_api("ERR_INVALID_REQUEST", "pre_adverse_waiting_days must be integer")
    # Validation priority: business_constraint federal floor (95) before generic schema (100)?
    # Federal floor is its own error_id (422). Apply after schema typing.
    if waiting_days < FEDERAL_WAITING_DAY_FLOOR:
        raise_api("ERR_BELOW_FEDERAL_FLOOR", f"pre_adverse_waiting_days must be >= {FEDERAL_WAITING_DAY_FLOOR}")
    # Uniqueness
    for j in db.jurisdictions.values():
        if j["state_code"] == state_code:
            raise_api("ERR_INVALID_REQUEST", f"state_code {state_code} already exists")
    j = {
        "id": new_id(),
        "created_at": db.current_utc_iso(),
        "state_code": state_code,
        "ban_the_box_enabled": ban_the_box,
        "salary_history_ban_enabled": salary_ban,
        "pre_adverse_waiting_days": waiting_days,
    }
    db.jurisdictions[j["id"]] = j
    return success(_serialize(j), 201)


@bp.route("/api/v1/jurisdictions/<jid>", methods=["GET"])
@require_roles("PlatformAdmin", "Recruiter", "ComplianceOfficer", "VerificationProvider", "Applicant")
def get_jurisdiction_route(jid, _user_id, _role):
    j = get_jurisdiction(jid)
    return success(_serialize(j))


@bp.route("/api/v1/jurisdictions", methods=["GET"])
@require_roles("PlatformAdmin", "Recruiter", "ComplianceOfficer")
def list_jurisdictions(_user_id, _role):
    from flask import request
    state_code = request.args.get("state_code")
    limit, offset = parse_pagination()
    items = list(db.jurisdictions.values())
    if state_code is not None:
        items = [j for j in items if j["state_code"] == state_code]
    items = sort_by_created_at(items)
    page_items, total = page(items, limit, offset)
    return list_success([_serialize(j) for j in page_items], limit, offset, total)
