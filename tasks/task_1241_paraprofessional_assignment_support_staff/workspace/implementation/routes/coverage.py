"""CoveragePlan endpoints (PRD §3.6)."""
from flask import Blueprint, request

import db
import services as svc
from errors import (
    ERR_COVERAGE_GAPS_OPEN, ERR_COVERAGE_PLAN_FROZEN,
    ERR_COVERAGE_PLAN_NOT_PUBLISHED, ERR_DUPLICATE_COVERAGE_PLAN,
    ERR_PLAN_NOT_ACTIVE, ApiError,
)
from middleware import auth_context, require_role
from response import paginate, success
from util import as_date_str, as_str, body_json, need

bp = Blueprint("coverage", __name__)

COORD = {"SpecialEdCoordinator"}
ANY = {"Any"}


def _auth(allowed):
    auth_context()
    require_role(request.headers.get("X-User-Role"), allowed)


def _frozen_or_not_published(cp, required):
    """State gate for coverage-plan transitions. `required` is the from-state."""
    if cp["status"] in ("LOCKED", "RECONCILED"):
        raise ApiError(ERR_COVERAGE_PLAN_FROZEN, 409,
                       "coverage plan is LOCKED/RECONCILED; mutation forbidden")
    if cp["status"] != required:
        raise ApiError(ERR_COVERAGE_PLAN_NOT_PUBLISHED, 409,
                       "coverage plan is not in the required state %s" % required)


@bp.post("/sped-staffing/coverage-plans")
def create_coverage_plan():
    _auth(COORD)
    body = body_json(request)
    plan_id = need(body, "plan_id")
    plan = svc.get_plan(as_str(plan_id, "plan_id"))
    building_id = need(body, "building_id")
    building = svc.get_building(as_str(building_id, "building_id"))
    coverage_date = as_date_str(need(body, "coverage_date"), "coverage_date")
    if plan["status"] != "ACTIVE":
        raise ApiError(ERR_PLAN_NOT_ACTIVE, 409,
                       "coverage plan creation requires plan ACTIVE")
    for c in db.STORE["coverage_plans"].values():
        if (c["building_id"] == building["id"]
                and c["coverage_date"] == coverage_date):
            raise ApiError(ERR_DUPLICATE_COVERAGE_PLAN, 409,
                           "a coverage plan already exists for (building_id, coverage_date)")
    cp = {
        "plan_id": plan["id"],
        "building_id": building["id"],
        "coverage_date": coverage_date,
        "status": "DRAFT",
    }
    svc.stamp_new(cp)
    db.STORE["coverage_plans"][cp["id"]] = cp
    return success(svc.ser_coverage_plan(cp), "object", 201)


@bp.get("/sped-staffing/coverage-plans")
def list_coverage_plans():
    _auth(ANY)
    plan_id = request.args.get("plan_id")
    building_id = request.args.get("building_id")
    coverage_date = request.args.get("coverage_date")
    status = request.args.get("status")
    items = []
    for c in svc.sorted_records("coverage_plans"):
        if plan_id is not None and c["plan_id"] != plan_id:
            continue
        if building_id is not None and c["building_id"] != building_id:
            continue
        if coverage_date is not None and c["coverage_date"] != coverage_date:
            continue
        if status is not None and c["status"] != status:
            continue
        items.append(svc.ser_coverage_plan(c))
    page, meta = paginate(items, request.args)
    return success(page, "array", 200, meta)


@bp.get("/sped-staffing/coverage-plans/<coveragePlanId>")
def get_coverage_plan(coveragePlanId):
    _auth(ANY)
    cp = svc.get_coverage_plan(coveragePlanId)
    return success(svc.ser_coverage_plan(cp), "object", 200)


@bp.post("/sped-staffing/coverage-plans/<coveragePlanId>/publish")
def publish_coverage_plan(coveragePlanId):
    _auth(COORD)
    cp = svc.get_coverage_plan(coveragePlanId)
    _frozen_or_not_published(cp, "DRAFT")
    cp["status"] = "PUBLISHED"
    svc.touch(cp)
    return success(svc.ser_coverage_plan(cp), "object", 200)


@bp.post("/sped-staffing/coverage-plans/<coveragePlanId>/reopen")
def reopen_coverage_plan(coveragePlanId):
    _auth(COORD)
    cp = svc.get_coverage_plan(coveragePlanId)
    _frozen_or_not_published(cp, "PUBLISHED")
    if svc.coverage_posture(cp) != "OPEN":
        raise ApiError(ERR_COVERAGE_GAPS_OPEN, 409,
                       "reopen blocked by open absence gaps")
    cp["status"] = "DRAFT"
    svc.touch(cp)
    return success(svc.ser_coverage_plan(cp), "object", 200)


@bp.post("/sped-staffing/coverage-plans/<coveragePlanId>/lock")
def lock_coverage_plan(coveragePlanId):
    _auth(COORD)
    cp = svc.get_coverage_plan(coveragePlanId)
    _frozen_or_not_published(cp, "PUBLISHED")
    if svc.coverage_posture(cp) != "OPEN":
        raise ApiError(ERR_COVERAGE_GAPS_OPEN, 409,
                       "lock blocked by open absence gaps")
    cp["status"] = "LOCKED"
    svc.touch(cp)
    return success(svc.ser_coverage_plan(cp), "object", 200)


@bp.post("/sped-staffing/coverage-plans/<coveragePlanId>/reconcile")
def reconcile_coverage_plan(coveragePlanId):
    _auth(COORD)
    cp = svc.get_coverage_plan(coveragePlanId)
    if cp["status"] in ("DRAFT", "PUBLISHED"):
        raise ApiError(ERR_COVERAGE_PLAN_NOT_PUBLISHED, 409,
                       "reconcile requires coverage plan LOCKED")
    if cp["status"] != "LOCKED":
        raise ApiError(ERR_COVERAGE_PLAN_FROZEN, 409,
                       "coverage plan is already RECONCILED")
    # Sweep linked absences and backfills to terminal states.
    for ab in db.STORE["absences"].values():
        if ab["coverage_plan_id"] != cp["id"]:
            continue
        if ab["status"] in svc.NON_TERMINAL_ABSENCE:
            ab["status"] = "UNCOVERED"
            svc.touch(ab)
    for b in db.STORE["backfills"].values():
        ab = db.STORE["absences"].get(b["absence_id"])
        if ab is None or ab["coverage_plan_id"] != cp["id"]:
            continue
        if b["status"] == "OFFERED":
            b["status"] = "CANCELLED"
            svc.touch(b)
        elif b["status"] == "ACCEPTED":
            b["status"] = "COMPLETED"
            svc.touch(b)
    cp["status"] = "RECONCILED"
    svc.touch(cp)
    return success(svc.ser_coverage_plan(cp), "object", 200)
