"""SupplierProgram creation, amendment (OCC), and lifecycle (PRD §3.3)."""

from flask import Blueprint, request

from db import store, new_entity, touch, public
from errors import (err_not_found, err_state, err_invalid_request, ApiError,
                    ERR_INVALID_TIER_SCHEDULE, ERR_INVALID_EXCLUSIVITY,
                    ERR_DUPLICATE_PROGRAM_CODE, ERR_SUPPLIER_NOT_ONBOARDED,
                    ERR_PROGRAM_HAS_ENROLLMENTS, ERR_STALE_PROGRAM_VERSION)
from middleware import require_roles, body_json, req_str, req_int, req_bool, opt_bool, opt_int
from response import success_object, success_list, parse_pagination, paginate
from routes.suppliers import get_supplier_or_404

bp = Blueprint("programs", __name__)

READ_ROLES = ("CoopAdmin", "SupplierRep", "FinanceOfficer", "ProgramAuditor", "MemberRep")
HOLDBACK_POLICIES = ("FLAT", "RISK_ADJUSTED")
AMENDABLE_STATES = ("DRAFT", "OPEN", "CLOSED_TO_NEW", "REOPENED")


def get_program_or_404(program_id):
    program = store.programs.get(program_id)
    if program is None:
        raise err_not_found("SupplierProgram not found")
    return program


def _arg(name):
    v = request.args.get(name)
    return v if v not in (None, "") else None


def parse_tier_schedule(body, required=True):
    """Schema-level shape check (ERR_INVALID_REQUEST) followed by the business
    tier-schedule check (ERR_INVALID_TIER_SCHEDULE, pipeline item 9)."""
    if "tier_schedule" not in body or body["tier_schedule"] is None:
        if required:
            raise err_invalid_request("Field 'tier_schedule' is required")
        return None
    ts = body["tier_schedule"]
    if not isinstance(ts, list):
        raise err_invalid_request("tier_schedule must be an array")
    for tier in ts:
        if not isinstance(tier, dict):
            raise err_invalid_request("each tier must be an object")
        mq = tier.get("min_qty")
        rb = tier.get("rate_bps")
        if isinstance(mq, bool) or not isinstance(mq, int):
            raise err_invalid_request("tier.min_qty must be an integer")
        if isinstance(rb, bool) or not isinstance(rb, int):
            raise err_invalid_request("tier.rate_bps must be an integer")
    return [{"min_qty": t["min_qty"], "rate_bps": t["rate_bps"]} for t in ts]


def validate_tier_schedule(ts):
    """Pipeline item 9: non-empty, ascending by min_qty, rate_bps in [0,10000]."""
    if ts is None:
        return
    if len(ts) == 0:
        raise ApiError(ERR_INVALID_TIER_SCHEDULE, 422, "tier_schedule must be non-empty")
    prev = None
    for tier in ts:
        if tier["min_qty"] < 0:
            raise ApiError(ERR_INVALID_TIER_SCHEDULE, 422, "min_qty must be >= 0")
        if tier["rate_bps"] < 0 or tier["rate_bps"] > 10000:
            raise ApiError(ERR_INVALID_TIER_SCHEDULE, 422, "rate_bps must be in [0, 10000]")
        if prev is not None and tier["min_qty"] <= prev:
            raise ApiError(ERR_INVALID_TIER_SCHEDULE, 422,
                           "tier_schedule must be ascending by min_qty")
        prev = tier["min_qty"]


def validate_exclusivity(exclusivity_required, threshold):
    """Pipeline item 10: threshold in [1,100] whenever exclusivity is required."""
    if exclusivity_required and (threshold is None or threshold < 1 or threshold > 100):
        raise ApiError(ERR_INVALID_EXCLUSIVITY, 422,
                       "exclusivity_threshold_pct must be in [1,100] when exclusivity_required")


@bp.route("/coop/suppliers/<supplier_id>/supplier-programs", methods=["POST"])
@require_roles("SupplierRep", "CoopAdmin")
def create_program(uid, role, supplier_id):
    supplier = get_supplier_or_404(supplier_id)
    body = body_json(required=True)
    program_code = req_str(body, "program_code")
    exclusivity_required = req_bool(body, "exclusivity_required")
    threshold = req_int(body, "exclusivity_threshold_pct")
    tier_schedule = parse_tier_schedule(body, required=True)
    holdback_policy = req_str(body, "holdback_policy")
    if holdback_policy not in HOLDBACK_POLICIES:
        raise err_invalid_request("holdback_policy must be FLAT or RISK_ADJUSTED")
    validate_tier_schedule(tier_schedule)
    validate_exclusivity(exclusivity_required, threshold)
    for p in store.programs.values():
        if (p["supplier_id"] == supplier["id"] and p["program_code"] == program_code
                and p["status"] != "TERMINATED"):
            raise ApiError(ERR_DUPLICATE_PROGRAM_CODE, 409,
                           "program_code already in use for this supplier")
    program = new_entity()
    program.update({
        "supplier_id": supplier["id"],
        "program_code": program_code,
        "exclusivity_required": exclusivity_required,
        "exclusivity_threshold_pct": threshold,
        "tier_schedule": tier_schedule,
        "holdback_policy": holdback_policy,
        "negotiation_round": 0,
        "status": "DRAFT",
    })
    store.programs[program["id"]] = program
    return success_object(public(program), code=201)


@bp.route("/coop/supplier-programs/<program_id>", methods=["GET"])
@require_roles(*READ_ROLES)
def get_program(uid, role, program_id):
    return success_object(public(get_program_or_404(program_id)), code=200)


@bp.route("/coop/supplier-programs", methods=["GET"])
@require_roles(*READ_ROLES)
def list_programs(uid, role):
    limit, offset = parse_pagination()
    items = list(store.programs.values())
    supplier_id = _arg("supplier_id")
    if supplier_id is not None:
        items = [p for p in items if p["supplier_id"] == supplier_id]
    status = _arg("status")
    if status is not None:
        items = [p for p in items if p["status"] == status]
    page, total = paginate(items, limit, offset)
    return success_list([public(p) for p in page], limit, offset, total)


@bp.route("/coop/supplier-programs/<program_id>", methods=["PUT"])
@require_roles("SupplierRep")
def amend_program(uid, role, program_id):
    program = get_program_or_404(program_id)
    body = body_json(required=True)
    expected = req_int(body, "expected_program_version")
    new_ts = parse_tier_schedule(body, required=False)
    new_required = opt_bool(body, "exclusivity_required")
    new_threshold = opt_int(body, "exclusivity_threshold_pct")
    new_policy = None
    if "holdback_policy" in body and body["holdback_policy"] is not None:
        new_policy = req_str(body, "holdback_policy")
        if new_policy not in HOLDBACK_POLICIES:
            raise err_invalid_request("holdback_policy must be FLAT or RISK_ADJUSTED")
    if program["status"] not in AMENDABLE_STATES:
        raise err_state("A TERMINATED program cannot be amended")
    validate_tier_schedule(new_ts)
    effective_required = program["exclusivity_required"] if new_required is None else new_required
    effective_threshold = (program["exclusivity_threshold_pct"]
                           if new_threshold is None else new_threshold)
    validate_exclusivity(effective_required, effective_threshold)
    if expected != program["version"]:
        raise ApiError(ERR_STALE_PROGRAM_VERSION, 412,
                       "expected_program_version does not match current version")
    if new_ts is not None:
        program["tier_schedule"] = new_ts
    if new_required is not None:
        program["exclusivity_required"] = new_required
    if new_threshold is not None:
        program["exclusivity_threshold_pct"] = new_threshold
    if new_policy is not None:
        program["holdback_policy"] = new_policy
    program["negotiation_round"] += 1
    touch(program)
    return success_object(public(program), code=200)


@bp.route("/coop/supplier-programs/<program_id>/open", methods=["POST"])
@require_roles("SupplierRep")
def open_program(uid, role, program_id):
    program = get_program_or_404(program_id)
    if program["status"] != "DRAFT":
        raise err_state("Only a DRAFT program can be opened")
    validate_tier_schedule(program["tier_schedule"])
    validate_exclusivity(program["exclusivity_required"], program["exclusivity_threshold_pct"])
    supplier = store.suppliers.get(program["supplier_id"])
    if supplier is None or supplier["status"] != "ONBOARDED":
        raise ApiError(ERR_SUPPLIER_NOT_ONBOARDED, 409,
                       "Supplier must be ONBOARDED before its program can be opened")
    program["status"] = "OPEN"
    touch(program)
    return success_object(public(program), code=200)


@bp.route("/coop/supplier-programs/<program_id>/close_to_new", methods=["POST"])
@require_roles("SupplierRep")
def close_program_to_new(uid, role, program_id):
    program = get_program_or_404(program_id)
    if program["status"] not in ("OPEN", "REOPENED"):
        raise err_state("Only an OPEN or REOPENED program can be closed to new enrollments")
    program["status"] = "CLOSED_TO_NEW"
    touch(program)
    return success_object(public(program), code=200)


@bp.route("/coop/supplier-programs/<program_id>/reopen", methods=["POST"])
@require_roles("SupplierRep")
def reopen_program(uid, role, program_id):
    program = get_program_or_404(program_id)
    if program["status"] != "CLOSED_TO_NEW":
        raise err_state("Only a CLOSED_TO_NEW program can be reopened")
    program["status"] = "REOPENED"
    touch(program)
    return success_object(public(program), code=200)


@bp.route("/coop/supplier-programs/<program_id>/terminate", methods=["POST"])
@require_roles("SupplierRep")
def terminate_program(uid, role, program_id):
    program = get_program_or_404(program_id)
    if program["status"] == "TERMINATED":
        raise err_state("Program is already TERMINATED")
    live = [e for e in store.enrollments.values()
            if e["program_id"] == program["id"] and e["status"] in ("ACTIVE", "SUSPENDED")]
    if live:
        raise ApiError(ERR_PROGRAM_HAS_ENROLLMENTS, 409,
                       "Program has ACTIVE or SUSPENDED enrollments")
    program["status"] = "TERMINATED"
    touch(program)
    return success_object(public(program), code=200)
