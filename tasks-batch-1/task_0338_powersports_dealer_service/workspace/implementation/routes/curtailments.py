"""Curtailments (PRD 3.2): append-only principal paydown ledger lines with OCC."""

from flask import Blueprint, request

import errors
import calculations as calc
from common import get_body, stamp_new, serialize, touch, paginate, as_int, as_str, as_enum
from db import db
from lookups import get_loan, get_curtailment
from middleware import get_user_context, require_role
from response import ok, ok_list

bp = Blueprint("curtailments", __name__)

REASONS = {"SCHEDULED", "SALE_PAYOFF", "VOLUNTARY"}


@bp.route("/curtailments", methods=["POST"])
def create_curtailment():
    _, role = get_user_context()
    require_role(role, {"DealerPrincipal"})
    body = get_body()

    # existence (404) — floor_plan_loan_id is the only FK
    loan_id = as_str(body, "floor_plan_loan_id")
    loan = get_loan(loan_id)

    # request well-formed (422)
    principal = as_int(body, "principal_cents")
    if principal <= 0:
        errors.err(errors.ERR_INVALID_REQUEST, "principal_cents must be > 0")
    reason = as_enum(body, "reason", REASONS, required=False, default="SCHEDULED")
    expected_version = as_int(body, "expected_floor_plan_loan_version")

    # OCC (412)
    if expected_version != loan["version"]:
        errors.err(errors.ERR_STALE_LOAN_VERSION, "FloorPlanLoan version is stale")

    # business constraints (422) by reason
    if reason == "SALE_PAYOFF":
        if principal != loan["principal_outstanding_cents"]:
            errors.err(errors.ERR_PAYOFF_NOT_FULL, "SALE_PAYOFF must equal outstanding principal")
    elif reason == "SCHEDULED":
        if loan["status"] == "CURTAILMENT_DUE":
            required = calc.required_scheduled_curtailment(loan)
            if principal < required:
                errors.err(errors.ERR_CURTAILMENT_INSUFFICIENT, "Scheduled curtailment below required minimum")

    # create the curtailment (append-only, always POSTED)
    rec = stamp_new({
        "floor_plan_loan_id": loan_id,
        "principal_cents": principal,
        "reason": reason,
        "status": "POSTED",
    }, common=False)
    db.curtailments[rec["id"]] = rec

    # mutate the loan
    loan["principal_outstanding_cents"] = max(loan["principal_outstanding_cents"] - principal, 0)
    loan["cumulative_curtailment_cents"] = loan.get("cumulative_curtailment_cents", 0) + principal

    if reason == "SALE_PAYOFF" and loan["principal_outstanding_cents"] == 0:
        loan["status"] = "PAID_OFF"
        loan["principal_outstanding_cents"] = 0
    elif reason == "SCHEDULED" and loan["status"] == "CURTAILMENT_DUE":
        loan["status"] = "OPEN"

    touch(loan)
    return ok(serialize(rec), 201)


@bp.route("/curtailments", methods=["GET"])
def list_curtailments():
    _, role = get_user_context()
    require_role(role, {"DealerPrincipal", "FinanceManager"})
    loan_id = request.args.get("floor_plan_loan_id")
    records = [c for c in db.curtailments.values()
               if loan_id is None or c["floor_plan_loan_id"] == loan_id]
    items, limit, offset, total = paginate(records)
    return ok_list(items, limit, offset, total)


@bp.route("/curtailments/<cid>", methods=["GET"])
def get_curtailment_route(cid):
    _, role = get_user_context()
    require_role(role, {"DealerPrincipal", "FinanceManager"})
    rec = get_curtailment(cid)
    return ok(serialize(rec), 200)
