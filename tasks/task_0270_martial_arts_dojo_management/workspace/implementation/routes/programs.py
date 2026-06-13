"""Programs & belt ranks (PRD §3.1)."""
from flask import Blueprint, request

from db import db
from errors import err, ERR_NOT_FOUND, ERR_DUPLICATE, ERR_INVALID_REQUEST
from middleware import get_identity, require_roles, ROLE_FRONTDESK, ROLE_INSTRUCTOR, ROLE_CHIEF, ROLE_MEMBER
from response import success
from common import (
    get_json_body, require_fields, require_str, require_int, require_enum,
    parse_pagination, paginate, sort_by_created,
)
from services.serialize import view, view_list

bp = Blueprint("programs", __name__)

DISCIPLINES = {"KARATE", "BJJ", "TAEKWONDO", "JUDO", "MUAY_THAI"}
ALL_ROLES = [ROLE_FRONTDESK, ROLE_INSTRUCTOR, ROLE_CHIEF, ROLE_MEMBER]


@bp.post("/dojo/programs")
def create_program():
    _, role = get_identity()
    require_roles(role, [ROLE_FRONTDESK])
    body = get_json_body()
    require_fields(body, ["name", "discipline", "base_monthly_tuition_cents",
                          "test_fee_cents", "min_attendance_for_test", "min_days_in_rank"])
    if not isinstance(body["name"], str) or body["name"].strip() == "" or len(body["name"]) > 120:
        raise err(ERR_INVALID_REQUEST, "name must be 1..120 chars, non-empty after trim.")
    require_enum(body["discipline"], DISCIPLINES, "discipline")
    require_int(body["base_monthly_tuition_cents"], "base_monthly_tuition_cents", minimum=0)
    require_int(body["test_fee_cents"], "test_fee_cents", minimum=0)
    require_int(body["min_attendance_for_test"], "min_attendance_for_test", minimum=0)
    require_int(body["min_days_in_rank"], "min_days_in_rank", minimum=0)

    now = db.now_iso()
    pid = db.new_id()
    program = {
        "id": pid,
        "name": body["name"],
        "discipline": body["discipline"],
        "base_monthly_tuition_cents": body["base_monthly_tuition_cents"],
        "test_fee_cents": body["test_fee_cents"],
        "min_attendance_for_test": body["min_attendance_for_test"],
        "min_days_in_rank": body["min_days_in_rank"],
        "status": "ACTIVE",
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.programs[pid] = program
    return success(view(program), 201)


@bp.get("/dojo/programs/<pid>")
def get_program(pid):
    _, role = get_identity()
    require_roles(role, ALL_ROLES)
    program = db.programs.get(pid)
    if program is None:
        raise err(ERR_NOT_FOUND, "Program not found.")
    return success(view(program), 200)


@bp.get("/dojo/programs")
def list_programs():
    _, role = get_identity()
    require_roles(role, ALL_ROLES)
    limit, offset = parse_pagination()
    status = request.args.get("status")
    items = [p for p in db.programs.values() if status is None or p["status"] == status]
    items = sort_by_created(items)
    page, meta = paginate(items, limit, offset)
    return success(view_list(page), 200, pagination=meta)


@bp.post("/dojo/programs/<pid>/archive")
def archive_program(pid):
    _, role = get_identity()
    require_roles(role, [ROLE_FRONTDESK])
    program = db.programs.get(pid)
    if program is None:
        raise err(ERR_NOT_FOUND, "Program not found.")
    program["status"] = "ARCHIVED"
    program["updated_at"] = db.now_iso()
    program["version"] = program["version"] + 1
    return success(view(program), 200)


@bp.post("/dojo/programs/<pid>/belt-ranks")
def create_belt_rank(pid):
    _, role = get_identity()
    require_roles(role, [ROLE_FRONTDESK])
    program = db.programs.get(pid)
    if program is None:
        raise err(ERR_NOT_FOUND, "Program not found.")
    body = get_json_body()
    require_fields(body, ["code", "rank_order"])
    require_str(body["code"], "code", min_len=1, max_len=40)
    require_int(body["rank_order"], "rank_order", minimum=0)
    next_rank_code = body.get("next_rank_code", None)
    if next_rank_code is not None and not isinstance(next_rank_code, str):
        raise err(ERR_INVALID_REQUEST, "next_rank_code must be a string or null.")
    is_entry_rank = body.get("is_entry_rank", False)
    if not isinstance(is_entry_rank, bool):
        raise err(ERR_INVALID_REQUEST, "is_entry_rank must be a boolean.")
    requires_chief_signoff = body.get("requires_chief_signoff", False)
    if not isinstance(requires_chief_signoff, bool):
        raise err(ERR_INVALID_REQUEST, "requires_chief_signoff must be a boolean.")

    # Uniqueness within program: code and rank_order (priority 6, ERR_DUPLICATE).
    for r in db.belt_ranks.values():
        if r["program_id"] == pid and r["code"] == body["code"]:
            raise err(ERR_DUPLICATE, "Belt rank code already exists in this program.")
        if r["program_id"] == pid and r["rank_order"] == body["rank_order"]:
            raise err(ERR_DUPLICATE, "Belt rank order already exists in this program.")

    now = db.now_iso()
    rid = db.new_id()
    rank = {
        "id": rid,
        "program_id": pid,
        "code": body["code"],
        "rank_order": body["rank_order"],
        "next_rank_code": next_rank_code,
        "is_entry_rank": is_entry_rank,
        "requires_chief_signoff": requires_chief_signoff,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.belt_ranks[rid] = rank
    return success(view(rank), 201)


@bp.get("/dojo/programs/<pid>/belt-ranks")
def list_belt_ranks(pid):
    _, role = get_identity()
    require_roles(role, ALL_ROLES)
    program = db.programs.get(pid)
    if program is None:
        raise err(ERR_NOT_FOUND, "Program not found.")
    limit, offset = parse_pagination()
    items = [r for r in db.belt_ranks.values() if r["program_id"] == pid]
    items = sort_by_created(items)
    page, meta = paginate(items, limit, offset)
    return success(view_list(page), 200, pagination=meta)
