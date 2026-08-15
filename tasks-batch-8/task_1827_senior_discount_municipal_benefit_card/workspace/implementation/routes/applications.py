from datetime import timedelta

from flask import Blueprint

import clock
import services
import store
from auth import authenticate, authorize, require_cardholder_self
from errors import (
    ERR_APPLICATION_INVALID_STATE,
    ERR_APPLICATION_NOT_FOUND,
    ERR_CARDHOLDER_NOT_FOUND,
    ERR_CARDHOLDER_OWNERSHIP_MISMATCH,
    ERR_DOCUMENT_ALREADY_REVIEWED,
    ERR_DOCUMENT_NOT_FOUND,
    ERR_DUPLICATE_PENDING_APPLICATION,
    ERR_ELIGIBILITY_AGE_NOT_MET,
    ERR_ELIGIBILITY_INCOME_EXCEEDED,
    ERR_INVALID_REQUEST,
    ERR_MISSING_REQUIRED_DOCUMENTS,
    ERR_RECERTIFICATION_NOT_DUE,
    ERR_SEGREGATION_OF_DUTIES,
    raise_err,
)
from util import (
    body_json,
    bump,
    get_or_404,
    list_response,
    new_record,
    req_date,
    req_enum,
    req_int,
    req_str,
    success_object,
)

bp = Blueprint("applications", __name__)

APPLICATION_KINDS = ("INITIAL", "RECERTIFICATION")
DOCUMENT_TYPES = ("PROOF_OF_AGE", "PROOF_OF_INCOME", "PROOF_OF_RESIDENCY")
APPLICATION_NON_TERMINAL = ("SUBMITTED", "UNDER_REVIEW", "INFO_REQUESTED")


@bp.route("/applications", methods=["POST"])
def create_application():
    uid, role = authenticate()
    authorize(role, ["Applicant", "Cardholder"])
    body = body_json()
    kind = req_enum(body, "kind", APPLICATION_KINDS)
    full_name = req_str(body, "applicant_full_name")
    dob = req_date(body, "date_of_birth")
    income = req_int(body, "annual_income_cents")
    if income < 0:
        raise_err(ERR_INVALID_REQUEST, "annual_income_cents must be >= 0")
    address = req_str(body, "residency_address")

    ch = None
    if kind == "RECERTIFICATION":
        ch_id = body.get("cardholder_id")
        if not isinstance(ch_id, str):
            raise_err(ERR_INVALID_REQUEST,
                      "cardholder_id is required for RECERTIFICATION")
        ch = store.cardholders.get(ch_id)
        if ch is None:
            raise_err(ERR_CARDHOLDER_NOT_FOUND, "Cardholder not found: %s" % ch_id)
        if role == "Cardholder":
            require_cardholder_self(uid, ch_id)

    # eligibility gates evaluated at submission against the logical clock
    if services.age_years(dob, clock.today()) < services.MIN_AGE_YEARS:
        raise_err(ERR_ELIGIBILITY_AGE_NOT_MET, "Applicant is under %d years of age"
                  % services.MIN_AGE_YEARS)
    if income > services.INCOME_LIMIT_CENTS:
        raise_err(ERR_ELIGIBILITY_INCOME_EXCEEDED,
                  "annual_income_cents exceeds the program limit")

    if kind == "RECERTIFICATION":
        for a in store.applications.values():
            if (a["cardholder_id"] == ch["id"] and a["kind"] == "RECERTIFICATION"
                    and a["status"] in APPLICATION_NON_TERMINAL):
                raise_err(ERR_DUPLICATE_PENDING_APPLICATION,
                          "Cardholder already has a pending recertification application")
        if ch["status"] not in ("RECERTIFICATION_DUE", "LAPSED"):
            raise_err(ERR_RECERTIFICATION_NOT_DUE,
                      "Cardholder is not due for recertification")

    rec = new_record()
    rec.update({
        "kind": kind,
        "applicant_full_name": full_name,
        "date_of_birth": dob,
        "annual_income_cents": income,
        "residency_address": address,
        "cardholder_id": ch["id"] if ch is not None else None,
        "status": "SUBMITTED",
        "reviewed_by_user_id": None,
        "info_request_reason": None,
        "denial_reason": None,
        "decided_by_user_id": None,
    })
    store.applications[rec["id"]] = rec
    return success_object(services.application_out(rec), 201)


@bp.route("/applications/<rid>", methods=["GET"])
def get_application(rid):
    _, role = authenticate()
    authorize(role, ["Applicant", "EligibilitySpecialist", "ProgramAdministrator",
                     "FraudAnalyst"])
    rec = get_or_404(store.applications, rid, ERR_APPLICATION_NOT_FOUND, "Application")
    return success_object(services.application_out(rec))


@bp.route("/applications/<rid>/start-review", methods=["POST"])
def start_review(rid):
    uid, role = authenticate()
    authorize(role, ["EligibilitySpecialist"])
    rec = get_or_404(store.applications, rid, ERR_APPLICATION_NOT_FOUND, "Application")
    if rec["status"] not in ("SUBMITTED", "INFO_REQUESTED"):
        raise_err(ERR_APPLICATION_INVALID_STATE,
                  "start-review requires status SUBMITTED or INFO_REQUESTED")
    rec["status"] = "UNDER_REVIEW"
    rec["reviewed_by_user_id"] = uid
    bump(rec)
    return success_object(services.application_out(rec))


@bp.route("/applications/<rid>/request-info", methods=["POST"])
def request_info(rid):
    _, role = authenticate()
    authorize(role, ["EligibilitySpecialist"])
    rec = get_or_404(store.applications, rid, ERR_APPLICATION_NOT_FOUND, "Application")
    if rec["status"] != "UNDER_REVIEW":
        raise_err(ERR_APPLICATION_INVALID_STATE,
                  "request-info requires status UNDER_REVIEW")
    body = body_json()
    reason = req_str(body, "reason")
    rec["status"] = "INFO_REQUESTED"
    rec["info_request_reason"] = reason
    bump(rec)
    return success_object(services.application_out(rec))


@bp.route("/applications/<rid>/approve", methods=["POST"])
def approve(rid):
    uid, role = authenticate()
    authorize(role, ["ProgramAdministrator"])
    rec = get_or_404(store.applications, rid, ERR_APPLICATION_NOT_FOUND, "Application")
    if rec["status"] != "UNDER_REVIEW":
        raise_err(ERR_APPLICATION_INVALID_STATE, "approve requires status UNDER_REVIEW")
    # segregation of duties: the approver must not have examined the case
    if rec["reviewed_by_user_id"] is not None and rec["reviewed_by_user_id"] == uid:
        raise_err(ERR_SEGREGATION_OF_DUTIES,
                  "Approver previously reviewed this application")
    docs = [d for d in store.documents.values() if d["application_id"] == rec["id"]]
    for d in docs:
        if d["status"] == "VERIFIED" and d["reviewed_by_user_id"] == uid:
            raise_err(ERR_SEGREGATION_OF_DUTIES,
                      "Approver verified a document on this application")
    # document completeness
    for doc_type in DOCUMENT_TYPES:
        if not any(d["document_type"] == doc_type and d["status"] == "VERIFIED"
                   for d in docs):
            raise_err(ERR_MISSING_REQUIRED_DOCUMENTS,
                      "Missing a VERIFIED document of type %s" % doc_type)
    # recertification timing re-verified at decision time
    ch = None
    if rec["kind"] == "RECERTIFICATION":
        ch = store.cardholders.get(rec["cardholder_id"])
        if ch is None or ch["status"] not in ("RECERTIFICATION_DUE", "LAPSED"):
            raise_err(ERR_RECERTIFICATION_NOT_DUE,
                      "Cardholder is not due for recertification")

    if rec["kind"] == "INITIAL":
        ch = new_record()
        ch.update({
            "full_name": rec["applicant_full_name"],
            "date_of_birth": rec["date_of_birth"],
            "annual_income_cents": rec["annual_income_cents"],
            "residency_address": rec["residency_address"],
            "status": "ACTIVE",
            "pre_suspension_status": None,
            "recertification_due_date": clock.today() + timedelta(days=365),
        })
        store.cardholders[ch["id"]] = ch
        rec["cardholder_id"] = ch["id"]
        services.issue_card(ch, "INITIAL", None)
    else:
        ch["status"] = "ACTIVE"
        ch["recertification_due_date"] = clock.today() + timedelta(days=365)
        ch["annual_income_cents"] = rec["annual_income_cents"]
        ch["residency_address"] = rec["residency_address"]
        bump(ch)

    rec["status"] = "APPROVED"
    rec["decided_by_user_id"] = uid
    bump(rec)
    return success_object(services.application_out(rec))


@bp.route("/applications/<rid>/deny", methods=["POST"])
def deny(rid):
    uid, role = authenticate()
    authorize(role, ["ProgramAdministrator"])
    rec = get_or_404(store.applications, rid, ERR_APPLICATION_NOT_FOUND, "Application")
    if rec["status"] != "UNDER_REVIEW":
        raise_err(ERR_APPLICATION_INVALID_STATE, "deny requires status UNDER_REVIEW")
    body = body_json()
    reason = req_str(body, "reason")
    rec["status"] = "DENIED"
    rec["denial_reason"] = reason
    rec["decided_by_user_id"] = uid
    bump(rec)
    return success_object(services.application_out(rec))


# ---------------------------------------------------------------------------
# verification documents
# ---------------------------------------------------------------------------
@bp.route("/applications/<rid>/documents", methods=["POST"])
def attach_document(rid):
    _, role = authenticate()
    authorize(role, ["Applicant", "Cardholder"])
    app = get_or_404(store.applications, rid, ERR_APPLICATION_NOT_FOUND, "Application")
    body = body_json()
    doc_type = req_enum(body, "document_type", DOCUMENT_TYPES)
    reference = req_str(body, "document_reference")
    rec = new_record()
    rec.update({
        "application_id": app["id"],
        "document_type": doc_type,
        "document_reference": reference,
        "status": "SUBMITTED",
        "reviewed_by_user_id": None,
        "rejection_reason": None,
    })
    store.documents[rec["id"]] = rec
    return success_object(services.document_out(rec), 201)


@bp.route("/applications/<rid>/documents", methods=["GET"])
def list_documents(rid):
    _, role = authenticate()
    authorize(role, ["Applicant", "EligibilitySpecialist", "ProgramAdministrator",
                     "FraudAnalyst"])
    app = get_or_404(store.applications, rid, ERR_APPLICATION_NOT_FOUND, "Application")
    docs = [d for d in store.documents.values() if d["application_id"] == app["id"]]
    return list_response(docs, services.document_out)


@bp.route("/applications/<rid>/documents/<doc_id>/review", methods=["POST"])
def review_document(rid, doc_id):
    uid, role = authenticate()
    authorize(role, ["EligibilitySpecialist"])
    app = get_or_404(store.applications, rid, ERR_APPLICATION_NOT_FOUND, "Application")
    doc = store.documents.get(doc_id)
    if doc is None or doc["application_id"] != app["id"]:
        raise_err(ERR_DOCUMENT_NOT_FOUND, "Document not found: %s" % doc_id)
    if app["status"] not in ("UNDER_REVIEW", "INFO_REQUESTED"):
        raise_err(ERR_APPLICATION_INVALID_STATE,
                  "Parent application is not under review")
    if doc["status"] != "SUBMITTED":
        raise_err(ERR_DOCUMENT_ALREADY_REVIEWED, "Document has already been reviewed")
    body = body_json()
    decision = req_enum(body, "decision", ("VERIFIED", "REJECTED"))
    rejection_reason = None
    if decision == "REJECTED":
        rejection_reason = req_str(body, "rejection_reason")
    doc["status"] = decision
    doc["reviewed_by_user_id"] = uid
    doc["rejection_reason"] = rejection_reason
    bump(doc)
    return success_object(services.document_out(doc))
