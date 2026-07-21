"""Releases: metadata, editorial workflow, pre-saves — PRD §3.3, §3.5."""

from flask import Blueprint, request

from db import db, common_fields, days, now, touch
from errors import ApiError
from middleware import auth, require_ownership
from response import created, ok, ok_list, paginate, read_pagination
from services import calc, core
import validation as v

bp = Blueprint("releases", __name__)

RELEASE_STATUSES = {"DRAFT", "SUBMITTED", "IN_REVIEW", "APPROVED", "REJECTED", "LIVE", "TAKEN_DOWN"}


def owned_release(user_id, role, release_id):
    """Ownership (step 3) is checked before path existence, so an unknown release
    addressed by an artist still reports not-found rather than leaking ownership."""
    release = db.releases.get(release_id)
    if role == "Artist" and release is not None:
        require_ownership(user_id == release["artist_id"])
    return core.find_release(release_id)


@bp.post("/api/releases")
def create_release():
    user_id, role = auth("Artist")
    raw = v.body()
    if isinstance(raw.get("artist_id"), str):
        require_ownership(user_id == raw["artist_id"])

    artist_id = v.req_id(raw, "artist_id")
    title = v.req_string(raw, "title", min_len=1, max_len=200)
    release_date = v.req_datetime(raw, "release_date")
    primary_genre = v.req_string(raw, "primary_genre")
    label_name = v.req_string(raw, "label_name")
    upc, has_upc = v.opt_string(raw, "upc")
    if has_upc:
        v.check_upc(upc)
    pre_save_enabled, has_pse = v.opt_bool(raw, "pre_save_enabled")
    pre_save_opens_at, has_psoa = v.opt_datetime(raw, "pre_save_opens_at")

    core.find_artist(artist_id)

    if upc is not None and any(r["upc"] == upc for r in db.releases.values()):
        raise ApiError("ERR_DUPLICATE_IDENTIFIER", "upc already in use.")

    row = common_fields()
    row.update({
        "artist_id": artist_id,
        "title": title,
        "upc": upc if has_upc else None,
        "release_date": release_date,
        "primary_genre": primary_genre,
        "label_name": label_name,
        "status": "DRAFT",
        "delivery_status": "NONE",
        "rejection_reason_code": None,
        "pre_save_enabled": pre_save_enabled if has_pse else False,
        "pre_save_opens_at": pre_save_opens_at if has_psoa else None,
        "pre_save_count": 0,
        "submitted_at": None,
        "taken_down_at": None,
    })
    db.releases[row["id"]] = row
    return created(row)


@bp.get("/api/releases/<release_id>")
def read_release(release_id):
    user_id, role = auth("Artist", "DistributionOps", "FinanceOps", "PlatformAdmin")
    return ok(owned_release(user_id, role, release_id))


@bp.get("/api/releases")
def list_releases():
    user_id, role = auth("Artist", "DistributionOps", "FinanceOps", "PlatformAdmin")
    limit, offset = read_pagination(request.args)
    rows = list(db.releases.values())
    if role == "Artist":
        rows = [r for r in rows if r["artist_id"] == user_id]
    artist_id = request.args.get("artist_id")
    if artist_id is not None:
        rows = [r for r in rows if r["artist_id"] == artist_id]
    status = request.args.get("status")
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    delivery_status = request.args.get("delivery_status")
    if delivery_status is not None:
        rows = [r for r in rows if r["delivery_status"] == delivery_status]
    page, total = paginate(rows, limit, offset)
    return ok_list(page, limit, offset, total)


@bp.patch("/api/releases/<release_id>")
def update_release(release_id):
    user_id, role = auth("Artist")
    data = v.body()
    title, has_title = v.opt_string(data, "title", min_len=1, max_len=200, nullable=False)
    upc, has_upc = v.opt_string(data, "upc")
    if has_upc:
        v.check_upc(upc)
    release_date, has_rd = v.opt_datetime(data, "release_date", nullable=False)
    primary_genre, has_pg = v.opt_string(data, "primary_genre", nullable=False)
    label_name, has_ln = v.opt_string(data, "label_name", nullable=False)
    pre_save_enabled, has_pse = v.opt_bool(data, "pre_save_enabled")
    pre_save_opens_at, has_psoa = v.opt_datetime(data, "pre_save_opens_at")

    release = owned_release(user_id, role, release_id)
    if release["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", "Only a DRAFT release may be amended.")

    if has_upc and upc is not None:
        if any(r["upc"] == upc and r["id"] != release["id"] for r in db.releases.values()):
            raise ApiError("ERR_DUPLICATE_IDENTIFIER", "upc already in use.")

    if has_title:
        release["title"] = title
    if has_upc:
        release["upc"] = upc
    if has_rd:
        release["release_date"] = release_date
    if has_pg:
        release["primary_genre"] = primary_genre
    if has_ln:
        release["label_name"] = label_name
    if has_pse:
        release["pre_save_enabled"] = pre_save_enabled
    if has_psoa:
        release["pre_save_opens_at"] = pre_save_opens_at
    touch(release)
    return ok(release)


@bp.post("/api/releases/<release_id>/submit")
def submit_release(release_id):
    user_id, role = auth("Artist")
    release = owned_release(user_id, role, release_id)

    if release["status"] != "DRAFT" or not core.tracks_of_release(release["id"]):
        raise ApiError("ERR_INVALID_STATE")

    if release["release_date"] < now() + days(core.MIN_RELEASE_LEAD_DAYS):
        raise ApiError("ERR_RELEASE_DATE_TOO_SOON")

    subscription = core.any_subscription(release["artist_id"])
    if not _subscription_entitled(subscription):
        raise ApiError("ERR_SUBSCRIPTION_INACTIVE")

    plan = db.subscription_plans.get(subscription["plan_id"])
    slots = plan["included_release_slots"] if plan else 0
    if subscription["releases_used"] >= slots:
        raise ApiError("ERR_RELEASE_SLOTS_EXHAUSTED")

    release["status"] = "SUBMITTED"
    release["submitted_at"] = now()
    touch(release)
    calc.recompute_releases_used(subscription)
    return ok(release)


def _subscription_entitled(subscription):
    if subscription is None:
        return False
    if subscription["status"] == "ACTIVE":
        return True
    if subscription["status"] == "PAST_DUE" and subscription["past_due_since"] is not None:
        return now() < subscription["past_due_since"] + days(core.SUBSCRIPTION_GRACE_DAYS)
    return False


@bp.post("/api/releases/<release_id>/withdraw")
def withdraw_release(release_id):
    user_id, role = auth("Artist")
    release = owned_release(user_id, role, release_id)

    if release["status"] == "SUBMITTED":
        release["status"] = "DRAFT"
        release["submitted_at"] = None
    elif release["status"] == "REJECTED":
        release["status"] = "DRAFT"
        release["rejection_reason_code"] = None
    else:
        raise ApiError("ERR_INVALID_STATE")

    touch(release)
    calc.recompute_releases_used(core.any_subscription(release["artist_id"]))
    return ok(release)


@bp.post("/api/releases/<release_id>/review")
def review_release(release_id):
    auth("DistributionOps")
    release = core.find_release(release_id)
    if release["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE")
    release["status"] = "IN_REVIEW"
    touch(release)
    return ok(release)


@bp.post("/api/releases/<release_id>/approve")
def approve_release(release_id):
    auth("DistributionOps")
    release = core.find_release(release_id)
    if release["status"] != "IN_REVIEW" or release["upc"] is None:
        raise ApiError("ERR_INVALID_STATE")
    release["status"] = "APPROVED"
    touch(release)
    return ok(release)


@bp.post("/api/releases/<release_id>/reject")
def reject_release(release_id):
    auth("DistributionOps")
    data = v.body()
    reason_code = v.req_string(data, "reason_code")

    release = core.find_release(release_id)
    if release["status"] != "IN_REVIEW":
        raise ApiError("ERR_INVALID_STATE")
    release["status"] = "REJECTED"
    release["rejection_reason_code"] = reason_code
    touch(release)
    calc.recompute_releases_used(core.any_subscription(release["artist_id"]))
    return ok(release)


@bp.post("/api/releases/<release_id>/go-live")
def go_live_release(release_id):
    auth("DistributionOps")
    release = core.find_release(release_id)
    if release["status"] != "APPROVED" or release["delivery_status"] != "DELIVERED":
        raise ApiError("ERR_INVALID_STATE")
    if now() < release["release_date"]:
        raise ApiError("ERR_RELEASE_DATE_NOT_REACHED")
    apply_go_live(release)
    return ok(release)


def apply_go_live(release):
    """PRD §3.5 — shared by the explicit and the automatic entry points."""
    release["status"] = "LIVE"
    for track in core.tracks_of_release(release["id"]):
        if track["status"] == "PENDING":
            track["status"] = "ACTIVE"
            touch(track)
    touch(release)
    calc.recompute_live_track_count(db.artists.get(release["artist_id"]))


@bp.post("/api/releases/<release_id>/takedown")
def takedown_release(release_id):
    user_id, role = auth("Artist", "DistributionOps")
    release = owned_release(user_id, role, release_id)
    if release["delivery_status"] != "DELIVERED":
        raise ApiError("ERR_INVALID_STATE")

    release["delivery_status"] = "TAKEDOWN_PENDING"
    for delivery in core.deliveries_of_release(release["id"]):
        if delivery["status"] == "ACCEPTED":
            delivery["status"] = "TAKEDOWN_REQUESTED"
            touch(delivery)
    touch(release)
    return ok(release)


@bp.post("/api/releases/<release_id>/pre-saves")
def register_pre_save(release_id):
    auth("Fan")
    data = v.body()
    v.req_string(data, "fan_reference")

    release = core.find_release(release_id)
    instant = now()
    opens_at = release["pre_save_opens_at"]
    if (
        not release["pre_save_enabled"]
        or opens_at is None
        or opens_at > instant
        or instant >= release["release_date"]
    ):
        raise ApiError("ERR_PRE_SAVE_WINDOW_CLOSED")

    release["pre_save_count"] += 1
    touch(release)
    return ok(release)
