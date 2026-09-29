"""Design licences and print films (PRD 3.3)."""

import re
from decimal import Decimal

from flask import Blueprint, request

import calc
import cascades
from db import db, new_row, now, serialize as _ser, touch
from errors import ApiError
from middleware import authorize, find, require_role
from response import enum_filter, list_response, object_response, string_filter
from support import STATUS_CREATED, body, license_active_check, unique
from validate import field as F
from validate import invalid, validate

bp = Blueprint("design", __name__)

TERRITORY = re.compile(r"^[A-Z]{2}$")

LICENSE_TYPE = ("EXCLUSIVE", "NON_EXCLUSIVE", "INTERNAL")
LICENSE_STATUS = ("ACTIVE", "SUSPENDED", "EXPIRED", "SUPERSEDED", "TERMINATED")
FILM_STATUS = ("AVAILABLE", "RESTRICTED", "WITHDRAWN")

LICENSE_READERS = ("PlantAdmin", "TechnicalDirector", "ProductionPlanner", "Formulator")
FILM_READERS = ("PlantAdmin", "TechnicalDirector", "ProductionPlanner", "QaTechnician")

ZERO2 = Decimal("0.00")


# ---------------------------------------------------------------------------
# DesignLicense
# ---------------------------------------------------------------------------

LICENSE_CREATE = [
    F("license_code", "string", required=True),
    F("licensor_name", "string", required=True),
    F("license_type", "string", required=True, enum=LICENSE_TYPE),
    F("royalty_rate_bps", "integer", required=True, min=0, max=2000),
    F("valid_from", "datetime", required=True),
    F("valid_until", "datetime", required=True),
    F("term_volume_cap_sqm", "number", required=True, exclusive_min=0, decimals=2),
    F("territory_codes", "array", required=True, non_empty=True,
      item=F("territory_codes[]", "string", regex=TERRITORY)),
]


@bp.post("/design-licenses")
def create_license():
    authorize("PlantAdmin")
    data = validate(LICENSE_CREATE, body())
    if data["valid_until"] <= data["valid_from"]:
        invalid()
    unique("design_licenses", "license_code", data["license_code"])
    row = new_row()
    row.update(data)
    row.update({
        "reserved_volume_sqm": ZERO2,
        "consumed_volume_sqm": ZERO2,
        "accrued_royalty_cents": 0,
        "status": "ACTIVE",
        "supersedes_license_id": None,
        "amendment_note": None,
    })
    db.design_licenses[row["id"]] = row
    return object_response(_ser(row), STATUS_CREATED)


@bp.get("/design-licenses")
def list_licenses():
    authorize(*LICENSE_READERS)
    status = enum_filter(request.args, "status", LICENSE_STATUS)
    parent = string_filter(request.args, "supersedes_license_id")
    license_type = enum_filter(request.args, "license_type", LICENSE_TYPE)
    rows = [r for r in db.design_licenses.values()
            if (status is None or r["status"] == status)
            and (parent is None or r["supersedes_license_id"] == parent)
            and (license_type is None or r["license_type"] == license_type)]
    return list_response(rows, request.args, _ser)


@bp.get("/design-licenses/<row_id>")
def read_license(row_id):
    authorize(*LICENSE_READERS)
    return object_response(_ser(find("design_licenses", row_id)))


@bp.get("/design-licenses/<row_id>/utilization")
def license_utilization(row_id):
    authorize("PlantAdmin", "TechnicalDirector", "ProductionPlanner")
    license_row = find("design_licenses", row_id)
    return object_response(_ser(calc.license_utilization(license_row)))


@bp.post("/design-licenses/<row_id>/amendments")
def amend_license(row_id):
    authorize("TechnicalDirector")
    data = validate([
        F("license_code", "string", required=True),
        F("term_volume_cap_sqm", "number", required=True, exclusive_min=0, decimals=2),
        F("valid_until", "datetime"),
        F("royalty_rate_bps", "integer", min=0, max=2000),
        F("amendment_note", "string"),
    ], body())
    parent = find("design_licenses", row_id)
    valid_until = data["valid_until"] if data["valid_until"] is not None else parent["valid_until"]
    if valid_until <= parent["valid_from"]:
        invalid()
    if parent["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_LICENSE_STATE")
    unique("design_licenses", "license_code", data["license_code"])
    committed = calc.rhu(calc.d(parent["consumed_volume_sqm"])
                         + calc.d(parent["reserved_volume_sqm"]), 2)
    if data["term_volume_cap_sqm"] < committed:
        raise ApiError("ERR_LICENSE_VOLUME_CAP_EXCEEDED")

    successor = new_row()
    successor.update({
        "license_code": data["license_code"],
        "licensor_name": parent["licensor_name"],
        "license_type": parent["license_type"],
        "royalty_rate_bps": (data["royalty_rate_bps"] if data["royalty_rate_bps"] is not None
                             else parent["royalty_rate_bps"]),
        "valid_from": parent["valid_from"],
        "valid_until": valid_until,
        "term_volume_cap_sqm": data["term_volume_cap_sqm"],
        "reserved_volume_sqm": parent["reserved_volume_sqm"],
        "consumed_volume_sqm": parent["consumed_volume_sqm"],
        "accrued_royalty_cents": parent["accrued_royalty_cents"],
        "territory_codes": list(parent["territory_codes"]),
        "status": "ACTIVE",
        "supersedes_license_id": parent["id"],
        "amendment_note": data["amendment_note"],
    })
    db.design_licenses[successor["id"]] = successor
    cascades.license_superseded(parent, successor)
    parent["status"] = "SUPERSEDED"
    touch(parent)
    return object_response(_ser(successor), STATUS_CREATED)


LICENSE_FROM = {
    "SUSPENDED": ("ACTIVE",),
    "ACTIVE": ("SUSPENDED",),
    "TERMINATED": ("ACTIVE", "SUSPENDED"),
}


@bp.post("/design-licenses/<row_id>/status")
def license_status(row_id):
    authorize("PlantAdmin", "TechnicalDirector")
    data = validate([F("to_status", "string", required=True, enum=LICENSE_STATUS)], body())
    to_status = data["to_status"]
    if to_status == "TERMINATED":
        require_role("TechnicalDirector")
    elif to_status in ("ACTIVE", "SUSPENDED"):
        require_role("PlantAdmin")

    license_row = find("design_licenses", row_id)
    allowed_from = LICENSE_FROM.get(to_status, ())
    if license_row["status"] not in allowed_from:
        raise ApiError("ERR_INVALID_LICENSE_STATE")
    if to_status == "ACTIVE" and now() >= license_row["valid_until"]:
        raise ApiError("ERR_LICENSE_EXPIRED")

    license_row["status"] = to_status
    touch(license_row)
    if to_status == "SUSPENDED":
        cascades.license_suspended(license_row)
    elif to_status == "ACTIVE":
        cascades.license_reactivated(license_row)
    else:
        cascades.license_terminated(license_row)
    return object_response(_ser(license_row))


# ---------------------------------------------------------------------------
# PrintFilm
# ---------------------------------------------------------------------------

FILM_CREATE = [
    F("design_code", "string", required=True),
    F("license_id", "string", required=True),
    F("pattern_repeat_mm_length", "number", required=True, exclusive_min=0),
    F("pattern_repeat_mm_width", "number", required=True, exclusive_min=0),
    F("registration_tolerance_mm", "number", required=True, exclusive_min=0),
    F("emboss_plate_code", "string", required=True),
    F("emboss_alignment_offset_mm", "number", required=True),
    F("master_roll_sets", "integer", required=True, min=1),
]


@bp.post("/print-films")
def create_film():
    authorize("PlantAdmin")
    data = validate(FILM_CREATE, body())
    license_row = find("design_licenses", data["license_id"])
    unique("print_films", "design_code", data["design_code"])
    license_active_check(license_row)
    row = new_row()
    row.update(data)
    row["status"] = "AVAILABLE"
    db.print_films[row["id"]] = row
    return object_response(_ser(row), STATUS_CREATED)


@bp.get("/print-films")
def list_films():
    authorize(*FILM_READERS)
    status = enum_filter(request.args, "status", FILM_STATUS)
    license_id = string_filter(request.args, "license_id")
    rows = [r for r in db.print_films.values()
            if (status is None or r["status"] == status)
            and (license_id is None or r["license_id"] == license_id)]
    return list_response(rows, request.args, _ser)


@bp.get("/print-films/<row_id>")
def read_film(row_id):
    authorize(*FILM_READERS)
    return object_response(_ser(find("print_films", row_id)))


FILM_FROM = {
    "RESTRICTED": ("AVAILABLE",),
    "AVAILABLE": ("RESTRICTED",),
    "WITHDRAWN": ("AVAILABLE", "RESTRICTED"),
}


@bp.post("/print-films/<row_id>/status")
def film_status(row_id):
    authorize("PlantAdmin")
    data = validate([F("to_status", "string", required=True, enum=FILM_STATUS)], body())
    to_status = data["to_status"]
    film = find("print_films", row_id)
    if film["status"] not in FILM_FROM[to_status]:
        raise ApiError("ERR_INVALID_PRINT_FILM_STATE")
    if to_status == "AVAILABLE":
        license_row = db.design_licenses.get(film["license_id"])
        if license_row is None or license_row["status"] != "ACTIVE":
            raise ApiError("ERR_INVALID_PRINT_FILM_STATE")
    film["status"] = to_status
    touch(film)
    return object_response(_ser(film))


__all__ = ["bp"]
