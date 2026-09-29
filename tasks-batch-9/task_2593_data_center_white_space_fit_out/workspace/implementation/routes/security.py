"""Cages, cameras and card readers."""

from flask import Blueprint

import db
import validation as v
from constants import (
    ALL_ROLES,
    DEVICE_TYPES,
    ROLE_SECURITY_ADMINISTRATOR,
    STAFF_ROLES,
)
from errors import ApiError
from middleware import caller_tenant_id, endpoint, is_tenant_caller
from output import created, filtered, listing, ok, require
from services import calc
from util import D, q

bp = Blueprint("security", __name__)

READ_ROLES = list(STAFF_ROLES)
TENANT_READ_ROLES = list(ALL_ROLES)
SA = [ROLE_SECURITY_ADMINISTRATOR]


# ----------------------------------------------------------------- cages ----

@bp.post("/cages")
@endpoint(SA)
def create_cage():
    payload = v.body()
    hall_id = v.fk_field(payload, "hall_id")
    tenant_id = v.fk_field(payload, "tenant_id")
    label = v.string_field(payload, "label", min_len=1, max_len=16)
    perimeter = v.number_field(payload, "perimeter_length_m", gt=0, places=1)
    coverage = v.number_field(
        payload,
        "required_camera_coverage_pct",
        required=False,
        gt=0,
        le=D("100.00"),
        places=2,
        default=q("95.00", 2),
    )
    zones = v.int_field(
        payload, "required_reader_zone_count", required=False, ge=1, default=2
    )

    hall = require("halls", hall_id)
    tenant = require("tenants", tenant_id)

    for row in db.where("cages", hall_id=hall["id"]):
        if row["label"] == label:
            raise ApiError("ERR_DUPLICATE_CODE")

    cage = db.new_row(
        "cages",
        {
            "hall_id": hall["id"],
            "tenant_id": tenant["id"],
            "label": label,
            "perimeter_length_m": perimeter,
            "required_camera_coverage_pct": coverage,
            "required_reader_zone_count": zones,
            "camera_coverage_pct": q(0, 2),
            "active_reader_zone_count": 0,
            "operational_status": "FIT_OUT",
        },
    )
    return created(cage)


@bp.get("/cages")
@endpoint(TENANT_READ_ROLES)
def list_cages():
    rows = filtered(
        "cages",
        {
            "hall_id": "hall_id",
            "tenant_id": "tenant_id",
            "operational_status": "operational_status",
        },
    )
    if is_tenant_caller():
        rows = [r for r in rows if r["tenant_id"] == caller_tenant_id()]
    return listing(rows)


@bp.get("/cages/<cage_id>")
@endpoint(TENANT_READ_ROLES)
def read_cage(cage_id):
    cage = require("cages", cage_id)
    if is_tenant_caller() and cage["tenant_id"] != caller_tenant_id():
        raise ApiError("ERR_TENANT_SCOPE_VIOLATION")
    return ok(cage)


# ------------------------------------------------------- security devices ----

@bp.post("/security-devices")
@endpoint(SA)
def create_device():
    payload = v.body()
    cage_id = v.fk_field(payload, "cage_id")
    device_type = v.enum_field(payload, "device_type", DEVICE_TYPES)
    label = v.string_field(payload, "label", min_len=1, max_len=16)

    covered = None
    reader_zone = None
    if device_type == "CAMERA":
        covered = v.number_field(payload, "covered_length_m", gt=0, places=1)
        if v.present(payload, "reader_zone_label"):
            v.fail("reader_zone_label", "must be omitted for a CAMERA device.")
    else:
        reader_zone = v.string_field(
            payload, "reader_zone_label", min_len=1, allow_empty=False
        )
        if v.present(payload, "covered_length_m"):
            v.fail("covered_length_m", "must be omitted for a CARD_READER device.")

    cage = require("cages", cage_id)
    for row in db.where("devices", cage_id=cage["id"]):
        if row["label"] == label:
            raise ApiError("ERR_DUPLICATE_CODE")

    device = db.new_row(
        "devices",
        {
            "cage_id": cage["id"],
            "device_type": device_type,
            "label": label,
            "covered_length_m": covered,
            "reader_zone_label": reader_zone,
            "status": "PLANNED",
        },
    )
    return created(device)


@bp.get("/security-devices")
@endpoint(READ_ROLES)
def list_devices():
    return listing(
        filtered(
            "devices",
            {"cage_id": "cage_id", "device_type": "device_type", "status": "status"},
        )
    )


@bp.get("/security-devices/<device_id>")
@endpoint(READ_ROLES)
def read_device(device_id):
    return ok(require("devices", device_id))


@bp.post("/security-devices/<device_id>/commission")
@endpoint(SA)
def commission_device(device_id):
    device = require("devices", device_id)
    if device["status"] != "PLANNED":
        raise ApiError("ERR_INVALID_STATE")
    device["status"] = "ACTIVE"
    db.touch(device)
    cage = db.get("cages", device["cage_id"])
    db.touch(cage)  # the commissioning re-derives the cage: always a version bump
    calc.apply_cage_coverage(cage)
    return ok(device)
