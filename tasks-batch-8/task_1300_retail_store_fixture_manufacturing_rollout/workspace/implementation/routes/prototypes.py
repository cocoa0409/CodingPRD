"""FixturePrototype endpoints."""

from __future__ import annotations

from flask import Blueprint

import db
from errors import (
    raise_err,
    ERR_INVALID_REQUEST,
    ERR_PROGRAM_NOT_FOUND,
    ERR_PROTOTYPE_NOT_FOUND,
    ERR_PROTOTYPE_INVALID_STATE,
    ERR_PROTOTYPE_SELF_APPROVAL,
    ERR_VE_NOT_REQUIRED,
)
from middleware import require_roles
from response import success_object, success_list
from services.calculations import prototype_costs
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

bp = Blueprint("prototypes", __name__)


def _get_prototype_or_404(prototype_id: str) -> dict:
    proto = db.prototypes.get(prototype_id)
    if proto is None:
        raise_err(ERR_PROTOTYPE_NOT_FOUND, "FixturePrototype id does not exist")
    return proto


def _validate_bom_lines(bom_lines) -> list:
    if not isinstance(bom_lines, list):
        raise_err(ERR_INVALID_REQUEST, "bom_lines must be an array")
    for line in bom_lines:
        if not isinstance(line, dict):
            raise_err(ERR_INVALID_REQUEST, "bom_lines entries must be objects")
        part_number = line.get("part_number")
        if not isinstance(part_number, str) or part_number == "":
            raise_err(ERR_INVALID_REQUEST, "bom_lines.part_number must be a non-empty string")
        qty = line.get("quantity")
        if isinstance(qty, bool) or not isinstance(qty, int) or qty < 1:
            raise_err(ERR_INVALID_REQUEST, "bom_lines.quantity must be an integer >= 1")
        list_cost = line.get("list_unit_cost_cents")
        if isinstance(list_cost, bool) or not isinstance(list_cost, int):
            raise_err(ERR_INVALID_REQUEST, "bom_lines.list_unit_cost_cents must be an integer")
        negotiated = line.get("negotiated_unit_cost_cents")
        if negotiated is not None and (isinstance(negotiated, bool) or not isinstance(negotiated, int)):
            raise_err(ERR_INVALID_REQUEST, "bom_lines.negotiated_unit_cost_cents must be an integer")
    return bom_lines


@bp.route("/fixture-prototypes", methods=["POST"])
@require_roles("FixtureEngineer")
def create_prototype(_user_id: str, _role: str):
    body = get_json_body()
    program_id = require_string(body, "program_id")
    fixture_code = require_string(body, "fixture_code")
    bom_lines = _validate_bom_lines(body.get("bom_lines"))
    target_cost_cents = require_int(body, "target_cost_cents")

    # Body-FK existence (priority 4)
    program = db.programs.get(program_id)
    if program is None:
        raise_err(ERR_PROGRAM_NOT_FOUND, "RolloutProgram id does not exist")

    provisional, engineered = prototype_costs(bom_lines)
    proto = {
        "program_id": program_id,
        "fixture_code": fixture_code,
        "bom_lines": bom_lines,
        "target_cost_cents": target_cost_cents,
        "provisional_cost_cents": provisional,
        "engineered_cost_cents": engineered,
        "final_cost_cents": None,
        "ve_round_count": 0,
        "submitted_by_user_id": None,
        "approved_by_user_id": None,
        "status": "DRAFT",
    }
    db.stamp_new(proto)
    db.prototypes[proto["id"]] = proto
    return success_object(serialize(proto), 201)


@bp.route("/fixture-prototypes", methods=["GET"])
@require_roles("Any")
def list_prototypes(_user_id: str, _role: str):
    limit, offset = parse_pagination()
    items = sort_by_created_at(list(db.prototypes.values()))
    items = apply_filters(items, ["program_id", "status"])
    page, total = paginate(items, limit, offset)
    return success_list(serialize_list(page), limit, offset, total)


@bp.route("/fixture-prototypes/<prototype_id>", methods=["GET"])
@require_roles("Any")
def get_prototype(prototype_id: str, _user_id: str, _role: str):
    proto = _get_prototype_or_404(prototype_id)
    return success_object(serialize(proto))


@bp.route("/fixture-prototypes/<prototype_id>", methods=["PATCH"])
@require_roles("FixtureEngineer")
def patch_prototype(prototype_id: str, _user_id: str, _role: str):
    proto = _get_prototype_or_404(prototype_id)
    if proto["status"] not in ("DRAFT", "VALUE_ENGINEERING"):
        raise_err(
            ERR_PROTOTYPE_INVALID_STATE,
            "PATCH allowed only while DRAFT or VALUE_ENGINEERING",
        )
    body = get_json_body()
    if "bom_lines" in body and body["bom_lines"] is not None:
        proto["bom_lines"] = _validate_bom_lines(body["bom_lines"])
    if "target_cost_cents" in body and body["target_cost_cents"] is not None:
        tcc = body["target_cost_cents"]
        if isinstance(tcc, bool) or not isinstance(tcc, int):
            raise_err(ERR_INVALID_REQUEST, "target_cost_cents must be an integer")
        proto["target_cost_cents"] = tcc
    provisional, engineered = prototype_costs(proto["bom_lines"])
    proto["provisional_cost_cents"] = provisional
    proto["engineered_cost_cents"] = engineered
    db.touch(proto)
    return success_object(serialize(proto))


@bp.route("/fixture-prototypes/<prototype_id>/submit-review", methods=["POST"])
@require_roles("FixtureEngineer")
def submit_review(prototype_id: str, _user_id: str, _role: str):
    proto = _get_prototype_or_404(prototype_id)
    if proto["status"] not in ("DRAFT", "VALUE_ENGINEERING"):
        raise_err(
            ERR_PROTOTYPE_INVALID_STATE,
            "submit-review requires DRAFT or VALUE_ENGINEERING",
        )
    if proto["status"] == "VALUE_ENGINEERING":
        # Resubmission after VE: recompute engineered variant from current BOM.
        _, engineered = prototype_costs(proto["bom_lines"])
        proto["engineered_cost_cents"] = engineered
    proto["submitted_by_user_id"] = _user_id
    proto["status"] = "ENGINEERING_REVIEW"
    db.touch(proto)
    return success_object(serialize(proto))


@bp.route("/fixture-prototypes/<prototype_id>/request-value-engineering", methods=["POST"])
@require_roles("ProgramManager")
def request_value_engineering(prototype_id: str, _user_id: str, _role: str):
    proto = _get_prototype_or_404(prototype_id)
    if proto["status"] != "ENGINEERING_REVIEW":
        raise_err(ERR_PROTOTYPE_INVALID_STATE, "request-value-engineering requires ENGINEERING_REVIEW")
    if not (proto["provisional_cost_cents"] > proto["target_cost_cents"]):
        raise_err(ERR_VE_NOT_REQUIRED, "request-value-engineering requires provisional_cost_cents > target_cost_cents")
    proto["ve_round_count"] += 1
    proto["status"] = "VALUE_ENGINEERING"
    db.touch(proto)
    return success_object(serialize(proto))


@bp.route("/fixture-prototypes/<prototype_id>/approve", methods=["POST"])
@require_roles("ProgramManager")
def approve_prototype(prototype_id: str, _user_id: str, _role: str):
    proto = _get_prototype_or_404(prototype_id)
    if proto["status"] not in ("ENGINEERING_REVIEW", "VALUE_ENGINEERING"):
        raise_err(ERR_PROTOTYPE_INVALID_STATE, "approve requires ENGINEERING_REVIEW or VALUE_ENGINEERING")
    if proto["submitted_by_user_id"] is not None and _user_id == proto["submitted_by_user_id"]:
        raise_err(ERR_PROTOTYPE_SELF_APPROVAL, "Approver must differ from the most recent submitter")
    proto["final_cost_cents"] = (
        proto["engineered_cost_cents"] if proto["ve_round_count"] > 0 else proto["provisional_cost_cents"]
    )
    proto["approved_by_user_id"] = _user_id
    proto["status"] = "APPROVED"
    db.touch(proto)
    return success_object(serialize(proto))
