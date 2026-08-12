"""Boxes, allocation, packing, shipping, returns and buy-out quoting (PRD 3.3 / 3.7)."""

from flask import Blueprint

import auth
import boxops
import calc
import constants as K
import derive
import envelope
import listing
import lookup
import selector
import serialize
import shape
import store
import timeutil
from errors import ApiError

bp = Blueprint("boxes", __name__)


@bp.post("/kidswear/boxes")
def create_box():
    auth.gate("WarehouseOperator", "PlatformAdmin")
    body = shape.body_json()
    cycle_id = shape.id_string(body, "cycle_id")
    cycle = lookup.cycle(cycle_id)
    member = lookup.member(cycle["member_id"])
    lookup.standing(member, block_pending=True)
    plan = lookup.plan(member["plan_id"])
    row = store.insert("boxes", {
        "cycle_id": cycle_id,
        "member_id": member["id"],
        "outbound_shipment_id": None,
        "status": "DRAFT",
        "slot_capacity": plan["slots_per_box"],
    })
    return envelope.created(serialize.box(row))


@bp.get("/kidswear/boxes")
def list_boxes():
    caller = auth.gate("WarehouseOperator", "PlatformAdmin", "Member",
                       "LogisticsCoordinator", "BillingAgent")
    rows = store.all_rows("boxes")
    rows = listing.scope_to_member(caller, rows, lambda r: r["member_id"])
    rows = listing.eq(rows, "cycle_id", shape.query_str("cycle_id"))
    rows = listing.eq(rows, "member_id", shape.query_str("member_id"))
    rows = listing.eq(rows, "outbound_shipment_id", shape.query_str("outbound_shipment_id"))
    rows = listing.eq(rows, "status", shape.query_member("status", K.BOX_STATUSES))
    return envelope.listing(rows, serialize.box)


@bp.get("/kidswear/boxes/<box_id>")
def read_box(box_id):
    caller = auth.gate("WarehouseOperator", "PlatformAdmin", "Member",
                       "LogisticsCoordinator", "BillingAgent")
    row = lookup.box(box_id)
    auth.own(caller, row["member_id"])
    return envelope.ok(serialize.box(row))


@bp.post("/kidswear/boxes/<box_id>/allocate")
def allocate(box_id):
    auth.gate("WarehouseOperator")
    body = shape.body_json()
    unit_id = shape.id_string(body, "unit_id", required=False)
    style_id = shape.id_string(body, "style_id", required=False)
    if unit_id is None and style_id is None:
        raise ApiError("ERR_VALIDATION", "Either unit_id or style_id is required.")

    box = lookup.box(box_id)
    unit = lookup.unit(unit_id) if unit_id is not None else None
    style = lookup.style(style_id) if (unit_id is None and style_id is not None) else None
    cycle = lookup.cycle(box["cycle_id"])
    member = lookup.member(box["member_id"])
    lookup.standing(member, block_pending=True, block_delinquent=True)
    lookup.pause_gate_r(member)

    # G7
    if cycle["status"] != "OPEN":
        raise ApiError("ERR_CYCLE_NOT_OPEN")
    if box["status"] != "DRAFT":
        raise ApiError("ERR_BOX_INVALID_STATE")
    if unit is not None and unit["state"] != "IN_STOCK":
        raise ApiError("ERR_UNIT_INVALID_STATE")
    # G9 rung 44
    if derive.box_occupied(box_id) + derive.box_permanently_consumed(box_id) >= box["slot_capacity"]:
        raise ApiError("ERR_BOX_SLOTS_EXHAUSTED")
    # G10
    if unit is not None:
        unit_style = lookup.style(unit["style_id"])
        if not calc.size_compatible(unit_style["size_code"], member["child_size_code"]):
            raise ApiError("ERR_SIZE_INCOMPATIBLE")
        if unit["current_grade"] == "RETIRE" or unit["retirement_eligible"]:
            raise ApiError("ERR_UNIT_RETIRE_GRADED")
        if unit["capsule_id"] is not None:
            held = selector.member_active_capsule_ids(member["id"])
            if unit["capsule_id"] not in held or not selector.capsule_open(unit["capsule_id"]):
                raise ApiError("ERR_CAPSULE_ALLOCATION_MISSING")
    else:
        unit = selector.box_fill(style, member)

    unit["state"] = "RESERVED"
    store.touch(unit)
    embargo_until = None
    if unit["capsule_id"] is not None:
        capsule = store.get("capsules", unit["capsule_id"])
        if capsule is not None:
            embargo_until = capsule["embargo_until"]
    item = store.insert("box_items", {
        "box_id": box_id,
        "unit_id": unit["id"],
        "return_shipment_id": None,
        "fulfillment_status": "ALLOCATED",
        "settlement_status": "OPEN",
        "slot_index": boxops.next_slot_index(box_id),
        "is_capsule_item": unit["capsule_id"] is not None,
        "embargo_until": embargo_until,
        "days_late": 0,
        "late_fee_cents": 0,
        "damage_fee_cents": 0,
        "assessed_grade": None,
    })
    return envelope.created(serialize.box_item(item))


@bp.post("/kidswear/boxes/<box_id>/pack")
def pack(box_id):
    auth.gate("WarehouseOperator")
    box = lookup.box(box_id)
    cycle = lookup.cycle(box["cycle_id"])
    member = lookup.member(box["member_id"])
    lookup.standing(member, block_pending=True)
    lookup.pause_gate_r(member)
    if cycle["status"] != "OPEN":
        raise ApiError("ERR_CYCLE_NOT_OPEN")
    if box["status"] != "DRAFT":
        raise ApiError("ERR_BOX_INVALID_STATE")
    allocated = len([i for i in derive.box_items(box_id)
                     if i["fulfillment_status"] == "ALLOCATED"])
    if allocated != box["slot_capacity"]:
        raise ApiError("ERR_BOX_NOT_FULL")
    box["status"] = "PACKED"
    store.touch(box)
    return envelope.ok(serialize.box(box))


@bp.post("/kidswear/boxes/<box_id>/ship")
def ship(box_id):
    auth.gate("LogisticsCoordinator")
    body = shape.body_json()
    label_id = shape.id_string(body, "label_id")
    box = lookup.box(box_id)
    label = lookup.label(label_id)
    member = lookup.member(box["member_id"])
    lookup.standing(member, block_pending=True)
    lookup.pause_gate_r(member)
    if box["status"] != "PACKED":
        raise ApiError("ERR_BOX_INVALID_STATE")
    if label["direction"] != "OUTBOUND":
        raise ApiError("ERR_LABEL_DIRECTION_MISMATCH")
    if label["status"] != "ISSUED":
        raise ApiError("ERR_LABEL_INVALID_STATE")
    if timeutil.now() > label["expires_at"]:
        raise ApiError("ERR_LABEL_EXPIRED")

    shipment = store.insert("shipments", {
        "member_id": member["id"],
        "label_id": label_id,
        "direction": "OUTBOUND",
        "status": "CREATED",
        "item_count": 0,
        "shipped_at": None,
        "delivered_at": None,
        "ever_scanned": False,
    })
    box["outbound_shipment_id"] = shipment["id"]
    box["status"] = "SHIPPED"
    store.touch(box)
    for item in derive.box_items(box_id):
        if item["fulfillment_status"] == "ALLOCATED":
            item["fulfillment_status"] = "SHIPPED"
            store.touch(item)
            unit = store.get("units", item["unit_id"])
            if unit is not None and unit["state"] == "RESERVED":
                unit["state"] = "OUT"
                store.touch(unit)
    return envelope.created(serialize.shipment(shipment))


@bp.get("/kidswear/box-items")
def list_box_items():
    caller = auth.gate("WarehouseOperator", "PlatformAdmin", "Member",
                       "LogisticsCoordinator", "BillingAgent", "MerchandisePlanner")
    rows = store.all_rows("box_items")
    rows = listing.scope_to_member(
        caller, rows, lambda r: (boxops.box_of_item(r) or {}).get("member_id"))
    rows = listing.eq(rows, "box_id", shape.query_str("box_id"))
    rows = listing.eq(rows, "unit_id", shape.query_str("unit_id"))
    rows = listing.eq(rows, "return_shipment_id", shape.query_str("return_shipment_id"))
    rows = listing.eq(rows, "fulfillment_status",
                      shape.query_member("fulfillment_status", K.BOX_ITEM_FULFILLMENT))
    rows = listing.eq(rows, "settlement_status",
                      shape.query_member("settlement_status", K.BOX_ITEM_SETTLEMENT))
    return envelope.listing(rows, serialize.box_item)


@bp.get("/kidswear/box-items/<box_item_id>")
def read_box_item(box_item_id):
    caller = auth.gate("WarehouseOperator", "PlatformAdmin", "Member",
                       "LogisticsCoordinator", "BillingAgent", "MerchandisePlanner")
    item = lookup.box_item(box_item_id)
    box = boxops.box_of_item(item)
    auth.own(caller, box["member_id"] if box else None)
    return envelope.ok(serialize.box_item(item))


@bp.post("/kidswear/box-items/<box_item_id>/start-return")
def start_return(box_item_id):
    caller = auth.gate("Member")
    body = shape.body_json()
    return_shipment_id = shape.id_string(body, "return_shipment_id")
    item = lookup.box_item(box_item_id)
    box = boxops.box_of_item(item)
    auth.own(caller, box["member_id"])
    shipment = lookup.shipment(return_shipment_id)
    member = lookup.member(box["member_id"])
    cycle = lookup.cycle(box["cycle_id"])
    lookup.standing(member, block_pending=True)

    if item["fulfillment_status"] not in ("SHIPPED", "WITH_MEMBER"):
        raise ApiError("ERR_BOX_ITEM_INVALID_FULFILLMENT_STATE")
    if item["settlement_status"] != "OPEN":
        raise ApiError("ERR_BOX_ITEM_ALREADY_SETTLED")
    unit = lookup.unit(item["unit_id"])
    if unit["state"] != "OUT":
        raise ApiError("ERR_UNIT_INVALID_STATE")
    label = lookup.label(shipment["label_id"])
    if label["status"] != "ISSUED":
        raise ApiError("ERR_LABEL_INVALID_STATE")
    clock = timeutil.now()
    if clock > label["expires_at"]:
        raise ApiError("ERR_LABEL_EXPIRED")

    item["fulfillment_status"] = "RETURNING"
    item["return_shipment_id"] = return_shipment_id
    item["days_late"] = calc.days_late_for(clock, cycle["grace_ends_at"])
    store.touch(item)
    unit["state"] = "INBOUND"
    store.touch(unit)
    boxops.start_return_on_box(box)
    return envelope.ok(serialize.box_item(item))


@bp.post("/kidswear/box-items/<box_item_id>/buy-out")
def buy_out(box_item_id):
    caller = auth.gate("Member")
    body = shape.body_json()
    quote_variant = shape.enum_in(body, "quote_variant", K.BUYOUT_QUOTE_VARIANTS)
    expected_version = shape.integer(body, "expected_box_item_version")
    item = lookup.box_item(box_item_id)
    box = boxops.box_of_item(item)
    auth.own(caller, box["member_id"])
    member = lookup.member(box["member_id"])
    lookup.standing(member, block_pending=True, block_delinquent=True)
    lookup.pause_gate_r(member)
    # G6 rung 20 -- deliberately before the settlement-state check
    if expected_version != item["version"]:
        raise ApiError("ERR_STALE_BOX_ITEM_VERSION")
    # G7 rung 26
    if item["settlement_status"] != "OPEN":
        raise ApiError("ERR_BOX_ITEM_ALREADY_SETTLED")
    for order in store.all_rows("buyout_orders"):
        if order["box_item_id"] == box_item_id and order["status"] in (
                "QUOTED", "ACCEPTED", "PAID", "COMPLETED"):
            raise ApiError("ERR_BUYOUT_ALREADY_EXISTS")
    clock = timeutil.now()
    # G8 rung 38
    if item["embargo_until"] is not None and clock < item["embargo_until"]:
        raise ApiError("ERR_CAPSULE_EMBARGOED")
    unit = lookup.unit(item["unit_id"])
    style = lookup.style(unit["style_id"])
    # G10 rung 55
    if unit["current_grade"] == "RETIRE" or unit["retirement_eligible"]:
        raise ApiError("ERR_UNIT_RETIRE_GRADED")
    # G11 rung 61
    if style["retail_price_cents"] < K.BUYOUT_MIN_PRICE_CENTS:
        raise ApiError("ERR_BUYOUT_BELOW_FLOOR")

    quoted = calc.buyout_quoted_price(style, unit, quote_variant, clock)
    surcharge = calc.buyout_late_surcharge(quoted, item["days_late"])
    final = calc.buyout_final_price(quoted, surcharge)
    order = store.insert("buyout_orders", {
        "box_item_id": box_item_id,
        "member_id": member["id"],
        "status": "QUOTED",
        "quote_variant": quote_variant,
        "quoted_price_cents": quoted,
        "late_surcharge_cents": surcharge,
        "final_price_cents": final,
        "quoted_at": clock,
        "quote_expires_at": timeutil.add_hours(clock, K.BUYOUT_QUOTE_TTL_HOURS),
    })
    store.touch(item)
    return envelope.created(serialize.buyout_order(order))
