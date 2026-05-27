"""ConsentDisclosure endpoints and lifecycle transitions."""

from flask import Blueprint

from db import db, parse_iso
from errors import raise_api
from middleware import require_roles
from response import success, list_success
from util import (
    stamp_common_create, stamp_update, get_consent, get_application,
    get_json_body, require_fields, check_occ, page, sort_by_created_at,
)
from services.audit import append_audit


bp = Blueprint("consents", __name__)


def _serialize(c):
    return {
        "id": c["id"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
        "application_id": c["application_id"],
        "disclosure_text_version": c["disclosure_text_version"],
        "signed_at": c["signed_at"],
        "ip_address": c["ip_address"],
        "consent_status": c["consent_status"],
    }


@bp.route("/api/v1/consents", methods=["POST"])
@require_roles("Applicant")
def create_consent(_user_id, _role):
    body = get_json_body()
    require_fields(body, "application_id", "disclosure_text_version", "signed_at", "ip_address")
    application_id = body["application_id"]
    disclosure_text_version = body["disclosure_text_version"]
    signed_at = body["signed_at"]
    ip_address = body["ip_address"]
    get_application(application_id)
    if not isinstance(disclosure_text_version, str):
        raise_api("ERR_INVALID_REQUEST", "disclosure_text_version must be a string")
    if not isinstance(signed_at, str):
        raise_api("ERR_INVALID_REQUEST", "signed_at must be ISO 8601 string")
    try:
        parse_iso(signed_at)
    except Exception:
        raise_api("ERR_INVALID_REQUEST", "signed_at must be ISO 8601")
    if not isinstance(ip_address, str):
        raise_api("ERR_INVALID_REQUEST", "ip_address must be a string")
    # At most one PENDING/GRANTED consent per application
    for c in db.consents.values():
        if c["application_id"] == application_id and c["consent_status"] in {"PENDING", "GRANTED"}:
            raise_api("ERR_CONSENT_ALREADY_OPEN", "Another open consent already exists for this application")
    c = {
        "application_id": application_id,
        "disclosure_text_version": disclosure_text_version,
        "signed_at": signed_at,
        "ip_address": ip_address,
        "consent_status": "PENDING",
    }
    stamp_common_create(c)
    db.consents[c["id"]] = c
    return success(_serialize(c), 201)


@bp.route("/api/v1/consents/<cid>", methods=["GET"])
@require_roles("Applicant", "Recruiter", "ComplianceOfficer")
def get_consent_route(cid, _user_id, _role):
    c = get_consent(cid)
    return success(_serialize(c))


@bp.route("/api/v1/applications/<aid>/consents", methods=["GET"])
@require_roles("Applicant", "Recruiter", "ComplianceOfficer")
def list_consents_for_application(aid, _user_id, _role):
    # Path validation left-to-right: application must resolve first.
    get_application(aid)
    from util import parse_pagination
    limit, offset = parse_pagination()
    items = [c for c in db.consents.values() if c["application_id"] == aid]
    items = sort_by_created_at(items)
    page_items, total = page(items, limit, offset)
    return list_success([_serialize(c) for c in page_items], limit, offset, total)


@bp.route("/api/v1/consents/<cid>/grant", methods=["POST"])
@require_roles("Applicant")
def grant_consent(cid, _user_id, _role):
    c = get_consent(cid)
    body = get_json_body()
    if c["consent_status"] != "PENDING":
        raise_api("ERR_INVALID_STATE", "Consent must be PENDING to grant")
    check_occ(body, "expected_consent_disclosure_version", c["version"])
    # signed_at <= current_utc
    try:
        signed_dt = parse_iso(c["signed_at"])
    except Exception:
        raise_api("ERR_INVALID_STATE", "Consent has invalid signed_at")
    if signed_dt > db.current_utc_dt():
        raise_api("ERR_INVALID_STATE", "Cannot grant a future-signed consent")
    prior = c["consent_status"]
    c["consent_status"] = "GRANTED"
    stamp_update(c)
    append_audit(_role, _user_id, "CONSENT_GRANT", "ConsentDisclosure", c["id"], prior, c["consent_status"])
    return success(_serialize(c))


@bp.route("/api/v1/consents/<cid>/revoke", methods=["POST"])
@require_roles("Applicant")
def revoke_consent(cid, _user_id, _role):
    c = get_consent(cid)
    body = get_json_body()
    if c["consent_status"] != "GRANTED":
        raise_api("ERR_INVALID_STATE", "Consent must be GRANTED to revoke")
    check_occ(body, "expected_consent_disclosure_version", c["version"])
    # ERR_CONSENT_REVOKE_TOO_LATE: any child order in {IN_REVIEW, COMPLETE}
    related_orders = [o for o in db.orders.values() if o.get("consent_id") == cid]
    for o in related_orders:
        if o["status"] in {"IN_REVIEW", "COMPLETE"}:
            raise_api("ERR_CONSENT_REVOKE_TOO_LATE", "Cannot revoke after a child order is in review or complete")
    prior = c["consent_status"]
    c["consent_status"] = "REVOKED"
    stamp_update(c)
    append_audit(_role, _user_id, "CONSENT_REVOKE", "ConsentDisclosure", c["id"], prior, c["consent_status"])
    # Cascade: any PENDING order for this consent -> CANCELLED, PENDING children -> RESOLVED with result=null
    for o in related_orders:
        if o["status"] == "PENDING":
            o["status"] = "CANCELLED"
            stamp_update(o)
            for v in db.verifications.values():
                if v["order_id"] == o["id"] and v["status"] == "PENDING":
                    v["status"] = "RESOLVED"
                    v["result"] = None
                    stamp_update(v)
    return success(_serialize(c))
