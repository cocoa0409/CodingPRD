"""UnderpaymentCase endpoints (PRD §3.7)."""

from flask import Blueprint, request

import db as _db
from errors import (
    err_not_found,
    err_invalid_state,
    err_invalid_request,
    err_sod_write_off,
    err_write_off_amount_mismatch,
    err_write_off_cap_exceeded,
)
from middleware import require_roles, ALL_ROLES
from response import success_object, success_list, parse_pagination
from services.serializers import serialize_case
from services.validation import body, reject_unknown, as_int, as_str
from services.cases import compute_case_ledger
from services.pricing import touch

bp = Blueprint("cases", __name__)

WRITE_OFF_DIRECTOR_CAP_CENTS = 250000

CASE_STATUSES = {
    "QUEUED", "UNDER_REVIEW", "APPEAL_L1", "APPEAL_L2", "MEDIATION",
    "ARBITRATION", "RECOVERED", "DENIED_FINAL", "WRITTEN_OFF", "WITHDRAWN",
}


@bp.get("/api/underpayment-cases/<cid>")
def get_case(cid):
    require_roles(ALL_ROLES)
    case = _db.store.cases.get(cid)
    if case is None:
        raise err_not_found("UnderpaymentCase not found")
    return success_object(serialize_case(case))


@bp.get("/api/underpayment-cases")
def list_cases():
    require_roles(ALL_ROLES)
    limit, offset = parse_pagination(request.args)
    claim_id = request.args.get("claim_id")
    payer_id = request.args.get("payer_id")
    contract_id = request.args.get("contract_id")
    status = request.args.get("status")
    escalation_level = request.args.get("escalation_level")
    if status is not None and status not in CASE_STATUSES:
        raise err_invalid_request("status filter invalid")
    if escalation_level is not None:
        try:
            escalation_level = int(escalation_level)
        except (TypeError, ValueError):
            raise err_invalid_request("escalation_level filter must be an integer")
    items = list(_db.store.cases.values())
    if claim_id is not None:
        items = [c for c in items if c["claim_id"] == claim_id]
    if payer_id is not None:
        items = [c for c in items if c["payer_id"] == payer_id]
    if contract_id is not None:
        items = [c for c in items if c.get("contract_id") == contract_id]
    if status is not None:
        items = [c for c in items if c["status"] == status]
    if escalation_level is not None:
        items = [c for c in items if c["escalation_level"] == escalation_level]
    items.sort(key=lambda c: c["seq"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serialize_case(c) for c in page], limit, offset, total)


def _get_case_or_404(cid):
    case = _db.store.cases.get(cid)
    if case is None:
        raise err_not_found("UnderpaymentCase not found")
    return case


@bp.post("/api/underpayment-cases/<cid>/pick_up")
def pick_up_case(cid):
    user_id, _ = require_roles(["RevenueIntegrityAnalyst", "RecoveryManager"])
    case = _get_case_or_404(cid)
    if case["status"] != "QUEUED":
        raise err_invalid_state("Only a QUEUED case may be picked up")
    case["status"] = "UNDER_REVIEW"
    case["claimed_by_user_id"] = user_id
    touch(case)
    return success_object(serialize_case(case))


@bp.post("/api/underpayment-cases/<cid>/write_off")
def write_off_case(cid):
    user_id, _ = require_roles(["FinanceDirector"])
    case = _get_case_or_404(cid)
    data = body()
    reject_unknown(data, {"amount_cents", "reason"})
    amount_cents = as_int(data, "amount_cents", required=True, min_value=0)
    reason = as_str(data, "reason")

    # State (rung 6): only from UNDER_REVIEW
    if case["status"] != "UNDER_REVIEW":
        raise err_invalid_state("Only an UNDER_REVIEW case may be written off")
    ledger = compute_case_ledger(case)
    # SoD (rung 7)
    if case.get("claimed_by_user_id") is not None and case["claimed_by_user_id"] == user_id:
        raise err_sod_write_off()
    # Uniqueness/consistency (rung 10): full-balance only
    if amount_cents != ledger["current_outstanding_cents"]:
        raise err_write_off_amount_mismatch()
    # Money guards (rung 11)
    if ledger["current_outstanding_cents"] > WRITE_OFF_DIRECTOR_CAP_CENTS:
        raise err_write_off_cap_exceeded()

    case["write_off_amount_cents"] = amount_cents
    case["status"] = "WRITTEN_OFF"
    touch(case)
    return success_object(serialize_case(case))


@bp.post("/api/underpayment-cases/<cid>/withdraw")
def withdraw_case(cid):
    require_roles(["RevenueIntegrityAnalyst", "RecoveryManager"])
    case = _get_case_or_404(cid)
    if case["status"] not in {"QUEUED", "UNDER_REVIEW"}:
        raise err_invalid_state("Only a QUEUED or UNDER_REVIEW case may be withdrawn")
    case["status"] = "WITHDRAWN"
    touch(case)
    return success_object(serialize_case(case))
