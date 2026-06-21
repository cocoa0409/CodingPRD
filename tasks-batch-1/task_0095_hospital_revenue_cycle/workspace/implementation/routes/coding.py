"""CodingAssignment lifecycle (PRD 3.5, 3.6)."""
import re

from flask import Blueprint

import calculations
import db
import errors
import listing
import response
import validate
from middleware import authenticate, require_role

bp = Blueprint("coding", __name__)

ICD10_RE = re.compile(r"^[A-Za-z][0-9]{2}(\.[A-Za-z0-9]{1,4})?$")


def _valid_icd10(code):
    return isinstance(code, str) and bool(ICD10_RE.match(code))


@bp.route("/encounters/<eid>/coding-assignment", methods=["POST"])
def create_coding(eid):
    _, role = authenticate()
    require_role(role, {"Coder"})
    enc = db.encounters.get(eid)
    if enc is None:
        raise errors.not_found()
    body = validate.get_body()

    principal = validate.require_str(body, "principal_icd10")
    if not _valid_icd10(principal):
        raise errors.invalid_request("principal_icd10 is not a valid ICD-10 code.")
    secondary = body.get("secondary_icd10", [])
    if secondary is None:
        secondary = []
    if not isinstance(secondary, list) or not all(_valid_icd10(c) for c in secondary):
        raise errors.invalid_request("secondary_icd10 must be a list of valid ICD-10 codes.")

    rec = db.base_record(common_fields=True)
    rec.update({
        "encounter_id": eid,
        "principal_icd10": principal,
        "secondary_icd10": list(secondary),
        "status": "DRAFT",
        "finalized_by_user_id": None,
        "compliance_risk_score": 0,
    })
    db.coding_assignments[rec["id"]] = rec
    return response.object_response(rec, 201)


@bp.route("/encounters/<eid>/coding-assignment", methods=["GET"])
def list_encounter_coding(eid):
    authenticate()
    if eid not in db.encounters:
        raise errors.not_found()
    recs = [c for c in db.coding_assignments.values() if c["encounter_id"] == eid]
    page, limit, offset, total = listing.paginate(recs)
    return response.array_response(page, limit, offset, total, 200)


@bp.route("/coding-assignments/<cid>", methods=["GET"])
def get_coding(cid):
    authenticate()
    rec = db.coding_assignments.get(cid)
    if rec is None:
        raise errors.not_found()
    return response.object_response(rec, 200)


@bp.route("/coding-assignments/<cid>/finalize", methods=["POST"])
def finalize_coding(cid):
    user_id, role = authenticate()
    require_role(role, {"Coder"})
    coding = db.coding_assignments.get(cid)
    if coding is None:
        raise errors.not_found()
    # state gate: defined only from DRAFT
    if coding["status"] != "DRAFT":
        raise errors.invalid_state("Finalize is only defined from DRAFT status.")
    # additionally requires encounter in CHARGES_CAPTURED
    enc = db.encounters.get(coding["encounter_id"])
    if enc is None or enc["status"] != "CHARGES_CAPTURED":
        raise errors.invalid_state("Finalize requires the encounter to be in CHARGES_CAPTURED status.")

    distinct_cpt = {c["cpt_code"] for c in db.charges.values()
                    if c["encounter_id"] == coding["encounter_id"] and c["status"] == "POSTED"}
    score = calculations.coding_compliance_risk(
        coding["principal_icd10"], coding["secondary_icd10"], len(distinct_cpt)
    )
    coding["compliance_risk_score"] = score
    coding["finalized_by_user_id"] = user_id
    # fork on the inclusive audit threshold (>= 50 -> AUDIT_HOLD)
    if score >= calculations.AUDIT_THRESHOLD:
        coding["status"] = "AUDIT_HOLD"
    else:
        coding["status"] = "FINALIZED"
    db.touch(coding)
    return response.object_response(coding, 200)


@bp.route("/coding-assignments/<cid>/return-for-recode", methods=["POST"])
def return_for_recode(cid):
    _, role = authenticate()
    require_role(role, {"Coder"})
    coding = db.coding_assignments.get(cid)
    if coding is None:
        raise errors.not_found()
    if coding["status"] != "AUDIT_HOLD":
        raise errors.invalid_state("Return-for-recode is only defined from AUDIT_HOLD status.")
    coding["finalized_by_user_id"] = None
    coding["status"] = "DRAFT"
    db.touch(coding)
    return response.object_response(coding, 200)


@bp.route("/coding-assignments/<cid>/clear", methods=["POST"])
def clear_coding(cid):
    _, role = authenticate()
    require_role(role, {"BillingSpecialist"})
    coding = db.coding_assignments.get(cid)
    if coding is None:
        raise errors.not_found()
    if coding["status"] != "FINALIZED":
        raise errors.invalid_state("Clear is only defined from FINALIZED status.")
    coding["status"] = "CLEARED"
    db.touch(coding)
    # bubble up: encounter CHARGES_CAPTURED -> CODED (only when in that state)
    enc = db.encounters.get(coding["encounter_id"])
    if enc is not None and enc["status"] == "CHARGES_CAPTURED":
        enc["status"] = "CODED"
        db.touch(enc)
    return response.object_response(coding, 200)
