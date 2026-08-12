"""Claim and claim-line endpoints."""

from flask import Blueprint, request

from db import stores
from errors import (
    raise_err, ERR_NOT_FOUND, ERR_INVALID_STATE, ERR_MEMBER_DISENROLLED,
    ERR_DUPLICATE_OUR_PLAN, ERR_NO_FINAL_PRIMACY, ERR_NO_VALID_ADJUSTMENT_CAUSE,
    ERR_NO_APPLIED_ADJUSTMENT,
)
from helpers import (
    base_record, touch, get_or_404, body, req_str, req_int, opt_int, paginate,
)
from middleware import require_roles
from response import success
from services.calculations import compute_claim_payment, primary_is_ours_for_determination

bp = Blueprint("claims", __name__)


@bp.route("/cob/claims", methods=["POST"])
def create_claim():
    require_roles("ClaimsExaminer")
    data = body()
    member_id = req_str(data, "member_id")
    provider_id = req_str(data, "provider_id")
    ext_id = req_str(data, "claim_external_id")
    service_date = req_str(data, "service_date")
    received_date = req_str(data, "received_date")
    total_billed = req_int(data, "total_billed_cents")

    member = stores["members"].get(member_id)
    if member is None:
        raise_err(ERR_NOT_FOUND, "member does not exist")
    provider = stores["providers"].get(provider_id)
    if provider is None:
        raise_err(ERR_NOT_FOUND, "provider does not exist")
    if member.get("status") != "ENROLLED":
        raise_err(ERR_MEMBER_DISENROLLED, "Operation requires Member.status == ENROLLED")
    for c in stores["claims"].values():
        if c.get("claim_external_id") == ext_id:
            raise_err(ERR_DUPLICATE_OUR_PLAN, "claim_external_id unique")

    rec = base_record()
    rec.update({
        "member_id": member_id,
        "provider_id": provider_id,
        "claim_external_id": ext_id,
        "service_date": service_date,
        "received_date": received_date,
        "total_billed_cents": total_billed,
        "total_allowed_cents": 0,
        "total_paid_cents": 0,
        "total_primary_paid_cents": 0,
        "primacy_determination_id": None,
        "rework_cycle_count": 0,
        "status": "RECEIVED",
    })
    stores["claims"][rec["id"]] = rec
    return success(rec, status=201)


@bp.route("/cob/claims/<cid>", methods=["GET"])
def get_claim(cid):
    require_roles("PlatformAdmin", "ClaimsExaminer", "RecoverySpecialist", "COBAnalyst", "COBAuditor")
    rec = get_or_404(stores["claims"], cid, "claim")
    return success(rec)


@bp.route("/cob/claims", methods=["GET"])
def list_claims():
    require_roles("PlatformAdmin", "ClaimsExaminer", "RecoverySpecialist", "COBAnalyst", "COBAuditor")
    items = list(stores["claims"].values())
    status = request.args.get("status")
    member_id = request.args.get("member_id")
    provider_id = request.args.get("provider_id")
    det_id = request.args.get("primacy_determination_id")
    if status:
        items = [c for c in items if c.get("status") == status]
    if member_id:
        items = [c for c in items if c.get("member_id") == member_id]
    if provider_id:
        items = [c for c in items if c.get("provider_id") == provider_id]
    if det_id:
        items = [c for c in items if c.get("primacy_determination_id") == det_id]
    return paginate(items)


@bp.route("/cob/claims/<cid>/lines", methods=["POST"])
def add_line(cid):
    require_roles("ClaimsExaminer")
    claim = get_or_404(stores["claims"], cid, "claim")
    data = body()
    line_number = req_int(data, "line_number")
    procedure_code = req_str(data, "procedure_code")
    billed = req_int(data, "billed_cents")
    allowed = req_int(data, "allowed_cents")
    primary_paid = opt_int(data, "primary_paid_cents", 0)
    rec = base_record()
    rec.update({
        "claim_id": cid,
        "line_number": line_number,
        "procedure_code": procedure_code,
        "billed_cents": billed,
        "allowed_cents": allowed,
        "primary_paid_cents": primary_paid if primary_paid is not None else 0,
        "paid_cents": 0,
    })
    stores["claim_lines"][rec["id"]] = rec
    return success(rec, status=201)


@bp.route("/cob/claims/<cid>/lines", methods=["GET"])
def list_lines(cid):
    require_roles("PlatformAdmin", "ClaimsExaminer", "RecoverySpecialist", "COBAnalyst", "COBAuditor")
    get_or_404(stores["claims"], cid, "claim")
    items = [l for l in stores["claim_lines"].values() if l.get("claim_id") == cid]
    return paginate(items)


def _final_determination_for(member_id, service_date):
    matches = [
        d for d in stores["determinations"].values()
        if d.get("member_id") == member_id
        and d.get("as_of_service_date") == service_date
        and d.get("status") == "FINALIZED"
    ]
    return matches


@bp.route("/cob/claims/<cid>/adjudicate", methods=["POST"])
def adjudicate_claim(cid):
    require_roles("ClaimsExaminer")
    claim = get_or_404(stores["claims"], cid, "claim")
    if claim.get("status") != "RECEIVED":
        raise_err(ERR_INVALID_STATE, "Claim is not in RECEIVED")
    member = stores["members"].get(claim["member_id"])
    if member is None or member.get("status") != "ENROLLED":
        raise_err(ERR_MEMBER_DISENROLLED, "Operation requires Member.status == ENROLLED")
    matches = _final_determination_for(claim["member_id"], claim["service_date"])
    if len(matches) != 1:
        raise_err(ERR_NO_FINAL_PRIMACY, "Claim adjudication requires exactly one FINALIZED PrimacyDetermination")
    det = matches[0]
    claim["primacy_determination_id"] = det["id"]
    compute_claim_payment(claim, primary_is_ours_for_determination(det))
    claim["status"] = "ADJUDICATED"
    touch(claim)
    touch(member)
    return success(claim)


@bp.route("/cob/claims/<cid>/pay", methods=["POST"])
def pay_claim(cid):
    require_roles("ClaimsExaminer")
    claim = get_or_404(stores["claims"], cid, "claim")
    if claim.get("status") != "ADJUDICATED":
        raise_err(ERR_INVALID_STATE, "Claim is not in ADJUDICATED")
    claim["status"] = "PAID"
    touch(claim)
    return success(claim)


REOPEN_CAUSES = ("NEW_COVERAGE_DISCOVERED", "PRIMACY_DETERMINATION_SUPERSEDED", "MSP_QUESTIONNAIRE_ADJUDICATED")


@bp.route("/cob/claims/<cid>/reopen", methods=["POST"])
def reopen_claim(cid):
    require_roles("RecoverySpecialist")
    claim = get_or_404(stores["claims"], cid, "claim")
    if claim.get("status") != "PAID":
        raise_err(ERR_INVALID_STATE, "Claim is not in PAID")
    found = False
    for adj in stores["adjustments"].values():
        if adj.get("claim_id") == cid and adj.get("cause") in REOPEN_CAUSES:
            found = True
            break
    if not found:
        raise_err(ERR_NO_VALID_ADJUSTMENT_CAUSE, "Claim reopen attempted without a triggering ClaimAdjustment")
    claim["status"] = "REOPENED"
    claim["rework_cycle_count"] = claim.get("rework_cycle_count", 0) + 1
    touch(claim)
    return success(claim)


@bp.route("/cob/claims/<cid>/readjudicate", methods=["POST"])
def readjudicate_claim(cid):
    require_roles("ClaimsExaminer")
    claim = get_or_404(stores["claims"], cid, "claim")
    if claim.get("status") != "REOPENED":
        raise_err(ERR_INVALID_STATE, "Claim is not in REOPENED")
    applied = [
        a for a in stores["adjustments"].values()
        if a.get("claim_id") == cid and a.get("status") == "APPLIED"
    ]
    if not applied:
        raise_err(ERR_NO_APPLIED_ADJUSTMENT, "Claim readjudication requires an APPLIED ClaimAdjustment")
    # Use the latest FINALIZED determination effective on service_date
    matches = _final_determination_for(claim["member_id"], claim["service_date"])
    if matches:
        det = matches[-1]
        claim["primacy_determination_id"] = det["id"]
        compute_claim_payment(claim, primary_is_ours_for_determination(det))
    claim["status"] = "READJUDICATED"
    touch(claim)
    return success(claim)


@bp.route("/cob/claims/<cid>/repay", methods=["POST"])
def repay_claim(cid):
    require_roles("ClaimsExaminer")
    claim = get_or_404(stores["claims"], cid, "claim")
    if claim.get("status") != "READJUDICATED":
        raise_err(ERR_INVALID_STATE, "Claim is not in READJUDICATED")
    claim["status"] = "REPAID"
    touch(claim)
    return success(claim)


@bp.route("/cob/claims/<cid>/close", methods=["POST"])
def close_claim(cid):
    require_roles("RecoverySpecialist")
    claim = get_or_404(stores["claims"], cid, "claim")
    if claim.get("status") != "REPAID":
        raise_err(ERR_INVALID_STATE, "Claim is not in REPAID")
    for rr in stores["recovery_requests"].values():
        if rr.get("claim_id") == cid and rr.get("status") not in ("FULLY_RECOVERED", "WRITTEN_OFF"):
            raise_err(ERR_INVALID_STATE, "All RecoveryRequest rows must be terminal")
    claim["status"] = "CLOSED"
    touch(claim)
    return success(claim)
