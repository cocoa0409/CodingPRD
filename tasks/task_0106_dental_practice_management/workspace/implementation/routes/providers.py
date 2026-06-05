"""Provider endpoints (PRD §3.1)."""
from __future__ import annotations

from flask import Blueprint, request

import db
from errors import ERR_PROVIDER_NOT_FOUND
from middleware import ROLE_BILLING, ROLE_CLINICIAN, ROLE_FRONT_DESK, ROLE_PATIENT
from response import ok_array, ok_object
from routes._helpers import apply_filters, guard
from services import common

bp = Blueprint("providers", __name__)


@bp.post("/providers")
def create_provider():
    guard([ROLE_FRONT_DESK])
    body = common.get_json_body()
    common.require_fields(body, ["full_name", "provider_type", "npi"])
    full_name = common.require_string(body, "full_name")
    provider_type = common.require_enum(body, "provider_type", {"DENTIST", "HYGIENIST"})
    npi = common.require_string(body, "npi")
    rec = common.new_common_fields()
    rec.update({
        "full_name": full_name,
        "provider_type": provider_type,
        "npi": npi,
        "status": "ACTIVE",
    })
    db.providers[rec["id"]] = rec
    return ok_object(common.serialize(rec), 201)


@bp.get("/providers")
def list_providers():
    guard([ROLE_FRONT_DESK, ROLE_CLINICIAN, ROLE_BILLING])
    records = apply_filters(list(db.providers.values()), {"status": request.args.get("status")})
    items, limit, offset, total = common.paginate(records)
    return ok_array(items, limit, offset, total)


@bp.get("/providers/<provider_id>")
def get_provider(provider_id):
    guard([ROLE_FRONT_DESK, ROLE_CLINICIAN, ROLE_BILLING, ROLE_PATIENT])
    rec = common.resolve(db.providers, provider_id, ERR_PROVIDER_NOT_FOUND)
    return ok_object(common.serialize(rec), 200)


@bp.post("/providers/<provider_id>/deactivate")
def deactivate_provider(provider_id):
    guard([ROLE_FRONT_DESK])
    rec = common.resolve(db.providers, provider_id, ERR_PROVIDER_NOT_FOUND)
    rec["status"] = "INACTIVE"
    common.touch(rec)
    return ok_object(common.serialize(rec), 200)
