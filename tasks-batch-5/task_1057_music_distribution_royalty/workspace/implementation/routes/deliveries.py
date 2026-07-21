"""Store delivery pipeline — PRD §3.6."""

from flask import Blueprint, request

from db import db, common_fields, days, minutes, now, touch
from errors import ApiError
from middleware import auth, require_ownership
from response import created, ok, ok_list, paginate, read_pagination
from routes.releases import apply_go_live
from services import calc, core
import validation as v

bp = Blueprint("deliveries", __name__)

OCCUPYING_STATUSES = ("QUEUED", "SENT")


def window_of(scheduled_send_at):
    start = scheduled_send_at - minutes(core.STORE_DELIVERY_BUFFER_MINUTES)
    end = (
        scheduled_send_at
        + minutes(core.STORE_DELIVERY_WINDOW_MINUTES)
        + minutes(core.STORE_DELIVERY_BUFFER_MINUTES)
    )
    return start, end


def intersects(a, b):
    """Half-open intervals: touching endpoints do not intersect."""
    return a[0] < b[1] and b[0] < a[1]


def owned_delivery(user_id, role, delivery_id):
    delivery = db.deliveries.get(delivery_id)
    if role == "Artist" and delivery is not None:
        release = db.releases.get(delivery["release_id"])
        if release is not None:
            require_ownership(user_id == release["artist_id"])
    return core.find_delivery(delivery_id)


@bp.post("/api/releases/<release_id>/deliveries")
def queue_delivery(release_id):
    auth("DistributionOps")
    data = v.body()
    store_id = v.req_id(data, "store_id")
    scheduled_send_at = v.req_datetime(data, "scheduled_send_at")

    release = core.find_release(release_id)
    store = core.find_store(store_id)

    if release["status"] not in ("APPROVED", "LIVE"):
        raise ApiError("ERR_INVALID_STATE")

    tracks = core.tracks_of_release(release["id"])

    if store["requires_explicit_flag"] and any(t["explicit"] is None for t in tracks):
        raise ApiError("ERR_METADATA_NONCOMPLIANT")
    if store["requires_isrc"] and any(t["isrc"] is None for t in tracks):
        raise ApiError("ERR_ISRC_MISSING")
    for track in tracks:
        sheet_id = track.get("locked_split_sheet_id")
        sheet = db.split_sheets.get(sheet_id) if sheet_id else None
        if sheet is None or sheet["status"] != "LOCKED":
            raise ApiError("ERR_SPLIT_SHEET_NOT_LOCKED")

    if scheduled_send_at + days(store["delivery_lead_days"]) > release["release_date"]:
        raise ApiError("ERR_DELIVERY_LEAD_TIME_VIOLATION")

    new_window = window_of(scheduled_send_at)
    occupancy = 0
    for existing in db.deliveries.values():
        if existing["store_id"] != store["id"]:
            continue
        if existing["status"] not in OCCUPYING_STATUSES:
            continue
        if intersects(window_of(existing["scheduled_send_at"]), new_window):
            occupancy += 1
    if occupancy >= store["max_concurrent_deliveries"]:
        raise ApiError("ERR_STORE_WINDOW_SATURATED")

    row = common_fields()
    row.update({
        "release_id": release["id"],
        "store_id": store["id"],
        "scheduled_send_at": scheduled_send_at,
        "status": "QUEUED",
        "attempt_count": 0,
        "last_error_code": None,
        "sent_at": None,
        "taken_down_at": None,
    })
    db.deliveries[row["id"]] = row

    if release["delivery_status"] == "NONE":
        release["delivery_status"] = "QUEUED"
    touch(release)
    return created(row)


@bp.get("/api/deliveries/<delivery_id>")
def read_delivery(delivery_id):
    user_id, role = auth("DistributionOps", "Artist", "PlatformAdmin")
    return ok(owned_delivery(user_id, role, delivery_id))


@bp.get("/api/deliveries")
def list_deliveries():
    user_id, role = auth("DistributionOps", "Artist", "PlatformAdmin")
    limit, offset = read_pagination(request.args)
    rows = list(db.deliveries.values())
    if role == "Artist":
        own = {r["id"] for r in db.releases.values() if r["artist_id"] == user_id}
        rows = [d for d in rows if d["release_id"] in own]
    release_id = request.args.get("release_id")
    if release_id is not None:
        rows = [d for d in rows if d["release_id"] == release_id]
    store_id = request.args.get("store_id")
    if store_id is not None:
        rows = [d for d in rows if d["store_id"] == store_id]
    status = request.args.get("status")
    if status is not None:
        rows = [d for d in rows if d["status"] == status]
    page, total = paginate(rows, limit, offset)
    return ok_list(page, limit, offset, total)


@bp.post("/api/deliveries/<delivery_id>/send")
def send_delivery(delivery_id):
    auth("DistributionOps")
    delivery = core.find_delivery(delivery_id)
    store = db.stores.get(delivery["store_id"])
    if delivery["status"] != "QUEUED" or store is None or store["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE")
    delivery["status"] = "SENT"
    delivery["attempt_count"] += 1
    delivery["sent_at"] = now()
    touch(delivery)
    return ok(delivery)


@bp.post("/api/deliveries/<delivery_id>/ack")
def ack_delivery(delivery_id):
    auth("DistributionOps")
    data = v.body()
    outcome = v.req_enum(data, "outcome", {"ACCEPTED", "REJECTED"})
    error_code, has_error_code = v.opt_string(data, "error_code")

    delivery = core.find_delivery(delivery_id)
    if delivery["status"] != "SENT":
        raise ApiError("ERR_INVALID_STATE")

    if outcome == "REJECTED":
        delivery["status"] = "REJECTED"
        delivery["last_error_code"] = error_code if has_error_code else None
        touch(delivery)
        return ok(delivery)

    delivery["status"] = "ACCEPTED"
    delivery["last_error_code"] = None
    touch(delivery)

    release = db.releases.get(delivery["release_id"])
    if release is not None:
        _recompute_delivery_status(release)
    return ok(delivery)


def _recompute_delivery_status(release):
    siblings = core.deliveries_of_release(release["id"])
    outstanding = [d for d in siblings if d["status"] in ("QUEUED", "SENT", "REJECTED")]
    accepted = [d for d in siblings if d["status"] == "ACCEPTED"]

    if siblings and not outstanding and len(accepted) == len(siblings):
        target = "DELIVERED"
    elif accepted and outstanding:
        target = "PARTIAL"
    else:
        target = release["delivery_status"]

    if target != release["delivery_status"]:
        release["delivery_status"] = target
        touch(release)

    if (
        release["delivery_status"] == "DELIVERED"
        and release["status"] == "APPROVED"
        and now() >= release["release_date"]
    ):
        apply_go_live(release)


@bp.post("/api/deliveries/<delivery_id>/retry")
def retry_delivery(delivery_id):
    auth("DistributionOps")
    delivery = core.find_delivery(delivery_id)
    if (
        delivery["status"] != "REJECTED"
        or delivery["attempt_count"] >= core.MAX_DELIVERY_ATTEMPTS
    ):
        raise ApiError("ERR_INVALID_STATE")
    delivery["status"] = "QUEUED"
    touch(delivery)
    return ok(delivery)


@bp.post("/api/deliveries/<delivery_id>/confirm-takedown")
def confirm_takedown(delivery_id):
    auth("DistributionOps")
    delivery = core.find_delivery(delivery_id)
    if delivery["status"] != "TAKEDOWN_REQUESTED":
        raise ApiError("ERR_INVALID_STATE")

    delivery["status"] = "TAKEN_DOWN"
    delivery["taken_down_at"] = now()
    touch(delivery)

    release = db.releases.get(delivery["release_id"])
    if release is None:
        return ok(delivery)

    siblings = core.deliveries_of_release(release["id"])
    still_active = [
        d for d in siblings
        if d["status"] in ("QUEUED", "SENT", "ACCEPTED", "TAKEDOWN_REQUESTED")
    ]
    if not still_active:
        release["delivery_status"] = "TAKEN_DOWN"
        if release["status"] == "LIVE":
            release["status"] = "TAKEN_DOWN"
            release["taken_down_at"] = now()
            for track in core.tracks_of_release(release["id"]):
                if track["status"] == "ACTIVE":
                    track["status"] = "INACTIVE"
                    track["content_id_enabled"] = False
                    touch(track)
        touch(release)
        calc.recompute_live_track_count(db.artists.get(release["artist_id"]))
        calc.recompute_releases_used(core.any_subscription(release["artist_id"]))
    return ok(delivery)
