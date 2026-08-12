"""Shipping labels, shipments and the loss / recovery cascades (PRD 3.5)."""

import random
import string

from flask import Blueprint

import auth
import boxops
import calc
import constants as K
import derive
import envelope
import ledger
import listing
import lookup
import serialize
import shape
import store
import timeutil
from errors import ApiError

bp = Blueprint("shipping", __name__)

_ALNUM = string.ascii_uppercase + string.digits


def _tracking_code():
    return "TRK" + "".join(random.choice(_ALNUM) for _ in range(12))


def _items_on_shipment(shipment_id):
    return [i for i in store.all_rows("box_items")
            if i["return_shipment_id"] == shipment_id]


def _submission_for_shipment(shipment_id):
    for submission in store.all_rows("submissions"):
        if submission["inbound_shipment_id"] == shipment_id:
            return submission
    return None


def _box_for_outbound(shipment_id):
    for box in store.all_rows("boxes"):
        if box["outbound_shipment_id"] == shipment_id:
            return box
    return None


# ---------- shipping labels ---------------------------------------------

@bp.post("/kidswear/shipping-labels")
def mint_label():
    auth.gate("LogisticsCoordinator")
    body = shape.body_json()
    member_id = shape.id_string(body, "member_id")
    direction = shape.enum_in(body, "direction", K.SHIPMENT_DIRECTIONS)
    member = lookup.member(member_id)
    lookup.standing(member)
    issued_at = timeutil.now()
    row = store.insert("labels", {
        "member_id": member_id,
        "replaces_label_id": None,
        "direction": direction,
        "status": "ISSUED",
        "issued_at": issued_at,
        "expires_at": timeutil.add_days(issued_at, K.LABEL_VALID_DAYS),
        "reissue_count": 0,
        "tracking_code": _tracking_code(),
    })
    return envelope.created(serialize.label(row))


@bp.get("/kidswear/shipping-labels")
def list_labels():
    caller = auth.gate("LogisticsCoordinator", "WarehouseOperator", "PlatformAdmin", "Member")
    rows = store.all_rows("labels")
    rows = listing.scope_to_member(caller, rows, lambda r: r["member_id"])
    rows = listing.eq(rows, "member_id", shape.query_str("member_id"))
    rows = listing.eq(rows, "replaces_label_id", shape.query_str("replaces_label_id"))
    rows = listing.eq(rows, "direction", shape.query_member("direction", K.SHIPMENT_DIRECTIONS))
    rows = listing.eq(rows, "status", shape.query_member("status", K.LABEL_STATUSES))
    return envelope.listing(rows, serialize.label)


@bp.get("/kidswear/shipping-labels/<label_id>")
def read_label(label_id):
    caller = auth.gate("LogisticsCoordinator", "WarehouseOperator", "PlatformAdmin", "Member")
    row = lookup.label(label_id)
    auth.own(caller, row["member_id"])
    return envelope.ok(serialize.label(row))


@bp.post("/kidswear/shipping-labels/<label_id>/void")
def void_label(label_id):
    auth.gate("LogisticsCoordinator")
    label = lookup.label(label_id)
    if label["status"] != "ISSUED":
        raise ApiError("ERR_LABEL_INVALID_STATE")
    for shipment in store.all_rows("shipments"):
        if shipment["label_id"] == label_id and shipment["status"] in ("IN_TRANSIT", "DELIVERED"):
            raise ApiError("ERR_LABEL_INVALID_STATE",
                           "A shipment under this label has already moved.")
    label["status"] = "VOIDED"
    store.touch(label)
    return envelope.ok(serialize.label(label))


@bp.post("/kidswear/shipping-labels/<label_id>/expire")
def expire_label(label_id):
    auth.gate("LogisticsCoordinator")
    label = lookup.label(label_id)
    if label["status"] != "ISSUED":
        raise ApiError("ERR_LABEL_INVALID_STATE")
    if timeutil.now() <= label["expires_at"]:
        raise ApiError("ERR_LABEL_NOT_EXPIRED")
    label["status"] = "EXPIRED"
    store.touch(label)
    return envelope.ok(serialize.label(label))


@bp.post("/kidswear/shipping-labels/<label_id>/reissue")
def reissue_label(label_id):
    auth.gate("LogisticsCoordinator")
    label = lookup.label(label_id)
    if label["status"] not in ("VOIDED", "EXPIRED"):
        raise ApiError("ERR_LABEL_INVALID_STATE")
    if label["reissue_count"] >= K.LABEL_REISSUE_CAP:
        raise ApiError("ERR_LABEL_REISSUE_CAP_REACHED")
    issued_at = timeutil.now()
    successor = store.insert("labels", {
        "member_id": label["member_id"],
        "replaces_label_id": label["id"],
        "direction": label["direction"],
        "status": "ISSUED",
        "issued_at": issued_at,
        "expires_at": timeutil.add_days(issued_at, K.LABEL_VALID_DAYS),
        "reissue_count": label["reissue_count"] + 1,
        "tracking_code": _tracking_code(),
    })
    store.touch(label)
    return envelope.created(serialize.label(successor))


# ---------- shipments ----------------------------------------------------

@bp.post("/kidswear/shipments")
def create_shipment():
    auth.gate("LogisticsCoordinator")
    body = shape.body_json()
    member_id = shape.id_string(body, "member_id")
    label_id = shape.id_string(body, "label_id")
    direction = shape.enum_in(body, "direction", K.SHIPMENT_DIRECTIONS)
    item_count = shape.integer(body, "item_count", required=False, default=0, minimum=0)
    member = lookup.member(member_id)
    lookup.label(label_id)
    lookup.standing(member)
    row = store.insert("shipments", {
        "member_id": member_id,
        "label_id": label_id,
        "direction": direction,
        "status": "CREATED",
        "item_count": item_count,
        "shipped_at": None,
        "delivered_at": None,
        "ever_scanned": False,
    })
    return envelope.created(serialize.shipment(row))


@bp.get("/kidswear/shipments")
def list_shipments():
    caller = auth.gate("LogisticsCoordinator", "WarehouseOperator", "PlatformAdmin",
                       "Member", "BillingAgent")
    rows = store.all_rows("shipments")
    rows = listing.scope_to_member(caller, rows, lambda r: r["member_id"])
    rows = listing.eq(rows, "member_id", shape.query_str("member_id"))
    rows = listing.eq(rows, "label_id", shape.query_str("label_id"))
    rows = listing.eq(rows, "direction", shape.query_member("direction", K.SHIPMENT_DIRECTIONS))
    rows = listing.eq(rows, "status", shape.query_member("status", K.SHIPMENT_STATUSES))
    return envelope.listing(rows, serialize.shipment)


@bp.get("/kidswear/shipments/<shipment_id>")
def read_shipment(shipment_id):
    caller = auth.gate("LogisticsCoordinator", "WarehouseOperator", "PlatformAdmin",
                       "Member", "BillingAgent")
    row = lookup.shipment(shipment_id)
    auth.own(caller, row["member_id"])
    return envelope.ok(serialize.shipment(row))


@bp.post("/kidswear/shipments/<shipment_id>/depart")
def depart(shipment_id):
    auth.gate("LogisticsCoordinator")
    shipment = lookup.shipment(shipment_id)
    label = lookup.label(shipment["label_id"])
    if shipment["status"] != "CREATED":
        raise ApiError("ERR_SHIPMENT_INVALID_STATE")
    if label["status"] != "ISSUED":
        raise ApiError("ERR_LABEL_INVALID_STATE")
    clock = timeutil.now()
    if clock > label["expires_at"]:
        raise ApiError("ERR_LABEL_EXPIRED")
    shipment["status"] = "IN_TRANSIT"
    shipment["shipped_at"] = clock
    shipment["ever_scanned"] = True
    store.touch(shipment)
    label["status"] = "IN_TRANSIT"
    store.touch(label)
    if shipment["direction"] == "TRADE_IN_INBOUND":
        submission = _submission_for_shipment(shipment_id)
        if submission is not None and submission["status"] == "LABEL_ISSUED":
            submission["status"] = "IN_TRANSIT"
            store.touch(submission)
    return envelope.ok(serialize.shipment(shipment))


@bp.post("/kidswear/shipments/<shipment_id>/receive")
def receive(shipment_id):
    auth.gate("WarehouseOperator")
    shipment = lookup.shipment(shipment_id)
    if shipment["status"] == "IN_TRANSIT":
        return _receive_in_transit(shipment)
    if shipment["status"] == "LOST":
        return _recover_lost(shipment)
    raise ApiError("ERR_SHIPMENT_INVALID_STATE")


def _receive_in_transit(shipment):
    clock = timeutil.now()
    shipment["status"] = "DELIVERED"
    shipment["delivered_at"] = clock
    store.touch(shipment)
    label = store.get("labels", shipment["label_id"])
    if label is not None and label["status"] == "IN_TRANSIT":
        label["status"] = "DELIVERED"
        store.touch(label)

    direction = shipment["direction"]
    if direction == "OUTBOUND":
        box = _box_for_outbound(shipment["id"])
        if box is not None:
            for item in derive.box_items(box["id"]):
                if item["fulfillment_status"] == "SHIPPED":
                    item["fulfillment_status"] = "WITH_MEMBER"
                    if item["is_capsule_item"]:
                        unit = store.get("units", item["unit_id"])
                        capsule = store.get("capsules", unit["capsule_id"]) if unit else None
                        if capsule is not None:
                            item["embargo_until"] = capsule["embargo_until"]
                    store.touch(item)
            if box["status"] == "SHIPPED":
                box["status"] = "DELIVERED"
                store.touch(box)
    elif direction == "RETURN":
        boxes_touched = set()
        for item in _items_on_shipment(shipment["id"]):
            if item["fulfillment_status"] != "RETURNING":
                continue
            item["fulfillment_status"] = "RECEIVED"
            store.touch(item)
            boxes_touched.add(item["box_id"])
            unit = store.get("units", item["unit_id"])
            if unit is not None and unit["state"] == "INBOUND":
                unit["state"] = "PROCESSING"
                unit["cycles_completed"] += 1
                store.touch(unit)
                store.insert("assessments", {
                    "unit_id": unit["id"],
                    "trade_in_item_id": None,
                    "pipeline": "RENTAL",
                    "status": "DRAFT",
                    "grade": None,
                    "defect_codes": [],
                    "regrade_count": 0,
                    "graded_by_user_id": None,
                    "confirmed_by_user_id": None,
                    "dispute_reason": None,
                })
        for box_id in boxes_touched:
            box = store.get("boxes", box_id)
            if box is not None:
                boxops.maybe_close_box(box)
    elif direction == "TRADE_IN_INBOUND":
        submission = _submission_for_shipment(shipment["id"])
        if submission is not None and submission["status"] == "IN_TRANSIT":
            submission["status"] = "RECEIVED"
            store.touch(submission)
    return envelope.ok(serialize.shipment(shipment))


def _recover_lost(shipment):
    for claim in store.all_rows("claims"):
        if claim["shipment_id"] == shipment["id"] and claim["status"] == "SETTLED":
            raise ApiError("ERR_SHIPMENT_INVALID_STATE",
                           "A settled claim already wrote this shipment off.")
    shipment["status"] = "DELIVERED"
    shipment["delivered_at"] = timeutil.now()
    store.touch(shipment)
    boxes_touched = set()
    for item in _items_on_shipment(shipment["id"]):
        if item["fulfillment_status"] != "LOST":
            continue
        item["fulfillment_status"] = "RECEIVED"
        item["settlement_status"] = "OPEN"
        store.touch(item)
        boxes_touched.add(item["box_id"])
        unit = store.get("units", item["unit_id"])
        if unit is not None and unit["state"] == "LOST_IN_TRANSIT":
            unit["state"] = "PROCESSING"
            store.touch(unit)
    for box_id in boxes_touched:
        box = store.get("boxes", box_id)
        if box is not None:
            boxops.maybe_close_box(box)
    for claim in store.all_rows("claims"):
        if claim["shipment_id"] == shipment["id"] and claim["status"] in ("OPENED", "INVESTIGATING"):
            claim["status"] = "DENIED"
            claim["denial_reason"] = "SHIPMENT_RECOVERED"
            store.touch(claim)
    return envelope.ok(serialize.shipment(shipment))


@bp.post("/kidswear/shipments/<shipment_id>/mark-lost")
def mark_lost(shipment_id):
    auth.gate("LogisticsCoordinator")
    shipment = lookup.shipment(shipment_id)
    if shipment["status"] not in ("CREATED", "IN_TRANSIT"):
        raise ApiError("ERR_SHIPMENT_INVALID_STATE")
    member = lookup.member(shipment["member_id"])
    label = store.get("labels", shipment["label_id"])
    shipment["status"] = "LOST"
    store.touch(shipment)
    if label is not None and label["status"] in ("ISSUED", "IN_TRANSIT"):
        label["status"] = "LOST"
        store.touch(label)
    lost_units = []
    for item in _items_on_shipment(shipment_id):
        if item["fulfillment_status"] != "RETURNING":
            continue
        item["fulfillment_status"] = "LOST"
        item["settlement_status"] = "LOST_CHARGED"
        store.touch(item)
        unit = store.get("units", item["unit_id"])
        if unit is not None and unit["state"] == "INBOUND":
            unit["state"] = "LOST_IN_TRANSIT"
            store.touch(unit)
            lost_units.append(unit)
    pairs = []
    for unit in sorted(lost_units, key=store.order_key):
        style = store.get("styles", unit["style_id"])
        if style is not None:
            pairs.append((unit, style))
    assessed = calc.lost_assessed_value(pairs)
    if assessed > 0:
        ledger.new_charge(member, "LOST_LIABILITY", assessed, None)
    return envelope.ok(serialize.shipment(shipment))


@bp.post("/kidswear/shipments/<shipment_id>/return-to-sender")
def return_to_sender(shipment_id):
    auth.gate("LogisticsCoordinator")
    shipment = lookup.shipment(shipment_id)
    if shipment["direction"] != "REJECT_RETURN":
        raise ApiError("ERR_SHIPMENT_DIRECTION_MISMATCH")
    if shipment["status"] != "IN_TRANSIT":
        raise ApiError("ERR_SHIPMENT_INVALID_STATE")
    shipment["status"] = "RETURNED_TO_SENDER"
    store.touch(shipment)
    label = store.get("labels", shipment["label_id"])
    if label is not None and label["status"] == "IN_TRANSIT":
        label["status"] = "DELIVERED"
        store.touch(label)
    return envelope.ok(serialize.shipment(shipment))
