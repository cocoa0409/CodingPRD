"""WaitlistEntry routes (PRD §3.8)."""
from flask import Blueprint, request

import clock
import db
from errors import (
    err, ERR_NOT_FOUND, ERR_INVALID_STATE, ERR_NOT_RESOURCE_OWNER,
    ERR_CUSTOMER_BLOCKED, ERR_RESTAURANT_CLOSED, ERR_NOTIFY_WINDOW_EXPIRED,
    ERR_NO_MATCHING_TABLE,
)
from middleware import require_roles
from response import object_response, array_response
from services import calc
from services.lookup import get_or_404
from services.cascades import (
    promotion_winner, notify_entry, run_table_freeing_cascade,
    _find_available_table,
)
from timeutil import parse_iso
from validators import get_body, require_str, require_int, paginate

bp = Blueprint("waitlist", __name__)


@bp.post("/waitlist-entries")
def join_waitlist():
    user_id, role = require_roles({"Customer", "Host"})
    body = get_body()
    restaurant_id = require_str(body, "restaurant_id")
    customer_id = require_str(body, "customer_id")
    party_size = require_int(body, "party_size", minimum=1)
    requested_start = parse_iso(require_str(body, "requested_start"), "requested_start")

    restaurant = db.restaurants.get(restaurant_id)
    if restaurant is None:
        raise err(ERR_NOT_FOUND, "restaurant not found")
    customer = db.customers.get(customer_id)
    if customer is None:
        raise err(ERR_NOT_FOUND, "customer not found")
    # No ownership check on join: PRD §2.1 limits ERR_NOT_RESOURCE_OWNER to
    # cancel / reschedule / waitlist-cancel only.
    if customer["status"] == "BLOCKED":
        raise err(ERR_CUSTOMER_BLOCKED, "customer is blocked")
    if restaurant["status"] != "OPEN":
        raise err(ERR_RESTAURANT_CLOSED, "restaurant is closed")

    rec = db.base_fields()
    rec.update({
        "restaurant_id": restaurant_id,
        "customer_id": customer_id,
        "party_size": party_size,
        "requested_start": requested_start,
        "joined_at": rec["created_at"],
        "notify_expires_at": None,
        "notify_count": 0,
        "converted_reservation_id": None,
        "status": "WAITING",
    })
    db.waitlist_entries[rec["id"]] = rec
    return object_response(db.serialize(rec), 201)


@bp.get("/waitlist-entries/<wid>")
def read_waitlist(wid):
    require_roles({"Manager", "Host", "Customer"})
    rec = get_or_404(db.waitlist_entries, wid)
    return object_response(db.serialize(rec), 200)


@bp.get("/waitlist-entries")
def list_waitlist():
    require_roles({"Manager", "Host", "Customer"})
    a = request.args
    restaurant_id = a.get("restaurant_id")
    customer_id = a.get("customer_id")
    converted_reservation_id = a.get("converted_reservation_id")
    status = a.get("status")
    records = []
    for w in db.waitlist_entries.values():
        if restaurant_id is not None and w["restaurant_id"] != restaurant_id:
            continue
        if customer_id is not None and w["customer_id"] != customer_id:
            continue
        if converted_reservation_id is not None and w["converted_reservation_id"] != converted_reservation_id:
            continue
        if status is not None and w["status"] != status:
            continue
        records.append(w)
    page, pagination = paginate(records)
    return array_response([db.serialize(r) for r in page], pagination, 200)


@bp.post("/waitlist-entries/<wid>/notify")
def notify_waitlist(wid):
    require_roles({"Host"})
    entry = get_or_404(db.waitlist_entries, wid)
    if entry["status"] != "WAITING":
        raise err(ERR_INVALID_STATE, "entry is not WAITING")
    restaurant = db.restaurants[entry["restaurant_id"]]
    if restaurant["status"] != "OPEN":
        raise err(ERR_RESTAURANT_CLOSED, "restaurant is closed")
    # no AVAILABLE table fits -> ERR_NO_MATCHING_TABLE
    if _find_available_table(entry["restaurant_id"], entry["party_size"]) is None:
        raise err(ERR_NO_MATCHING_TABLE, "no available table fits the party")
    # must be the promotion winner
    winner = promotion_winner(entry["restaurant_id"])
    if winner is None or winner["id"] != entry["id"]:
        raise err(ERR_INVALID_STATE, "entry is not the promotion winner")
    customer = db.customers[entry["customer_id"]]
    notify_entry(entry, customer)
    return object_response(db.serialize(entry), 200)


@bp.post("/waitlist-entries/<wid>/convert")
def convert_waitlist(wid):
    require_roles({"Host"})
    entry = get_or_404(db.waitlist_entries, wid)
    if entry["status"] != "NOTIFIED":
        raise err(ERR_INVALID_STATE, "entry is not NOTIFIED")
    body = get_body()
    table_id = require_str(body, "table_id")
    table = db.tables.get(table_id)
    if table is None:
        raise err(ERR_NOT_FOUND, "table not found")
    # within the offer window
    if entry["notify_expires_at"] is not None and clock.now() > entry["notify_expires_at"]:
        raise err(ERR_NOTIFY_WINDOW_EXPIRED, "offer window expired")
    # a matching AVAILABLE table must exist
    if _find_available_table(entry["restaurant_id"], entry["party_size"]) is None:
        raise err(ERR_NO_MATCHING_TABLE, "no available table fits the party")
    # the supplied table must itself be AVAILABLE and fit the party
    if table["status"] != "AVAILABLE" or not (
            table["min_party_size"] <= entry["party_size"] <= table["max_party_size"]):
        raise err(ERR_NO_MATCHING_TABLE, "supplied table does not fit the party")

    now = clock.now()
    restaurant = db.restaurants[entry["restaurant_id"]]
    turn_window_end, release_at = calc.reservation_turn_window(now, table, restaurant)
    res = db.base_fields()
    res.update({
        "restaurant_id": entry["restaurant_id"],
        "customer_id": entry["customer_id"],
        "table_id": table_id,
        "expected_table_version": table["version"],
        "party_size": entry["party_size"],
        "reservation_start": now,
        "turn_window_end": turn_window_end,
        "release_at": release_at,
        "deposit_required": entry["party_size"] >= restaurant["deposit_required_party_threshold"],
        "cancellation_fee_cents": 0,
        "status": "CONFIRMED",
    })
    db.reservations[res["id"]] = res

    entry["converted_reservation_id"] = res["id"]
    entry["status"] = "CONVERTED"
    db.touch(entry)
    return object_response(db.serialize(entry), 200)


@bp.post("/waitlist-entries/<wid>/requeue")
def requeue_waitlist(wid):
    require_roles({"Host"})
    entry = get_or_404(db.waitlist_entries, wid)
    if entry["status"] != "NOTIFIED":
        raise err(ERR_INVALID_STATE, "entry is not NOTIFIED")
    entry["notify_count"] += 1
    entry["notify_expires_at"] = None
    entry["status"] = "WAITING"
    db.touch(entry)
    return object_response(db.serialize(entry), 200)


@bp.post("/waitlist-entries/<wid>/cancel")
def cancel_waitlist(wid):
    user_id, role = require_roles({"Customer", "Host"})
    entry = get_or_404(db.waitlist_entries, wid)
    if entry["status"] not in ("WAITING", "NOTIFIED"):
        raise err(ERR_INVALID_STATE, "entry is not cancellable")
    if role == "Customer" and entry["customer_id"] != user_id:
        raise err(ERR_NOT_RESOURCE_OWNER, "not the resource owner")
    was_notified = entry["status"] == "NOTIFIED"
    entry["status"] = "CANCELLED"
    db.touch(entry)
    if was_notified:
        # a freed-by-decline slot re-runs promotion
        run_table_freeing_cascade(entry["restaurant_id"])
    return object_response(db.serialize(entry), 200)
