"""Rack positions: layout, as-built tagging, installation and energisation."""

from flask import Blueprint

import db
import validation as v
from constants import (
    ALL_ROLES,
    ROLE_ELECTRICAL_CONTRACTOR,
    ROLE_FACILITY_PLANNER,
    STAFF_ROLES,
)
from errors import ApiError
from middleware import caller_tenant_id, endpoint, is_tenant_caller
from output import created, filtered, listing, ok, require
from services import calc
from util import D, q

bp = Blueprint("racks", __name__)

READ_ROLES = list(STAFF_ROLES)
TENANT_READ_ROLES = list(ALL_ROLES)
FP = [ROLE_FACILITY_PLANNER]
EC = [ROLE_ELECTRICAL_CONTRACTOR]


def refresh_draft_packets(rack):
    """As-built tagging keeps every DRAFT packet of the rack's cage honest."""
    if not rack.get("cage_id"):
        return
    for packet in db.where("packets", cage_id=rack["cage_id"], status="DRAFT"):
        calc.apply_packet_figures(packet)


@bp.post("/racks")
@endpoint(FP)
def create_rack():
    payload = v.body()
    hall_id = v.fk_field(payload, "hall_id")
    zone_id = v.fk_field(payload, "containment_zone_id")
    grid_row = v.string_field(payload, "grid_row", min_len=1, max_len=4)
    grid_col = v.int_field(payload, "grid_col", ge=1)
    design_kw = v.number_field(payload, "design_kw", gt=0, places=2)
    u_height = v.int_field(
        payload, "u_height", required=False, allowed=[42, 45, 48], default=42
    )
    required_feeds = v.int_field(
        payload, "required_feed_count", required=False, allowed=[1, 2], default=2
    )
    cage_id = v.fk_field(payload, "cage_id", required=False)
    tenant_id = v.fk_field(payload, "tenant_id", required=False)
    asset_tag = v.string_field(payload, "asset_tag", required=False)

    hall = require("halls", hall_id)
    zone = require("zones", zone_id)
    cage = require("cages", cage_id) if cage_id else None
    tenant = require("tenants", tenant_id) if tenant_id else None

    if zone["hall_id"] != hall["id"]:
        raise ApiError("ERR_HALL_MISMATCH")
    if cage is not None and cage["hall_id"] != hall["id"]:
        raise ApiError("ERR_HALL_MISMATCH")
    # PRD 2.5: a cage's tenant may not contradict the tenant of the racks the cage
    # contains, and the disagreement is refused on rack creation.
    if cage is not None and tenant is not None and cage["tenant_id"] != tenant["id"]:
        raise ApiError("ERR_HALL_MISMATCH")

    for row in db.where("racks", hall_id=hall["id"]):
        if row["grid_row"] == grid_row and row["grid_col"] == grid_col:
            raise ApiError("ERR_DUPLICATE_GRID_POSITION")

    rack = db.new_row(
        "racks",
        {
            "hall_id": hall["id"],
            "containment_zone_id": zone["id"],
            "cage_id": cage["id"] if cage else None,
            "tenant_id": tenant["id"] if tenant else None,
            "grid_row": grid_row,
            "grid_col": grid_col,
            "design_kw": design_kw,
            "required_feed_count": required_feeds,
            "u_height": u_height,
            "asset_tag": asset_tag,
            "status": "PLANNED",
            "pre_risk_status": None,
            "connected_kw": q(0, 3),
            "energized_feed_count": 0,
            "chargeable_kw": q(design_kw * D("1.045"), 2),
        },
    )
    calc.apply_custody(hall)
    return created(rack)


@bp.get("/racks")
@endpoint(TENANT_READ_ROLES)
def list_racks():
    rows = filtered(
        "racks",
        {
            "hall_id": "hall_id",
            "cage_id": "cage_id",
            "containment_zone_id": "containment_zone_id",
            "tenant_id": "tenant_id",
            "status": "status",
        },
    )
    if is_tenant_caller():
        rows = [r for r in rows if r.get("tenant_id") == caller_tenant_id()]
    return listing(rows)


@bp.get("/racks/<rack_id>")
@endpoint(TENANT_READ_ROLES)
def read_rack(rack_id):
    rack = require("racks", rack_id)
    if is_tenant_caller() and rack.get("tenant_id") != caller_tenant_id():
        raise ApiError("ERR_TENANT_SCOPE_VIOLATION")
    return ok(rack)


@bp.patch("/racks/<rack_id>")
@endpoint(FP)
def tag_rack(rack_id):
    payload = v.body()
    asset_tag = v.string_field(payload, "asset_tag", allow_empty=False)
    rack = require("racks", rack_id)
    rack["asset_tag"] = asset_tag
    db.touch(rack)
    refresh_draft_packets(rack)
    return ok(rack)


@bp.post("/racks/<rack_id>/install")
@endpoint(FP)
def install_rack(rack_id):
    payload = v.body()
    asset_tag = v.string_field(payload, "asset_tag", required=False)
    rack = require("racks", rack_id)

    if rack["status"] != "PLANNED":
        raise ApiError("ERR_INVALID_STATE")
    hall = db.get("halls", rack["hall_id"])
    if hall["status"] not in ("FIT_OUT", "COMMISSIONING", "LIVE"):
        raise ApiError("ERR_HALL_PHASE_INVALID")

    tenant = db.get("tenants", rack["tenant_id"]) if rack.get("tenant_id") else None
    if tenant is not None:
        projected = calc.compute_tenant_allocated(tenant, extra_rack=rack)
        if projected > D(tenant["contracted_kw"]):
            raise ApiError("ERR_TENANT_CONTRACT_EXCEEDED")

    rack["status"] = "INSTALLED"
    if asset_tag is not None:
        rack["asset_tag"] = asset_tag
    db.touch(rack)
    calc.apply_tenant_allocated(tenant)
    calc.apply_chargeable(hall)
    calc.apply_custody(hall)
    return ok(rack)


@bp.post("/racks/<rack_id>/power-on")
@endpoint(EC)
def power_on_rack(rack_id):
    rack = require("racks", rack_id)
    if rack["status"] != "INSTALLED":
        raise ApiError("ERR_INVALID_STATE")

    hall = db.get("halls", rack["hall_id"])
    if hall["status"] not in ("FIT_OUT", "COMMISSIONING", "LIVE"):
        raise ApiError("ERR_HALL_PHASE_INVALID")

    reserved = db.where("feeds", rack_id=rack["id"], status="RESERVED")
    for feed in reserved:
        busway = db.get("busways", feed["busway_id"])
        if busway is None or busway["status"] != "ENERGIZED":
            raise ApiError("ERR_BUSWAY_NOT_ENERGIZED")

    zone = db.get("zones", rack["containment_zone_id"])
    if zone is None or zone["leakage_status"] != "PASS":
        raise ApiError("ERR_CONTAINMENT_NOT_PASSED")

    if len(reserved) != rack["required_feed_count"]:
        raise ApiError("ERR_FEED_TOPOLOGY_INCOMPLETE")
    if rack["required_feed_count"] == 2:
        sides = set(f["feed_side"] for f in reserved)
        if len(sides) != 2:
            raise ApiError("ERR_FEED_TOPOLOGY_INCOMPLETE")

    if hall["release_posture"] == "LOCKED":
        raise ApiError("ERR_RELEASE_POSTURE_BLOCKED")

    projected = calc.compute_cooling(hall, extra_rack_ids=[rack["id"]])
    if projected["cooling_margin_kw"] < D("0.00"):
        raise ApiError("ERR_COOLING_MARGIN_EXCEEDED")

    for feed in reserved:
        feed["status"] = "ENERGIZED"
        db.touch(feed)
    rack["status"] = "POWERED"
    db.touch(rack)
    calc.apply_rack_load(rack)
    calc.rack_chain(hall)
    return ok(rack)
