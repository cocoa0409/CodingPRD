"""Clock, ops run, farms, houses."""
from flask import Blueprint, request

from db import STORE, CLOCK, new_record, today, now_dt
from errors import ApiError, ERR_VALIDATION, not_found
from middleware import endpoint, ALL_ROLES
from response import ok, paginate, pub
from util import parse_instant, req_str, req_int, req_enum
from services.domain import get_entity
from services.ops_run import run_daily_ops

bp = Blueprint("core", __name__)

CERT_PROGRAMS = {"CONVENTIONAL", "CAGE_FREE", "PASTURE"}
ENV_TYPES = {"CAGED", "AVIARY", "PASTURE_RANGE"}


def _body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ApiError(ERR_VALIDATION, 400, "Request body must be a JSON object")
    return data


# ---------------------------------------------------------------------------
# Test-driving: logical clock + daily ops run
# ---------------------------------------------------------------------------
@bp.route("/_clock/set_current_utc", methods=["POST"])
@endpoint(["PlatformAdmin"])
def set_clock(actor):
    body = _body()
    dt = parse_instant(body.get("to_iso8601"))
    if dt is None:
        raise ApiError(ERR_VALIDATION, 400, "to_iso8601 must be an ISO 8601 instant")
    CLOCK["dt"] = dt
    CLOCK["raw"] = body["to_iso8601"] if isinstance(body.get("to_iso8601"), str) else dt.isoformat()
    return ok({"current_utc": CLOCK["raw"]}, status=200)


@bp.route("/api/ops/run-daily", methods=["POST"])
@endpoint(["PlatformAdmin"])
def ops_run_daily(actor):
    return ok(run_daily_ops(), status=200)


# ---------------------------------------------------------------------------
# Farms
# ---------------------------------------------------------------------------
@bp.route("/api/farms", methods=["POST"])
@endpoint(["PlatformAdmin"])
def create_farm(actor):
    body = _body()
    name = req_str(body, "name")
    program = req_enum(body, "certification_program", CERT_PROGRAMS)
    overhead = req_int(body, "daily_overhead_cents", min_v=0)
    rec = new_record()
    rec.update({
        "name": name,
        "certification_program": program,
        "daily_overhead_cents": overhead,
        "compliance_posture": "CLEAR",
    })
    STORE["farms"][rec["id"]] = rec
    return ok(_farm_out(rec), status=201)


def _farm_out(rec):
    from services.domain import farm_active_flock_count
    out = pub(rec)
    out["active_flock_count"] = farm_active_flock_count(rec)
    return out


@bp.route("/api/farms/<farmId>", methods=["GET"])
@endpoint(ALL_ROLES)
def get_farm(farmId, actor):
    farm = get_entity("farms", farmId, "Farm")
    return ok(_farm_out(farm), status=200)


# ---------------------------------------------------------------------------
# Houses
# ---------------------------------------------------------------------------
@bp.route("/api/houses", methods=["POST"])
@endpoint(["PlatformAdmin", "FarmManager"])
def create_house(actor):
    body = _body()
    # Tier 4: body FK existence (farm_id) before tier 5 schema details.
    farm_id = body.get("farm_id")
    if isinstance(farm_id, str) and farm_id:
        get_entity("farms", farm_id, "Farm")
    farm_id = req_str(body, "farm_id")
    get_entity("farms", farm_id, "Farm")
    house_code = req_str(body, "house_code")
    env = req_enum(body, "environment_type", ENV_TYPES)
    capacity = req_int(body, "capacity_hens", min_v=1)
    for h in STORE["houses"].values():
        if h["farm_id"] == farm_id and h["house_code"] == house_code:
            raise ApiError(ERR_VALIDATION, 400, "house_code must be unique within the farm")
    rec = new_record()
    rec.update({
        "farm_id": farm_id,
        "house_code": house_code,
        "environment_type": env,
        "capacity_hens": capacity,
        "status": "EMPTY",
        "status_changed_date": today(),
        "current_flock_id": None,
    })
    STORE["houses"][rec["id"]] = rec
    return ok(pub(rec), status=201)


@bp.route("/api/houses/<houseId>", methods=["GET"])
@endpoint(ALL_ROLES)
def get_house(houseId, actor):
    return ok(pub(get_entity("houses", houseId, "House")), status=200)


@bp.route("/api/houses", methods=["GET"])
@endpoint(ALL_ROLES)
def list_houses(actor):
    items = list(STORE["houses"].values())
    farm_id = request.args.get("farm_id")
    status = request.args.get("status")
    if farm_id is not None:
        items = [h for h in items if h["farm_id"] == farm_id]
    if status is not None:
        items = [h for h in items if h["status"] == status]
    items.sort(key=lambda h: (h["created_at"], h["_seq"]))
    return paginate(items, pub)
