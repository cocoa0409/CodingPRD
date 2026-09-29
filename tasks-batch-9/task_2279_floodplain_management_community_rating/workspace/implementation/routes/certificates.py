"""Elevation certificate filing, review, and the amendment loop."""

from flask import Blueprint

from db import (base_fields, db, iso, iso_now, now, shift_years, sort_rows,
                touch)
from errors import fail
from middleware import ALL_ROLES, require
from response import list_response, object_response
from services import calc, engine
from validation import (body, fk, lookup, opt_str, opt_str_list, pagination,
                        paginate, query_filters, req_enum, req_num)

bp = Blueprint("certificates", __name__)

_DECISIONS = ("ACCEPT", "DEFICIENT")


def _owner_guard(user_id, role, permit):
    if role != "PropertyOwner" or permit is None:
        return
    if user_id != permit["property_id"]:
        fail("ERR_NOT_PROPERTY_OWNER")


@bp.post("/elevation-certificates")
def create_certificate():
    user_id, role = require("PropertyOwner")
    data = body()
    raw_permit = data.get("permit_id")
    _owner_guard(user_id, role,
                 db.permits.get(raw_permit) if isinstance(raw_permit, str) else None)

    permit_id = fk(data, "permit_id", "permit")
    structure_id = fk(data, "structure_id", "structure")
    certificate_type = req_enum(data, "certificate_type", calc.CERTIFICATE_TYPES)
    datum = req_enum(data, "datum", calc.DATUMS)
    measured_floor = req_num(data, "measured_lowest_floor_ft")
    measured_bfe = req_num(data, "measured_bfe_ft")
    license_no = opt_str(data, "surveyor_license_no")

    permit = lookup("permit", permit_id)
    lookup("structure", structure_id)
    if structure_id != permit["structure_id"]:
        fail("ERR_CERTIFICATE_STRUCTURE_MISMATCH")

    if certificate_type == "FINISHED_CONSTRUCTION" and not license_no:
        fail("ERR_SURVEYOR_LICENSE_REQUIRED")
    if permit["status"] != "ISSUED":
        fail("ERR_PERMIT_NOT_ISSUED")

    row = base_fields()
    row.update({
        "permit_id": permit_id,
        "structure_id": structure_id,
        "certificate_type": certificate_type,
        "surveyor_license_no": license_no,
        "datum": datum,
        # PRD 2.6: only elevations the server *computes or stores as a derived
        # value* are rounded to 1 dp.  The surveyed measurements are raw inputs
        # and are kept at full precision, because 3.5 adds the datum offset to
        # the raw measurement and rounds only that sum.
        "measured_lowest_floor_ft": calc.dec(measured_floor),
        "measured_bfe_ft": calc.dec(measured_bfe),
        "normalized_lowest_floor_ft": None,
        "freeboard_margin_ft": None,
        "status": "SUBMITTED",
        "deficiency_codes": [],
        "accepted_at": None,
        "retention_review_due_at": None,
    })
    engine.normalize_certificate(row, permit)
    db.certificates[row["id"]] = row
    return object_response(row, 201)


@bp.get("/elevation-certificates/<certificate_id>")
def read_certificate(certificate_id):
    require(*ALL_ROLES)
    return object_response(lookup("certificate", certificate_id))


@bp.get("/elevation-certificates")
def list_certificates():
    require(*ALL_ROLES)
    limit, offset = pagination()
    rows = query_filters(list(db.certificates.values()), {
        "permit_id": ("permit_id", None),
        "structure_id": ("structure_id", None),
        "status": ("status", None),
        "certificate_type": ("certificate_type", None),
    })
    page, total = paginate(rows, limit, offset)
    return list_response(page, limit, offset, total)


@bp.post("/elevation-certificates/<certificate_id>/review")
def review_certificate(certificate_id):
    require("FloodplainAdministrator")
    certificate = lookup("certificate", certificate_id)
    data = body()
    decision = req_enum(data, "decision", _DECISIONS)
    codes = opt_str_list(data, "deficiency_codes", default=[])

    if certificate["status"] != "SUBMITTED":
        fail("ERR_CERTIFICATE_NOT_REVIEWABLE")

    permit = db.permits.get(certificate["permit_id"])
    if decision == "DEFICIENT":
        certificate["status"] = "DEFICIENT"
        certificate["deficiency_codes"] = list(codes)
        touch(certificate)
        return object_response(certificate)

    if permit is not None and certificate["structure_id"] != permit["structure_id"]:
        fail("ERR_CERTIFICATE_STRUCTURE_MISMATCH")
    margin = certificate["freeboard_margin_ft"]
    if margin is not None and calc.dec(margin) < calc.ZERO:
        fail("ERR_ELEVATION_BELOW_REQUIRED")

    certificate["status"] = "ACCEPTED"
    certificate["accepted_at"] = iso_now()
    certificate["retention_review_due_at"] = iso(
        shift_years(now(), calc.DOC_RETENTION_REVIEW_YEARS))
    touch(certificate)

    for other in sort_rows(engine.certificates_of_structure(certificate["structure_id"])):
        if other["id"] == certificate["id"] or other["status"] != "ACCEPTED":
            continue
        other["status"] = "SUPERSEDED"
        touch(other)

    if certificate["certificate_type"] == "FINISHED_CONSTRUCTION":
        structure = db.structures.get(certificate["structure_id"])
        if structure is not None:
            changed = False
            if structure["lowest_floor_elevation_ft"] != certificate["normalized_lowest_floor_ft"]:
                structure["lowest_floor_elevation_ft"] = certificate["normalized_lowest_floor_ft"]
                changed = True
            if (structure["compliance_status"] == "PENDING_CERTIFICATE"
                    and not engine.has_active_violation(structure["id"])):
                structure["compliance_status"] = "COMPLIANT"
                changed = True
            if changed:
                touch(structure)

    return object_response(certificate)


@bp.post("/elevation-certificates/<certificate_id>/amend")
def amend_certificate(certificate_id):
    user_id, role = require("PropertyOwner")
    certificate = lookup("certificate", certificate_id)
    permit = db.permits.get(certificate["permit_id"])
    _owner_guard(user_id, role, permit)

    data = body()
    datum = req_enum(data, "datum", calc.DATUMS)
    measured_floor = req_num(data, "measured_lowest_floor_ft")
    measured_bfe = req_num(data, "measured_bfe_ft")
    license_no = opt_str(data, "surveyor_license_no")

    if certificate["status"] != "DEFICIENT":
        fail("ERR_CERTIFICATE_NOT_DEFICIENT")
    if certificate["certificate_type"] == "FINISHED_CONSTRUCTION" and not license_no:
        fail("ERR_SURVEYOR_LICENSE_REQUIRED")

    certificate["datum"] = datum
    certificate["measured_lowest_floor_ft"] = calc.dec(measured_floor)
    certificate["measured_bfe_ft"] = calc.dec(measured_bfe)
    certificate["surveyor_license_no"] = license_no
    certificate["status"] = "SUBMITTED"
    certificate["deficiency_codes"] = []
    engine.normalize_certificate(certificate, permit or {})
    touch(certificate)
    return object_response(certificate)
