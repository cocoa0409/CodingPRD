"""Routes: dismissal, warrants, reinstatement, expungement referrals."""

from decimal import Decimal
from flask import Blueprint, request, g

from errors import ApiError
from auth import endpoint, ALL_ROLES
from store import db, now, base_fields, touch, serialize
from envelope import success, parse_pagination, list_response
import bodyutil as B
import calc
from domain import (account_of_case, diversion_of_case, plans_of_account,
                    warrants_of_case, recompute_account, recompute_assessed,
                    recompute_agreement)
from routes_core import get_case

bp_lifecycle = Blueprint("lifecycle", __name__)


def get_referral(rid):
    r = db.expungement_referrals.get(rid)
    if r is None:
        raise ApiError("ERR_EXPUNGEMENT_REFERRAL_NOT_FOUND", "expungement referral not found")
    return r


def get_amnesty(aid):
    a = db.amnesty_programs.get(aid)
    if a is None:
        raise ApiError("ERR_AMNESTY_PROGRAM_NOT_FOUND", "amnesty program not found")
    return a


# ---------------------------------------------------------------------------
# dismiss
# ---------------------------------------------------------------------------
@bp_lifecycle.post("/cases/<cid>/dismiss")
@endpoint(["Judge"])
def dismiss_case(cid):
    case = get_case(cid)
    if case["status"] != "COMPLIED":
        raise ApiError("ERR_INVALID_STATE", "case is not COMPLIED")
    agr = diversion_of_case(cid)
    if agr is None or agr["status"] != "COMPLETED":
        raise ApiError("ERR_DIVERSION_NOT_COMPLETE", "diversion agreement is not COMPLETED")
    case["status"] = "DISMISSED"
    touch(case)
    defendant = db.defendants[case["defendant_id"]]
    defendant["prior_diversion_count"] = defendant["prior_diversion_count"] + 1
    touch(defendant)
    acct = account_of_case(cid)
    if acct is not None and acct["status"] == "SETTLED":
        acct["status"] = "CLOSED"
        touch(acct, bump_version=False)
    return success(serialize(case), status=200)


# ---------------------------------------------------------------------------
# warrant (failure to comply)
# ---------------------------------------------------------------------------
@bp_lifecycle.post("/cases/<cid>/warrant")
@endpoint(["Judge"])
def issue_warrant(cid):
    case = get_case(cid)
    if case["status"] != "DIVERSION_GRANTED":
        raise ApiError("ERR_INVALID_STATE", "case is not DIVERSION_GRANTED")
    agr = diversion_of_case(cid)
    if agr is None or now() <= agr["program_deadline"]:
        raise ApiError("ERR_DEADLINE_NOT_PASSED", "program deadline has not passed")

    # cascade
    case["status"] = "FAILED_TO_COMPLY"
    touch(case)
    if agr["status"] in ("OFFERED", "IN_PROGRESS"):
        agr["status"] = "DEFAULTED"
        touch(agr)
    acct = account_of_case(cid)
    if acct is not None:
        for plan in plans_of_account(acct["id"]):
            if plan["status"] == "ACTIVE":
                plan["status"] = "DELINQUENT"
                touch(plan)
        acct["_penalty"] = calc.to_decimal(acct["_penalty"]) + calc.LATE_PENALTY
        recompute_account(acct)
        touch(acct, bump_version=False)

    warrant = base_fields()
    warrant.update({
        "case_id": cid,
        "reason": "Failure to comply with diversion agreement by the program deadline",
        "status": "ISSUED",
    })
    db.warrants[warrant["id"]] = warrant
    return success(serialize(warrant), status=201)


@bp_lifecycle.get("/cases/<cid>/warrants")
@endpoint(ALL_ROLES)
def list_warrants(cid):
    get_case(cid)
    limit, offset = parse_pagination(request.args)
    return list_response(warrants_of_case(cid), limit, offset, serialize)


# ---------------------------------------------------------------------------
# reinstate
# ---------------------------------------------------------------------------
@bp_lifecycle.post("/cases/<cid>/reinstate")
@endpoint(["Judge"])
def reinstate_case(cid):
    case = get_case(cid)
    if case["status"] != "FAILED_TO_COMPLY":
        raise ApiError("ERR_INVALID_STATE", "case is not FAILED_TO_COMPLY")
    body = B.get_body()
    program_id = body.get("amnesty_program_id")
    if not isinstance(program_id, str) or program_id == "":
        raise ApiError("ERR_VALIDATION", "'amnesty_program_id' is required")
    program = get_amnesty(program_id)
    if not (program["active_from"] <= now() < program["active_to"]):
        raise ApiError("ERR_AMNESTY_WINDOW_CLOSED", "amnesty window is closed")

    # cascade
    case["status"] = "DIVERSION_GRANTED"
    touch(case)
    agr = diversion_of_case(cid)
    if agr is not None and agr["status"] == "DEFAULTED":
        agr["status"] = "IN_PROGRESS"
        touch(agr)
    for w in warrants_of_case(cid):
        if w["status"] == "ISSUED":
            w["status"] = "RECALLED"
            touch(w)
    acct = account_of_case(cid)
    if acct is not None:
        waived, _ = calc.reinstatement_adjustment(
            acct["assessed_amount"], program["penalty_waiver_pct"], program["reinstatement_fee"])
        acct["_penalty"] = (calc.to_decimal(acct["_penalty"]) - waived
                            + calc.to_decimal(program["reinstatement_fee"]))
        recompute_account(acct)
        touch(acct, bump_version=False)
        for plan in plans_of_account(acct["id"]):
            if plan["status"] == "DELINQUENT":
                plan["status"] = "ACTIVE"
                touch(plan)
    if agr is not None:
        recompute_agreement(agr)
    return success(serialize(case), status=200)


# ---------------------------------------------------------------------------
# expungement referrals
# ---------------------------------------------------------------------------
@bp_lifecycle.get("/cases/<cid>/expungement-referrals")
@endpoint(ALL_ROLES)
def list_referrals(cid):
    get_case(cid)
    limit, offset = parse_pagination(request.args)
    items = [r for r in db.expungement_referrals.values() if r["case_id"] == cid]
    return list_response(items, limit, offset, serialize)


@bp_lifecycle.post("/expungement-referrals/<rid>/submit")
@endpoint(["CourtClerk"])
def submit_referral(rid):
    ref = get_referral(rid)
    case = db.cases[ref["case_id"]]
    if ref["status"] != "PENDING" or case["status"] != "DISMISSED":
        raise ApiError("ERR_INVALID_STATE", "referral cannot be submitted")
    ref["status"] = "SUBMITTED"
    touch(ref)
    return success(serialize(ref), status=200)
