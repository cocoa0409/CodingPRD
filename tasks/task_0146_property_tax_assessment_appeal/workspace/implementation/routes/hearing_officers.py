"""HearingOfficer endpoints."""

from flask import Blueprint

from db import store
from errors import raise_error
from middleware import require_roles
from response import success
from routes._helpers import get_json_body, require_field, require_hearing_officer
from services.serializers import serialize_hearing_officer
from utils import new_uuid

officers_bp = Blueprint("hearing_officers", __name__)


@officers_bp.post("/hearing_officers")
def create_officer():
    require_roles({"Treasurer"})
    body = get_json_body()
    full_name = require_field(body, "full_name")
    if not isinstance(full_name, str) or not full_name.strip():
        raise_error("ERR_VALIDATION_FAILED", "full_name must be a non-empty string")
    active = body.get("active", True)
    if active is None:
        active = True
    if not isinstance(active, bool):
        raise_error("ERR_VALIDATION_FAILED", "active must be a boolean")

    now = store.clock.now()
    rec = {
        "id": new_uuid(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "full_name": full_name,
        "active": active,
    }
    with store.lock:
        store.hearing_officers[rec["id"]] = rec
    return success(serialize_hearing_officer(rec), status_code=201)


@officers_bp.get("/hearing_officers/<officer_id>")
def get_officer(officer_id):
    require_roles({"Assessor", "Treasurer", "HearingOfficer", "Owner"})
    rec = require_hearing_officer(officer_id)
    return success(serialize_hearing_officer(rec))
