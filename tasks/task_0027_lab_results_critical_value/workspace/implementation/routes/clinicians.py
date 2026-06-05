"""Clinician CRUD."""
from __future__ import annotations

from flask import Blueprint, request

import db
from errors import (
    APIError, ERR_DUPLICATE_IDENTIFIER, ERR_BACKUP_REQUIRED, ERR_NOT_FOUND,
)
from middleware import require_auth, get_json_body
from response import ok_object, ok_array, paginate_params, slice_page
from services.validation import (
    require_fields, require_string, require_pattern, require_enum, lookup_or_404,
    NPI_PATTERN, PHONE_PATTERN,
)


bp = Blueprint("clinicians", __name__)


ROLE_TYPES = {"ORDERING_PROVIDER", "PHLEBOTOMIST", "LAB_TECH", "LAB_DIRECTOR"}


# ---------- POST /clinicians ------------------------------------------------

@bp.post("/clinicians")
def create_clinician():
    require_auth(["Anonymous", "LabDirector"])()
    body = get_json_body()
    require_fields(body, ["npi", "full_name", "role_type", "phone_e164"])
    npi = body["npi"]
    full_name = body["full_name"]
    role_type = body["role_type"]
    phone_e164 = body["phone_e164"]
    backup = body.get("backup_clinician_id")

    require_string(npi, "npi")
    require_pattern(npi, NPI_PATTERN, "npi")
    require_string(full_name, "full_name", min_len=1, max_len=500)
    require_enum(role_type, ROLE_TYPES, "role_type")
    require_string(phone_e164, "phone_e164")
    require_pattern(phone_e164, PHONE_PATTERN, "phone_e164")

    # NPI uniqueness.
    for c in db.clinicians.values():
        if c.get("npi") == npi:
            raise APIError(ERR_DUPLICATE_IDENTIFIER, 409,
                           f"Clinician with npi '{npi}' already exists")

    # Backup requirement: required for everyone except LAB_DIRECTOR.
    if role_type != "LAB_DIRECTOR":
        if backup is None:
            raise APIError(ERR_BACKUP_REQUIRED, 422,
                           "backup_clinician_id is required for non-LAB_DIRECTOR clinicians")
        require_string(backup, "backup_clinician_id")
        # FK existence — must reference an existing clinician.
        if backup not in db.clinicians:
            raise APIError(ERR_NOT_FOUND, 404,
                           f"backup_clinician_id '{backup}' not found")
    else:
        # LAB_DIRECTOR may have backup as null or referencing another clinician.
        if backup is not None:
            require_string(backup, "backup_clinician_id")
            if backup not in db.clinicians:
                raise APIError(ERR_NOT_FOUND, 404,
                               f"backup_clinician_id '{backup}' not found")

    clinician = {
        "npi": npi,
        "full_name": full_name,
        "role_type": role_type,
        "phone_e164": phone_e164,
        "backup_clinician_id": backup,
    }
    db.stamp_common(clinician)
    db.clinicians[clinician["id"]] = clinician
    return ok_object(clinician, http_status=201)


# ---------- GET /clinicians/{id} --------------------------------------------

@bp.get("/clinicians/<cid>")
def get_clinician(cid):
    require_auth(["LabTech", "LabDirector", "OrderingProvider", "Phlebotomist"])()
    c = lookup_or_404(db.clinicians, cid, "Clinician")
    return ok_object(c)


# ---------- GET /clinicians -------------------------------------------------

@bp.get("/clinicians")
def list_clinicians():
    require_auth(["LabTech", "LabDirector", "OrderingProvider"])()
    limit, offset = paginate_params(request.args)
    role_type = request.args.get("role_type")
    backup_filter = request.args.get("backup_clinician_id")
    items = list(db.clinicians.values())
    if role_type is not None:
        items = [c for c in items if c.get("role_type") == role_type]
    if backup_filter is not None:
        items = [c for c in items if c.get("backup_clinician_id") == backup_filter]
    items.sort(key=lambda x: x["created_at"])
    page, total = slice_page(items, limit, offset)
    return ok_array(page, limit, offset, total)
