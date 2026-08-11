"""Recovery request and reimbursement endpoints."""

from datetime import timedelta

from flask import Blueprint, request

from db import stores, now_dt, now_iso, iso_fmt
from errors import (
    raise_err, ERR_NOT_FOUND, ERR_INVALID_STATE, ERR_NO_OVERPAYMENT,
    ERR_OVERRECOVERY, ERR_NOT_PAST_DUE,
)
from helpers import base_record, touch, get_or_404, body, req_str, req_int, req_enum, paginate
from middleware import require_roles
from response import success
from services.calculations import active_config

bp = Blueprint("recovery", __name__)

METHODS = ("PROVIDER_REFUND_CHECK", "OFFSET_AGAINST_FUTURE_CLAIMS", "CARRIER_TO_CARRIER_TRANSFER")


def _get_nested_rr(cid, rid):
    get_or_404(stores["claims"], cid, "claim")
    rr = stores["recovery_requests"].get(rid)
    if rr is None or rr.get("claim_id") != cid:
        raise_err(ERR_NOT_FOUND, "recovery request does not exist or does not belong to claim")
    return rr


def _originating_overpayment(claim_id):
    """Overpayment from the claim's applied adjustments (latest)."""
    best = None
    for adj in stores["adjustments"].values():
        if adj.get("claim_id") == claim_id and adj.get("status") == "APPLIED":
            if best is None or adj.get("created_at", "") > best.get("created_at", ""):
                best = adj
    return best


@bp.route("/cob/claims/<cid>/recovery-requests", methods=["POST"])
def create_recovery_request(cid):
    require_roles("RecoverySpecialist")
    get_or_404(stores["claims"], cid, "claim")
    data = body()
    provider_id = req_str(data, "provider_id")
    amount = req_int(data, "amount_cents")
    provider = stores["providers"].get(provider_id)
    if provider is None:
        raise_err(ERR_NOT_FOUND, "provider does not exist")
    adj = _originating_overpayment(cid)
    overpayment = adj.get("overpayment_cents") if adj else 0
    if not overpayment or overpayment <= 0 or amount != overpayment:
        raise_err(ERR_NO_OVERPAYMENT, "RecoveryRequest requires an originating ClaimAdjustment with overpayment_cents > 0 and amount_cents == overpayment_cents")
    rec = base_record()
    rec.update({
        "claim_id": cid,
        "provider_id": provider_id,
        "amount_cents": amount,
        "issued_at": None,
        "due_date": None,
        "amount_recovered_cents": 0,
        "adjustment_id": adj["id"] if adj else None,
        "status": "DRAFT",
    })
    stores["recovery_requests"][rec["id"]] = rec
    return success(rec, status=201)


@bp.route("/cob/claims/<cid>/recovery-requests", methods=["GET"])
def list_recovery_requests(cid):
    require_roles("PlatformAdmin", "ClaimsExaminer", "RecoverySpecialist", "COBAuditor")
    get_or_404(stores["claims"], cid, "claim")
    items = [r for r in stores["recovery_requests"].values() if r.get("claim_id") == cid]
    status = request.args.get("status")
    if status:
        items = [r for r in items if r.get("status") == status]
    return paginate(items)


@bp.route("/cob/claims/<cid>/recovery-requests/<rid>", methods=["GET"])
def get_recovery_request(cid, rid):
    require_roles("PlatformAdmin", "ClaimsExaminer", "RecoverySpecialist", "COBAuditor")
    rr = _get_nested_rr(cid, rid)
    return success(rr)


@bp.route("/cob/claims/<cid>/recovery-requests/<rid>/issue", methods=["POST"])
def issue_recovery_request(cid, rid):
    require_roles("RecoverySpecialist")
    claim = get_or_404(stores["claims"], cid, "claim")
    rr = _get_nested_rr(cid, rid)
    if rr.get("status") != "DRAFT":
        raise_err(ERR_INVALID_STATE, "RecoveryRequest is not in DRAFT")
    if claim.get("status") != "REPAID":
        raise_err(ERR_INVALID_STATE, "claim.status must be REPAID")
    adj = _originating_overpayment(cid)
    overpayment = adj.get("overpayment_cents") if adj else 0
    if not overpayment or overpayment <= 0:
        raise_err(ERR_NO_OVERPAYMENT, "The originating ClaimAdjustment.overpayment_cents must be > 0")
    now = now_dt()
    config = active_config()
    window = config["recovery_window_days"] if config else 30
    rr["issued_at"] = iso_fmt(now)
    rr["due_date"] = iso_fmt(now + timedelta(days=window))
    rr["status"] = "ISSUED"
    touch(rr)
    return success(rr)


def _past_due_check(rr):
    if rr.get("due_date") is None:
        raise_err(ERR_NOT_PAST_DUE, "Recovery request has no due_date")
    from db import parse_iso
    if now_dt() <= parse_iso(rr["due_date"]) or rr.get("amount_recovered_cents", 0) >= rr.get("amount_cents", 0):
        raise_err(ERR_NOT_PAST_DUE, "Escalate or write-off requires current clock > due_date AND amount_recovered < amount_cents")


@bp.route("/cob/claims/<cid>/recovery-requests/<rid>/escalate", methods=["POST"])
def escalate_recovery_request(cid, rid):
    require_roles("RecoverySpecialist")
    get_or_404(stores["claims"], cid, "claim")
    rr = _get_nested_rr(cid, rid)
    if rr.get("status") not in ("ISSUED", "PARTIALLY_RECOVERED"):
        raise_err(ERR_INVALID_STATE, "RecoveryRequest is not in ISSUED or PARTIALLY_RECOVERED")
    _past_due_check(rr)
    rr["status"] = "ESCALATED"
    touch(rr)
    return success(rr)


@bp.route("/cob/claims/<cid>/recovery-requests/<rid>/write-off", methods=["POST"])
def write_off_recovery_request(cid, rid):
    require_roles("RecoverySpecialist")
    get_or_404(stores["claims"], cid, "claim")
    rr = _get_nested_rr(cid, rid)
    if rr.get("status") not in ("ISSUED", "PARTIALLY_RECOVERED"):
        raise_err(ERR_INVALID_STATE, "RecoveryRequest is not in ISSUED or PARTIALLY_RECOVERED")
    _past_due_check(rr)
    rr["status"] = "WRITTEN_OFF"
    touch(rr)
    return success(rr)


# ---- Reimbursements ----

@bp.route("/cob/claims/<cid>/recovery-requests/<rid>/reimbursements", methods=["POST"])
def post_reimbursement(cid, rid):
    require_roles("RecoverySpecialist")
    get_or_404(stores["claims"], cid, "claim")
    rr = _get_nested_rr(cid, rid)
    if rr.get("status") not in ("ISSUED", "PARTIALLY_RECOVERED"):
        raise_err(ERR_INVALID_STATE, "RecoveryRequest is not in ISSUED or PARTIALLY_RECOVERED")
    data = body()
    amount = req_int(data, "amount_cents")
    method = req_enum(data, "method", METHODS)
    remaining = rr.get("amount_cents", 0) - rr.get("amount_recovered_cents", 0)
    if amount > remaining:
        raise_err(ERR_OVERRECOVERY, "Reimbursement.amount_cents exceeds remaining unrecovered balance")

    # Reimbursement is an immutable ledger posting: id + created_at only
    rec = {
        "id": base_record(common=False)["id"],
        "created_at": now_iso(),
        "recovery_request_id": rid,
        "amount_cents": amount,
        "received_at": now_iso(),
        "method": method,
    }
    stores["reimbursements"][rec["id"]] = rec

    rr["amount_recovered_cents"] = rr.get("amount_recovered_cents", 0) + amount
    if rr["amount_recovered_cents"] >= rr["amount_cents"]:
        rr["amount_recovered_cents"] = rr["amount_cents"]
        rr["status"] = "FULLY_RECOVERED"
    else:
        rr["status"] = "PARTIALLY_RECOVERED"
    touch(rr)
    return success(rec, status=201)


@bp.route("/cob/claims/<cid>/recovery-requests/<rid>/reimbursements", methods=["GET"])
def list_reimbursements(cid, rid):
    require_roles("PlatformAdmin", "ClaimsExaminer", "RecoverySpecialist", "COBAuditor")
    _get_nested_rr(cid, rid)
    items = [r for r in stores["reimbursements"].values() if r.get("recovery_request_id") == rid]
    return paginate(items)


# ---- Top-level reverse-lookup endpoints ----

@bp.route("/cob/recovery-requests/<rid>", methods=["GET"])
def get_recovery_request_top(rid):
    require_roles("PlatformAdmin", "ClaimsExaminer", "RecoverySpecialist", "COBAuditor")
    rr = get_or_404(stores["recovery_requests"], rid, "recovery request")
    return success(rr)


@bp.route("/cob/recovery-requests", methods=["GET"])
def list_recovery_requests_top():
    require_roles("PlatformAdmin", "ClaimsExaminer", "RecoverySpecialist", "COBAuditor")
    items = list(stores["recovery_requests"].values())
    status = request.args.get("status")
    claim_id = request.args.get("claim_id")
    provider_id = request.args.get("provider_id")
    if status:
        items = [r for r in items if r.get("status") == status]
    if claim_id:
        items = [r for r in items if r.get("claim_id") == claim_id]
    if provider_id:
        items = [r for r in items if r.get("provider_id") == provider_id]
    return paginate(items)


@bp.route("/cob/reimbursements/<rid>", methods=["GET"])
def get_reimbursement_top(rid):
    require_roles("PlatformAdmin", "ClaimsExaminer", "RecoverySpecialist", "COBAuditor")
    rec = get_or_404(stores["reimbursements"], rid, "reimbursement")
    return success(rec)


@bp.route("/cob/reimbursements", methods=["GET"])
def list_reimbursements_top():
    require_roles("PlatformAdmin", "ClaimsExaminer", "RecoverySpecialist", "COBAuditor")
    items = list(stores["reimbursements"].values())
    rrid = request.args.get("recovery_request_id")
    if rrid:
        items = [r for r in items if r.get("recovery_request_id") == rrid]
    return paginate(items)
