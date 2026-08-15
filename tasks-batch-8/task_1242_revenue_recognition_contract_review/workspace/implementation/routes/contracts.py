from datetime import date

from flask import Blueprint, request

from db import STORE, make_rec, mark, sort_created
from errors import (ApiError, ERR_INVALID_REQUEST, ERR_NOT_FOUND,
                    ERR_INVALID_STATE_TRANSITION, ERR_REVIEW_OUTSTANDING,
                    ERR_COMBINATION_WINDOW_EXCEEDED, ERR_COMBINATION_CRITERIA_NOT_MET)
from response import ok_object, ok_list
import serializers as ser
import services as svc
from validate import (require_roles, body, req_str, req_int, req_enum, req_date,
                      opt_bool, pagination)

bp = Blueprint("contracts", __name__)

RISK_TIERS = {"STANDARD", "ELEVATED", "HIGH"}
ALL_READ = ("RevenueAccountant", "RevenueManager", "ContractReviewer", "Controller")
PRE_APPROVAL = ("DRAFT", "IN_REVIEW", "CHANGES_REQUESTED")
COMBINATION_WINDOW_DAYS = 30


def get_contract_or_404(contract_id):
    c = STORE.contracts.get(contract_id)
    if c is None:
        raise ApiError(ERR_NOT_FOUND, 404, "contract_id does not identify an existing contract")
    return c


@bp.post("/revrec/contracts")
def create_contract():
    require_roles("RevenueAccountant")
    data = body()
    customer_id = req_str(data, "customer_id")
    contract_ref = req_str(data, "contract_ref")
    signed = req_date(data, "signed_date")
    fixed = req_int(data, "fixed_consideration_cents")
    risk = req_enum(data, "risk_tier", RISK_TIERS)
    package_flag = opt_bool(data, "package_negotiated_flag", False)
    if fixed < 0:
        raise ApiError(ERR_INVALID_REQUEST, 400, "fixed_consideration_cents must be >= 0")
    if customer_id not in STORE.customers:
        raise ApiError(ERR_INVALID_REQUEST, 400, "customer_id does not reference an existing customer")
    for c in STORE.contracts.values():
        if c["contract_ref"] == contract_ref:
            raise ApiError(ERR_INVALID_REQUEST, 400, "contract_ref must be unique per contract")
    rec = make_rec(STORE.contracts, {
        "customer_id": customer_id,
        "contract_ref": contract_ref,
        "signed_date": signed.isoformat(),
        "risk_tier": risk,
        "package_negotiated_flag": package_flag,
        "combined_into_contract_id": None,
        "fixed_consideration_cents": fixed,
        "vc_estimate_cents": 0,
        "active_vc_estimate_id": None,
        "status": "DRAFT",
        "completed_at": None,
    })
    return ok_object(ser.contract(rec), 201)


@bp.get("/revrec/contracts/<contract_id>")
def get_contract(contract_id):
    require_roles(*ALL_READ)
    return ok_object(ser.contract(get_contract_or_404(contract_id)))


@bp.get("/revrec/contracts")
def list_contracts():
    require_roles(*ALL_READ)
    limit, offset = pagination()
    items = list(STORE.contracts.values())
    for f in ("customer_id", "status", "combined_into_contract_id"):
        v = request.args.get(f)
        if v is not None:
            items = [c for c in items if str(c.get(f)) == v]
    items = sort_created(items)
    total = len(items)
    page = items[offset:offset + limit]
    return ok_list([ser.contract(c) for c in page], limit, offset, total)


@bp.post("/revrec/contracts/<contract_id>/submit")
def submit_contract(contract_id):
    require_roles("RevenueAccountant")
    c = get_contract_or_404(contract_id)
    if c["status"] not in ("DRAFT", "CHANGES_REQUESTED"):
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409,
                       "submit requires the contract to be DRAFT or CHANGES_REQUESTED")
    if not svc.pobs_of(contract_id):
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409,
                       "submit requires at least one performance obligation")
    c["status"] = "IN_REVIEW"
    mark(c)
    for cl in sort_created([x for x in STORE.clauses.values() if x["contract_id"] == contract_id]):
        if cl["is_non_standard"] and cl["status"] == "PENDING_REVIEW":
            make_rec(STORE.review_tasks, {
                "contract_id": contract_id,
                "clause_id": cl["id"],
                "status": "ASSIGNED",
                "reviewer_user_id": None,
                "recommendation": None,
                "recommended_by_user_id": None,
                "decision": None,
                "decided_by_user_id": None,
                "note": None,
            })
    return ok_object(ser.contract(c))


@bp.post("/revrec/contracts/<contract_id>/return")
def return_contract(contract_id):
    require_roles("RevenueManager")
    c = get_contract_or_404(contract_id)
    data = body()
    req_str(data, "reason")
    if c["status"] != "IN_REVIEW":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409, "return requires the contract to be IN_REVIEW")
    c["status"] = "CHANGES_REQUESTED"
    mark(c)
    return ok_object(ser.contract(c))


@bp.post("/revrec/contracts/<contract_id>/approve")
def approve_contract(contract_id):
    require_roles("RevenueManager")
    c = get_contract_or_404(contract_id)
    if c["status"] != "IN_REVIEW":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409, "approve requires the contract to be IN_REVIEW")
    for cl in STORE.clauses.values():
        if cl["contract_id"] == contract_id and cl["status"] != "APPROVED":
            raise ApiError(ERR_REVIEW_OUTSTANDING, 409,
                           "every contract clause must be APPROVED before the contract can be approved")
    tx = c["fixed_consideration_cents"] + c["vc_estimate_cents"]
    svc.run_full_allocation(c, tx)
    c["status"] = "APPROVED"
    mark(c)
    return ok_object(ser.contract(c))


@bp.post("/revrec/contracts/<contract_id>/activate")
def activate_contract(contract_id):
    require_roles("RevenueManager")
    c = get_contract_or_404(contract_id)
    if c["status"] != "APPROVED":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409, "activate requires the contract to be APPROVED")
    c["status"] = "ACTIVE"
    mark(c)
    return ok_object(ser.contract(c))


@bp.post("/revrec/contracts/<contract_id>/hold")
def hold_contract(contract_id):
    require_roles("RevenueManager")
    c = get_contract_or_404(contract_id)
    if c["status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409, "hold requires the contract to be ACTIVE")
    c["status"] = "ON_HOLD"
    mark(c)
    return ok_object(ser.contract(c))


@bp.post("/revrec/contracts/<contract_id>/resume")
def resume_contract(contract_id):
    require_roles("RevenueManager")
    c = get_contract_or_404(contract_id)
    if c["status"] != "ON_HOLD":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409, "resume requires the contract to be ON_HOLD")
    c["status"] = "ACTIVE"
    mark(c)
    return ok_object(ser.contract(c))


@bp.post("/revrec/contracts/<contract_id>/cancel")
def cancel_contract(contract_id):
    require_roles("RevenueAccountant")
    c = get_contract_or_404(contract_id)
    data = body()
    req_str(data, "reason")
    if c["status"] not in ("DRAFT", "IN_REVIEW", "CHANGES_REQUESTED"):
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409,
                       "cancel requires the contract to be DRAFT, IN_REVIEW, or CHANGES_REQUESTED")
    c["status"] = "CANCELLED"
    mark(c)
    for p in svc.pobs_of(contract_id):
        if p["status"] in ("PENDING", "IN_PROGRESS"):
            p["status"] = "CANCELLED"
            mark(p)
    return ok_object(ser.contract(c))


@bp.post("/revrec/contracts/<contract_id>/absorb")
def absorb_contract(contract_id):
    require_roles("RevenueManager")
    survivor = get_contract_or_404(contract_id)
    data = body()
    absorbed_id = req_str(data, "absorbed_contract_id")
    absorbed = STORE.contracts.get(absorbed_id)
    if absorbed is None or absorbed_id == contract_id:
        raise ApiError(ERR_INVALID_REQUEST, 400, "absorbed_contract_id does not reference another existing contract")
    if survivor["status"] not in PRE_APPROVAL or absorbed["status"] not in PRE_APPROVAL:
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409,
                       "absorb requires both contracts to be DRAFT, IN_REVIEW, or CHANGES_REQUESTED")
    gap = abs((date.fromisoformat(survivor["signed_date"]) - date.fromisoformat(absorbed["signed_date"])).days)
    if gap > COMBINATION_WINDOW_DAYS:
        raise ApiError(ERR_COMBINATION_WINDOW_EXCEEDED, 409,
                       "signed dates of survivor and absorbed differ by more than 30 days")
    if survivor["customer_id"] != absorbed["customer_id"] or not (
            survivor["package_negotiated_flag"] or absorbed["package_negotiated_flag"]):
        raise ApiError(ERR_COMBINATION_CRITERIA_NOT_MET, 422,
                       "combination requires the same customer and at least one package-negotiated contract")
    absorbed["status"] = "ABSORBED"
    absorbed["combined_into_contract_id"] = contract_id
    mark(absorbed)
    for p in svc.pobs_of(absorbed_id):
        p["contract_id"] = contract_id
        mark(p)
    survivor["fixed_consideration_cents"] += absorbed["fixed_consideration_cents"]
    mark(survivor)
    return ok_object(ser.contract(survivor))


@bp.get("/revrec/contracts/<contract_id>/rollforward")
def rollforward(contract_id):
    require_roles(*ALL_READ)
    c = get_contract_or_404(contract_id)
    period_id = request.args.get("accounting_period_id")
    if not period_id:
        raise ApiError(ERR_INVALID_REQUEST, 400, "query parameter 'accounting_period_id' is required")
    period = STORE.periods.get(period_id)
    if period is None:
        raise ApiError(ERR_NOT_FOUND, 404, "accounting_period_id does not identify an existing period")
    p_start = date.fromisoformat(period["start_date"])
    p_end = date.fromisoformat(period["end_date"])

    # Billed movements: +amount at invoice_date on issue; -amount at the
    # void's clock date on void.
    billed_movs = []
    for inv in STORE.invoices.values():
        if inv["contract_id"] != contract_id:
            continue
        billed_movs.append((date.fromisoformat(inv["invoice_date"]), inv["amount_cents"]))
        if inv["status"] == "VOIDED" and inv.get("_voided_date"):
            billed_movs.append((inv["_voided_date"], -inv["amount_cents"]))

    entries = [e for e in STORE.entries.values() if e["contract_id"] == contract_id]

    beginning_billed = sum(a for d, a in billed_movs if d < p_start)
    billed_in = sum(a for d, a in billed_movs if p_start <= d < p_end)
    beginning_recognized = sum(e["amount_cents"] for e in entries
                               if date.fromisoformat(e["posting_date"]) < p_start)
    recognized_in = sum(e["amount_cents"] for e in entries
                        if p_start <= date.fromisoformat(e["posting_date"]) < p_end)
    catch_up = sum(e["amount_cents"] for e in entries
                   if e["entry_type"] == "CATCH_UP_ADJUSTMENT"
                   and p_start <= date.fromisoformat(e["posting_date"]) < p_end)
    reversal = sum(e["amount_cents"] for e in entries
                   if e["entry_type"] == "REVERSAL"
                   and p_start <= date.fromisoformat(e["posting_date"]) < p_end)

    ending_billed = beginning_billed + billed_in
    ending_recognized = beginning_recognized + recognized_in
    return ok_object({
        "contract_id": contract_id,
        "accounting_period_id": period_id,
        "beginning_billed_cents": beginning_billed,
        "beginning_recognized_cents": beginning_recognized,
        "billed_cents": billed_in,
        "recognized_cents": recognized_in,
        "catch_up_cents": catch_up,
        "reversal_cents": reversal,
        "ending_billed_cents": ending_billed,
        "ending_recognized_cents": ending_recognized,
        "ending_deferred_revenue_cents": max(0, ending_billed - ending_recognized),
        "ending_contract_asset_cents": max(0, ending_recognized - ending_billed),
    })
