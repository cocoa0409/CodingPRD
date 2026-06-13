"""Production side: green lots, roast batches, roasted lots."""
from flask import Blueprint, request

import errors
from db import store
from middleware import get_identity, require_role
from helpers import (
    get_body, require_fields, as_str, as_int, require_positive_number,
    parse_pagination, paginate, sort_by_created, new_record, touch,
    round_kg, clamp_kg, round_cents, D,
)
from response import object_response, array_response
from services import lookups, serializers
from services.inventory import recompute_green_lot, recompute_roasted_lot
from decimal import Decimal, ROUND_HALF_UP

bp = Blueprint("production", __name__)

MAX_REROASTS = 2


# ==========================================================================
# Green lots
# ==========================================================================
@bp.post("/green-lots")
def create_green_lot():
    _, role = get_identity()
    require_role(role, {"RoasterStaff"})
    body = get_body()
    require_fields(body, ["origin", "lot_ref", "received_kg", "par_level_kg"])
    origin = as_str(body["origin"], "origin")
    lot_ref = as_str(body["lot_ref"], "lot_ref")
    received_kg = require_positive_number(body["received_kg"], "received_kg")
    par_level_kg = body["par_level_kg"]
    if isinstance(par_level_kg, bool) or not isinstance(par_level_kg, (int, float)) or par_level_kg < 0:
        raise errors.invalid_request("par_level_kg must be a non-negative number")

    # uniqueness among non-depleted (priority 5). A lot is depleted when its
    # on_hand_kg has been fully consumed (== 0) with no live reservation.
    for g in store.green_lots.values():
        if g["lot_ref"] == lot_ref and not _is_depleted(g):
            raise errors.duplicate("lot_ref already in use for a non-depleted lot")

    rec = new_record()
    rec.update({
        "origin": origin,
        "lot_ref": lot_ref,
        "received_kg": round_kg(received_kg),
        "par_level_kg": round_kg(par_level_kg),
    })
    recompute_green_lot(rec)  # sets on_hand/reserved/available/reorder_status
    store.green_lots[rec["id"]] = rec
    return object_response(serializers.green_lot_public(rec), 201)


def _is_depleted(lot):
    recompute_green_lot(lot)
    return lot["on_hand_kg"] == 0 and lot["reserved_kg"] == 0


@bp.get("/green-lots")
def list_green_lots():
    _, role = get_identity()
    require_role(role, {"RoasterStaff", "SalesRep"})
    limit, offset = parse_pagination()
    reorder_status = request.args.get("reorder_status")
    items = list(store.green_lots.values())
    for g in items:
        recompute_green_lot(g)
    if reorder_status is not None:
        items = [g for g in items if g["reorder_status"] == reorder_status]
    items = sort_by_created(items)
    page, total = paginate(items, limit, offset)
    return array_response([serializers.green_lot_public(g) for g in page], limit, offset, total)


@bp.get("/green-lots/<gid>")
def get_green_lot(gid):
    _, role = get_identity()
    require_role(role, {"RoasterStaff", "SalesRep"})
    rec = lookups.get_green_lot(gid)
    recompute_green_lot(rec)
    return object_response(serializers.green_lot_public(rec))


@bp.get("/green-lots/<gid>/roast-batches")
def list_green_lot_batches(gid):
    _, role = get_identity()
    require_role(role, {"RoasterStaff", "SalesRep"})
    lookups.get_green_lot(gid)
    limit, offset = parse_pagination()
    status = request.args.get("status")
    items = [b for b in store.roast_batches.values() if b["green_lot_id"] == gid]
    if status is not None:
        items = [b for b in items if b["status"] == status]
    items = sort_by_created(items)
    page, total = paginate(items, limit, offset)
    return array_response([serializers.roast_batch_public(b) for b in page], limit, offset, total)


# ==========================================================================
# Roast batches
# ==========================================================================
@bp.post("/roast-batches")
def create_batch():
    _, role = get_identity()
    require_role(role, {"RoasterStaff"})
    body = get_body()
    require_fields(body, ["green_lot_id", "product_id", "planned_green_kg", "expected_green_lot_version"])
    planned_green_kg = require_positive_number(body["planned_green_kg"], "planned_green_kg")
    expected_version = as_int(body["expected_green_lot_version"], "expected_green_lot_version")
    # FK existence (priority 3), left to right
    green_lot = lookups.get_green_lot(as_str(body["green_lot_id"], "green_lot_id"))
    product = lookups.get_product(as_str(body["product_id"], "product_id"))
    profile = lookups.get_profile(product["roast_profile_id"])

    # OCC (priority 15) on green lot version
    if expected_version != green_lot["version"]:
        raise errors.stale_version("green lot version mismatch")

    # planned_roasted_kg = planned_green_kg * (1 - expected_shrink_bps/10000), 3dp HALF_UP
    planned_roasted = round_kg(
        D(planned_green_kg) * (D(1) - D(profile["expected_shrink_bps"]) / D(10000))
    )

    rec = new_record()
    rec.update({
        "green_lot_id": green_lot["id"],
        "product_id": product["id"],
        "roast_profile_id": product["roast_profile_id"],  # pinned at creation
        "planned_green_kg": round_kg(planned_green_kg),
        "planned_roasted_kg": planned_roasted,
        "actual_green_kg": None,
        "actual_roasted_kg": None,
        "actual_shrink_bps": None,
        "roast_date": None,
        "status": "PLANNED",
    })
    store.roast_batches[rec["id"]] = rec
    # reserves planned_green_kg on the green lot; bump green lot version
    recompute_green_lot(green_lot, bump=True)
    return object_response(serializers.roast_batch_public(rec), 201)


@bp.get("/roast-batches")
def list_batches():
    _, role = get_identity()
    require_role(role, {"RoasterStaff", "SalesRep"})
    limit, offset = parse_pagination()
    product_id = request.args.get("product_id")
    roast_profile_id = request.args.get("roast_profile_id")
    status = request.args.get("status")
    items = list(store.roast_batches.values())
    if product_id is not None:
        items = [b for b in items if b["product_id"] == product_id]
    if roast_profile_id is not None:
        items = [b for b in items if b["roast_profile_id"] == roast_profile_id]
    if status is not None:
        items = [b for b in items if b["status"] == status]
    items = sort_by_created(items)
    page, total = paginate(items, limit, offset)
    return array_response([serializers.roast_batch_public(b) for b in page], limit, offset, total)


@bp.get("/roast-batches/<bid>")
def get_batch(bid):
    _, role = get_identity()
    require_role(role, {"RoasterStaff", "SalesRep"})
    rec = lookups.get_batch(bid)
    return object_response(serializers.roast_batch_public(rec))


@bp.post("/roast-batches/<bid>/start")
def start_batch(bid):
    _, role = get_identity()
    require_role(role, {"RoasterStaff"})
    rec = lookups.get_batch(bid)
    body = get_body()
    require_fields(body, ["actual_green_kg"])
    actual_green_kg = require_positive_number(body["actual_green_kg"], "actual_green_kg")
    # state gate (priority 6)
    if rec["status"] != "PLANNED":
        raise errors.invalid_state("batch is not PLANNED")
    # green sufficiency (priority 10): actual_green_kg <= GreenLot.on_hand_kg
    green_lot = store.green_lots[rec["green_lot_id"]]
    recompute_green_lot(green_lot)
    if D(actual_green_kg) > D(green_lot["on_hand_kg"]):
        raise errors.insufficient_green("actual_green_kg exceeds on-hand green")

    rec["actual_green_kg"] = round_kg(actual_green_kg)
    rec["status"] = "ROASTING"
    touch(rec)
    # reservation -> consumption; recompute + bump green lot
    recompute_green_lot(green_lot, bump=True)
    return object_response(serializers.roast_batch_public(rec), 200)


@bp.post("/roast-batches/<bid>/drop")
def drop_batch(bid):
    _, role = get_identity()
    require_role(role, {"RoasterStaff"})
    rec = lookups.get_batch(bid)
    if rec["status"] != "ROASTING":
        raise errors.invalid_state("batch is not ROASTING")
    rec["status"] = "COOLING"
    touch(rec)
    return object_response(serializers.roast_batch_public(rec), 200)


@bp.post("/roast-batches/<bid>/reroast")
def reroast_batch(bid):
    _, role = get_identity()
    require_role(role, {"RoasterStaff"})
    rec = lookups.get_batch(bid)
    if rec["status"] != "COOLING" or rec.get("_reroast_count", 0) >= MAX_REROASTS:
        raise errors.invalid_state("batch cannot be re-roasted")
    rec["_reroast_count"] = rec.get("_reroast_count", 0) + 1
    rec["status"] = "ROASTING"
    touch(rec)
    return object_response(serializers.roast_batch_public(rec), 200)


@bp.post("/roast-batches/<bid>/complete")
def complete_batch(bid):
    _, role = get_identity()
    require_role(role, {"RoasterStaff"})
    rec = lookups.get_batch(bid)
    body = get_body()
    require_fields(body, ["actual_roasted_kg"])
    actual_roasted_kg = require_positive_number(body["actual_roasted_kg"], "actual_roasted_kg")
    if rec["status"] != "COOLING":
        raise errors.invalid_state("batch is not COOLING")
    # weight conservation (priority 12)
    if D(actual_roasted_kg) > D(rec["actual_green_kg"]):
        raise errors.weight_gain("actual_roasted_kg exceeds actual_green_kg")

    rec["actual_roasted_kg"] = round_kg(actual_roasted_kg)
    # actual_shrink_bps = round_half_up((1 - actual_roasted/actual_green) * 10000)
    shrink = (D(1) - D(rec["actual_roasted_kg"]) / D(rec["actual_green_kg"])) * D(10000)
    rec["actual_shrink_bps"] = int(shrink.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    roast_date = store.clock()
    rec["roast_date"] = roast_date
    rec["status"] = "COMPLETED"
    touch(rec)

    # cascade-create roasted lot
    lot = new_record()
    lot.update({
        "roast_batch_id": rec["id"],
        "product_id": rec["product_id"],
        "roast_date": roast_date,
        "produced_kg": rec["actual_roasted_kg"],
    })
    recompute_roasted_lot(lot)
    store.roasted_lots[lot["id"]] = lot

    # consumption already reflected via status COMPLETED; recompute green lot
    green_lot = store.green_lots[rec["green_lot_id"]]
    recompute_green_lot(green_lot, bump=True)
    return object_response(serializers.roast_batch_public(rec), 200)


@bp.post("/roast-batches/<bid>/cancel")
def cancel_batch(bid):
    _, role = get_identity()
    require_role(role, {"RoasterStaff"})
    rec = lookups.get_batch(bid)
    if rec["status"] != "PLANNED":
        raise errors.invalid_state("only a PLANNED batch can be cancelled")
    rec["status"] = "CANCELLED"
    touch(rec)
    # release reservation; recompute + bump green lot
    green_lot = store.green_lots[rec["green_lot_id"]]
    recompute_green_lot(green_lot, bump=True)
    return object_response(serializers.roast_batch_public(rec), 200)


@bp.get("/roast-batches/<bid>/roasted-lots")
def list_batch_roasted_lots(bid):
    _, role = get_identity()
    require_role(role, {"RoasterStaff", "SalesRep"})
    lookups.get_batch(bid)
    limit, offset = parse_pagination()
    items = [l for l in store.roasted_lots.values() if l["roast_batch_id"] == bid]
    for l in items:
        recompute_roasted_lot(l)
    items = sort_by_created(items)
    page, total = paginate(items, limit, offset)
    return array_response([serializers.roasted_lot_public(l) for l in page], limit, offset, total)


# ==========================================================================
# Roasted lots (read only)
# ==========================================================================
@bp.get("/roasted-lots")
def list_roasted_lots():
    _, role = get_identity()
    require_role(role, {"RoasterStaff", "SalesRep"})
    limit, offset = parse_pagination()
    product_id = request.args.get("product_id")
    items = list(store.roasted_lots.values())
    for l in items:
        recompute_roasted_lot(l)
    if product_id is not None:
        items = [l for l in items if l["product_id"] == product_id]
    items = sort_by_created(items)
    page, total = paginate(items, limit, offset)
    return array_response([serializers.roasted_lot_public(l) for l in page], limit, offset, total)


@bp.get("/roasted-lots/<lid>")
def get_roasted_lot(lid):
    _, role = get_identity()
    require_role(role, {"RoasterStaff", "SalesRep"})
    rec = lookups.get_roasted_lot(lid)
    recompute_roasted_lot(rec)
    return object_response(serializers.roasted_lot_public(rec))
