"""Compliance certificates (PRD section 3.9)."""

from flask import Blueprint, request

import calc
import domain
from auth import auth
from db import db, sort_created
from errors import fail
from response import jsonable, ok, ok_list, touch
from validate import body, get_enum, get_str, lookup, page, pagination

bp = Blueprint("certificates", __name__, url_prefix="/fire-district")

READERS = ("ProgramAdmin", "FireMarshal", "PropertyOwner", "TitleAgent")


def _certificate(certificate_id):
    return lookup("certificates", certificate_id, "ERR_CERTIFICATE_NOT_FOUND")


@bp.get("/compliance-certificates/<certificate_id>")
def read_certificate(certificate_id):
    auth(*READERS)
    return ok(jsonable(_certificate(certificate_id)))


@bp.get("/compliance-certificates")
def list_certificates():
    auth(*READERS)
    limit, offset = pagination()
    records = sort_created(list(db.certificates.values()))
    for field in ("parcel_id", "requester_kind", "status"):
        value = request.args.get(field)
        if value is not None:
            records = [r for r in records if r[field] == value]
    return ok_list(
        [jsonable(r) for r in page(records, limit, offset)], limit, offset, len(records)
    )


@bp.post("/compliance-certificates/<certificate_id>/decision")
def decide_certificate(certificate_id):
    auth("ProgramAdmin")
    certificate = _certificate(certificate_id)
    b = body()
    decision = get_enum(b, "decision", ("ISSUE", "DENY"))
    note = get_str(b, "note", required=False)
    if certificate["status"] != "REQUESTED":
        fail("ERR_INVALID_STATE", "Only a REQUESTED certificate can be adjudicated.")
    parcel = db.parcels.get(certificate["parcel_id"])
    if decision == "ISSUE":
        # Rung 18 — error selection between the two failure modes is unambiguous.
        if parcel["compliance_status"] == "PENDING_INSPECTION":
            fail("ERR_PARCEL_NOT_INSPECTED", "The parcel has never been inspected.")
        blocked = parcel["compliance_status"] not in ("COMPLIANT", "EXEMPT")
        if not blocked:
            blocked = any(
                n["status"] in domain.OPEN_NOTICE_STATUSES
                for n in domain.parcel_notices(parcel["id"])
            )
        if blocked:
            fail("ERR_OPEN_VIOLATION_EXISTS", "The parcel does not hold a clean posture.")
        certificate["status"] = "ISSUED"
        certificate["issued_at_utc"] = db.clock
        certificate["expires_at_utc"] = calc.end_of_day(db.clock, calc.CERTIFICATE_VALID_DAYS)
        certificate["snapshot_risk_class"] = parcel["risk_class"]
        certificate["snapshot_compliance_status"] = parcel["compliance_status"]
        if note is not None:
            certificate["decision_note"] = note
    else:
        certificate["status"] = "DENIED"
        certificate["decision_note"] = note
    touch(certificate)
    return ok(jsonable(certificate))
