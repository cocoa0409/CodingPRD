"""HousingBlock endpoints.  rooms_total == rooms_available + rooms_occupied always."""
from flask import Blueprint, request

import derive
import store
import validate
from envelope import created, ok
from errors import fail
from routes.common import begin, listing
from store import touch

bp = Blueprint("housing", __name__)


@bp.post("/housing-blocks")
def create_block():
    begin()
    soft = validate.soft_body()
    raw_event = validate.raw_ref(soft, "event_id")
    event = validate.event(raw_event) if raw_event is not None else None
    payload = validate.body()
    if event is None:
        validate.req_string(payload, "event_id")

    hotel_name = validate.req_string(payload, "hotel_name")
    city = validate.req_string(payload, "city")
    rooms_total = validate.req_int(payload, "rooms_total", minimum=0, maximum=400)
    nightly_rate = validate.req_number(payload, "nightly_rate", exclusive_min=0)
    start = validate.req_datetime(payload, "block_start_date")
    end = validate.req_datetime(payload, "block_end_date")
    # Position 16 - interval well-formedness.
    validate.interval(start, end,
                      "block_end_date must be strictly later than block_start_date.")

    rec = store.base_record()
    rec.update({
        "event_id": event["id"],
        "hotel_name": hotel_name,
        "city": city,
        "rooms_total": rooms_total,
        "nightly_rate": nightly_rate,
        "block_start_date": start,
        "block_end_date": end,
        "status": "PENDING",
    })
    store.housing_blocks[rec["id"]] = rec
    return created(derive.housing_block_out(rec))


@bp.get("/housing-blocks")
def list_blocks():
    begin()
    rows = list(store.housing_blocks.values())
    for param, field in (("event_id", "event_id"), ("status", "status"),
                         ("city", "city")):
        value = request.args.get(param)
        if value is not None:
            rows = [r for r in rows if r.get(field) == value]
    return listing(rows, derive.housing_block_out)


@bp.get("/housing-blocks/<housing_block_id>")
def read_block(housing_block_id):
    begin()
    return ok(derive.housing_block_out(validate.housing_block(housing_block_id)))


@bp.post("/housing-blocks/<housing_block_id>/open")
def open_block(housing_block_id):
    begin()
    rec = validate.housing_block(housing_block_id)
    if rec["status"] != "PENDING":
        fail("ERR_HOUSING_NOT_PENDING")
    event = store.events.get(rec["event_id"])
    if event is None or event["status"] not in ("DECLARED", "SURGE_ACTIVE"):
        fail("ERR_EVENT_NOT_DECLARED")
    # Position 36 - an empty block can never be opened.
    if int(rec["rooms_total"]) < 1:
        fail("ERR_HOUSING_BLOCK_EMPTY")
    rec["status"] = "ACTIVE"
    touch(rec)
    touch(event)
    return ok(derive.housing_block_out(rec))


@bp.post("/housing-blocks/<housing_block_id>/release")
def release_block(housing_block_id):
    begin()
    rec = validate.housing_block(housing_block_id)
    if rec["status"] not in ("PENDING", "ACTIVE", "EXHAUSTED"):
        fail("ERR_HOUSING_NOT_RELEASABLE")
    if derive.block_rooms_occupied(rec["id"]) != 0:
        fail("ERR_HOUSING_STILL_OCCUPIED")
    rec["status"] = "RELEASED"
    touch(rec)
    return ok(derive.housing_block_out(rec))
