"""Loads, compartment allocations, plan finalize/reopen."""
from datetime import timedelta

from flask import Blueprint, request

import db
import services as svc
from errors import (
    raise_err, ERR_SHIPPER_NOT_FOUND, ERR_LOAD_NOT_FOUND,
    ERR_COMPARTMENT_NOT_FOUND, ERR_ALLOCATION_NOT_FOUND, ERR_LOAD_NOT_DRAFT,
    ERR_LOAD_NOT_PLANNED, ERR_STALE_VERSION, ERR_SPECIES_MIX_FORBIDDEN,
    ERR_COMPARTMENT_HEAD_EXCEEDED, ERR_COMPARTMENT_WEIGHT_EXCEEDED,
    ERR_MIXED_TRAILER_ALLOCATIONS, ERR_ALLOCATION_TOTAL_MISMATCH,
    ERR_GVWR_EXCEEDED, ERR_INVALID_BACKHAUL_LINK,
)
from middleware import require_role
from response import success
from util import get_body, v_str, v_int, v_num, v_enum, v_dt, paginate, dec, round_half_up_int

bp = Blueprint("loads", __name__)

SPECIES = {"CATTLE", "SWINE", "SHEEP", "HORSES"}


def load_or_404(load_id):
    ld = db.store["loads"].get(load_id)
    if ld is None:
        raise_err(ERR_LOAD_NOT_FOUND)
    return ld


# ---------------------------------------------------------------- loads
@bp.post("/haul/loads")
def create_load():
    require_role("Dispatcher")
    body = get_body()
    shipper_id = v_str(body, "shipper_id")
    species = v_enum(body, "species", SPECIES)
    head = v_int(body, "declared_head_count", min_value=1)
    weight = v_int(body, "declared_weight_lb", min_value=1)
    origin = v_str(body, "origin")
    destination = v_str(body, "destination")
    planned_departure = v_dt(body, "planned_departure_at")
    duration = v_int(body, "planned_duration_hours", min_value=1)
    rate = v_int(body, "rate_per_loaded_mile_cents", min_value=1)
    miles = v_int(body, "loaded_miles", min_value=1)
    shrink_pct = v_num(body, "shrink_allowance_pct", required=False, default=None,
                       min_value=0)
    backhaul_id = v_str(body, "backhaul_of_load_id", required=False, default=None)

    shipper = db.store["shippers"].get(shipper_id)
    if shipper is None:
        raise_err(ERR_SHIPPER_NOT_FOUND)
    if backhaul_id is not None:
        target = db.store["loads"].get(backhaul_id)
        if target is None:
            raise_err(ERR_LOAD_NOT_FOUND, "backhaul target load not found")
        bad = (
            target["status"] != "DELIVERED"
            or target["destination"] != origin
            or target["delivered_at"] is None
            or target["delivered_at"] > planned_departure
            or planned_departure - target["delivered_at"]
            > timedelta(hours=svc.BACKHAUL_WINDOW_HOURS)
        )
        if bad:
            raise_err(ERR_INVALID_BACKHAUL_LINK,
                          "backhaul target must be DELIVERED, destination must equal "
                          "origin, and the gap must be <= 72h")

    rec = svc.new_common()
    rec.update({
        "shipper_id": shipper_id, "species": species,
        "declared_head_count": head, "declared_weight_lb": weight,
        "origin": origin, "destination": destination,
        "planned_departure_at": planned_departure,
        "planned_duration_hours": duration,
        "rate_per_loaded_mile_cents": rate, "loaded_miles": miles,
        "shrink_allowance_pct": shrink_pct,
        "effective_shrink_pct": shrink_pct if shrink_pct is not None
        else shipper["default_shrink_allowance_pct"],
        "backhaul_of_load_id": backhaul_id,
        "driver_id": None, "trailer_id": None, "status": "DRAFT",
        "confinement_anchor_at": None, "rest_unload_started_at": None,
        "departed_at": None, "arrived_at": None, "delivered_at": None,
    })
    db.store["loads"][rec["id"]] = rec
    return success(svc.load_json(rec), status=201)


@bp.get("/haul/loads")
def list_loads():
    items = sorted(db.store["loads"].values(), key=lambda l: l["seq"])
    for param in ("status", "shipper_id", "driver_id", "trailer_id",
                  "backhaul_of_load_id"):
        val = request.args.get(param)
        if val is not None:
            items = [l for l in items if l[param] == val]
    page, meta = paginate([svc.load_json(l) for l in items])
    return success(page, response_type="array", pagination=meta)


@bp.get("/haul/loads/<lid>")
def get_load(lid):
    return success(svc.load_json(load_or_404(lid)))


# ---------------------------------------------------------------- allocations
@bp.post("/haul/loads/<lid>/allocations")
def create_allocation(lid):
    require_role("Dispatcher")
    body = get_body()
    compartment_id = v_str(body, "trailer_compartment_id")
    head_count = v_int(body, "head_count", min_value=1)
    avg_weight = v_num(body, "avg_weight_lb", min_value=0, exclusive_min=True)
    expected_version = v_int(body, "expected_load_version")
    ld = load_or_404(lid)
    comp = db.store["compartments"].get(compartment_id)
    if comp is None:
        raise_err(ERR_COMPARTMENT_NOT_FOUND)
    if ld["status"] != "DRAFT":
        raise_err(ERR_LOAD_NOT_DRAFT, "allocations may only be created while DRAFT")
    if expected_version != ld["version"]:
        raise_err(ERR_STALE_VERSION, "expected_load_version does not match load version")
    # species: no ACTIVE allocation of a different species in this compartment
    for a in db.store["allocations"].values():
        if (a["trailer_compartment_id"] == compartment_id and a["status"] == "ACTIVE"):
            other = db.store["loads"].get(a["load_id"])
            if other is not None and other["species"] != ld["species"]:
                raise_err(ERR_SPECIES_MIX_FORBIDDEN,
                          "compartment already holds a different species")
    weight_lb = round_half_up_int(dec(head_count) * dec(avg_weight))
    occ_head, occ_weight = svc.compartment_occupied(compartment_id)
    if occ_head + head_count > comp["max_head_count"]:
        raise_err(ERR_COMPARTMENT_HEAD_EXCEEDED, "compartment head capacity exceeded")
    if occ_weight + weight_lb > comp["max_weight_lb"]:
        raise_err(ERR_COMPARTMENT_WEIGHT_EXCEEDED, "compartment weight capacity exceeded")
    rec = svc.new_common()
    rec.update({
        "load_id": lid, "trailer_compartment_id": compartment_id,
        "head_count": head_count, "avg_weight_lb": avg_weight,
        "weight_lb": weight_lb, "status": "ACTIVE", "release_reason": None,
    })
    db.store["allocations"][rec["id"]] = rec
    svc.touch(ld)
    return success(svc.allocation_json(rec), status=201)


@bp.get("/haul/loads/<lid>/allocations")
def list_load_allocations(lid):
    load_or_404(lid)
    items = [a for a in db.store["allocations"].values() if a["load_id"] == lid]
    st = request.args.get("status")
    if st is not None:
        items = [a for a in items if a["status"] == st]
    items.sort(key=lambda a: a["seq"])
    page, meta = paginate([svc.allocation_json(a) for a in items])
    return success(page, response_type="array", pagination=meta)


@bp.get("/haul/allocations/<aid>")
def get_allocation(aid):
    a = db.store["allocations"].get(aid)
    if a is None:
        raise_err(ERR_ALLOCATION_NOT_FOUND)
    return success(svc.allocation_json(a))


@bp.get("/haul/allocations")
def list_allocations():
    items = sorted(db.store["allocations"].values(), key=lambda a: a["seq"])
    for param in ("trailer_compartment_id", "load_id", "status"):
        val = request.args.get(param)
        if val is not None:
            items = [a for a in items if a[param] == val]
    page, meta = paginate([svc.allocation_json(a) for a in items])
    return success(page, response_type="array", pagination=meta)


@bp.post("/haul/allocations/<aid>/release")
def release_allocation(aid):
    require_role("Dispatcher")
    body = get_body()
    expected_version = v_int(body, "expected_load_version")
    a = db.store["allocations"].get(aid)
    if a is None:
        raise_err(ERR_ALLOCATION_NOT_FOUND)
    ld = db.store["loads"].get(a["load_id"])
    if ld["status"] != "DRAFT":
        raise_err(ERR_LOAD_NOT_DRAFT, "manual release requires the load in DRAFT")
    if expected_version != ld["version"]:
        raise_err(ERR_STALE_VERSION, "expected_load_version does not match load version")
    a["status"] = "RELEASED"
    a["release_reason"] = "REPLANNED"
    svc.touch(a)
    svc.touch(ld)
    return success(svc.allocation_json(a))


# ---------------------------------------------------------------- plan
@bp.post("/haul/loads/<lid>/finalize-plan")
def finalize_plan(lid):
    require_role("Dispatcher")
    ld = load_or_404(lid)
    if ld["status"] != "DRAFT":
        raise_err(ERR_LOAD_NOT_DRAFT, "finalize-plan requires DRAFT")
    actives = [a for a in db.store["allocations"].values()
               if a["load_id"] == lid and a["status"] == "ACTIVE"]
    trailer_ids = set()
    for a in actives:
        comp = db.store["compartments"].get(a["trailer_compartment_id"])
        if comp is not None:
            trailer_ids.add(comp["trailer_id"])
    if len(trailer_ids) > 1:
        raise_err(ERR_MIXED_TRAILER_ALLOCATIONS,
                  "ACTIVE allocations span more than one trailer")
    head, weight = svc.load_totals(lid)
    if (not actives or head != ld["declared_head_count"]
            or weight != ld["declared_weight_lb"]):
        raise_err(ERR_ALLOCATION_TOTAL_MISMATCH,
                  "allocated totals must equal declared totals")
    trailer = db.store["trailers"].get(next(iter(trailer_ids)))
    if weight > trailer["max_gross_weight_lb"]:
        raise_err(ERR_GVWR_EXCEEDED, "allocated weight exceeds trailer GVWR")
    ld["trailer_id"] = trailer["id"]
    ld["status"] = "PLANNED"
    svc.touch(ld)
    return success(svc.load_json(ld))


@bp.post("/haul/loads/<lid>/reopen-plan")
def reopen_plan(lid):
    require_role("Dispatcher")
    ld = load_or_404(lid)
    if ld["status"] != "PLANNED":
        raise_err(ERR_LOAD_NOT_PLANNED, "reopen-plan requires PLANNED")
    svc.release_allocations(ld, "REPLANNED")
    ld["trailer_id"] = None
    ld["status"] = "DRAFT"
    svc.touch(ld)
    return success(svc.load_json(ld))
