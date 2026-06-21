"""Policy + Coverage routes (PRD §3.1)."""
from flask import Blueprint

import db
import serializers as S
from auth import authenticate, authorize
from errors import err
from helpers import (get_json_body, require_resource, require_fields,
                     require_str, require_int, optional_int, optional_enum,
                     parse_pagination, paginate)
from response import success, list_success
from util import parse_iso
from services.lookups import coverages_for_policy, coverage_of_type

bp = Blueprint("policies", __name__)

FAULT_RULES = {"PURE", "MODIFIED_50", "MODIFIED_51"}
COVERAGE_TYPES = {"COLLISION", "COMPREHENSIVE", "RENTAL"}

READ_ROLES = {"ClaimsSupervisor", "ClaimsAdjuster", "TotalLossAdjuster",
              "SubrogationSpecialist"}


def _policy_interval_overlap(new_start, new_end, ex_start, ex_end):
    """Closed-interval overlap, adjacency REJECTED:
    overlap iff start_A <= end_B AND start_B <= end_A."""
    return new_start <= ex_end and ex_start <= new_end


@bp.route("/policies", methods=["POST"])
def create_policy():
    principal = authenticate()
    authorize(principal, {"ClaimsSupervisor"})
    body = get_json_body()
    require_fields(body, ["policyholder_name", "policy_number",
                          "effective_date", "expiration_date"])
    policyholder_name = require_str(body, "policyholder_name")
    policy_number = require_str(body, "policy_number")
    effective_date = parse_iso(body["effective_date"])
    expiration_date = parse_iso(body["expiration_date"])
    fault_rule = optional_enum(body, "comparative_fault_rule", FAULT_RULES, "MODIFIED_50")

    # Unique policy_number across all policies.
    for p in db.policies.values():
        if p["policy_number"] == policy_number:
            raise err("ERR_INVALID_REQUEST",
                      "policy_number already exists: %s" % policy_number)

    # Policy-period overlap for the same policyholder_name (closed interval,
    # adjacency rejected); ignore CANCELLED policies (status IN {ACTIVE,LAPSED}).
    for p in db.policies.values():
        if p["policyholder_name"] != policyholder_name:
            continue
        if p["status"] not in ("ACTIVE", "LAPSED"):
            continue
        if _policy_interval_overlap(effective_date, expiration_date,
                                    p["effective_date"], p["expiration_date"]):
            raise err("ERR_POLICY_PERIOD_OVERLAP",
                      "policy period overlaps an existing policy for this policyholder")

    rec = {
        "policyholder_name": policyholder_name,
        "policy_number": policy_number,
        "status": "ACTIVE",
        "effective_date": effective_date,
        "expiration_date": expiration_date,
        "comparative_fault_rule": fault_rule,
    }
    db.insert(db.policies, rec)
    return success(S.policy(rec), status=201)


@bp.route("/policies/<pid>", methods=["GET"])
def get_policy(pid):
    principal = authenticate()
    authorize(principal, READ_ROLES)
    rec = require_resource(db.policies, pid, "policy")
    return success(S.policy(rec), status=200)


@bp.route("/policies/<pid>/lapse", methods=["POST"])
def lapse_policy(pid):
    principal = authenticate()
    authorize(principal, {"ClaimsSupervisor"})
    rec = require_resource(db.policies, pid, "policy")
    rec["status"] = "LAPSED"
    db.touch(rec)
    return success(S.policy(rec), status=200)


@bp.route("/policies/<pid>/coverages", methods=["POST"])
def add_coverage(pid):
    principal = authenticate()
    authorize(principal, {"ClaimsSupervisor"})
    policy = require_resource(db.policies, pid, "policy")
    body = get_json_body()
    require_fields(body, ["coverage_type", "limit_cents"])
    coverage_type = body["coverage_type"]
    if coverage_type not in COVERAGE_TYPES:
        raise err("ERR_INVALID_REQUEST", "coverage_type out of set")
    limit_cents = require_int(body, "limit_cents")
    deductible_cents = optional_int(body, "deductible_cents", 0)
    rental_daily_cap_cents = optional_int(body, "rental_daily_cap_cents", 0)
    rental_max_days = optional_int(body, "rental_max_days", 0)

    # At most one Coverage per (policy_id, coverage_type).
    if coverage_of_type(pid, coverage_type) is not None:
        raise err("ERR_DUPLICATE_COVERAGE",
                  "coverage of type %s already exists for this policy" % coverage_type)

    rec = {
        "policy_id": pid,
        "coverage_type": coverage_type,
        "limit_cents": limit_cents,
        "deductible_cents": deductible_cents,
        "rental_daily_cap_cents": rental_daily_cap_cents,
        "rental_max_days": rental_max_days,
    }
    db.insert(db.coverages, rec)
    return success(S.coverage(rec), status=201)


@bp.route("/policies/<pid>/coverages", methods=["GET"])
def list_coverages(pid):
    principal = authenticate()
    authorize(principal, READ_ROLES)
    require_resource(db.policies, pid, "policy")
    limit, offset = parse_pagination()
    rows = coverages_for_policy(pid)
    page, total = paginate(rows, limit, offset)
    return list_success([S.coverage(r) for r in page], limit, offset, total)
