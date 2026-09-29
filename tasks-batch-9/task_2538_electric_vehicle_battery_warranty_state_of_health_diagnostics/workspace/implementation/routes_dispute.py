"""Capacity disputes: independent verification and the remedy reversal edges."""
from datetime import timedelta

from flask import Blueprint

import calc
import cascade
import claim_service as svc
from common import (API_PREFIX, ApiError, D, R_ADJ, R_LAB, R_OWNER, READ_ROLES,
                    auth, claim_disputes, db, forbidden, get_body, must, new_record,
                    now, ok, opt_str, req_dec, req_int, req_str, touch)

bp = Blueprint("dispute", __name__, url_prefix=API_PREFIX)

DISPUTABLE = ("APPROVED_MODULE", "APPROVED_PACK", "APPROVED_SOFTWARE", "DENIED", "FULFILLED")
OPEN_DISPUTES = ("LAB_ASSIGNED", "LAB_RESULT_RECEIVED")


@bp.route("/capacity-disputes", methods=["POST"])
def create_dispute():
    role, user_id = auth((R_OWNER,))
    body = get_body()
    claim_id = req_str(body, "claim_id")
    lab_name = req_str(body, "lab_name")
    statement = req_str(body, "owner_statement")
    expected_version = req_int(body, "expected_claim_version", minimum=0)
    claim = must("claims", claim_id)
    if user_id != claim["vehicle_id"]:
        raise forbidden("X-User-ID must equal the claim's vehicle_id.")
    if expected_version != claim["version"]:
        raise ApiError("ERR_STALE_CLAIM_VERSION", 412,
                       "expected_claim_version does not match the claim.")
    if claim["adjudication_status"] not in DISPUTABLE:
        raise ApiError("ERR_CLAIM_NOT_DISPUTABLE", 409,
                       "The claim is not in a disputable state.")
    program = svc.program_of(claim)
    adjudicated_at = claim.get("_adjudicated_at")
    if adjudicated_at is not None:
        deadline = adjudicated_at + timedelta(days=program["dispute_window_days"])
        if now() > deadline:
            raise ApiError("ERR_DISPUTE_WINDOW_EXPIRED", 409,
                           "The dispute window on this claim has closed.")
    for existing in claim_disputes(claim_id):
        if existing["dispute_status"] in OPEN_DISPUTES:
            raise ApiError("ERR_DUPLICATE_ACTIVE_DISPUTE", 409,
                           "An unresolved dispute already exists on this claim.")
    assessment = svc.assessment_of(claim)
    record = new_record()
    record.update({
        "claim_id": claim_id,
        "lab_name": lab_name,
        "owner_statement": statement,
        "nominal_basis_kwh": assessment["nominal_basis_kwh"],
        "oem_retention_pct": assessment["retention_pct"],
        "lab_measured_capacity_kwh": None,
        "lab_retention_pct": None,
        "deviation_pct": None,
        "retest_count": 0,
        "dispute_status": "LAB_ASSIGNED",
        "resolution_note": None,
        "resolved_by_user_id": None,
    })
    db.disputes[record["id"]] = record
    touch(claim)
    return ok(record, 201)


@bp.route("/capacity-disputes/<dispute_id>", methods=["GET"])
def get_dispute(dispute_id):
    auth(READ_ROLES)
    return ok(must("disputes", dispute_id))


@bp.route("/capacity-disputes/<dispute_id>/lab-result", methods=["POST"])
def lab_result(dispute_id):
    auth((R_LAB,))
    body = get_body()
    measured = req_dec(body, "lab_measured_capacity_kwh", 3, minimum=0)
    opt_str(body, "lab_report_reference")
    dispute = must("disputes", dispute_id)
    if dispute["dispute_status"] not in OPEN_DISPUTES:
        raise ApiError("ERR_DISPUTE_RESOLVED", 409,
                       "The dispute is resolved and accepts no further result.")
    claim = db.claims[dispute["claim_id"]]
    program = svc.program_of(claim)
    lab_retention, deviation = calc.lab_deviation(dispute["nominal_basis_kwh"], measured,
                                                  dispute["oem_retention_pct"])
    dispute["lab_measured_capacity_kwh"] = measured
    dispute["lab_retention_pct"] = lab_retention
    dispute["deviation_pct"] = deviation
    tolerance = D(program["lab_tolerance_pct"])
    beyond = deviation is not None and abs(D(deviation)) > tolerance
    if beyond and dispute["retest_count"] == 0:
        # A materially deviating first measurement must be confirmed by exactly
        # one mandatory retest before it can move a remedy.
        dispute["retest_count"] = 1
    else:
        dispute["dispute_status"] = "LAB_RESULT_RECEIVED"
    touch(dispute)
    return ok(dispute)


# ============================================================ remedy reversals
def _overturn(claim, program):
    status = claim["adjudication_status"]
    if status == "DENIED":
        claim["adjudication_status"] = "SUBMITTED"
        claim["reopened_count"] = claim["reopened_count"] + 1
        claim["approved_remedy"] = None
        claim["denial_reason"] = None
        claim["adjudicated_by_user_id"] = None
        touch(claim)
    elif status == "APPROVED_MODULE":
        center = svc.center_of(claim)
        removed = svc.pack_of(claim)
        chosen = calc.select_replacement_pack(program, center, removed)
        if chosen is None:
            raise ApiError("ERR_NO_REMAN_PACK_AVAILABLE", 409,
                           "No eligible replacement pack is available to escalate to.")
        fields = svc.compute_settlement(claim, "PACK_REPLACEMENT", chosen)
        claim["adjudication_status"] = "APPROVED_PACK"
        claim["approved_remedy"] = "PACK_REPLACEMENT"
        claim["replacement_pack_id"] = chosen["id"]
        svc.reserve_pack(chosen)
        svc.write_settlement(claim, fields)
        touch(claim)


def _downgrade(claim, program):
    status = claim["adjudication_status"]
    if status == "APPROVED_PACK":
        svc.release_reserved_pack(claim)
        claim["replacement_pack_id"] = None
        fields = svc.compute_settlement(claim, "MODULE_REPLACEMENT", None)
        claim["adjudication_status"] = "APPROVED_MODULE"
        claim["approved_remedy"] = "MODULE_REPLACEMENT"
        svc.write_settlement(claim, fields)
        touch(claim)
    elif status == "APPROVED_MODULE":
        claim["adjudication_status"] = "DENIED"
        claim["denial_reason"] = "DISPUTE_DOWNGRADE"
        # The administration fee and the proration factor stand: only the four
        # cost figures collapse on a dispute-driven denial.
        svc.zero_money(claim, include_admin_fee=False, reset_proration=False)
        touch(claim)


@bp.route("/capacity-disputes/<dispute_id>/resolve", methods=["POST"])
def resolve_dispute(dispute_id):
    role, user_id = auth((R_ADJ,), actor_required=True)
    body = get_body()
    note = req_str(body, "resolution_note")
    dispute = must("disputes", dispute_id)
    if dispute["dispute_status"] not in OPEN_DISPUTES:
        raise ApiError("ERR_DISPUTE_RESOLVED", 409, "The dispute is already resolved.")
    if dispute["dispute_status"] != "LAB_RESULT_RECEIVED":
        raise ApiError("ERR_LAB_RESULT_REQUIRED", 409,
                       "A laboratory result is required before resolution.")
    claim = db.claims[dispute["claim_id"]]
    if claim["adjudicated_by_user_id"] is not None and user_id == claim["adjudicated_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES", 403,
                       "The adjudicator who decided the claim may not resolve its dispute.")
    program = svc.program_of(claim)
    outcome = calc.dispute_outcome(dispute["deviation_pct"], program["lab_tolerance_pct"])
    if outcome == "RESOLVED_OVERTURNED":
        _overturn(claim, program)
    elif outcome == "RESOLVED_DOWNGRADED":
        _downgrade(claim, program)
    dispute["dispute_status"] = outcome
    dispute["resolution_note"] = note
    dispute["resolved_by_user_id"] = user_id
    touch(dispute)
    cascade.refresh_accrual(program)
    return ok(dispute)
