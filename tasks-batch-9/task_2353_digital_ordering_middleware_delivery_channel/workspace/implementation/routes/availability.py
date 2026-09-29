"""Eighty-sixing and restoring items, and the cross-channel fan-out."""
from flask import Blueprint

import clock
import db
import errors
import middleware as M
import response
import validation
from errors import fail
from routes import common
from services import constants as K
from services import domain, serializers

bp = Blueprint("availability", __name__)


@bp.post("/availability-events")
@M.endpoint(M.STORE_OPERATOR, M.CHANNEL_PARTNER)
def create_availability_event():
    payload = validation.body()
    store_id = validation.req_str(payload, "store_id")
    menu_item_id = validation.req_str(payload, "menu_item_id")
    event_type = validation.req_enum(payload, "event_type", K.EVENT_TYPES)
    actor_channel_id = validation.opt_str(payload, "actor_channel_id")

    store = common.get_store(store_id)
    item = common.get_menu_item(menu_item_id)
    if actor_channel_id is not None:
        common.get_channel(actor_channel_id)

    M.require_store_scope(store["id"])
    if actor_channel_id is not None:
        M.require_channel_scope(actor_channel_id)

    if store["active_menu_version_id"] is None:
        fail(errors.ERR_STORE_MENU_NOT_PUBLISHED)
    if item["menu_version_id"] != store["active_menu_version_id"]:
        # A foreign key naming a row outside the addressed parent is not found.
        fail(errors.ERR_MENU_ITEM_NOT_FOUND)

    eighty_six = event_type == "EIGHTY_SIX"
    propagated = 0
    skipped = 0
    for listing in db.sorted_records(
            db.listings,
            lambda l: l["store_id"] == store["id"] and l["menu_item_id"] == item["id"]):
        channel = db.channels.get(listing["channel_id"])
        if channel is None or channel["eighty_six_policy"] != "HONOR_86":
            skipped += 1
            continue
        if listing["eighty_sixed"] != eighty_six:
            listing["eighty_sixed"] = eighty_six
            propagated += 1
            listing["availability_state"] = domain.derive_availability_state(
                listing, channel, store)
            db.touch(listing)
        else:
            listing["availability_state"] = domain.derive_availability_state(
                listing, channel, store)

    held = 0
    if eighty_six:
        for order in db.sorted_records(
                db.orders,
                lambda o: o["store_id"] == store["id"] and o["injection_status"] == "PENDING"):
            channel = db.channels.get(order["channel_id"])
            if channel is None or channel["eighty_six_policy"] != "HONOR_86":
                continue
            lines = domain.lines_of_order(order["id"])
            if not any(line["sku"] == item["sku"] for line in lines):
                continue
            order["injection_status"] = "INJECTION_HELD"
            db.touch(order)
            store["reserved_prep_slots"] = max(0, store["reserved_prep_slots"] - 1)
            db.touch(store)
            domain.withdraw_open_assignments(order, states=("OFFERED",))
            held += 1

    domain.bubble_menu_version_exhaustion(
        db.menu_versions.get(store["active_menu_version_id"]))

    event = db.record(journal=True)
    event.update({
        "store_id": store["id"],
        "menu_item_id": item["id"],
        "actor_channel_id": actor_channel_id,
        "event_type": event_type,
        "effective_at": clock.now(),
        "propagated_listing_count": propagated,
        "skipped_listing_count": skipped,
        "held_order_count": held,
    })
    db.availability_events[event["id"]] = event
    return response.object_response(serializers.availability_event(event), 201)


@bp.get("/availability-events/<event_id>")
@M.endpoint(M.PLATFORM_ADMIN, M.STORE_OPERATOR, M.CHANNEL_PARTNER)
def read_availability_event(event_id):
    event = common.get_availability_event(event_id)
    M.require_store_scope(event["store_id"])
    return response.object_response(serializers.availability_event(event))


@bp.get("/availability-events")
@M.endpoint(M.PLATFORM_ADMIN, M.STORE_OPERATOR, M.CHANNEL_PARTNER)
def list_availability_events():
    limit, offset = validation.pagination()
    store_id = validation.query_str("store_id")
    menu_item_id = validation.query_str("menu_item_id")
    actor_channel_id = validation.query_str("actor_channel_id")
    event_type = validation.query_enum("event_type", K.EVENT_TYPES)

    def keep(rec):
        if store_id is not None and rec["store_id"] != store_id:
            return False
        if menu_item_id is not None and rec["menu_item_id"] != menu_item_id:
            return False
        if actor_channel_id is not None and rec["actor_channel_id"] != actor_channel_id:
            return False
        if event_type is not None and rec["event_type"] != event_type:
            return False
        return True

    records = db.sorted_records(db.availability_events, keep)
    page, meta = response.paginate(records, limit, offset)
    return response.array_response(
        [serializers.availability_event(r) for r in page], meta)
