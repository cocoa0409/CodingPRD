"""De-identification keys, access grants, reveals."""
from datetime import timedelta

from flask import Blueprint, request

import db
from clock import parse_iso8601, now
from errors import raise_error
from middleware import (
    require_roles,
    get_json_body,
    check_known_fields,
    require_fields,
    validate_string,
    parse_pagination,
    ALL_ROLES,
)
from response import success_object, success_list
from serializers import key_out, grant_out
from services.common import make_record, get_or_404, touch

bp = Blueprint("keys", __name__)

GRANT_BUFFER = timedelta(hours=24)


@bp.route("/biobank/deidentification-keys", methods=["POST"])
def create_key():
    user_id, _ = require_roles({"ConsentCoordinator"})
    body = get_json_body()
    check_known_fields(body, {"specimen_id"})
    require_fields(body, ["specimen_id"])
    specimen_id = validate_string(body["specimen_id"], "specimen_id")
    specimen = db.specimens.get(specimen_id)
    if specimen is None:
        raise_error("ERR_NOT_FOUND", f"specimen not found: {specimen_id}")
    for k in db.deidentification_keys.values():
        if k["specimen_id"] == specimen_id and k["status"] != "REVOKED":
            raise_error("ERR_KEY_ALREADY_EXISTS", "Specimen already has a non-REVOKED key")
    key = make_record(db.deidentification_keys, {
        "specimen_id": specimen_id,
        "key_code": "key_" + db.new_id().replace("-", "")[:24],
        "holder_user_id": user_id,
        "status": "ACTIVE",
        "reveal_count": 0,
    })
    return success_object(key_out(key), status=201)


@bp.route("/biobank/deidentification-keys", methods=["GET"])
def list_keys():
    require_roles(ALL_ROLES)
    limit, offset = parse_pagination()
    items = list(db.deidentification_keys.values())
    specimen_id = request.args.get("specimen_id")
    status = request.args.get("status")
    if specimen_id is not None:
        items = [k for k in items if k["specimen_id"] == specimen_id]
    if status is not None:
        items = [k for k in items if k["status"] == status]
    items.sort(key=lambda k: k["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([key_out(k) for k in page], limit, offset, total)


@bp.route("/biobank/deidentification-keys/<keyId>", methods=["GET"])
def get_key(keyId):
    require_roles(ALL_ROLES)
    key = get_or_404(db.deidentification_keys, keyId, "deidentification key")
    return success_object(key_out(key))


@bp.route("/biobank/deidentification-keys/<id>/grants", methods=["POST"])
def create_grant(id):
    require_roles({"ConsentCoordinator"})
    key = get_or_404(db.deidentification_keys, id, "deidentification key")
    body = get_json_body()
    check_known_fields(body, {"grantee_user_id", "starts_at", "ends_at", "purpose"})
    require_fields(body, ["grantee_user_id", "starts_at", "ends_at", "purpose"])
    grantee = validate_string(body["grantee_user_id"], "grantee_user_id")
    starts_at = parse_iso8601(body["starts_at"], "starts_at")
    ends_at = parse_iso8601(body["ends_at"], "ends_at")
    purpose = validate_string(body["purpose"], "purpose")
    if ends_at <= starts_at:
        raise_error("ERR_INVALID_REQUEST", "ends_at must be strictly after starts_at")
    # Closed windows: touching counts as overlap; plus a 24h buffer on each side.
    for g in db.key_access_grants.values():
        if g["deidentification_key_id"] != key["id"]:
            continue
        # Overlap of closed windows [s,e]: s <= existing.ends_at and existing.starts_at <= e
        if starts_at <= g["ends_at"] and g["starts_at"] <= ends_at:
            raise_error("ERR_GRANT_WINDOW_CONFLICT", "Grant window overlaps an existing grant")
        # Buffer rule: gap on either side must be >= 24h.
        if ends_at < g["starts_at"]:
            gap = g["starts_at"] - ends_at
            if gap < GRANT_BUFFER:
                raise_error("ERR_GRANT_WINDOW_CONFLICT", "Grant window within 24h buffer of an existing grant")
        elif starts_at > g["ends_at"]:
            gap = starts_at - g["ends_at"]
            if gap < GRANT_BUFFER:
                raise_error("ERR_GRANT_WINDOW_CONFLICT", "Grant window within 24h buffer of an existing grant")
    grant = make_record(db.key_access_grants, {
        "deidentification_key_id": key["id"],
        "grantee_user_id": grantee,
        "starts_at": starts_at,
        "ends_at": ends_at,
        "purpose": purpose,
        "status": "ACTIVE",
    })
    return success_object(grant_out(grant), status=201)


@bp.route("/biobank/deidentification-keys/<id>/grants", methods=["GET"])
def list_grants(id):
    require_roles(ALL_ROLES)
    key = get_or_404(db.deidentification_keys, id, "deidentification key")
    limit, offset = parse_pagination()
    items = [g for g in db.key_access_grants.values() if g["deidentification_key_id"] == key["id"]]
    items.sort(key=lambda g: g["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([grant_out(g) for g in page], limit, offset, total)


@bp.route("/biobank/deidentification-keys/<keyId>/reveal", methods=["POST"])
def reveal_key(keyId):
    user_id, _ = require_roles({"QualityOfficer"})
    key = get_or_404(db.deidentification_keys, keyId, "deidentification key")
    body = get_json_body()
    check_known_fields(body, {"grant_id", "justification"})
    require_fields(body, ["grant_id", "justification"])
    grant_id = validate_string(body["grant_id"], "grant_id")
    justification = body["justification"]
    if not isinstance(justification, str):
        raise_error("ERR_INVALID_REQUEST", "justification must be a string")
    grant = db.key_access_grants.get(grant_id)
    if grant is None:
        raise_error("ERR_NOT_FOUND", f"key access grant not found: {grant_id}")
    # 1. Dual control.
    if grant["grantee_user_id"] == user_id:
        raise_error("ERR_SEGREGATION_OF_DUTIES", "Revealing officer must differ from the grant grantee")
    # 2. Justification length.
    if len(justification) < 20:
        raise_error("ERR_JUSTIFICATION_TOO_SHORT", "justification must be at least 20 characters")
    # 3. Terminal gate: key ACTIVE, grant on this key ACTIVE with window containing now,
    #    consent allow_reidentification true.
    if key["status"] != "ACTIVE":
        raise_error("ERR_KEY_NOT_ACTIVE", "De-identification key is not ACTIVE")
    current = now()
    active_covering = any(
        g["deidentification_key_id"] == key["id"]
        and g["status"] == "ACTIVE"
        and g["starts_at"] <= current <= g["ends_at"]
        for g in db.key_access_grants.values()
    )
    if not active_covering:
        raise_error("ERR_NO_ACTIVE_GRANT", "No ACTIVE grant window contains the current time")
    specimen = db.specimens.get(key["specimen_id"])
    consent = db.consent_records.get(specimen["consent_record_id"]) if specimen else None
    if consent is None or not consent["allow_reidentification"]:
        raise_error("ERR_NO_ACTIVE_GRANT", "Consent does not permit re-identification")
    key["reveal_count"] += 1
    touch(key)
    return success_object(key_out(key))
