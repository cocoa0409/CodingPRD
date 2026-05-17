"""Clinician endpoints."""
from __future__ import annotations

from flask import Blueprint

from ..auth import ROLE_LAB_DIRECTOR, ROLE_LAB_TECH, ROLE_ORDERING_PROVIDER, require_roles
from ..errors import err_validation
from ..helpers import (
    assert_bool,
    assert_enum,
    assert_string,
    new_uuid,
    occ_check,
    require_json_object,
)
from ..responses import created, ok
from ..services.lookups import get_clinician
from ..services.serialize import clinician_view
from ..services.workflows import bump, create_common_fields
from ..store import store

bp = Blueprint("clinicians", __name__)

NPI_PATTERN = r"^[0-9]{10}$"
PHONE_PATTERN = r"^\+[1-9][0-9]{6,14}$"
ROLE_KINDS = ["ORDERING_PROVIDER", "LAB_TECH", "LAB_DIRECTOR"]


@bp.route("/clinicians", methods=["POST"])
@require_roles(ROLE_LAB_DIRECTOR)
def register_clinician(**_):
    body = require_json_object()
    npi = assert_string(body.get("npi"), "npi", pattern=NPI_PATTERN)
    full_name = assert_string(body.get("full_name"), "full_name")
    role_kind = assert_enum(body.get("role_kind"), "role_kind", ROLE_KINDS)
    phone = assert_string(body.get("phone_e164"), "phone_e164", pattern=PHONE_PATTERN)

    with store().lock:
        for c in store().clinicians.values():
            if c["npi"] == npi:
                raise err_validation(f"npi {npi} already exists")
        row = {
            **create_common_fields(),
            "npi": npi,
            "full_name": full_name,
            "role_kind": role_kind,
            "phone_e164": phone,
            "active": True,
        }
        store().clinicians[row["id"]] = row
    return created(clinician_view(row))


@bp.route("/clinicians/<cid>", methods=["PATCH"])
@require_roles(ROLE_LAB_DIRECTOR)
def update_clinician(cid, **_):
    body = require_json_object()
    with store().lock:
        row = get_clinician(cid)
        occ_check(body.get("version"), row["version"])
        mutated = False
        if "active" in body:
            row["active"] = assert_bool(body.get("active"), "active")
            mutated = True
        if "phone_e164" in body:
            row["phone_e164"] = assert_string(body.get("phone_e164"), "phone_e164", pattern=PHONE_PATTERN)
            mutated = True
        if mutated:
            bump(row)
    return ok(clinician_view(row))


@bp.route("/clinicians/<cid>", methods=["GET"])
@require_roles(ROLE_ORDERING_PROVIDER, ROLE_LAB_TECH, ROLE_LAB_DIRECTOR)
def fetch_clinician(cid, **_):
    row = get_clinician(cid)
    return ok(clinician_view(row))
