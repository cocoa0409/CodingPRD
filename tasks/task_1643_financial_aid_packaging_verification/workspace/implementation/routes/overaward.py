"""OverawardCase endpoints (PRD 3.8): resolution plan, rollback, verify."""
from flask import Blueprint, request

from db import db
from errors import (
    raise_error, ERR_INVALID_REQUEST, ERR_INVALID_STATE,
    ERR_OVERAWARD_PLAN_INVALID,
)
from middleware import authorized
from response import success_object
from routes.helpers import list_response
from services.core import (
    public, touch, recompute_package_totals, recompute_aggregates,
    counted_external_aid, package_for,
)
from validate import get_body, require_path_resource

bp = Blueprint("overaward", __name__)

DIRECTOR_OFFICER = ["AidDirector", "AidOfficer"]
OFFICER = ["AidOfficer"]


@bp.get("/overaward-cases")
def list_cases():
    authorized(DIRECTOR_OFFICER)
    return list_response("overaward_cases", {
        "student_id": request.args.get("student_id"),
        "aid_year_id": request.args.get("aid_year_id"),
        "status": request.args.get("status"),
    })


@bp.get("/overaward-cases/<rid>")
def get_case(rid):
    authorized(DIRECTOR_OFFICER)
    rec = require_path_resource("overaward_cases", rid)
    return success_object(public(rec))


def _validate_plan(case, plan):
    """Whole-plan validation (PRD 3.8). Any violation fails with
    ERR_OVERAWARD_PLAN_INVALID and leaves the case OPEN."""
    if not plan:
        raise_error(ERR_OVERAWARD_PLAN_INVALID, "resolution_plan must be non-empty")
    steps = []
    running = {}
    for entry in plan:
        if not isinstance(entry, dict):
            raise_error(ERR_OVERAWARD_PLAN_INVALID,
                        "resolution_plan steps must be objects")
        line_id = entry.get("award_line_id")
        reduce_by = entry.get("reduce_by_cents")
        if not isinstance(line_id, str) or not line_id:
            raise_error(ERR_OVERAWARD_PLAN_INVALID,
                        "each step must name an award_line_id")
        if not isinstance(reduce_by, int) or isinstance(reduce_by, bool):
            raise_error(ERR_OVERAWARD_PLAN_INVALID,
                        "each step's reduce_by_cents must be an integer")
        line = db.award_lines.get(line_id)
        if line is None:
            raise_error(ERR_OVERAWARD_PLAN_INVALID,
                        f"plan references an unknown award line: {line_id}")
        pkg = db.award_packages.get(line["package_id"])
        if (pkg is None or pkg["student_id"] != case["student_id"]
                or pkg["aid_year_id"] != case["aid_year_id"]):
            raise_error(ERR_OVERAWARD_PLAN_INVALID,
                        "every referenced line must belong to a package of the same "
                        "student and aid year")
        if reduce_by <= 0:
            raise_error(ERR_OVERAWARD_PLAN_INVALID,
                        "each reduce_by_cents must be strictly positive")
        remaining = running.get(line_id, line["accepted_cents"])
        if reduce_by > remaining:
            raise_error(ERR_OVERAWARD_PLAN_INVALID,
                        "reduce_by_cents may not exceed the target line's "
                        "accepted_cents")
        running[line_id] = remaining - reduce_by
        steps.append((line, reduce_by))
    if sum(amount for _, amount in steps) < case["overage_cents"]:
        raise_error(ERR_OVERAWARD_PLAN_INVALID,
                    "the plan's steps must sum to at least the overage_cents")
    return steps


def _line_has_posted_disbursement(line_id):
    return any(d["award_line_id"] == line_id and d["status"] == "POSTED"
               for d in db.disbursements.values())


@bp.post("/overaward-cases/<rid>/begin-resolution")
def begin_resolution(rid):
    authorized(OFFICER)
    case = require_path_resource("overaward_cases", rid)
    if case["status"] != "OPEN":
        raise_error(ERR_INVALID_STATE,
                    f"case is {case['status']}, expected OPEN")
    body = get_body()
    plan = body.get("resolution_plan")
    if plan is None or not isinstance(plan, list):
        raise_error(ERR_INVALID_REQUEST, "resolution_plan must be an array")
    steps = _validate_plan(case, plan)

    # Snapshot every step for an exact rollback, then apply in array order.
    snapshot = [{"award_line_id": line["id"],
                 "old_status": line["status"],
                 "old_accepted_cents": line["accepted_cents"]} for line, _ in steps]
    affected_packages = set()
    for line, reduce_by in steps:
        line["accepted_cents"] -= reduce_by
        remainder = line["accepted_cents"]
        if remainder == 0 and not _line_has_posted_disbursement(line["id"]):
            line["status"] = "DECLINED"
        elif remainder > 0 and line["status"] == "ACCEPTED":
            line["status"] = "PARTIALLY_ACCEPTED"
        touch(line)
        affected_packages.add(line["package_id"])
    for pkg_id in affected_packages:
        recompute_package_totals(db.award_packages[pkg_id])
    recompute_aggregates(case["aid_year_id"])

    case["status"] = "RESOLVING"
    case["resolution_plan"] = [dict(award_line_id=l["id"], reduce_by_cents=a)
                               for l, a in steps]
    case["_plan_snapshot"] = snapshot
    touch(case)

    # Auto-transition to RESOLVED once the recomputed total aid is at or below
    # the cost of attendance.
    pkg = package_for(case["student_id"], case["aid_year_id"])
    if pkg is not None:
        total_aid = pkg["total_accepted_cents"] + counted_external_aid(
            case["student_id"], case["aid_year_id"])
        if total_aid <= pkg["coa_used_cents"]:
            case["status"] = "RESOLVED"
            touch(case)
    return success_object(public(case))


@bp.post("/overaward-cases/<rid>/rollback")
def rollback(rid):
    authorized(OFFICER)
    case = require_path_resource("overaward_cases", rid)
    if case["status"] not in ("RESOLVING", "RESOLVED"):
        raise_error(ERR_INVALID_STATE,
                    f"case is {case['status']}, expected RESOLVING or RESOLVED")
    snapshot = case.get("_plan_snapshot") or []
    # Rollback is only possible while no POSTED disbursement exists on any line
    # the plan modified.
    for step in snapshot:
        if _line_has_posted_disbursement(step["award_line_id"]):
            raise_error(ERR_INVALID_STATE,
                        "a POSTED disbursement exists on a line the plan modified")
    affected_packages = set()
    for step in snapshot:
        line = db.award_lines.get(step["award_line_id"])
        if line is None:
            continue
        line["accepted_cents"] = step["old_accepted_cents"]
        line["status"] = step["old_status"]
        touch(line)
        affected_packages.add(line["package_id"])
    for pkg_id in affected_packages:
        recompute_package_totals(db.award_packages[pkg_id])
    recompute_aggregates(case["aid_year_id"])
    case["status"] = "OPEN"
    touch(case)
    return success_object(public(case))


@bp.post("/overaward-cases/<rid>/verify")
def verify(rid):
    authorized(["AidDirector"])
    case = require_path_resource("overaward_cases", rid)
    if case["status"] != "RESOLVED":
        raise_error(ERR_INVALID_STATE,
                    f"case is {case['status']}, expected RESOLVED")
    case["status"] = "VERIFIED"
    touch(case)
    return success_object(public(case))
