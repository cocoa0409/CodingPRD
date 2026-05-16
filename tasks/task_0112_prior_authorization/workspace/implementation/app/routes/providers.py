"""Provider routes."""
from flask import Blueprint, jsonify

from ..auth import require_auth
from ..errors import APIError
from ..helpers import get_json_body, optional_field, require_field
from ..responses import success_response
from ..services.lookups import get_provider_or_404
from ..services.serialize import serialize_provider
from ..store import get_lock, get_store, stamp_create


bp = Blueprint("providers", __name__)


@bp.post("/providers")
@require_auth("PlatformAdmin")
def create_provider():
    body = get_json_body()
    npi = require_field(body, "npi")
    full_name = require_field(body, "full_name")
    specialty = require_field(body, "specialty")
    in_network = optional_field(body, "in_network", True)
    if not isinstance(npi, str) or len(npi) != 10 or not npi.isdigit():
        raise APIError("ERR_VALIDATION", "npi must be a 10-digit string")
    if not isinstance(in_network, bool):
        raise APIError("ERR_VALIDATION", "in_network must be a boolean")

    with get_lock():
        store = get_store()
        for existing in store.providers.values():
            if existing["npi"] == npi:
                raise APIError("ERR_VALIDATION", "npi already exists")
        rec = {
            "npi": npi,
            "full_name": full_name,
            "specialty": specialty,
            "in_network": in_network,
            "status": "ACTIVE",
        }
        stamp_create(rec)
        store.providers[rec["id"]] = rec

    body_out, status = success_response(serialize_provider(rec), status=201)
    return jsonify(body_out), status


@bp.get("/providers/<provider_id>")
@require_auth("PlatformAdmin", "Provider", "InitialReviewer")
def get_provider(provider_id: str):
    rec = get_provider_or_404(provider_id)
    body_out, status = success_response(serialize_provider(rec))
    return jsonify(body_out), status
