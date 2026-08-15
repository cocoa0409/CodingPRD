"""Flocks: placement, age/molt/depopulation lifecycle, economics read."""
from datetime import timedelta

from flask import Blueprint, request

from db import STORE, new_record, today, touch
from errors import (
    ApiError, ERR_VALIDATION, ERR_HOUSE_NOT_EMPTY, ERR_FARM_SUSPENDED,
    ERR_UNRESOLVED_POSITIVE, ERR_MOLT_AGE_INELIGIBLE, ERR_MOLT_LIMIT_REACHED,
    ERR_MOLT_REST_TOO_SHORT, ERR_INVALID_STATE,
)
from middleware import endpoint, ALL_ROLES
from response import ok, paginate, pub
from util import req_str, req_int, req_num, req_date, parse_date
from services.domain import (
    get_entity, serialize_flock, flock_age_weeks, farm_of_flock,
    MOLT_MIN_AGE_WEEKS, MAX_MOLTS, MOLT_REST_MIN_DAYS,
)
from services.pricing import (
    feed_conversion_ratio, cost_per_dozen_actual, cost_per_dozen_projected,
)

bp = Blueprint("flocks", __name__)

FM = ["FarmManager"]


def _body():
    from flask import request as _r
    data = _r.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ApiError(ERR_VALIDATION, 400, "Request body must be a JSON object")
    return data


def _get_flock(flockId):
    return get_entity("flocks", flockId, "Flock")


# ---------------------------------------------------------------------------
# Placement
# ---------------------------------------------------------------------------
@bp.route("/api/flocks", methods=["POST"])
@endpoint(FM)
def create_flock(actor):
    body = _body()
    # Tier 4: body FK existence before schema details.
    house_id = body.get("house_id")
    if isinstance(house_id, str) and house_id:
        get_entity("houses", house_id, "House")
    house_id = req_str(body, "house_id")
    house = get_entity("houses", house_id, "House")
    # Tier 5: schema.
    breed_code = req_str(body, "breed_code")
    peak = req_num(body, "breed_peak_rate_pct")
    placement_date = req_date(body, "placement_date")
    if placement_date > today():
        raise ApiError(ERR_VALIDATION, 400, "placement_date must not be later than the clock date")
    hens = req_int(body, "initial_hen_count", min_v=1)
    if hens > house["capacity_hens"]:
        raise ApiError(ERR_VALIDATION, 400, "initial_hen_count exceeds house capacity_hens")
    pullet_cost = req_int(body, "pullet_cost_cents", min_v=0)
    # Tier 8: house must be EMPTY.
    if house["status"] != "EMPTY":
        raise ApiError(ERR_HOUSE_NOT_EMPTY, 409, "House is not EMPTY")
    # Self-referential link: house's most recently DEPLETED flock.
    depleted = [
        f for f in STORE["flocks"].values()
        if f["house_id"] == house["id"] and f["status"] == "DEPLETED"
    ]
    prior_id = None
    if depleted:
        depleted.sort(key=lambda f: (f["created_at"], f["_seq"]))
        latest_date = max(f["depleted_date"] for f in depleted)
        prior_id = next(f for f in depleted if f["depleted_date"] == latest_date)["id"]
    rec = new_record()
    rec.update({
        "house_id": house["id"],
        "breed_code": breed_code,
        "breed_peak_rate_pct": peak,
        "placement_date": placement_date,
        "initial_hen_count": hens,
        "pullet_cost_cents": pullet_cost,
        "prior_flock_id": prior_id,
        "depleted_date": None,
        "lay_cycle": "FIRST",
        "molt_count": 0,
        "molt_started_date": None,
        "status": "PLACED",
        "quarantine_status": "CLEAR",
    })
    STORE["flocks"][rec["id"]] = rec
    # Cascade: house EMPTY -> OCCUPIED.
    house["status"] = "OCCUPIED"
    house["current_flock_id"] = rec["id"]
    house["status_changed_date"] = today()
    touch(house)
    return ok(pub(serialize_flock(rec)), status=201)


@bp.route("/api/flocks/<flockId>", methods=["GET"])
@endpoint(ALL_ROLES)
def get_flock(flockId, actor):
    return ok(pub(serialize_flock(_get_flock(flockId))), status=200)


@bp.route("/api/flocks", methods=["GET"])
@endpoint(ALL_ROLES)
def list_flocks(actor):
    items = list(STORE["flocks"].values())
    house_id = request.args.get("house_id")
    prior = request.args.get("prior_flock_id")
    status = request.args.get("status")
    if house_id is not None:
        items = [f for f in items if f["house_id"] == house_id]
    if prior is not None:
        items = [f for f in items if f.get("prior_flock_id") == prior]
    if status is not None:
        items = [f for f in items if f["status"] == status]
    items.sort(key=lambda f: (f["created_at"], f["_seq"]))
    return paginate(items, lambda f: pub(serialize_flock(f)))


# ---------------------------------------------------------------------------
# Lifecycle actions
# ---------------------------------------------------------------------------
@bp.route("/api/flocks/<flockId>/induce-molt", methods=["POST"])
@endpoint(FM)
def induce_molt(flockId, actor):
    flock = _get_flock(flockId)
    # Tier 6: own state machine.
    if flock["status"] != "LAYING":
        raise ApiError(ERR_INVALID_STATE, 409, "Flock must be LAYING to induce molt")
    # Tier 9: quarantine gate.
    if flock["quarantine_status"] != "CLEAR":
        raise ApiError(ERR_UNRESOLVED_POSITIVE, 409, "Flock is quarantined")
    # Tier 10: age >= 60 (exactly 60 eligible).
    if flock_age_weeks(flock) < MOLT_MIN_AGE_WEEKS:
        raise ApiError(ERR_MOLT_AGE_INELIGIBLE, 422, "Flock age_weeks below 60")
    # Tier 11: molt cap.
    if flock["molt_count"] >= MAX_MOLTS:
        raise ApiError(ERR_MOLT_LIMIT_REACHED, 422, "Flock has already completed a molt")
    flock["status"] = "MOLT_REST"
    flock["molt_started_date"] = today()
    touch(flock)
    return ok(pub(serialize_flock(flock)), status=200)


@bp.route("/api/flocks/<flockId>/resume-lay", methods=["POST"])
@endpoint(FM)
def resume_lay(flockId, actor):
    flock = _get_flock(flockId)
    if flock["status"] != "MOLT_REST":
        raise ApiError(ERR_INVALID_STATE, 409, "Flock must be in MOLT_REST to resume lay")
    if today() < flock["molt_started_date"] + timedelta(days=MOLT_REST_MIN_DAYS):
        raise ApiError(ERR_MOLT_REST_TOO_SHORT, 422, "Molt rest shorter than 14 days")
    flock["status"] = "LAYING"
    flock["molt_count"] += 1
    flock["lay_cycle"] = "SECOND"
    touch(flock)
    return ok(pub(serialize_flock(flock)), status=200)


@bp.route("/api/flocks/<flockId>/depopulate", methods=["POST"])
@endpoint(FM)
def depopulate(flockId, actor):
    flock = _get_flock(flockId)
    if flock["status"] not in ("LAYING", "MOLT_REST"):
        raise ApiError(ERR_INVALID_STATE, 409, "Flock must be LAYING or MOLT_REST to depopulate")
    flock["status"] = "DEPOPULATING"
    touch(flock)
    house = STORE["houses"].get(flock["house_id"])
    if house is not None and house["status"] == "OCCUPIED":
        house["status"] = "DEPOPULATING"
        house["status_changed_date"] = today()
        touch(house)
    return ok(pub(serialize_flock(flock)), status=200)


# ---------------------------------------------------------------------------
# Economics (computed read)
# ---------------------------------------------------------------------------
@bp.route("/api/flocks/<flockId>/economics", methods=["GET"])
@endpoint(["PlatformAdmin", "FarmManager", "ContractManager"])
def flock_economics(flockId, actor):
    flock = _get_flock(flockId)
    ps_raw = request.args.get("period_start")
    pe_raw = request.args.get("period_end")
    variant = request.args.get("variant") or "ACTUAL_FIFO"
    if variant not in ("ACTUAL_FIFO", "PROJECTED_STANDARD"):
        raise ApiError(ERR_VALIDATION, 400, "variant must be ACTUAL_FIFO or PROJECTED_STANDARD")
    period_start = parse_date(ps_raw) if ps_raw is not None else None
    period_end = parse_date(pe_raw) if pe_raw is not None else None
    if period_start is None or period_end is None:
        raise ApiError(ERR_VALIDATION, 400, "period_start and period_end are required")
    if period_start > period_end:
        raise ApiError(ERR_VALIDATION, 400, "period_start must not be after period_end")
    days_in_period = (period_end - period_start).days + 1
    farm = farm_of_flock(flock)
    if variant == "ACTUAL_FIFO":
        result = cost_per_dozen_actual(flock, farm, period_start, period_end, days_in_period)
    else:
        result = cost_per_dozen_projected(flock, farm, period_start, period_end, days_in_period)
    result["feed_conversion_ratio"] = feed_conversion_ratio(flock, period_start, period_end)
    # Stable field order in output.
    out = {
        "cost_per_dozen_cents": result["cost_per_dozen_cents"],
        "feed_conversion_ratio": result["feed_conversion_ratio"],
        "total_eggs": result["total_eggs"],
        "feed_cost_cents": result["feed_cost_cents"],
        "overhead_cents": result["overhead_cents"],
        "amortization_cents": result["amortization_cents"],
        "spent_hen_credit_cents": result["spent_hen_credit_cents"],
    }
    return ok(out, status=200)
