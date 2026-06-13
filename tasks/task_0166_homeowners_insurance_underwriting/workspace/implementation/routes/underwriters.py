"""Underwriter routes (PRD §3.6). Immutable: only id + created_at."""
from flask import Blueprint

from db import db
from middleware import require_roles
from response import success
from services.common import get_json_body, require_field, as_string, as_number
from services.models import base_record, serialize

bp = Blueprint("underwriters", __name__)


@bp.post("/underwriters")
@require_roles("Admin")
def create_underwriter():
    body = get_json_body()
    full_name = as_string(require_field(body, "full_name"), "full_name")
    authority_limit = as_number(require_field(body, "authority_limit"), "authority_limit")
    if authority_limit <= 0:
        from errors import err
        raise err("ERR_INVALID_REQUEST", "authority_limit must be > 0.")
    with db.lock:
        rec = base_record(common_fields=False)  # immutable: no updated_at/version
        rec["full_name"] = full_name
        rec["authority_limit"] = authority_limit
        db.underwriters[rec["id"]] = rec
    return success(serialize(rec), status=201)
