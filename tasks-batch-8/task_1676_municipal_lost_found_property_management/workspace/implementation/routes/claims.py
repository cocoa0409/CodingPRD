"""Ownership claims: filing, scoring, examination (PRD 3.4)."""
from flask import Blueprint

from db import db
from errors import (
    raise_error, ERR_FORBIDDEN, ERR_INVALID_STATE, ERR_STALE_ITEM_VERSION,
    ERR_ITEM_NOT_CLAIMABLE, ERR_CLAIM_PROOF_INSUFFICIENT, ERR_SEGREGATION_OF_DUTIES,
)
from middleware import authorized
from response import success_object, success_list
from services import core
from validate import (
    get_body, req_str, req_bool, req_enum, req_int, opt_str,
    require_path, require_ref, pagination_params, opt_query_enum, opt_query_str,
    paginate,
)

bp = Blueprint("claims", __name__)

CLAIM_READERS = {"ClaimsExaminer", "ReleaseOfficer", "PoliceLiaison", "ProgramAdmin", "Claimant"}
EXAMINER = {"ClaimsExaminer"}
CLAIMANT = {"Claimant"}


def _check_claimant_owns(caller, claim):
    if caller.role == "Claimant" and claim["claimant_id"] != caller.user_id:
        raise_error(ERR_FORBIDDEN, "Claimant may only access its own claims")


@bp.post("/claims")
def file_claim():
    body = get_body()
    item_id = req_str(body, "item_id")
    claimant_id = req_str(body, "claimant_id")
    proof_serial = req_bool(body, "proof_serial")
    proof_photo = req_bool(body, "proof_photo")
    proof_receipt = req_bool(body, "proof_receipt")
    proof_description_detail = req_enum(body, "proof_description_detail", core.PROOF_DETAILS)
    expected_item_version = req_int(body, "expected_item_version")
    caller = authorized(CLAIMANT)
    # Claimant ownership: body claimant_id must equal X-User-ID (PRD 2.1).
    if claimant_id != caller.user_id:
        raise_error(ERR_FORBIDDEN, "claimant_id must equal the caller's X-User-ID")
    item = require_ref("items", item_id, "item_id")
    claimant = require_ref("claimants", claimant_id, "claimant_id")
    # OCC on the Item (PRD 2.6) — evaluated before the claimability check (3.4).
    if expected_item_version != item["version"]:
        raise_error(ERR_STALE_ITEM_VERSION,
                    "expected_item_version does not match the item's current version")
    if item["status"] not in ("STORED", "LISTED"):
        raise_error(ERR_ITEM_NOT_CLAIMABLE,
                    "claims may only be filed against STORED or LISTED items")
    proofs = {
        "proof_serial": proof_serial,
        "proof_photo": proof_photo,
        "proof_receipt": proof_receipt,
        "proof_description_detail": proof_description_detail,
    }
    claim = core.new_record("claims", {
        "item_id": item_id,
        "claimant_id": claimant_id,
        "status": "SUBMITTED",
        "proof_serial": proof_serial,
        "proof_photo": proof_photo,
        "proof_receipt": proof_receipt,
        "proof_description_detail": proof_description_detail,
        "proof_score": core.compute_proof_score(proofs, claimant),
        "examiner_id": None,
        "decision_reason": None,
        "pre_stay_status": None,
        "info_request_text": None,
    })
    # Filing itself advances the item's version (PRD 3.4).
    core.touch(item)
    return success_object(claim, 201)


@bp.get("/claims")
def list_claims():
    limit, offset = pagination_params()
    item_id = opt_query_str("item_id")
    claimant_id = opt_query_str("claimant_id")
    status = opt_query_enum("status", core.CLAIM_STATUSES)
    caller = authorized(CLAIM_READERS)
    recs = list(db["claims"].values())
    if caller.role == "Claimant":
        recs = [r for r in recs if r["claimant_id"] == caller.user_id]
    if item_id is not None:
        recs = [r for r in recs if r["item_id"] == item_id]
    if claimant_id is not None:
        recs = [r for r in recs if r["claimant_id"] == claimant_id]
    if status is not None:
        recs = [r for r in recs if r["status"] == status]
    page, total = paginate(recs, limit, offset)
    return success_list(page, total, limit, offset)


@bp.get("/claims/<claim_id>")
def get_claim(claim_id):
    caller = authorized(CLAIM_READERS)
    claim = require_path("claims", claim_id)
    _check_claimant_owns(caller, claim)
    return success_object(claim)


@bp.post("/claims/<claim_id>/start-review")
def start_review(claim_id):
    caller = authorized(EXAMINER)
    claim = require_path("claims", claim_id)
    if claim["status"] != "SUBMITTED":
        raise_error(ERR_INVALID_STATE, "only a SUBMITTED claim can enter review")
    claim["examiner_id"] = caller.user_id
    claim["status"] = "UNDER_REVIEW"
    core.touch(claim)
    return success_object(claim)


@bp.post("/claims/<claim_id>/request-info")
def request_info(claim_id):
    body = get_body()
    info_request_text = req_str(body, "info_request_text")
    caller = authorized(EXAMINER)
    claim = require_path("claims", claim_id)
    # Examiner-ownership precedes state admissibility (PRD 2.7 step 2, 3.4).
    if claim["examiner_id"] != caller.user_id:
        raise_error(ERR_FORBIDDEN, "only the recording examiner may request info")
    if claim["status"] != "UNDER_REVIEW":
        raise_error(ERR_INVALID_STATE, "only an UNDER_REVIEW claim can request info")
    claim["info_request_text"] = info_request_text
    claim["status"] = "INFO_REQUESTED"
    core.touch(claim)
    return success_object(claim)


@bp.post("/claims/<claim_id>/resubmit")
def resubmit(claim_id):
    body = get_body()
    proof_serial = req_bool(body, "proof_serial")
    proof_photo = req_bool(body, "proof_photo")
    proof_receipt = req_bool(body, "proof_receipt")
    proof_description_detail = req_enum(body, "proof_description_detail", core.PROOF_DETAILS)
    caller = authorized(CLAIMANT)
    claim = require_path("claims", claim_id)
    if claim["claimant_id"] != caller.user_id:
        raise_error(ERR_FORBIDDEN, "only the owning claimant may resubmit")
    if claim["status"] != "INFO_REQUESTED":
        raise_error(ERR_INVALID_STATE, "only an INFO_REQUESTED claim can be resubmitted")
    claim["proof_serial"] = proof_serial
    claim["proof_photo"] = proof_photo
    claim["proof_receipt"] = proof_receipt
    claim["proof_description_detail"] = proof_description_detail
    claimant = db["claimants"].get(claim["claimant_id"])
    claim["proof_score"] = core.compute_proof_score(claim, claimant)
    claim["status"] = "SUBMITTED"
    core.touch(claim)
    return success_object(claim)


@bp.post("/claims/<claim_id>/approve")
def approve(claim_id):
    body = get_body()
    decision_reason = opt_str(body, "decision_reason", None)
    caller = authorized(EXAMINER)
    claim = require_path("claims", claim_id)
    # Fixed order (PRD 3.4): examiner-ownership -> state admissibility ->
    # proof sufficiency -> duty segregation.
    if claim["examiner_id"] != caller.user_id:
        raise_error(ERR_FORBIDDEN, "only the recording examiner may approve")
    if claim["status"] != "UNDER_REVIEW":
        raise_error(ERR_INVALID_STATE, "only an UNDER_REVIEW claim can be approved")
    item = db["items"].get(claim["item_id"])
    if item is None or item["status"] not in ("STORED", "LISTED"):
        raise_error(ERR_INVALID_STATE,
                    "the claimed item must be STORED or LISTED to approve")
    claimant = db["claimants"].get(claim["claimant_id"])
    threshold = core.PROOF_THRESHOLDS[item["value_tier"]]
    if claim["proof_score"] < threshold or (
        item["value_tier"] == "HIGH" and not (claimant and claimant["id_verified"])
    ):
        raise_error(ERR_CLAIM_PROOF_INSUFFICIENT,
                    "proof score below the tier threshold or HIGH tier without verified ID")
    if caller.user_id == item["intake_officer_id"]:
        raise_error(ERR_SEGREGATION_OF_DUTIES,
                    "approving examiner may not be the item's intake officer")
    if decision_reason is not None:
        claim["decision_reason"] = decision_reason
    claim["status"] = "APPROVED"
    core.touch(claim)
    item["status"] = "RELEASE_PENDING"
    core.touch(item)
    # Auto-reject every other open claim on the item (3.4).
    for other in db["claims"].values():
        if other["id"] == claim["id"] or other["item_id"] != item["id"]:
            continue
        if other["status"] in ("SUBMITTED", "UNDER_REVIEW", "INFO_REQUESTED"):
            other["status"] = "REJECTED"
            other["decision_reason"] = "ITEM_AWARDED"
            core.touch(other)
    return success_object(claim)


@bp.post("/claims/<claim_id>/reject")
def reject(claim_id):
    body = get_body()
    decision_reason = req_str(body, "decision_reason")
    caller = authorized(EXAMINER)
    claim = require_path("claims", claim_id)
    if claim["examiner_id"] != caller.user_id:
        raise_error(ERR_FORBIDDEN, "only the recording examiner may reject")
    if claim["status"] != "UNDER_REVIEW":
        raise_error(ERR_INVALID_STATE, "only an UNDER_REVIEW claim can be rejected")
    claim["decision_reason"] = decision_reason
    claim["status"] = "REJECTED"
    core.touch(claim)
    return success_object(claim)


@bp.post("/claims/<claim_id>/withdraw")
def withdraw(claim_id):
    caller = authorized(CLAIMANT)
    claim = require_path("claims", claim_id)
    if claim["claimant_id"] != caller.user_id:
        raise_error(ERR_FORBIDDEN, "only the owning claimant may withdraw")
    if claim["status"] not in ("SUBMITTED", "INFO_REQUESTED"):
        raise_error(ERR_INVALID_STATE,
                    "only a SUBMITTED or INFO_REQUESTED claim can be withdrawn")
    claim["status"] = "WITHDRAWN"
    core.touch(claim)
    return success_object(claim)
