"""EV Charging Network API — entry point and all routes.

In-memory storage only (see db.py); nothing is seeded at startup. Validation
order follows PRD §2.7: auth -> role -> existence (left-to-right) -> ownership
-> body schema -> state -> business rules.
"""
import os
from decimal import Decimal

from flask import Flask, request

import db
import errors
import lookups
import response
import serialize
import validation as V
from clock import set_now, parse_iso, current_utc
from middleware import get_identity, require_role

import services.site as site_svc
import services.session as session_svc
import services.settlement as settle_svc
import services.reservation as res_svc

app = Flask(__name__)

CONNECTORS = {"CCS", "CHADEMO", "J1772", "NACS"}
ALLOC_POLICIES = {"PROPORTIONAL", "PRIORITY"}
PRICING_MODES = {"ENERGY_BASED", "TIME_BASED"}
READING_CONTEXTS = {"TRANSACTION_BEGIN", "SAMPLE_PERIODIC", "TRANSACTION_END"}
OCPP_REPORTED = {"AVAILABLE", "OCCUPIED", "FAULTED", "UNAVAILABLE"}


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------
@app.errorhandler(errors.ApiError)
def handle_api_error(e):
    return response.error(e.error_id, e.message, e.http_status)


@app.errorhandler(404)
def handle_404(e):
    return response.error(errors.ERR_NOT_FOUND, "route not found", 404)


@app.errorhandler(405)
def handle_405(e):
    return response.error(errors.ERR_NOT_FOUND, "method not allowed", 404)


@app.errorhandler(Exception)
def handle_unexpected(e):
    if isinstance(e, errors.ApiError):
        return response.error(e.error_id, e.message, e.http_status)
    return response.error(errors.ERR_INVALID_REQUEST, "unexpected error: %s" % e, 422)


# ---------------------------------------------------------------------------
# Auth helper used by every route
# ---------------------------------------------------------------------------
def auth(allowed_roles):
    user_id, role = get_identity()
    require_role(role, allowed_roles)
    return user_id, role


def list_response(records, serializer, sort_key=None):
    limit, offset = V.parse_pagination()
    if sort_key is None:
        sort_key = lambda r: (r["created_at"], r.get("_seq", 0), r["id"])
    records = sorted(records, key=sort_key)
    page, total = V.paginate(records, limit, offset)
    return response.success_list([serializer(r) for r in page], limit, offset, total)


# ===========================================================================
# Sites
# ===========================================================================
@app.route("/api/sites", methods=["POST"])
def create_site():
    auth(["CPOOperator"])
    body = V.get_body()
    name = V.check_str(V.require(body, "name"), "name", non_empty=True)
    circuit = V.check_number(V.require(body, "circuit_limit_kw"), "circuit_limit_kw")
    threshold = V.check_number(V.require(body, "demand_charge_threshold_kw"),
                               "demand_charge_threshold_kw")
    if circuit <= 0:
        raise errors.err(errors.ERR_INVALID_REQUEST, "circuit_limit_kw must be > 0")
    if threshold <= 0:
        raise errors.err(errors.ERR_INVALID_REQUEST, "demand_charge_threshold_kw must be > 0")

    policy = body.get("allocation_policy", "PROPORTIONAL")
    if policy is None:
        policy = "PROPORTIONAL"
    V.check_enum(policy, "allocation_policy", ALLOC_POLICIES)

    armed = body.get("demand_avoidance_armed", False)
    if armed is None:
        armed = False
    V.check_bool(armed, "demand_avoidance_armed")

    # business rule: threshold may not exceed circuit limit
    if threshold > circuit:
        raise errors.err(errors.ERR_OVER_CIRCUIT_LIMIT,
                         "demand_charge_threshold_kw exceeds circuit_limit_kw")

    site = {
        "name": name,
        "circuit_limit_kw": circuit,
        "allocation_policy": policy,
        "demand_charge_threshold_kw": threshold,
        "demand_avoidance_armed": armed,
        "allocated_total_kw": Decimal("0"),
        "active_session_count": 0,
    }
    db.stamp_create(site)
    db.sites[site["id"]] = site
    return response.success(serialize.site(site), 201)


@app.route("/api/sites/<sid>", methods=["GET"])
def get_site(sid):
    auth(["CPOOperator", "Driver", "StationController"])
    site = lookups.site(sid)
    return response.success(serialize.site(site))


@app.route("/api/sites", methods=["GET"])
def list_sites():
    auth(["CPOOperator", "Driver"])
    return list_response(list(db.sites.values()), serialize.site)


@app.route("/api/sites/<sid>/rebalance", methods=["POST"])
def rebalance_site(sid):
    auth(["CPOOperator"])
    site = lookups.site(sid)
    snap = site_svc.run_allocation(site, "MANUAL_REBALANCE")
    db.touch(site)
    site_svc.recompute_site_aggregates(site)
    return response.success(serialize.load_allocation(snap), 200)


@app.route("/api/sites/<sid>/load-allocations", methods=["GET"])
def list_load_allocations(sid):
    auth(["CPOOperator"])
    lookups.site(sid)
    recs = [la for la in db.load_allocations.values() if la["site_id"] == sid]
    return list_response(recs, serialize.load_allocation)


@app.route("/api/sites/<sid>/stalls", methods=["GET"])
def list_site_stalls(sid):
    auth(["CPOOperator", "Driver", "StationController"])
    lookups.site(sid)
    recs = [s for s in db.stalls.values() if s["site_id"] == sid]
    return list_response(recs, serialize.stall)


@app.route("/api/sites/<sid>/tariffs", methods=["GET"])
def list_site_tariffs(sid):
    auth(["CPOOperator", "Driver"])
    lookups.site(sid)
    recs = [t for t in db.tariffs.values() if t["site_id"] == sid]
    connector = request.args.get("connector_type")
    if connector is not None:
        recs = [t for t in recs if t["connector_type"] == connector]
    return list_response(recs, serialize.tariff)


# ===========================================================================
# Stalls
# ===========================================================================
@app.route("/api/stalls", methods=["POST"])
def create_stall():
    auth(["CPOOperator"])
    body = V.get_body()
    site_id = V.check_str(V.require(body, "site_id"), "site_id")
    lookups.site(site_id)
    connector = V.check_enum(V.require(body, "connector_type"), "connector_type", CONNECTORS)
    max_power = V.check_number(V.require(body, "max_power_kw"), "max_power_kw")
    if max_power <= 0:
        raise errors.err(errors.ERR_INVALID_REQUEST, "max_power_kw must be > 0")

    priority = body.get("reservation_priority", 100)
    if priority is None:
        priority = 100
    V.check_int(priority, "reservation_priority")
    if priority < 1:
        raise errors.err(errors.ERR_INVALID_REQUEST, "reservation_priority must be >= 1")

    stall = {
        "site_id": site_id,
        "connector_type": connector,
        "max_power_kw": max_power,
        "ocpp_status": "AVAILABLE",
        "reservation_priority": priority,
    }
    db.stamp_create(stall)
    db.stalls[stall["id"]] = stall
    return response.success(serialize.stall(stall), 201)


@app.route("/api/stalls/<sid>", methods=["GET"])
def get_stall(sid):
    auth(["CPOOperator", "Driver", "StationController"])
    return response.success(serialize.stall(lookups.stall(sid)))


@app.route("/api/stalls/<sid>/ocpp-status", methods=["POST"])
def stall_ocpp_status(sid):
    auth(["StationController"])
    stall = lookups.stall(sid)
    body = V.get_body()
    reported = V.check_enum(V.require(body, "reported_status"), "reported_status", OCPP_REPORTED)

    cur = stall["ocpp_status"]
    # Defined transitions driven by StatusNotification:
    if reported == "FAULTED":
        if cur in ("AVAILABLE", "OCCUPIED"):
            _fault_stall(stall)
        else:
            raise errors.err(errors.ERR_INVALID_STATE,
                             "FAULTED not defined from %s" % cur)
    elif reported == "AVAILABLE":
        if cur == "FAULTED":
            stall["ocpp_status"] = "AVAILABLE"
            db.touch(stall)
        else:
            raise errors.err(errors.ERR_INVALID_STATE,
                             "AVAILABLE not defined from %s" % cur)
    elif reported == "UNAVAILABLE":
        if cur == "AVAILABLE":
            stall["ocpp_status"] = "UNAVAILABLE"
            db.touch(stall)
        else:
            raise errors.err(errors.ERR_INVALID_STATE,
                             "UNAVAILABLE not defined from %s" % cur)
    elif reported == "OCCUPIED":
        # Occupancy is system-driven by session create/finish, not a direct
        # StatusNotification transition.
        raise errors.err(errors.ERR_INVALID_STATE, "OCCUPIED is not a reportable status")

    return response.success(serialize.stall(stall))


def _fault_stall(stall):
    """AVAILABLE/OCCUPIED -> FAULTED with the depth-3 cascade (PRD §2.5, §3.1)."""
    stall["ocpp_status"] = "FAULTED"
    db.touch(stall)
    # If a session on this stall is mid-flight, force SUSPENDED + free power.
    affected_site = None
    for sess in db.sessions.values():
        if sess["stall_id"] != stall["id"]:
            continue
        if sess["charging_status"] in ("PREPARING", "CHARGING", "SUSPENDED"):
            session_svc.force_suspend_from_fault(sess)
            affected_site = db.sites[stall["site_id"]]
    if affected_site is not None:
        site_svc.run_allocation(affected_site, "SESSION_SUSPEND")
        db.touch(affected_site)
        site_svc.recompute_site_aggregates(affected_site)


# ===========================================================================
# Drivers
# ===========================================================================
@app.route("/api/drivers", methods=["POST"])
def create_driver():
    auth(["CPOOperator"])
    body = V.get_body()
    email = V.check_str(V.require(body, "email"), "email", non_empty=True)
    full_name = V.check_str(V.require(body, "full_name"), "full_name")
    home_emsp_id = V.check_str(V.require(body, "home_emsp_id"), "home_emsp_id")
    lookups.emsp(home_emsp_id)

    # email uniqueness
    for d in db.drivers.values():
        if d["email"] == email:
            raise errors.err(errors.ERR_INVALID_REQUEST, "email must be unique")

    driver = {
        "email": email,
        "full_name": full_name,
        "home_emsp_id": home_emsp_id,
        "wallet_balance_cents": 0,
    }
    db.stamp_create(driver)
    db.drivers[driver["id"]] = driver
    return response.success(serialize.driver(driver), 201)


@app.route("/api/drivers/<did>", methods=["GET"])
def get_driver(did):
    auth(["CPOOperator", "Driver"])
    return response.success(serialize.driver(lookups.driver(did)))


@app.route("/api/drivers", methods=["GET"])
def list_drivers():
    auth(["CPOOperator"])
    recs = list(db.drivers.values())
    home_emsp = request.args.get("home_emsp_id")
    if home_emsp is not None:
        recs = [d for d in recs if d["home_emsp_id"] == home_emsp]
    return list_response(recs, serialize.driver)


@app.route("/api/drivers/<did>/wallet/adjustments", methods=["POST"])
def adjust_wallet(did):
    auth(["CPOOperator"])
    driver = lookups.driver(did)
    body = V.get_body()
    amount = V.check_int(V.require(body, "amount_cents"), "amount_cents")
    if driver["wallet_balance_cents"] + amount < 0:
        raise errors.err(errors.ERR_NEGATIVE_WALLET, "adjustment drives wallet below zero")
    driver["wallet_balance_cents"] += amount
    db.touch(driver)
    return response.success(serialize.driver(driver))


# ===========================================================================
# eMSPs
# ===========================================================================
@app.route("/api/emsps", methods=["POST"])
def create_emsp():
    auth(["CPOOperator"])
    body = V.get_body()
    name = V.check_str(V.require(body, "name"), "name", non_empty=True)
    commission = V.check_number(V.require(body, "commission_pct"), "commission_pct")
    if not (commission >= 0 and commission < 1):
        raise errors.err(errors.ERR_INVALID_REQUEST,
                         "commission_pct must be >= 0 and < 1")
    emsp = {
        "name": name,
        "commission_pct": commission,
        "receivable_balance_cents": 0,
    }
    db.stamp_create(emsp)
    db.emsps[emsp["id"]] = emsp
    return response.success(serialize.emsp(emsp), 201)


@app.route("/api/emsps/<eid>", methods=["GET"])
def get_emsp(eid):
    auth(["CPOOperator"])
    emsp = lookups.emsp(eid)
    settle_svc.recompute_emsp_receivable(emsp)
    return response.success(serialize.emsp(emsp))


# ===========================================================================
# Tariffs
# ===========================================================================
@app.route("/api/tariffs", methods=["POST"])
def create_tariff():
    auth(["CPOOperator"])
    body = V.get_body()
    site_id = V.check_str(V.require(body, "site_id"), "site_id")
    lookups.site(site_id)
    connector = V.check_enum(V.require(body, "connector_type"), "connector_type", CONNECTORS)
    mode = V.check_enum(V.require(body, "pricing_mode"), "pricing_mode", PRICING_MODES)

    session_fee = body.get("session_fee_cents", 0)
    if session_fee is None:
        session_fee = 0
    V.check_int(session_fee, "session_fee_cents")
    if session_fee < 0:
        raise errors.err(errors.ERR_INVALID_REQUEST, "session_fee_cents must be >= 0")

    t1_max = V.check_number(V.require(body, "energy_tier_1_max_kwh"), "energy_tier_1_max_kwh")
    t2_max = V.check_number(V.require(body, "energy_tier_2_max_kwh"), "energy_tier_2_max_kwh")
    if t1_max <= 0:
        raise errors.err(errors.ERR_INVALID_REQUEST, "energy_tier_1_max_kwh must be > 0")

    r1 = V.check_int(V.require(body, "energy_rate_t1_cents"), "energy_rate_t1_cents")
    r2 = V.check_int(V.require(body, "energy_rate_t2_cents"), "energy_rate_t2_cents")
    r3 = V.check_int(V.require(body, "energy_rate_t3_cents"), "energy_rate_t3_cents")
    for rv, rn in ((r1, "energy_rate_t1_cents"), (r2, "energy_rate_t2_cents"), (r3, "energy_rate_t3_cents")):
        if rv < 0:
            raise errors.err(errors.ERR_INVALID_REQUEST, "%s must be >= 0" % rn)

    time_rate = V.check_int(V.require(body, "time_rate_cents_per_min"), "time_rate_cents_per_min")
    if time_rate < 0:
        raise errors.err(errors.ERR_INVALID_REQUEST, "time_rate_cents_per_min must be >= 0")

    idle_grace = body.get("idle_grace_minutes", 0)
    if idle_grace is None:
        idle_grace = 0
    V.check_int(idle_grace, "idle_grace_minutes")
    if idle_grace < 0:
        raise errors.err(errors.ERR_INVALID_REQUEST, "idle_grace_minutes must be >= 0")

    idle_fee = body.get("idle_fee_cents_per_min", 0)
    if idle_fee is None:
        idle_fee = 0
    V.check_int(idle_fee, "idle_fee_cents_per_min")
    if idle_fee < 0:
        raise errors.err(errors.ERR_INVALID_REQUEST, "idle_fee_cents_per_min must be >= 0")

    eff_from_raw = V.check_str(V.require(body, "effective_from"), "effective_from")
    eff_to_raw = V.check_str(V.require(body, "effective_to"), "effective_to")
    try:
        eff_from = parse_iso(eff_from_raw)
        eff_to = parse_iso(eff_to_raw)
    except (ValueError, TypeError):
        raise errors.err(errors.ERR_INVALID_REQUEST, "invalid datetime")

    # tier / window sanity -> ERR_TARIFF_INVALID_TIERS (422)
    if t2_max <= t1_max or eff_to < eff_from:
        raise errors.err(errors.ERR_TARIFF_INVALID_TIERS,
                         "tier 2 must exceed tier 1 and effective_to >= effective_from")

    # window overlap for same (site_id, connector_type); closed interval (touching allowed)
    for t in db.tariffs.values():
        if t["site_id"] == site_id and t["connector_type"] == connector:
            o_from = parse_iso(t["effective_from"])
            o_to = parse_iso(t["effective_to"])
            # closed intervals overlap if start <= other_end and other_start <= end,
            # but merely touching endpoints is allowed -> use strict comparisons.
            if eff_from < o_to and o_from < eff_to:
                raise errors.err(errors.ERR_TARIFF_WINDOW_OVERLAP,
                                 "overlapping effective window")

    tariff = {
        "site_id": site_id,
        "connector_type": connector,
        "pricing_mode": mode,
        "session_fee_cents": session_fee,
        "energy_tier_1_max_kwh": t1_max,
        "energy_tier_2_max_kwh": t2_max,
        "energy_rate_t1_cents": r1,
        "energy_rate_t2_cents": r2,
        "energy_rate_t3_cents": r3,
        "time_rate_cents_per_min": time_rate,
        "idle_grace_minutes": idle_grace,
        "idle_fee_cents_per_min": idle_fee,
        "effective_from": eff_from_raw,
        "effective_to": eff_to_raw,
    }
    db.stamp_create(tariff)
    db.tariffs[tariff["id"]] = tariff
    return response.success(serialize.tariff(tariff), 201)


@app.route("/api/tariffs/<tid>", methods=["GET"])
def get_tariff(tid):
    auth(["CPOOperator", "Driver"])
    return response.success(serialize.tariff(lookups.tariff(tid)))


# ===========================================================================
# Reservations
# ===========================================================================
@app.route("/api/reservations", methods=["POST"])
def create_reservation():
    user_id, role = auth(["Driver"])
    body = V.get_body()
    stall_id = V.check_str(V.require(body, "stall_id"), "stall_id")
    driver_id = V.check_str(V.require(body, "driver_id"), "driver_id")
    # existence left-to-right
    stall = lookups.stall(stall_id)
    lookups.driver(driver_id)

    # ownership: Driver must own the reservation it creates (driver_id == X-User-ID)
    if driver_id != user_id:
        raise errors.err(errors.ERR_FORBIDDEN, "driver may only create own reservation")

    ws_raw = V.check_str(V.require(body, "window_start"), "window_start")
    we_raw = V.check_str(V.require(body, "window_end"), "window_end")
    try:
        ws = parse_iso(ws_raw)
        we = parse_iso(we_raw)
    except (ValueError, TypeError):
        raise errors.err(errors.ERR_INVALID_REQUEST, "invalid datetime")
    if not (we > ws):
        raise errors.err(errors.ERR_INVALID_REQUEST, "window_end must be after window_start")

    hold_fee = body.get("hold_fee_cents", 0)
    if hold_fee is None:
        hold_fee = 0
    V.check_int(hold_fee, "hold_fee_cents")
    if hold_fee < 0:
        raise errors.err(errors.ERR_INVALID_REQUEST, "hold_fee_cents must be >= 0")

    expected = V.require(body, "expected_stall_version")
    V.check_int(expected, "expected_stall_version")

    # OCC: stale stall version -> ERR_STALE_VERSION (412)
    if expected != stall["version"]:
        raise errors.err(errors.ERR_STALE_VERSION, "stale expected_stall_version")

    reservation = {
        "stall_id": stall_id,
        "driver_id": driver_id,
        "window_start": ws_raw,
        "window_end": we_raw,
        "status": "REQUESTED",
        "hold_fee_cents": hold_fee,
    }
    db.stamp_create(reservation)
    db.reservations[reservation["id"]] = reservation

    # creating a reservation advances the stall version (stall availability changes)
    db.touch(stall)
    return response.success(serialize.reservation(reservation), 201)


@app.route("/api/reservations/<rid>", methods=["GET"])
def get_reservation(rid):
    auth(["CPOOperator", "Driver"])
    res = lookups.reservation(rid)
    res_svc.observe(res)
    return response.success(serialize.reservation(res))


@app.route("/api/reservations", methods=["GET"])
def list_reservations():
    auth(["CPOOperator", "Driver"])
    res_svc.observe_all()
    recs = list(db.reservations.values())
    stall_id = request.args.get("stall_id")
    driver_id = request.args.get("driver_id")
    if stall_id is not None:
        recs = [r for r in recs if r["stall_id"] == stall_id]
    if driver_id is not None:
        recs = [r for r in recs if r["driver_id"] == driver_id]
    return list_response(recs, serialize.reservation)


def _own_reservation(res, user_id):
    if res["driver_id"] != user_id:
        raise errors.err(errors.ERR_FORBIDDEN, "driver does not own this reservation")


@app.route("/api/reservations/<rid>/confirm", methods=["POST"])
def confirm_reservation(rid):
    user_id, role = auth(["Driver"])
    res = lookups.reservation(rid)
    _own_reservation(res, user_id)
    res_svc.observe(res)

    if res["status"] != "REQUESTED":
        raise errors.err(errors.ERR_INVALID_STATE, "confirm requires REQUESTED")

    # buffered overlap with another CONFIRMED/CHECKED_IN reservation on same stall
    ws = parse_iso(res["window_start"])
    we = parse_iso(res["window_end"])
    buffer = res_svc.RESERVATION_BUFFER_MIN
    import datetime
    buf = datetime.timedelta(minutes=buffer)
    for other in db.reservations.values():
        if other["id"] == res["id"]:
            continue
        if other["stall_id"] != res["stall_id"]:
            continue
        if other["status"] not in ("CONFIRMED", "CHECKED_IN"):
            continue
        ows = parse_iso(other["window_start"])
        owe = parse_iso(other["window_end"])
        # half-open [start, end) extended by buffer at the tail
        if ws < (owe + buf) and ows < (we + buf):
            raise errors.err(errors.ERR_RESERVATION_OVERLAP, "buffered window collision")

    driver = db.drivers[res["driver_id"]]
    if driver["wallet_balance_cents"] - res["hold_fee_cents"] < 0:
        raise errors.err(errors.ERR_INSUFFICIENT_WALLET_HOLD, "hold fee drives wallet below zero")

    driver["wallet_balance_cents"] -= res["hold_fee_cents"]
    db.touch(driver)
    res["status"] = "CONFIRMED"
    db.touch(res)
    return response.success(serialize.reservation(res))


@app.route("/api/reservations/<rid>/check-in", methods=["POST"])
def checkin_reservation(rid):
    user_id, role = auth(["Driver"])
    res = lookups.reservation(rid)
    _own_reservation(res, user_id)
    # NOTE: do NOT lazily transition a past-window CONFIRMED reservation to
    # NO_SHOW here. The temporal window check (priority 8,
    # ERR_RESERVATION_WINDOW_CLOSED) must take precedence over the NO_SHOW
    # observation for the check-in action (PRD §3.5 / §2.7).
    if res["status"] != "CONFIRMED":
        raise errors.err(errors.ERR_INVALID_STATE, "check-in requires CONFIRMED")

    now = current_utc()
    ws = parse_iso(res["window_start"])
    we = parse_iso(res["window_end"])
    if not (ws <= now < we):
        raise errors.err(errors.ERR_RESERVATION_WINDOW_CLOSED, "outside [window_start, window_end)")

    stall = db.stalls[res["stall_id"]]
    if stall["ocpp_status"] not in ("AVAILABLE", "OCCUPIED"):
        raise errors.err(errors.ERR_INVALID_STATE, "stall not AVAILABLE/OCCUPIED")

    res["status"] = "CHECKED_IN"
    db.touch(res)
    return response.success(serialize.reservation(res))


@app.route("/api/reservations/<rid>/cancel", methods=["POST"])
def cancel_reservation(rid):
    user_id, role = auth(["Driver"])
    res = lookups.reservation(rid)
    _own_reservation(res, user_id)
    res_svc.observe(res)

    status = res["status"]
    if status == "REQUESTED":
        res["status"] = "CANCELLED"
        db.touch(res)
    elif status == "CONFIRMED":
        # refund the already-charged deposit
        driver = db.drivers[res["driver_id"]]
        driver["wallet_balance_cents"] += res["hold_fee_cents"]
        db.touch(driver)
        res["status"] = "CANCELLED"
        db.touch(res)
    else:
        raise errors.err(errors.ERR_INVALID_STATE, "cancel requires REQUESTED or CONFIRMED")
    return response.success(serialize.reservation(res))


# ===========================================================================
# Charging sessions
# ===========================================================================
@app.route("/api/sessions", methods=["POST"])
def create_session():
    user_id, role = auth(["Driver", "StationController"])
    body = V.get_body()
    stall_id = V.check_str(V.require(body, "stall_id"), "stall_id")
    driver_id = V.check_str(V.require(body, "driver_id"), "driver_id")
    stall = lookups.stall(stall_id)
    driver = lookups.driver(driver_id)

    reservation_id = body.get("reservation_id")
    if reservation_id is not None:
        V.check_str(reservation_id, "reservation_id")
        lookups.reservation(reservation_id)

    # ownership: a Driver may only start a session for own driver_id
    if role == "Driver" and driver_id != user_id:
        raise errors.err(errors.ERR_FORBIDDEN, "driver may only start own session")

    is_roaming = body.get("is_roaming", False)
    if is_roaming is None:
        is_roaming = False
    V.check_bool(is_roaming, "is_roaming")

    # state: stall must be AVAILABLE
    if stall["ocpp_status"] != "AVAILABLE":
        raise errors.err(errors.ERR_STALL_NOT_AVAILABLE, "stall is not AVAILABLE")

    # resolve tariff at the clock for site+connector
    now = current_utc()
    matching = []
    for t in db.tariffs.values():
        if t["site_id"] != stall["site_id"]:
            continue
        if t["connector_type"] != stall["connector_type"]:
            continue
        if parse_iso(t["effective_from"]) <= now <= parse_iso(t["effective_to"]):
            matching.append(t)
    if not matching:
        raise errors.err(errors.ERR_NO_ACTIVE_TARIFF, "no active tariff for site+connector")
    tariff = sorted(matching, key=lambda t: (t["created_at"], t["id"]))[0]

    # connector mismatch (defensive; tariff was resolved on connector match)
    if stall["connector_type"] != tariff["connector_type"]:
        raise errors.err(errors.ERR_CONNECTOR_MISMATCH, "stall connector does not match tariff")

    emsp_id = driver["home_emsp_id"] if is_roaming else None

    session = {
        "stall_id": stall_id,
        "driver_id": driver_id,
        "tariff_id": tariff["id"],
        "reservation_id": reservation_id,
        "emsp_id": emsp_id,
        "is_roaming": is_roaming,
        "charging_status": "PREPARING",
        "billing_status": "UNBILLED",
        "energy_delivered_kwh": Decimal("0"),
        "charging_minutes": 0,
        "idle_minutes": 0,
        "allocated_power_kw": Decimal("0"),
        "total_cost_cents": 0,
        "idle_fee_cents": 0,
        # internal time accounting
        "_charging_seconds": 0.0,
        "_idle_seconds": 0.0,
        "_charging_started_at": None,
        "_suspend_started_at": None,
    }
    db.stamp_create(session)
    db.sessions[session["id"]] = session

    # stall AVAILABLE -> OCCUPIED, bump stall version
    stall["ocpp_status"] = "OCCUPIED"
    db.touch(stall)
    return response.success(serialize.session(session), 201)


@app.route("/api/sessions/<sid>", methods=["GET"])
def get_session(sid):
    auth(["CPOOperator", "Driver", "StationController"])
    sess = lookups.session(sid)
    return response.success(serialize.session(sess))


@app.route("/api/sessions", methods=["GET"])
def list_sessions():
    auth(["CPOOperator", "Driver", "StationController"])
    recs = list(db.sessions.values())
    for key in ("driver_id", "stall_id", "reservation_id", "tariff_id", "emsp_id"):
        val = request.args.get(key)
        if val is not None:
            recs = [s for s in recs if s.get(key) == val]
    return list_response(recs, serialize.session)


@app.route("/api/sessions/<sid>/meter-events", methods=["POST"])
def post_meter_event(sid):
    auth(["StationController"])
    sess = lookups.session(sid)
    body = V.get_body()
    meter_kwh = V.check_number(V.require(body, "meter_kwh"), "meter_kwh")
    if meter_kwh < 0:
        raise errors.err(errors.ERR_INVALID_REQUEST, "meter_kwh must be >= 0")
    sampled_at = V.check_str(V.require(body, "sampled_at"), "sampled_at")
    context = V.check_enum(V.require(body, "reading_context"), "reading_context", READING_CONTEXTS)

    # monotonic non-decreasing per session
    existing = [m for m in db.meter_events.values() if m["session_id"] == sid]
    if existing:
        existing.sort(key=lambda m: m["_seq"])
        prior = Decimal(str(existing[-1]["meter_kwh"]))
        if Decimal(str(meter_kwh)) < prior:
            raise errors.err(errors.ERR_METER_REGRESSION, "meter_kwh below prior reading")

    me = {
        "session_id": sid,
        "meter_kwh": meter_kwh,
        "sampled_at": sampled_at,
        "reading_context": context,
        "_seq": db.next_seq(),
    }
    me["id"] = db.new_id()
    from clock import now_iso
    me["created_at"] = now_iso()
    db.meter_events[me["id"]] = me

    session_svc.recompute_energy(sess)
    db.touch(sess)
    return response.success(serialize.meter_event(me), 201)


@app.route("/api/sessions/<sid>/meter-events", methods=["GET"])
def list_meter_events(sid):
    auth(["CPOOperator", "Driver", "StationController"])
    lookups.session(sid)
    recs = [m for m in db.meter_events.values() if m["session_id"] == sid]
    return list_response(recs, serialize.meter_event)


@app.route("/api/sessions/<sid>/begin-charging", methods=["POST"])
def begin_charging(sid):
    auth(["StationController"])
    sess = lookups.session(sid)
    if sess["charging_status"] not in ("PREPARING", "SUSPENDED"):
        raise errors.err(errors.ERR_INVALID_STATE,
                         "begin-charging not defined from %s" % sess["charging_status"])
    session_svc.begin_charging(sess)
    return response.success(serialize.session(sess))


@app.route("/api/sessions/<sid>/suspend", methods=["POST"])
def suspend_session(sid):
    auth(["StationController"])
    sess = lookups.session(sid)
    session_svc.suspend(sess)
    return response.success(serialize.session(sess))


@app.route("/api/sessions/<sid>/stop", methods=["POST"])
def stop_session(sid):
    user_id, role = auth(["Driver", "StationController"])
    sess = lookups.session(sid)
    if role == "Driver" and sess["driver_id"] != user_id:
        raise errors.err(errors.ERR_FORBIDDEN, "driver does not own this session")
    session_svc.stop(sess)
    return response.success(serialize.session(sess))


@app.route("/api/sessions/<sid>/abort", methods=["POST"])
def abort_session(sid):
    user_id, role = auth(["Driver", "StationController"])
    sess = lookups.session(sid)
    if role == "Driver" and sess["driver_id"] != user_id:
        raise errors.err(errors.ERR_FORBIDDEN, "driver does not own this session")
    session_svc.abort(sess)
    return response.success(serialize.session(sess))


@app.route("/api/sessions/<sid>/cost-preview", methods=["GET"])
def session_cost_preview(sid):
    auth(["CPOOperator", "Driver", "StationController"])
    sess = lookups.session(sid)
    total_cost, idle_fee = session_svc.cost_preview(sess)
    view = serialize.session(sess)
    view["total_cost_cents"] = total_cost
    view["idle_fee_cents"] = idle_fee
    return response.success(view)


# ===========================================================================
# Settlement
# ===========================================================================
@app.route("/api/settlement-batches", methods=["POST"])
def create_batch():
    auth(["CPOOperator"])
    body = V.get_body()
    emsp_id = V.check_str(V.require(body, "emsp_id"), "emsp_id")
    lookups.emsp(emsp_id)
    batch = {
        "emsp_id": emsp_id,
        "status": "OPEN",
        "line_item_count": 0,
        "total_amount_cents": 0,
    }
    db.stamp_create(batch)
    db.batches[batch["id"]] = batch
    return response.success(serialize.batch(batch), 201)


@app.route("/api/settlement-batches/<bid>", methods=["GET"])
def get_batch(bid):
    auth(["CPOOperator"])
    batch = lookups.batch(bid)
    settle_svc.recompute_batch(batch)
    return response.success(serialize.batch(batch))


@app.route("/api/settlement-batches", methods=["GET"])
def list_batches():
    auth(["CPOOperator"])
    recs = list(db.batches.values())
    emsp_id = request.args.get("emsp_id")
    if emsp_id is not None:
        recs = [b for b in recs if b["emsp_id"] == emsp_id]
    return list_response(recs, serialize.batch)


@app.route("/api/settlement-batches/<bid>/line-items", methods=["POST"])
def add_line_item(bid):
    auth(["CPOOperator"])
    batch = lookups.batch(bid)
    body = V.get_body()
    session_id = V.check_str(V.require(body, "session_id"), "session_id")
    sess = lookups.session(session_id)

    if batch["status"] != "OPEN":
        raise errors.err(errors.ERR_INVALID_STATE, "line items can only be added to OPEN batch")

    # settleability: RATED + roaming + emsp matches batch
    if not (sess["billing_status"] == "RATED" and sess["is_roaming"] and
            sess["emsp_id"] == batch["emsp_id"]):
        raise errors.err(errors.ERR_SESSION_NOT_SETTLEABLE,
                         "session not RATED roaming for this eMSP")

    # duplicate: already in a non-reversed line item
    for li in db.line_items.values():
        if li["session_id"] == session_id and li["status"] != "REVERSED":
            raise errors.err(errors.ERR_DUPLICATE_LINE_ITEM,
                             "session already in a line item")

    li = settle_svc.add_line_item(batch, sess)
    return response.success(serialize.line_item(li), 201)


@app.route("/api/settlement-batches/<bid>/line-items", methods=["GET"])
def list_batch_line_items(bid):
    auth(["CPOOperator"])
    lookups.batch(bid)
    recs = [li for li in db.line_items.values() if li["batch_id"] == bid]
    return list_response(recs, serialize.line_item)


@app.route("/api/settlement-line-items", methods=["GET"])
def list_line_items():
    auth(["CPOOperator"])
    recs = list(db.line_items.values())
    session_id = request.args.get("session_id")
    if session_id is not None:
        recs = [li for li in recs if li["session_id"] == session_id]
    return list_response(recs, serialize.line_item)


@app.route("/api/settlement-line-items/<lid>", methods=["GET"])
def get_line_item(lid):
    auth(["CPOOperator"])
    return response.success(serialize.line_item(lookups.line_item(lid)))


@app.route("/api/settlement-batches/<bid>/lock", methods=["POST"])
def lock_batch(bid):
    auth(["CPOOperator"])
    batch = lookups.batch(bid)
    if batch["status"] != "OPEN":
        raise errors.err(errors.ERR_INVALID_STATE, "lock requires OPEN")
    members = [li for li in db.line_items.values() if li["batch_id"] == bid]
    if len(members) < 1:
        raise errors.err(errors.ERR_EMPTY_BATCH, "cannot lock empty batch")
    settle_svc.lock(batch)
    return response.success(serialize.batch(batch))


@app.route("/api/settlement-batches/<bid>/settle", methods=["POST"])
def settle_batch(bid):
    auth(["CPOOperator"])
    batch = lookups.batch(bid)
    body = V.get_body()
    if batch["status"] != "LOCKED":
        raise errors.err(errors.ERR_INVALID_STATE, "settle requires LOCKED")
    expected = V.require(body, "expected_settlementbatch_version")
    V.check_int(expected, "expected_settlementbatch_version")
    if expected != batch["version"]:
        raise errors.err(errors.ERR_STALE_VERSION, "stale expected_settlementbatch_version")
    settle_svc.settle(batch)
    return response.success(serialize.batch(batch))


@app.route("/api/settlement-batches/<bid>/dispute", methods=["POST"])
def dispute_batch(bid):
    auth(["CPOOperator"])
    batch = lookups.batch(bid)
    if batch["status"] != "LOCKED":
        raise errors.err(errors.ERR_INVALID_STATE, "dispute requires LOCKED")
    settle_svc.dispute(batch)
    return response.success(serialize.batch(batch))


@app.route("/api/settlement-batches/<bid>/reopen", methods=["POST"])
def reopen_batch(bid):
    auth(["CPOOperator"])
    batch = lookups.batch(bid)
    if batch["status"] != "DISPUTED":
        raise errors.err(errors.ERR_INVALID_STATE, "reopen requires DISPUTED")
    settle_svc.reopen(batch)
    return response.success(serialize.batch(batch))


# ===========================================================================
# Test-driving clock
# ===========================================================================
@app.route("/api/_clock/set_current_utc", methods=["POST"])
def set_clock():
    auth(["CPOOperator"])
    body = V.get_body()
    to_iso = V.check_str(V.require(body, "to_iso8601"), "to_iso8601")
    try:
        dt = parse_iso(to_iso)
    except (ValueError, TypeError):
        raise errors.err(errors.ERR_INVALID_REQUEST, "invalid datetime")
    set_now(dt)
    # PRD §3.9: advancing the clock "may, on the NEXT OBSERVATION, drive" the
    # system reservation transitions (REQUESTED->EXPIRED, CONFIRMED->NO_SHOW).
    # The transitions are therefore applied lazily when a reservation is next
    # READ (GET single / list), not eagerly here — so an action that has its
    # own temporal guard (e.g. check-in's ERR_RESERVATION_WINDOW_CLOSED) can
    # still take precedence over the NO_SHOW observation.
    return response.success({}, 200)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
