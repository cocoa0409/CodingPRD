"""Financial assurance instruments."""

from flask import Blueprint

import schema
from db import db, insert, now
from errors import fail
from middleware import endpoint
from response import created, ok
from routes.common import by_created_at, check_expected_version, load, reference, respond_list
from services import calc, derive
from services.tracking import touch
from util import new_id

bp = Blueprint("instruments", __name__)

READERS = ["PlatformAdmin", "ComplianceManager", "RegulatoryInspector"]

CREATE_SPEC = {
    "facility_id": {"type": "string", "required": True},
    "instrument_type": {"type": "string", "required": True, "enum": calc.INSTRUMENT_TYPES},
    "face_amount_cents": {"type": "int", "required": True, "ge": 0},
    "effective_on": {"type": "date", "required": True},
    "expected_facility_version": {"type": "int", "required": True},
}


@bp.post("/tsdf/financial-assurance-instruments")
@endpoint(roles=["ComplianceManager"], mutating=True)
def create_instrument():
    body = schema.body(CREATE_SPEC)
    f = reference("facilities", body["facility_id"])
    check_expected_version(f, body["expected_facility_version"])

    stamp = now()
    row = {
        "id": new_id(),
        "facility_id": f["id"],
        "instrument_type": body["instrument_type"],
        "face_amount_cents": body["face_amount_cents"],
        "effective_on": body["effective_on"],
        "status": "ACTIVE",
        "superseded_by_instrument_id": None,
        "superseded_at": None,
        "created_at": stamp,
        "updated_at": stamp,
        "version": 1,
    }

    for prior in derive.instruments_of_facility(f["id"]):
        if prior["status"] == "ACTIVE":
            prior["status"] = "SUPERSEDED"
            prior["superseded_by_instrument_id"] = row["id"]
            prior["superseded_at"] = stamp

    insert("instruments", row)
    # The facility's own version advances with the posted assurance it now carries.
    touch("facilities", f)
    return created(derive.project_instrument(row))


@bp.get("/tsdf/financial-assurance-instruments/<iid>")
@endpoint(roles=READERS)
def get_instrument(iid):
    return ok(derive.project_instrument(load("instruments", iid)))


@bp.get("/tsdf/financial-assurance-instruments")
@endpoint(roles=READERS)
def list_instruments():
    filters, limit, offset = schema.listing(
        filters=["facility_id", "superseded_by_instrument_id", "status"],
        enums={"status": calc.INSTRUMENT_STATUSES})
    rows = by_created_at(list(db.instruments.values()))
    for key in ("facility_id", "superseded_by_instrument_id", "status"):
        if key in filters:
            rows = [i for i in rows if i[key] == filters[key]]
    return respond_list(rows, derive.project_instrument, limit, offset)


@bp.post("/tsdf/financial-assurance-instruments/<iid>/cancel")
@endpoint(roles=["ComplianceManager"], mutating=True)
def cancel_instrument(iid):
    schema.body({"reason_code": {"type": "string"}})
    row = load("instruments", iid)
    if row["status"] != "ACTIVE":
        fail("ERR_INVALID_STATE", "Only an active instrument may be cancelled")

    f = derive.facility(row["facility_id"])
    required = derive.facility_required_assurance(f) if f is not None else 0
    if required != 0:
        covered = any(other["status"] == "ACTIVE" and other["id"] != row["id"]
                      and int(other["face_amount_cents"]) >= required
                      for other in derive.instruments_of_facility(row["facility_id"]))
        if not covered:
            fail("ERR_FINANCIAL_ASSURANCE_SHORTFALL")

    row["status"] = "CANCELLED"
    row["superseded_at"] = now()
    touch("instruments", row)
    return ok(derive.project_instrument(row))
