"""The electrical chain: power distribution units, busway runs and branch feeds."""

from flask import Blueprint, request

import db
import validation as v
from constants import FEED_SIDES, ROLE_ELECTRICAL_CONTRACTOR, STAFF_ROLES, TOPOLOGIES
from errors import ApiError
from middleware import endpoint
from output import created, filtered, listing, ok, require
from services import calc, cascade
from util import D, q

bp = Blueprint("electrical", __name__)

READ_ROLES = list(STAFF_ROLES)
EC = [ROLE_ELECTRICAL_CONTRACTOR]


# ------------------------------------------------------- distribution units ----

@bp.post("/pdus")
@endpoint(EC)
def create_pdu():
    payload = v.body()
    hall_id = v.fk_field(payload, "hall_id")
    name = v.string_field(payload, "name")
    feed_side = v.enum_field(payload, "feed_side", FEED_SIDES)
    rated_kw = v.number_field(payload, "rated_kw", gt=0, places=2)

    hall = require("halls", hall_id)
    pdu = db.new_row(
        "pdus",
        {
            "hall_id": hall["id"],
            "name": name,
            "feed_side": feed_side,
            "rated_kw": rated_kw,
            "measured_derate_factor": q(1, 2),
            "usable_cap_kw": q(rated_kw * D("0.80"), 3),
            "status": "PLANNED",
        },
    )
    return created(pdu)


@bp.get("/pdus")
@endpoint(READ_ROLES)
def list_pdus():
    return listing(
        filtered(
            "pdus",
            {"hall_id": "hall_id", "feed_side": "feed_side", "status": "status"},
        )
    )


@bp.get("/pdus/<pdu_id>")
@endpoint(READ_ROLES)
def read_pdu(pdu_id):
    return ok(require("pdus", pdu_id))


@bp.patch("/pdus/<pdu_id>")
@endpoint(EC)
def record_pdu_derate(pdu_id):
    payload = v.body()
    factor = v.number_field(
        payload, "measured_derate_factor", ge=D("0.50"), le=D("1.00"), places=2
    )
    pdu = require("pdus", pdu_id)

    if pdu["status"] != "PLANNED":
        raise ApiError("ERR_INVALID_STATE")

    hall = db.get("halls", pdu["hall_id"])
    busways = db.where("busways", pdu_id=pdu["id"])
    covered = [pdu["id"]] + [b["id"] for b in busways]
    cascade.require_covering_mop(hall, covered)

    pdu["measured_derate_factor"] = factor
    pdu["status"] = "COMMISSIONED"
    db.touch(pdu)
    for busway in busways:
        calc.apply_busway_ceiling(busway)
    return ok(pdu)


# ------------------------------------------------------------- busway runs ----

@bp.post("/busways")
@endpoint(EC)
def create_busway():
    payload = v.body()
    pdu_id = v.fk_field(payload, "pdu_id")
    name = v.string_field(payload, "name")
    rated_amps = v.int_field(payload, "rated_amps", ge=1)
    voltage_v = v.int_field(payload, "voltage_v", allowed=[400, 415, 480])
    topology = v.enum_field(payload, "redundancy_topology", TOPOLOGIES)
    declared_hall = v.optional_string_or_null(payload, "hall_id")

    pdu = require("pdus", pdu_id)
    if declared_hall not in (None, v.MISSING):
        hall_row = require("halls", declared_hall)
        if hall_row["id"] != pdu["hall_id"]:
            raise ApiError("ERR_HALL_MISMATCH")

    for row in db.where("busways", pdu_id=pdu["id"]):
        if row["name"] == name:
            raise ApiError("ERR_DUPLICATE_CODE")

    hall = db.get("halls", pdu["hall_id"])
    busway = db.new_row(
        "busways",
        {
            "pdu_id": pdu["id"],
            "hall_id": pdu["hall_id"],
            "name": name,
            "rated_amps": rated_amps,
            "voltage_v": voltage_v,
            "redundancy_topology": topology,
            "feed_side": pdu["feed_side"],
            "raw_kw": q(0, 3),
            "usable_kw": q(0, 2),
            "usable_variant": calc.variant_for_hall(hall),
            "committed_kw": q(0, 3),
            "feed_count": 0,
            "status": "INSTALLED",
        },
    )
    calc.apply_busway_ceiling(busway)
    return created(busway)


@bp.get("/busways")
@endpoint(READ_ROLES)
def list_busways():
    return listing(
        filtered(
            "busways",
            {"pdu_id": "pdu_id", "hall_id": "hall_id", "status": "status"},
        )
    )


@bp.get("/busways/<busway_id>")
@endpoint(READ_ROLES)
def read_busway(busway_id):
    return ok(require("busways", busway_id))


@bp.post("/busways/<busway_id>/energize")
@endpoint(EC)
def energize_busway(busway_id):
    busway = require("busways", busway_id)
    if busway["status"] != "INSTALLED":
        raise ApiError("ERR_INVALID_STATE")
    hall = db.get("halls", busway["hall_id"])
    if hall["status"] == "PLANNING":
        raise ApiError("ERR_HALL_PHASE_INVALID")
    pdu = db.get("pdus", busway["pdu_id"])
    if pdu["status"] != "COMMISSIONED":
        raise ApiError("ERR_PDU_NOT_COMMISSIONED")

    busway["status"] = "ENERGIZED"
    db.touch(busway)
    calc.apply_busway_ceiling(busway, calc.variant_for_hall(hall))
    return ok(busway)


# ------------------------------------------------------------ branch feeds ----

@bp.post("/rack-feeds")
@endpoint(EC)
def create_feed():
    payload = v.body()
    rack_id = v.fk_field(payload, "rack_id")
    busway_id = v.fk_field(payload, "busway_id")
    v.enum_field(payload, "feed_side", FEED_SIDES)
    requested_kw = v.number_field(payload, "requested_kw", gt=0)
    breaker_amps = v.int_field(payload, "breaker_amps", ge=1)

    rack = require("racks", rack_id)
    busway = require("busways", busway_id)

    if busway["hall_id"] != rack["hall_id"]:
        raise ApiError("ERR_HALL_MISMATCH")

    side = busway["feed_side"]
    for peer in db.where("feeds", rack_id=rack["id"]):
        if peer["status"] != "RELEASED" and peer["feed_side"] == side:
            raise ApiError("ERR_DUPLICATE_FEED_SIDE")

    hall = db.get("halls", rack["hall_id"])
    if hall["status"] not in ("FIT_OUT", "COMMISSIONING"):
        raise ApiError("ERR_HALL_PHASE_INVALID")
    if busway["status"] == "ISOLATED":
        raise ApiError("ERR_BUSWAY_NOT_ENERGIZED")

    allocated = q(requested_kw, 3)

    ceiling = calc.busway_usable_kw(busway, busway["usable_variant"])
    if D(busway["committed_kw"]) + allocated > ceiling:
        raise ApiError("ERR_BUSWAY_CAPACITY_EXCEEDED")

    _committed, _reserve, spare = calc.compute_ledger(hall, extra_kw=allocated)
    if spare < D("0.00"):
        raise ApiError("ERR_HALL_SPARE_CAPACITY_EXCEEDED")

    breaker_ceiling = calc.breaker_continuous_kw(breaker_amps, busway["voltage_v"])
    if allocated > breaker_ceiling:
        raise ApiError("ERR_BREAKER_DERATE_EXCEEDED")

    feed = db.new_row(
        "feeds",
        {
            "rack_id": rack["id"],
            "busway_id": busway["id"],
            "feed_side": side,
            "allocated_kw": allocated,
            "breaker_amps": breaker_amps,
            "status": "RESERVED",
            "released_at": None,
        },
    )
    calc.apply_busway_load(busway)
    calc.apply_rack_load(rack)
    calc.apply_ledger(hall)
    return created(feed)


@bp.get("/rack-feeds")
@endpoint(READ_ROLES)
def list_feeds():
    rows = filtered(
        "feeds",
        {"rack_id": "rack_id", "busway_id": "busway_id", "status": "status"},
    )
    if not v.truthy(request.args.get("include_released")):
        rows = [r for r in rows if r["status"] != "RELEASED"]
    return listing(rows)


@bp.get("/rack-feeds/<feed_id>")
@endpoint(READ_ROLES)
def read_feed(feed_id):
    return ok(require("feeds", feed_id))


@bp.delete("/rack-feeds/<feed_id>")
@endpoint(EC)
def release_feed(feed_id):
    feed = require("feeds", feed_id)
    rack = db.get("racks", feed["rack_id"])
    if feed["status"] != "RESERVED":
        raise ApiError("ERR_INVALID_STATE")
    if rack["status"] not in ("PLANNED", "INSTALLED"):
        raise ApiError("ERR_INVALID_STATE")

    feed["status"] = "RELEASED"
    feed["released_at"] = db.clock_now()
    db.touch(feed)

    busway = db.get("busways", feed["busway_id"])
    hall = db.get("halls", rack["hall_id"])
    calc.apply_busway_load(busway)
    calc.apply_rack_load(rack)
    calc.apply_ledger(hall)
    return ok(feed)
