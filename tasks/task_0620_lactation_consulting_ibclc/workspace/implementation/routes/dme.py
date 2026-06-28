"""Breast-pump DME qualifications (PRD §3.10)."""
from flask import Blueprint, request

import db
from errors import (
    err,
    ERR_CONSULT_NOT_COMPLETED,
    ERR_DME_NOT_PENDING,
)
from middleware import get_auth, require_roles
from response import object_response, array_response
from services.common import (
    init_full, touch, serialize, get_body,
    require_str, require_enum, paginate,
)
from services.lookups import get_or_404, get_fk_or_404
from services.calculations import dme_qualified

bp = Blueprint("dme", __name__)

PUMP_TYPES = {"STANDARD_ELECTRIC", "HOSPITAL_GRADE"}
READ_ROLES = {"PracticeAdmin", "BillingSpecialist", "Consultant", "Client"}


@bp.post("/dme-qualifications")
def create_dme():
    # PRD §3.10 / §4: BillingSpecialist or Consultant.
    _, role = get_auth()
    require_roles(role, {"BillingSpecialist", "Consultant"})
    body = get_body()
    consult_id = require_str(body, "consult_id")
    # FK existence.
    consult = get_fk_or_404(db.consults, consult_id)
    # Well-formedness.
    pump_type = require_enum(body, "pump_type", PUMP_TYPES)
    # Parent consult must be COMPLETED (PRD §3.10).
    if consult["status"] != "COMPLETED":
        raise err(ERR_CONSULT_NOT_COMPLETED, "Parent consult is not COMPLETED")

    practice = db.practices[consult["practice_id"]]
    client = db.clients[consult["client_id"]]
    requested_utc = practice["now_utc"]  # stamped from the logical clock
    qualified = dme_qualified(
        consult["status"], pump_type, requested_utc, client["infant_dob"]
    )

    record = {
        "consult_id": consult_id,
        "client_id": consult["client_id"],  # copied from consult
        "requested_utc": requested_utc,
        "pump_type": pump_type,
        "qualified": qualified,
        "status": "PENDING",
    }
    init_full(record)
    db.dme_qualifications[record["id"]] = record
    return object_response(serialize(record), 201)


@bp.get("/dme-qualifications/<rid>")
def get_dme(rid):
    _, role = get_auth()
    require_roles(role, READ_ROLES)
    record = get_or_404(db.dme_qualifications, rid)
    return object_response(serialize(record), 200)


@bp.get("/dme-qualifications")
def list_dme():
    _, role = get_auth()
    require_roles(role, READ_ROLES)
    consult_id = request.args.get("consult_id")
    client_id = request.args.get("client_id")
    records = []
    for r in db.dme_qualifications.values():
        if consult_id is not None and r["consult_id"] != consult_id:
            continue
        if client_id is not None and r["client_id"] != client_id:
            continue
        records.append(r)
    items, limit, offset, total = paginate(records)
    return array_response(items, limit, offset, total, 200)


@bp.post("/dme-qualifications/<rid>/adjudicate")
def adjudicate_dme(rid):
    _, role = get_auth()
    require_roles(role, {"BillingSpecialist"})
    qual = get_or_404(db.dme_qualifications, rid)
    # Must be PENDING (PRD §3.10).
    if qual["status"] != "PENDING":
        raise err(ERR_DME_NOT_PENDING, "DME qualification is not PENDING")
    # qualified true -> QUALIFIED; false -> DENIED. Cannot force QUALIFIED when
    # the flag is false (PRD §3.10).
    if qual["qualified"]:
        qual["status"] = "QUALIFIED"
    else:
        qual["status"] = "DENIED"
    touch(qual)
    return object_response(serialize(qual), 200)
