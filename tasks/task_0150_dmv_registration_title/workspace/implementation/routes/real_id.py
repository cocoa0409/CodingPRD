"""REAL ID Application endpoints — submit/start-review/approve/reject/resubmit/revoke."""

from flask import Blueprint, g

from config import (
    APPROVAL_THRESHOLD,
    REALID_APPROVED,
    REALID_APPROVED_EXPIRY_YEARS,
    REALID_DOC_REJECTED,
    REALID_DOC_REVIEW,
    REALID_MAX_REVISIONS,
    REALID_REVOKED,
    REALID_SUBMITTED,
    REAL_ID_APPROVED,
    REAL_ID_PENDING,
    REAL_ID_REVOKED,
    ROLE_APPLICANT,
    ROLE_PLATFORM_ADMIN,
    ROLE_REAL_ID_REVIEWER,
)
from db import store
from errors import make_error
from middleware import parse_json_body, require_auth
from response import success
from routes._helpers import check_occ, require_bool, require_field
from services.calculations import real_id_eligibility_score
from services.engine import (
    cascade_realid_revocation,
    stamp_create,
    stamp_update,
)
from services.serializers import serialize_realid_application
from utils import add_years_calendar, iso_format, new_uuid, parse_iso_date

real_id_bp = Blueprint("real_id", __name__)


@real_id_bp.route("/owners/<owner_id>/real-id-applications", methods=["POST"])
@require_auth(allowed_roles=[ROLE_APPLICANT])
def submit_realid(owner_id: str):
    body = parse_json_body()
    doc_id = require_bool(require_field(body, "documents_proof_of_identity"),
                          "documents_proof_of_identity")
    doc_res = require_bool(require_field(body, "documents_proof_of_residency"),
                           "documents_proof_of_residency")
    doc_ssn = require_bool(require_field(body, "documents_proof_of_ssn"),
                           "documents_proof_of_ssn")

    with store.lock:
        owner = store.owners.get(owner_id)
        if owner is None:
            raise make_error("ERR_RESOURCE_NOT_FOUND")
        # Ownership: applicant must match owner_id
        if g.user_role == ROLE_APPLICANT and g.user_id != owner_id:
            raise make_error("ERR_ROLE_FORBIDDEN")

        app = {
            "owner_id": owner_id,
            "status": REALID_SUBMITTED,
            "documents_proof_of_identity": doc_id,
            "documents_proof_of_residency": doc_res,
            "documents_proof_of_ssn": doc_ssn,
            "revision_count": 0,
            "approved_at": None,
        }
        stamp_create(app, now=store.now())
        store.real_id_applications[app["id"]] = app

        # Side effect: Owner.real_id_status := PENDING
        owner["real_id_status"] = REAL_ID_PENDING
        stamp_update(owner, now=store.now())

    return success(serialize_realid_application(app), status=201)


def _get_app_or_404(app_id: str) -> dict:
    app = store.real_id_applications.get(app_id)
    if app is None:
        raise make_error("ERR_RESOURCE_NOT_FOUND")
    return app


@real_id_bp.route("/real-id-applications/<app_id>/start-review", methods=["POST"])
@require_auth(allowed_roles=[ROLE_REAL_ID_REVIEWER])
def start_review(app_id: str):
    parse_json_body()
    with store.lock:
        app = _get_app_or_404(app_id)
        if app["status"] != REALID_SUBMITTED:
            raise make_error("ERR_INVALID_STATE")
        # Precondition: all three document booleans must be true
        if not (app["documents_proof_of_identity"] and app["documents_proof_of_residency"]
                and app["documents_proof_of_ssn"]):
            raise make_error("ERR_INVALID_STATE",
                             "All three document attachments must be true to start review.")
        app["status"] = REALID_DOC_REVIEW
        stamp_update(app, now=store.now())
    return success(serialize_realid_application(app))


def _compute_score(app: dict) -> "Decimal":
    owner = store.owners.get(app["owner_id"])
    if owner is None:
        raise make_error("ERR_RESOURCE_NOT_FOUND")
    dob_dt = parse_iso_date(owner["date_of_birth"])
    return real_id_eligibility_score(
        app["documents_proof_of_identity"],
        app["documents_proof_of_residency"],
        app["documents_proof_of_ssn"],
        dob_dt,
        store.now(),
        app["revision_count"],
    )


@real_id_bp.route("/real-id-applications/<app_id>/approve", methods=["POST"])
@require_auth(allowed_roles=[ROLE_REAL_ID_REVIEWER])
def approve_realid(app_id: str):
    parse_json_body()
    with store.lock:
        app = _get_app_or_404(app_id)
        if app["status"] != REALID_DOC_REVIEW:
            raise make_error("ERR_INVALID_STATE")
        score = _compute_score(app)
        if score < APPROVAL_THRESHOLD:
            raise make_error("ERR_INVALID_STATE",
                             "REAL ID eligibility score below approval threshold.")
        owner = store.owners[app["owner_id"]]
        app["status"] = REALID_APPROVED
        app["approved_at"] = iso_format(store.now())
        stamp_update(app, now=store.now())

        owner["real_id_status"] = REAL_ID_APPROVED
        owner["real_id_score"] = score
        owner["real_id_expires_at"] = iso_format(
            add_years_calendar(store.now(), REALID_APPROVED_EXPIRY_YEARS))
        stamp_update(owner, now=store.now())
    return success(serialize_realid_application(app))


@real_id_bp.route("/real-id-applications/<app_id>/reject", methods=["POST"])
@require_auth(allowed_roles=[ROLE_REAL_ID_REVIEWER])
def reject_realid(app_id: str):
    parse_json_body()
    with store.lock:
        app = _get_app_or_404(app_id)
        if app["status"] != REALID_DOC_REVIEW:
            raise make_error("ERR_INVALID_STATE")
        score = _compute_score(app)
        if score >= APPROVAL_THRESHOLD:
            raise make_error("ERR_INVALID_STATE",
                             "REAL ID eligibility score is at or above approval threshold.")
        owner = store.owners[app["owner_id"]]
        app["status"] = REALID_DOC_REJECTED
        stamp_update(app, now=store.now())
        # Side effect: Owner.real_id_status rolled back to PENDING
        owner["real_id_status"] = REAL_ID_PENDING
        stamp_update(owner, now=store.now())
    return success(serialize_realid_application(app))


@real_id_bp.route("/real-id-applications/<app_id>/resubmit", methods=["PATCH"])
@require_auth(allowed_roles=[ROLE_APPLICANT])
def resubmit_realid(app_id: str):
    body = parse_json_body()
    doc_id = require_bool(require_field(body, "documents_proof_of_identity"),
                          "documents_proof_of_identity")
    doc_res = require_bool(require_field(body, "documents_proof_of_residency"),
                           "documents_proof_of_residency")
    doc_ssn = require_bool(require_field(body, "documents_proof_of_ssn"),
                           "documents_proof_of_ssn")

    with store.lock:
        app = _get_app_or_404(app_id)
        # Ownership
        if g.user_id != app["owner_id"]:
            raise make_error("ERR_ROLE_FORBIDDEN")
        if app["status"] != REALID_DOC_REJECTED:
            raise make_error("ERR_INVALID_STATE")
        # Priority 15 (BEFORE OCC at priority 20): revision limit
        if app["revision_count"] >= REALID_MAX_REVISIONS:
            raise make_error("ERR_REVISION_LIMIT_EXCEEDED")
        # OCC
        check_occ(body, app)

        app["documents_proof_of_identity"] = doc_id
        app["documents_proof_of_residency"] = doc_res
        app["documents_proof_of_ssn"] = doc_ssn
        app["revision_count"] = app["revision_count"] + 1
        app["status"] = REALID_SUBMITTED
        stamp_update(app, now=store.now())
    return success(serialize_realid_application(app))


@real_id_bp.route("/real-id-applications/<app_id>/revoke", methods=["POST"])
@require_auth(allowed_roles=[ROLE_PLATFORM_ADMIN])
def revoke_realid(app_id: str):
    parse_json_body()
    with store.lock:
        app = _get_app_or_404(app_id)
        if app["status"] != REALID_APPROVED:
            raise make_error("ERR_INVALID_STATE")
        owner = store.owners.get(app["owner_id"])
        if owner is None:
            raise make_error("ERR_RESOURCE_NOT_FOUND")
        app["status"] = REALID_REVOKED
        stamp_update(app, now=store.now())
        owner["real_id_status"] = REAL_ID_REVOKED
        stamp_update(owner, now=store.now())
        # Cascade: ACTIVE plates on this owner's vehicles -> SUSPENDED
        cascade_realid_revocation(owner["id"], now=store.now())
    return success(serialize_realid_application(app))
