"""Spot orders, credit counters and makegood placement (PRD 3.9)."""
from flask import Blueprint, request

import auth
import plcalc
import store
import timeutil
import views
from constants import DAYPARTS, ORDER_STATUSES, PRIORITY_CLASSES
from errors import fail
from response import created, listing, ok
from routes_playlist import build_item, drop_item
from validate import F, validate

bp = Blueprint("spot", __name__)

TRAFFIC = ["TrafficCoordinator", "StationAdmin"]
ORDER_READERS = ["MasterControlOperator", "ProgramDirector", "TrafficCoordinator",
                 "ComplianceOfficer", "StationAdmin"]
PLACERS = ["ProgramDirector", "TrafficCoordinator", "StationAdmin"]


@bp.post("/spot-orders")
def create_order():
    auth.authorize(TRAFFIC)
    body = validate(request.get_json(silent=True), [
        F("channel_id", "str", required=True),
        F("advertiser_name", "str", required=True, min_len=1),
        F("order_reference", "str", required=True, min_len=1, max_len=64),
        F("ordered_spots", "int", required=True, minimum=1),
        F("unit_duration_seconds", "int", required=True, minimum=5),
        F("rate_cents_total", "int", required=True, minimum=1),
        F("daypart", "enum", required=True, values=DAYPARTS),
        F("priority_class", "enum", required=True, values=PRIORITY_CLASSES),
        F("makegood_deadline_utc", "ts", required=True),
    ])
    channel = auth.channel(body["channel_id"])
    for existing in store.rows(store.spot_orders):
        if existing["order_reference"] == body["order_reference"]:
            fail("ERR_DUPLICATE_ORDER_REFERENCE",
                 "order_reference %s is already held by another order."
                 % body["order_reference"])
    rec = store.base()
    rec.update({
        "channel_id": channel["id"],
        "advertiser_name": body["advertiser_name"],
        "order_reference": body["order_reference"],
        "ordered_spots": int(body["ordered_spots"]),
        "unit_duration_seconds": int(body["unit_duration_seconds"]),
        "rate_cents_total": int(body["rate_cents_total"]),
        "daypart": body["daypart"],
        "priority_class": body["priority_class"],
        "makegood_deadline_utc": body["makegood_deadline_utc"],
        "scheduled_spots": 0,
        "aired_spots": 0,
        "short_aired_spots": 0,
        "credited_spots": 0,
        "unplaced_spots": int(body["ordered_spots"]),
        "credit_accrued_cents": 0,
        "status": "OPEN",
    })
    store.add(store.spot_orders, rec)
    return created(views.plain(rec))


@bp.get("/spot-orders/<ident>")
def read_order(ident):
    auth.authorize(ORDER_READERS, mutating=False)
    return ok(views.plain(auth.spot_order(ident)))


@bp.get("/spot-orders")
def list_orders():
    auth.authorize(ORDER_READERS, mutating=False)
    rows = store.rows(store.spot_orders)
    value = request.args.get("channel_id")
    if value:
        rows = [r for r in rows if r["channel_id"] == value]
    for name, vocabulary in (("status", ORDER_STATUSES), ("priority_class", PRIORITY_CLASSES)):
        value = request.args.get(name)
        if value:
            if value not in vocabulary:
                fail("ERR_INVALID_ENUM_VALUE", "%s '%s' is not recognised." % (name, value))
            rows = [r for r in rows if r[name] == value]
    return listing(rows, views.plain)


# --- makegoods -------------------------------------------------------------

def credited_element(order):
    """The oldest credited element of the order that no makegood has replaced yet."""
    for item in plcalc.linked_items(order):
        if plcalc.classify(item, order) == "NOT_AIRED":
            return item
    return None


@bp.post("/spot-orders/<ident>/makegoods")
def place_makegood(ident):
    auth.authorize(PLACERS)
    body = validate(request.get_json(silent=True), [
        F("target_playlist_id", "str", required=True),
        F("expected_playlist_version", "int", required=True, minimum=0),
        F("sequence_number", "int", required=True, minimum=1),
        F("scheduled_start_utc", "ts", required=True),
        F("scheduled_duration_seconds", "int", minimum=1),
    ])
    order = auth.spot_order(ident)
    playlist = auth.playlist(body["target_playlist_id"])

    deadline = timeutil.sec(order["makegood_deadline_utc"])
    if timeutil.sec(store.clock()) > deadline \
            or timeutil.sec(body["scheduled_start_utc"]) > deadline:
        fail("ERR_MAKEGOOD_DEADLINE_PASSED",
             "The makegood deadline for this order has passed.")
    if int(order["credited_spots"]) < 1:
        fail("ERR_NO_CREDITED_SPOT_TO_MAKEGOOD",
             "The order holds no credited spot to place again.")
    if playlist["channel_id"] != order["channel_id"]:
        fail("ERR_SPOT_ORDER_CHANNEL_MISMATCH",
             "The target playlist belongs to another channel.")
    channel = store.channels.get(order["channel_id"])
    if channel is None or playlist["channel_id"] != channel["id"]:
        fail("ERR_ITEM_PLAYLIST_MISMATCH",
             "The target playlist does not belong to the order's channel.")
    if int(body["expected_playlist_version"]) != int(playlist["version"]):
        fail("ERR_STALE_PLAYLIST_VERSION", "The target playlist version has moved on.")
    if order["status"] in ("FULLY_AIRED", "CLOSED_WITH_CREDIT"):
        fail("ERR_ORDER_FULLY_SETTLED", "The order is already settled.")
    if playlist["status"] in ("CLOSED", "ABANDONED"):
        fail("ERR_PLAYLIST_INVALID_STATE",
             "A makegood cannot be placed into a closed or abandoned playlist.")

    numbers = [int(i["sequence_number"]) for i in store.items_of(playlist["id"])]
    wanted = int(body["sequence_number"])
    if wanted in numbers or sorted(numbers + [wanted]) != list(range(1, len(numbers) + 2)):
        fail("ERR_SEQUENCE_NUMBER_CONFLICT",
             "sequence_number %d would break the playlist's dense run." % wanted)

    replaced = credited_element(order)
    duration = int(body["scheduled_duration_seconds"]) \
        if body.get("scheduled_duration_seconds") is not None \
        else int(order["unit_duration_seconds"])
    reversal = plcalc.round_half_up(plcalc.raw_credit(replaced, order, "NOT_AIRED")) \
        if replaced is not None else plcalc.full_spot_credit(order)

    spec = {
        "sequence_number": wanted,
        "element_kind": "COMMERCIAL",
        "scheduled_start_utc": body["scheduled_start_utc"],
        "scheduled_duration_seconds": duration,
        "asset_id": replaced.get("asset_id") if replaced is not None else None,
        "spot_order_id": order["id"],
        "feed_window_id": None,
        "max_trim_seconds": 0,
    }
    item = build_item(playlist, spec, is_makegood=True,
                      replaces_item_id=replaced["id"] if replaced is not None else None)
    try:
        plcalc.check_inventory(playlist)
        plcalc.check_timeline(playlist)
    except Exception:
        drop_item(item)
        plcalc.recompute_playlist(playlist, bump=False)
        raise

    order["credited_spots"] = max(0, int(order["credited_spots"]) - 1)
    order["credit_accrued_cents"] = max(0, int(order["credit_accrued_cents"]) - int(reversal))
    plcalc.recompute_unplaced(order)
    plcalc.refresh_order_status(order)
    store.bump(order)

    if playlist["status"] in ("VALIDATED", "ARMED"):
        playlist["status"] = "IMPORTED"
        playlist["armed_at_utc"] = None
    plcalc.recompute_playlist(playlist, bump=False)
    store.bump(playlist)
    return created(views.item_view(item))
