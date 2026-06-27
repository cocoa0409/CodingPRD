"""Clinician endpoints (PRD §3.1)."""
import re

from flask import Blueprint

from db import db
from errors import err
from middleware import get_auth, require_roles
from models import base_record, serialize
from response import object_response
from services.store import get_clinician
from validation import get_body, require_str, require_enum, optional_bool

bp = Blueprint("clinicians", __name__)

_STATE_RE = re.compile(r"^[A-Z]{2}$")


@bp.route("/clinicians", methods=["POST"])
def create_clinician():
    _, role = get_auth()
    require_roles(role, {"BillingAdmin"})
    body = get_body()
    full_name = require_str(body, "full_name")
    license_state_codes = body.get("license_state_codes")
    role_type = require_enum(body, "role_type", {"DENTIST", "ORTHODONTIST"})
    active = optional_bool(body, "active", default=True)

    if (not isinstance(license_state_codes, list)
            or len(license_state_codes) == 0):
        raise err("ERR_INVALID_REQUEST",
                  "license_state_codes must be a non-empty array.")
    for code in license_state_codes:
        if not isinstance(code, str) or not _STATE_RE.match(code):
            raise err("ERR_INVALID_REQUEST",
                      "license_state_codes must contain two-letter codes.")

    rec = base_record(common_fields=True)
    rec.update({
        "full_name": full_name,
        "license_state_codes": list(license_state_codes),
        "role_type": role_type,
        "active": active,
    })
    db.clinicians[rec["id"]] = rec
    return object_response(serialize(rec), status=201)


@bp.route("/clinicians/<cid>", methods=["GET"])
def fetch_clinician(cid):
    _, role = get_auth()
    require_roles(role, {"Clinician", "BillingAdmin", "ManufacturingOps"})
    rec = get_clinician(cid)
    return object_response(serialize(rec), status=200)
