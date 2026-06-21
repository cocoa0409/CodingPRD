"""Credential item single-resource, reverify, and verification requests."""
from flask import Blueprint, request

from db import store
from errors import err
from middleware import require_auth, require_role
from response import success_array, success_object
from services.common import (
    parse_pagination,
    paginate,
    require_body,
    sort_by_created,
)
from services.lookups import get_credential_item, get_verification_request, get_provider
from services.model import make_record, serialize, touch
from services.posture import recompute_provider

bp = Blueprint("verification", __name__)


# ---------------------------------------------------------------------------
# Credential item single resource & reverify
# ---------------------------------------------------------------------------
@bp.route("/credential-items/<rid>", methods=["GET"])
def get_credential_item_route(rid):
    _, role = require_auth()
    require_role(role, {"CredentialingSpecialist", "MedicalDirector",
                        "ComplianceOfficer", "SystemAdmin"})
    rec = get_credential_item(rid)
    return success_object(serialize(rec), 200)


@bp.route("/credential-items/<rid>/reverify", methods=["POST"])
def reverify(rid):
    _, role = require_auth()
    require_role(role, {"CredentialingSpecialist"})
    item = get_credential_item(rid)

    if item["verification_state"] != "REJECTED":
        raise err("ERR_ITEM_NOT_REJECTED", "Credential item is not REJECTED.")

    item["verification_state"] = "PENDING_PSV"
    touch(item)
    # fresh OPEN VerificationRequest
    make_record("verification_requests", {
        "credential_item_id": item["id"],
        "provider_id": item["provider_id"],
        "method": "PRIMARY_SOURCE",
        "source_reference": "",
        "status": "OPEN",
        "verified_at": None,
    })
    return success_object(serialize(item), 200)


# ---------------------------------------------------------------------------
# Verification requests
# ---------------------------------------------------------------------------
@bp.route("/credential-items/<rid>/verification-requests", methods=["POST"])
def create_verification_request(rid):
    _, role = require_auth()
    require_role(role, {"CredentialingSpecialist"})
    item = get_credential_item(rid)
    body = require_body()

    method = body.get("method")
    if method not in ("PRIMARY_SOURCE", "DESIGNATED_AGENT"):
        raise err("ERR_INVALID_REQUEST", "method must be PRIMARY_SOURCE or DESIGNATED_AGENT.")
    source_reference = body.get("source_reference")
    if not isinstance(source_reference, str) or source_reference.strip() == "":
        raise err("ERR_INVALID_REQUEST", "source_reference is required.")

    rec = make_record("verification_requests", {
        "credential_item_id": item["id"],
        "provider_id": item["provider_id"],
        "method": method,
        "source_reference": source_reference,
        "status": "OPEN",
        "verified_at": None,
    })
    return success_object(serialize(rec), 201)


@bp.route("/credential-items/<rid>/verification-requests", methods=["GET"])
def list_item_verification_requests(rid):
    _, role = require_auth()
    require_role(role, {"CredentialingSpecialist", "MedicalDirector",
                        "ComplianceOfficer", "SystemAdmin"})
    get_credential_item(rid)
    limit, offset = parse_pagination()
    rows = [v for v in store.verification_requests.values()
            if v["credential_item_id"] == rid]
    rows = sort_by_created(rows)
    page, total = paginate(rows, limit, offset)
    return success_array([serialize(r) for r in page], limit, offset, total, 200)


@bp.route("/verification-requests", methods=["GET"])
def list_verification_requests():
    _, role = require_auth()
    require_role(role, {"CredentialingSpecialist", "MedicalDirector",
                        "ComplianceOfficer", "SystemAdmin"})
    provider_id = request.args.get("provider_id")
    limit, offset = parse_pagination()
    rows = [v for v in store.verification_requests.values()
            if provider_id is None or v["provider_id"] == provider_id]
    rows = sort_by_created(rows)
    page, total = paginate(rows, limit, offset)
    return success_array([serialize(r) for r in page], limit, offset, total, 200)


@bp.route("/verification-requests/<rid>", methods=["GET"])
def get_verification_request_route(rid):
    _, role = require_auth()
    require_role(role, {"CredentialingSpecialist", "MedicalDirector",
                        "ComplianceOfficer", "SystemAdmin"})
    rec = get_verification_request(rid)
    return success_object(serialize(rec), 200)


@bp.route("/verification-requests/<rid>/complete", methods=["POST"])
def complete_verification(rid):
    _, role = require_auth()
    require_role(role, {"CredentialingSpecialist"})
    vr = get_verification_request(rid)
    body = require_body()

    outcome = body.get("outcome")
    if outcome not in ("PASS", "FAIL"):
        raise err("ERR_INVALID_REQUEST", "outcome must be PASS or FAIL.")

    if vr["status"] != "OPEN":
        raise err("ERR_VERIFICATION_NOT_OPEN", "Verification request is not OPEN.")

    item = store.credential_items.get(vr["credential_item_id"])

    if outcome == "PASS":
        if item is not None and item["expirable_band"] == "LAPSED":
            raise err("ERR_CREDENTIAL_LAPSED", "Cannot pass a lapsed credential.")

    prov = store.providers.get(vr["provider_id"])
    org = store.orgs.get(prov["org_id"]) if prov else None
    now_clock = org["current_utc"] if org else None

    if outcome == "PASS":
        vr["status"] = "COMPLETED_PASS"
        vr["verified_at"] = now_clock
        touch(vr)
        if item is not None:
            item["verification_state"] = "VERIFIED"
            touch(item)
    else:
        vr["status"] = "COMPLETED_FAIL"
        vr["verified_at"] = now_clock
        touch(vr)
        if item is not None:
            item["verification_state"] = "REJECTED"
            touch(item)

    if prov is not None:
        recompute_provider(prov, recompute_readiness=True)
    return success_object(serialize(vr), 200)
