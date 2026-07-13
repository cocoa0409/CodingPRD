"""ChannelPrice: create (OCC + supersede + overlap) and reads."""
from flask import Blueprint, request

from auth import identity, require_roles, require_ownership
from envelope import ApiError, success
from helpers import resolve, get_body, require_fields, require_enum, paginate_list
from store import db, base_record, touch, parse_dt
import calc
import models
import queries

bp = Blueprint("price", __name__)

TERRITORIES = {"US", "UK", "EU", "ROW"}


def _windows_overlap(a_start, a_end, b_start, b_end):
    """Half-open [start, end); None end = +infinity. Touching endpoints do NOT
    overlap (strict inequalities)."""
    left = True if b_end is None else (a_start < b_end)
    right = True if a_end is None else (b_start < a_end)
    return left and right


@bp.route("/formats/<fid>/prices", methods=["POST"])
def create_price(fid):
    uid, role = identity()
    require_roles(role, {"Publisher"})
    fmt = resolve("format", fid)
    require_ownership(role, uid, "format", fmt)
    body = get_body()

    channel_id = body.get("channel_id")
    channel = resolve("channel", channel_id) if channel_id is not None else None

    ef = parse_dt(body.get("effective_from"))
    et = parse_dt(body.get("effective_to"))
    territory = body.get("territory")
    list_price = body.get("list_price_cents")
    expanded = bool(body.get("expanded_reach", False))
    expected = body.get("expected_format_version")

    # prio5 temporal: effective_to (if present) must be strictly > effective_from
    if body.get("effective_to") is not None and et is not None and ef is not None:
        if not (et > ef):
            raise ApiError("ERR_INVALID_EFFECTIVE_WINDOW",
                           "effective_to must be greater than effective_from")

    # prio7 business_constraint: channel supports this format type
    if channel is not None:
        if fmt["format_type"] not in channel.get("supports_formats", []):
            raise ApiError("ERR_CHANNEL_FORMAT_UNSUPPORTED",
                           "Channel does not distribute this format type")

    # identify prior open-ended default to supersede (only when new is open-ended)
    new_open_ended = body.get("effective_to") is None
    active_key = [p for p in db.prices.values()
                  if p["status"] == "ACTIVE" and p["format_id"] == fmt["id"]
                  and channel is not None and p["channel_id"] == channel["id"]
                  and p.get("territory") == territory]
    to_supersede = None
    if new_open_ended:
        for p in active_key:
            if parse_dt(p.get("effective_to")) is None:
                to_supersede = p
                break

    # prio7 business_constraint: window overlap (excluding the to-be-superseded default)
    if channel is not None and ef is not None and territory is not None:
        for p in active_key:
            if p is to_supersede:
                continue
            if _windows_overlap(ef, et, parse_dt(p.get("effective_from")),
                                parse_dt(p.get("effective_to"))):
                raise ApiError("ERR_PRICE_WINDOW_OVERLAP",
                               "Price window overlaps an existing ACTIVE price")

    # prio8 business_fiscal: list price within channel bounds (positive values only)
    if channel is not None and isinstance(list_price, int) and not isinstance(list_price, bool) \
            and list_price > 0:
        lo = channel.get("min_list_price_cents")
        hi = channel.get("max_list_price_cents")
        if (lo is not None and list_price < lo) or (hi is not None and list_price > hi):
            raise ApiError("ERR_PRICE_OUT_OF_BOUNDS",
                           "list_price_cents is outside the channel's accepted range")

    # prio9 concurrency: OCC on Format.version
    if expected is not None and expected != fmt["version"]:
        raise ApiError("ERR_STALE_FORMAT_VERSION",
                       "expected_format_version does not match the current format version")

    # prio10 shape
    require_fields(body, ["channel_id", "territory", "list_price_cents",
                          "effective_from", "expected_format_version"])
    require_enum(territory, TERRITORIES, "territory")
    if not isinstance(list_price, int) or isinstance(list_price, bool) or list_price <= 0:
        raise ApiError("ERR_INVALID_REQUEST", "list_price_cents must be a positive integer")
    if not isinstance(expected, int) or isinstance(expected, bool):
        raise ApiError("ERR_INVALID_REQUEST", "expected_format_version must be an integer")
    if ef is None:
        raise ApiError("ERR_INVALID_REQUEST", "effective_from is invalid")

    currency = body.get("currency", "USD")
    if currency is None:
        currency = "USD"

    royalty = calc.royalty_per_unit(fmt, channel, list_price, expanded)

    rec = base_record()
    rec.update({
        "format_id": fmt["id"],
        "channel_id": channel["id"],
        "territory": territory,
        "list_price_cents": list_price,
        "currency": currency,
        "effective_from": body["effective_from"],
        "effective_to": body.get("effective_to"),
        "expanded_reach": expanded,
        "royalty_per_unit_cents": royalty,
        "status": "ACTIVE",
    })
    db.prices[rec["id"]] = rec

    # side effect: supersede prior open-ended default (close its window)
    if to_supersede is not None:
        to_supersede["status"] = "SUPERSEDED"
        to_supersede["effective_to"] = body["effective_from"]
        touch(to_supersede)

    # side effect: creating a price increments Format.version by 1
    touch(fmt)

    return success(models.ser_price(rec), status=201)


@bp.route("/prices/<pid>", methods=["GET"])
def get_price(pid):
    uid, role = identity()
    require_roles(role, {"Publisher", "PlatformAdmin"})
    rec = resolve("price", pid)
    require_ownership(role, uid, "price", rec)
    return success(models.ser_price(rec))


@bp.route("/prices", methods=["GET"])
def list_prices():
    uid, role = identity()
    require_roles(role, {"Publisher", "PlatformAdmin"})
    records = list(db.prices.values())
    if role == "Publisher":
        records = [p for p in records
                   if queries.publisher_id_of_format(db.formats.get(p["format_id"])) == uid]
    fid = request.args.get("format_id")
    cid = request.args.get("channel_id")
    if fid:
        records = [p for p in records if p.get("format_id") == fid]
    if cid:
        records = [p for p in records if p.get("channel_id") == cid]
    return paginate_list(records, models.ser_price)
