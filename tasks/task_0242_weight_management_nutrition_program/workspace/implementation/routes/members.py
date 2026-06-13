"""Member endpoints (PRD 3.2)."""
from flask import Blueprint, request

from common import (as_number, as_str, get_body, init_common, parse_pagination,
                    require, sort_by_creation)
from db import db
from errors import ERR_DUPLICATE_EMAIL, ERR_INVALID_REQUEST, raise_error
from lookups import get_member, get_program
from middleware import require_roles
from response import paginated, success
from serializers import serialize, serialize_list

bp = Blueprint("members", __name__)


@bp.route("/wm/members", methods=["POST"])
@require_roles("ProgramAdmin", "Member")
def register_member():
    body = get_body()
    program_id = as_str(require(body, "program_id"), "program_id")
    get_program(program_id)  # ERR_PROGRAM_NOT_FOUND

    full_name = as_str(require(body, "full_name"), "full_name")
    email = as_str(require(body, "email"), "email")
    height_cm = as_number(require(body, "height_cm"), "height_cm")
    if height_cm <= 0:
        raise_error(ERR_INVALID_REQUEST, "height_cm must be > 0")

    # unique within program, case-insensitive
    for m in db.members.values():
        if m["program_id"] == program_id and m["email"].lower() == email.lower():
            raise_error(ERR_DUPLICATE_EMAIL, "Email already used within program")

    member = {
        "program_id": program_id,
        "full_name": full_name,
        "email": email,
        "height_cm": height_cm,
        "baseline_weight_kg": None,
        "latest_weight_kg": None,
        "latest_lean_mass_kg": None,
        "scale_progress_pct": 0,
        "lean_adjusted_progress_pct": 0,
        "account_balance_cents": 0,
        "status": "REGISTERED",
    }
    init_common(member)
    db.members[member["id"]] = member
    return success(serialize(member), 201)


@bp.route("/wm/members", methods=["GET"])
@require_roles("ProgramAdmin", "Clinician", "BillingAgent", "Coach")
def list_members():
    limit, offset = parse_pagination()
    items = list(db.members.values())
    program_id = request.args.get("program_id")
    status = request.args.get("status")
    if program_id is not None:
        items = [m for m in items if m["program_id"] == program_id]
    if status is not None:
        items = [m for m in items if m["status"] == status]
    items = sort_by_creation(items)
    total = len(items)
    page = items[offset:offset + limit]
    return paginated(serialize_list(page), limit, offset, total)


@bp.route("/wm/members/<member_id>", methods=["GET"])
@require_roles("ProgramAdmin", "Clinician", "BillingAgent", "Coach", "Member")
def get_one_member(member_id):
    return success(serialize(get_member(member_id)), 200)
