"""Provider (endoscopist) endpoints (PRD 3.1)."""
from flask import Blueprint, request

from db import db
from errors import ERR_PROVIDER_NOT_FOUND
from middleware import authorized
from response import success_object
from routes.helpers import get_one, list_response
from services.core import new_record, public, touch
from validate import get_body, opt_enum, opt_str, req_enum, req_str, require_path_resource

bp = Blueprint("providers", __name__)

SPECIALTIES = {"GASTROENTEROLOGY", "COLORECTAL_SURGERY"}
CREDENTIAL_STATUSES = {"ACTIVE", "SUSPENDED"}


@bp.post("/endoscopy/providers")
def create_provider():
    authorized(["UnitAdmin"])
    body = get_body()
    full_name = req_str(body, "full_name")
    specialty = req_enum(body, "specialty", SPECIALTIES)
    rec = new_record("providers", {
        "full_name": full_name,
        "specialty": specialty,
        "credential_status": "ACTIVE",
    })
    return success_object(public(rec), status=201)


@bp.get("/endoscopy/providers")
def list_providers():
    return list_response("providers", {"credential_status": request.args.get("credential_status")})


@bp.get("/endoscopy/providers/<rid>")
def get_provider(rid):
    return get_one("providers", rid, ERR_PROVIDER_NOT_FOUND)


@bp.patch("/endoscopy/providers/<rid>")
def patch_provider(rid):
    authorized(["UnitAdmin"])
    rec = require_path_resource("providers", rid, ERR_PROVIDER_NOT_FOUND)
    body = get_body()
    full_name = opt_str(body, "full_name", None)
    credential_status = opt_enum(body, "credential_status", CREDENTIAL_STATUSES, None)
    if full_name is not None:
        rec["full_name"] = full_name
    if credential_status is not None:
        rec["credential_status"] = credential_status
    touch(rec)
    return success_object(public(rec))
