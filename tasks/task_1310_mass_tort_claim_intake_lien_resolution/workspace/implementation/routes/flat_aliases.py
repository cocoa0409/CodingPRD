"""Flat alias endpoints for reverse-reachability GETs.

Both nested and flat shapes must be supported; they return the same resources.
"""

from flask import Blueprint, request

import db
from errors import ApiError, ERR_NOT_FOUND
from middleware import require_role
from response import success_envelope
from routes.helpers import (
    get_pagination,
    paginate,
    sort_by_created_at,
)

bp = Blueprint("flat_aliases", __name__)

ALL_ROLES = (
    "ProgramAdministrator",
    "IntakeSpecialist",
    "RecordsAnalyst",
    "LienAnalyst",
    "DisbursementApprover",
    "ClaimantRole",
)

NON_CLAIMANT_READ = (
    "ProgramAdministrator",
    "IntakeSpecialist",
    "RecordsAnalyst",
    "LienAnalyst",
    "DisbursementApprover",
)


# ------------------------------------------------------------------
# Flat single-resource reads
# ------------------------------------------------------------------

@bp.route("/settlement-programs/claimants/<rid>", methods=["GET"])
def flat_get_claimant(rid):
    user_id, role = require_role(*ALL_ROLES)
    obj = db.claimants.get(rid)
    if obj is None:
        raise ApiError(ERR_NOT_FOUND, "Claimant not found", 404)
    if role == "ClaimantRole" and user_id != rid:
        raise ApiError(ERR_NOT_FOUND, "Claimant not found", 404)
    return success_envelope(obj, 200, "object")


@bp.route("/settlement-programs/claims/<rid>", methods=["GET"])
def flat_get_claim(rid):
    user_id, role = require_role(*ALL_ROLES)
    obj = db.claims.get(rid)
    if obj is None:
        raise ApiError(ERR_NOT_FOUND, "Claim not found", 404)
    if role == "ClaimantRole" and user_id != obj["claimant_id"]:
        raise ApiError(ERR_NOT_FOUND, "Claim not found", 404)
    return success_envelope(obj, 200, "object")


@bp.route("/settlement-programs/tier-matrices/<rid>", methods=["GET"])
def flat_get_tier_matrix(rid):
    user_id, role = require_role(*NON_CLAIMANT_READ)
    obj = db.tier_matrices.get(rid)
    if obj is None:
        raise ApiError(ERR_NOT_FOUND, "TierMatrix not found", 404)
    return success_envelope(obj, 200, "object")


@bp.route("/settlement-programs/medical-records/<rid>", methods=["GET"])
def flat_get_medical_record(rid):
    user_id, role = require_role(
        "ProgramAdministrator", "IntakeSpecialist", "RecordsAnalyst", "LienAnalyst"
    )
    obj = db.medical_records.get(rid)
    if obj is None:
        raise ApiError(ERR_NOT_FOUND, "MedicalRecord not found", 404)
    return success_envelope(obj, 200, "object")


@bp.route("/settlement-programs/liens/<rid>", methods=["GET"])
def flat_get_lien(rid):
    user_id, role = require_role(
        "ProgramAdministrator", "LienAnalyst", "DisbursementApprover", "ClaimantRole"
    )
    obj = db.liens.get(rid)
    if obj is None:
        raise ApiError(ERR_NOT_FOUND, "Lien not found", 404)
    if role == "ClaimantRole":
        claim = db.claims.get(obj["claim_id"])
        if claim and user_id != claim["claimant_id"]:
            raise ApiError(ERR_NOT_FOUND, "Lien not found", 404)
    return success_envelope(obj, 200, "object")


@bp.route("/settlement-programs/appeals/<rid>", methods=["GET"])
def flat_get_appeal(rid):
    user_id, role = require_role(
        "ProgramAdministrator", "IntakeSpecialist", "LienAnalyst", "ClaimantRole"
    )
    obj = db.appeals.get(rid)
    if obj is None:
        raise ApiError(ERR_NOT_FOUND, "Appeal not found", 404)
    if role == "ClaimantRole":
        claim = db.claims.get(obj["claim_id"])
        if claim and user_id != claim["claimant_id"]:
            raise ApiError(ERR_NOT_FOUND, "Appeal not found", 404)
    return success_envelope(obj, 200, "object")


@bp.route("/settlement-programs/disbursements/<rid>", methods=["GET"])
def flat_get_disbursement(rid):
    user_id, role = require_role(
        "ProgramAdministrator", "DisbursementApprover", "ClaimantRole"
    )
    obj = db.disbursements.get(rid)
    if obj is None:
        raise ApiError(ERR_NOT_FOUND, "Disbursement not found", 404)
    if role == "ClaimantRole":
        claim = db.claims.get(obj["claim_id"])
        if claim and user_id != claim["claimant_id"]:
            raise ApiError(ERR_NOT_FOUND, "Disbursement not found", 404)
    return success_envelope(obj, 200, "object")


@bp.route("/settlement-programs/closing-statements/<rid>", methods=["GET"])
def flat_get_closing_statement(rid):
    user_id, role = require_role(
        "ProgramAdministrator", "DisbursementApprover", "ClaimantRole"
    )
    obj = db.closing_statements.get(rid)
    if obj is None:
        raise ApiError(ERR_NOT_FOUND, "ClosingStatement not found", 404)
    if role == "ClaimantRole":
        claim = db.claims.get(obj["claim_id"])
        if claim and user_id != claim["claimant_id"]:
            raise ApiError(ERR_NOT_FOUND, "ClosingStatement not found", 404)
    return success_envelope(obj, 200, "object")


# ------------------------------------------------------------------
# Flat list aliases
# ------------------------------------------------------------------

@bp.route("/settlement-programs/claimants", methods=["GET"])
def flat_list_claimants():
    user_id, role = require_role(*NON_CLAIMANT_READ)
    limit, offset = get_pagination()
    items = list(db.claimants.values())

    sp = request.args.get("settlement_program_id")
    if sp:
        items = [c for c in items if c["settlement_program_id"] == sp]
    dup = request.args.get("duplicate_of_claimant_id")
    if dup:
        items = [c for c in items if c.get("duplicate_of_claimant_id") == dup]

    items = sort_by_created_at(items)
    page, meta = paginate(items, limit, offset)
    return success_envelope(page, 200, "array", meta)


@bp.route("/settlement-programs/claims", methods=["GET"])
def flat_list_claims():
    user_id, role = require_role(*NON_CLAIMANT_READ)
    limit, offset = get_pagination()
    items = list(db.claims.values())

    sp = request.args.get("settlement_program_id")
    if sp:
        items = [c for c in items if c["settlement_program_id"] == sp]
    cl = request.args.get("claimant_id")
    if cl:
        items = [c for c in items if c["claimant_id"] == cl]
    aa = request.args.get("active_appeal_id")
    if aa:
        items = [c for c in items if c.get("active_appeal_id") == aa]
    st = request.args.get("status")
    if st:
        items = [c for c in items if c["status"] == st]

    items = sort_by_created_at(items)
    page, meta = paginate(items, limit, offset)
    return success_envelope(page, 200, "array", meta)


@bp.route("/settlement-programs/tier-matrices", methods=["GET"])
def flat_list_tier_matrices():
    user_id, role = require_role(*NON_CLAIMANT_READ)
    limit, offset = get_pagination()
    items = list(db.tier_matrices.values())

    sp = request.args.get("settlement_program_id")
    if sp:
        items = [t for t in items if t["settlement_program_id"] == sp]
    ms = request.args.get("matrix_state")
    if ms:
        items = [t for t in items if t["matrix_state"] == ms]

    items = sort_by_created_at(items)
    page, meta = paginate(items, limit, offset)
    return success_envelope(page, 200, "array", meta)


@bp.route("/settlement-programs/medical-records", methods=["GET"])
def flat_list_medical_records():
    user_id, role = require_role(
        "ProgramAdministrator", "IntakeSpecialist", "RecordsAnalyst", "LienAnalyst"
    )
    limit, offset = get_pagination()
    items = list(db.medical_records.values())

    ci = request.args.get("claim_id")
    if ci:
        items = [r for r in items if r["claim_id"] == ci]
    rs = request.args.get("review_state")
    if rs:
        items = [r for r in items if r["review_state"] == rs]

    items = sort_by_created_at(items)
    page, meta = paginate(items, limit, offset)
    return success_envelope(page, 200, "array", meta)


@bp.route("/settlement-programs/liens", methods=["GET"])
def flat_list_liens():
    user_id, role = require_role(
        "ProgramAdministrator", "LienAnalyst", "DisbursementApprover", "ClaimantRole"
    )
    limit, offset = get_pagination()
    items = list(db.liens.values())

    ci = request.args.get("claim_id")
    if ci:
        items = [l for l in items if l["claim_id"] == ci]
    st = request.args.get("state")
    if st:
        items = [l for l in items if l["state"] == st]
    lt = request.args.get("lien_type")
    if lt:
        items = [l for l in items if l["lien_type"] == lt]

    items = sort_by_created_at(items)
    page, meta = paginate(items, limit, offset)
    return success_envelope(page, 200, "array", meta)


@bp.route("/settlement-programs/appeals", methods=["GET"])
def flat_list_appeals():
    user_id, role = require_role(
        "ProgramAdministrator", "IntakeSpecialist", "LienAnalyst", "ClaimantRole"
    )
    limit, offset = get_pagination()
    items = list(db.appeals.values())

    ci = request.args.get("claim_id")
    if ci:
        items = [a for a in items if a["claim_id"] == ci]
    atm = request.args.get("appealed_tier_matrix_id")
    if atm:
        items = [a for a in items if a["appealed_tier_matrix_id"] == atm]
    rtm = request.args.get("requested_tier_matrix_id")
    if rtm:
        items = [a for a in items if a["requested_tier_matrix_id"] == rtm]
    st = request.args.get("state")
    if st:
        items = [a for a in items if a["state"] == st]

    items = sort_by_created_at(items)
    page, meta = paginate(items, limit, offset)
    return success_envelope(page, 200, "array", meta)


@bp.route("/settlement-programs/disbursements", methods=["GET"])
def flat_list_disbursements():
    user_id, role = require_role(
        "ProgramAdministrator", "DisbursementApprover", "ClaimantRole"
    )
    limit, offset = get_pagination()
    items = list(db.disbursements.values())

    ci = request.args.get("claim_id")
    if ci:
        items = [d for d in items if d["claim_id"] == ci]
    st = request.args.get("state")
    if st:
        items = [d for d in items if d["state"] == st]

    items = sort_by_created_at(items)
    page, meta = paginate(items, limit, offset)
    return success_envelope(page, 200, "array", meta)


@bp.route("/settlement-programs/closing-statements", methods=["GET"])
def flat_list_closing_statements():
    user_id, role = require_role(
        "ProgramAdministrator", "DisbursementApprover", "ClaimantRole"
    )
    limit, offset = get_pagination()
    items = list(db.closing_statements.values())

    ci = request.args.get("claim_id")
    if ci:
        items = [s for s in items if s["claim_id"] == ci]

    items = sort_by_created_at(items)
    page, meta = paginate(items, limit, offset)
    return success_envelope(page, 200, "array", meta)
