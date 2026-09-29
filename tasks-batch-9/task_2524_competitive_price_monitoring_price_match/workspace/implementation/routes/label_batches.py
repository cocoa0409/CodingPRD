"""Shelf-label print batch endpoints (PRD 3.10)."""
from flask import Blueprint, request

import clock
import db
from errors import err
from middleware import (ALL_ROLES, PRICING_MANAGER, STORE_MANAGER, body,
                        endpoint, enforce_store_scope)
from response import object_response
from routes.common import FK_STORE, filtered, list_page, path_lookup, resolve_fks
from services import calc, cascades, ledger, serialize
from util import as_dt, as_enum, as_int, as_str, get_required, invalid

bp = Blueprint("label_batches", __name__)

ADVANCE_STATUSES = ("PRINTING", "COMPLETED")


@bp.post("/label-batches")
@endpoint([STORE_MANAGER, PRICING_MANAGER])
def create_label_batch(user_id, role):
    payload = body()
    fks = resolve_fks(payload, [FK_STORE])

    store = fks["store_id"]
    if store is None:
        get_required(payload, "store_id")
    window_start = as_dt(get_required(payload, "window_start"), "window_start")
    window_end = as_dt(get_required(payload, "window_end"), "window_end")
    if window_end <= window_start:
        raise invalid("window_end", "must be strictly later than window_start.")
    reserved_item_count = 0
    if payload.get("reserved_item_count") is not None:
        reserved_item_count = as_int(payload["reserved_item_count"],
                                     "reserved_item_count", minimum=0)

    enforce_store_scope(user_id, role, store["id"])

    if cascades.batch_window_conflict(store["id"], window_start, window_end,
                                      calc.PRINTER_BUFFER_MINUTES):
        raise err("ERR_PRINT_WINDOW_CONFLICT",
                  "The window sits within %d minutes of another live batch."
                  % calc.PRINTER_BUFFER_MINUTES)

    if (ledger.label_slots_used_today(store) + reserved_item_count
            > store["label_printer_capacity_per_day"]):
        raise err("ERR_PRINT_CAPACITY_EXCEEDED",
                  "The reservation exceeds the store's daily printer capacity.")

    record = db.new_record()
    record.update({
        "store_id": store["id"],
        "window_start": window_start,
        "window_end": window_end,
        "reserved_item_count": reserved_item_count,
        "queued_order_ids": [],
        "status": "SCHEDULED",
        "cancel_reason": None,
    })
    db.batches[record["id"]] = record
    return object_response(serialize.batch(record), 201)


@bp.post("/label-batches/<batch_id>/advance")
@endpoint([STORE_MANAGER, PRICING_MANAGER])
def advance_label_batch(user_id, role, batch_id):
    batch = path_lookup("batches", batch_id, "ERR_BATCH_NOT_FOUND")
    payload = body()
    to_status_raw = as_str(get_required(payload, "to_status"), "to_status",
                          min_len=1)
    to_status = as_enum(to_status_raw, "to_status", ADVANCE_STATUSES)

    enforce_store_scope(user_id, role, batch["store_id"])

    if to_status == "PRINTING":
        if batch["status"] != "SCHEDULED":
            raise err("ERR_INVALID_STATE",
                      "Only a SCHEDULED batch may start printing.")
        if clock.now() < batch["window_start"]:
            raise err("ERR_INVALID_STATE",
                      "The batch's window_start has not been reached.")
        batch["status"] = "PRINTING"
        db.touch(batch)
    else:
        if batch["status"] != "PRINTING":
            raise err("ERR_INVALID_STATE",
                      "Only a PRINTING batch may be completed.")
        cascades.complete_batch(batch)

    return object_response(serialize.batch(batch))


@bp.post("/label-batches/<batch_id>/cancel")
@endpoint([STORE_MANAGER, PRICING_MANAGER])
def cancel_label_batch(user_id, role, batch_id):
    batch = path_lookup("batches", batch_id, "ERR_BATCH_NOT_FOUND")
    payload = body()
    cancel_reason = as_str(get_required(payload, "cancel_reason"),
                          "cancel_reason", min_len=1)

    enforce_store_scope(user_id, role, batch["store_id"])

    if batch["status"] not in ("SCHEDULED", "PRINTING"):
        raise err("ERR_INVALID_STATE",
                  "A batch in %s cannot be cancelled." % batch["status"])

    cascades.cancel_batch(batch, cancel_reason)
    return object_response(serialize.batch(batch))


@bp.get("/label-batches/<batch_id>")
@endpoint(ALL_ROLES)
def read_label_batch(user_id, role, batch_id):
    batch = path_lookup("batches", batch_id, "ERR_BATCH_NOT_FOUND")
    return object_response(serialize.batch(batch))


@bp.get("/label-batches")
@endpoint(ALL_ROLES)
def list_label_batches(user_id, role):
    rows = filtered(db.ordered(db.batches), request.args,
                    [("store_id", "store_id"), ("status", "status")])
    return list_page(rows, serialize.batch)
