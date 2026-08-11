from flask import Blueprint, request

from db import create_rec, sorted_ords, store
from errors import ApiError
from middleware import body, require_roles
from response import ok_obj, paginate
from serialize import ser_plan
from validate import req_enum, req_num, req_str

bp = Blueprint("plans", __name__)

PRICING_MODELS = ("PER_DAY", "PERCENT_OF_RENTAL")
SEVERITIES = ("COSMETIC", "MINOR", "MAJOR", "TOTAL_LOSS")


def _get_plan(pid):
    p = store.plans.get(pid)
    if p is None:
        raise ApiError("ERR_PLAN_NOT_FOUND", 404, "Insurance plan not found")
    return p


def _is_intish(v):
    return (isinstance(v, int) and not isinstance(v, bool)) or \
           (isinstance(v, float) and v == int(v))


@bp.post("/insurance-plans")
def create_plan():
    require_roles("OperationsAdmin")
    b = body()
    code = req_str(b, "code")
    pricing_model = req_enum(b, "pricing_model", PRICING_MODELS)
    rate = b.get("rate_value")
    if not (isinstance(rate, (int, float)) and not isinstance(rate, bool)):
        raise ApiError("ERR_INVALID_REQUEST", 400, "rate_value must be a number")
    deductible = b.get("deductible_cents")
    if not _is_intish(deductible) or deductible < 0:
        raise ApiError("ERR_INVALID_REQUEST", 400, "deductible_cents must be an integer >= 0")
    cap = b.get("coverage_cap_cents")
    if not _is_intish(cap) or cap <= 0:
        raise ApiError("ERR_INVALID_REQUEST", 400, "coverage_cap_cents must be an integer > 0")
    covered = b.get("covered_severities")
    if (not isinstance(covered, list)
            or any(s not in SEVERITIES for s in covered)):
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "covered_severities must be a subset of COSMETIC/MINOR/MAJOR/TOTAL_LOSS")
    if any(p["code"] == code for p in store.plans.values()):
        raise ApiError("ERR_INVALID_REQUEST", 400, "code must be unique across plans")
    # Fiscal sanity: rate range depends on the pricing model -> ERR_INVALID_PLAN_RATE
    if pricing_model == "PER_DAY":
        if not _is_intish(rate) or rate <= 0:
            raise ApiError("ERR_INVALID_PLAN_RATE", 422,
                           "PER_DAY rate_value must be a positive integer (cents per day)")
    else:
        if rate <= 0 or rate > 0.25:
            raise ApiError("ERR_INVALID_PLAN_RATE", 422,
                           "PERCENT_OF_RENTAL rate_value must be in (0, 0.25]")
    rec = create_rec(store.plans, {
        "code": code, "pricing_model": pricing_model, "rate_value": rate,
        "deductible_cents": int(deductible), "coverage_cap_cents": int(cap),
        "covered_severities": list(covered)})
    return ok_obj(ser_plan(rec), 201)


@bp.get("/insurance-plans")
def list_plans():
    require_roles("Customer", "HotelPartner", "OperationsAdmin")
    recs = sorted_ords(list(store.plans.values()))
    model = request.args.get("pricing_model")
    if model is not None:
        recs = [p for p in recs if p["pricing_model"] == model]
    return paginate(recs, ser_plan)


@bp.get("/insurance-plans/<pid>")
def get_plan(pid):
    require_roles("Customer", "HotelPartner", "OperationsAdmin")
    return ok_obj(ser_plan(_get_plan(pid)))
