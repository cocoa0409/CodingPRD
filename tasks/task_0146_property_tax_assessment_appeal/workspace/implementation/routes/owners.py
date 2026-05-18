"""Owner endpoints."""

from flask import Blueprint

from db import store
from errors import raise_error
from middleware import require_roles
from response import success
from routes._helpers import get_json_body, require_field, require_owner
from services.serializers import serialize_owner
from utils import new_uuid, parse_iso_date

owners_bp = Blueprint("owners", __name__)


@owners_bp.post("/owners")
def create_owner():
    require_roles({"Assessor", "Treasurer"})
    body = get_json_body()
    full_name = require_field(body, "full_name")
    if not isinstance(full_name, str) or not full_name.strip():
        raise_error("ERR_VALIDATION_FAILED", "full_name must be a non-empty string")
    dob = require_field(body, "date_of_birth")
    if not isinstance(dob, str):
        raise_error("ERR_VALIDATION_FAILED", "date_of_birth must be a string")
    try:
        parse_iso_date(dob)
    except Exception:
        raise_error("ERR_VALIDATION_FAILED", "date_of_birth must be ISO date YYYY-MM-DD")
    veteran = body.get("veteran_status", False)
    if veteran is None:
        veteran = False
    if not isinstance(veteran, bool):
        raise_error("ERR_VALIDATION_FAILED", "veteran_status must be a boolean")
    rating = body.get("disability_rating", 0)
    if rating is None:
        rating = 0
    if not isinstance(rating, int) or isinstance(rating, bool) or rating < 0 or rating > 100:
        raise_error("ERR_VALIDATION_FAILED", "disability_rating must be an integer 0..100")

    now = store.clock.now()
    rec = {
        "id": new_uuid(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "full_name": full_name,
        "date_of_birth": dob,
        "veteran_status": veteran,
        "disability_rating": rating,
    }
    with store.lock:
        store.owners[rec["id"]] = rec
    return success(serialize_owner(rec), status_code=201)


@owners_bp.get("/owners/<owner_id>")
def get_owner(owner_id):
    require_roles({"Assessor", "Treasurer", "HearingOfficer", "Owner"})
    rec = require_owner(owner_id)
    return success(serialize_owner(rec))
