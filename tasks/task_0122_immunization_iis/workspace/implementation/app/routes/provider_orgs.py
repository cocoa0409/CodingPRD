"""ProviderOrganization routes."""
from __future__ import annotations

from flask import Blueprint, jsonify

from .. import store
from ..auth import require_roles
from ..errors import APIError
from ..helpers import (
    check_version_conflict,
    ensure_enum,
    parse_json_body,
    require_field,
    validate_npi,
)
from ..responses import build_envelope
from ..services.calculations import compute_provider_compliance_score


bp = Blueprint("provider_orgs", __name__)


JURISDICTIONS = {"IN_STATE", "OUT_OF_STATE"}


def _serialize(p: dict) -> dict:
    return {
        "id": p["id"],
        "name": p["name"],
        "npi": p["npi"],
        "reporting_jurisdiction": p["reporting_jurisdiction"],
        "reporting_compliance_score": p["reporting_compliance_score"],
        "status": p["status"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


@bp.post("/provider-organizations")
@require_roles(["PublicHealthOfficer"])
def create_provider():
    body = parse_json_body()
    name = require_field(body, "name")
    if not isinstance(name, str) or not name:
        raise APIError("ERR_VALIDATION", "name must be a non-empty string.")
    npi = validate_npi(require_field(body, "npi"))
    for existing in store.provider_organizations.values():
        if existing["npi"] == npi:
            raise APIError("ERR_VALIDATION", "npi must be unique.")
    jurisdiction = ensure_enum(require_field(body, "reporting_jurisdiction"), JURISDICTIONS, "reporting_jurisdiction")

    with store.lock:
        rec = {
            "name": name,
            "npi": npi,
            "reporting_jurisdiction": jurisdiction,
            "reporting_compliance_score": 100.00,
            "status": "ACTIVE",
        }
        store.stamp_create(rec)
        store.provider_organizations[rec["id"]] = rec
    return jsonify(build_envelope(_serialize(rec), "object")), 201


@bp.get("/provider-organizations/<prov_id>")
@require_roles(["PublicHealthOfficer", "ProviderClinician"])
def read_provider(prov_id: str):
    org = store.provider_organizations.get(prov_id)
    if not org:
        raise APIError("ERR_PROVIDER_NOT_FOUND", f"ProviderOrganization {prov_id} not found.")
    # Recompute compliance score on read.
    with store.lock:
        new_score = compute_provider_compliance_score(prov_id)
        new_score_float = float(new_score)
        prev_status = org["status"]
        new_status = prev_status
        if new_score < 70 and prev_status == "ACTIVE":
            new_status = "SUSPENDED"
        score_changed = (org["reporting_compliance_score"] != new_score_float)
        status_changed = (new_status != prev_status)
        if score_changed or status_changed:
            org["reporting_compliance_score"] = new_score_float
            org["status"] = new_status
            store.stamp_update(org)
    return jsonify(build_envelope(_serialize(org), "object")), 200


@bp.post("/provider-organizations/<prov_id>/suspend")
@require_roles(["PublicHealthOfficer"])
def suspend_provider(prov_id: str):
    body = parse_json_body(required=False)
    org = store.provider_organizations.get(prov_id)
    if not org:
        raise APIError("ERR_PROVIDER_NOT_FOUND", f"ProviderOrganization {prov_id} not found.")
    if org["status"] == "SUSPENDED":
        raise APIError("ERR_INVALID_STATE", "Provider is already SUSPENDED.")
    check_version_conflict(body, org)
    with store.lock:
        org["status"] = "SUSPENDED"
        store.stamp_update(org)
    return jsonify(build_envelope(_serialize(org), "object")), 200


@bp.post("/provider-organizations/<prov_id>/reinstate")
@require_roles(["PublicHealthOfficer"])
def reinstate_provider(prov_id: str):
    body = parse_json_body(required=False)
    org = store.provider_organizations.get(prov_id)
    if not org:
        raise APIError("ERR_PROVIDER_NOT_FOUND", f"ProviderOrganization {prov_id} not found.")
    if org["status"] != "SUSPENDED":
        raise APIError("ERR_INVALID_STATE", "Provider is not SUSPENDED.")
    check_version_conflict(body, org)
    # Score must be >= 90 to reinstate.
    if org["reporting_compliance_score"] < 90:
        raise APIError("ERR_INVALID_STATE", "Score below 90 — cannot reinstate.")
    with store.lock:
        org["status"] = "ACTIVE"
        store.stamp_update(org)
    return jsonify(build_envelope(_serialize(org), "object")), 200
