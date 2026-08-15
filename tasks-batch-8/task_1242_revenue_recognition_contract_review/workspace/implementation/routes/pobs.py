from flask import Blueprint

from db import STORE, make_rec, mark, sort_created
from errors import (ApiError, ERR_INVALID_REQUEST, ERR_NOT_FOUND,
                    ERR_INVALID_STATE_TRANSITION, ERR_CONTRACT_NOT_ACTIVE,
                    ERR_INVALID_AMOUNT, ERR_RECOGNITION_PATTERN_FORBIDDEN,
                    ERR_SSP_NOT_FOUND)
from response import ok_object, ok_list
import serializers as ser
import services as svc
from clock import CLOCK, now_ts
from validate import (require_roles, body, req_str, opt_str, req_enum, req_int,
                      opt_int, opt_date, req_date)

bp = Blueprint("pobs", __name__)

PATTERNS = {"POINT_IN_TIME", "OVER_TIME_INPUT_COST", "OVER_TIME_STRAIGHT_LINE"}
ALL_READ = ("RevenueAccountant", "RevenueManager", "ContractReviewer", "Controller")


def get_pob_or_404(pob_id):
    p = STORE.pobs.get(pob_id)
    if p is None:
        raise ApiError(ERR_NOT_FOUND, 404, "pob_id does not identify an existing performance obligation")
    return p


def get_contract_or_404(contract_id):
    c = STORE.contracts.get(contract_id)
    if c is None:
        raise ApiError(ERR_NOT_FOUND, 404, "contract id does not identify an existing contract")
    return c


def require_active(contract):
    if contract["status"] != "ACTIVE":
        raise ApiError(ERR_CONTRACT_NOT_ACTIVE, 409, "operation requires the owning contract to be ACTIVE")


def resolve_ssp(product_code, region, signed_date):
    """ACTIVE price whose CLOSED window covers (product, region) at signed_date."""
    for s in STORE.ssp_prices.values():
        if s["status"] != "ACTIVE":
            continue
        if s["product_code"] == product_code and s["region"] == region \
                and s["effective_from"] <= signed_date <= s["effective_to"]:
            return s
    return None


@bp.post("/revrec/contracts/<contract_id>/pobs")
def create_pob(contract_id):
    require_roles("RevenueAccountant")
    c = get_contract_or_404(contract_id)
    data = body()
    pob_ref = req_str(data, "pob_ref")
    product_code = req_str(data, "product_code")
    region = req_str(data, "region")
    pattern = req_enum(data, "recognition_pattern", PATTERNS)
    description = opt_str(data, "description")
    start = opt_date(data, "service_start_date")
    end = opt_date(data, "service_end_date")
    est_cost = opt_int(data, "estimated_total_cost_cents")
    if pattern == "OVER_TIME_STRAIGHT_LINE":
        if start is None or end is None:
            raise ApiError(ERR_INVALID_REQUEST, 400,
                           "service_start_date and service_end_date are required for OVER_TIME_STRAIGHT_LINE")
        if end <= start:
            raise ApiError(ERR_INVALID_REQUEST, 400, "service_end_date must be after service_start_date")
    if pattern == "OVER_TIME_INPUT_COST" and est_cost is None:
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "estimated_total_cost_cents is required for OVER_TIME_INPUT_COST")
    if c["status"] not in ("DRAFT", "CHANGES_REQUESTED"):
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409,
                       "obligations may be added only while the contract is DRAFT or CHANGES_REQUESTED")
    for p in STORE.pobs.values():
        if p["contract_id"] == contract_id and p["pob_ref"] == pob_ref:
            raise ApiError(ERR_INVALID_REQUEST, 400, "pob_ref must be unique within its contract")
    if pattern == "OVER_TIME_INPUT_COST" and est_cost <= 0:
        raise ApiError(ERR_INVALID_AMOUNT, 422, "estimated_total_cost_cents must be > 0")
    price = resolve_ssp(product_code, region, c["signed_date"])
    if price is None:
        raise ApiError(ERR_SSP_NOT_FOUND, 422,
                       "no ACTIVE SspPrice covers (product_code, region) at the contract's signed_date")
    rec = make_rec(STORE.pobs, {
        "contract_id": contract_id,
        "pob_ref": pob_ref,
        "description": description,
        "product_code": product_code,
        "region": region,
        "recognition_pattern": pattern,
        "service_start_date": start.isoformat() if start else None,
        "service_end_date": end.isoformat() if end else None,
        "estimated_total_cost_cents": est_cost,
        "ssp_cents": price["ssp_cents"],
        "allocated_amount_cents": 0,
        "status": "PENDING",
        "satisfied_at": None,
    })
    return ok_object(ser.pob(rec), 201)


@bp.get("/revrec/contracts/<contract_id>/pobs")
def list_pobs(contract_id):
    require_roles(*ALL_READ)
    get_contract_or_404(contract_id)
    return ok_list([ser.pob(p) for p in svc.pobs_of(contract_id)], len(svc.pobs_of(contract_id)) or 1, 0,
                   len(svc.pobs_of(contract_id)))


@bp.get("/revrec/pobs/<pob_id>")
def get_pob(pob_id):
    require_roles(*ALL_READ)
    return ok_object(ser.pob(get_pob_or_404(pob_id)))


@bp.post("/revrec/pobs/<pob_id>/satisfy")
def satisfy_pob(pob_id):
    require_roles("RevenueAccountant")
    p = get_pob_or_404(pob_id)
    c = get_contract_or_404(p["contract_id"])
    require_active(c)
    if p["status"] not in ("PENDING", "IN_PROGRESS"):
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409,
                       "satisfy requires the obligation to be PENDING or IN_PROGRESS")
    svc.require_open_period(CLOCK.today())
    if p["recognition_pattern"] != "POINT_IN_TIME":
        raise ApiError(ERR_RECOGNITION_PATTERN_FORBIDDEN, 422,
                       "delivery acceptance applies only to POINT_IN_TIME obligations")
    remainder = p["allocated_amount_cents"] - svc.pob_recognized(pob_id)
    if remainder != 0:
        svc.post_entry(c, p, "RECOGNITION", "SATISFY", remainder, CLOCK.today())
    p["status"] = "SATISFIED"
    p["satisfied_at"] = now_ts()
    mark(p)
    svc.evaluate_auto_completion(c)
    return ok_object(ser.pob(p))


@bp.post("/revrec/pobs/<pob_id>/recognize")
def recognize_pob(pob_id):
    require_roles("RevenueAccountant")
    p = get_pob_or_404(pob_id)
    c = get_contract_or_404(p["contract_id"])
    require_active(c)
    svc.require_open_period(CLOCK.today())
    if p["recognition_pattern"] == "POINT_IN_TIME":
        raise ApiError(ERR_RECOGNITION_PATTERN_FORBIDDEN, 422,
                       "recognize applies only to over-time obligations")
    target = svc.recognition_target(p)
    recognized = svc.pob_recognized(pob_id)
    if target > recognized:
        svc.post_entry(c, p, "RECOGNITION", "RECOGNIZE", target - recognized, CLOCK.today())
    svc.maybe_satisfy_overtime(p)
    svc.evaluate_auto_completion(c)
    return ok_object(ser.pob(p))


@bp.post("/revrec/pobs/<pob_id>/cost-entries")
def create_cost_entry(pob_id):
    require_roles("RevenueAccountant")
    p = get_pob_or_404(pob_id)
    data = body()
    amount = req_int(data, "amount_cents")
    incurred = req_date(data, "incurred_date")
    memo = opt_str(data, "memo")
    c = get_contract_or_404(p["contract_id"])
    require_active(c)
    svc.require_open_period(incurred)
    if p["recognition_pattern"] != "OVER_TIME_INPUT_COST":
        raise ApiError(ERR_RECOGNITION_PATTERN_FORBIDDEN, 422,
                       "cost entries apply only to OVER_TIME_INPUT_COST obligations")
    if amount <= 0:
        raise ApiError(ERR_INVALID_AMOUNT, 422, "amount_cents must be > 0")
    rec = make_rec(STORE.cost_entries, {
        "pob_id": pob_id,
        "amount_cents": amount,
        "incurred_date": incurred.isoformat(),
        "memo": memo,
    }, lean=True)
    # Cost-driven recognition posts at the cost's incurred_date.
    target = svc.recognition_target(p)
    recognized = svc.pob_recognized(pob_id)
    if target > recognized:
        svc.post_entry(c, p, "RECOGNITION", "COST_ENTRY", target - recognized, incurred)
    svc.maybe_satisfy_overtime(p)
    svc.evaluate_auto_completion(c)
    return ok_object(ser.cost_entry(rec), 201)


@bp.get("/revrec/pobs/<pob_id>/cost-entries")
def list_cost_entries(pob_id):
    require_roles(*ALL_READ)
    get_pob_or_404(pob_id)
    items = sort_created([ce for ce in STORE.cost_entries.values() if ce["pob_id"] == pob_id])
    return ok_list([ser.cost_entry(ce) for ce in items], len(items) or 1, 0, len(items))
