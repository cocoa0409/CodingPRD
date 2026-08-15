"""Ops endpoints: clock, bases, aircraft, pilots, routes, seasonal capacity,
ops checkpoint (PRD 3.1, 2.5, 3.8)."""
from decimal import Decimal

from flask import Blueprint, request

from db import DB, clock_now, set_clock
from errors import ApiError
from middleware import auth, client_owner_guard
from response import ok, ok_list
from services import (
    get_aircraft,
    get_base,
    get_pilot,
    get_route,
    hours_remaining,
    new_record,
    pub,
    recompute_campaign,
    sorted_created,
    touch,
)
from util import (
    as_bool,
    as_enum,
    as_int,
    as_iso_dt,
    as_month,
    as_num,
    as_str,
    body,
    pagination_args,
    required,
)

bp = Blueprint("ops", __name__, url_prefix="/btaa")

AIRCRAFT_MODELS = {"CITABRIA", "SUPER_CUB", "PAWNEE"}
ENDORSEMENTS = {"TRAINEE", "STANDARD", "STADIUM_QUALIFIED"}
ROUTE_KINDS = {"BEACH", "STADIUM", "FESTIVAL", "PARADE"}

FLEET_READ = ["PlatformAdmin", "Dispatcher", "GroundCrewLead", "ComplianceOfficer", "FinanceOfficer"]


def _list(recs, filters):
    items = sorted_created(recs)
    for key, val in filters.items():
        if val is not None:
            items = [r for r in items if r.get(key) == val]
    limit, offset = pagination_args()
    total = len(items)
    page = items[offset : offset + limit]
    return ok_list([pub(r) for r in page], total, limit, offset)


# ---------------------------------------------------------------------------
# Logical clock (test-driving)
# ---------------------------------------------------------------------------
@bp.post("/_clock/set_current_utc")
def set_current_utc():
    auth(["PlatformAdmin"])
    data = body()
    raw, dt = as_iso_dt(required(data, "to_iso8601"), "to_iso8601")
    set_clock(dt)
    return ok({"current_utc": raw})


# ---------------------------------------------------------------------------
# Bases
# ---------------------------------------------------------------------------
@bp.post("/bases")
def create_base():
    auth(["PlatformAdmin"])
    data = body()
    code = as_str(required(data, "code"), "code")
    name = as_str(required(data, "name"), "name")
    rec = new_record()
    rec.update({"code": code, "name": name, "status": "ACTIVE"})
    DB["bases"][rec["id"]] = rec
    return ok(pub(rec), status=201)


@bp.get("/bases/<bid>")
def get_one_base(bid):
    auth(FLEET_READ)
    return ok(pub(get_base(bid)))


# ---------------------------------------------------------------------------
# Aircraft
# ---------------------------------------------------------------------------
@bp.post("/bases/<bid>/aircraft")
def create_aircraft(bid):
    auth(["PlatformAdmin"])
    base = get_base(bid)
    data = body()
    tail = as_str(required(data, "tail_number"), "tail_number")
    model = as_enum(required(data, "model"), "model", AIRCRAFT_MODELS)
    max_tow = as_int(required(data, "max_tow_weight_lbs"), "max_tow_weight_lbs")
    rate = as_int(required(data, "hourly_rate_cents"), "hourly_rate_cents")
    rec = new_record()
    rec.update(
        {
            "base_id": base["id"],
            "tail_number": tail,
            "model": model,
            "max_tow_weight_lbs": max_tow,
            "hourly_rate_cents": rate,
            "status": "ACTIVE",
            "season_hours_flown": 0.0,
            "_season_hours": Decimal(0),
        }
    )
    DB["aircraft"][rec["id"]] = rec
    return ok(pub(rec), status=201)


@bp.get("/bases/<bid>/aircraft")
def list_aircraft(bid):
    auth(FLEET_READ + ["Client"])
    base = get_base(bid)
    recs = [a for a in DB["aircraft"].values() if a["base_id"] == base["id"]]
    return _list(recs, {"status": request.args.get("status")})


@bp.get("/aircraft/<aid>")
def get_one_aircraft(aid):
    auth(FLEET_READ)
    return ok(pub(get_aircraft(aid)))


@bp.post("/aircraft/<aid>/ground")
def ground_aircraft(aid):
    auth(["GroundCrewLead", "PlatformAdmin"])
    a = get_aircraft(aid)
    if a["status"] != "ACTIVE":
        raise ApiError(
            "ERR_INVALID_STATE", 409, "Aircraft is not in a state permitting ground"
        )
    a["status"] = "MAINTENANCE"
    touch(a)
    # Cascade: every SCHEDULED slot assigned to this aircraft reverts to
    # BOOKED with its assigned_aircraft_id cleared (PRD 3.1).
    for s in DB["flight_slots"].values():
        if s.get("assigned_aircraft_id") == a["id"] and s["status"] == "SCHEDULED":
            s["status"] = "BOOKED"
            s["assigned_aircraft_id"] = None
            touch(s)
            camp = DB["campaigns"].get(s["campaign_id"])
            if camp:
                recompute_campaign(camp)
    return ok(pub(a))


@bp.post("/aircraft/<aid>/return_to_service")
def return_aircraft(aid):
    auth(["GroundCrewLead", "PlatformAdmin"])
    a = get_aircraft(aid)
    if a["status"] != "MAINTENANCE":
        raise ApiError(
            "ERR_INVALID_STATE",
            409,
            "Aircraft is not in a state permitting return_to_service",
        )
    a["status"] = "ACTIVE"
    touch(a)
    return ok(pub(a))


@bp.post("/aircraft/<aid>/retire")
def retire_aircraft(aid):
    auth(["PlatformAdmin"])
    a = get_aircraft(aid)
    if a["status"] != "ACTIVE":
        raise ApiError(
            "ERR_INVALID_STATE", 409, "Aircraft is not in a state permitting retire"
        )
    for s in DB["flight_slots"].values():
        if s.get("assigned_aircraft_id") == a["id"] and s["status"] == "SCHEDULED":
            raise ApiError(
                "ERR_INVALID_STATE",
                409,
                "Aircraft has SCHEDULED slots assigned",
            )
    a["status"] = "RETIRED"
    touch(a)
    return ok(pub(a))


# ---------------------------------------------------------------------------
# Pilots
# ---------------------------------------------------------------------------
@bp.post("/bases/<bid>/pilots")
def create_pilot(bid):
    auth(["PlatformAdmin"])
    base = get_base(bid)
    data = body()
    full_name = as_str(required(data, "full_name"), "full_name")
    cert = as_str(required(data, "certificate_number"), "certificate_number")
    level = as_enum(
        required(data, "tow_endorsement_level"), "tow_endorsement_level", ENDORSEMENTS
    )
    rec = new_record()
    rec.update(
        {
            "base_id": base["id"],
            "full_name": full_name,
            "certificate_number": cert,
            "tow_endorsement_level": level,
            "status": "ACTIVE",
            "season_hours_flown": 0.0,
            "season_pickup_failure_count": 0,
            "_season_hours": Decimal(0),
        }
    )
    DB["pilots"][rec["id"]] = rec
    return ok(pub(rec), status=201)


@bp.get("/bases/<bid>/pilots")
def list_pilots(bid):
    auth(FLEET_READ)
    base = get_base(bid)
    recs = [p for p in DB["pilots"].values() if p["base_id"] == base["id"]]
    return _list(recs, {"status": request.args.get("status")})


@bp.get("/pilots/<pid>")
def get_one_pilot(pid):
    user_id, role = auth(FLEET_READ + ["Pilot"])
    p = get_pilot(pid)
    if role == "Pilot" and p["id"] != user_id:
        raise ApiError(
            "ERR_UNAUTHORIZED_OWNER", 403, "Pilot does not own this resource"
        )
    return ok(pub(p))


@bp.post("/pilots/<pid>/reinstate")
def reinstate_pilot(pid):
    auth(["PlatformAdmin"])
    p = get_pilot(pid)
    if p["status"] != "SUSPENDED":
        raise ApiError(
            "ERR_INVALID_STATE",
            409,
            "Pilot is not in a state permitting reinstate",
        )
    if p["season_pickup_failure_count"] >= 3:
        raise ApiError(
            "ERR_INVALID_STATE",
            409,
            "Pilot season_pickup_failure_count is not below 3",
        )
    p["status"] = "ACTIVE"
    touch(p)
    return ok(pub(p))


@bp.post("/pilots/<pid>/deactivate")
def deactivate_pilot(pid):
    auth(["PlatformAdmin"])
    p = get_pilot(pid)
    if p["status"] != "ACTIVE":
        raise ApiError(
            "ERR_INVALID_STATE",
            409,
            "Pilot is not in a state permitting deactivate",
        )
    for s in DB["flight_slots"].values():
        if s.get("assigned_pilot_id") == p["id"] and s["status"] == "SCHEDULED":
            raise ApiError(
                "ERR_INVALID_STATE", 409, "Pilot has SCHEDULED slots assigned"
            )
    p["status"] = "INACTIVE"
    touch(p)
    return ok(pub(p))


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@bp.post("/routes")
def create_route():
    auth(["PlatformAdmin"])
    data = body()
    code = as_str(required(data, "code"), "code")
    kind = as_enum(required(data, "kind"), "kind", ROUTE_KINDS)
    base = get_base(as_str(required(data, "base_id"), "base_id"))
    length_nm = as_num(required(data, "length_nm"), "length_nm")
    min_len = as_int(required(data, "min_banner_length_ft"), "min_banner_length_ft")
    rec = new_record()
    rec.update(
        {
            "code": code,
            "kind": kind,
            "base_id": base["id"],
            "length_nm": length_nm,
            "min_banner_length_ft": min_len,
            "status": "ACTIVE",
        }
    )
    DB["routes"][rec["id"]] = rec
    return ok(pub(rec), status=201)


@bp.get("/routes/<rid>")
def get_one_route(rid):
    auth(FLEET_READ + ["Client", "Pilot"])
    return ok(pub(get_route(rid)))


@bp.get("/bases/<bid>/routes")
def list_routes(bid):
    auth(FLEET_READ + ["Client", "Pilot"])
    base = get_base(bid)
    recs = [r for r in DB["routes"].values() if r["base_id"] == base["id"]]
    return _list(
        recs,
        {"kind": request.args.get("kind"), "status": request.args.get("status")},
    )


# ---------------------------------------------------------------------------
# Seasonal capacity
# ---------------------------------------------------------------------------
@bp.post("/bases/<bid>/seasonal_capacities")
def create_capacity(bid):
    auth(["PlatformAdmin"])
    base = get_base(bid)
    data = body()
    month = as_month(required(data, "month_yyyy_mm"), "month_yyyy_mm")
    quota = as_int(required(data, "aircraft_hour_quota"), "aircraft_hour_quota")
    rec = new_record()
    rec.update(
        {
            "base_id": base["id"],
            "month_yyyy_mm": month,
            "aircraft_hour_quota": quota,
            "hours_committed": 0,
        }
    )
    DB["seasonal_capacities"][rec["id"]] = rec
    out = pub(rec)
    out["hours_remaining"] = hours_remaining(rec)
    return ok(out, status=201)


CAP_READ = ["PlatformAdmin", "Dispatcher", "FinanceOfficer", "ComplianceOfficer", "Client"]


@bp.get("/bases/<bid>/seasonal_capacities")
def list_capacities(bid):
    auth(CAP_READ)
    base = get_base(bid)
    recs = [c for c in DB["seasonal_capacities"].values() if c["base_id"] == base["id"]]
    month = request.args.get("month_yyyy_mm")
    if month is not None:
        recs = [c for c in recs if c["month_yyyy_mm"] == month]
    recs = sorted_created(recs)
    limit, offset = pagination_args()
    total = len(recs)
    page = recs[offset : offset + limit]
    items = []
    for c in page:
        o = pub(c)
        o["hours_remaining"] = hours_remaining(c)
        items.append(o)
    return ok_list(items, total, limit, offset)


@bp.get("/seasonal_capacities/<cid>")
def get_one_capacity(cid):
    auth(CAP_READ)
    for c in DB["seasonal_capacities"].values():
        if c["id"] == cid:
            out = pub(c)
            out["hours_remaining"] = hours_remaining(c)
            return ok(out)
    raise ApiError("ERR_NOT_FOUND", 404, "Referenced resource does not exist")


# ---------------------------------------------------------------------------
# Ops checkpoint (PRD 3.8): expire stale MakeGoodCredits.
# ---------------------------------------------------------------------------
@bp.post("/bases/<bid>/run_ops")
def run_ops(bid):
    auth(["PlatformAdmin"])
    get_base(bid)
    today = clock_now().date()
    expired = []
    for c in sorted_created(DB["make_good_credits"].values()):
        if c["status"] in ("OPEN", "PARTIALLY_APPLIED") and c["_expires_date"] < today:
            c["status"] = "EXPIRED"
            touch(c)
            expired.append(c)
    affected = {c["campaign_id"] for c in expired}
    for cid in affected:
        camp = DB["campaigns"].get(cid)
        if camp:
            recompute_campaign(camp)
    return ok(
        {
            "expired_credit_count": len(expired),
            "expired_credit_ids": [c["id"] for c in expired],
        }
    )
