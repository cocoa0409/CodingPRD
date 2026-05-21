"""Operating agreement attachment."""
from __future__ import annotations

from flask import Blueprint, jsonify

from ..auth import current_caller, require_auth
from ..envelope import object_response
from ..errors import APIError, err_entity_not_active, err_not_found
from ..store import store
from ..timeutil import now as clock_now
from ..util import get_json_body, new_uuid, require_str
from ..services import serializers
from ..services.engine import make_template_hash


bp = Blueprint("operating_agreements", __name__, url_prefix="/business-registry")


TEMPLATE_BY_TYPE = {
    "LLC": {"LLC_MM", "LLC_MGR"},
    "CORP": {"CORP_BYLAWS"},
    "LP": {"LP_AGREEMENT"},
}


@bp.post("/operating-agreements")
@require_auth(["Filer"])
def create_operating_agreement():
    caller = current_caller()
    body = get_json_body()
    business_entity_id = require_str(body, "business_entity_id")
    template_code = require_str(body, "template_code")
    template_version = require_str(body, "template_version", min_len=1, max_len=64)
    with store.lock:
        entity = store.business_entities.get(business_entity_id)
        if entity is None:
            raise err_not_found(f"business_entity_id {business_entity_id!r} not found")
        if entity.get("formation_status") != "ACTIVE":
            raise err_entity_not_active()
        if caller.user_id != business_entity_id:
            raise APIError("ERR_FORBIDDEN", "Filer may not act on another entity", 403)
        valid = TEMPLATE_BY_TYPE.get(entity.get("entity_type") or "", set())
        if template_code not in valid:
            raise APIError("ERR_TEMPLATE_TYPE_MISMATCH",
                           f"template_code {template_code!r} does not match entity_type {entity.get('entity_type')!r}", 422)
        now = clock_now()
        row = {
            "id": new_uuid(),
            "created_at": now,
            "business_entity_id": business_entity_id,
            "template_code": template_code,
            "template_version": template_version,
            "locked_template_hash": make_template_hash(template_code, template_version),
            "attached_at": now,
        }
        store.operating_agreements[row["id"]] = row
        return jsonify(object_response(serializers.operating_agreement(row))), 201
