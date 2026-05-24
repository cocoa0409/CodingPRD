"""DischargeApplication endpoints."""
from __future__ import annotations

import re

from flask import Blueprint, request

import db
from errors import (
    APIError,
    ERR_FORBIDDEN_ROLE,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_NOT_FOUND,
    ERR_NOT_RESOURCE_OWNER,
    ERR_NOT_VETERAN,
    ERR_SOD_VIOLATION,
    ERR_STALE_VERSION,
    ERR_VA_DOC_REQUIRED_OR_FORBIDDEN,
)
from middleware import current_role, current_user_id, require_roles
from response import success, success_list
from routes._common import (
    get_field,
    must_get,
    paginate_sorted,
    parse_json_body,
    parse_pagination,
)
from services import loan_ops, serializer

bp = Blueprint("discharge_applications", __name__)

VALID_DISCHARGE_TYPES = {
    "VETERAN_TOTAL_PERMANENT_DISABILITY",
    "PSLF_FORGIVENESS",
    "DEATH",
    "CLOSED_SCHOOL",
}

TERMINAL_LOAN_STATES = {"PAID_OFF", "DEFAULT", "DISCHARGED"}


@bp.post("/v1/discharge-applications")
@require_roles({"LoanServicer", "Borrower"})
def create_application():
    body = parse_json_body()
    borrower_id = get_field(body, "borrower_id")
    discharge_type = get_field(body, "discharge_type")
    filed_on = get_field(body, "filed_on")
    va_doc = body.get("va_certification_doc_id")

    borrower = must_get(db.borrowers, borrower_id, "Borrower")
    if current_role() == "Borrower" and current_user_id() != borrower_id:
        raise APIError(ERR_NOT_RESOURCE_OWNER, "Borrower does not own this resource")

    if discharge_type not in VALID_DISCHARGE_TYPES:
        raise APIError(ERR_INVALID_REQUEST, "Invalid discharge_type")
    if not isinstance(filed_on, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", filed_on):
        raise APIError(ERR_INVALID_REQUEST, "filed_on must be YYYY-MM-DD")

    # Priority 23: NOT_VETERAN check (before va_doc check per validation table)
    if discharge_type == "VETERAN_TOTAL_PERMANENT_DISABILITY":
        if borrower["military_status"] not in {"VETERAN", "DISABLED_VETERAN"}:
            raise APIError(ERR_NOT_VETERAN, "Borrower not VETERAN/DISABLED_VETERAN")

    # Priority 29: va_certification_doc_id required iff VETERAN
    if discharge_type == "VETERAN_TOTAL_PERMANENT_DISABILITY":
        if va_doc is None or not isinstance(va_doc, str) or not va_doc.strip():
            raise APIError(ERR_VA_DOC_REQUIRED_OR_FORBIDDEN, "va_certification_doc_id required for veteran discharge")
    else:
        if va_doc is not None:
            raise APIError(ERR_VA_DOC_REQUIRED_OR_FORBIDDEN, "va_certification_doc_id forbidden for non-veteran discharge")

    aid = db.new_id()
    now = db.now_iso()
    app = {
        "id": aid,
        "borrower_id": borrower_id,
        "discharge_type": discharge_type,
        "va_certification_doc_id": va_doc,
        "filed_on": filed_on,
        "status": "SUBMITTED",
        "approved_by_user_id": None,
        "total_discharged_principal_cents": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.discharge_applications[aid] = app
    return success(serializer.serialize_application(app), status=201)


def _role_matches_discharge_type(role: str, discharge_type: str) -> bool:
    if discharge_type == "VETERAN_TOTAL_PERMANENT_DISABILITY":
        return role == "VADischargeOfficer"
    if discharge_type == "PSLF_FORGIVENESS":
        return role == "PSLFAdjudicator"
    # DEATH, CLOSED_SCHOOL → neither role can adjudicate per scaffold; reject
    return False


@bp.post("/v1/discharge-applications/<app_id>/begin-review")
@require_roles({"VADischargeOfficer", "PSLFAdjudicator"})
def begin_review(app_id):
    app = must_get(db.discharge_applications, app_id, "DischargeApplication")
    if app["status"] != "SUBMITTED":
        raise APIError(ERR_INVALID_STATE, "Application not SUBMITTED")
    if not _role_matches_discharge_type(current_role(), app["discharge_type"]):
        raise APIError(ERR_FORBIDDEN_ROLE, "Role does not match discharge_type")
    app["status"] = "UNDER_REVIEW"
    serializer.bump_application(app)
    return success(serializer.serialize_application(app), status=200)


@bp.post("/v1/discharge-applications/<app_id>/approve")
@require_roles({"VADischargeOfficer", "PSLFAdjudicator"})
def approve(app_id):
    app = must_get(db.discharge_applications, app_id, "DischargeApplication")
    body = parse_json_body()
    expected_versions = get_field(body, "expected_loan_version_by_loan_id")
    if not isinstance(expected_versions, dict):
        raise APIError(ERR_INVALID_REQUEST, "expected_loan_version_by_loan_id must be an object")

    if app["status"] != "UNDER_REVIEW":
        raise APIError(ERR_INVALID_STATE, "Application not UNDER_REVIEW")
    if not _role_matches_discharge_type(current_role(), app["discharge_type"]):
        raise APIError(ERR_FORBIDDEN_ROLE, "Role does not match discharge_type")

    borrower = must_get(db.borrowers, app["borrower_id"], "Borrower")
    dtype = app["discharge_type"]

    if dtype == "VETERAN_TOTAL_PERMANENT_DISABILITY":
        if borrower["military_status"] not in {"VETERAN", "DISABLED_VETERAN"}:
            raise APIError(ERR_NOT_VETERAN, "Borrower not VETERAN/DISABLED_VETERAN")
        if not app.get("va_certification_doc_id"):
            raise APIError(ERR_VA_DOC_REQUIRED_OR_FORBIDDEN, "Missing va_certification_doc_id")
    elif dtype == "PSLF_FORGIVENESS":
        tracker = serializer.tracker_for_borrower(app["borrower_id"])
        if tracker is None or tracker["status"] != "ELIGIBLE_FOR_FORGIVENESS":
            raise APIError(ERR_INVALID_STATE, "PSLFTracker not ELIGIBLE_FOR_FORGIVENESS")
        # Priority 12: SoD — acting user must not have recorded any contributing payment
        acting = current_user_id()
        # We need the list of payments that contributed to qualifying_payment_count.
        # Per the relaxed recount, this is every Payment with pslf_qualifying=True
        # for any loan of this borrower.
        borrower_loan_ids = {l["id"] for l in db.loans.values() if l["borrower_id"] == app["borrower_id"]}
        contributing = [
            p for p in db.payments.values()
            if p["loan_id"] in borrower_loan_ids and p.get("pslf_qualifying", False)
        ]
        for p in contributing:
            if p["recorded_by_user_id"] == acting:
                raise APIError(ERR_SOD_VIOLATION, "SoD: adjudicator recorded a contributing payment")

    # OCC check (priority 40 — last gate)
    # Per PRD §2.5: expected_loan_version_by_loan_id maps each non-terminal loan_id of
    # the borrower → observed version. Mismatch on any → ERR_STALE_VERSION.
    borrower_loans = [l for l in db.loans.values() if l["borrower_id"] == app["borrower_id"]]
    non_terminal = [l for l in borrower_loans if l["status"] not in TERMINAL_LOAN_STATES]
    # Validate each non-terminal loan's expected version
    for loan in non_terminal:
        observed = expected_versions.get(loan["id"])
        if observed is None:
            raise APIError(ERR_STALE_VERSION, f"Missing expected_loan_version for loan {loan['id']}")
        if not isinstance(observed, int) or isinstance(observed, bool):
            raise APIError(ERR_INVALID_REQUEST, "expected_loan_version must be int")
        if observed != loan["version"]:
            raise APIError(ERR_STALE_VERSION, f"Stale version for loan {loan['id']}")

    # Snapshot pre-cascade sum of outstanding_principal_cents across non-terminal loans
    total_discharged = sum(l["outstanding_principal_cents"] for l in non_terminal)

    # Cascade — each non-terminal loan → DISCHARGED
    now_clock = db.get_clock_date()
    for loan in non_terminal:
        loan_ops.transition_to_discharged(loan, now_clock, current_user_id())

    # Stamp on the application
    app["status"] = "APPROVED"
    app["approved_by_user_id"] = current_user_id()
    app["total_discharged_principal_cents"] = total_discharged
    serializer.bump_application(app)

    # Bubble-up borrower status
    serializer.recompute_borrower(app["borrower_id"])

    # If PSLF, advance the tracker → FORGIVEN
    if dtype == "PSLF_FORGIVENESS":
        tracker = serializer.tracker_for_borrower(app["borrower_id"])
        if tracker:
            tracker["status"] = "FORGIVEN"
            serializer.bump_tracker(tracker)

    return success(serializer.serialize_application(app), status=200)


@bp.post("/v1/discharge-applications/<app_id>/deny")
@require_roles({"VADischargeOfficer", "PSLFAdjudicator"})
def deny(app_id):
    app = must_get(db.discharge_applications, app_id, "DischargeApplication")
    if app["status"] != "UNDER_REVIEW":
        raise APIError(ERR_INVALID_STATE, "Application not UNDER_REVIEW")
    if not _role_matches_discharge_type(current_role(), app["discharge_type"]):
        raise APIError(ERR_FORBIDDEN_ROLE, "Role does not match discharge_type")
    app["status"] = "DENIED"
    serializer.bump_application(app)
    return success(serializer.serialize_application(app), status=200)


@bp.get("/v1/discharge-applications/<app_id>")
@require_roles({"LoanServicer", "VADischargeOfficer", "PSLFAdjudicator", "Borrower"})
def get_application(app_id):
    app = must_get(db.discharge_applications, app_id, "DischargeApplication")
    if current_role() == "Borrower" and current_user_id() != app["borrower_id"]:
        raise APIError(ERR_NOT_RESOURCE_OWNER, "Borrower does not own this application")
    return success(serializer.serialize_application(app), status=200)


@bp.get("/v1/discharge-applications")
@require_roles({"LoanServicer", "VADischargeOfficer", "PSLFAdjudicator", "Borrower"})
def list_applications():
    limit, offset = parse_pagination()
    borrower_filter = request.args.get("borrower_id")
    status_filter = request.args.get("status")
    items = list(db.discharge_applications.values())
    if current_role() == "Borrower":
        items = [a for a in items if a["borrower_id"] == current_user_id()]
    if borrower_filter:
        items = [a for a in items if a["borrower_id"] == borrower_filter]
    if status_filter:
        items = [a for a in items if a["status"] == status_filter]
    items.sort(key=lambda a: a["created_at"])
    page, total = paginate_sorted(items, limit, offset)
    return success_list([serializer.serialize_application(a) for a in page], limit, offset, total)
