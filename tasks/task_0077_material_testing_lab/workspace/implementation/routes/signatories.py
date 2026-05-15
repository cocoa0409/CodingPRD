"""Signatory routes."""

from flask import Blueprint

from db import DB, new_id, LOCK
from errors import ERR_VALIDATION, raise_error
from middleware import auth_required
from response import success_response
from services.common import get_json_body, require_fields
from services.serializers import serialize_signatory
from services.time_util import now_iso

bp = Blueprint("signatories", __name__)

VALID_CATEGORIES = {"CONCRETE", "STEEL_REBAR", "SOIL", "ASPHALT", "CEMENT"}


@bp.post("/signatories")
@auth_required(["LabManager"])
def create_signatory():
    body = get_json_body()
    require_fields(body, ["full_name", "signature_certificate_id", "scope_categories"])
    if not isinstance(body["full_name"], str) or not body["full_name"]:
        raise_error(ERR_VALIDATION, "full_name required")
    if not isinstance(body["signature_certificate_id"], str) or not body["signature_certificate_id"]:
        raise_error(ERR_VALIDATION, "signature_certificate_id required")
    sc = body["scope_categories"]
    if not isinstance(sc, list):
        raise_error(ERR_VALIDATION, "scope_categories must be a list")
    for c in sc:
        if c not in VALID_CATEGORIES:
            raise_error(ERR_VALIDATION, f"invalid scope category: {c}")
    now = now_iso()
    with LOCK:
        row = {
            "id": new_id(),
            "created_at": now,
            "updated_at": now,
            "version": 1,
            "full_name": body["full_name"],
            "signature_certificate_id": body["signature_certificate_id"],
            "scope_categories": sc,
        }
        DB["signatories"][row["id"]] = row
    return success_response(serialize_signatory(row), 201)
