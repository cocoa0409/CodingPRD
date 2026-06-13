"""Inspector routes (PRD §3.3)."""
from flask import Blueprint

from db import db
from errors import err
from middleware import require_roles
from response import success
from services.common import get_json_body, require_field, as_string, as_int
from services.models import base_record, serialize

bp = Blueprint("inspectors", __name__)


@bp.post("/inspectors")
@require_roles("Admin")
def create_inspector():
    body = get_json_body()
    full_name = as_string(require_field(body, "full_name"), "full_name")
    license_state = as_string(require_field(body, "license_state"), "license_state")
    if "buffer_minutes" in body and body["buffer_minutes"] is not None:
        buffer_minutes = as_int(body["buffer_minutes"], "buffer_minutes")
        if buffer_minutes < 0:
            raise err("ERR_INVALID_REQUEST", "buffer_minutes must be >= 0.")
    else:
        buffer_minutes = 60
    with db.lock:
        rec = base_record()
        rec.update({
            "full_name": full_name,
            "license_state": license_state,
            "buffer_minutes": buffer_minutes,
            "status": "ACTIVE",
        })
        db.inspectors[rec["id"]] = rec
    return success(serialize(rec), status=201)
