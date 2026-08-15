"""Verification case and document endpoints (PRD 3.4)."""
from flask import Blueprint, request

from db import db
from errors import (
    raise_error, ERR_INVALID_REQUEST, ERR_INVALID_STATE,
    ERR_VERIFICATION_DOCS_INCOMPLETE, ERR_CONFLICTING_INFO_OPEN,
)
from middleware import authorized
from response import success_object
from routes.helpers import list_response
from services.calc import compute_efc
from services.core import new_record, public, touch
from services.packaging import maybe_mark_needs_repack
from util import CLOCK
from validate import get_body, req_str, opt_int, require_path_resource

bp = Blueprint("verification", __name__)

DIRECTOR_OFFICER = ["AidDirector", "AidOfficer"]
REQUIRED_DOC_TYPES = ("TAX_RETURN_TRANSCRIPT", "W2", "HOUSEHOLD_FORM")
ALL_DOC_TYPES = ("TAX_RETURN_TRANSCRIPT", "W2", "HOUSEHOLD_FORM",
                 "IDENTITY_STATEMENT", "OTHER")
OPEN_CONFLICT_STATUSES = ("OPEN", "SUBSTANTIATED", "RESOLVED_REQUIRES_CORRECTION")


def _case_documents(case_id):
    docs = [d for d in db.verification_documents.values()
            if d["verification_case_id"] == case_id]
    docs.sort(key=lambda d: (d["created_at"], d["_seq"]))
    return docs


def _evaluate_auto_advance(case):
    """Each time a document lands in RECEIVED or ACCEPTED: when all three
    required V1 doc types are RECEIVED or ACCEPTED, the case moves itself from
    DOCUMENTS_REQUESTED to DOCUMENTS_RECEIVED (PRD 3.4)."""
    if case["status"] != "DOCUMENTS_REQUESTED":
        return
    docs = _case_documents(case["id"])
    ready = 0
    for doc_type in REQUIRED_DOC_TYPES:
        row = next((d for d in docs if d["doc_type"] == doc_type), None)
        if row is not None and row["status"] in ("RECEIVED", "ACCEPTED"):
            ready += 1
    if ready == len(REQUIRED_DOC_TYPES):
        case["status"] = "DOCUMENTS_RECEIVED"
        touch(case)


# ---------------------------------------------------------------------------
# VerificationCase
# ---------------------------------------------------------------------------

@bp.get("/verification-cases")
def list_verification_cases():
    authorized(DIRECTOR_OFFICER)
    return list_response("verification_cases", {
        "student_id": request.args.get("student_id"),
        "aid_year_id": request.args.get("aid_year_id"),
        "isir_id": request.args.get("isir_id"),
    })


@bp.get("/verification-cases/<rid>")
def get_verification_case(rid):
    authorized(DIRECTOR_OFFICER)
    rec = require_path_resource("verification_cases", rid)
    return success_object(public(rec))


@bp.post("/verification-cases/<rid>/begin-review")
def begin_review(rid):
    authorized(["AidOfficer"])
    case = require_path_resource("verification_cases", rid)
    if case["status"] != "DOCUMENTS_RECEIVED":
        raise_error(ERR_INVALID_STATE,
                    f"case is {case['status']}, expected DOCUMENTS_RECEIVED")
    case["status"] = "UNDER_REVIEW"
    touch(case)
    return success_object(public(case))


@bp.post("/verification-cases/<rid>/request-documents")
def request_documents(rid):
    authorized(["AidOfficer"])
    case = require_path_resource("verification_cases", rid)
    if case["status"] != "UNDER_REVIEW":
        raise_error(ERR_INVALID_STATE,
                    f"case is {case['status']}, expected UNDER_REVIEW")
    body = get_body()
    doc_types = body.get("doc_types")
    if not isinstance(doc_types, list) or not doc_types:
        raise_error(ERR_INVALID_REQUEST, "doc_types must be a non-empty array")
    for dt in doc_types:
        if not isinstance(dt, str) or dt not in ALL_DOC_TYPES:
            raise_error(ERR_INVALID_REQUEST, f"invalid doc_type: {dt}")
    docs = _case_documents(case["id"])
    for dt in doc_types:
        row = next((d for d in docs if d["doc_type"] == dt), None)
        if row is None:
            new_record("verification_documents", {
                "verification_case_id": case["id"],
                "doc_type": dt,
                "status": "REQUESTED",
                "rejection_reason": None,
                "received_at": None,
            })
        else:
            # Reset to REQUESTED; rejection_reason is preserved on previously
            # rejected rows as history.
            row["status"] = "REQUESTED"
            row["received_at"] = None
            touch(row)
    case["status"] = "DOCUMENTS_REQUESTED"
    touch(case)
    return success_object(public(case))


@bp.post("/verification-cases/<rid>/complete-satisfied")
def complete_satisfied(rid):
    authorized(["AidOfficer"])
    case = require_path_resource("verification_cases", rid)
    if case["status"] != "UNDER_REVIEW":
        raise_error(ERR_INVALID_STATE,
                    f"case is {case['status']}, expected UNDER_REVIEW")
    body = get_body()
    notes = req_str(body, "resolution_notes")
    verified_agi = opt_int(body, "verified_agi_cents", None, minimum=0)
    verified_untaxed = opt_int(body, "verified_untaxed_income_cents", None, minimum=0)
    verified_assets = opt_int(body, "verified_asset_net_worth_cents", None, minimum=0)
    verified_household = opt_int(body, "verified_household_size", None, minimum=1)
    verified_ncollege = opt_int(body, "verified_number_in_college", None, minimum=1)
    # Every required document type must be ACCEPTED.
    docs = _case_documents(case["id"])
    for doc_type in REQUIRED_DOC_TYPES:
        row = next((d for d in docs if d["doc_type"] == doc_type), None)
        if row is None or row["status"] != "ACCEPTED":
            raise_error(ERR_VERIFICATION_DOCS_INCOMPLETE,
                        f"required document {doc_type} is not ACCEPTED")
    # Federal rules forbid completing verification while a conflict is open.
    for conflict in db.conflicting_info_cases.values():
        if (conflict["student_id"] == case["student_id"]
                and conflict["aid_year_id"] == case["aid_year_id"]
                and conflict["status"] in OPEN_CONFLICT_STATUSES):
            raise_error(ERR_CONFLICTING_INFO_OPEN,
                        "a conflicting-information case is still open for this "
                        "student and aid year")

    # VERIFIED variant of the EFC: verified values default to the as-reported
    # import values of the linked ISIR record.
    isir = db.isir_records.get(case["isir_id"])
    student = db.students.get(case["student_id"])
    if isir is not None and student is not None:
        efc_verified = compute_efc(
            student["dependency_status"],
            verified_household if verified_household is not None else isir["household_size"],
            verified_ncollege if verified_ncollege is not None else isir["number_in_college"],
            verified_agi if verified_agi is not None else isir["agi_cents"],
            verified_untaxed if verified_untaxed is not None else isir["untaxed_income_cents"],
            verified_assets if verified_assets is not None else isir["asset_net_worth_cents"],
        )
        isir["efc_verified_cents"] = efc_verified
        isir["efc_official_cents"] = efc_verified
        touch(isir)

    case["status"] = "COMPLETED_SATISFIED"
    case["resolution_notes"] = notes
    case["completed_at"] = CLOCK.now_iso()
    touch(case)

    # A drift between the new official EFC and a package's frozen snapshots
    # flags needs_repack; existing lines are deliberately left untouched.
    maybe_mark_needs_repack(case["student_id"], case["aid_year_id"])
    return success_object(public(case))


@bp.post("/verification-cases/<rid>/complete-correction")
def complete_correction(rid):
    authorized(["AidOfficer"])
    case = require_path_resource("verification_cases", rid)
    if case["status"] != "UNDER_REVIEW":
        raise_error(ERR_INVALID_STATE,
                    f"case is {case['status']}, expected UNDER_REVIEW")
    body = get_body()
    notes = req_str(body, "resolution_notes")
    docs = _case_documents(case["id"])
    accepted_required = any(
        d["doc_type"] in REQUIRED_DOC_TYPES and d["status"] == "ACCEPTED"
        for d in docs)
    if not accepted_required:
        raise_error(ERR_INVALID_STATE,
                    "at least one required document must be ACCEPTED to complete "
                    "with a correction")
    case["status"] = "COMPLETED_CORRECTION_SENT"
    case["resolution_notes"] = notes
    touch(case)
    return success_object(public(case))


@bp.post("/verification-cases/<rid>/waive")
def waive(rid):
    authorized(["AidDirector"])
    case = require_path_resource("verification_cases", rid)
    if case["status"] not in ("DOCUMENTS_REQUESTED", "DOCUMENTS_RECEIVED", "UNDER_REVIEW"):
        raise_error(ERR_INVALID_STATE,
                    f"case is {case['status']}; only a non-terminal case may be waived")
    body = get_body()
    reason = req_str(body, "waived_reason")
    case["status"] = "WAIVED"
    case["waived_reason"] = reason
    case["completed_at"] = CLOCK.now_iso()
    touch(case)
    # Waiving lets the provisional figure stand.
    isir = db.isir_records.get(case["isir_id"])
    if isir is not None and isir["efc_official_cents"] != isir["efc_provisional_cents"]:
        isir["efc_official_cents"] = isir["efc_provisional_cents"]
        touch(isir)
    return success_object(public(case))


@bp.get("/verification-cases/<rid>/documents")
def list_case_documents(rid):
    authorized(DIRECTOR_OFFICER)
    require_path_resource("verification_cases", rid)
    return list_response("verification_documents", {"verification_case_id": rid})


# ---------------------------------------------------------------------------
# VerificationDocument
# ---------------------------------------------------------------------------

@bp.post("/verification-documents/<rid>/mark-received")
def mark_received(rid):
    authorized(["AidOfficer"])
    doc = require_path_resource("verification_documents", rid)
    if doc["status"] != "REQUESTED":
        raise_error(ERR_INVALID_STATE,
                    f"document is {doc['status']}, expected REQUESTED")
    doc["status"] = "RECEIVED"
    doc["received_at"] = CLOCK.now_iso()
    touch(doc)
    case = db.verification_cases.get(doc["verification_case_id"])
    if case is not None:
        _evaluate_auto_advance(case)
    return success_object(public(doc))


@bp.post("/verification-documents/<rid>/accept")
def accept_document(rid):
    authorized(["AidOfficer"])
    doc = require_path_resource("verification_documents", rid)
    if doc["status"] != "RECEIVED":
        raise_error(ERR_INVALID_STATE,
                    f"document is {doc['status']}, expected RECEIVED")
    doc["status"] = "ACCEPTED"
    touch(doc)
    case = db.verification_cases.get(doc["verification_case_id"])
    if case is not None:
        _evaluate_auto_advance(case)
    return success_object(public(doc))


@bp.post("/verification-documents/<rid>/reject")
def reject_document(rid):
    authorized(["AidOfficer"])
    doc = require_path_resource("verification_documents", rid)
    if doc["status"] != "RECEIVED":
        raise_error(ERR_INVALID_STATE,
                    f"document is {doc['status']}, expected RECEIVED")
    body = get_body()
    reason = req_str(body, "rejection_reason")
    doc["status"] = "REJECTED"
    doc["rejection_reason"] = reason
    touch(doc)
    return success_object(public(doc))


@bp.post("/verification-documents/<rid>/request-resubmission")
def request_resubmission(rid):
    authorized(["AidOfficer"])
    doc = require_path_resource("verification_documents", rid)
    if doc["status"] != "REJECTED":
        raise_error(ERR_INVALID_STATE,
                    f"document is {doc['status']}, expected REJECTED")
    doc["status"] = "REQUESTED"
    doc["received_at"] = None
    # The prior rejection_reason is retained as history.
    touch(doc)
    return success_object(public(doc))
