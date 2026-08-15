"""Programs and retention policies (PRD 3.1)."""
from flask import Blueprint

from db import db
from errors import raise_error, ERR_STALE_PROGRAM_VERSION
from middleware import authorized, STAFF_ROLES
from response import success_object, success_list
from services import core
from validate import (
    get_body, req_str, req_enum, req_int, require_path, require_ref,
    pagination_params, opt_query_enum, opt_query_bool, opt_query_str, paginate,
)

bp = Blueprint("programs", __name__)

ADMIN = {"ProgramAdmin"}


# ---------------------------------------------------------------------------
# Programs
# ---------------------------------------------------------------------------

@bp.post("/programs")
def create_program():
    body = get_body()
    name = req_str(body, "name")
    program_type = req_enum(body, "program_type", core.PROGRAM_TYPES)
    contact_email = req_str(body, "contact_email")
    authorized(ADMIN)
    rec = core.new_record("programs", {
        "name": name,
        "program_type": program_type,
        "contact_email": contact_email,
        "active": True,
    })
    return success_object(rec, 201)


@bp.get("/programs")
def list_programs():
    limit, offset = pagination_params()
    program_type = opt_query_enum("program_type", core.PROGRAM_TYPES)
    active = opt_query_bool("active")
    authorized(STAFF_ROLES)
    recs = list(db["programs"].values())
    if program_type is not None:
        recs = [r for r in recs if r["program_type"] == program_type]
    if active is not None:
        recs = [r for r in recs if r["active"] == active]
    page, total = paginate(recs, limit, offset)
    return success_list(page, total, limit, offset)


@bp.get("/programs/<program_id>")
def get_program(program_id):
    authorized(STAFF_ROLES)
    rec = require_path("programs", program_id)
    return success_object(rec)


@bp.post("/programs/<program_id>/deactivate")
def deactivate_program(program_id):
    authorized(ADMIN)
    rec = require_path("programs", program_id)
    rec["active"] = False
    core.touch(rec)
    return success_object(rec)


# ---------------------------------------------------------------------------
# Retention policies
# ---------------------------------------------------------------------------

@bp.post("/retention-policies")
def create_policy():
    body = get_body()
    program_id = req_str(body, "program_id")
    item_category = req_enum(body, "item_category", core.CATEGORIES)
    value_tier = req_enum(body, "value_tier", core.VALUE_TIERS)
    retention_days = req_int(body, "retention_days", minimum=1)
    disposal_method = req_enum(body, "disposal_method", core.DISPOSAL_METHODS)
    expected_program_version = req_int(body, "expected_program_version")
    authorized(ADMIN)
    program = require_ref("programs", program_id, "program_id")
    # OCC on the parent Program (PRD 2.6)
    if expected_program_version != program["version"]:
        raise_error(
            ERR_STALE_PROGRAM_VERSION,
            "expected_program_version does not match the program's current version",
        )
    # Supersede any active policy with the same (program_id, item_category, value_tier)
    for p in db["retention_policies"].values():
        if (
            p["program_id"] == program_id
            and p["item_category"] == item_category
            and p["value_tier"] == value_tier
            and p["active"]
        ):
            p["active"] = False
            core.touch(p)
    core.touch(program)
    rec = core.new_record("retention_policies", {
        "program_id": program_id,
        "item_category": item_category,
        "value_tier": value_tier,
        "retention_days": retention_days,
        "disposal_method": disposal_method,
        "active": True,
    })
    return success_object(rec, 201)


@bp.get("/retention-policies")
def list_policies():
    limit, offset = pagination_params()
    program_id = opt_query_str("program_id")
    item_category = opt_query_enum("item_category", core.CATEGORIES)
    value_tier = opt_query_enum("value_tier", core.VALUE_TIERS)
    active = opt_query_bool("active")
    authorized(STAFF_ROLES)
    recs = list(db["retention_policies"].values())
    if program_id is not None:
        recs = [r for r in recs if r["program_id"] == program_id]
    if item_category is not None:
        recs = [r for r in recs if r["item_category"] == item_category]
    if value_tier is not None:
        recs = [r for r in recs if r["value_tier"] == value_tier]
    if active is not None:
        recs = [r for r in recs if r["active"] == active]
    page, total = paginate(recs, limit, offset)
    return success_list(page, total, limit, offset)


@bp.get("/retention-policies/<policy_id>")
def get_policy(policy_id):
    authorized(STAFF_ROLES)
    rec = require_path("retention_policies", policy_id)
    return success_object(rec)
