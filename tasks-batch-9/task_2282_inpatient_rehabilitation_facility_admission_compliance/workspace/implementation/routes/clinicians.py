"""Clinician registration, listing and deactivation (PRD §3.1)."""

from flask import Blueprint, request

from auth import ALL_ROLES, authenticate
from db import store
from errors import ApiError
from queryargs import enum_arg, matches, str_arg
from response import envelope, paged, pagination_params
from services import CREDENTIALS, by_seq, require, stamp_new, touch
from util import Body, serialize

bp = Blueprint("clinicians", __name__)


@bp.post("/clinicians")
def create_clinician():
    authenticate(("ComplianceOfficer",))
    body = Body(request.get_json(silent=True))

    facility_id = body.id_field("facility_id")
    full_name = body.str_field("full_name", min_len=1)
    credential = body.enum_field("credential", CREDENTIALS)
    npi = body.str_field("npi", pattern=r"^\d{10}$")

    # ladder rank 10 — body identifier existence
    require(store.facilities, facility_id)

    # ladder rank 40 — npi uniqueness across clinicians
    for existing in store.clinicians.values():
        if existing["npi"] == npi:
            raise ApiError("ERR_MRN_DUPLICATE")

    clinician = stamp_new({
        "facility_id": facility_id,
        "full_name": full_name,
        "credential": credential,
        "npi": npi,
        "status": "ACTIVE",
    })
    store.clinicians[clinician["id"]] = clinician
    return envelope(serialize(clinician), 201)


@bp.get("/clinicians/<clinician_id>")
def get_clinician(clinician_id):
    authenticate(ALL_ROLES)
    clinician = require(store.clinicians, clinician_id)
    return envelope(serialize(clinician), 200)


@bp.get("/clinicians")
def list_clinicians():
    authenticate(ALL_ROLES)
    limit, offset = pagination_params()
    filters = {
        "facility_id": str_arg("facility_id"),
        "credential": enum_arg("credential", CREDENTIALS),
        "status": enum_arg("status", ("ACTIVE", "INACTIVE")),
    }
    items = [c for c in by_seq(list(store.clinicians.values())) if matches(c, filters)]
    page, pagination = paged(items, limit, offset)
    return envelope([serialize(c) for c in page], 200, pagination)


@bp.post("/clinicians/<clinician_id>/deactivate")
def deactivate_clinician(clinician_id):
    authenticate(("ComplianceOfficer",))
    clinician = require(store.clinicians, clinician_id)

    # ladder rank 16 — declared transition ACTIVE -> INACTIVE
    if clinician["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE")

    clinician["status"] = "INACTIVE"
    touch(clinician)
    return envelope(serialize(clinician), 200)
