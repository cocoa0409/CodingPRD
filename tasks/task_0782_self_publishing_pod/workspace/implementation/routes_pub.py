"""Publishers, ISBNs (pool), Channels, Titles, and publisher-scoped statement open."""
from flask import Blueprint

from auth import identity, require_roles, require_ownership, owner_of
from envelope import ApiError, success
from helpers import (resolve, get_body, require_fields, require_enum,
                     paginate_list, pagination, ordered)
from store import db, base_record, parse_dt
from envelope import success_list
import models

bp = Blueprint("pub", __name__)

PAYOUT_METHODS = {"BANK", "PAYPAL"}
CHANNEL_TYPES = {"RETAIL", "LIBRARY", "DIRECT"}
FORMAT_TYPES = {"PRINT", "EBOOK", "AUDIO"}


# ---------------- Publishers ----------------
@bp.route("/publishers", methods=["POST"])
def create_publisher():
    uid, role = identity()
    require_roles(role, {"PlatformAdmin"})
    body = get_body()
    require_fields(body, ["name", "email"])
    payout = body.get("payout_method", "BANK")
    if payout is None:
        payout = "BANK"
    require_enum(payout, PAYOUT_METHODS, "payout_method")
    rec = base_record()
    rec.update({
        "name": body["name"],
        "email": body["email"],
        "payout_method": payout,
        "reserve_held_cents": 0,
        "lifetime_paid_cents": 0,
        "status": "ACTIVE",
    })
    db.publishers[rec["id"]] = rec
    return success(models.ser_publisher(rec), status=201)


@bp.route("/publishers/<pid>", methods=["GET"])
def get_publisher(pid):
    uid, role = identity()
    require_roles(role, {"Publisher", "PlatformAdmin"})
    rec = resolve("publisher", pid)
    require_ownership(role, uid, "publisher", rec)
    return success(models.ser_publisher(rec))


@bp.route("/publishers/<pid>/isbns", methods=["POST"])
def add_isbn(pid):
    uid, role = identity()
    require_roles(role, {"PlatformAdmin"})
    pub = resolve("publisher", pid)
    body = get_body()
    require_fields(body, ["isbn_13"])
    rec = base_record()
    rec.update({
        "publisher_id": pub["id"],
        "isbn_13": body["isbn_13"],
        "assigned_format_id": None,
        "status": "FREE",
    })
    db.isbns[rec["id"]] = rec
    return success(models.ser_isbn(rec), status=201)


@bp.route("/publishers/<pid>/royalty-statements", methods=["POST"])
def open_statement(pid):
    uid, role = identity()
    require_roles(role, {"PlatformAdmin"})
    pub = resolve("publisher", pid)
    body = get_body()
    ps_dt = parse_dt(body.get("period_start"))
    pe_dt = parse_dt(body.get("period_end"))
    # business_constraint (priority 7): closed-inclusive period overlap, touching rejected
    if ps_dt is not None and pe_dt is not None:
        for s in db.statements.values():
            if s.get("publisher_id") != pub["id"]:
                continue
            es = parse_dt(s.get("period_start"))
            ee = parse_dt(s.get("period_end"))
            if es is None or ee is None:
                continue
            if ps_dt <= ee and es <= pe_dt:
                raise ApiError("ERR_STATEMENT_PERIOD_OVERLAP",
                               "Statement period overlaps an existing period")
    # shape (priority 10)
    require_fields(body, ["period_start", "period_end"])
    if ps_dt is None or pe_dt is None:
        raise ApiError("ERR_INVALID_REQUEST", "Invalid period_start/period_end")
    rec = base_record()
    rec.update({
        "publisher_id": pub["id"],
        "period_start": body["period_start"],
        "period_end": body["period_end"],
        "gross_royalty_cents": 0,
        "reserve_held_cents": 0,
        "reserve_released_cents": 0,
        "provisional_net_cents": 0,
        "net_payable_cents": 0,
        "status": "ACCRUING",
    })
    db.statements[rec["id"]] = rec
    return success(models.ser_statement(rec), status=201)


# ---------------- Channels ----------------
@bp.route("/channels", methods=["POST"])
def create_channel():
    uid, role = identity()
    require_roles(role, {"PlatformAdmin"})
    body = get_body()
    require_fields(body, ["name", "channel_type", "supports_formats",
                          "distribution_discount_standard",
                          "distribution_discount_expanded", "returns_reserve_pct",
                          "min_list_price_cents", "max_list_price_cents"])
    require_enum(body["channel_type"], CHANNEL_TYPES, "channel_type")
    sf = body["supports_formats"]
    if not isinstance(sf, list) or not sf or any(f not in FORMAT_TYPES for f in sf):
        raise ApiError("ERR_INVALID_REQUEST", "Invalid supports_formats")
    rec = base_record()
    rec.update({
        "name": body["name"],
        "channel_type": body["channel_type"],
        "supports_formats": sf,
        "ebook_high_rate": body.get("ebook_high_rate"),
        "ebook_low_rate": body.get("ebook_low_rate"),
        "ebook_rate_low_threshold_cents": body.get("ebook_rate_low_threshold_cents"),
        "ebook_rate_high_threshold_cents": body.get("ebook_rate_high_threshold_cents"),
        "delivery_fee_per_mb_cents": (body.get("delivery_fee_per_mb_cents")
                                      if body.get("delivery_fee_per_mb_cents") is not None else 0),
        "distribution_discount_standard": body["distribution_discount_standard"],
        "distribution_discount_expanded": body["distribution_discount_expanded"],
        "returns_reserve_pct": body["returns_reserve_pct"],
        "min_list_price_cents": body["min_list_price_cents"],
        "max_list_price_cents": body["max_list_price_cents"],
    })
    db.channels[rec["id"]] = rec
    return success(models.ser_channel(rec), status=201)


@bp.route("/channels/<cid>", methods=["GET"])
def get_channel(cid):
    uid, role = identity()
    require_roles(role, {"Publisher", "PlatformAdmin"})
    rec = resolve("channel", cid)
    return success(models.ser_channel(rec))


# ---------------- Titles ----------------
@bp.route("/titles", methods=["POST"])
def create_title():
    uid, role = identity()
    require_roles(role, {"Publisher"})
    body = get_body()
    pub_id = body.get("publisher_id")
    # ownership (403) before existence (404), per PRD precedence
    if pub_id is not None and pub_id != uid:
        raise ApiError("ERR_FORBIDDEN", "Publisher may only create titles it owns")
    if pub_id is not None:
        resolve("publisher", pub_id)
    require_fields(body, ["publisher_id", "title", "language", "bisac_category"])
    rec = base_record()
    rec.update({
        "publisher_id": pub_id,
        "title": body["title"],
        "subtitle": body.get("subtitle"),
        "language": body["language"],
        "bisac_category": body["bisac_category"],
        "status": "DRAFT",
    })
    db.titles[rec["id"]] = rec
    return success(models.ser_title(rec), status=201)


@bp.route("/titles/<tid>", methods=["GET"])
def get_title(tid):
    uid, role = identity()
    require_roles(role, {"Publisher", "PlatformAdmin"})
    rec = resolve("title", tid)
    require_ownership(role, uid, "title", rec)
    return success(models.ser_title(rec))


@bp.route("/titles", methods=["GET"])
def list_titles():
    from flask import request
    uid, role = identity()
    require_roles(role, {"Publisher", "PlatformAdmin"})
    records = list(db.titles.values())
    if role == "Publisher":
        records = [r for r in records if r.get("publisher_id") == uid]
    pub_filter = request.args.get("publisher_id")
    if pub_filter:
        records = [r for r in records if r.get("publisher_id") == pub_filter]
    return paginate_list(records, models.ser_title)
