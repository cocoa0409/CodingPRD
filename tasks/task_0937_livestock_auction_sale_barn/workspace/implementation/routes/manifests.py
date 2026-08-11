"""Trucking: load manifests, load lines, dispatch and delivery (PRD 3.9)."""
from flask import Blueprint

import config
import serialize
from auth import actor, ownership
from bodyval import body, check_min, enum_field, fields, path_row, reference
from clock import clock, render_instant
from envelope import filter_arg, ok, paginate
from errors import fail
from gates import run_gates
from money import D, q2
from services.charges import add_charge_line
from services.manifests import manifest_lines, recompute_manifest
from services.pens import recompute_pens
from store import db, get, insert, insert_versioned, touch

bp = Blueprint("manifests", __name__)
ALL = config.ALL_ROLES


@bp.post("/sale-barn/load-manifests")
def create_manifest():
    role, user_id = actor(["Carrier"])
    data = body()
    v = fields(data, required=[
        ("sale_day_id", "string"),
        ("carrier_party_id", "string"),
        ("trailer_code", "string"),
        ("trailer_head_capacity", "integer"),
        ("trailer_weight_capacity_lb", "number"),
        ("haul_basis", "string"),
    ], optional=[("loaded_miles", "number"), ("proration_basis", "string")])
    haul_basis = enum_field(data, "haul_basis", config.HAUL_BASES)
    proration_basis = enum_field(data, "proration_basis", config.PRORATION_BASES,
                                 required=False, default="BY_WEIGHT")
    check_min(v["trailer_head_capacity"], 1, "trailer_head_capacity")
    check_min(v["trailer_weight_capacity_lb"], 0, "trailer_weight_capacity_lb",
              inclusive=False)
    loaded_miles = v["loaded_miles"] if v["loaded_miles"] is not None else 0
    check_min(loaded_miles, 0, "loaded_miles")

    sale_day = reference("sale_days", v["sale_day_id"], "SaleDay")
    party = reference("parties", v["carrier_party_id"], "Party")
    ownership(role, user_id, party["id"])
    run_gates("load_manifests.create", sale_day=sale_day, party=party)

    row = insert_versioned("load_manifests", {
        "sale_day_id": sale_day["id"],
        "carrier_party_id": party["id"],
        "trailer_code": v["trailer_code"],
        "trailer_head_capacity": v["trailer_head_capacity"],
        "trailer_weight_capacity_lb": D(v["trailer_weight_capacity_lb"]),
        "haul_basis": haul_basis,
        "loaded_miles": D(loaded_miles),
        "proration_basis": proration_basis,
        "loaded_head": 0,
        "loaded_weight_lb": D(0),
        "haul_charge": q2(0),
        "status": "PLANNED",
        "dispatched_at": None,
    })
    return ok(serialize.load_manifest(row), 201)


@bp.get("/sale-barn/load-manifests/<manifest_id>")
def read_manifest(manifest_id):
    actor(ALL)
    return ok(serialize.load_manifest(
        path_row("load_manifests", manifest_id, "LoadManifest")))


@bp.get("/sale-barn/load-manifests")
def list_manifests():
    actor(ALL)
    rows = list(db["load_manifests"].values())
    for key in ("sale_day_id", "carrier_party_id", "status"):
        value = filter_arg(key)
        if value is not None:
            rows = [r for r in rows if r.get(key) == value]
    return paginate(rows, serialize.load_manifest)


def _manifest_context(manifest):
    return (get("sale_days", manifest["sale_day_id"]),
            get("parties", manifest["carrier_party_id"]))


@bp.post("/sale-barn/load-manifests/<manifest_id>/lines")
def add_line(manifest_id):
    actor(["Carrier"])
    manifest = path_row("load_manifests", manifest_id, "LoadManifest")
    data = body()
    v = fields(data, required=[("lot_id", "string"),
                               ("expected_load_manifest_version", "integer")])
    lot = reference("lots", v["lot_id"], "Lot")

    # Rung 8 - a load line's lot and its manifest share a sale day.
    if lot["sale_day_id"] != manifest["sale_day_id"]:
        fail("ERR_SALE_DAY_MISMATCH")
    # Rung 10 - OCC on the manifest, before all five gates.
    if v["expected_load_manifest_version"] != manifest["version"]:
        fail("ERR_STALE_VERSION")

    sale_day, party = _manifest_context(manifest)
    run_gates("load_manifests.lines", sale_day=sale_day, lot=lot, party=party)

    if manifest["status"] not in ("PLANNED", "LOADING"):
        fail("ERR_INVALID_STATE")

    # Rungs 39 and 40 - genuinely independent, head checked first.
    if manifest["loaded_head"] + lot["head_count"] > manifest["trailer_head_capacity"]:
        fail("ERR_TRAILER_HEAD_CAPACITY_EXCEEDED")
    lot_weight = D(lot["settle_weight_lb"]) if lot.get("settle_weight_lb") is not None else D(0)
    if D(manifest["loaded_weight_lb"]) + lot_weight > D(manifest["trailer_weight_capacity_lb"]):
        fail("ERR_TRAILER_WEIGHT_CAPACITY_EXCEEDED")

    line = insert("load_lines", {
        "load_manifest_id": manifest["id"],
        "lot_id": lot["id"],
        "head": lot["head_count"],
        "weight_lb": lot.get("settle_weight_lb"),
        "prorated_haul_amount": q2(0),
    })
    if manifest["status"] == "PLANNED":
        manifest["status"] = "LOADING"
    recompute_manifest(manifest)
    return ok(serialize.load_line(line), 201)


@bp.delete("/sale-barn/load-manifests/<manifest_id>/lines/<line_id>")
def remove_line(manifest_id, line_id):
    role, user_id = actor(["Carrier"])
    manifest = path_row("load_manifests", manifest_id, "LoadManifest")
    line = path_row("load_lines", line_id, "LoadLine")
    if line["load_manifest_id"] != manifest["id"]:
        fail("ERR_RESOURCE_NOT_FOUND", "LoadLine '%s' does not exist." % line_id)
    lot = get("lots", line["lot_id"])
    sale_day, party = _manifest_context(manifest)
    ownership(role, user_id, manifest["carrier_party_id"])
    run_gates("load_manifests.remove_line", sale_day=sale_day, lot=lot, party=party)
    if manifest["status"] not in ("LOADING", "DISPATCHED"):
        fail("ERR_INVALID_STATE")

    del db["load_lines"][line["id"]]
    if lot is not None and lot["custody_status"] == "LOADED":
        lot["custody_status"] = "BUYER_PEN"
        touch(lot)
        recompute_pens(lot.get("pen_id"))
    if not manifest_lines(manifest["id"]) and manifest["status"] == "LOADING":
        manifest["status"] = "PLANNED"
    recompute_manifest(manifest)
    return "", 204


@bp.post("/sale-barn/load-manifests/<manifest_id>/dispatch")
def dispatch(manifest_id):
    role, user_id = actor(["Carrier"])
    manifest = path_row("load_manifests", manifest_id, "LoadManifest")
    sale_day, party = _manifest_context(manifest)
    ownership(role, user_id, manifest["carrier_party_id"])
    run_gates("load_manifests.dispatch", sale_day=sale_day, party=party)
    lines = manifest_lines(manifest["id"])
    if manifest["status"] != "LOADING" or not lines:
        fail("ERR_INVALID_STATE")
    manifest["status"] = "DISPATCHED"
    manifest["dispatched_at"] = render_instant(clock.now())
    touch(manifest)
    add_charge_line("HAUL", manifest["sale_day_id"], manifest["haul_charge"],
                    head=manifest["loaded_head"],
                    unit_rate=(config.HAUL_RATE_PER_LOADED_MILE
                               if manifest["haul_basis"] == "PER_MILE"
                               else config.HAUL_RATE_PER_HEAD))
    pen_ids = []
    for line in lines:
        lot = get("lots", line["lot_id"])
        if lot is None:
            continue
        if lot["custody_status"] == "BUYER_PEN":
            lot["custody_status"] = "LOADED"
            touch(lot)
            pen_ids.append(lot.get("pen_id"))
    recompute_pens(*pen_ids)
    return ok(serialize.load_manifest(manifest))


@bp.post("/sale-barn/load-manifests/<manifest_id>/deliver")
def deliver(manifest_id):
    role, user_id = actor(["Carrier"])
    manifest = path_row("load_manifests", manifest_id, "LoadManifest")
    sale_day, party = _manifest_context(manifest)
    ownership(role, user_id, manifest["carrier_party_id"])
    run_gates("load_manifests.deliver", sale_day=sale_day, party=party)
    if manifest["status"] != "DISPATCHED":
        fail("ERR_INVALID_STATE")
    manifest["status"] = "DELIVERED"
    touch(manifest)
    return ok(serialize.load_manifest(manifest))


@bp.post("/sale-barn/load-manifests/<manifest_id>/close")
def close_manifest(manifest_id):
    role, user_id = actor(["Carrier"])
    manifest = path_row("load_manifests", manifest_id, "LoadManifest")
    sale_day, party = _manifest_context(manifest)
    ownership(role, user_id, manifest["carrier_party_id"])
    run_gates("load_manifests.close", sale_day=sale_day, party=party)
    if manifest["status"] != "DELIVERED":
        fail("ERR_INVALID_STATE")
    for line in manifest_lines(manifest["id"]):
        lot = get("lots", line["lot_id"])
        if lot is None or lot["custody_status"] != "RELEASED":
            fail("ERR_INVALID_STATE")
    manifest["status"] = "CLOSED"
    touch(manifest)
    return ok(serialize.load_manifest(manifest))


# ------------------------------------------------------------- load lines --
@bp.get("/sale-barn/load-lines/<line_id>")
def read_line(line_id):
    actor(ALL)
    return ok(serialize.load_line(path_row("load_lines", line_id, "LoadLine")))


@bp.get("/sale-barn/load-lines")
def list_lines():
    actor(ALL)
    rows = list(db["load_lines"].values())
    for key in ("load_manifest_id", "lot_id"):
        value = filter_arg(key)
        if value is not None:
            rows = [r for r in rows if r.get(key) == value]
    return paginate(rows, serialize.load_line)
