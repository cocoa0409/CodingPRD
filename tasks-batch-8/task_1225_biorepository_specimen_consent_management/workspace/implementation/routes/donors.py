"""Donor + consent record endpoints."""
from flask import Blueprint, request

import db
from clock import parse_iso8601, now
from errors import raise_error
from middleware import (
    require_roles,
    get_json_body,
    check_known_fields,
    require_fields,
    validate_use_list,
    validate_bool,
    validate_string,
    parse_pagination,
    ALL_ROLES,
)
from response import success_object, success_list
from serializers import donor_out, consent_out
from services.common import make_record, get_or_404, touch

bp = Blueprint("donors", __name__)


@bp.route("/biobank/donors", methods=["POST"])
def create_donor():
    require_roles({"ConsentCoordinator"})
    body = get_json_body()
    check_known_fields(body, {"donor_reference_code"})
    require_fields(body, ["donor_reference_code"])
    code = validate_string(body["donor_reference_code"], "donor_reference_code")
    donor = make_record(db.donors, {
        "donor_reference_code": code,
        "status": "ENROLLED",
    })
    return success_object(donor_out(donor), status=201)


@bp.route("/biobank/donors/<donorId>", methods=["GET"])
def get_donor(donorId):
    require_roles(ALL_ROLES)
    donor = get_or_404(db.donors, donorId, "donor")
    return success_object(donor_out(donor))


@bp.route("/biobank/donors/<donorId>/consent-records", methods=["POST"])
def create_consent(donorId):
    require_roles({"ConsentCoordinator"})
    donor = get_or_404(db.donors, donorId, "donor")
    body = get_json_body()
    check_known_fields(body, {"permitted_uses", "excluded_uses", "allow_reidentification", "effective_from"})
    require_fields(body, ["permitted_uses", "effective_from"])
    permitted = validate_use_list(body["permitted_uses"], "permitted_uses", non_empty=True)
    excluded = body.get("excluded_uses", [])
    excluded = validate_use_list(excluded, "excluded_uses", non_empty=False)
    allow_reid = body.get("allow_reidentification", False)
    validate_bool(allow_reid, "allow_reidentification")
    effective_from = parse_iso8601(body["effective_from"], "effective_from")
    consent = make_record(db.consent_records, {
        "donor_id": donor["id"],
        "permitted_uses": list(permitted),
        "excluded_uses": list(excluded),
        "allow_reidentification": allow_reid,
        "effective_from": effective_from,
        "status": "ACTIVE",
        "withdrawal_requested_at": None,
        "grace_deadline": None,
        "supersedes_consent_id": None,
    })
    return success_object(consent_out(consent), status=201)


@bp.route("/biobank/consent-records", methods=["GET"])
def list_consents():
    require_roles(ALL_ROLES)
    limit, offset = parse_pagination()
    items = list(db.consent_records.values())
    donor_id = request.args.get("donor_id")
    supersedes = request.args.get("supersedes_consent_id")
    status = request.args.get("status")
    if donor_id is not None:
        items = [c for c in items if c["donor_id"] == donor_id]
    if supersedes is not None:
        items = [c for c in items if c["supersedes_consent_id"] == supersedes]
    if status is not None:
        items = [c for c in items if c["status"] == status]
    items.sort(key=lambda c: c["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([consent_out(c) for c in page], limit, offset, total)


@bp.route("/biobank/donors/<donorId>/consent-records", methods=["GET"])
def list_donor_consents(donorId):
    require_roles(ALL_ROLES)
    get_or_404(db.donors, donorId, "donor")
    limit, offset = parse_pagination()
    items = [c for c in db.consent_records.values() if c["donor_id"] == donorId]
    items.sort(key=lambda c: c["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([consent_out(c) for c in page], limit, offset, total)


@bp.route("/biobank/consent-records/<consentId>", methods=["GET"])
def get_consent(consentId):
    require_roles(ALL_ROLES)
    consent = get_or_404(db.consent_records, consentId, "consent record")
    return success_object(consent_out(consent))


@bp.route("/biobank/consent-records/<consentId>/withdraw", methods=["POST"])
def withdraw_consent(consentId):
    require_roles({"ConsentCoordinator"})
    consent = get_or_404(db.consent_records, consentId, "consent record")
    get_json_body()
    if consent["status"] != "ACTIVE" or now() < consent["effective_from"]:
        raise_error("ERR_CONSENT_NOT_ACTIVE", "Consent must be ACTIVE and effective to withdraw")
    from datetime import timedelta
    consent["status"] = "WITHDRAWAL_PENDING"
    consent["withdrawal_requested_at"] = now()
    consent["grace_deadline"] = now() + timedelta(hours=72)
    touch(consent)
    return success_object(consent_out(consent))


@bp.route("/biobank/consent-records/<consentId>/rescind-withdrawal", methods=["POST"])
def rescind_withdrawal(consentId):
    require_roles({"ConsentCoordinator"})
    consent = get_or_404(db.consent_records, consentId, "consent record")
    get_json_body()
    if consent["status"] != "WITHDRAWAL_PENDING":
        raise_error("ERR_CONSENT_NOT_ACTIVE", "Consent is not WITHDRAWAL_PENDING")
    if now() >= consent["grace_deadline"]:
        raise_error("ERR_WITHDRAWAL_GRACE_EXPIRED", "Grace deadline has passed")
    consent["status"] = "ACTIVE"
    consent["withdrawal_requested_at"] = None
    consent["grace_deadline"] = None
    touch(consent)
    return success_object(consent_out(consent))


@bp.route("/biobank/consent-records/<consentId>/amendments", methods=["POST"])
def amend_consent(consentId):
    require_roles({"ConsentCoordinator"})
    consent = get_or_404(db.consent_records, consentId, "consent record")
    body = get_json_body()
    check_known_fields(body, {
        "permitted_uses", "excluded_uses", "allow_reidentification",
        "effective_from", "expected_consent_record_version",
    })
    require_fields(body, ["permitted_uses", "effective_from", "expected_consent_record_version"])
    # OCC check runs before any state/business rule (priority 3.5).
    expected = body["expected_consent_record_version"]
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise_error("ERR_INVALID_REQUEST", "expected_consent_record_version must be an integer")
    if expected != consent["version"]:
        raise_error("ERR_STALE_VERSION", "expected_consent_record_version does not match current version")
    permitted = validate_use_list(body["permitted_uses"], "permitted_uses", non_empty=True)
    excluded = validate_use_list(body.get("excluded_uses", []), "excluded_uses", non_empty=False)
    allow_reid = body.get("allow_reidentification", False)
    validate_bool(allow_reid, "allow_reidentification")
    effective_from = parse_iso8601(body["effective_from"], "effective_from")
    if consent["status"] != "ACTIVE":
        raise_error("ERR_CONSENT_NOT_ACTIVE", "Consent must be ACTIVE to amend")
    new_consent = make_record(db.consent_records, {
        "donor_id": consent["donor_id"],
        "permitted_uses": list(permitted),
        "excluded_uses": list(excluded),
        "allow_reidentification": allow_reid,
        "effective_from": effective_from,
        "status": "ACTIVE",
        "withdrawal_requested_at": None,
        "grace_deadline": None,
        "supersedes_consent_id": consent["id"],
    })
    consent["status"] = "SUPERSEDED"
    touch(consent)
    return success_object(consent_out(new_consent), status=201)
