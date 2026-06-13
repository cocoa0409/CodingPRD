"""Carpool & Vanpool Matching API — entry point and all routes.

In-memory only; the store is wiped on every process boot (no seeding).
"""
import os

from flask import Flask, request

from db import db
from errors import ApiError, err
from response import success, error_response
import calc
import core
from core import (
    require_auth, require_roles, require_ownership, stamp_new, touch, public,
    require_fields, as_int, as_number, as_bool, as_enum, as_fraction, lookup,
    paginate, sorted_by_created, recompute_trip_seats, recompute_pool_committed,
    recompute_program_consumed, recompute_member_reliability,
    recompute_member_counters, recompute_member_month_benefit,
    recompute_member_grh, reload_time_buckets, append_ledger,
    append_reliability_event, parse_iso, clock_now, RIDER_BUFFER_MIN,
    MATCH_EXPIRY_DAYS,
)

app = Flask(__name__)


# =========================================================================
# Error / envelope plumbing
# =========================================================================
@app.errorhandler(ApiError)
def handle_api_error(e):
    return error_response(e.error_id, e.http_status, e.message)


@app.errorhandler(404)
def handle_404(e):
    return error_response("ERR_NOT_FOUND", 404, "Resource not found")


@app.errorhandler(405)
def handle_405(e):
    return error_response("ERR_NOT_FOUND", 404, "Method not allowed")


@app.errorhandler(Exception)
def handle_unexpected(e):
    if isinstance(e, ApiError):
        return handle_api_error(e)
    return error_response("ERR_INVALID_REQUEST", 422, f"Unexpected error: {e}")


def body():
    if request.data and request.data.strip():
        try:
            data = request.get_json(force=True, silent=False)
        except Exception:
            raise err("ERR_INVALID_REQUEST", "Malformed JSON body")
        if data is None:
            return {}
        if not isinstance(data, dict):
            raise err("ERR_INVALID_REQUEST", "Body must be a JSON object")
        return data
    return {}


def auth():
    return require_auth(request.headers)


# =========================================================================
# Health
# =========================================================================
@app.route("/healthz", methods=["GET"])
def healthz():
    return success({}, 200)


# =========================================================================
# Serializers
# =========================================================================
def ser_program(p):
    return public(p)


def ser_member(m):
    return public(m)


def ser_generic(o):
    return public(o)


# =========================================================================
# List helper
# =========================================================================
def do_list(collection, filters):
    items = list(collection.values())
    for key, value in filters.items():
        if value is not None:
            items = [o for o in items if o.get(key) == value]
    items = sorted_by_created(items)
    total = len(items)
    limit, offset = paginate(request.args)
    page = items[offset:offset + limit]
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }
    return success([public(o) for o in page], 200, pagination=pagination)


# =========================================================================
# EmployerProgram
# =========================================================================
@app.route("/employer-programs", methods=["POST"])
def create_program():
    a = auth()
    require_roles(a, {"ProgramAdmin", "PlatformOps"})
    b = body()
    require_fields(b, ["employer_name"])
    if not isinstance(b["employer_name"], str):
        raise err("ERR_INVALID_REQUEST", "employer_name must be a string")
    p = {
        "employer_name": b["employer_name"],
        "hov_discount_pct": as_fraction(b, "hov_discount_pct"),
        "employer_match_pct": as_fraction(b, "employer_match_pct"),
        "monthly_benefit_cap_cents": as_int(b, "monthly_benefit_cap_cents", minimum=0),
        "grh_annual_cap_cents": as_int(b, "grh_annual_cap_cents", minimum=0),
        "grh_per_event_cap_cents": as_int(b, "grh_per_event_cap_cents", minimum=0),
        "grh_max_events_per_year": as_int(b, "grh_max_events_per_year",
                                          required=False, default=4, minimum=0),
        "subsidy_budget_cents": as_int(b, "subsidy_budget_cents"),
        "subsidy_consumed_cents": 0,
        "status": "ACTIVE",
    }
    stamp_new(p)
    db.employer_programs[p["id"]] = p
    return success(ser_program(p), 201)


@app.route("/employer-programs/<pid>", methods=["GET"])
def get_program(pid):
    a = auth()
    require_roles(a, {"ProgramAdmin", "PlatformOps", "Driver", "Rider"})
    p = lookup(db.employer_programs, pid, "EmployerProgram")
    return success(ser_program(p), 200)


@app.route("/employer-programs/<pid>/freeze", methods=["POST"])
def freeze_program(pid):
    a = auth()
    require_roles(a, {"ProgramAdmin", "PlatformOps"})
    p = lookup(db.employer_programs, pid, "EmployerProgram")
    if p["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Program is not ACTIVE")
    p["status"] = "FROZEN"
    touch(p)
    return success(ser_program(p), 200)


@app.route("/employer-programs/<pid>/unfreeze", methods=["POST"])
def unfreeze_program(pid):
    a = auth()
    require_roles(a, {"ProgramAdmin", "PlatformOps"})
    p = lookup(db.employer_programs, pid, "EmployerProgram")
    if p["status"] != "FROZEN":
        raise err("ERR_INVALID_STATE", "Program is not FROZEN")
    p["status"] = "ACTIVE"
    touch(p)
    return success(ser_program(p), 200)


@app.route("/employer-programs/<pid>/ledger", methods=["GET"])
def program_ledger(pid):
    a = auth()
    require_roles(a, {"ProgramAdmin", "PlatformOps"})
    lookup(db.employer_programs, pid, "EmployerProgram")
    return do_list(db.subsidy_ledger_entries, {"employer_program_id": pid})


# =========================================================================
# Member
# =========================================================================
@app.route("/members", methods=["POST"])
def create_member():
    a = auth()
    require_roles(a, {"ProgramAdmin", "PlatformOps"})
    b = body()
    require_fields(b, ["employer_program_id", "full_name", "home_zone", "work_zone"])
    lookup(db.employer_programs, b["employer_program_id"], "EmployerProgram")
    for f in ("full_name", "home_zone", "work_zone"):
        if not isinstance(b[f], str):
            raise err("ERR_INVALID_REQUEST", f"{f} must be a string")
    m = {
        "employer_program_id": b["employer_program_id"],
        "full_name": b["full_name"],
        "home_zone": b["home_zone"],
        "work_zone": b["work_zone"],
        "can_drive": as_bool(b, "can_drive", default=False),
        "wallet_balance_cents": as_int(b, "wallet_balance_cents",
                                       required=False, default=0, minimum=0),
        "completed_trip_count": 0,
        "no_show_count": 0,
        "reliability_score": 100.0,
        "month_benefit_used_cents": 0,
        "grh_year_used_cents": 0,
        "grh_year_event_count": 0,
    }
    stamp_new(m)
    db.members[m["id"]] = m
    return success(ser_member(m), 201)


@app.route("/members/<mid>", methods=["GET"])
def get_member(mid):
    a = auth()
    require_roles(a, {"ProgramAdmin", "PlatformOps", "Driver", "Rider"})
    m = lookup(db.members, mid, "Member")
    reload_time_buckets(m)
    return success(ser_member(m), 200)


@app.route("/members", methods=["GET"])
def list_members():
    a = auth()
    require_roles(a, {"ProgramAdmin", "PlatformOps"})
    return do_list(db.members, {"employer_program_id": request.args.get("employer_program_id")})


@app.route("/members/<mid>/reliability", methods=["GET"])
def member_reliability(mid):
    a = auth()
    require_roles(a, {"ProgramAdmin", "PlatformOps", "Driver", "Rider"})
    m = lookup(db.members, mid, "Member")
    mode = request.args.get("mode", "confirmed")
    if mode not in ("confirmed", "provisional"):
        raise err("ERR_INVALID_REQUEST", "mode must be confirmed or provisional")
    if mode == "provisional":
        deltas = core.member_reliability_deltas(mid)
        pending = sum(
            1 for r in db.reservations.values()
            if r["rider_member_id"] == mid and r["reservation_status"] == "RESERVED"
        )
        view = dict(m)
        view["reliability_score"] = calc.reliability_score(deltas, provisional_pending=pending)
        return success(public(view), 200)
    return success(ser_member(m), 200)


@app.route("/members/<mid>/wallet/adjustments", methods=["POST"])
def wallet_adjust(mid):
    a = auth()
    require_roles(a, {"PlatformOps", "ProgramAdmin"})
    m = lookup(db.members, mid, "Member")
    b = body()
    amount = as_int(b, "amount_cents")
    new_balance = m["wallet_balance_cents"] + amount
    if new_balance < 0:
        new_balance = 0
    m["wallet_balance_cents"] = new_balance
    touch(m)
    return success(ser_member(m), 200)


# =========================================================================
# Vehicle
# =========================================================================
@app.route("/vehicles", methods=["POST"])
def create_vehicle():
    a = auth()
    require_roles(a, {"Driver", "PlatformOps"})
    b = body()
    require_fields(b, ["owner_member_id", "plate", "seat_capacity"])
    owner = lookup(db.members, b["owner_member_id"], "Member")
    require_ownership(a, owner["id"])
    if not isinstance(b["plate"], str):
        raise err("ERR_INVALID_REQUEST", "plate must be a string")
    v = {
        "owner_member_id": owner["id"],
        "plate": b["plate"],
        "seat_capacity": as_int(b, "seat_capacity", minimum=1),
        "hov_eligible": as_bool(b, "hov_eligible", default=True),
    }
    stamp_new(v)
    db.vehicles[v["id"]] = v
    return success(ser_generic(v), 201)


@app.route("/vehicles/<vid>", methods=["GET"])
def get_vehicle(vid):
    a = auth()
    require_roles(a, {"Driver", "PlatformOps", "ProgramAdmin", "Rider"})
    v = lookup(db.vehicles, vid, "Vehicle")
    return success(ser_generic(v), 200)


@app.route("/vehicles", methods=["GET"])
def list_vehicles():
    a = auth()
    require_roles(a, {"Driver", "PlatformOps", "ProgramAdmin"})
    return do_list(db.vehicles, {"owner_member_id": request.args.get("owner_member_id")})


# =========================================================================
# Pool
# =========================================================================
@app.route("/pools", methods=["POST"])
def create_pool():
    a = auth()
    require_roles(a, {"Driver", "PlatformOps"})
    b = body()
    require_fields(b, ["employer_program_id", "driver_member_id", "vehicle_id",
                       "kind", "origin_zone", "dest_zone", "departure_days",
                       "base_cost_cents", "per_mile_cents"])
    # FK existence, left-to-right.
    program = lookup(db.employer_programs, b["employer_program_id"], "EmployerProgram")
    driver = lookup(db.members, b["driver_member_id"], "Member")
    vehicle = lookup(db.vehicles, b["vehicle_id"], "Vehicle")
    require_ownership(a, driver["id"])
    kind = as_enum(b, "kind", {"CARPOOL", "VANPOOL"})
    for f in ("origin_zone", "dest_zone"):
        if not isinstance(b[f], str):
            raise err("ERR_INVALID_REQUEST", f"{f} must be a string")
    days = b["departure_days"]
    valid_days = {"MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"}
    if not isinstance(days, list) or any(d not in valid_days for d in days):
        raise err("ERR_INVALID_REQUEST", "departure_days must be a subset of weekday codes")
    base_cost = as_int(b, "base_cost_cents", minimum=0)
    per_mile = as_int(b, "per_mile_cents", minimum=0)
    # Driver must be able to drive and must own the referenced vehicle.
    if not driver.get("can_drive") or vehicle["owner_member_id"] != driver["id"]:
        raise err("ERR_VALIDATION_DRIVER_REQUIRED",
                  "Driver must have can_drive true and own the vehicle")
    p = {
        "employer_program_id": program["id"],
        "driver_member_id": driver["id"],
        "vehicle_id": vehicle["id"],
        "kind": kind,
        "origin_zone": b["origin_zone"],
        "dest_zone": b["dest_zone"],
        "departure_days": list(days),
        "base_cost_cents": base_cost,
        "per_mile_cents": per_mile,
        "seat_capacity": vehicle["seat_capacity"],
        "committed_seat_count": 0,
        "status": "FORMING",
    }
    stamp_new(p)
    db.pools[p["id"]] = p
    return success(ser_generic(p), 201)


@app.route("/pools/<pid>", methods=["GET"])
def get_pool(pid):
    a = auth()
    require_roles(a, {"Driver", "PlatformOps", "ProgramAdmin", "Rider"})
    p = lookup(db.pools, pid, "Pool")
    return success(ser_generic(p), 200)


@app.route("/pools", methods=["GET"])
def list_pools():
    a = auth()
    require_roles(a, {"Driver", "PlatformOps", "ProgramAdmin", "Rider"})
    return do_list(db.pools, {
        "employer_program_id": request.args.get("employer_program_id"),
        "driver_member_id": request.args.get("driver_member_id"),
        "vehicle_id": request.args.get("vehicle_id"),
    })


@app.route("/pools/<pid>/activate", methods=["POST"])
def activate_pool(pid):
    a = auth()
    require_roles(a, {"Driver", "ProgramAdmin", "PlatformOps"})
    p = lookup(db.pools, pid, "Pool")
    require_ownership(a, p["driver_member_id"])
    program = db.employer_programs.get(p["employer_program_id"])
    if p["status"] == "FORMING":
        # Recompute committed first to reflect any current memberships.
        if p["committed_seat_count"] < 1:
            raise err("ERR_INVALID_STATE",
                      "Pool requires at least one ACTIVE membership to activate")
        if not db.vehicles.get(p["vehicle_id"]):
            raise err("ERR_DEPENDENCY_NOT_READY", "Linked vehicle missing")
        if not program or program["status"] != "ACTIVE":
            raise err("ERR_DEPENDENCY_NOT_READY", "Owning program is not ACTIVE")
    elif p["status"] == "SUSPENDED":
        if not program or program["status"] != "ACTIVE":
            raise err("ERR_DEPENDENCY_NOT_READY", "Owning program is not ACTIVE")
    else:
        raise err("ERR_INVALID_STATE", "Pool cannot be activated from its current state")
    p["status"] = "ACTIVE"
    touch(p)
    return success(ser_generic(p), 200)


def _cancel_trip_cascade(trip, system_actor=True):
    """Transition a SCHEDULED/BOARDING trip to CANCELLED and cascade to
    reservations (PRD §3.5). Used by both /trips/{id}/cancel and pool cascades."""
    from_state = trip["status"]
    trip["status"] = "CANCELLED"
    if from_state == "SCHEDULED":
        targets = ["RESERVED"]
    else:  # BOARDING
        targets = ["RESERVED", "CHECKED_IN"]
    for r in list(db.reservations.values()):
        if r["trip_id"] == trip["id"] and r["reservation_status"] in targets:
            _cancel_reservation_system(r)
    recompute_trip_seats(trip)


def _suspend_or_close_future_trips(pool, close=False):
    for t in list(db.trips.values()):
        if t["pool_id"] != pool["id"]:
            continue
        if t["status"] == "SCHEDULED" and parse_iso(t["departure_at"]) > clock_now():
            _cancel_trip_cascade(t)


@app.route("/pools/<pid>/suspend", methods=["POST"])
def suspend_pool(pid):
    a = auth()
    require_roles(a, {"Driver", "ProgramAdmin", "PlatformOps"})
    p = lookup(db.pools, pid, "Pool")
    require_ownership(a, p["driver_member_id"])
    if p["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Pool is not ACTIVE")
    p["status"] = "SUSPENDED"
    _suspend_or_close_future_trips(p)
    touch(p)
    return success(ser_generic(p), 200)


@app.route("/pools/<pid>/close", methods=["POST"])
def close_pool(pid):
    a = auth()
    require_roles(a, {"Driver", "PlatformOps"})
    p = lookup(db.pools, pid, "Pool")
    require_ownership(a, p["driver_member_id"])
    if p["status"] == "ACTIVE":
        for t in db.trips.values():
            if t["pool_id"] == p["id"] and t["status"] in ("BOARDING", "IN_TRANSIT"):
                raise err("ERR_INVALID_STATE",
                          "Cannot close: a trip is BOARDING or IN_TRANSIT")
    elif p["status"] == "SUSPENDED":
        pass
    else:
        raise err("ERR_INVALID_STATE", "Pool cannot be closed from its current state")
    p["status"] = "CLOSED"
    # End active memberships.
    for m in list(db.memberships.values()):
        if m["pool_id"] == p["id"] and m["status"] == "ACTIVE":
            m["status"] = "ENDED"
            touch(m)
    # Cancel future scheduled trips.
    for t in list(db.trips.values()):
        if t["pool_id"] == p["id"] and t["status"] == "SCHEDULED" \
                and parse_iso(t["departure_at"]) > clock_now():
            _cancel_trip_cascade(t)
    recompute_pool_committed(p)
    return success(ser_generic(p), 200)


# =========================================================================
# MatchRequest
# =========================================================================
@app.route("/match-requests", methods=["POST"])
def create_match_request():
    a = auth()
    require_roles(a, {"Rider", "PlatformOps"})
    b = body()
    require_fields(b, ["rider_member_id", "origin_zone", "dest_zone",
                       "needed_days", "earliest_departure_min", "latest_departure_min"])
    rider = lookup(db.members, b["rider_member_id"], "Member")
    require_ownership(a, rider["id"])
    for f in ("origin_zone", "dest_zone"):
        if not isinstance(b[f], str):
            raise err("ERR_INVALID_REQUEST", f"{f} must be a string")
    days = b["needed_days"]
    valid_days = {"MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"}
    if not isinstance(days, list) or any(d not in valid_days for d in days):
        raise err("ERR_INVALID_REQUEST", "needed_days must be a subset of weekday codes")
    earliest = as_int(b, "earliest_departure_min")
    latest = as_int(b, "latest_departure_min")
    if not (0 <= earliest < 1440):
        raise err("ERR_INVALID_REQUEST", "earliest_departure_min out of range")
    if not (0 <= latest < 1440):
        raise err("ERR_INVALID_REQUEST", "latest_departure_min out of range")
    if latest < earliest:
        raise err("ERR_INVALID_REQUEST", "latest_departure_min < earliest_departure_min")
    mr = {
        "rider_member_id": rider["id"],
        "origin_zone": b["origin_zone"],
        "dest_zone": b["dest_zone"],
        "needed_days": list(days),
        "earliest_departure_min": earliest,
        "latest_departure_min": latest,
        "matched_pool_id": None,
        "match_score": None,
        "status": "OPEN",
    }
    stamp_new(mr)
    db.match_requests[mr["id"]] = mr
    return success(ser_generic(mr), 201)


@app.route("/match-requests/<mid>", methods=["GET"])
def get_match_request(mid):
    a = auth()
    require_roles(a, {"Rider", "PlatformOps", "ProgramAdmin"})
    mr = lookup(db.match_requests, mid, "MatchRequest")
    return success(ser_generic(mr), 200)


@app.route("/match-requests", methods=["GET"])
def list_match_requests():
    a = auth()
    require_roles(a, {"Rider", "PlatformOps", "ProgramAdmin"})
    return do_list(db.match_requests, {
        "rider_member_id": request.args.get("rider_member_id"),
        "matched_pool_id": request.args.get("matched_pool_id"),
    })


def _match_candidates(mr, rider):
    excluded = db.exclusion_set(mr["id"])
    needed = set(mr["needed_days"])
    cands = []
    for p in db.pools.values():
        if p["status"] != "ACTIVE":
            continue
        if p["employer_program_id"] != rider["employer_program_id"]:
            continue
        if p["origin_zone"] != mr["origin_zone"] or p["dest_zone"] != mr["dest_zone"]:
            continue
        if not needed.issubset(set(p["departure_days"])):
            continue
        if p["committed_seat_count"] >= p["seat_capacity"]:
            continue
        if p["id"] in excluded:
            continue
        cands.append(p)
    return cands


@app.route("/match-requests/<mid>/match", methods=["POST"])
def match_match_request(mid):
    a = auth()
    require_roles(a, {"Rider", "PlatformOps"})
    mr = lookup(db.match_requests, mid, "MatchRequest")
    require_ownership(a, mr["rider_member_id"])
    if mr["status"] != "OPEN":
        raise err("ERR_INVALID_STATE", "MatchRequest is not OPEN")
    rider = db.members[mr["rider_member_id"]]
    cands = _match_candidates(mr, rider)
    if not cands:
        raise err("ERR_NO_MATCH_FOUND", "No candidate pool satisfies the filter")

    def score_of(p):
        driver = db.members.get(p["driver_member_id"], {})
        rel = driver.get("reliability_score", 0.0)
        seat_room = p["seat_capacity"] - p["committed_seat_count"]
        return calc.match_score(len(mr["needed_days"]), seat_room, rel)

    def sort_key(p):
        driver = db.members.get(p["driver_member_id"], {})
        rel = driver.get("reliability_score", 0.0)
        # higher score, then higher reliability, then earliest created_at
        return (-score_of(p), -rel, p["created_at"], p["_seq"])

    best = sorted(cands, key=sort_key)[0]
    mr["matched_pool_id"] = best["id"]
    mr["match_score"] = score_of(best)
    mr["status"] = "MATCHED"
    touch(mr)
    return success(ser_generic(mr), 200)


@app.route("/match-requests/<mid>/reject", methods=["POST"])
def reject_match_request(mid):
    a = auth()
    require_roles(a, {"Rider", "PlatformOps"})
    mr = lookup(db.match_requests, mid, "MatchRequest")
    require_ownership(a, mr["rider_member_id"])
    if mr["status"] != "MATCHED":
        raise err("ERR_INVALID_STATE", "MatchRequest is not MATCHED")
    rejected = mr["matched_pool_id"]
    if rejected:
        db.exclusion_set(mr["id"]).add(rejected)
    mr["matched_pool_id"] = None
    mr["match_score"] = None
    mr["status"] = "OPEN"
    touch(mr)
    return success(ser_generic(mr), 200)


@app.route("/match-requests/<mid>/confirm", methods=["POST"])
def confirm_match_request(mid):
    a = auth()
    require_roles(a, {"Rider"})
    mr = lookup(db.match_requests, mid, "MatchRequest")
    require_ownership(a, mr["rider_member_id"])
    if mr["status"] != "MATCHED":
        raise err("ERR_INVALID_STATE", "MatchRequest is not MATCHED")
    pool = db.pools.get(mr["matched_pool_id"])
    if not pool or pool["status"] != "ACTIVE":
        raise err("ERR_DEPENDENCY_NOT_READY", "Matched pool is not ACTIVE")
    if pool["committed_seat_count"] + 1 > pool["seat_capacity"]:
        raise err("ERR_POOL_CAPACITY_EXCEEDED", "Confirm would exceed pool capacity")
    membership = {
        "pool_id": pool["id"],
        "rider_member_id": mr["rider_member_id"],
        "recurring_seats": 1,
        "status": "ACTIVE",
    }
    stamp_new(membership)
    db.memberships[membership["id"]] = membership
    recompute_pool_committed(pool)
    mr["status"] = "CONFIRMED"
    touch(mr)
    return success(ser_generic(mr), 200)


@app.route("/match-requests/<mid>/cancel", methods=["POST"])
def cancel_match_request(mid):
    a = auth()
    require_roles(a, {"Rider", "PlatformOps"})
    mr = lookup(db.match_requests, mid, "MatchRequest")
    require_ownership(a, mr["rider_member_id"])
    if mr["status"] not in ("OPEN", "MATCHED"):
        raise err("ERR_INVALID_STATE", "MatchRequest cannot be cancelled")
    mr["status"] = "CANCELLED"
    touch(mr)
    return success(ser_generic(mr), 200)


# =========================================================================
# Membership
# =========================================================================
@app.route("/memberships", methods=["POST"])
def create_membership():
    a = auth()
    require_roles(a, {"Rider", "PlatformOps"})
    b = body()
    require_fields(b, ["pool_id", "rider_member_id", "expected_pool_version"])
    pool = lookup(db.pools, b["pool_id"], "Pool")
    rider = lookup(db.members, b["rider_member_id"], "Member")
    require_ownership(a, rider["id"])
    recurring = as_int(b, "recurring_seats", required=False, default=1, minimum=1)
    expected_v = as_int(b, "expected_pool_version")
    # OCC (priority 5).
    if expected_v != pool["version"]:
        raise err("ERR_STALE_POOL_VERSION", "expected_pool_version is stale")
    # Duplicate active membership (priority 6 state).
    for m in db.memberships.values():
        if m["pool_id"] == pool["id"] and m["rider_member_id"] == rider["id"] \
                and m["status"] == "ACTIVE":
            raise err("ERR_MEMBERSHIP_DUPLICATE",
                      "Rider already holds an ACTIVE membership on this pool")
    # Capacity (priority 12).
    if pool["committed_seat_count"] + recurring > pool["seat_capacity"]:
        raise err("ERR_POOL_CAPACITY_EXCEEDED", "Would exceed pool seat capacity")
    membership = {
        "pool_id": pool["id"],
        "rider_member_id": rider["id"],
        "recurring_seats": recurring,
        "status": "ACTIVE",
    }
    stamp_new(membership)
    db.memberships[membership["id"]] = membership
    recompute_pool_committed(pool)
    return success(ser_generic(membership), 201)


@app.route("/memberships/<mid>", methods=["GET"])
def get_membership(mid):
    a = auth()
    require_roles(a, {"Rider", "Driver", "PlatformOps", "ProgramAdmin"})
    m = lookup(db.memberships, mid, "Membership")
    return success(ser_generic(m), 200)


@app.route("/memberships", methods=["GET"])
def list_memberships():
    a = auth()
    require_roles(a, {"Rider", "Driver", "PlatformOps", "ProgramAdmin"})
    return do_list(db.memberships, {
        "pool_id": request.args.get("pool_id"),
        "rider_member_id": request.args.get("rider_member_id"),
    })


@app.route("/memberships/<mid>/end", methods=["POST"])
def end_membership(mid):
    a = auth()
    require_roles(a, {"Rider", "Driver", "PlatformOps"})
    m = lookup(db.memberships, mid, "Membership")
    pool = db.pools.get(m["pool_id"])
    # Ownership: rider owns by rider_member_id; driver owns the pool.
    if a.role == "Rider":
        require_ownership(a, m["rider_member_id"])
    elif a.role == "Driver":
        require_ownership(a, pool["driver_member_id"] if pool else None)
    if m["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Membership is not ACTIVE")
    m["status"] = "ENDED"
    touch(m)
    if pool:
        recompute_pool_committed(pool)
    return success(ser_generic(m), 200)


# =========================================================================
# Trip
# =========================================================================
def _windows_overlap_half_open(s1, e1, s2, e2):
    return s1 < e2 and s2 < e1


@app.route("/trips", methods=["POST"])
def create_trip():
    a = auth()
    require_roles(a, {"Driver", "PlatformOps"})
    b = body()
    require_fields(b, ["pool_id", "departure_at", "duration_min", "distance_miles"])
    pool = lookup(db.pools, b["pool_id"], "Pool")
    require_ownership(a, pool["driver_member_id"])
    if not isinstance(b["departure_at"], str):
        raise err("ERR_INVALID_REQUEST", "departure_at must be a string")
    try:
        dep = parse_iso(b["departure_at"])
    except Exception:
        raise err("ERR_INVALID_REQUEST", "departure_at must be ISO 8601")
    duration = as_int(b, "duration_min", minimum=1)
    distance = as_number(b, "distance_miles", gt=0)
    vehicle = db.vehicles.get(pool["vehicle_id"], {})
    default_hov = vehicle.get("hov_eligible", False)
    hov = as_bool(b, "hov_lane_used", default=default_hov)
    # Overlap check against non-CANCELLED trips of the same pool (half-open).
    new_start = dep
    new_end = dep + __import__("datetime").timedelta(minutes=duration)
    for t in db.trips.values():
        if t["pool_id"] != pool["id"] or t["status"] == "CANCELLED":
            continue
        es = parse_iso(t["departure_at"])
        ee = es + __import__("datetime").timedelta(minutes=t["duration_min"])
        if _windows_overlap_half_open(new_start, new_end, es, ee):
            raise err("ERR_TRIP_WINDOW_OVERLAP", "Trip window overlaps an existing trip")
    total = calc.trip_total_cost(pool["base_cost_cents"], pool["per_mile_cents"], distance)
    trip = {
        "pool_id": pool["id"],
        "departure_at": b["departure_at"],
        "duration_min": duration,
        "distance_miles": distance,
        "hov_lane_used": hov,
        "seats_reserved": 0,
        "total_cost_cents": total,
        "status": "SCHEDULED",
    }
    stamp_new(trip)
    db.trips[trip["id"]] = trip
    return success(ser_generic(trip), 201)


@app.route("/trips/<tid>", methods=["GET"])
def get_trip(tid):
    a = auth()
    require_roles(a, {"Driver", "PlatformOps", "ProgramAdmin", "Rider"})
    t = lookup(db.trips, tid, "Trip")
    return success(ser_generic(t), 200)


@app.route("/trips", methods=["GET"])
def list_trips():
    a = auth()
    require_roles(a, {"Driver", "PlatformOps", "ProgramAdmin", "Rider"})
    return do_list(db.trips, {"pool_id": request.args.get("pool_id")})


@app.route("/trips/<tid>/open-boarding", methods=["POST"])
def open_boarding(tid):
    a = auth()
    require_roles(a, {"Driver", "PlatformOps"})
    t = lookup(db.trips, tid, "Trip")
    pool = db.pools.get(t["pool_id"])
    require_ownership(a, pool["driver_member_id"] if pool else None)
    if t["status"] != "SCHEDULED":
        raise err("ERR_INVALID_STATE", "Trip is not SCHEDULED")
    if not pool or pool["status"] != "ACTIVE":
        raise err("ERR_DEPENDENCY_NOT_READY", "Owning pool is not ACTIVE")
    t["status"] = "BOARDING"
    touch(t)
    return success(ser_generic(t), 200)


def _no_show_reservation(r, late=False):
    """Apply no-show side effects to a RESERVED reservation (PRD §3.6)."""
    r["reservation_status"] = "NO_SHOW"
    if r["payment_status"] == "CHARGED":
        # estimate retained as penalty; settle.
        r["payment_status"] = "SETTLED"
    touch(r)
    member = db.members[r["rider_member_id"]]
    recompute_member_counters(member)
    append_reliability_event(member["id"], r["id"], "NO_SHOW")
    recompute_member_reliability(member)


@app.route("/trips/<tid>/depart", methods=["POST"])
def depart_trip(tid):
    a = auth()
    require_roles(a, {"Driver", "PlatformOps"})
    t = lookup(db.trips, tid, "Trip")
    pool = db.pools.get(t["pool_id"])
    require_ownership(a, pool["driver_member_id"] if pool else None)
    if t["status"] != "BOARDING":
        raise err("ERR_INVALID_STATE", "Trip is not BOARDING")
    t["status"] = "IN_TRANSIT"
    for r in list(db.reservations.values()):
        if r["trip_id"] == t["id"] and r["reservation_status"] == "RESERVED":
            _no_show_reservation(r)
    recompute_trip_seats(t)
    return success(ser_generic(t), 200)


@app.route("/trips/<tid>/complete", methods=["POST"])
def complete_trip(tid):
    a = auth()
    require_roles(a, {"Driver", "PlatformOps"})
    t = lookup(db.trips, tid, "Trip")
    pool = db.pools.get(t["pool_id"])
    require_ownership(a, pool["driver_member_id"] if pool else None)
    if t["status"] != "IN_TRANSIT":
        raise err("ERR_INVALID_STATE", "Trip is not IN_TRANSIT")
    b = body()
    hov = as_bool(b, "hov_lane_used", default=None) if "hov_lane_used" in b else None
    if hov is None:
        raise err("ERR_INVALID_REQUEST", "hov_lane_used is required on completion")
    t["hov_lane_used"] = hov
    t["total_cost_cents"] = calc.trip_total_cost(
        pool["base_cost_cents"], pool["per_mile_cents"], t["distance_miles"])
    program = db.employer_programs.get(pool["employer_program_id"])
    # FINAL inclusion set N: sum of seat_count over reservations that will be COMPLETED.
    checked_in = [r for r in db.reservations.values()
                  if r["trip_id"] == t["id"] and r["reservation_status"] == "CHECKED_IN"]
    checked_in.sort(key=lambda r: r["_seq"])
    n_final = sum(r["seat_count"] for r in checked_in)
    driver_credit = 0
    for r in checked_in:
        member = db.members[r["rider_member_id"]]
        final_cs = calc.cost_share(t["total_cost_cents"], n_final, r["seat_count"])
        r["final_cost_share_cents"] = final_cs
        # Subsidy (final). Read fresh month_remaining for this member.
        recompute_member_month_benefit(member)
        month_remaining = (program["monthly_benefit_cap_cents"]
                           - member["month_benefit_used_cents"])
        final_sub = calc.subsidy(
            final_cs, t["hov_lane_used"], program["hov_discount_pct"],
            program["employer_match_pct"], month_remaining, program["status"],
            program["subsidy_consumed_cents"], program["subsidy_budget_cents"])
        r["final_subsidy_cents"] = final_sub
        net = max(0, final_cs - final_sub)
        r["net_charge_cents"] = net
        member["wallet_balance_cents"] = max(0, member["wallet_balance_cents"] - net)
        r["reservation_status"] = "COMPLETED"
        r["payment_status"] = "SETTLED"
        touch(r)
        if final_sub > 0:
            append_ledger(program["id"], member["id"], r["id"], final_sub,
                          "DEBIT", "RESERVATION_FINALIZED")
            recompute_program_consumed(program)
            recompute_member_month_benefit(member)
        append_reliability_event(member["id"], r["id"], "COMPLETION")
        recompute_member_counters(member)
        recompute_member_reliability(member)
        touch(member)
        driver_credit += final_cs
    # Credit driver wallet with sum of final cost-shares.
    if driver_credit and pool:
        driver = db.members.get(pool["driver_member_id"])
        if driver:
            driver["wallet_balance_cents"] += driver_credit
            touch(driver)
    t["status"] = "COMPLETED"
    recompute_trip_seats(t)
    return success(ser_generic(t), 200)


def _cancel_reservation_system(r):
    """System-driven reservation cancel (trip-cancel cascade): no reliability
    penalty, full refund of any CHARGED amount, subsidy CREDIT if a DEBIT
    existed (PRD §3.5)."""
    r["reservation_status"] = "CANCELLED"
    member = db.members[r["rider_member_id"]]
    if r["payment_status"] == "CHARGED":
        member["wallet_balance_cents"] += r["estimate_cost_share_cents"]
        r["payment_status"] = "REFUNDED"
        touch(member)
    else:
        r["payment_status"] = "REFUNDED"
    _credit_prior_debit(r, member, reason="TRIP_CANCELLED")
    touch(r)


def _credit_prior_debit(r, member, reason):
    """If a DEBIT ledger entry exists for this reservation, append a
    compensating CREDIT and recompute program consumed + month benefit."""
    has_debit = any(
        e["reservation_id"] == r["id"] and e["entry_type"] == "DEBIT"
        for e in db.subsidy_ledger_entries.values()
    )
    if has_debit:
        pool = db.pools.get(db.trips[r["trip_id"]]["pool_id"])
        program = db.employer_programs.get(pool["employer_program_id"]) if pool else None
        if program:
            append_ledger(program["id"], member["id"], r["id"],
                          -r["estimate_subsidy_cents"], "CREDIT", reason)
            recompute_program_consumed(program)
            recompute_member_month_benefit(member)


@app.route("/trips/<tid>/cancel", methods=["POST"])
def cancel_trip(tid):
    a = auth()
    require_roles(a, {"Driver", "ProgramAdmin", "PlatformOps"})
    t = lookup(db.trips, tid, "Trip")
    pool = db.pools.get(t["pool_id"])
    if a.role == "Driver":
        require_ownership(a, pool["driver_member_id"] if pool else None)
    if t["status"] not in ("SCHEDULED", "BOARDING"):
        raise err("ERR_INVALID_STATE", "Trip cannot be cancelled from its current state")
    _cancel_trip_cascade(t)
    return success(ser_generic(t), 200)


# =========================================================================
# Reservation
# =========================================================================
@app.route("/reservations", methods=["POST"])
def create_reservation():
    a = auth()
    require_roles(a, {"Rider", "PlatformOps"})
    b = body()
    require_fields(b, ["trip_id", "rider_member_id", "expected_trip_version"])
    trip = lookup(db.trips, b["trip_id"], "Trip")
    rider = lookup(db.members, b["rider_member_id"], "Member")
    require_ownership(a, rider["id"])
    seat_count = as_int(b, "seat_count", required=False, default=1, minimum=1)
    expected_v = as_int(b, "expected_trip_version")
    pay_now = as_bool(b, "pay_now", default=False)
    pool = db.pools.get(trip["pool_id"])
    # Priority 5: OCC.
    if expected_v != trip["version"]:
        raise err("ERR_STALE_TRIP_VERSION", "expected_trip_version is stale")
    # Priority 6: target trip state must be SCHEDULED.
    if trip["status"] != "SCHEDULED":
        raise err("ERR_INVALID_STATE", "Trip is not SCHEDULED")
    # Priority 7: cross-entity gate — owning pool ACTIVE.
    if not pool or pool["status"] != "ACTIVE":
        raise err("ERR_DEPENDENCY_NOT_READY", "Owning pool is not ACTIVE")
    # Priority 8: reliability gate (strict < 70.0 blocks).
    if rider["reliability_score"] < 70.0:
        raise err("ERR_RELIABILITY_TOO_LOW", "Rider reliability score below 70.0")
    # Priority 10: rider double-booking (closed interval expanded by buffer).
    _check_double_booked(rider["id"], trip, seat_count)
    # Priority 11: seat capacity.
    if trip["seats_reserved"] + seat_count > pool["seat_capacity"]:
        raise err("ERR_SEATS_EXHAUSTED", "Seats exhausted on this trip")
    # Build reservation, compute estimate.
    r = {
        "trip_id": trip["id"],
        "rider_member_id": rider["id"],
        "seat_count": seat_count,
        "reservation_status": "RESERVED",
        "payment_status": "PENDING",
        "estimate_cost_share_cents": 0,
        "estimate_subsidy_cents": 0,
        "final_cost_share_cents": 0,
        "final_subsidy_cents": 0,
        "net_charge_cents": 0,
    }
    # ESTIMATE inclusion set N: forward-looking RESERVED+CHECKED_IN incl. this one.
    n_est = seat_count
    for other in db.reservations.values():
        if other["trip_id"] == trip["id"] and other["reservation_status"] in (
            "RESERVED", "CHECKED_IN"
        ):
            n_est += other["seat_count"]
    est_cs = calc.cost_share(trip["total_cost_cents"], n_est, seat_count)
    program = db.employer_programs.get(pool["employer_program_id"])
    recompute_member_month_benefit(rider)
    month_remaining = program["monthly_benefit_cap_cents"] - rider["month_benefit_used_cents"]
    est_sub = calc.subsidy(
        est_cs, trip["hov_lane_used"], program["hov_discount_pct"],
        program["employer_match_pct"], month_remaining, program["status"],
        program["subsidy_consumed_cents"], program["subsidy_budget_cents"])
    r["estimate_cost_share_cents"] = est_cs
    r["estimate_subsidy_cents"] = est_sub
    # Priority 15: wallet funding (only if charging immediately).
    if pay_now:
        if rider["wallet_balance_cents"] < est_cs:
            raise err("ERR_INSUFFICIENT_WALLET", "Wallet cannot cover the charge")
    stamp_new(r)
    db.reservations[r["id"]] = r
    if pay_now:
        rider["wallet_balance_cents"] -= est_cs
        r["payment_status"] = "CHARGED"
        touch(rider)
    recompute_trip_seats(trip)
    return success(ser_generic(r), 201)


def _trip_window(trip):
    s = parse_iso(trip["departure_at"])
    e = s + __import__("datetime").timedelta(minutes=trip["duration_min"])
    return s, e


def _check_double_booked(rider_id, new_trip, seat_count):
    ns, ne = _trip_window(new_trip)
    buf = __import__("datetime").timedelta(minutes=RIDER_BUFFER_MIN)
    ns_b, ne_b = ns - buf, ne + buf
    for r in db.reservations.values():
        if r["rider_member_id"] != rider_id:
            continue
        if r["reservation_status"] not in ("RESERVED", "CHECKED_IN"):
            continue
        other_trip = db.trips.get(r["trip_id"])
        if not other_trip or other_trip["id"] == new_trip["id"]:
            continue
        os_, oe = _trip_window(other_trip)
        os_b, oe_b = os_ - buf, oe + buf
        # Closed-interval overlap.
        if ns_b <= oe_b and os_b <= ne_b:
            raise err("ERR_RIDER_DOUBLE_BOOKED", "Rider double-booked across trips")


@app.route("/reservations/<rid>", methods=["GET"])
def get_reservation(rid):
    a = auth()
    require_roles(a, {"Rider", "Driver", "PlatformOps", "ProgramAdmin"})
    r = lookup(db.reservations, rid, "Reservation")
    return success(ser_generic(r), 200)


@app.route("/reservations", methods=["GET"])
def list_reservations():
    a = auth()
    require_roles(a, {"Rider", "Driver", "PlatformOps", "ProgramAdmin"})
    return do_list(db.reservations, {
        "trip_id": request.args.get("trip_id"),
        "rider_member_id": request.args.get("rider_member_id"),
    })


@app.route("/reservations/<rid>/check-in", methods=["POST"])
def check_in(rid):
    a = auth()
    require_roles(a, {"Driver", "PlatformOps"})
    r = lookup(db.reservations, rid, "Reservation")
    trip = db.trips.get(r["trip_id"])
    pool = db.pools.get(trip["pool_id"]) if trip else None
    require_ownership(a, pool["driver_member_id"] if pool else None)
    if r["reservation_status"] != "RESERVED":
        raise err("ERR_INVALID_STATE", "Reservation is not RESERVED")
    if not trip or trip["status"] != "BOARDING":
        raise err("ERR_INVALID_STATE", "Owning trip is not BOARDING")
    r["reservation_status"] = "CHECKED_IN"
    touch(r)
    return success(ser_generic(r), 200)


@app.route("/reservations/<rid>/no-show", methods=["POST"])
def no_show(rid):
    a = auth()
    require_roles(a, {"Driver", "PlatformOps"})
    r = lookup(db.reservations, rid, "Reservation")
    trip = db.trips.get(r["trip_id"])
    pool = db.pools.get(trip["pool_id"]) if trip else None
    require_ownership(a, pool["driver_member_id"] if pool else None)
    if r["reservation_status"] != "RESERVED":
        raise err("ERR_INVALID_STATE", "Reservation is not RESERVED")
    if not trip or trip["status"] not in ("BOARDING", "IN_TRANSIT"):
        raise err("ERR_INVALID_STATE", "Owning trip is not BOARDING or IN_TRANSIT")
    _no_show_reservation(r)
    recompute_trip_seats(trip)
    return success(ser_generic(r), 200)


@app.route("/reservations/<rid>/cancel", methods=["POST"])
def cancel_reservation(rid):
    a = auth()
    require_roles(a, {"Rider", "Driver", "PlatformOps"})
    r = lookup(db.reservations, rid, "Reservation")
    trip = db.trips.get(r["trip_id"])
    pool = db.pools.get(trip["pool_id"]) if trip else None
    if a.role == "Rider":
        require_ownership(a, r["rider_member_id"])
    elif a.role == "Driver":
        require_ownership(a, pool["driver_member_id"] if pool else None)
    if r["reservation_status"] != "RESERVED":
        raise err("ERR_INVALID_STATE", "Reservation is not RESERVED")
    if not trip or trip["status"] not in ("SCHEDULED", "BOARDING"):
        raise err("ERR_INVALID_STATE", "Owning trip is not SCHEDULED or BOARDING")
    was_boarding = trip["status"] == "BOARDING"
    rider_initiated = a.role == "Rider"
    r["reservation_status"] = "CANCELLED"
    member = db.members[r["rider_member_id"]]
    if r["payment_status"] == "CHARGED":
        member["wallet_balance_cents"] += r["estimate_cost_share_cents"]
        r["payment_status"] = "REFUNDED"
        touch(member)
    else:
        r["payment_status"] = "REFUNDED"
    # Reverse subsidy if a prior DEBIT existed.
    _credit_prior_debit_reservation_cancel(r, member)
    touch(r)
    recompute_trip_seats(trip)
    # Late cancel: rider-initiated while BOARDING -> reliability penalty.
    if rider_initiated and was_boarding:
        append_reliability_event(member["id"], r["id"], "LATE_CANCEL")
        recompute_member_reliability(member)
    return success(ser_generic(r), 200)


def _credit_prior_debit_reservation_cancel(r, member):
    """RESERVATION_CANCELLED credit path (PRD §3.6)."""
    has_debit = any(
        e["reservation_id"] == r["id"] and e["entry_type"] == "DEBIT"
        for e in db.subsidy_ledger_entries.values()
    )
    if has_debit:
        trip = db.trips.get(r["trip_id"])
        pool = db.pools.get(trip["pool_id"]) if trip else None
        program = db.employer_programs.get(pool["employer_program_id"]) if pool else None
        if program:
            append_ledger(program["id"], member["id"], r["id"],
                          -r["estimate_subsidy_cents"], "CREDIT", "RESERVATION_CANCELLED")
            recompute_program_consumed(program)
            recompute_member_month_benefit(member)


# =========================================================================
# GuaranteedRideHome
# =========================================================================
@app.route("/grh-claims", methods=["POST"])
def create_grh():
    a = auth()
    require_roles(a, {"Rider", "PlatformOps"})
    b = body()
    require_fields(b, ["rider_member_id", "employer_program_id", "claimed_fare_cents",
                       "reason_code"])
    rider = lookup(db.members, b["rider_member_id"], "Member")
    program = lookup(db.employer_programs, b["employer_program_id"], "EmployerProgram")
    require_ownership(a, rider["id"])
    trip_id = b.get("trip_id")
    if trip_id is not None:
        lookup(db.trips, trip_id, "Trip")
    claimed = as_int(b, "claimed_fare_cents", minimum=0)
    reason = as_enum(b, "reason_code", {"ILLNESS", "OVERTIME", "EMERGENCY", "DRIVER_CANCEL"})
    g = {
        "rider_member_id": rider["id"],
        "employer_program_id": program["id"],
        "trip_id": trip_id,
        "claimed_fare_cents": claimed,
        "reason_code": reason,
        "reimbursed_cents": 0,
        "status": "REQUESTED",
        "denial_reason": None,
    }
    stamp_new(g)
    db.grh_claims[g["id"]] = g
    return success(ser_generic(g), 201)


@app.route("/grh-claims/<gid>", methods=["GET"])
def get_grh(gid):
    a = auth()
    require_roles(a, {"Rider", "ProgramAdmin", "PlatformOps"})
    g = lookup(db.grh_claims, gid, "GuaranteedRideHome")
    return success(ser_generic(g), 200)


@app.route("/grh-claims", methods=["GET"])
def list_grh():
    a = auth()
    require_roles(a, {"Rider", "ProgramAdmin", "PlatformOps"})
    return do_list(db.grh_claims, {
        "rider_member_id": request.args.get("rider_member_id"),
        "employer_program_id": request.args.get("employer_program_id"),
        "trip_id": request.args.get("trip_id"),
    })


@app.route("/grh-claims/<gid>/approve", methods=["POST"])
def approve_grh(gid):
    a = auth()
    require_roles(a, {"ProgramAdmin", "PlatformOps"})
    g = lookup(db.grh_claims, gid, "GuaranteedRideHome")
    if g["status"] != "REQUESTED":
        raise err("ERR_INVALID_STATE", "Claim is not REQUESTED")
    program = db.employer_programs.get(g["employer_program_id"])
    member = db.members.get(g["rider_member_id"])
    reload_time_buckets(member)
    # Cross-entity gate: program ACTIVE.
    if not program or program["status"] != "ACTIVE":
        raise err("ERR_DEPENDENCY_NOT_READY", "Program is not ACTIVE")
    # Event-count cap (priority 13).
    if member["grh_year_event_count"] >= program["grh_max_events_per_year"]:
        raise err("ERR_GRH_EVENT_CAP", "GRH event-count cap reached")
    # Annual cap (priority 14).
    if member["grh_year_used_cents"] >= program["grh_annual_cap_cents"]:
        raise err("ERR_GRH_ANNUAL_CAP", "GRH annual cap reached")
    g["status"] = "APPROVED"
    touch(g)
    return success(ser_generic(g), 200)


@app.route("/grh-claims/<gid>/reimburse", methods=["POST"])
def reimburse_grh(gid):
    a = auth()
    require_roles(a, {"ProgramAdmin", "PlatformOps"})
    g = lookup(db.grh_claims, gid, "GuaranteedRideHome")
    if g["status"] != "APPROVED":
        raise err("ERR_INVALID_STATE", "Claim is not APPROVED")
    program = db.employer_programs.get(g["employer_program_id"])
    member = db.members.get(g["rider_member_id"])
    reload_time_buckets(member)
    annual_remaining = max(0, program["grh_annual_cap_cents"] - member["grh_year_used_cents"])
    reimbursed = calc.grh_reimbursement(
        g["claimed_fare_cents"], program["grh_per_event_cap_cents"], annual_remaining)
    g["reimbursed_cents"] = reimbursed
    member["wallet_balance_cents"] += reimbursed
    touch(member)
    append_ledger(program["id"], member["id"], None, reimbursed, "DEBIT", "GRH_REIMBURSED")
    recompute_program_consumed(program)
    recompute_member_grh(member)
    # GRH_OVERUSE reliability event when reaching the max.
    if member["grh_year_event_count"] == program["grh_max_events_per_year"]:
        append_reliability_event(member["id"], None, "GRH_OVERUSE")
        recompute_member_reliability(member)
    g["status"] = "REIMBURSED"
    touch(g)
    return success(ser_generic(g), 200)


@app.route("/grh-claims/<gid>/deny", methods=["POST"])
def deny_grh(gid):
    a = auth()
    require_roles(a, {"ProgramAdmin", "PlatformOps"})
    g = lookup(db.grh_claims, gid, "GuaranteedRideHome")
    if g["status"] != "REQUESTED":
        raise err("ERR_INVALID_STATE", "Claim is not REQUESTED")
    b = body()
    reason = as_enum(b, "denial_reason", {"ANNUAL_CAP", "EVENT_CAP", "NOT_ELIGIBLE"})
    g["denial_reason"] = reason
    g["status"] = "DENIED"
    touch(g)
    return success(ser_generic(g), 200)


# =========================================================================
# ReliabilityEvent / SubsidyLedgerEntry reads
# =========================================================================
@app.route("/reliability-events/<eid>", methods=["GET"])
def get_reliability_event(eid):
    a = auth()
    require_roles(a, {"ProgramAdmin", "PlatformOps", "Driver", "Rider"})
    e = lookup(db.reliability_events, eid, "ReliabilityEvent")
    return success(ser_generic(e), 200)


@app.route("/reliability-events", methods=["GET"])
def list_reliability_events():
    a = auth()
    require_roles(a, {"ProgramAdmin", "PlatformOps", "Driver", "Rider"})
    return do_list(db.reliability_events, {
        "member_id": request.args.get("member_id"),
        "reservation_id": request.args.get("reservation_id"),
    })


@app.route("/subsidy-ledger-entries/<eid>", methods=["GET"])
def get_ledger_entry(eid):
    a = auth()
    require_roles(a, {"ProgramAdmin", "PlatformOps"})
    e = lookup(db.subsidy_ledger_entries, eid, "SubsidyLedgerEntry")
    return success(ser_generic(e), 200)


@app.route("/subsidy-ledger-entries", methods=["GET"])
def list_ledger_entries():
    a = auth()
    require_roles(a, {"ProgramAdmin", "PlatformOps"})
    return do_list(db.subsidy_ledger_entries, {
        "member_id": request.args.get("member_id"),
        "reservation_id": request.args.get("reservation_id"),
        "employer_program_id": request.args.get("employer_program_id"),
    })


# =========================================================================
# Test-driving / operational
# =========================================================================
@app.route("/_clock/set", methods=["POST"])
def clock_set():
    a = auth()
    require_roles(a, {"PlatformOps"})
    b = body()
    require_fields(b, ["now_iso8601"])
    try:
        db.clock_now = parse_iso(b["now_iso8601"])
    except Exception:
        raise err("ERR_INVALID_REQUEST", "now_iso8601 must be ISO 8601")
    return success({}, 200)


@app.route("/_batch/run", methods=["POST"])
def batch_run():
    a = auth()
    require_roles(a, {"PlatformOps"})
    cutoff = clock_now()
    for mr in db.match_requests.values():
        if mr["status"] != "OPEN":
            continue
        created = parse_iso(mr["created_at"])
        if cutoff > created + __import__("datetime").timedelta(days=MATCH_EXPIRY_DAYS):
            mr["status"] = "EXPIRED"
            touch(mr)
    return success({}, 200)


if __name__ == "__main__":
    # The WSGI dev server's server_bind() calls socket.getfqdn("0.0.0.0") and
    # Werkzeug's startup banner resolves the host's name. Under the test
    # runner's DNS isolation those reverse lookups have no resolver and block
    # for the full ~5s DNS timeout on every boot. With per-test-server
    # isolation (a fresh boot before each test, 8 rounds concurrently) that
    # latency stacks up and trips the runner's restart-readiness window. The
    # FQDN is only used for the cosmetic server_name, so short-circuit it.
    import socket

    _orig_getfqdn = socket.getfqdn

    def _fast_getfqdn(name=""):
        if not name or name in ("0.0.0.0", "::", "127.0.0.1", "localhost"):
            return name or "localhost"
        return _orig_getfqdn(name)

    socket.getfqdn = _fast_getfqdn

    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
