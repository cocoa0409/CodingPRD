"""TuitionTier endpoints (SCAFFOLD §1.5, PRD §3.1)."""
from flask import Blueprint

import errors
from db import db, new_common_fields
from middleware import get_auth, require_role
from response import object_response, array_response
from services.common import (
    get_json_body, require_fields, require_non_empty_string, require_int,
    require_number, require_enum, optional_enum, parse_pagination,
    sort_created_asc, paginate, serialize, serialize_list, str_arg, bool_arg,
)

bp = Blueprint("tiers", __name__)

LEVELS = {"TODDLER", "PRIMARY", "ELEMENTARY"}
READ_ROLES = {"Registrar", "Guide", "ComplianceOfficer", "Parent"}


@bp.route("/tiers", methods=["POST"])
def create_tier():
    _, role = get_auth()
    require_role(role, {"Registrar"})
    body = get_json_body()
    require_fields(body, ["code", "level", "base_annual_cents", "deposit_pct"])

    code = require_non_empty_string(body, "code")
    level = require_enum(body, "level", LEVELS)
    base_annual_cents = require_int(body, "base_annual_cents", minimum=0)
    deposit_pct = require_number(body, "deposit_pct", minimum=0, maximum=1)

    installments = 10
    if "installments" in body and body["installments"] is not None:
        installments = require_int(body, "installments", minimum=1, maximum=12)
    extended_day = 0
    if "extended_day_annual_cents" in body and body["extended_day_annual_cents"] is not None:
        extended_day = require_int(body, "extended_day_annual_cents", minimum=0)
    active = True
    if "active" in body and body["active"] is not None:
        if not isinstance(body["active"], bool):
            raise errors.invalid_request("active must be a boolean.")
        active = body["active"]

    # code unique across tiers, case-sensitive (PRD §3.1).
    for t in db.tiers.values():
        if t["code"] == code:
            raise errors.invalid_request("Tier code must be unique.")

    tier = new_common_fields()
    tier.update({
        "code": code,
        "level": level,
        "base_annual_cents": base_annual_cents,
        "deposit_pct": deposit_pct,
        "installments": installments,
        "extended_day_annual_cents": extended_day,
        "active": active,
    })
    db.tiers[tier["id"]] = tier
    return object_response(serialize(tier), 201)


@bp.route("/tiers/<tier_id>", methods=["GET"])
def get_tier(tier_id):
    _, role = get_auth()
    require_role(role, READ_ROLES)
    tier = db.tiers.get(tier_id)
    if tier is None:
        raise errors.not_found("Tier not found.")
    return object_response(serialize(tier), 200)


@bp.route("/tiers", methods=["GET"])
def list_tiers():
    _, role = get_auth()
    require_role(role, READ_ROLES)
    limit, offset = parse_pagination()
    level = optional_enum(str_arg("level"), LEVELS, "level")
    active = bool_arg("active")

    records = list(db.tiers.values())
    if level is not None:
        records = [t for t in records if t["level"] == level]
    if active is not None:
        records = [t for t in records if t["active"] == active]
    records = sort_created_asc(records)
    page, total = paginate(records, limit, offset)
    return array_response(serialize_list(page), limit, offset, total)
