"""RolloutProgram endpoints."""

from __future__ import annotations

from flask import Blueprint

import db
from errors import (
    raise_err,
    ERR_INVALID_REQUEST,
    ERR_PROGRAM_NOT_FOUND,
    ERR_PROGRAM_NOT_ACTIVE,
    ERR_PROGRAM_NOT_CLOSEOUT_PENDING,
    ERR_CLOSEOUT_BLOCKED,
    ERR_UNDISPOSED_STOCK_REMAINS,
)
from middleware import require_roles
from response import success_object, success_list
from services.serializers import serialize, serialize_list
from util import (
    apply_filters,
    get_json_body,
    optional_field,
    paginate,
    parse_pagination,
    require_int,
    require_string,
    sort_by_created_at,
)

bp = Blueprint("programs", __name__)

VALUATION_METHODS = {"PROGRAM_AVERAGE", "LIQUIDATION"}


def _get_program_or_404(program_id: str) -> dict:
    program = db.programs.get(program_id)
    if program is None:
        raise_err(ERR_PROGRAM_NOT_FOUND, "RolloutProgram id does not exist")
    return program


@bp.route("/rollout-programs", methods=["POST"])
@require_roles("ProgramManager")
def create_program(_user_id: str, _role: str):
    body = get_json_body()
    program_name = require_string(body, "program_name")
    retailer_code = require_string(body, "retailer_code")
    budget_total_cents = require_int(body, "budget_total_cents")
    if budget_total_cents <= 0:
        raise_err(ERR_INVALID_REQUEST, "budget_total_cents must be > 0")
    contingency_budget_cents = require_int(body, "contingency_budget_cents")
    if contingency_budget_cents < 0:
        raise_err(ERR_INVALID_REQUEST, "contingency_budget_cents must be >= 0")

    recalled = optional_field(body, "recalled_part_numbers", [])
    if not isinstance(recalled, list):
        raise_err(ERR_INVALID_REQUEST, "recalled_part_numbers must be an array")

    method = optional_field(body, "attic_valuation_method", "PROGRAM_AVERAGE")
    if not isinstance(method, str) or method not in VALUATION_METHODS:
        raise_err(
            ERR_INVALID_REQUEST,
            "attic_valuation_method must be PROGRAM_AVERAGE or LIQUIDATION",
        )

    program = {
        "program_name": program_name,
        "retailer_code": retailer_code,
        "budget_total_cents": budget_total_cents,
        "contingency_budget_cents": contingency_budget_cents,
        "recalled_part_numbers": recalled,
        "attic_valuation_method": method,
        "remaining_budget_cents": budget_total_cents,
        "contingency_spent_cents": 0,
        "fulfilled_kit_count": 0,
        "closeout_recovery_cents": 0,
        "final_reconciliation_cents": None,
        "status": "DRAFT",
    }
    db.stamp_new(program)
    db.programs[program["id"]] = program
    return success_object(serialize(program), 201)


@bp.route("/rollout-programs", methods=["GET"])
@require_roles("Any")
def list_programs(_user_id: str, _role: str):
    limit, offset = parse_pagination()
    items = sort_by_created_at(list(db.programs.values()))
    items = apply_filters(items, ["status"])
    page, total = paginate(items, limit, offset)
    return success_list(serialize_list(page), limit, offset, total)


@bp.route("/rollout-programs/<program_id>", methods=["GET"])
@require_roles("Any")
def get_program(program_id: str, _user_id: str, _role: str):
    program = _get_program_or_404(program_id)
    return success_object(serialize(program))


@bp.route("/rollout-programs/<program_id>/activate", methods=["POST"])
@require_roles("ProgramManager")
def activate_program(program_id: str, _user_id: str, _role: str):
    program = _get_program_or_404(program_id)
    if program["status"] != "DRAFT":
        raise_err(ERR_PROGRAM_NOT_ACTIVE, "Operation requires program DRAFT to activate")
    if program["budget_total_cents"] <= 0:
        raise_err(ERR_INVALID_REQUEST, "budget_total_cents must be > 0")
    program["status"] = "ACTIVE"
    db.touch(program)
    return success_object(serialize(program))


@bp.route("/rollout-programs/<program_id>/initiate-closeout", methods=["POST"])
@require_roles("ProgramManager")
def initiate_closeout(program_id: str, _user_id: str, _role: str):
    program = _get_program_or_404(program_id)
    if program["status"] != "ACTIVE":
        raise_err(ERR_PROGRAM_NOT_ACTIVE, "Operation requires program ACTIVE")

    # Kits must not be in DRAFT/FROZEN/RELEASED
    for kit in db.kits.values():
        if kit["program_id"] == program_id and kit["status"] in ("DRAFT", "FROZEN", "RELEASED"):
            raise_err(
                ERR_CLOSEOUT_BLOCKED,
                "initiate-closeout blocked: kit in DRAFT/FROZEN/RELEASED",
            )

    # No OPEN claims belonging to this program (via delivery -> kit -> program)
    for claim in db.claims.values():
        if claim["status"] != "OPEN":
            continue
        delivery = db.deliveries.get(claim["delivery_id"])
        if delivery is None:
            continue
        kit = db.kits.get(delivery["kit_id"])
        if kit is None:
            continue
        if kit["program_id"] == program_id:
            raise_err(ERR_CLOSEOUT_BLOCKED, "initiate-closeout blocked: OPEN claim")

    # All waves COMPLETE or CANCELLED
    for wave in db.waves.values():
        if wave["program_id"] == program_id and wave["status"] not in ("COMPLETE", "CANCELLED"):
            raise_err(ERR_CLOSEOUT_BLOCKED, "initiate-closeout blocked: wave not terminal")

    program["status"] = "CLOSEOUT_PENDING"
    db.touch(program)
    return success_object(serialize(program))


@bp.route("/rollout-programs/<program_id>/finalize-closeout", methods=["POST"])
@require_roles("ProgramManager")
def finalize_closeout(program_id: str, _user_id: str, _role: str):
    program = _get_program_or_404(program_id)
    if program["status"] != "CLOSEOUT_PENDING":
        raise_err(
            ERR_PROGRAM_NOT_CLOSEOUT_PENDING,
            "Operation requires program CLOSEOUT_PENDING",
        )

    # All attic ledgers of this program's kits must be DEPLETED or DISPOSED
    kit_ids = {k["id"] for k in db.kits.values() if k["program_id"] == program_id}
    for ledger in db.ledgers.values():
        if ledger["kit_id"] in kit_ids and ledger["status"] not in ("DEPLETED", "DISPOSED"):
            raise_err(
                ERR_UNDISPOSED_STOCK_REMAINS,
                "finalize-closeout blocked: attic ledger still ACTIVE",
            )

    program["final_reconciliation_cents"] = (
        program["remaining_budget_cents"]
        - program["contingency_spent_cents"]
        + program["closeout_recovery_cents"]
    )
    program["status"] = "CLOSED"
    db.touch(program)
    return success_object(serialize(program))
