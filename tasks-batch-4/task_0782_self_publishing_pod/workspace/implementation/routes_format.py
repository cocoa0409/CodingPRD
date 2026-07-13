"""Formats: CRUD + lifecycle actions (lock, publish, assign/release ISBN),
proof ordering and distribution-request creation."""
from flask import Blueprint, request

from auth import identity, require_roles, require_ownership
from envelope import ApiError, success
from helpers import (resolve, get_body, require_fields, require_enum,
                     require_positive_int, paginate_list)
from store import db, base_record, touch
import calc
import models
import queries

bp = Blueprint("format", __name__)

FORMAT_TYPES = {"PRINT", "EBOOK", "AUDIO"}
TRIM_SIZES = {"5x8", "6x9", "7x10", "8.5x11"}
INTERIOR_COLORS = {"BW", "STANDARD_COLOR", "PREMIUM_COLOR"}
TERRITORIES = {"US", "UK", "EU", "ROW"}


def _own_format(uid, role, fmt):
    require_ownership(role, uid, "format", fmt)


# ---------------- Format CRUD ----------------
@bp.route("/titles/<tid>/formats", methods=["POST"])
def create_format(tid):
    uid, role = identity()
    require_roles(role, {"Publisher"})
    title = resolve("title", tid)
    require_ownership(role, uid, "title", title)
    body = get_body()
    require_fields(body, ["format_type"])
    ftype = body["format_type"]
    require_enum(ftype, FORMAT_TYPES, "format_type")

    trim = body.get("trim_size")
    color = body.get("interior_color")
    pages = body.get("page_count")
    file_size = body.get("file_size_mb")
    print_cost = None
    if ftype == "PRINT":
        require_fields(body, ["trim_size", "interior_color", "page_count"])
        require_enum(trim, TRIM_SIZES, "trim_size")
        require_enum(color, INTERIOR_COLORS, "interior_color")
        require_positive_int(pages, "page_count")
        print_cost = calc.print_cost_per_unit(pages, color, trim)

    rec = base_record()
    rec.update({
        "title_id": title["id"],
        "format_type": ftype,
        "trim_size": trim,
        "interior_color": color,
        "page_count": pages,
        "file_size_mb": file_size,
        "isbn_id": None,
        "print_cost_cents": print_cost,
        "status": "DRAFT",
    })
    db.formats[rec["id"]] = rec
    return success(models.ser_format(rec), status=201)


@bp.route("/formats/<fid>", methods=["GET"])
def get_format(fid):
    uid, role = identity()
    require_roles(role, {"Publisher", "PlatformAdmin"})
    rec = resolve("format", fid)
    _own_format(uid, role, rec)
    return success(models.ser_format(rec))


@bp.route("/formats", methods=["GET"])
def list_formats():
    uid, role = identity()
    require_roles(role, {"Publisher", "PlatformAdmin"})
    records = list(db.formats.values())
    if role == "Publisher":
        records = [f for f in records if queries.publisher_id_of_format(f) == uid]
    title_id = request.args.get("title_id")
    if title_id:
        records = [f for f in records if f.get("title_id") == title_id]
    return paginate_list(records, models.ser_format)


# ---------------- lock ----------------
@bp.route("/formats/<fid>/lock", methods=["POST"])
def lock_format(fid):
    uid, role = identity()
    require_roles(role, {"Publisher"})
    fmt = resolve("format", fid)
    _own_format(uid, role, fmt)
    if fmt["status"] != "DRAFT":
        raise ApiError("ERR_FORMAT_INVALID_STATE", "Format must be DRAFT to lock")
    has_interior = any(a["format_id"] == fmt["id"] and a["asset_type"] == "INTERIOR"
                       and a["status"] == "VALIDATED" for a in db.assets.values())
    if not has_interior:
        raise ApiError("ERR_MANUSCRIPT_NOT_VALIDATED",
                       "A VALIDATED INTERIOR asset is required to lock")
    if fmt["format_type"] == "PRINT":
        has_cover = any(a["format_id"] == fmt["id"] and a["asset_type"] == "COVER"
                        and a["status"] == "VALIDATED" for a in db.assets.values())
        if not has_cover:
            raise ApiError("ERR_COVER_NOT_APPROVED",
                           "A VALIDATED COVER asset is required to lock a PRINT format")
    fmt["status"] = "CONTENT_LOCKED"
    touch(fmt)
    return success(models.ser_format(fmt))


# ---------------- publish (CASCADE A) ----------------
@bp.route("/formats/<fid>/publish", methods=["POST"])
def publish_format(fid):
    uid, role = identity()
    require_roles(role, {"Publisher"})
    fmt = resolve("format", fid)
    _own_format(uid, role, fmt)
    if fmt["status"] != "CONTENT_LOCKED":
        raise ApiError("ERR_FORMAT_INVALID_STATE", "Format must be CONTENT_LOCKED to publish")
    has_approved_proof = any(p["format_id"] == fmt["id"] and p["status"] == "APPROVED"
                             for p in db.proofs.values())
    if not has_approved_proof:
        raise ApiError("ERR_FORMAT_INVALID_STATE", "An APPROVED proof is required to publish")
    if not fmt.get("isbn_id"):
        raise ApiError("ERR_ISBN_NOT_ASSIGNED", "An assigned ISBN is required to publish")

    # 1. format -> PUBLISHED
    fmt["status"] = "PUBLISHED"
    touch(fmt)
    # 2. assigned Isbn ASSIGNED -> LOCKED
    for isbn in db.isbns.values():
        if isbn.get("assigned_format_id") == fmt["id"] and isbn["status"] == "ASSIGNED":
            isbn["status"] = "LOCKED"
            touch(isbn)
    # 3. APPROVED DistributionRequests -> LIVE (each drives Title DRAFT->LIVE)
    any_live = False
    for dr in db.drequests.values():
        if dr["format_id"] == fmt["id"] and dr["status"] == "APPROVED":
            dr["status"] = "LIVE"
            touch(dr)
            any_live = True
    # 4. Title DRAFT -> LIVE if any request reached LIVE
    if any_live:
        title = db.titles.get(fmt["title_id"])
        if title and title["status"] == "DRAFT":
            title["status"] = "LIVE"
            touch(title)
    return success(models.ser_format(fmt))


# ---------------- assign / release ISBN ----------------
@bp.route("/formats/<fid>/assign-isbn", methods=["POST"])
def assign_isbn(fid):
    uid, role = identity()
    require_roles(role, {"Publisher"})
    fmt = resolve("format", fid)
    _own_format(uid, role, fmt)
    body = get_body()
    isbn_id = body.get("isbn_id")
    if isbn_id is None:
        raise ApiError("ERR_INVALID_REQUEST", "isbn_id is required")
    isbn = resolve("isbn", isbn_id)
    owner_pub = queries.publisher_id_of_format(fmt)
    if isbn["status"] != "FREE" or isbn.get("publisher_id") != owner_pub:
        raise ApiError("ERR_ISBN_NOT_AVAILABLE",
                       "ISBN must be FREE and belong to the format's publisher")
    isbn["status"] = "ASSIGNED"
    isbn["assigned_format_id"] = fmt["id"]
    touch(isbn)
    fmt["isbn_id"] = isbn["id"]
    touch(fmt)
    return success(models.ser_format(fmt))


@bp.route("/formats/<fid>/release-isbn", methods=["POST"])
def release_isbn(fid):
    uid, role = identity()
    require_roles(role, {"Publisher"})
    fmt = resolve("format", fid)
    _own_format(uid, role, fmt)
    if not fmt.get("isbn_id"):
        raise ApiError("ERR_ISBN_NOT_ASSIGNED", "No ISBN is assigned to release")
    isbn = db.isbns.get(fmt["isbn_id"])
    if isbn and isbn["status"] == "ASSIGNED" and isbn.get("assigned_format_id") == fmt["id"]:
        isbn["status"] = "FREE"
        isbn["assigned_format_id"] = None
        touch(isbn)
    fmt["isbn_id"] = None
    touch(fmt)
    return success(models.ser_format(fmt))


# ---------------- order proof ----------------
@bp.route("/formats/<fid>/proofs", methods=["POST"])
def order_proof(fid):
    uid, role = identity()
    require_roles(role, {"Publisher"})
    fmt = resolve("format", fid)
    _own_format(uid, role, fmt)
    existing = [p for p in db.proofs.values() if p["format_id"] == fmt["id"]]
    next_round = max((p["round_number"] for p in existing), default=0) + 1
    rec = base_record()
    rec.update({
        "format_id": fmt["id"],
        "round_number": next_round,
        "revision_notes": None,
        "status": "ORDERED",
    })
    db.proofs[rec["id"]] = rec
    return success(models.ser_proof(rec), status=201)


# ---------------- create distribution request ----------------
@bp.route("/formats/<fid>/distribution-requests", methods=["POST"])
def create_distribution_request(fid):
    uid, role = identity()
    require_roles(role, {"Publisher"})
    fmt = resolve("format", fid)
    _own_format(uid, role, fmt)
    body = get_body()
    channel_id = body.get("channel_id")
    if channel_id is None:
        raise ApiError("ERR_INVALID_REQUEST", "channel_id is required")
    channel = resolve("channel", channel_id)
    territory = body.get("territory")
    expanded = bool(body.get("expanded_reach", False))
    # business_constraint (prio7): channel must distribute this format type
    if fmt["format_type"] not in channel.get("supports_formats", []):
        raise ApiError("ERR_CHANNEL_FORMAT_UNSUPPORTED",
                       "Channel does not distribute this format type")
    # business_fiscal (prio8): an ACTIVE in-bounds price must exist for the key
    lo = channel.get("min_list_price_cents")
    hi = channel.get("max_list_price_cents")
    has_price = any(
        p["status"] == "ACTIVE" and p["format_id"] == fmt["id"]
        and p["channel_id"] == channel["id"] and p.get("territory") == territory
        and (lo is None or p["list_price_cents"] >= lo)
        and (hi is None or p["list_price_cents"] <= hi)
        for p in db.prices.values()
    )
    if not has_price:
        raise ApiError("ERR_NO_VALID_PRICE",
                       "No ACTIVE in-bounds price exists for this format/channel/territory")
    # shape (prio10)
    require_enum(territory, TERRITORIES, "territory")
    rec = base_record()
    rec.update({
        "format_id": fmt["id"],
        "channel_id": channel["id"],
        "territory": territory,
        "expanded_reach": expanded,
        "reason": None,
        "status": "REQUESTED",
    })
    db.drequests[rec["id"]] = rec
    return success(models.ser_drequest(rec), status=201)
