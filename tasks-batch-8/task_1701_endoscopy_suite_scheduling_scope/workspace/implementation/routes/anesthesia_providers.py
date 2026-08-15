"""AnesthesiaProvider endpoints (PRD 3.1/3.3)."""
from flask import Blueprint, request

from errors import ERR_ANESTHESIA_PROVIDER_NOT_FOUND
from middleware import authorized
from response import success_object
from routes.helpers import get_one, list_response
from services.core import new_record, public_anesthesia_provider, touch
from validate import get_body, opt_enum, opt_str, req_str, require_path_resource

bp = Blueprint("anesthesia_providers", __name__)

CREDENTIAL_STATUSES = {"ACTIVE", "SUSPENDED"}


@bp.post("/endoscopy/anesthesia-providers")
def create_anesthesia_provider():
    authorized(["UnitAdmin"])
    body = get_body()
    full_name = req_str(body, "full_name")
    rec = new_record("anesthesia_providers", {
        "full_name": full_name,
        "credential_status": "ACTIVE",
    })
    return success_object(public_anesthesia_provider(rec), status=201)


@bp.get("/endoscopy/anesthesia-providers")
def list_anesthesia_providers():
    return list_response(
        "anesthesia_providers",
        {"credential_status": request.args.get("credential_status")},
    )


@bp.get("/endoscopy/anesthesia-providers/<rid>")
def get_anesthesia_provider(rid):
    return get_one("anesthesia_providers", rid, ERR_ANESTHESIA_PROVIDER_NOT_FOUND)


@bp.patch("/endoscopy/anesthesia-providers/<rid>")
def patch_anesthesia_provider(rid):
    authorized(["UnitAdmin"])
    rec = require_path_resource("anesthesia_providers", rid, ERR_ANESTHESIA_PROVIDER_NOT_FOUND)
    body = get_body()
    full_name = opt_str(body, "full_name", None)
    credential_status = opt_enum(body, "credential_status", CREDENTIAL_STATUSES, None)
    if full_name is not None:
        rec["full_name"] = full_name
    if credential_status is not None:
        rec["credential_status"] = credential_status
    touch(rec)
    return success_object(public_anesthesia_provider(rec))
