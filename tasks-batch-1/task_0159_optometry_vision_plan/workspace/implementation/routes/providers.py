"""Provider registration and retrieval (lean entity: id + created_at only)."""
from flask import Blueprint

import errors
import helpers
import response
import serialize
from db import db, new_id, stamp_create
from middleware import require_roles

bp = Blueprint("providers", __name__)

ALL_ROLES = ("FrontDesk", "Optometrist", "Optician", "Biller")
PROVIDER_ROLES = {"OPTOMETRIST", "OPTICIAN"}


@bp.post("/providers")
@require_roles("FrontDesk")
def create_provider():
    body = helpers.get_json_body()
    full_name = helpers.require_str(body, "full_name")
    role = helpers.require_enum(body, "role", PROVIDER_ROLES)
    npi = helpers.require_str(body, "npi")
    if not (len(npi) == 10 and npi.isdigit()):
        raise errors.invalid_request("npi must be exactly 10 digits")

    record = {
        "id": new_id(),
        "full_name": full_name,
        "role": role,
        "npi": npi,
    }
    stamp_create(record, versioned=False)
    db.providers[record["id"]] = record
    return response.object_response(serialize.provider(record), 201)


@bp.get("/providers/<provider_id>")
@require_roles(*ALL_ROLES)
def get_provider(provider_id):
    record = db.providers.get(provider_id)
    if record is None:
        raise errors.not_found("Provider not found")
    return response.object_response(serialize.provider(record), 200)


@bp.get("/providers")
@require_roles(*ALL_ROLES)
def list_providers():
    from flask import request
    limit, offset = helpers.parse_pagination()
    role = request.args.get("role")
    records = list(db.providers.values())
    if role is not None:
        records = [r for r in records if r["role"] == role]
    page, total = helpers.paginate(records, limit, offset)
    return response.array_response(
        [serialize.provider(r) for r in page], limit, offset, total, 200)
