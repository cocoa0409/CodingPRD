"""AllocationFormula + FundingAllocation endpoints (PRD §3.1, §3.9)."""
from flask import Blueprint, request

import db
import services as svc
from errors import (
    ERR_ALLOCATIONS_ALREADY_COMPUTED, ERR_FORMULA_NOT_PUBLISHED,
    ERR_PLAN_NOT_ACTIVE, ApiError,
)
from middleware import auth_context, require_role
from response import paginate, success
from util import as_int, as_num, as_str, bad_request, body_json, need

bp = Blueprint("funding", __name__)

ADMIN = {"DistrictStaffingAdmin"}
ANY = {"Any"}


def _auth(allowed):
    auth_context()
    require_role(request.headers.get("X-User-Role"), allowed)


@bp.post("/sped-staffing/allocation-formulas")
def create_formula():
    _auth(ADMIN)
    body = body_json(request)
    plan_id = need(body, "plan_id")
    plan = svc.get_plan(as_str(plan_id, "plan_id"))
    base_grant = as_int(need(body, "base_grant_cents"), "base_grant_cents")
    if base_grant < 0:
        bad_request("base_grant_cents must be >= 0")
    rate = as_int(need(body, "per_minute_rate_cents"), "per_minute_rate_cents")
    if rate <= 0:
        bad_request("per_minute_rate_cents must be > 0")
    w_oto = as_num(need(body, "weight_one_to_one"), "weight_one_to_one")
    w_ss = as_num(need(body, "weight_shared_support"), "weight_shared_support")
    w_tr = as_num(need(body, "weight_transitional"), "weight_transitional")
    period_weeks = as_int(need(body, "period_weeks"), "period_weeks")
    if period_weeks <= 0:
        bad_request("period_weeks must be > 0")
    if plan["status"] not in ("DRAFT", "ACTIVE"):
        raise ApiError(ERR_PLAN_NOT_ACTIVE, 409,
                       "formula creation requires plan DRAFT or ACTIVE")
    version_no = 1
    for f in db.STORE["formulas"].values():
        if f["plan_id"] == plan["id"] and f["version_no"] >= version_no:
            version_no = f["version_no"] + 1
    formula = {
        "plan_id": plan["id"],
        "version_no": version_no,
        "base_grant_cents": base_grant,
        "per_minute_rate_cents": rate,
        "weight_one_to_one": w_oto,
        "weight_shared_support": w_ss,
        "weight_transitional": w_tr,
        "period_weeks": period_weeks,
        "status": "DRAFT",
    }
    svc.stamp_new(formula)
    db.STORE["formulas"][formula["id"]] = formula
    return success(svc.ser_formula(formula), "object", 201)


@bp.get("/sped-staffing/allocation-formulas")
def list_formulas():
    _auth(ANY)
    plan_id = request.args.get("plan_id")
    status = request.args.get("status")
    items = []
    for f in svc.sorted_records("formulas"):
        if plan_id is not None and f["plan_id"] != plan_id:
            continue
        if status is not None and f["status"] != status:
            continue
        items.append(svc.ser_formula(f))
    page, meta = paginate(items, request.args)
    return success(page, "array", 200, meta)


@bp.get("/sped-staffing/allocation-formulas/<formulaId>")
def get_formula(formulaId):
    _auth(ANY)
    f = svc.get_formula(formulaId)
    return success(svc.ser_formula(f), "object", 200)


@bp.post("/sped-staffing/allocation-formulas/<formulaId>/publish")
def publish_formula(formulaId):
    _auth(ADMIN)
    f = svc.get_formula(formulaId)
    if f["status"] != "DRAFT":
        raise ApiError(ERR_FORMULA_NOT_PUBLISHED, 409,
                       "publish requires formula DRAFT")
    # Supersede any other PUBLISHED formula of the same plan.
    for other in db.STORE["formulas"].values():
        if (other["plan_id"] == f["plan_id"] and other["id"] != f["id"]
                and other["status"] == "PUBLISHED"):
            other["status"] = "SUPERSEDED"
            svc.touch(other)
    f["status"] = "PUBLISHED"
    svc.touch(f)
    return success(svc.ser_formula(f), "object", 200)


@bp.post("/sped-staffing/funding-allocations/compute")
def compute_allocations():
    _auth(ADMIN)
    body = body_json(request)
    formula_id = need(body, "formula_id")
    formula = svc.get_formula(as_str(formula_id, "formula_id"))
    period_label = as_str(need(body, "period_label"), "period_label")
    plan = db.STORE["plans"][formula["plan_id"]]
    if plan["status"] != "ACTIVE":
        raise ApiError(ERR_PLAN_NOT_ACTIVE, 409,
                       "allocation compute requires plan ACTIVE")
    if formula["status"] != "PUBLISHED":
        raise ApiError(ERR_FORMULA_NOT_PUBLISHED, 409,
                       "compute requires the formula PUBLISHED")
    for al in db.STORE["allocations"].values():
        if al["formula_id"] == formula["id"] and al["period_label"] == period_label:
            raise ApiError(ERR_ALLOCATIONS_ALREADY_COMPUTED, 409,
                           "allocations already computed for (formula_id, period_label)")
    rows = []
    for b in svc.sorted_records("buildings"):
        if b["plan_id"] != plan["id"]:
            continue
        al = {
            "plan_id": plan["id"],
            "building_id": b["id"],
            "formula_id": formula["id"],
            "period_label": period_label,
            "provisional_amount_cents": svc.provisional_building_amount(
                formula, b, plan),
            "final_amount_cents": None,
            "variance_cents": None,
            "status": "PROVISIONAL",
        }
        svc.stamp_new(al)
        db.STORE["allocations"][al["id"]] = al
        rows.append(svc.ser_allocation(al))
    return success(rows, "array", 201)


@bp.get("/sped-staffing/funding-allocations")
def list_allocations():
    _auth(ANY)
    plan_id = request.args.get("plan_id")
    building_id = request.args.get("building_id")
    formula_id = request.args.get("formula_id")
    status = request.args.get("status")
    items = []
    for a in svc.sorted_records("allocations"):
        if plan_id is not None and a["plan_id"] != plan_id:
            continue
        if building_id is not None and a["building_id"] != building_id:
            continue
        if formula_id is not None and a["formula_id"] != formula_id:
            continue
        if status is not None and a["status"] != status:
            continue
        items.append(svc.ser_allocation(a))
    page, meta = paginate(items, request.args)
    return success(page, "array", 200, meta)


@bp.get("/sped-staffing/funding-allocations/<allocationId>")
def get_allocation(allocationId):
    _auth(ANY)
    a = svc.get_allocation(allocationId)
    return success(svc.ser_allocation(a), "object", 200)
