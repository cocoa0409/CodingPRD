"""House ads."""

from db import store, new_id, next_seq, now_str, touch
from errors import (
    raise_err,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE_TRANSITION,
    ERR_REFERENCE_NOT_FOUND,
)
from middleware import caller, require_roles, body, ROLE_AD_OPS
from response import created, ok, paginate
from serializers import ser_house_ad
from services.core import get_or_404
from util import req_str, req_int, opt_int
from flask import Blueprint, request

bp = Blueprint("house_ads", __name__)

ADOPS = [ROLE_AD_OPS]

PATCH_TRANSITIONS = {
    ("ACTIVE", "PAUSED"),
    ("PAUSED", "ACTIVE"),
    ("ACTIVE", "RETIRED"),
    ("PAUSED", "RETIRED"),
}


@bp.route("/v1/house-ads", methods=["POST"])
def create_house_ad():
    _, role = caller()
    b = body()
    name = req_str(b, "name")
    priority_weight = req_int(b, "priority_weight")
    daily_cap = req_int(b, "daily_impression_cap")
    if daily_cap <= 0:
        raise_err(ERR_INVALID_REQUEST, "daily_impression_cap must be > 0")
    duration = opt_int(b, "duration_seconds")
    if duration is None:
        duration = 30
    elif duration != 30:
        raise_err(ERR_INVALID_REQUEST, "duration_seconds must be exactly 30")
    channel_id = b.get("channel_id")
    if channel_id is not None and not isinstance(channel_id, str):
        raise_err(ERR_INVALID_REQUEST, "channel_id must be a string or null")
    require_roles(role, ADOPS)
    if channel_id is not None and channel_id not in store.channels:
        raise_err(ERR_REFERENCE_NOT_FOUND, "channel_id does not reference an existing channel")
    ts = now_str()
    rec = {
        "id": new_id(),
        "name": name,
        "channel_id": channel_id,
        "duration_seconds": duration,
        "priority_weight": priority_weight,
        "daily_impression_cap": daily_cap,
        "house_ad_status": "ACTIVE",
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": next_seq(),
    }
    store.house_ads[rec["id"]] = rec
    return created(ser_house_ad(rec))


@bp.route("/v1/house-ads", methods=["GET"])
def list_house_ads():
    caller()
    recs = list(store.house_ads.values())
    fc = request.args.get("channel_id")
    fs = request.args.get("house_ad_status")
    if fc is not None:
        recs = [r for r in recs if r["channel_id"] == fc]
    if fs is not None:
        recs = [r for r in recs if r["house_ad_status"] == fs]
    return paginate(recs, ser_house_ad)


@bp.route("/v1/house-ads/<house_ad_id>", methods=["GET"])
def get_house_ad(house_ad_id):
    caller()
    rec = get_or_404(store.house_ads, house_ad_id, "HouseAd")
    return ok(ser_house_ad(rec))


@bp.route("/v1/house-ads/<house_ad_id>", methods=["PATCH"])
def patch_house_ad(house_ad_id):
    _, role = caller()
    b = body()
    target = b.get("target_status")
    if not isinstance(target, str) or target not in ("ACTIVE", "PAUSED", "RETIRED"):
        raise_err(ERR_INVALID_REQUEST, "target_status must be one of ACTIVE, PAUSED, RETIRED")
    require_roles(role, ADOPS)
    rec = get_or_404(store.house_ads, house_ad_id, "HouseAd")
    if (rec["house_ad_status"], target) not in PATCH_TRANSITIONS:
        raise_err(
            ERR_INVALID_STATE_TRANSITION,
            "House ad in %s cannot transition to %s" % (rec["house_ad_status"], target),
        )
    rec["house_ad_status"] = target
    touch(rec)
    return ok(ser_house_ad(rec))
