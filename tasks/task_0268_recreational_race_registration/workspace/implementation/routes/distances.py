"""Distance, Wave, PricingTier endpoints."""
from flask import Blueprint, request

from db import db, new_id
from errors import err, ERR_INVALID_REQUEST, ERR_DUPLICATE_PRICING_TIER
from middleware import auth, require_role, get_json, parse_iso
from response import object_response
from services.store import (stamp_new, serialize_distance, serialize_wave,
                            serialize_generic, paginate_and_respond)
from services.validate import (require_str, require_number, require_int, opt_int,
                               require_enum, lookup)

bp = Blueprint("distances", __name__)

DISTANCE_LABELS = {"FIVE_K", "TEN_K", "HALF_MARATHON", "MARATHON"}
TIER_NAMES = {"EARLY_BIRD", "REGULAR", "LATE"}


# ---------- Distance ----------

@bp.route("/events/<event_id>/distances", methods=["POST"])
def create_distance(event_id):
    user_id, role = auth()
    require_role(role, {"RaceDirector"})
    event = lookup(db.events, event_id, "Event")
    body = get_json()
    label = require_enum(body, "label", DISTANCE_LABELS)
    distance_km = require_number(body, "distance_km")
    capacity_total = require_int(body, "capacity_total", minimum=1)
    charity_capacity = opt_int(body, "charity_capacity", default=0, minimum=0)
    charity_min = opt_int(body, "charity_fundraising_minimum_cents", default=0, minimum=0)
    if charity_capacity > capacity_total:
        raise err(ERR_INVALID_REQUEST, "charity_capacity must be <= capacity_total")

    did = new_id()
    d = {
        "id": did,
        "event_id": event_id,
        "label": label,
        "distance_km": distance_km,
        "capacity_total": capacity_total,
        "charity_capacity": charity_capacity,
        "charity_fundraising_minimum_cents": charity_min,
    }
    stamp_new(d)
    db.distances[did] = d
    return object_response(serialize_distance(d), 201)


@bp.route("/events/<event_id>/distances", methods=["GET"])
def list_event_distances(event_id):
    user_id, role = auth()
    require_role(role, {"RaceDirector", "Participant", "PacketStaff", "TimingOfficial"})
    lookup(db.events, event_id, "Event")
    items = [d for d in db.distances.values() if d["event_id"] == event_id]
    return paginate_and_respond("distance", items, request.args)


@bp.route("/distances/<distance_id>", methods=["GET"])
def get_distance(distance_id):
    user_id, role = auth()
    require_role(role, {"RaceDirector", "Participant", "PacketStaff", "TimingOfficial"})
    d = lookup(db.distances, distance_id, "Distance")
    return object_response(serialize_distance(d), 200)


@bp.route("/distances", methods=["GET"])
def list_distances():
    user_id, role = auth()
    require_role(role, {"RaceDirector", "Participant", "PacketStaff", "TimingOfficial"})
    event_id = request.args.get("event_id")
    items = list(db.distances.values())
    if event_id is not None:
        items = [d for d in items if d["event_id"] == event_id]
    return paginate_and_respond("distance", items, request.args)


# ---------- Wave ----------

@bp.route("/distances/<distance_id>/waves", methods=["POST"])
def create_wave(distance_id):
    user_id, role = auth()
    require_role(role, {"RaceDirector"})
    d = lookup(db.distances, distance_id, "Distance")
    body = get_json()
    name = require_str(body, "name")
    start_offset = require_int(body, "start_offset_seconds")
    wave_capacity = require_int(body, "wave_capacity", minimum=1)
    corral_capacity = require_int(body, "corral_capacity", minimum=1)

    wid = new_id()
    w = {
        "id": wid,
        "distance_id": distance_id,
        "name": name,
        "start_offset_seconds": start_offset,
        "wave_capacity": wave_capacity,
        "corral_capacity": corral_capacity,
    }
    stamp_new(w)
    db.waves[wid] = w
    return object_response(serialize_wave(w), 201)


@bp.route("/distances/<distance_id>/waves", methods=["GET"])
def list_distance_waves(distance_id):
    user_id, role = auth()
    require_role(role, {"RaceDirector", "Participant", "PacketStaff", "TimingOfficial"})
    lookup(db.distances, distance_id, "Distance")
    items = [w for w in db.waves.values() if w["distance_id"] == distance_id]
    return paginate_and_respond("wave", items, request.args)


@bp.route("/waves/<wave_id>", methods=["GET"])
def get_wave(wave_id):
    user_id, role = auth()
    require_role(role, {"RaceDirector", "Participant", "PacketStaff", "TimingOfficial"})
    w = lookup(db.waves, wave_id, "Wave")
    return object_response(serialize_wave(w), 200)


@bp.route("/waves", methods=["GET"])
def list_waves():
    user_id, role = auth()
    require_role(role, {"RaceDirector", "Participant", "PacketStaff", "TimingOfficial"})
    distance_id = request.args.get("distance_id")
    items = list(db.waves.values())
    if distance_id is not None:
        items = [w for w in items if w["distance_id"] == distance_id]
    return paginate_and_respond("wave", items, request.args)


# ---------- PricingTier ----------

@bp.route("/distances/<distance_id>/pricing-tiers", methods=["POST"])
def create_pricing_tier(distance_id):
    user_id, role = auth()
    require_role(role, {"RaceDirector"})
    d = lookup(db.distances, distance_id, "Distance")
    body = get_json()
    tier_name = require_enum(body, "tier_name", TIER_NAMES)
    effective_from = require_str(body, "effective_from_utc")
    base_price = require_int(body, "base_price_cents", minimum=0)
    eff_dt = parse_iso(effective_from)

    # uniqueness of effective_from_utc within the distance (ERR_DUPLICATE_PRICING_TIER)
    for t in db.pricing_tiers.values():
        if t["distance_id"] == distance_id and t["_effective_from_dt"] == eff_dt:
            raise err(ERR_DUPLICATE_PRICING_TIER,
                      "A pricing tier with this effective_from_utc already exists on the distance")

    tid = new_id()
    t = {
        "id": tid,
        "distance_id": distance_id,
        "tier_name": tier_name,
        "effective_from_utc": effective_from,
        "base_price_cents": base_price,
        "_effective_from_dt": eff_dt,
    }
    # PricingTier carries only id + created_at (no updated_at / version)
    stamp_new(t, with_version=False)
    db.pricing_tiers[tid] = t
    return object_response(serialize_generic(t), 201)


@bp.route("/pricing-tiers/<pricing_tier_id>", methods=["GET"])
def get_pricing_tier(pricing_tier_id):
    user_id, role = auth()
    require_role(role, {"RaceDirector", "Participant", "PacketStaff", "TimingOfficial"})
    t = lookup(db.pricing_tiers, pricing_tier_id, "PricingTier")
    return object_response(serialize_generic(t), 200)


@bp.route("/pricing-tiers", methods=["GET"])
def list_pricing_tiers():
    user_id, role = auth()
    require_role(role, {"RaceDirector", "Participant", "PacketStaff", "TimingOfficial"})
    distance_id = request.args.get("distance_id")
    items = list(db.pricing_tiers.values())
    if distance_id is not None:
        items = [t for t in items if t["distance_id"] == distance_id]
    return paginate_and_respond("pricing_tier", items, request.args)
