"""Verification documents: fetch, list, verify, reject (PRD 3.5, 3.6)."""
from datetime import timedelta
from flask import Blueprint, request

from db import db
from errors import (
    raise_error, ERR_DOCUMENT_NOT_FOUND, ERR_DOCUMENT_NOT_SUBMITTED,
    ERR_APPLICATION_TERMINAL, ERR_DOC_PERIOD_OVERLAP,
)
from middleware import authorized, check_ownership
from response import success_object
from routes.helpers import list_envelope, require
from services.core import create_notice, new_record, pinned_policy, public, touch
from util import CLOCK, fmt_dt
from validate import get_body, req_str

bp = Blueprint("documents", __name__)

DOC_READ = ["Patient", "FinancialCounselor", "AssistanceReviewer",
            "BillingAdministrator", "ComplianceOfficer"]
REVIEWABLE_STATUSES = ("SUBMITTED", "UNDER_REVIEW", "PENDING_DOCUMENTS")


def _doc_patient_id(doc):
    app = db["applications"].get(doc["application_id"])
    return app["patient_id"] if app else None


@bp.get("/charity-care/documents/<did>")
def get_document(did):
    caller = authorized(DOC_READ)
    doc = require("documents", did, ERR_DOCUMENT_NOT_FOUND)
    check_ownership(caller, _doc_patient_id(doc))
    return success_object(public(doc))


@bp.get("/charity-care/documents")
def list_documents():
    caller = authorized(DOC_READ)
    items = list(db["documents"].values())
    if caller.role == "Patient":
        items = [d for d in items if _doc_patient_id(d) == caller.user_id]
    application_id = request.args.get("application_id")
    household_member_id = request.args.get("household_member_id")
    status = request.args.get("status")
    if application_id is not None:
        items = [d for d in items if d["application_id"] == application_id]
    if household_member_id is not None:
        items = [d for d in items if d.get("household_member_id") == household_member_id]
    if status is not None:
        items = [d for d in items if d["status"] == status]
    return list_envelope(items, view=public)


@bp.post("/charity-care/documents/<did>/verify")
def verify_document(did):
    caller = authorized(["FinancialCounselor"])
    doc = require("documents", did, ERR_DOCUMENT_NOT_FOUND)
    if doc["status"] != "SUBMITTED":
        raise_error(ERR_DOCUMENT_NOT_SUBMITTED, "verify requires a SUBMITTED document")
    app = db["applications"].get(doc["application_id"])
    if app is None or app["status"] not in REVIEWABLE_STATUSES:
        raise_error(ERR_APPLICATION_TERMINAL,
                    "the owning application is not in a reviewable state")
    # Priority 11: BANK_STATEMENT closed-interval overlap vs VERIFIED statements
    # of the same household member; touching dates count as overlap.
    if doc["doc_type"] == "BANK_STATEMENT" and doc.get("household_member_id"):
        for other in db["documents"].values():
            if other["id"] == did:
                continue
            if (other["application_id"] == doc["application_id"]
                    and other["doc_type"] == "BANK_STATEMENT"
                    and other.get("household_member_id") == doc["household_member_id"]
                    and other["status"] == "VERIFIED"):
                if (doc["period_start"] <= other["period_end"]
                        and other["period_start"] <= doc["period_end"]):
                    raise_error(ERR_DOC_PERIOD_OVERLAP,
                                "bank statement period overlaps a VERIFIED statement of this member")
    doc["status"] = "VERIFIED"
    doc["verified_by_user_id"] = caller.user_id
    touch(doc)
    if app is not None:
        touch(app)
    return success_object(public(doc))


@bp.post("/charity-care/documents/<did>/reject")
def reject_document(did):
    authorized(["FinancialCounselor"])
    doc = require("documents", did, ERR_DOCUMENT_NOT_FOUND)
    if doc["status"] != "SUBMITTED":
        raise_error(ERR_DOCUMENT_NOT_SUBMITTED, "reject requires a SUBMITTED document")
    app = db["applications"].get(doc["application_id"])
    if app is None or app["status"] not in REVIEWABLE_STATUSES:
        raise_error(ERR_APPLICATION_TERMINAL,
                    "the owning application is not in a reviewable state")
    body = get_body()
    reason = req_str(body, "rejection_reason")
    doc["status"] = "REJECTED"
    doc["rejection_reason"] = reason
    touch(doc)
    # Cascade link 1: an UNDER_REVIEW application falls back to PENDING_DOCUMENTS
    if app is not None and app["status"] == "UNDER_REVIEW":
        requested = list(app["requested_doc_types"])
        if doc["doc_type"] not in requested:
            requested.append(doc["doc_type"])
        app["requested_doc_types"] = requested
        policy = pinned_policy(app)
        days = policy["doc_response_days"] if policy else 0
        app["doc_response_deadline"] = fmt_dt(CLOCK.now() + timedelta(days=days))
        app["status"] = "PENDING_DOCUMENTS"
        create_notice(account_id=None, application_id=app["id"],
                      notice_type="DOC_REQUEST", is_plain_language=True)
    if app is not None:
        touch(app)
    return success_object(public(doc))
