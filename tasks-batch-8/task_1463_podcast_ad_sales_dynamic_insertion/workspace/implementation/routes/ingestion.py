"""Ingestion-side endpoints: batched download pings (with the dynamic
insertion selector), impression reads, attribution-event ingest."""

from datetime import timedelta

from flask import Blueprint, request

import db
from errors import (
    err_not_found,
    err_invalid,
    err_conflict,
    ERR_EPISODE_NOT_PUBLISHED,
)
from helpers import (
    body_of,
    new_id,
    now_timestamp,
    require_string,
    require_enum,
    require_int,
    parse_dt,
)
from middleware import require_roles
from response import success_object, success_array, list_response, serialize
from services import Changes, select_line_items, ATTRIBUTION_WINDOW_DAYS

bp = Blueprint("ingestion", __name__)

USER_AGENT_CLASSES = {"HUMAN", "BOT", "UNKNOWN"}
ATTRIBUTION_KINDS = {"PROMO_CODE", "PIXEL"}
FINANCE_ROLES = {"AdOps", "Finance"}


@bp.route("/adnet/downloads", methods=["POST"])
def ingest_downloads():
    require_roles({"Ingestion"})
    body = body_of(request)

    episode_id = body.get("episode_id")
    episode = None
    if isinstance(episode_id, str):
        episode = db.episodes.get(episode_id)
        if episode is None:
            raise err_not_found(f"Episode '{episode_id}' not found")

    # State: the episode must be PUBLISHED.
    if episode is not None and episode["status"] != "PUBLISHED":
        raise err_conflict(
            ERR_EPISODE_NOT_PUBLISHED,
            f"Episode is {episode['status']}; downloads require PUBLISHED",
        )

    # Field shape (catch-all).
    episode_id = require_string(body, "episode_id")
    if episode is None:
        raise err_not_found(f"Episode '{episode_id}' not found")
    listener_key_prefix = require_string(body, "listener_key_prefix")
    count = require_int(body, "count", minimum=1, maximum=1000)
    occurred_at = body.get("occurred_at")
    occurred_dt = parse_dt(occurred_at)
    if occurred_dt is None:
        raise err_invalid("Field 'occurred_at' must be an ISO 8601 UTC timestamp")
    user_agent_class = require_enum(body, "user_agent_class", USER_AGENT_CLASSES)

    qualified_provisional = user_agent_class != "BOT"
    created = []
    provisional_new = 0
    for i in range(count):
        download = {
            "id": new_id(),
            "episode_id": episode_id,
            "listener_key": f"{listener_key_prefix}-{i}",
            "occurred_at": occurred_at,
            "user_agent_class": user_agent_class,
            "qualified_provisional": qualified_provisional,
            "qualified_final": None,
            "created_at": now_timestamp(),
            "_seq": db.next_seq(),
        }
        db.downloads[download["id"]] = download
        if qualified_provisional:
            provisional_new += 1
        # Dynamic insertion: each download carries up to slot_capacity ads.
        for li in select_line_items(episode, occurred_dt):
            impression = {
                "id": new_id(),
                "download_id": download["id"],
                "line_item_id": li["id"],
                "campaign_id": li["campaign_id"],
                "position": li["position"],
                "served_at": occurred_at,
                "billable_provisional": download["qualified_provisional"],
                "billable_final": None,
                "created_at": now_timestamp(),
                "_seq": db.next_seq(),
            }
            db.impressions[impression["id"]] = impression
        created.append(download)

    ch = Changes()
    ch.update(
        episode,
        provisional_download_count=episode["provisional_download_count"] + provisional_new,
    )
    ch.commit()
    return success_array([serialize(d) for d in created], 201)


@bp.route("/adnet/impressions/<impression_id>", methods=["GET"])
def get_impression(impression_id):
    require_roles(FINANCE_ROLES)
    impression = db.impressions.get(impression_id)
    if impression is None:
        raise err_not_found(f"Impression '{impression_id}' not found")
    return success_object(serialize(impression))


@bp.route("/adnet/impressions", methods=["GET"])
def list_impressions():
    require_roles(FINANCE_ROLES)
    items = list(db.impressions.values())
    for param in ("campaign_id", "line_item_id", "download_id"):
        value = request.args.get(param)
        if value is not None:
            items = [i for i in items if i.get(param) == value]
    return list_response(items, request.args)


@bp.route("/adnet/attribution-events", methods=["POST"])
def ingest_attribution_event():
    require_roles({"Ingestion"})
    body = body_of(request)

    campaign_id = body.get("campaign_id")
    campaign = None
    if isinstance(campaign_id, str):
        campaign = db.campaigns.get(campaign_id)
        if campaign is None:
            raise err_not_found(f"Campaign '{campaign_id}' not found")

    # Cross-reference integrity: promo_code present iff kind == PROMO_CODE.
    kind = body.get("kind")
    promo_code = body.get("promo_code")
    if kind == "PROMO_CODE":
        if not isinstance(promo_code, str) or promo_code == "":
            raise err_invalid("Field 'promo_code' is required when kind is PROMO_CODE")
    elif kind == "PIXEL":
        if promo_code is not None:
            raise err_invalid("Field 'promo_code' must be absent when kind is PIXEL")

    # Field shape (catch-all).
    campaign_id = require_string(body, "campaign_id")
    if campaign is None:
        raise err_not_found(f"Campaign '{campaign_id}' not found")
    kind = require_enum(body, "kind", ATTRIBUTION_KINDS)
    occurred_at = body.get("occurred_at")
    occurred_dt = parse_dt(occurred_at)
    if occurred_dt is None:
        raise err_invalid("Field 'occurred_at' must be an ISO 8601 UTC timestamp")

    # attribution_window: [flight_start, current flight_end + 30 days],
    # both bounds inclusive, evaluated at ingest time.
    flight_start = parse_dt(campaign["flight_start"])
    window_end = parse_dt(campaign["flight_end"]) + timedelta(days=ATTRIBUTION_WINDOW_DAYS)
    attributed = flight_start <= occurred_dt <= window_end

    event = {
        "id": new_id(),
        "campaign_id": campaign_id,
        "kind": kind,
        "promo_code": promo_code if kind == "PROMO_CODE" else None,
        "occurred_at": occurred_at,
        "attributed": attributed,
        "created_at": now_timestamp(),
        "_seq": db.next_seq(),
    }
    db.attribution_events[event["id"]] = event
    return success_object(serialize(event), 201)
