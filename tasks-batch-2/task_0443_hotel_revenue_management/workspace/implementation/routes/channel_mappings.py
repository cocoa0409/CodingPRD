"""ChannelMapping endpoints (PRD §3.5, §3.6)."""
from flask import Blueprint, request

from db import db, new_id
from middleware import authenticate, require_role
from response import success, list_success
from errors import (
    err, ERR_INVALID_REQUEST, ERR_FK_NOT_FOUND, ERR_CHANNEL_ALREADY_MAPPED,
)
from services.common import (
    get_body, require_str, opt_number, stamp_new, bump,
    parse_pagination, sort_by_created, get_or_404,
)
from services.serialize import ser_channel_mapping
from services.calc import sync_channel

bp = Blueprint("channel_mappings", __name__)

READ_ROLES = {"ChannelManager", "RevenueManager", "Analyst"}
CHANNELS = {"DIRECT", "OTA_A", "OTA_B", "GDS"}


@bp.route("/channel-mappings", methods=["POST"])
def create_channel_mapping():
    _, role = authenticate()
    require_role(role, {"ChannelManager"})
    body = get_body()
    rate_plan_id = require_str(body, "rate_plan_id")
    if "channel" not in body or body["channel"] is None:
        raise err(ERR_INVALID_REQUEST, "Missing required field: channel")
    channel = body["channel"]
    if channel not in CHANNELS:
        raise err(ERR_INVALID_REQUEST, "channel must be one of DIRECT,OTA_A,OTA_B,GDS")
    markup_pct = opt_number(body, "markup_pct", 0.0)
    if markup_pct < 0:
        raise err(ERR_INVALID_REQUEST, "markup_pct must be >= 0")
    manual_override = None
    if "manual_rate_override" in body and body["manual_rate_override"] is not None:
        manual_override = opt_number(body, "manual_rate_override", None)
        if manual_override < 0:
            raise err(ERR_INVALID_REQUEST, "manual_rate_override must be >= 0 when set")

    if rate_plan_id not in db.rate_plans:
        raise err(ERR_FK_NOT_FOUND, "rate_plan_id does not reference an existing rate plan")

    # At most one mapping per (rate_plan_id, channel).
    for m in db.channel_mappings.values():
        if m["rate_plan_id"] == rate_plan_id and m["channel"] == channel:
            raise err(ERR_CHANNEL_ALREADY_MAPPED, "A mapping already exists for this plan+channel")

    rec = {
        "id": new_id(),
        "rate_plan_id": rate_plan_id,
        "channel": channel,
        "markup_pct": markup_pct,
        "manual_rate_override": manual_override,
        "parity_status": "IN_PARITY",
        "channel_rate": None,
        "_seq": db.next_seq(),
    }
    stamp_new(rec)
    db.channel_mappings[rec["id"]] = rec
    # Sync channel_rate / parity (uses published_rate or override if available).
    sync_channel(rec)
    return success(ser_channel_mapping(rec), status=201)


@bp.route("/channel-mappings/<mid>", methods=["GET"])
def get_channel_mapping(mid):
    _, role = authenticate()
    require_role(role, READ_ROLES)
    rec = get_or_404(db.channel_mappings, mid)
    return success(ser_channel_mapping(rec), status=200)


@bp.route("/channel-mappings", methods=["GET"])
def list_channel_mappings():
    _, role = authenticate()
    require_role(role, READ_ROLES)
    limit, offset = parse_pagination()
    rate_plan_id = request.args.get("rate_plan_id")
    channel = request.args.get("channel")
    items = []
    for m in db.channel_mappings.values():
        if rate_plan_id is not None and m["rate_plan_id"] != rate_plan_id:
            continue
        if channel is not None and m["channel"] != channel:
            continue
        items.append(m)
    items = sort_by_created(items)
    total = len(items)
    page = [ser_channel_mapping(m) for m in items[offset:offset + limit]]
    return list_success(page, limit, offset, total)


@bp.route("/channel-mappings/<mid>", methods=["PATCH"])
def patch_channel_mapping(mid):
    _, role = authenticate()
    require_role(role, {"ChannelManager"})
    rec = get_or_404(db.channel_mappings, mid)
    body = get_body()

    if "markup_pct" in body and body["markup_pct"] is not None:
        mk = opt_number(body, "markup_pct", rec["markup_pct"])
        if mk < 0:
            raise err(ERR_INVALID_REQUEST, "markup_pct must be >= 0")
        rec["markup_pct"] = mk
    if "manual_rate_override" in body:
        mo = body["manual_rate_override"]
        if mo is None:
            rec["manual_rate_override"] = None
        else:
            mo = opt_number(body, "manual_rate_override", None)
            if mo < 0:
                raise err(ERR_INVALID_REQUEST, "manual_rate_override must be >= 0 when set")
            rec["manual_rate_override"] = mo

    # Re-run the sync for this mapping, recompute its parity_status, bump version
    # (PRD §3.5/§3.6 — scoped to the updated mapping).
    sync_channel(rec)
    bump(rec)
    return success(ser_channel_mapping(rec), status=200)
