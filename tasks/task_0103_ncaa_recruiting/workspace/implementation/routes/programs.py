"""/programs endpoints."""

from flask import Blueprint, request

from core.auth import require_roles
from core.envelope import success_object, success_array
from core.errors import raise_error
from core.models import make_entity, serialize, serialize_list
from core.store import STORE, lock
from core.validation import (
    require_body,
    require_field,
    require_enum,
    parse_pagination,
)


bp = Blueprint("programs", __name__)


VALID_SPORTS = {"FOOTBALL", "MENS_BASKETBALL", "WOMENS_BASKETBALL", "BASEBALL", "SOFTBALL"}
VALID_DIVISIONS = {"DI", "DII", "DIII"}
VALID_COMPLIANCE = {"GREEN", "YELLOW", "RED"}


@bp.route("/programs", methods=["POST"])
@require_roles("ComplianceOfficer")
def create_program():
    body = require_body(request)
    institution_name = require_field(body, "institution_name", kind="string")
    sport = require_enum(body, "sport", VALID_SPORTS)
    division = require_enum(body, "division", VALID_DIVISIONS)
    cap = require_field(body, "scholarship_cap_equivalencies", kind="number")
    if isinstance(cap, bool) or cap <= 0:
        raise_error("ERR_VALIDATION_FAILED", "scholarship_cap_equivalencies must be > 0")
    roster_cap = require_field(body, "roster_cap_count", kind="positive_int")

    with lock():
        prog = make_entity("Program", {
            "institution_name": institution_name,
            "sport": sport,
            "division": division,
            "scholarship_cap_equivalencies": float(cap),
            "roster_cap_count": int(roster_cap),
            "total_equivalencies_used": 0.0,
            "active_roster_count": 0,
            "penalty_points_total": 0,
            "compliance_status": "GREEN",
        })
        STORE.programs[prog["id"]] = prog
        return success_object(serialize(prog), status=201)


@bp.route("/programs/<program_id>", methods=["GET"])
@require_roles("ComplianceOfficer", "Coach", "Auditor")
def get_program(program_id):
    with lock():
        p = STORE.programs.get(program_id)
        if not p:
            raise_error("ERR_NOT_FOUND", "Program not found")
        return success_object(serialize(p))


@bp.route("/programs", methods=["GET"])
@require_roles("ComplianceOfficer", "Coach", "Auditor")
def list_programs():
    limit, offset = parse_pagination(request)
    sport = request.args.get("sport")
    division = request.args.get("division")
    compliance_status = request.args.get("compliance_status")

    with lock():
        items = list(STORE.programs.values())
        if sport:
            items = [p for p in items if p.get("sport") == sport]
        if division:
            items = [p for p in items if p.get("division") == division]
        if compliance_status:
            items = [p for p in items if p.get("compliance_status") == compliance_status]
        items.sort(key=lambda p: (p["created_at"], p["_seq"]))
        total = len(items)
        page = items[offset:offset + limit]
        return success_array(serialize_list(page), limit, offset, total)
