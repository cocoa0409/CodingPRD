"""Disbursement routes (PRD §3.9). Disbursements are created only by cascades;
the client may fetch one or void an APPROVED one (compensating action).
"""
from flask import Blueprint

import db
import serializers as S
from auth import authenticate, authorize
from errors import err
from helpers import require_resource
from response import success
from services import calc

bp = Blueprint("disbursements", __name__)


@bp.route("/disbursements/<did>", methods=["GET"])
def get_disbursement(did):
    principal = authenticate()
    authorize(principal, {"ClaimsSupervisor", "ClaimsAdjuster", "SubrogationSpecialist"})
    rec = require_resource(db.disbursements, did, "disbursement")
    return success(S.disbursement(rec), status=200)


@bp.route("/disbursements/<did>/void", methods=["POST"])
def void_disbursement(did):
    principal = authenticate()
    authorize(principal, {"ClaimsSupervisor"})
    disb = require_resource(db.disbursements, did, "disbursement")
    if disb["status"] != "APPROVED":
        raise err("ERR_INVALID_STATE", "disbursement is not APPROVED")

    # Hop 1: VOIDED (drops out of the APPROVED sum).
    disb["status"] = "VOIDED"
    db.touch(disb)
    # Hop 2: recompute parent Claim.total_disbursed_cents.
    claim = db.claims.get(disb["claim_id"])
    if claim is not None:
        calc.refresh_claim_ledger(claim)
    return success(S.disbursement(disb), status=200)
