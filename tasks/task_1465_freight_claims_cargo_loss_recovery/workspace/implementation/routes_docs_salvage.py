"""Routes: claim documents, liability assessments, salvage dispositions."""

from flask import Blueprint, g, request

from db import STORE, iso, new_id, next_seq, now, parse_dt
from errors import (
    ApiError,
    ERR_ASSESSMENT_INVALID_STATE,
    ERR_ASSESSMENT_NOT_FOUND,
    ERR_CLAIM_AMOUNT_EXCEEDS_DECLARED_VALUE,
    ERR_CLAIM_INVALID_STATE,
    ERR_CLAIM_LOCKED,
    ERR_DOCUMENT_INVALID_STATE,
    ERR_DOCUMENT_NOT_FOUND,
    ERR_DOCUMENTS_NOT_VERIFIED,
    ERR_INVALID_TEMPORAL_RANGE,
    ERR_REJECTION_REASON_REQUIRED,
    ERR_SALVAGE_INVALID_STATE,
    ERR_SALVAGE_NOT_YET_DUE,
    ERR_SEGREGATION_OF_DUTIES_VIOLATION,
)
from middleware import as_enum, as_int, as_str, req_field, request_body, require_roles
from response import paginate, success_object
from routes_claims import get_claim_or_404
from serializers import ser_assessment, ser_document, ser_salvage
from services import (
    add_event,
    execute_salvage,
    liability_pipeline,
    touch,
    touch_claim,
)

bp = Blueprint("docs_salvage", __name__)

DOCUMENT_KINDS = {"BOL", "COMMERCIAL_INVOICE", "PHOTO", "DELIVERY_RECEIPT",
                  "INSPECTION_REPORT", "REPAIR_ESTIMATE"}
NEGLIGENCE_FLAGS = {"NONE", "CARRIER_NEGLIGENT", "SHIPPER_FAULT", "ACT_OF_GOD", "THIRD_PARTY"}
DISPOSITION_KINDS = {"RETURN_TO_SHIPPER", "AUCTION", "DESTROY", "DONATE", "REPAIR_AND_RETURN"}
DOC_MUTABLE_CLAIM_STATES = {"DRAFT", "SUBMITTED", "ACKNOWLEDGED"}


def get_document_or_404(claim, doc_id):
    doc = STORE["documents"].get(doc_id)
    if doc is None or doc["claim_id"] != claim["id"]:
        raise ApiError(ERR_DOCUMENT_NOT_FOUND, f"Document '{doc_id}' not found", 404)
    return doc


def get_assessment_or_404(claim, assessment_id):
    assessment = STORE["assessments"].get(assessment_id)
    if assessment is None or assessment["claim_id"] != claim["id"]:
        raise ApiError(ERR_ASSESSMENT_NOT_FOUND, f"Assessment '{assessment_id}' not found", 404)
    return assessment


def get_salvage_or_404(claim, salvage_id):
    salvage = STORE["salvage"].get(salvage_id)
    if salvage is None or salvage["claim_id"] != claim["id"]:
        raise ApiError(ERR_SALVAGE_NOT_FOUND, f"Salvage disposition '{salvage_id}' not found", 404)
    return salvage


# ---------------------------------------------------------------------------
# ClaimDocument
# ---------------------------------------------------------------------------

@bp.post("/freight-claims/claims/<claim_id>/documents")
@require_roles("ClaimsClerk")
def create_document(claim_id):
    claim = get_claim_or_404(claim_id)
    body = request_body()
    document_kind = as_enum(req_field(body, "document_kind"), "document_kind", DOCUMENT_KINDS)
    storage_uri = as_str(req_field(body, "storage_uri"), "storage_uri")
    captured_at = req_field(body, "captured_at")
    parse_dt(captured_at, "captured_at")
    stamp = iso(now())
    doc = {
        "id": new_id(),
        "claim_id": claim["id"],
        "document_kind": document_kind,
        "storage_uri": storage_uri,
        "captured_at": captured_at,
        "verification_status": "PENDING",
        "rejection_reason": None,
        "created_at": stamp,
        "updated_at": stamp,
        "version": 1,
        "_seq": next_seq(),
    }
    STORE["documents"][doc["id"]] = doc
    return success_object(ser_document(doc), status=201)


@bp.get("/freight-claims/claims/<claim_id>/documents")
@require_roles("Any")
def list_documents(claim_id):
    claim = get_claim_or_404(claim_id)
    records = [d for d in STORE["documents"].values() if d["claim_id"] == claim["id"]]
    verification_status = request.args.get("verification_status")
    document_kind = request.args.get("document_kind")
    if verification_status is not None:
        records = [d for d in records if d["verification_status"] == verification_status]
    if document_kind is not None:
        records = [d for d in records if d["document_kind"] == document_kind]
    return paginate(records, ser_document)


@bp.get("/freight-claims/claims/<claim_id>/documents/<doc_id>")
@require_roles("Any")
def get_document(claim_id, doc_id):
    claim = get_claim_or_404(claim_id)
    return success_object(ser_document(get_document_or_404(claim, doc_id)))


@bp.post("/freight-claims/claims/<claim_id>/documents/<doc_id>/verify")
@require_roles("ClaimsAdjuster")
def verify_document(claim_id, doc_id):
    claim = get_claim_or_404(claim_id)
    doc = get_document_or_404(claim, doc_id)
    if doc["verification_status"] != "PENDING":
        raise ApiError(ERR_DOCUMENT_INVALID_STATE,
                       "Only a PENDING document may be verified", 409)
    if claim["filing_status"] not in DOC_MUTABLE_CLAIM_STATES:
        raise ApiError(ERR_CLAIM_LOCKED,
                       "Claim is locked against document verification in its current state", 409)
    doc["verification_status"] = "VERIFIED"
    touch(doc)
    return success_object(ser_document(doc))


@bp.post("/freight-claims/claims/<claim_id>/documents/<doc_id>/reject")
@require_roles("ClaimsAdjuster")
def reject_document(claim_id, doc_id):
    claim = get_claim_or_404(claim_id)
    doc = get_document_or_404(claim, doc_id)
    if doc["verification_status"] != "PENDING":
        raise ApiError(ERR_DOCUMENT_INVALID_STATE,
                       "Only a PENDING document may be rejected", 409)
    body = request_body()
    reason = body.get("rejection_reason")
    if not isinstance(reason, str) or not reason.strip():
        raise ApiError(ERR_REJECTION_REASON_REQUIRED,
                       "A non-empty rejection_reason is required", 422)
    doc["verification_status"] = "REJECTED"
    doc["rejection_reason"] = reason
    touch(doc)
    return success_object(ser_document(doc))


# ---------------------------------------------------------------------------
# LiabilityAssessment
# ---------------------------------------------------------------------------

@bp.post("/freight-claims/claims/<claim_id>/assessments")
@require_roles("ClaimsAdjuster")
def create_assessment(claim_id):
    claim = get_claim_or_404(claim_id)
    if claim["filing_status"] != "ACKNOWLEDGED":
        raise ApiError(ERR_CLAIM_INVALID_STATE,
                       "An assessment may be created only on an ACKNOWLEDGED claim", 409)
    docs = [d for d in STORE["documents"].values() if d["claim_id"] == claim["id"]]
    if any(d["verification_status"] != "VERIFIED" for d in docs):
        raise ApiError(ERR_DOCUMENTS_NOT_VERIFIED,
                       "All claim documents must be VERIFIED before assessment", 422)
    body = request_body()
    negligence_flag = as_enum(req_field(body, "negligence_flag"), "negligence_flag",
                              NEGLIGENCE_FLAGS)
    shipment = STORE["shipments"][claim["shipment_id"]]
    carrier = STORE["carriers"][claim["carrier_id"]]
    basis, carrier_limit, discount_pct, computed = liability_pipeline(
        claim, shipment, carrier, negligence_flag=negligence_flag)

    # Supersede any prior SUBMITTED assessment for this claim.
    for prior in STORE["assessments"].values():
        if prior["claim_id"] == claim["id"] and prior["state"] == "SUBMITTED":
            prior["state"] = "SUPERSEDED"
            touch(prior)

    stamp = iso(now())
    assessment = {
        "id": new_id(),
        "claim_id": claim["id"],
        "assessed_by_user_id": g.user_id,
        "liability_model_applied": carrier["liability_model"],
        "limitation_basis_cents": basis,
        "carrier_limit_cents": carrier_limit,
        "lane_discount_pct": discount_pct,
        "computed_liability_cents": computed,
        "negligence_flag": negligence_flag,
        "state": "SUBMITTED",
        "created_at": stamp,
        "updated_at": stamp,
        "version": 1,
        "_seq": next_seq(),
    }
    STORE["assessments"][assessment["id"]] = assessment

    claim["computed_liability_cents"] = computed
    claim["liability_assessment_id"] = assessment["id"]
    claim["net_exposure_cents"] = max(computed - claim["salvage_credit_cents"], 0)
    claim["filing_status"] = "UNDER_REVIEW"
    add_event(claim["id"], "ASSESSED", g.user_id, {
        "assessment_id": assessment["id"],
        "computed_liability_cents": computed,
    })
    touch_claim(claim)
    return success_object(ser_assessment(assessment), status=201)


@bp.get("/freight-claims/claims/<claim_id>/assessments")
@require_roles("Any")
def list_assessments(claim_id):
    claim = get_claim_or_404(claim_id)
    records = [a for a in STORE["assessments"].values() if a["claim_id"] == claim["id"]]
    return paginate(records, ser_assessment)


@bp.get("/freight-claims/claims/<claim_id>/assessments/<assessment_id>")
@require_roles("Any")
def get_assessment(claim_id, assessment_id):
    claim = get_claim_or_404(claim_id)
    return success_object(ser_assessment(get_assessment_or_404(claim, assessment_id)))


@bp.post("/freight-claims/claims/<claim_id>/assessments/<assessment_id>/approve")
@require_roles("ClaimsManager")
def approve_assessment(claim_id, assessment_id):
    claim = get_claim_or_404(claim_id)
    assessment = get_assessment_or_404(claim, assessment_id)
    if assessment["state"] != "SUBMITTED":
        raise ApiError(ERR_ASSESSMENT_INVALID_STATE,
                       "Only a SUBMITTED assessment may be approved", 409)
    if g.user_id == assessment["assessed_by_user_id"]:
        raise ApiError(ERR_SEGREGATION_OF_DUTIES_VIOLATION,
                       "The assessing adjuster may not approve their own assessment", 403)
    assessment["state"] = "APPROVED"
    touch(assessment)
    return success_object(ser_assessment(assessment))


# ---------------------------------------------------------------------------
# SalvageDisposition
# ---------------------------------------------------------------------------

@bp.post("/freight-claims/claims/<claim_id>/salvage")
@require_roles("SalvageCoordinator")
def create_salvage(claim_id):
    claim = get_claim_or_404(claim_id)
    body = request_body()
    disposition_kind = as_enum(req_field(body, "disposition_kind"), "disposition_kind",
                               DISPOSITION_KINDS)
    gross = as_int(req_field(body, "gross_proceeds_cents"), "gross_proceeds_cents")
    handling = as_int(req_field(body, "handling_cost_cents"), "handling_cost_cents")
    scheduled_at = req_field(body, "scheduled_at")
    scheduled_dt = parse_dt(scheduled_at, "scheduled_at")
    if scheduled_dt <= now():
        raise ApiError(ERR_INVALID_TEMPORAL_RANGE,
                       "scheduled_at must be in the future", 400)
    if gross < 0 or handling < 0:
        raise ApiError(ERR_CLAIM_AMOUNT_EXCEEDS_DECLARED_VALUE,
                       "gross_proceeds_cents and handling_cost_cents must be >= 0", 422)
    stamp = iso(now())
    salvage = {
        "id": new_id(),
        "claim_id": claim["id"],
        "disposition_kind": disposition_kind,
        "gross_proceeds_cents": gross,
        "handling_cost_cents": handling,
        "net_credit_cents": max(gross - handling, 0),
        "scheduled_at": scheduled_at,
        "state": "SCHEDULED",
        "created_at": stamp,
        "updated_at": stamp,
        "version": 1,
        "_scheduled_at_dt": scheduled_dt,
        "_seq": next_seq(),
    }
    STORE["salvage"][salvage["id"]] = salvage
    return success_object(ser_salvage(salvage), status=201)


@bp.get("/freight-claims/claims/<claim_id>/salvage")
@require_roles("Any")
def list_salvage(claim_id):
    claim = get_claim_or_404(claim_id)
    records = [s for s in STORE["salvage"].values() if s["claim_id"] == claim["id"]]
    state = request.args.get("state")
    if state is not None:
        records = [s for s in records if s["state"] == state]
    return paginate(records, ser_salvage)


@bp.get("/freight-claims/claims/<claim_id>/salvage/<salvage_id>")
@require_roles("Any")
def get_salvage(claim_id, salvage_id):
    claim = get_claim_or_404(claim_id)
    return success_object(ser_salvage(get_salvage_or_404(claim, salvage_id)))


@bp.post("/freight-claims/claims/<claim_id>/salvage/<salvage_id>/execute")
@require_roles("SalvageCoordinator")
def execute_salvage_route(claim_id, salvage_id):
    claim = get_claim_or_404(claim_id)
    salvage = get_salvage_or_404(claim, salvage_id)
    if salvage["state"] != "SCHEDULED":
        raise ApiError(ERR_SALVAGE_INVALID_STATE,
                       "Only a SCHEDULED disposition may be executed", 409)
    if now() < salvage["_scheduled_at_dt"]:
        raise ApiError(ERR_SALVAGE_NOT_YET_DUE,
                       "The disposition's scheduled_at has not been reached", 409)
    if claim["filing_status"] not in ("UNDER_REVIEW", "OFFERED", "DECLINED", "APPEALED"):
        raise ApiError(ERR_CLAIM_INVALID_STATE,
                       "Claim state does not admit salvage execution", 409)
    execute_salvage(claim, salvage, g.user_id)
    return success_object(ser_salvage(salvage))


@bp.post("/freight-claims/claims/<claim_id>/salvage/<salvage_id>/cancel")
@require_roles("SalvageCoordinator")
def cancel_salvage(claim_id, salvage_id):
    claim = get_claim_or_404(claim_id)
    salvage = get_salvage_or_404(claim, salvage_id)
    if salvage["state"] != "SCHEDULED":
        raise ApiError(ERR_SALVAGE_INVALID_STATE,
                       "Only a SCHEDULED disposition may be cancelled", 409)
    salvage["state"] = "CANCELLED"
    touch(salvage)
    return success_object(ser_salvage(salvage))
