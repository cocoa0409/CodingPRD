"""Feed deliveries (FIFO queue) and production days (immutable event log)."""
from flask import Blueprint, request

from db import STORE, new_record, today, touch
from errors import (
    ApiError, ERR_VALIDATION, ERR_FLOCK_NOT_LAYING, ERR_DUPLICATE_PRODUCTION_DAY,
    ERR_HEN_COUNT_EXCEEDED, ERR_FEED_STOCK_EXHAUSTED,
)
from middleware import endpoint, ALL_ROLES
from response import ok, paginate, pub
from util import req_str, req_int, req_date, rhu
from util import D
from services.domain import (
    get_entity, farm_of_flock, flock_current_hen_count,
)

bp = Blueprint("production", __name__)

FM = ["FarmManager"]


def _body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ApiError(ERR_VALIDATION, 400, "Request body must be a JSON object")
    return data


def _feed_out(rec):
    out = pub(rec)
    out["status"] = "DEPLETED" if rec["remaining_kg"] == 0 else "ACTIVE"
    return out


# ---------------------------------------------------------------------------
# Feed deliveries
# ---------------------------------------------------------------------------
@bp.route("/api/feed-deliveries", methods=["POST"])
@endpoint(FM)
def create_feed_delivery(actor):
    body = _body()
    farm_id = body.get("farm_id")
    if isinstance(farm_id, str) and farm_id:
        get_entity("farms", farm_id, "Farm")
    farm_id = req_str(body, "farm_id")
    get_entity("farms", farm_id, "Farm")
    delivered_at = req_date(body, "delivered_at")
    qty = req_int(body, "quantity_kg", min_v=1)
    cost = req_int(body, "cost_per_kg_cents", min_v=1)
    rec = new_record()
    rec.update({
        "farm_id": farm_id,
        "delivered_at": delivered_at,
        "quantity_kg": qty,
        "cost_per_kg_cents": cost,
        "remaining_kg": qty,
    })
    STORE["feed_deliveries"][rec["id"]] = rec
    return ok(_feed_out(rec), status=201)


@bp.route("/api/feed-deliveries/<feedDeliveryId>", methods=["GET"])
@endpoint(ALL_ROLES)
def get_feed_delivery(feedDeliveryId, actor):
    return ok(_feed_out(get_entity("feed_deliveries", feedDeliveryId, "FeedDelivery")), status=200)


@bp.route("/api/feed-deliveries", methods=["GET"])
@endpoint(ALL_ROLES)
def list_feed_deliveries(actor):
    items = list(STORE["feed_deliveries"].values())
    farm_id = request.args.get("farm_id")
    status = request.args.get("status")
    if farm_id is not None:
        items = [d for d in items if d["farm_id"] == farm_id]
    if status is not None:
        items = [d for d in items if ("DEPLETED" if d["remaining_kg"] == 0 else "ACTIVE") == status]
    # FIFO order: delivered_at ASC, created_at ASC.
    items.sort(key=lambda d: (d["delivered_at"], d["created_at"], d["_seq"]))
    return paginate(items, _feed_out)


# ---------------------------------------------------------------------------
# Production days (immutable event log: id + created_at only, PRD §2.5)
# ---------------------------------------------------------------------------
@bp.route("/api/production-days", methods=["POST"])
@endpoint(FM)
def create_production_day(actor):
    body = _body()
    # Tier 4: body FK existence.
    flock_id = body.get("flock_id")
    if isinstance(flock_id, str) and flock_id:
        get_entity("flocks", flock_id, "Flock")
    flock_id = req_str(body, "flock_id")
    flock = get_entity("flocks", flock_id, "Flock")
    # Tier 5: schema.
    lay_date = req_date(body, "lay_date")
    if lay_date < flock["placement_date"]:
        raise ApiError(ERR_VALIDATION, 400, "lay_date must be on or after placement_date")
    if lay_date > today():
        raise ApiError(ERR_VALIDATION, 400, "lay_date must not be later than the clock date")
    eggs = req_int(body, "eggs_collected", min_v=0)
    rejected = req_int(body, "rejected_eggs", min_v=0)
    if rejected > eggs:
        raise ApiError(ERR_VALIDATION, 400, "rejected_eggs must not exceed eggs_collected")
    feed_kg = req_int(body, "feed_issued_kg", min_v=0)
    mortality = req_int(body, "mortality_count", min_v=0)
    # Tier 8: flock must be LAYING.
    if flock["status"] != "LAYING":
        raise ApiError(ERR_FLOCK_NOT_LAYING, 409, "Flock is not LAYING")
    # Tier 11: one production day per (flock, lay_date).
    for p in STORE["production_days"].values():
        if p["flock_id"] == flock_id and p["lay_date"] == lay_date:
            raise ApiError(ERR_DUPLICATE_PRODUCTION_DAY, 409, "Production day already exists for this flock and date")
    # Tier 11: mortality ceiling.
    hens_at_start = flock_current_hen_count(flock)
    if mortality > hens_at_start:
        raise ApiError(ERR_HEN_COUNT_EXCEEDED, 422, "mortality_count exceeds current hen count")
    # Tier 11: FIFO feed costing against the farm's queue (chronological).
    farm = farm_of_flock(flock)
    queue = [
        d for d in STORE["feed_deliveries"].values()
        if d["farm_id"] == farm["id"] and d["remaining_kg"] > 0
    ]
    queue.sort(key=lambda d: (d["delivered_at"], d["created_at"], d["_seq"]))
    if sum(d["remaining_kg"] for d in queue) < feed_kg:
        raise ApiError(ERR_FEED_STOCK_EXHAUSTED, 422, "Feed issued exceeds remaining FIFO stock")
    need = feed_kg
    feed_cost = 0
    for delivery in queue:
        if need <= 0:
            break
        take = min(need, delivery["remaining_kg"])
        feed_cost += take * delivery["cost_per_kg_cents"]
        delivery["remaining_kg"] -= take
        touch(delivery)
        need -= take
    rec = new_record(has_version=False)  # immutable: no updated_at / version
    lay_rate = rhu(D(eggs * 100) / D(hens_at_start), 2) if hens_at_start else D("0.00")
    rec.update({
        "flock_id": flock_id,
        "lay_date": lay_date,
        "eggs_collected": eggs,
        "rejected_eggs": rejected,
        "feed_issued_kg": feed_kg,
        "mortality_count": mortality,
        "hens_at_start": hens_at_start,
        "feed_cost_cents": feed_cost,
        "lay_rate_pct": float(lay_rate),
    })
    STORE["production_days"][rec["id"]] = rec
    touch(flock)  # ledger update bumps flock version (PRD §3.3)
    return ok(pub(rec), status=201)


@bp.route("/api/production-days/<productionDayId>", methods=["GET"])
@endpoint(ALL_ROLES)
def get_production_day(productionDayId, actor):
    return ok(pub(get_entity("production_days", productionDayId, "ProductionDay")), status=200)


@bp.route("/api/production-days", methods=["GET"])
@endpoint(ALL_ROLES)
def list_production_days(actor):
    items = list(STORE["production_days"].values())
    flock_id = request.args.get("flock_id")
    lay_date_raw = request.args.get("lay_date")
    if flock_id is not None:
        items = [p for p in items if p["flock_id"] == flock_id]
    if lay_date_raw is not None:
        items = [p for p in items if p["lay_date"].isoformat() == lay_date_raw]
    # Chronological: lay_date ASC.
    items.sort(key=lambda p: (p["lay_date"], p["created_at"], p["_seq"]))
    return paginate(items, pub)
