"""Clock, labels (with sweep), and artists."""

from datetime import datetime, timedelta, timezone

from flask import Blueprint, request

from db import db, today
from errors import raise_err
from helpers import (
    get_body, make_entity, touch, serialize, get_or_404, list_page,
    apply_filters, parse_date, v_str, v_int, v_num, v_enum, v_date,
)
from middleware import auth, check_ownership
from response import ok, ok_list
from services.calc import compute_scouting_score
from services.domain import (
    OPEN_MEMO_STATES, maybe_revert_artist_to_scouted, label_of_artist,
)

bp = Blueprint("labels_artists", __name__)

GENRES = ["POP", "HIPHOP", "ROCK", "ELECTRONIC", "OTHER"]

DEFAULT_GENRE_MULTIPLIERS = {"POP": 1.10, "HIPHOP": 1.05, "ROCK": 1.00, "ELECTRONIC": 0.95, "OTHER": 0.90}
DEFAULT_CHANNEL_DEDUCTION_BPS = {"STREAMING": 3000, "DOWNLOAD": 1500, "PHYSICAL": 2500, "SYNC": 0}
DEFAULT_TIER_THRESHOLDS = [
    {"units": 0, "delta_bps": 0},
    {"units": 500000, "delta_bps": 200},
    {"units": 2000000, "delta_bps": 300},
]
DEFAULT_TOUR_CATEGORY_CAPS_BPS = {"TRAVEL": 5000, "LODGING": 3000, "PRODUCTION": 4000, "MISC": 1000}


# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------

@bp.post("/api/_clock/set_current_utc")
def set_clock():
    auth(["LabelAdmin"])
    body = get_body()
    to_iso = v_str(body, "to_iso8601")
    parsed = None
    if isinstance(to_iso, str):
        candidate = to_iso.strip()
        if candidate.endswith("Z"):
            candidate = candidate[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(candidate)
        except ValueError:
            parsed = None
    if parsed is None:
        raise_err("ERR_INVALID_REQUEST", "to_iso8601 must be an ISO 8601 timestamp")
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    db.clock = parsed.astimezone(timezone.utc)
    current = db.clock.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (db.clock.microsecond // 1000)
    return ok({"current_utc": current})


# ---------------------------------------------------------------------------
# Labels
# ---------------------------------------------------------------------------

def _validate_bps_map(body, name):
    val = body.get(name)
    if val is None:
        return None
    if not isinstance(val, dict):
        raise_err("ERR_INVALID_REQUEST", "%s must be an object" % name)
    for k, v in val.items():
        if not isinstance(k, str) or isinstance(v, bool) or not isinstance(v, int) or v < 0 or v > 10000:
            raise_err("ERR_INVALID_REQUEST", "%s entries must be integer bps" % name)
    return val


def _validate_multiplier_map(body, name):
    val = body.get(name)
    if val is None:
        return None
    if not isinstance(val, dict):
        raise_err("ERR_INVALID_REQUEST", "%s must be an object" % name)
    for k, v in val.items():
        if not isinstance(k, str) or isinstance(v, bool) or not isinstance(v, (int, float)) or v < 0:
            raise_err("ERR_INVALID_REQUEST", "%s entries must be non-negative numbers" % name)
    return val


def _validate_tier_thresholds(body):
    val = body.get("tier_thresholds")
    if val is None:
        return None
    if not isinstance(val, list):
        raise_err("ERR_INVALID_REQUEST", "tier_thresholds must be an array")
    for item in val:
        if not isinstance(item, dict):
            raise_err("ERR_INVALID_REQUEST", "tier_thresholds entries must be objects")
        units = item.get("units")
        delta = item.get("delta_bps")
        if (isinstance(units, bool) or not isinstance(units, int) or units < 0
                or isinstance(delta, bool) or not isinstance(delta, int) or delta < 0):
            raise_err("ERR_INVALID_REQUEST", "tier_thresholds entries need non-negative units/delta_bps")
    return [{"units": t["units"], "delta_bps": t["delta_bps"]} for t in val]


@bp.post("/api/labels")
def create_label():
    auth(["LabelAdmin"])
    body = get_body()
    name = v_str(body, "name")
    advance_cap = v_int(body, "advance_cap_cents", required=False, min_v=0)
    reserve_rate = v_int(body, "reserve_rate_bps", required=False, min_v=0, max_v=10000)
    sign_threshold = v_num(body, "sign_threshold_score", required=False, min_v=0)
    option_window_days = v_int(body, "option_window_days", required=False, min_v=0)
    release_lead_days = v_int(body, "release_lead_days", required=False, min_v=0)
    beat_pre = v_int(body, "beat_pre_release_days", required=False, min_v=0)
    beat_post = v_int(body, "beat_post_release_days", required=False, min_v=0)
    campaign_gap = v_int(body, "campaign_gap_days", required=False, min_v=0)

    genre_mult = DEFAULT_GENRE_MULTIPLIERS
    override = _validate_multiplier_map(body, "genre_multipliers")
    if override is not None:
        genre_mult = {**DEFAULT_GENRE_MULTIPLIERS, **override}
    channel_ded = DEFAULT_CHANNEL_DEDUCTION_BPS
    override = _validate_bps_map(body, "channel_deduction_bps")
    if override is not None:
        channel_ded = {**DEFAULT_CHANNEL_DEDUCTION_BPS, **override}
    tour_caps = DEFAULT_TOUR_CATEGORY_CAPS_BPS
    override = _validate_bps_map(body, "tour_category_caps_bps")
    if override is not None:
        tour_caps = {**DEFAULT_TOUR_CATEGORY_CAPS_BPS, **override}
    tiers = _validate_tier_thresholds(body)
    if tiers is None:
        tiers = [dict(t) for t in DEFAULT_TIER_THRESHOLDS]

    label = make_entity({
        "name": name,
        "advance_cap_cents": advance_cap if advance_cap is not None else 5000000,
        "reserve_rate_bps": reserve_rate if reserve_rate is not None else 1000,
        "sign_threshold_score": sign_threshold if sign_threshold is not None else 40.0,
        "option_window_days": option_window_days if option_window_days is not None else 90,
        "release_lead_days": release_lead_days if release_lead_days is not None else 21,
        "beat_pre_release_days": beat_pre if beat_pre is not None else 42,
        "beat_post_release_days": beat_post if beat_post is not None else 30,
        "campaign_gap_days": campaign_gap if campaign_gap is not None else 7,
        "genre_multipliers": genre_mult,
        "channel_deduction_bps": channel_ded,
        "tier_thresholds": tiers,
        "tour_category_caps_bps": tour_caps,
    })
    db.labels[label["id"]] = label
    return ok(serialize(label), code=201)


@bp.get("/api/labels/<lid>")
def get_label(lid):
    auth(["LabelAdmin", "AnRManager", "FinanceController", "MarketingManager", "ArtistPortal"])
    label = get_or_404(db.labels, lid)
    return ok(serialize(label))


@bp.post("/api/labels/<lid>/ops/sweep")
def sweep(lid):
    auth(["LabelAdmin"])
    label = get_or_404(db.labels, lid)
    get_body()
    now = today()

    label_artist_ids = {a["id"] for a in db.artists.values() if a["label_id"] == lid}

    expired_memo_ids = []
    for memo in sorted(db.deal_memos.values(), key=lambda m: m["_seq"]):
        if memo["artist_id"] not in label_artist_ids:
            continue
        if memo["status"] not in OPEN_MEMO_STATES:
            continue
        if memo.get("_valid_until") is not None and now > memo["_valid_until"]:
            memo["status"] = "EXPIRED"
            touch(memo)
            expired_memo_ids.append(memo["id"])
            maybe_revert_artist_to_scouted(db.artists.get(memo["artist_id"]))

    window_entered = []
    expired_contracts = []
    for contract in sorted(db.contracts.values(), key=lambda c: c["_seq"]):
        if contract["artist_id"] not in label_artist_ids:
            continue
        status = contract["status"]
        end = contract.get("_current_term_end_date")
        if end is None:
            continue
        if status in ("ACTIVE", "OPTION_WINDOW", "EXTENDED") and now > end:
            contract["status"] = "EXPIRED"
            touch(contract)
            expired_contracts.append(contract["id"])
        elif (
            status in ("ACTIVE", "EXTENDED")
            and now >= end - timedelta(days=label["option_window_days"])
            and now <= end
            and contract["options_exercised"] < contract["options_total"]
        ):
            contract["status"] = "OPTION_WINDOW"
            touch(contract)
            window_entered.append(contract["id"])

    return ok({
        "expired_deal_memo_ids": expired_memo_ids,
        "window_entered_contract_ids": window_entered,
        "expired_contract_ids": expired_contracts,
    })


# ---------------------------------------------------------------------------
# Artists
# ---------------------------------------------------------------------------

@bp.post("/api/artists")
def create_artist():
    auth(["AnRManager"])
    body = get_body()
    label_id = v_str(body, "label_id")
    label = db.labels.get(label_id)
    if label is None:
        raise_err("ERR_NOT_FOUND", "label_id does not reference an existing label")
    stage_name = v_str(body, "stage_name")
    genre = v_enum(body, "genre", GENRES)
    birth_date = v_date(body, "birth_date")
    monthly_streams = v_int(body, "monthly_streams", min_v=0)
    social_followers = v_int(body, "social_followers", min_v=0)
    engagement_rate = v_num(body, "engagement_rate", min_v=0, max_v=1)
    live_draw_avg = v_int(body, "live_draw_avg", min_v=0)

    score = compute_scouting_score(
        label, genre, monthly_streams, social_followers, engagement_rate, live_draw_avg
    )
    artist = make_entity({
        "label_id": label_id,
        "stage_name": stage_name,
        "genre": genre,
        "birth_date": birth_date,
        "monthly_streams": monthly_streams,
        "social_followers": social_followers,
        "engagement_rate": engagement_rate,
        "live_draw_avg": live_draw_avg,
        "scouting_score": score,
        "status": "SCOUTED",
        "pre_hiatus_status": None,
        "_birth_date": parse_date(birth_date),
    })
    db.artists[artist["id"]] = artist
    return ok(serialize(artist), code=201)


@bp.get("/api/artists/<aid>")
def get_artist(aid):
    uid, role = auth(["LabelAdmin", "AnRManager", "FinanceController", "MarketingManager", "ArtistPortal"])
    artist = get_or_404(db.artists, aid)
    check_ownership(role, uid, artist["id"])
    return ok(serialize(artist))


@bp.get("/api/artists")
def list_artists():
    auth(["LabelAdmin", "AnRManager", "FinanceController", "MarketingManager"])
    items = apply_filters(db.artists.values(), [
        ("label_id", lambda a: a["label_id"]),
        ("status", lambda a: a["status"]),
        ("genre", lambda a: a["genre"]),
    ])
    data, pagination = list_page(items)
    return ok_list(data, pagination)


@bp.post("/api/artists/<aid>/hiatus")
def artist_hiatus(aid):
    auth(["AnRManager"])
    get_body()
    artist = get_or_404(db.artists, aid)
    if artist["status"] not in ("SIGNED", "ACTIVE"):
        raise_err("ERR_INVALID_STATE", "Only SIGNED or ACTIVE artists may enter HIATUS")
    artist["pre_hiatus_status"] = artist["status"]
    artist["status"] = "HIATUS"
    touch(artist)
    return ok(serialize(artist))


@bp.post("/api/artists/<aid>/reactivate")
def artist_reactivate(aid):
    auth(["AnRManager"])
    get_body()
    artist = get_or_404(db.artists, aid)
    if artist["status"] != "HIATUS":
        raise_err("ERR_INVALID_STATE", "Only HIATUS artists may be reactivated")
    artist["status"] = artist["pre_hiatus_status"]
    artist["pre_hiatus_status"] = None
    touch(artist)
    return ok(serialize(artist))


@bp.post("/api/artists/<aid>/drop")
def artist_drop(aid):
    auth(["LabelAdmin"])
    get_body()
    artist = get_or_404(db.artists, aid)
    if artist["status"] not in ("SIGNED", "ACTIVE", "HIATUS"):
        raise_err("ERR_INVALID_STATE", "Artist cannot be dropped from %s" % artist["status"])
    for contract in db.contracts.values():
        if contract["artist_id"] == aid and contract["status"] not in ("EXPIRED", "TERMINATED"):
            raise_err("ERR_INVALID_STATE", "Artist has non-terminal contracts")
    artist["status"] = "DROPPED"
    touch(artist)
    return ok(serialize(artist))
