"""Policy endpoints: create/list/get, bind (OCC-guarded), cancel."""

from flask import request

from db import db
from errors import err
from middleware import require_roles
from response import success_list, success_object
from routes import bp
from services.lifecycle import sweep
from services.posture import (
    recompute_posture,
    touch_production_once,
)
from services.pricing import premium_calculate
from util import (
    body,
    get_child,
    get_production,
    make_entity,
    paginate,
    req_dt,
    req_enum,
    req_int,
    req_string,
    serialize,
    touch,
)

COVERAGE_LINES = (
    "GENERAL_LIABILITY",
    "EQUIPMENT",
    "CAST",
    "ERRORS_OMISSIONS",
    "FOREIGN_TRAVEL",
)

POLICY_READ_ROLES = {
    "BrokerAgent", "ProductionManager", "UnderwriterAgent",
    "ClaimsAdjuster", "ExternalAuditor", "PlatformOperator",
}


def get_policy(prod_id, policy_id):
    return get_child(db.policies, policy_id, "production_id", prod_id, "Policy")


def _check_policy_number_unique(carrier_code, coverage_line, policy_number):
    for pol in db.policies.values():
        if (pol["carrier_code"] == carrier_code
                and pol["coverage_line"] == coverage_line
                and pol["policy_number"] == policy_number):
            raise err("ERR_DUPLICATE_IDENTIFIER",
                      "policy_number '%s' already exists for (%s, %s)"
                      % (policy_number, carrier_code, coverage_line))


def _occ_check_production(data, prod):
    expected = data.get("expected_production_version")
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise err("ERR_INVALID_REQUEST",
                  "Field 'expected_production_version' is required and must be an integer")
    if expected != prod["version"]:
        raise err("ERR_STALE_VERSION",
                  "expected_production_version %s does not match current version %s"
                  % (expected, prod["version"]))


@bp.route("/productions/<id>/policies", methods=["POST"])
def create_policy(id):
    require_roles({"BrokerAgent"})
    with db.lock:
        prod = get_production(id)
        data = body()
        coverage_line = req_enum(data, "coverage_line", COVERAGE_LINES)
        carrier_code = req_string(data, "carrier_code")
        policy_number = req_string(data, "policy_number")
        limit_cents = req_int(data, "limit_cents")
        aggregate_limit_cents = req_int(data, "aggregate_limit_cents")
        deductible_cents = req_int(data, "deductible_cents")
        effective_date = req_dt(data, "effective_date")
        expiry_date = req_dt(data, "expiry_date")
        payroll_basis_cents = req_int(data, "payroll_basis_cents")

        if expiry_date <= effective_date:
            raise err("ERR_TEMPORAL_RANGE_INVALID",
                      "expiry_date must be after effective_date")
        if limit_cents <= 0:
            raise err("ERR_FISCAL_CONSTRAINT_VIOLATED", "limit_cents must be greater than zero")
        if aggregate_limit_cents < limit_cents:
            raise err("ERR_FISCAL_CONSTRAINT_VIOLATED",
                      "aggregate_limit_cents must be at least limit_cents")
        if deductible_cents < 0:
            raise err("ERR_FISCAL_CONSTRAINT_VIOLATED", "deductible_cents must be zero or more")
        if payroll_basis_cents < 0:
            raise err("ERR_FISCAL_CONSTRAINT_VIOLATED",
                      "payroll_basis_cents must be zero or more")
        _check_policy_number_unique(carrier_code, coverage_line, policy_number)

        rec = make_entity({
            "production_id": id,
            "coverage_line": coverage_line,
            "carrier_code": carrier_code,
            "policy_number": policy_number,
            "limit_cents": limit_cents,
            "aggregate_limit_cents": aggregate_limit_cents,
            "deductible_cents": deductible_cents,
            "effective_date": effective_date,
            "expiry_date": expiry_date,
            "provisional_premium_cents": None,
            "final_premium_cents": None,
            "payroll_basis_cents": payroll_basis_cents,
            "audited_payroll_cents": None,
            "status": "QUOTED",
        })
        db.policies[rec["id"]] = rec
        return success_object(serialize(rec), status=201)


@bp.route("/productions/<id>/policies", methods=["GET"])
def list_policies(id):
    require_roles(POLICY_READ_ROLES)
    get_production(id)
    line = request.args.get("coverage_line")
    status = request.args.get("status")
    records = [p for p in db.policies.values() if p["production_id"] == id]
    if line is not None:
        records = [r for r in records if r["coverage_line"] == line]
    if status is not None:
        records = [r for r in records if r["status"] == status]
    items, page = paginate(records)
    return success_list(items, page)


@bp.route("/productions/<id>/policies/<childId>", methods=["GET"])
def get_policy_by_id(id, childId):
    require_roles(POLICY_READ_ROLES)
    get_production(id)
    rec = get_policy(id, childId)
    return success_object(serialize(rec))


@bp.route("/productions/<id>/policies/<childId>/bind", methods=["POST"])
def bind_policy(id, childId):
    require_roles({"BrokerAgent"})
    with db.lock:
        prod = get_production(id)
        pol = get_policy(id, childId)
        if pol["status"] != "QUOTED":
            raise err("ERR_INVALID_STATE",
                      "Policy must be QUOTED to bind (current: %s)" % pol["status"])
        data = body()
        _occ_check_production(data, prod)

        if prod["status"] not in ("DRAFT", "ACTIVE"):
            raise err("ERR_REFERENCED_STATE_INVALID",
                      "Production must be DRAFT or ACTIVE to bind a policy")

        line = pol["coverage_line"]
        if line == "CAST":
            for cm in db.cast_members.values():
                if (cm["production_id"] == id and cm["endorsement_required"]
                        and cm["physical_exam_status"] not in ("CLEARED", "CONDITIONAL")):
                    raise err("ERR_CAST_EXAM_INCOMPLETE",
                              "Cast member '%s' exam is not CLEARED or CONDITIONAL" % cm["id"])
        elif line == "ERRORS_OMISSIONS":
            for ci in db.clearance_items.values():
                if (ci["production_id"] == id
                        and ci["clearance_kind"] in ("SCRIPT", "TITLE")
                        and ci["status"] not in ("CLEARED", "WAIVED")):
                    raise err("ERR_EO_CLEARANCE_INCOMPLETE",
                              "Clearance item '%s' is not CLEARED or WAIVED" % ci["id"])
        elif line == "FOREIGN_TRAVEL":
            has_gl = any(
                p["production_id"] == id
                and p["coverage_line"] == "GENERAL_LIABILITY"
                and p["status"] in ("BOUND", "ENDORSED_PENDING", "ACTIVE")
                for p in db.policies.values()
            )
            if not has_gl:
                raise err("ERR_GL_PREREQUISITE_MISSING",
                          "A bound GENERAL_LIABILITY policy is required first")

        pol["provisional_premium_cents"] = premium_calculate(
            prod, pol, pol["payroll_basis_cents"])
        pol["status"] = "BOUND"
        touch(pol)
        touch_production_once(prod)   # binding explicitly advances the production version
        recompute_posture(prod)
        sweep()
        return success_object(serialize(pol))


@bp.route("/productions/<id>/policies/<childId>/cancel", methods=["POST"])
def cancel_policy(id, childId):
    require_roles({"BrokerAgent"})
    with db.lock:
        prod = get_production(id)
        pol = get_policy(id, childId)
        if pol["status"] not in ("BOUND", "ACTIVE"):
            raise err("ERR_INVALID_STATE",
                      "Policy must be BOUND or ACTIVE to cancel (current: %s)" % pol["status"])
        for cl in db.claims.values():
            if cl["policy_id"] == childId and cl["status"] in ("SUBMITTED", "UNDER_REVIEW", "ADJUSTED"):
                raise err("ERR_OPEN_CLAIMS_BLOCK_POLICY_CANCEL",
                          "Policy cannot cancel while it has open claims")

        was = pol["status"]
        pol["status"] = "CANCELLED"
        touch(pol)

        for e in db.cast_endorsements.values():
            if e["policy_id"] == childId and e["status"] in ("DRAFT", "ISSUED"):
                e["status"] = "REVOKED"
                e["revoked_at"] = pol["updated_at"]
                touch(e)

        if was == "ACTIVE":
            for cert in db.certificates.values():
                if (cert["production_id"] == id
                        and cert["status"] in ("DRAFT", "ISSUED")
                        and pol["coverage_line"] in cert["coverage_lines"]):
                    cert["status"] = "VOIDED"
                    touch(cert)

        recompute_posture(prod)
        return success_object(serialize(pol))
