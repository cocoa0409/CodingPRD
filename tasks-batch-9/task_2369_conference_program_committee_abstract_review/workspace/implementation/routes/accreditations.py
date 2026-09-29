"""CME accreditation and disclosure-statement endpoints."""

from flask import Blueprint

from db import db, new_row, touch
from errors import fail
from middleware import ROLE_ADMIN, ROLE_AUTHOR, ROLE_CHAIR, endpoint
from response import created, ok, ok_list
from routes.helpers import filtered, lookup, resolve_fk
from services import derive, logic
from validators import (body_json, paginate, present, q_str, v_bool, v_enum,
                        v_int, v_string)

bp = Blueprint("accreditations", __name__)


@bp.post("/accreditations")
@endpoint(ROLE_ADMIN, ROLE_CHAIR)
def create_accreditation(actor):
    body = body_json()
    abstract = resolve_fk(body, "abstract_id")
    content_minutes = v_int(body, "content_minutes", required=True, minimum=5, maximum=240)
    disclosed = v_bool(body, "commercial_support_disclosed", default=False)
    if abstract is None:
        fail("ERR_VALIDATION", "abstract_id is required.")

    category = logic.category_of(abstract)
    # Band 10.
    if abstract["status"] not in ("ACCEPTED", "CONFIRMED", "SCHEDULED"):
        fail("ERR_ABSTRACT_STATE_INVALID")
    for existing in derive.abstract_accreditations(abstract["id"]):
        if existing["validation_status"] in ("PENDING", "VALIDATED"):
            fail("ERR_ACCREDITATION_STATE_INVALID",
                 "This abstract already has a live accreditation.")
    # Band 14.
    if category is None or not category["cme_eligible"]:
        fail("ERR_CATEGORY_NOT_CME_ELIGIBLE")

    row = new_row({
        "abstract_id": abstract["id"],
        "content_minutes": content_minutes,
        "commercial_support_disclosed": bool(disclosed),
        "validation_status": "PENDING",
        "validated_by_member_id": None,
        "validated_at": None,
    })
    db.accreditations[row["id"]] = row
    return created(derive.accreditation_out(row))


@bp.get("/accreditations")
@endpoint(ROLE_ADMIN, ROLE_CHAIR, ROLE_AUTHOR)
def list_accreditations(actor):
    rows = filtered(db.accreditations.values(), {
        "abstract_id": q_str("abstract_id"),
        "validated_by_member_id": q_str("validated_by_member_id"),
        "validation_status": q_str("validation_status"),
    })
    page, meta = paginate(rows)
    return ok_list([derive.accreditation_out(r) for r in page], meta)


@bp.get("/accreditations/<accreditation_id>")
@endpoint(ROLE_ADMIN, ROLE_CHAIR, ROLE_AUTHOR)
def get_accreditation(actor, accreditation_id):
    row = lookup("accreditations", accreditation_id, "ERR_ACCREDITATION_NOT_FOUND")
    return ok(derive.accreditation_out(row))


@bp.post("/accreditations/<accreditation_id>/validation")
@endpoint(ROLE_CHAIR)
def validate_accreditation(actor, accreditation_id):
    accreditation = lookup("accreditations", accreditation_id,
                           "ERR_ACCREDITATION_NOT_FOUND")
    abstract = db.abstracts.get(accreditation["abstract_id"])
    conference = logic.conference_of(abstract) if abstract else None

    body = body_json()
    action = v_enum(body, "action", ("VALIDATE", "REJECT", "REVOKE"), required=True)
    rejection_reason = None
    if present(body, "rejection_reason"):
        rejection_reason = v_string(body, "rejection_reason", min_len=1, max_len=1000)
    if action == "REJECT" and not rejection_reason:
        fail("ERR_VALIDATION", "rejection_reason is required to reject an accreditation.")

    status = accreditation["validation_status"]

    if action == "VALIDATE":
        if status != "PENDING":
            fail("ERR_ACCREDITATION_STATE_INVALID")
        # Band 11 — the deciding chair may not validate their own decision.
        if abstract is not None and abstract["decided_by_member_id"] == actor.member_id:
            fail("ERR_ACCREDITATION_SELF_VALIDATION")
        # Band 13 — disclosure completeness.
        disclosures = derive.accreditation_disclosures(accreditation_id)
        if not disclosures or any(d["status"] != "VALIDATED" for d in disclosures):
            fail("ERR_DISCLOSURE_INCOMPLETE")
        if derive.commercial_bias_flag(accreditation):
            fail("ERR_DISCLOSURE_INCOMPLETE")
        # Band 21 — conserved CME minute pool.
        if accreditation["content_minutes"] > derive.cme_minutes_available(conference):
            fail("ERR_CME_POOL_EXHAUSTED")

        accreditation["validation_status"] = "VALIDATED"
        accreditation["validated_by_member_id"] = actor.member_id
        accreditation["validated_at"] = db.now_raw()
        touch(accreditation)
        touch(conference)
        for session in logic.sessions_holding_abstract(accreditation["abstract_id"]):
            logic.bump_session(session)

    elif action == "REJECT":
        if status != "PENDING":
            fail("ERR_ACCREDITATION_STATE_INVALID")
        accreditation["validation_status"] = "REJECTED"
        touch(accreditation)

    else:  # REVOKE
        if status != "VALIDATED":
            fail("ERR_ACCREDITATION_STATE_INVALID")
        accreditation["validation_status"] = "REVOKED"
        touch(accreditation)
        touch(conference)
        for session in logic.sessions_holding_abstract(accreditation["abstract_id"]):
            logic.bump_session(session)
            logic.unpublish_if_non_compliant(session)

    return ok(derive.accreditation_out(accreditation))


# ---------------------------------------------------------------------------
# disclosure statements
# ---------------------------------------------------------------------------

disclosures_bp = Blueprint("disclosures", __name__)


@disclosures_bp.post("/disclosure-statements")
@endpoint(ROLE_AUTHOR, ROLE_ADMIN)
def create_disclosure(actor):
    body = body_json()
    abstract = resolve_fk(body, "abstract_id")
    accreditation = resolve_fk(body, "accreditation_id")
    author = resolve_fk(body, "author_id")

    has_relationship = v_bool(body, "has_financial_relationship", required=True)
    relationship_entity = None
    if present(body, "relationship_entity"):
        relationship_entity = v_string(body, "relationship_entity", min_len=1, max_len=200)
    if abstract is None:
        fail("ERR_VALIDATION", "abstract_id is required.")
    if accreditation is None:
        fail("ERR_VALIDATION", "accreditation_id is required.")
    if author is None:
        fail("ERR_VALIDATION", "author_id is required.")
    if has_relationship and not relationship_entity:
        fail("ERR_VALIDATION",
             "relationship_entity is required when has_financial_relationship is true.")

    # Band 10.
    if accreditation["validation_status"] != "PENDING":
        fail("ERR_ACCREDITATION_STATE_INVALID")
    # Band 14.
    if accreditation["abstract_id"] != abstract["id"]:
        fail("ERR_DISCLOSURE_ABSTRACT_MISMATCH")
    if author["email"] not in derive.author_emails(abstract):
        fail("ERR_PRESENTER_NOT_ON_ABSTRACT")

    row = new_row({
        "abstract_id": abstract["id"],
        "accreditation_id": accreditation["id"],
        "author_id": author["id"],
        "has_financial_relationship": bool(has_relationship),
        "relationship_entity": relationship_entity,
        "mitigation_required": bool(has_relationship),
        "mitigation_completed": False,
        "status": "SUBMITTED",
        "rejection_reason": None,
    })
    db.disclosures[row["id"]] = row
    touch(accreditation)
    return created(derive.disclosure_out(row))


@disclosures_bp.get("/disclosure-statements")
@endpoint(ROLE_ADMIN, ROLE_CHAIR, ROLE_AUTHOR)
def list_disclosures(actor):
    rows = filtered(db.disclosures.values(), {
        "abstract_id": q_str("abstract_id"),
        "accreditation_id": q_str("accreditation_id"),
        "author_id": q_str("author_id"),
        "status": q_str("status"),
    })
    page, meta = paginate(rows)
    return ok_list([derive.disclosure_out(r) for r in page], meta)


@disclosures_bp.get("/disclosure-statements/<disclosure_id>")
@endpoint(ROLE_ADMIN, ROLE_CHAIR, ROLE_AUTHOR)
def get_disclosure(actor, disclosure_id):
    row = lookup("disclosures", disclosure_id, "ERR_DISCLOSURE_NOT_FOUND")
    return ok(derive.disclosure_out(row))


@disclosures_bp.post("/disclosure-statements/<disclosure_id>/adjudication")
@endpoint(ROLE_CHAIR)
def adjudicate_disclosure(actor, disclosure_id):
    disclosure = lookup("disclosures", disclosure_id, "ERR_DISCLOSURE_NOT_FOUND")
    body = body_json()
    outcome = v_enum(body, "outcome", ("VALIDATED", "REJECTED"), required=True)
    rejection_reason = None
    if present(body, "rejection_reason"):
        rejection_reason = v_string(body, "rejection_reason", min_len=1, max_len=1000)
    mitigation_completed = v_bool(body, "mitigation_completed")
    if outcome == "REJECTED" and not rejection_reason:
        fail("ERR_VALIDATION", "rejection_reason is required to reject a disclosure.")

    status = disclosure["status"]
    # Band 10.
    if status == "REJECTED":
        fail("ERR_DISCLOSURE_STATE_INVALID")
    if outcome == "VALIDATED" and status != "SUBMITTED":
        fail("ERR_DISCLOSURE_STATE_INVALID")

    effective_mitigation = (disclosure["mitigation_completed"]
                            if mitigation_completed is None else mitigation_completed)

    if outcome == "VALIDATED":
        # Band 13.
        if disclosure["mitigation_required"] and not effective_mitigation:
            fail("ERR_DISCLOSURE_INCOMPLETE")
        disclosure["mitigation_completed"] = effective_mitigation
        disclosure["status"] = "VALIDATED"
        touch(disclosure)
        accreditation = db.accreditations.get(disclosure["accreditation_id"])
        if accreditation is not None:
            touch(accreditation)
        return ok(derive.disclosure_out(disclosure))

    # REJECTED
    disclosure["mitigation_completed"] = effective_mitigation
    disclosure["rejection_reason"] = rejection_reason
    if status == "VALIDATED":
        disclosure["status"] = "REJECTED"
        touch(disclosure)
        logic.cascade_disclosure_rejection(disclosure)
    else:
        disclosure["status"] = "REJECTED"
        touch(disclosure)
        accreditation = db.accreditations.get(disclosure["accreditation_id"])
        if accreditation is not None:
            touch(accreditation)
    return ok(derive.disclosure_out(disclosure))
