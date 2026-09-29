"""Season roadmap container (PRD 3.1)."""
from flask import Blueprint, request

import config
import db
import resolve
import validators as v
from db import ordered, serialize
from errors import fail
from middleware import authenticate
from response import list_response, object_response, touch
from services import calc, cascades

bp = Blueprint("seasons", __name__)

READ_ROLES = (
    config.ROLE_CONTENT_PRODUCER,
    config.ROLE_ECONOMY_DESIGNER,
    config.ROLE_LIVEOPS_COMMANDER,
    config.ROLE_COMPLIANCE_OFFICER,
)


@bp.post("/seasons")
def create_season():
    authenticate(config.ROLE_CONTENT_PRODUCER)
    payload = v.body()
    code = v.req_string(payload, "code", min_len=1, max_len=16)
    title = v.req_string(payload, "title")
    starts_at = v.req_datetime(payload, "starts_at")
    ends_at = v.req_datetime(payload, "ends_at")
    if ends_at <= starts_at:
        v.bad("ends_at", "must be strictly after starts_at")
    planned_episode_count = v.req_int(payload, "planned_episode_count", minimum=1)
    target_xp_total = v.req_int(payload, "target_xp_total", minimum=1)
    pass_price_minor = v.req_int(payload, "pass_price_minor", minimum=0)

    for existing in db.db.seasons.values():
        if existing["code"] == code:
            fail("ERR_SEASON_CODE_DUPLICATE", "A season with this code already exists.")

    season = db.insert(
        db.db.seasons,
        {
            "code": code,
            "title": title,
            "starts_at": starts_at,
            "ends_at": ends_at,
            "planned_episode_count": planned_episode_count,
            "target_xp_total": target_xp_total,
            "pass_price_minor": pass_price_minor,
            "status": "PLANNED",
            "economy_health": "HEALTHY",
            "content_posture": "ON_TRACK",
            "scheduled_episode_count": 0,
            "released_episode_count": 0,
            "cadence_debt_days": 0,
            "gross_faucet_minor": 0,
            "gross_sink_minor": 0,
            "lifetime_ratio_bp": 10000,
            "pending_revenue_minor": 0,
            "settled_revenue_minor": 0,
            "live_offer_count": 0,
            "effective_sink_rate_bp": 10000,
            "active_tuning_count": 0,
            "tuning_stage_epoch": 0,
        },
    )
    return object_response(serialize(season), 201)


@bp.get("/seasons/<season_id>")
def read_season(season_id):
    authenticate(*READ_ROLES)
    season = resolve.season(season_id)
    return object_response(serialize(season))


@bp.post("/seasons/<season_id>/status")
def season_status(season_id):
    authenticate(config.ROLE_CONTENT_PRODUCER, config.ROLE_LIVEOPS_COMMANDER)
    season = resolve.season(season_id)
    payload = v.body()
    to_status = v.req_enum(payload, "to_status", config.SEASON_STATUSES)

    current = season["status"]
    if current == "PLANNED" and to_status == "LIVE":
        season["status"] = "LIVE"
        touch(season)
    elif current == "LIVE" and to_status == "CONCLUDED":
        episodes = [e for e in db.db.episodes.values() if e["season_id"] == season["id"]]
        all_at_rest = all(e["status"] in ("CONCLUDED", "ROLLED_BACK") for e in episodes)
        if not (db.now() >= season["ends_at"] or all_at_rest):
            fail(
                "ERR_SEASON_INVALID_STATE",
                "The season may not be concluded before its end instant while episodes are still open.",
            )
        cascades.conclude_season(season)
    elif current == "CONCLUDED" and to_status == "ARCHIVED":
        season_offer_ids = set(
            o["id"] for o in db.db.offers.values() if o["season_id"] == season["id"]
        )
        for purchase in db.db.purchases.values():
            if purchase["offer_id"] in season_offer_ids and purchase["status"] == "PENDING":
                fail(
                    "ERR_SEASON_INVALID_STATE",
                    "A purchase against this season is still PENDING.",
                )
        for run in db.db.monitoring_runs.values():
            if run["season_id"] == season["id"] and run["status"] not in ("CERTIFIED", "VOIDED"):
                fail(
                    "ERR_SEASON_INVALID_STATE",
                    "A monitoring run of this season has not been certified or voided.",
                )
        season["status"] = "ARCHIVED"
        touch(season)
    else:
        fail("ERR_SEASON_INVALID_STATE", "That transition does not exist from the current status.")
    return object_response(serialize(season))


@bp.get("/seasons/<season_id>/episodes")
def list_season_episodes(season_id):
    authenticate(*READ_ROLES)
    season = resolve.season(season_id)
    status = v.query_enum("status", config.EPISODE_STATUSES)
    limit, offset = v.pagination()
    rows = [e for e in db.db.episodes.values() if e["season_id"] == season["id"]]
    if status is not None:
        rows = [e for e in rows if e["status"] == status]
    records = [serialize(e) for e in ordered(rows)]
    page, total = v.paginate(records, limit, offset)
    return list_response(page, limit, offset, total)


@bp.get("/seasons/<season_id>/economy-summary")
def economy_summary(season_id):
    authenticate(*READ_ROLES)
    season = resolve.season(season_id)
    variant = request.args.get("variant")
    if variant is None:
        v.bad("variant", "is required")
    if variant not in ("EPOCH_WINDOWED", "LIFETIME_CUMULATIVE"):
        v.bad("variant", "must be one of EPOCH_WINDOWED, LIFETIME_CUMULATIVE")
    epoch_no = None
    raw_epoch = request.args.get("epoch_no")
    if raw_epoch is not None:
        try:
            epoch_no = int(raw_epoch)
        except (TypeError, ValueError):
            v.bad("epoch_no", "must be an integer")
        if epoch_no < 1:
            v.bad("epoch_no", "must be at least 1")

    if variant == "LIFETIME_CUMULATIVE":
        window_start = season["starts_at"]
        window_end = season["ends_at"]
        faucet, sink = calc.lifetime_totals(season["id"])
    else:
        window_start, window_end = _epoch_window(season, epoch_no)
        faucet, sink = calc.epoch_totals(season["id"], window_start, window_end)

    ratio = calc.ratio_bp(sink, faucet)
    data = {
        "season_id": season["id"],
        "variant": variant,
        "window_start": db.iso(window_start),
        "window_end": db.iso(window_end),
        "gross_faucet_minor": faucet,
        "gross_sink_minor": sink,
        "sink_faucet_ratio_bp": ratio,
        "health_band": calc.health_band(ratio),
        "economy_health": season["economy_health"],
        "cadence_debt_days": season["cadence_debt_days"],
        "content_posture": season["content_posture"],
        "effective_sink_rate_bp": season["effective_sink_rate_bp"],
    }
    return object_response(data)


def _epoch_window(season, epoch_no):
    runs = [r for r in db.db.monitoring_runs.values() if r["season_id"] == season["id"]]
    if epoch_no is not None:
        for run in runs:
            if run["epoch_no"] == epoch_no:
                return run["window_start"], run["window_end"]
    resolved = [r for r in runs if r["status"] in ("COMPUTED", "CERTIFIED")]
    if resolved:
        latest = max(resolved, key=lambda r: r["epoch_no"])
        return latest["window_start"], latest["window_end"]
    return season["starts_at"], db.now()
