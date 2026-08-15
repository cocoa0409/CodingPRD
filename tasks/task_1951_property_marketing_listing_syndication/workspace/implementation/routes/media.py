from flask import Blueprint, request

import clock
from db import store
from errors import (
    ApiError,
    ERR_INVALID_STATE,
    ERR_POSTURE_SUSPENDED,
    ERR_MEDIA_TOO_SMALL,
    ERR_PRIMARY_REQUIRES_PHOTO,
    ERR_MEDIA_NOT_READY,
    ERR_ALREADY_PRIMARY,
)
from middleware import (
    authenticate, require_roles, check_listing_ownership, get_body,
    f_str, f_int, f_enum, not_found, paginate,
)
from middleware import invalid
from response import success_object, success_list
from services import derived
from services.ops import stamp, touch, queue_jobs_for_subscribed_subs
from services.serialize import media_json

bp = Blueprint("media", __name__)

READ_ROLES = ("ListingAgent", "MarketingCoordinator", "ComplianceOfficer",
              "MarketingDirector")
WRITE_ROLES = ("ListingAgent", "MarketingCoordinator")
KINDS = ("PHOTO", "VIDEO", "FLOOR_PLAN")


def _media_jobs(listing, now):
    if listing["lifecycle_status"] == "ACTIVE":
        queue_jobs_for_subscribed_subs(listing, "MEDIA_UPDATE", now)


def _load_asset(asset_id):
    uid, role = authenticate()
    require_roles(role, WRITE_ROLES)
    asset = store.media_assets.get(asset_id)
    if asset is None:
        raise not_found("MediaAsset not found")
    listing = store.listings.get(asset["listing_id"])
    if listing is not None:
        check_listing_ownership(role, uid, listing)
    return asset, listing


def _posture_guard(listing, now):
    if listing is not None and derived.compute_posture(listing, now) == "SUSPENDED":
        raise ApiError(ERR_POSTURE_SUSPENDED, 409,
                       "Mutation forbidden while posture is SUSPENDED")


@bp.route("/listings/<listing_id>/media-assets", methods=["POST"])
def create_media(listing_id):
    uid, role = authenticate()
    require_roles(role, WRITE_ROLES)
    listing = store.listings.get(listing_id)
    if listing is None:
        raise not_found("Listing not found")
    check_listing_ownership(role, uid, listing)
    body = get_body()
    kind = f_enum(body, "kind", KINDS, required=True)
    file_url = f_str(body, "file_url", required=True)
    file_bytes = f_int(body, "file_bytes", required=True)
    if file_bytes <= 0:
        raise invalid("file_bytes must be > 0")
    width_px = f_int(body, "width_px")
    height_px = f_int(body, "height_px")
    now = clock.now()
    _posture_guard(listing, now)
    asset = stamp({
        "listing_id": listing["id"],
        "kind": kind,
        "file_url": file_url,
        "file_bytes": file_bytes,
        "width_px": width_px,
        "height_px": height_px,
        "is_primary": False,
        "status": "UPLOADED",
    }, now)
    store.media_assets[asset["id"]] = asset
    return success_object(media_json(asset), status=201)


@bp.route("/listings/<listing_id>/media-assets", methods=["GET"])
def list_media(listing_id):
    _, role = authenticate()
    require_roles(role, READ_ROLES)
    listing = store.listings.get(listing_id)
    if listing is None:
        raise not_found("Listing not found")
    kind = request.args.get("kind")
    status = request.args.get("status")
    items = sorted(
        (m for m in store.media_assets.values()
         if m["listing_id"] == listing["id"]),
        key=lambda m: (m["created_at"], m["_seq"]))
    if kind is not None:
        items = [m for m in items if m["kind"] == kind]
    if status is not None:
        items = [m for m in items if m["status"] == status]
    page, limit, offset, total = paginate(items)
    return success_list([media_json(m) for m in page], limit, offset, total)


@bp.route("/media-assets/<asset_id>/mark-ready", methods=["POST"])
def mark_ready(asset_id):
    asset, listing = _load_asset(asset_id)
    get_body()
    # Field validity first (PRD 3.2): PHOTO missing dims -> 400.
    if asset["kind"] == "PHOTO" and (
            asset["width_px"] is None or asset["height_px"] is None):
        raise invalid("PHOTO requires width_px and height_px")
    # State gate: asset UPLOADED, listing lifecycle in {DRAFT, COMPLIANCE_HOLD, ACTIVE}.
    if asset["status"] != "UPLOADED":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "mark-ready requires asset status UPLOADED")
    if listing is not None and listing["lifecycle_status"] not in (
            "DRAFT", "COMPLIANCE_HOLD", "ACTIVE"):
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Listing lifecycle does not permit mark-ready")
    now = clock.now()
    _posture_guard(listing, now)
    if asset["kind"] == "PHOTO" and (
            asset["width_px"] < 1024 or asset["height_px"] < 768):
        raise ApiError(ERR_MEDIA_TOO_SMALL, 422,
                       "PHOTO must be at least 1024x768")
    asset["status"] = "READY"
    touch(asset, now)
    if asset["kind"] == "PHOTO":
        has_primary = any(
            m["listing_id"] == asset["listing_id"] and m["kind"] == "PHOTO"
            and m["status"] == "READY" and m["is_primary"] and m["id"] != asset["id"]
            for m in store.media_assets.values())
        if not has_primary:
            asset["is_primary"] = True
    if listing is not None:
        _media_jobs(listing, now)
    return success_object(media_json(asset))


@bp.route("/media-assets/<asset_id>/set-primary", methods=["POST"])
def set_primary(asset_id):
    asset, listing = _load_asset(asset_id)
    get_body()
    now = clock.now()
    _posture_guard(listing, now)
    if asset["kind"] != "PHOTO":
        raise ApiError(ERR_PRIMARY_REQUIRES_PHOTO, 422,
                       "set-primary requires a PHOTO asset")
    if asset["status"] != "READY":
        raise ApiError(ERR_MEDIA_NOT_READY, 409,
                       "set-primary requires asset status READY")
    if asset["is_primary"]:
        raise ApiError(ERR_ALREADY_PRIMARY, 409,
                       "Asset is already the primary photo")
    for m in store.media_assets.values():
        if m["listing_id"] == asset["listing_id"] and m["kind"] == "PHOTO" \
                and m["status"] == "READY" and m["is_primary"]:
            m["is_primary"] = False
            touch(m, now)
    asset["is_primary"] = True
    touch(asset, now)
    if listing is not None:
        _media_jobs(listing, now)
    return success_object(media_json(asset))


@bp.route("/media-assets/<asset_id>/archive", methods=["POST"])
def archive(asset_id):
    asset, listing = _load_asset(asset_id)
    get_body()
    if asset["status"] not in ("READY", "REJECTED"):
        raise ApiError(ERR_INVALID_STATE, 409,
                       "archive requires asset status READY or REJECTED")
    now = clock.now()
    _posture_guard(listing, now)
    from_ready = asset["status"] == "READY"
    was_primary_ready_photo = from_ready and asset["kind"] == "PHOTO" \
        and asset["is_primary"]
    asset["status"] = "ARCHIVED"
    asset["is_primary"] = False
    touch(asset, now)
    if was_primary_ready_photo:
        remaining = sorted(
            (m for m in store.media_assets.values()
             if m["listing_id"] == asset["listing_id"] and m["kind"] == "PHOTO"
             and m["status"] == "READY"),
            key=lambda m: (m["created_at"], m["_seq"]))
        if remaining:
            remaining[0]["is_primary"] = True
            touch(remaining[0], now)
    if from_ready and listing is not None:
        _media_jobs(listing, now)
    return success_object(media_json(asset))
