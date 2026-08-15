"""Operational failure case endpoints."""
from datetime import date

from flask import Blueprint, request

import db
from errors import (
    ERR_PLAN_NOT_ACTIVE,
    ERR_ACCOUNT_CLOSED,
    ERR_FAILURE_STATE_INVALID,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_CORRECTION_WINDOW_EXPIRED,
    ERR_CROSS_PLAN_REFERENCE,
    raise_err,
)
from middleware import user_context, require_role
from response import ok_object
from routes.plans import _list_response
from services.core import (
    body,
    req_date,
    req_int,
    req_enum,
    opt_string,
    get_or_404,
    stamp_new,
    touch,
)
from util import CLOCK, fmt_date, parse_date, round_half_up_div

bp = Blueprint("operational_failures", __name__)

FAILURE_TYPES = {"EARLY_PAYMENT", "LATE_PAYMENT", "EXCESS_DEFERRAL", "IMPROPER_ACCELERATION"}

UNDERPAYMENT_RATE_BP = 700
PREMIUM_RATE_BP = 100
EXCISE_TAX_BP = 2000


def failure_view(f):
    return {
        "id": f["id"],
        "created_at": f["created_at"],
        "updated_at": f["updated_at"],
        "version": f["version"],
        "account_id": f["account_id"],
        "distribution_request_id": f["distribution_request_id"],
        "participant_id": f["participant_id"],
        "failure_type": f["failure_type"],
        "failure_date": f["failure_date"],
        "amount_cents": f["amount_cents"],
        "reported_by_user_id": f["reported_by_user_id"],
        "correction_credit_cents": f["correction_credit_cents"],
        "includible_base_cents": f["includible_base_cents"],
        "premium_interest_cents": f["premium_interest_cents"],
        "additional_tax_cents": f["additional_tax_cents"],
        "total_inclusion_cents": f["total_inclusion_cents"],
        "correction_deadline": f["correction_deadline"],
        "status": f["status"],
        "assessed_by_user_id": f["assessed_by_user_id"],
        "description": f["description"],
    }


@bp.post("/api/operational-failures")
def create_failure():
    data = body()
    from errors import ERR_INVALID_REQUEST

    account_id = data.get("account_id")
    if not isinstance(account_id, str) or not account_id:
        raise_err(ERR_INVALID_REQUEST, "account_id is required and must be a string")
    failure_type = req_enum(data, "failure_type", FAILURE_TYPES)
    failure_date = req_date(data, "failure_date")
    amount = req_int(data, "amount_cents", lo=1)
    dist_req_id = data.get("distribution_request_id")
    if dist_req_id is not None and (not isinstance(dist_req_id, str) or not dist_req_id):
        raise_err(ERR_INVALID_REQUEST, "distribution_request_id must be a string")
    description = opt_string(data, "description")

    if failure_date > CLOCK.date():
        raise_err(ERR_INVALID_REQUEST, "failure_date may not lie in the future")

    user_id, role = user_context()
    require_role(role, {"BenefitsAdministrator"})
    account = get_or_404(db.accounts, account_id, "Account")
    plan = db.plans[account["plan_id"]]
    if plan["status"] != "ACTIVE":
        raise_err(ERR_PLAN_NOT_ACTIVE, "Plan must be ACTIVE to report an operational failure")

    if dist_req_id is not None:
        dist = get_or_404(db.distribution_requests, dist_req_id, "DistributionRequest")
        if dist["account_id"] != account_id:
            raise_err(ERR_CROSS_PLAN_REFERENCE, "distribution_request must belong to the same account")

    failure = stamp_new(
        {
            "account_id": account_id,
            "distribution_request_id": dist_req_id,
            "participant_id": account["participant_id"],
            "failure_type": failure_type,
            "failure_date": fmt_date(failure_date),
            "amount_cents": amount,
            "reported_by_user_id": user_id,
            "correction_credit_cents": None,
            "includible_base_cents": None,
            "premium_interest_cents": None,
            "additional_tax_cents": None,
            "total_inclusion_cents": None,
            "correction_deadline": fmt_date(date(failure_date.year + 2, 12, 31)),
            "status": "IDENTIFIED",
            "assessed_by_user_id": None,
            "description": description,
        }
    )
    db.operational_failures[failure["id"]] = failure
    return ok_object(failure_view(failure), 201)


@bp.get("/api/operational-failures")
def list_failures():
    user_context()
    items = list(db.operational_failures.values())
    for f in ("account_id", "distribution_request_id", "participant_id"):
        v = request.args.get(f)
        if v is not None:
            items = [x for x in items if x[f] == v]
    return _list_response([failure_view(f) for f in items], request.args)


@bp.get("/api/operational-failures/<failureId>")
def get_failure(failureId):
    user_context()
    f = get_or_404(db.operational_failures, failureId, "OperationalFailureCase")
    return ok_object(failure_view(f))


@bp.post("/api/operational-failures/<failureId>/quantify")
def quantify_failure(failureId):
    data = body()
    credit = req_int(data, "correction_credit_cents", lo=0)

    user_id, role = user_context()
    require_role(role, {"ComplianceOfficer"})
    f = get_or_404(db.operational_failures, failureId, "OperationalFailureCase")

    if f["status"] != "IDENTIFIED":
        raise_err(ERR_FAILURE_STATE_INVALID, "quantify requires IDENTIFIED")
    if credit > f["amount_cents"]:
        from errors import ERR_INVALID_REQUEST

        raise_err(ERR_INVALID_REQUEST, "correction_credit_cents may not exceed amount_cents")

    # Pinned five-step order
    base = max(0, f["amount_cents"] - credit)
    days_outstanding = (CLOCK.date() - parse_date(f["failure_date"])).days
    interest = round_half_up_div(base * (UNDERPAYMENT_RATE_BP + PREMIUM_RATE_BP) * days_outstanding, 10000 * 365)
    tax = round_half_up_div(base * EXCISE_TAX_BP, 10000)
    total = base + interest + tax

    f["correction_credit_cents"] = credit
    f["includible_base_cents"] = base
    f["premium_interest_cents"] = interest
    f["additional_tax_cents"] = tax
    f["total_inclusion_cents"] = total
    f["status"] = "QUANTIFIED"
    touch(f)
    return ok_object(failure_view(f))


@bp.post("/api/operational-failures/<failureId>/assess-inclusion")
def assess_failure(failureId):
    body()
    user_id, role = user_context()
    require_role(role, {"ComplianceOfficer"})
    f = get_or_404(db.operational_failures, failureId, "OperationalFailureCase")

    if f["status"] != "QUANTIFIED":
        raise_err(ERR_FAILURE_STATE_INVALID, "assess-inclusion requires QUANTIFIED")
    if user_id == f["reported_by_user_id"]:
        raise_err(ERR_SEGREGATION_OF_DUTIES, "Assessor must differ from the reporter")
    account = db.accounts[f["account_id"]]
    if account["status"] not in ("ACTIVE", "FLAGGED_FOR_INCLUSION"):
        raise_err(ERR_ACCOUNT_CLOSED, "Account is CLOSED")

    participant = db.participants[f["participant_id"]]
    participant["inclusion_liability_cents"] += f["total_inclusion_cents"]
    touch(participant)
    if account["status"] == "ACTIVE":
        account["status"] = "FLAGGED_FOR_INCLUSION"
        touch(account)

    f["assessed_by_user_id"] = user_id
    f["status"] = "INCLUSION_ASSESSED"
    touch(f)
    return ok_object(failure_view(f))


@bp.post("/api/operational-failures/<failureId>/correct")
def correct_failure(failureId):
    body()
    user_id, role = user_context()
    require_role(role, {"ComplianceOfficer"})
    f = get_or_404(db.operational_failures, failureId, "OperationalFailureCase")

    if f["status"] not in ("QUANTIFIED", "INCLUSION_ASSESSED"):
        raise_err(ERR_FAILURE_STATE_INVALID, "correct requires QUANTIFIED or INCLUSION_ASSESSED")
    if CLOCK.date() > parse_date(f["correction_deadline"]):
        raise_err(ERR_CORRECTION_WINDOW_EXPIRED, "Correction deadline has passed")

    was_assessed = f["status"] == "INCLUSION_ASSESSED"
    if was_assessed:
        participant = db.participants[f["participant_id"]]
        participant["inclusion_liability_cents"] -= f["total_inclusion_cents"]
        touch(participant)

    f["status"] = "CORRECTED"
    touch(f)

    account = db.accounts[f["account_id"]]
    remaining = [
        x
        for x in db.operational_failures.values()
        if x["account_id"] == account["id"] and x["id"] != f["id"] and x["status"] in ("QUANTIFIED", "INCLUSION_ASSESSED")
    ]
    if not remaining and account["status"] == "FLAGGED_FOR_INCLUSION":
        account["status"] = "ACTIVE"
        touch(account)

    return ok_object(failure_view(f))
