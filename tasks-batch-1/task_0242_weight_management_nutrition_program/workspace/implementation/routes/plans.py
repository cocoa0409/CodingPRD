"""PlanCatalogItem endpoints (PRD 3.1, 2.9)."""
from flask import Blueprint

from common import (as_bool, as_enum, as_int, as_str, get_body, init_common,
                    parse_pagination, require, sort_by_creation, touch)
from db import db
from errors import ERR_INVALID_REQUEST, raise_error
from lookups import get_plan, get_program
from middleware import require_roles
from response import paginated, success
from serializers import serialize, serialize_list

bp = Blueprint("plans", __name__)

ALL_ROLES = ("ProgramAdmin", "Clinician", "BillingAgent", "Coach", "Member")
TIERS = {"COACHING", "RX", "MEAL"}


@bp.route("/wm/plans", methods=["POST"])
@require_roles("ProgramAdmin")
def create_plan():
    body = get_body()
    program_id = as_str(require(body, "program_id"), "program_id")
    get_program(program_id)  # existence -> ERR_PROGRAM_NOT_FOUND

    tier = as_enum(require(body, "tier"), "tier", TIERS)
    name = as_str(require(body, "name"), "name")
    monthly = as_int(require(body, "monthly_fee_cents"), "monthly_fee_cents")
    if monthly < 0:
        raise_error(ERR_INVALID_REQUEST, "monthly_fee_cents must be >= 0")

    enrollment_fee = 0
    if body.get("enrollment_fee_cents") is not None:
        enrollment_fee = as_int(body["enrollment_fee_cents"], "enrollment_fee_cents")
        if enrollment_fee < 0:
            raise_error(ERR_INVALID_REQUEST, "enrollment_fee_cents must be >= 0")

    hsa_default = False
    if body.get("hsa_fsa_default_eligible") is not None:
        hsa_default = as_bool(body["hsa_fsa_default_eligible"], "hsa_fsa_default_eligible")

    plan = {
        "program_id": program_id,
        "tier": tier,
        "name": name,
        "monthly_fee_cents": monthly,
        "enrollment_fee_cents": enrollment_fee,
        "requires_rx": tier == "RX",
        "hsa_fsa_default_eligible": hsa_default,
        "active": True,
    }
    init_common(plan)
    db.plans[plan["id"]] = plan
    return success(serialize(plan), 201)


@bp.route("/wm/plans", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_plans():
    from flask import request
    limit, offset = parse_pagination()
    items = list(db.plans.values())
    program_id = request.args.get("program_id")
    tier = request.args.get("tier")
    if program_id is not None:
        items = [p for p in items if p["program_id"] == program_id]
    if tier is not None:
        items = [p for p in items if p["tier"] == tier]
    items = sort_by_creation(items)
    total = len(items)
    page = items[offset:offset + limit]
    return paginated(serialize_list(page), limit, offset, total)


@bp.route("/wm/plans/<plan_id>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_one_plan(plan_id):
    return success(serialize(get_plan(plan_id)), 200)


@bp.route("/wm/plans/<plan_id>/retire", methods=["POST"])
@require_roles("ProgramAdmin")
def retire_plan(plan_id):
    plan = get_plan(plan_id)
    plan["active"] = False
    touch(plan)
    return success(serialize(plan), 200)
