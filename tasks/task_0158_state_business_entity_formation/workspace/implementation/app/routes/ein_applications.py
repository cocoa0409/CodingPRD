"""EIN application routes."""
from __future__ import annotations

from flask import Blueprint, jsonify

from ..auth import current_caller, require_auth
from ..envelope import object_response
from ..errors import (
    APIError,
    err_entity_not_active,
    err_invalid_input,
    err_invalid_state,
    err_not_found,
    err_segregation,
)
from ..store import store
from ..timeutil import now as clock_now
from ..util import SSN4_RE, get_json_body, new_uuid, require_str
from ..services import serializers
from ..services.engine import touch


bp = Blueprint("ein_applications", __name__, url_prefix="/business-registry")


def _app_or_404(app_id):
    row = store.ein_applications.get(app_id)
    if row is None:
        raise err_not_found(f"EIN application {app_id!r} not found")
    return row


@bp.post("/ein-applications")
@require_auth(["Filer"])
def create_ein_application():
    caller = current_caller()
    body = get_json_body()
    business_entity_id = require_str(body, "business_entity_id")
    responsible_party_name = require_str(body, "responsible_party_name", min_len=1, max_len=300)
    ssn4 = require_str(body, "responsible_party_ssn_last4", min_len=4, max_len=4)
    if not SSN4_RE.match(ssn4):
        raise err_invalid_input("responsible_party_ssn_last4 must match ^[0-9]{4}$")
    with store.lock:
        entity = store.business_entities.get(business_entity_id)
        if entity is None:
            raise err_not_found(f"business_entity_id {business_entity_id!r} not found")
        if entity.get("formation_status") != "ACTIVE":
            raise err_entity_not_active()
        if caller.user_id != business_entity_id:
            raise APIError("ERR_FORBIDDEN", "Filer may not act on another entity", 403)
        # At most one non-REJECTED EIN application per entity
        for existing in store.ein_applications.values():
            if existing.get("business_entity_id") == business_entity_id and existing.get("status") != "REJECTED":
                raise err_invalid_state("Another non-REJECTED EIN application already exists for this entity")
        now = clock_now()
        row = {
            "id": new_uuid(),
            "created_at": now,
            "updated_at": now,
            "version": 1,
            "business_entity_id": business_entity_id,
            "responsible_party_name": responsible_party_name,
            "responsible_party_ssn_last4": ssn4,
            "status": "DRAFT",
            "assigned_ein": None,
        }
        store.ein_applications[row["id"]] = row
        return jsonify(object_response(serializers.ein_application(row))), 201


@bp.post("/ein-applications/<app_id>/submit")
@require_auth(["Filer"])
def submit_ein(app_id):
    caller = current_caller()
    with store.lock:
        row = _app_or_404(app_id)
        if row.get("status") != "DRAFT":
            raise err_invalid_state("EIN application is not in DRAFT")
        entity = store.business_entities.get(row.get("business_entity_id"))
        if entity is None or entity.get("formation_status") != "ACTIVE":
            raise err_entity_not_active()
        if caller.user_id != row.get("business_entity_id"):
            raise APIError("ERR_FORBIDDEN", "Filer may not act on another entity", 403)
        if not SSN4_RE.match(row.get("responsible_party_ssn_last4") or ""):
            raise err_invalid_input("responsible_party_ssn_last4 must match ^[0-9]{4}$")
        row["status"] = "SUBMITTED"
        touch(row)
        return jsonify(object_response(serializers.ein_application(row))), 200


@bp.post("/ein-applications/<app_id>/approve")
@require_auth(["TaxOfficer"])
def approve_ein(app_id):
    caller = current_caller()
    with store.lock:
        row = _app_or_404(app_id)
        if row.get("status") != "SUBMITTED":
            raise err_invalid_state("EIN application is not in SUBMITTED")
        entity = store.business_entities.get(row.get("business_entity_id"))
        if entity is None or entity.get("formation_status") != "ACTIVE":
            raise err_entity_not_active()
        # Segregation: TaxOfficer X-User-ID must not equal the BusinessEntity.id
        if caller.user_id == row.get("business_entity_id"):
            raise err_segregation()
        ein = store.next_ein()
        row["status"] = "APPROVED"
        row["assigned_ein"] = ein
        touch(row)
        entity["ein"] = ein
        touch(entity)
        return jsonify(object_response(serializers.ein_application(row))), 200


@bp.post("/ein-applications/<app_id>/reject")
@require_auth(["TaxOfficer"])
def reject_ein(app_id):
    with store.lock:
        row = _app_or_404(app_id)
        if row.get("status") != "SUBMITTED":
            raise err_invalid_state("EIN application is not in SUBMITTED")
        entity = store.business_entities.get(row.get("business_entity_id"))
        if entity is None or entity.get("formation_status") != "ACTIVE":
            raise err_entity_not_active()
        row["status"] = "REJECTED"
        touch(row)
        return jsonify(object_response(serializers.ein_application(row))), 200
