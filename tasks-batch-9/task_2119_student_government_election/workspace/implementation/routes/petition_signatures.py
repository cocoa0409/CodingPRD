"""Nominating-petition signature endpoints (PRD 3.3)."""
from flask import Blueprint

import auth
import calc
import cascades
import constants
import db
import errors
import listing
import lookup
import response
import serialize
import validation

bp = Blueprint("petition_signatures", __name__)


@bp.post("/petition-signatures")
def create_signature():
    auth.require(constants.STUDENT_VOTER)
    body = validation.get_body()

    # rule 4 — body foreign keys, in input-list order
    candidacy = lookup.fk_candidacy(body)
    signer = lookup.fk_student(body, "signer_student_id")

    # rule 5 — schema
    validation.req_str(body, "candidacy_id")
    signer_student_id = validation.req_str(body, "signer_student_id")
    signed_at = validation.req_dt(body, "signed_at")

    # rule 7 — ownership
    auth.require_owner(signer_student_id)

    election = db.store.elections[candidacy["election_id"]]

    # rule 9 — the parent candidacy's posture
    if candidacy["status"] in constants.CANDIDACY_CLOSED_FOR_LEDGER:
        errors.fail(errors.ERR_INVALID_STATE,
                    "This candidacy may no longer collect signatures.")
    # rule 10 — election phase
    if election["status"] != "PETITIONING":
        errors.fail(errors.ERR_ELECTION_PHASE_INVALID,
                    "Signatures may only be added while the election is PETITIONING.")
    # rule 14 — petition timing
    if not db.now() < election["petition_deadline"]:
        errors.fail(errors.ERR_PETITION_DEADLINE_PASSED,
                    "The petition deadline has passed.")
    # rule 22 — one non-voided signature per signer per candidacy
    for existing in lookup.signatures_of(candidacy["id"]):
        if existing["signer_student_id"] == signer["id"] and existing["status"] != "VOIDED":
            errors.fail(errors.ERR_DUPLICATE_SIGNATURE,
                        "This signer already holds a live signature on this petition.")
    # rule 23 — a candidate may not sign their own petition
    if signer["id"] == candidacy["student_id"]:
        errors.fail(errors.ERR_SELF_SIGNATURE,
                    "A candidate may not sign their own petition.")

    row = db.new_row(db.store.petition_signatures, {
        "candidacy_id": candidacy["id"],
        "signer_student_id": signer["id"],
        "signed_at": signed_at,
        "status": "SUBMITTED",
        "eligibility_result": "UNKNOWN",
        "reject_reason": None,
        "verified_by_user_id": None,
    })
    calc.recompute_petition_counters(candidacy)
    return response.object_response(serialize.signature(row), 201)


@bp.get("/petition-signatures")
def list_signatures():
    auth.require_any()
    rows = listing.filtered(db.store.petition_signatures, {
        "candidacy_id": ("candidacy_id", None),
        "signer_student_id": ("signer_student_id", None),
        "status": ("status", None),
    })
    return listing.list_response(rows, serialize.signature)


@bp.get("/petition-signatures/<petition_signature_id>")
def read_signature(petition_signature_id):
    auth.require_any()
    row = lookup.signature(petition_signature_id)
    return response.object_response(serialize.signature(row))


@bp.post("/petition-signatures/<petition_signature_id>/adjudicate")
def adjudicate(petition_signature_id):
    user_id, _role = auth.require(constants.ELECTION_COMMISSIONER)
    signature = lookup.signature(petition_signature_id)
    candidacy = db.store.candidacies[signature["candidacy_id"]]
    election = db.store.elections[candidacy["election_id"]]

    body = validation.get_body()
    outcome = validation.req_enum(body, "outcome", constants.ADJUDICATION_OUTCOMES)
    reject_reason = validation.opt_text(body, "reject_reason")

    if signature["status"] != "SUBMITTED":
        errors.fail(errors.ERR_INVALID_STATE,
                    "Only a SUBMITTED signature may be adjudicated.")
    if election["status"] != "PETITIONING":
        errors.fail(errors.ERR_ELECTION_PHASE_INVALID,
                    "Signatures may only be adjudicated while the election is PETITIONING.")

    if outcome == "VERIFIED":
        db.set_fields(signature, status="VERIFIED", verified_by_user_id=user_id,
                      eligibility_result=calc.signature_verdict(signature, candidacy))
    else:
        db.set_fields(signature, status="REJECTED", verified_by_user_id=user_id,
                      reject_reason=reject_reason)
    db.touch(signature)
    calc.recompute_petition_counters(candidacy)
    return response.object_response(serialize.signature(signature))


@bp.post("/petition-signatures/<petition_signature_id>/void")
def void_signature(petition_signature_id):
    auth.require(constants.ELECTION_COMMISSIONER)
    signature = lookup.signature(petition_signature_id)
    candidacy = db.store.candidacies[signature["candidacy_id"]]
    election = db.store.elections[candidacy["election_id"]]

    body = validation.get_body()
    validation.opt_text(body, "reason")

    if signature["status"] not in ("SUBMITTED", "VERIFIED"):
        errors.fail(errors.ERR_INVALID_STATE,
                    "Only a SUBMITTED or VERIFIED signature may be voided.")
    if election["status"] not in ("PETITIONING", "BALLOT_BUILDING"):
        errors.fail(errors.ERR_INVALID_STATE,
                    "Signatures may only be voided while the election is PETITIONING or BALLOT_BUILDING.")

    db.set_fields(signature, status="VOIDED")
    db.touch(signature)
    # hop 1 — recompute; hops 2 and 3 — deficiency and slate suspension
    calc.recompute_petition_counters(candidacy)
    cascades.petition_void_cascade(candidacy)
    return response.object_response(serialize.signature(signature))
