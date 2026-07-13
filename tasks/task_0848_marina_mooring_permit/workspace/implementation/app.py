"""Marina Mooring Permit API — Flask entry point (all routes)."""
import os
from datetime import timedelta

from flask import Flask, request, jsonify

import core
from core import (
    ApiError, store, clock,
    base_common, touch, serialize, serialize_vessel,
    parse_dt, to_date, iso, now_iso, gen_req_id,
    recompute_marina, issue_invoice, offer_permit, free_berth,
    waitlist_promotion, check_activation, activate_permit, revoke_permit,
    compute_provisional_fee, ramp_pass_fee, vessel_reg_status,
    run_lottery_draw, derelict_actual_cost, run_maintenance,
    NOTICE_FEE_CENTS, TRANSFER_FEE_CENTS, OFFER_TTL_DAYS,
    DEFAULT_PUMPOUT_INTERVAL_DAYS,
)

app = Flask(__name__)

ROLES = {"Harbormaster", "FinanceClerk", "Boater"}


# ---------------------------------------------------------------------------
# Response envelope
# ---------------------------------------------------------------------------
def _meta(pagination=None):
    m = {"api_request_id": gen_req_id(), "api_request_timestamp": now_iso()}
    if pagination:
        m.update(pagination)
    return m


def ok(data, status=200, response_type="object", pagination=None):
    return jsonify({"meta": _meta(pagination), "response_type": response_type, "data": data}), status


def err_response(error_id, http_status, message):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), http_status


@app.errorhandler(ApiError)
def _handle_api_error(e):
    return err_response(e.error_id, e.http_status, e.message)


@app.errorhandler(404)
def _handle_404(e):
    return err_response("ERR_NOT_FOUND", 404, "Resource not found")


@app.errorhandler(405)
def _handle_405(e):
    return err_response("ERR_NOT_FOUND", 404, "Method not allowed")


@app.errorhandler(500)
def _handle_500(e):
    return err_response("ERR_VALIDATION", 400, "Internal error")


# ---------------------------------------------------------------------------
# Auth / validation helpers
# ---------------------------------------------------------------------------
def authn():
    role = request.headers.get("X-User-Role")
    if role is None or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", 401, "Missing or invalid role")
    return request.headers.get("X-User-ID"), role


def authz(role, allowed):
    if role not in allowed:
        raise ApiError("ERR_UNAUTHORIZED", 403, "Role not permitted for this operation")


def require_owner(role, user_id, owner_id):
    if role == "Boater" and owner_id != user_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", 403, "Boater does not own this resource")


def body():
    data = request.get_json(force=True, silent=True)
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise ApiError("ERR_VALIDATION", 400, "Malformed request body")
    return data


def require_fields(data, fields):
    for f in fields:
        if data.get(f) is None:
            raise ApiError("ERR_VALIDATION", 400, f"Missing required field: {f}")


def require_enum(value, allowed, name):
    if value not in allowed:
        raise ApiError("ERR_VALIDATION", 400, f"Invalid value for {name}")


def get_or_404(coll, rid):
    ent = coll.get(rid)
    if ent is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Resource not found")
    return ent


def parse_pagination():
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args:
        try:
            limit = int(args["limit"])
        except (ValueError, TypeError):
            raise ApiError("ERR_PAGINATION_INVALID", 400, "Invalid limit")
        if limit < 1 or limit > 100:
            raise ApiError("ERR_PAGINATION_INVALID", 400, "limit out of range")
    if "offset" in args:
        try:
            offset = int(args["offset"])
        except (ValueError, TypeError):
            raise ApiError("ERR_PAGINATION_INVALID", 400, "Invalid offset")
        if offset < 0:
            raise ApiError("ERR_PAGINATION_INVALID", 400, "offset out of range")
    return limit, offset


def paginate(items, limit, offset):
    items = sorted(items, key=lambda e: e["_seq"])
    total = len(items)
    page = items[offset:offset + limit]
    pag = {"limit": limit, "offset": offset, "total_count": total, "has_more": offset + limit < total}
    return page, pag


def list_response(items, serializer):
    limit, offset = parse_pagination()
    page, pag = paginate(items, limit, offset)
    return ok([serializer(e) for e in page], 200, "array", pag)


# ===========================================================================
# Marina
# ===========================================================================
@app.route("/marina/marinas", methods=["POST"])
def create_marina():
    _, role = authn()
    authz(role, {"Harbormaster"})
    data = body()
    require_fields(data, ["name", "season_start_date", "season_end_date", "liveaboard_cap"])
    cap = data["liveaboard_cap"]
    if not isinstance(cap, int) or isinstance(cap, bool):
        raise ApiError("ERR_VALIDATION", 400, "liveaboard_cap must be integer")
    if cap < 0:
        raise ApiError("ERR_LIVEABOARD_CAP_NEGATIVE", 400, "liveaboard_cap must be >= 0")
    if to_date(data["season_end_date"]) < to_date(data["season_start_date"]):
        raise ApiError("ERR_INVALID_DATE_RANGE", 400, "season_end before season_start")
    m = base_common()
    m.update({
        "name": data["name"],
        "season_start_date": data["season_start_date"],
        "season_end_date": data["season_end_date"],
        "liveaboard_cap": cap,
        "pumpout_interval_days": data.get("pumpout_interval_days", DEFAULT_PUMPOUT_INTERVAL_DAYS),
        "available_slip_count": 0,
        "occupied_slip_count": 0,
        "available_mooring_count": 0,
        "occupied_mooring_count": 0,
        "liveaboard_count": 0,
        "waitlist_length": 0,
    })
    store.marinas[m["id"]] = m
    return ok(serialize(m), 201)


@app.route("/marina/marinas/<marina_id>", methods=["GET"])
def get_marina(marina_id):
    authn()
    m = get_or_404(store.marinas, marina_id)
    recompute_marina(m)
    return ok(serialize(m))


@app.route("/marina/marinas/<marina_id>/run-maintenance", methods=["POST"])
def maintenance(marina_id):
    _, role = authn()
    authz(role, {"Harbormaster"})
    m = get_or_404(store.marinas, marina_id)
    run_maintenance(m)
    return ok(serialize(m))


# ===========================================================================
# Berth
# ===========================================================================
@app.route("/marina/berths", methods=["POST"])
def create_berth():
    _, role = authn()
    authz(role, {"Harbormaster"})
    data = body()
    require_fields(data, ["marina_id", "berth_type", "size_class", "max_length_ft"])
    require_enum(data["berth_type"], {"SLIP", "MOORING"}, "berth_type")
    require_enum(data["size_class"], {"SMALL", "MEDIUM", "LARGE"}, "size_class")
    m = get_or_404(store.marinas, data["marina_id"])
    b = base_common()
    b.update({
        "marina_id": data["marina_id"],
        "berth_type": data["berth_type"],
        "size_class": data["size_class"],
        "max_length_ft": data["max_length_ft"],
        "resident_only": bool(data.get("resident_only", False)),
        "status": "AVAILABLE",
        "current_permit_id": None,
    })
    store.berths[b["id"]] = b
    recompute_marina(m)
    return ok(serialize(b), 201)


@app.route("/marina/berths/<berth_id>", methods=["GET"])
def get_berth(berth_id):
    authn()
    b = get_or_404(store.berths, berth_id)
    return ok(serialize(b))


@app.route("/marina/berths", methods=["GET"])
def list_berths():
    authn()
    items = list(store.berths.values())
    if "marina_id" in request.args:
        items = [b for b in items if b["marina_id"] == request.args["marina_id"]]
    if "berth_type" in request.args:
        items = [b for b in items if b["berth_type"] == request.args["berth_type"]]
    if "status" in request.args:
        items = [b for b in items if b["status"] == request.args["status"]]
    return list_response(items, serialize)


# ===========================================================================
# Boater
# ===========================================================================
@app.route("/marina/boaters", methods=["POST"])
def create_boater():
    _, role = authn()
    authz(role, {"Harbormaster"})
    data = body()
    require_fields(data, ["full_name", "email", "residency_status"])
    require_enum(data["residency_status"], {"RESIDENT", "NON_RESIDENT"}, "residency_status")
    bo = base_common()
    bo.update({
        "full_name": data["full_name"],
        "email": data["email"],
        "residency_status": data["residency_status"],
        "street_address": data.get("street_address"),
        "account_status": "ACTIVE",
    })
    store.boaters[bo["id"]] = bo
    return ok(serialize(bo), 201)


@app.route("/marina/boaters/<boater_id>", methods=["GET"])
def get_boater(boater_id):
    authn()
    bo = get_or_404(store.boaters, boater_id)
    return ok(serialize(bo))


# ===========================================================================
# Vessel
# ===========================================================================
@app.route("/marina/vessels", methods=["POST"])
def create_vessel():
    user_id, role = authn()
    authz(role, {"Harbormaster", "Boater"})
    data = body()
    require_fields(data, ["boater_id", "name", "length_ft", "registration_number",
                          "registration_expiry_date", "has_holding_tank"])
    bo = get_or_404(store.boaters, data["boater_id"])
    require_owner(role, user_id, bo["id"])
    v = base_common()
    v.update({
        "boater_id": data["boater_id"],
        "name": data["name"],
        "length_ft": data["length_ft"],
        "registration_number": data["registration_number"],
        "registration_expiry_date": data["registration_expiry_date"],
        "has_holding_tank": bool(data["has_holding_tank"]),
        "_revoked": False,
    })
    store.vessels[v["id"]] = v
    return ok(serialize_vessel(v), 201)


@app.route("/marina/vessels/<vessel_id>", methods=["GET"])
def get_vessel(vessel_id):
    user_id, role = authn()
    v = get_or_404(store.vessels, vessel_id)
    require_owner(role, user_id, v["boater_id"])
    return ok(serialize_vessel(v))


@app.route("/marina/vessels", methods=["GET"])
def list_vessels():
    authn()
    items = list(store.vessels.values())
    if "boater_id" in request.args:
        items = [v for v in items if v["boater_id"] == request.args["boater_id"]]
    if "registration_status" in request.args:
        items = [v for v in items if vessel_reg_status(v) == request.args["registration_status"]]
    return list_response(items, serialize_vessel)


@app.route("/marina/vessels/<vessel_id>/pump-out-records", methods=["POST"])
def create_pumpout(vessel_id):
    user_id, role = authn()
    authz(role, {"Harbormaster", "Boater"})
    v = get_or_404(store.vessels, vessel_id)
    require_owner(role, user_id, v["boater_id"])
    data = body()
    require_fields(data, ["pumpout_date"])
    rec = {
        "id": core.gen_id(),
        "created_at": now_iso(),
        "_seq": store.next_seq(),
        "vessel_id": vessel_id,
        "pumpout_date": data["pumpout_date"],
        "recorded_by_role": role,
    }
    store.pumpouts[rec["id"]] = rec
    touch(v)
    # cure any SUSPENDED permit that becomes compliant
    for p in store.permits.values():
        if p["vessel_id"] == vessel_id and p["status"] == "SUSPENDED":
            m = store.marinas.get(p["marina_id"])
            interval = m.get("pumpout_interval_days", DEFAULT_PUMPOUT_INTERVAL_DAYS) if m else DEFAULT_PUMPOUT_INTERVAL_DAYS
            if core.days_since_pumpout(v, p) <= interval:
                p["status"] = "ACTIVE"
                touch(p)
                if m:
                    recompute_marina(m)
    return ok(serialize(rec), 201)


@app.route("/marina/vessels/<vessel_id>/pump-out-records", methods=["GET"])
def list_pumpouts(vessel_id):
    authn()
    get_or_404(store.vessels, vessel_id)
    items = [r for r in store.pumpouts.values() if r["vessel_id"] == vessel_id]
    return list_response(items, serialize)


# ===========================================================================
# Permit
# ===========================================================================
def _new_permit_base(marina, boater, vessel, req_type, req_size, season_year, is_liveaboard, source):
    p = base_common()
    p.update({
        "marina_id": marina["id"],
        "boater_id": boater["id"],
        "vessel_id": vessel["id"],
        "berth_id": None,
        "requested_berth_type": req_type,
        "requested_size_class": req_size,
        "season_year": season_year,
        "season_start_date": marina["season_start_date"],
        "season_end_date": marina["season_end_date"],
        "is_liveaboard": bool(is_liveaboard),
        "source": source,
        "fee_basis": boater["residency_status"],
        "priority_tier": 0 if boater["residency_status"] == "RESIDENT" else 1,
        "provisional_fee_cents": None,
        "final_fee_cents": None,
        "activated_on_date": None,
        "offer_expires_at": None,
        "invoice_id": None,
        "status": "WAITLISTED",
    })
    return p


@app.route("/marina/permits", methods=["POST"])
def create_permit():
    user_id, role = authn()
    authz(role, {"Harbormaster", "Boater"})
    data = body()
    require_fields(data, ["marina_id", "boater_id", "vessel_id",
                          "requested_berth_type", "requested_size_class", "season_year"])
    require_enum(data["requested_berth_type"], {"SLIP", "MOORING"}, "requested_berth_type")
    require_enum(data["requested_size_class"], {"SMALL", "MEDIUM", "LARGE"}, "requested_size_class")
    marina = get_or_404(store.marinas, data["marina_id"])
    boater = get_or_404(store.boaters, data["boater_id"])
    vessel = get_or_404(store.vessels, data["vessel_id"])
    require_owner(role, user_id, boater["id"])
    if vessel_reg_status(vessel) != "REGISTERED":
        raise ApiError("ERR_VESSEL_REGISTRATION_EXPIRED", 422, "Vessel registration is not current")

    p = _new_permit_base(marina, boater, vessel, data["requested_berth_type"],
                         data["requested_size_class"], data["season_year"],
                         data.get("is_liveaboard", False), "DIRECT")

    # Determine immediate-offer vs waitlist among AVAILABLE berths matching type+size
    matches = [b for b in store.berths.values()
               if b["marina_id"] == marina["id"]
               and b["berth_type"] == data["requested_berth_type"]
               and b["size_class"] == data["requested_size_class"]
               and b["status"] == "AVAILABLE"]
    if matches:
        # p7: resident_only honored
        res_ok = [b for b in matches if not b.get("resident_only") or boater["residency_status"] == "RESIDENT"]
        if not res_ok:
            raise ApiError("ERR_BERTH_TYPE_MISMATCH", 422, "resident_only berth requires a resident boater")
        # p10: vessel length fit
        fit = [b for b in res_ok if b["max_length_ft"] >= vessel["length_ft"]]
        if not fit:
            raise ApiError("ERR_VESSEL_TOO_LONG", 422, "Vessel exceeds berth max length")
        fit.sort(key=lambda b: b["_seq"])
        store.permits[p["id"]] = p
        offer_permit(p, fit[0])
    else:
        store.permits[p["id"]] = p
        recompute_marina(marina)
    return ok(serialize(p), 201)


@app.route("/marina/permits/<permit_id>", methods=["GET"])
def get_permit(permit_id):
    user_id, role = authn()
    p = get_or_404(store.permits, permit_id)
    require_owner(role, user_id, p["boater_id"])
    return ok(serialize(p))


@app.route("/marina/permits", methods=["GET"])
def list_permits():
    authn()
    items = list(store.permits.values())
    for key in ("marina_id", "boater_id", "vessel_id", "berth_id", "status"):
        if key in request.args:
            items = [p for p in items if p.get(key) == request.args[key]]
    return list_response(items, serialize)


@app.route("/marina/permits/<permit_id>/cancel", methods=["POST"])
def cancel_permit(permit_id):
    user_id, role = authn()
    authz(role, {"Harbormaster", "Boater"})
    p = get_or_404(store.permits, permit_id)
    require_owner(role, user_id, p["boater_id"])
    if p["status"] == "WAITLISTED":
        p["status"] = "CANCELLED"
        touch(p)
        m = store.marinas.get(p["marina_id"])
        if m:
            recompute_marina(m)
    elif p["status"] == "OFFERED":
        p["status"] = "DECLINED"
        touch(p)
        inv = store.invoices.get(p.get("invoice_id")) if p.get("invoice_id") else None
        if inv is not None and inv["status"] == "UNPAID":
            inv["status"] = "VOID"
            touch(inv)
        berth = store.berths.get(p.get("berth_id"))
        if berth is not None:
            free_berth(berth)
    else:
        raise ApiError("ERR_INVALID_STATE", 409, "Permit cannot be cancelled from its current state")
    return ok(serialize(p))


@app.route("/marina/permits/<permit_id>/revoke", methods=["POST"])
def revoke_permit_endpoint(permit_id):
    _, role = authn()
    authz(role, {"Harbormaster"})
    p = get_or_404(store.permits, permit_id)
    if p["status"] not in ("ACTIVE", "SUSPENDED"):
        raise ApiError("ERR_PERMIT_NOT_ACTIVE", 409, "Permit is not ACTIVE/SUSPENDED")
    revoke_permit(p)
    return ok(serialize(p))


@app.route("/marina/permits/<permit_id>/transfer", methods=["POST"])
def transfer_permit(permit_id):
    _, role = authn()
    authz(role, {"Harbormaster"})
    p = get_or_404(store.permits, permit_id)
    data = body()
    require_fields(data, ["to_boater_id"])
    to_boater = get_or_404(store.boaters, data["to_boater_id"])
    if p["status"] != "ACTIVE":
        raise ApiError("ERR_PERMIT_NOT_ACTIVE", 409, "Permit is not ACTIVE")
    if to_boater["id"] == p["boater_id"]:
        raise ApiError("ERR_TRANSFER_TARGET_INVALID", 422, "Transfer target must differ from current holder")

    # original -> TRANSFERRED
    p["status"] = "TRANSFERRED"
    touch(p)

    marina = store.marinas[p["marina_id"]]
    vessel = store.vessels[p["vessel_id"]]
    berth = store.berths.get(p["berth_id"])

    np = _new_permit_base(marina, to_boater, vessel, p["requested_berth_type"],
                          p["requested_size_class"], p["season_year"],
                          p["is_liveaboard"], "TRANSFER")
    np["berth_id"] = p["berth_id"]
    np["status"] = "ACTIVE"
    np["activated_on_date"] = iso(clock())
    np["provisional_fee_cents"] = p.get("provisional_fee_cents")
    np["final_fee_cents"] = p.get("final_fee_cents")
    store.permits[np["id"]] = np

    inv = issue_invoice("TRANSFER", np["id"], to_boater["id"], TRANSFER_FEE_CENTS,
                        iso(clock() + timedelta(days=14)))
    np["invoice_id"] = inv["id"]
    touch(np)

    if berth is not None:
        berth["current_permit_id"] = np["id"]
        touch(berth)
    recompute_marina(marina)
    return ok(serialize(np))


@app.route("/marina/permits/<permit_id>/reassign-berth", methods=["POST"])
def reassign_berth(permit_id):
    _, role = authn()
    authz(role, {"Harbormaster"})
    p = get_or_404(store.permits, permit_id)
    data = body()
    require_fields(data, ["new_berth_id", "expected_permit_version"])
    new_berth = get_or_404(store.berths, data["new_berth_id"])
    if p["status"] != "ACTIVE":
        raise ApiError("ERR_PERMIT_NOT_ACTIVE", 409, "Permit is not ACTIVE")
    vessel = store.vessels[p["vessel_id"]]
    boater = store.boaters[p["boater_id"]]
    # business checks (per §3.5)
    if new_berth["status"] != "AVAILABLE":
        raise ApiError("ERR_BERTH_NOT_AVAILABLE", 409, "Target berth is not AVAILABLE")
    if vessel["length_ft"] > new_berth["max_length_ft"]:
        raise ApiError("ERR_VESSEL_TOO_LONG", 422, "Vessel exceeds new berth max length")
    if (new_berth["berth_type"] != p["requested_berth_type"]
            or new_berth["size_class"] != p["requested_size_class"]
            or (new_berth.get("resident_only") and p["fee_basis"] != "RESIDENT")):
        raise ApiError("ERR_BERTH_TYPE_MISMATCH", 422, "New berth type/size/residency mismatch")
    if core.season_overlap_conflict(new_berth["id"], p):
        raise ApiError("ERR_BERTH_SEASON_CONFLICT", 409, "Season overlap on new berth")
    # OCC last
    if data["expected_permit_version"] != p["version"]:
        raise ApiError("ERR_STALE_VERSION", 412, "expected_permit_version does not match")

    old_berth = store.berths.get(p["berth_id"])
    # new berth -> OCCUPIED
    new_berth["status"] = "OCCUPIED"
    new_berth["current_permit_id"] = p["id"]
    touch(new_berth)
    p["berth_id"] = new_berth["id"]
    touch(p)
    marina = store.marinas.get(p["marina_id"])
    if marina:
        recompute_marina(marina)
    # old berth -> AVAILABLE (+ waitlist promotion)
    if old_berth is not None:
        free_berth(old_berth)
    return ok(serialize(p))


# ===========================================================================
# Lottery Round
# ===========================================================================
@app.route("/marina/lottery-rounds", methods=["POST"])
def create_round():
    _, role = authn()
    authz(role, {"Harbormaster"})
    data = body()
    require_fields(data, ["marina_id", "season_year", "berth_type",
                          "entry_open_date", "entry_close_date", "berth_ids"])
    require_enum(data["berth_type"], {"SLIP", "MOORING"}, "berth_type")
    get_or_404(store.marinas, data["marina_id"])
    if not isinstance(data["berth_ids"], list):
        raise ApiError("ERR_VALIDATION", 400, "berth_ids must be a list")
    for bid in data["berth_ids"]:
        get_or_404(store.berths, bid)
    if to_date(data["entry_close_date"]) < to_date(data["entry_open_date"]):
        raise ApiError("ERR_INVALID_DATE_RANGE", 400, "entry_close before entry_open")
    r = base_common()
    r.update({
        "marina_id": data["marina_id"],
        "season_year": data["season_year"],
        "berth_type": data["berth_type"],
        "entry_open_date": data["entry_open_date"],
        "entry_close_date": data["entry_close_date"],
        "berth_ids": list(data["berth_ids"]),
        "status": "OPEN",
        "drawn_on_date": None,
    })
    store.rounds[r["id"]] = r
    return ok(serialize(r), 201)


@app.route("/marina/lottery-rounds/<round_id>", methods=["GET"])
def get_round(round_id):
    authn()
    r = get_or_404(store.rounds, round_id)
    return ok(serialize(r))


@app.route("/marina/lottery-rounds", methods=["GET"])
def list_rounds():
    authn()
    items = list(store.rounds.values())
    if "marina_id" in request.args:
        items = [r for r in items if r["marina_id"] == request.args["marina_id"]]
    if "status" in request.args:
        items = [r for r in items if r["status"] == request.args["status"]]
    return list_response(items, serialize)


@app.route("/marina/lottery-rounds/<round_id>/draw", methods=["POST"])
def draw_round(round_id):
    _, role = authn()
    authz(role, {"Harbormaster"})
    r = get_or_404(store.rounds, round_id)
    if r["status"] != "OPEN":
        raise ApiError("ERR_ROUND_ALREADY_DRAWN", 409, "Round is not OPEN")
    if clock().date() <= to_date(r["entry_close_date"]):
        raise ApiError("ERR_ROUND_NOT_CLOSED_FOR_DRAW", 409, "Entry window not closed")
    run_lottery_draw(r)
    return ok(serialize(r))


# ===========================================================================
# Lottery Entry
# ===========================================================================
@app.route("/marina/lottery-entries", methods=["POST"])
def create_entry():
    user_id, role = authn()
    authz(role, {"Harbormaster", "Boater"})
    data = body()
    require_fields(data, ["round_id", "boater_id", "vessel_id"])
    r = get_or_404(store.rounds, data["round_id"])
    boater = get_or_404(store.boaters, data["boater_id"])
    vessel = get_or_404(store.vessels, data["vessel_id"])
    require_owner(role, user_id, boater["id"])
    if vessel_reg_status(vessel) != "REGISTERED":
        raise ApiError("ERR_VESSEL_REGISTRATION_EXPIRED", 422, "Vessel registration is not current")
    now = clock().date()
    if r["status"] != "OPEN" or now < to_date(r["entry_open_date"]) or now > to_date(r["entry_close_date"]):
        raise ApiError("ERR_ENTRY_WINDOW_CLOSED", 409, "Round not open for entries")
    for e in store.entries.values():
        if (e["round_id"] == r["id"] and e["boater_id"] == boater["id"]
                and e["vessel_id"] == vessel["id"] and e["status"] == "ENTERED"):
            raise ApiError("ERR_DUPLICATE_LOTTERY_ENTRY", 409, "Duplicate lottery entry")
    draw_number = sum(1 for e in store.entries.values() if e["round_id"] == r["id"]) + 1
    e = base_common()
    e.update({
        "round_id": r["id"],
        "boater_id": boater["id"],
        "vessel_id": vessel["id"],
        "draw_number": draw_number,
        "priority_tier": 0 if boater["residency_status"] == "RESIDENT" else 1,
        "awarded_berth_id": None,
        "claim_deadline": None,
        "permit_id": None,
        "status": "ENTERED",
    })
    store.entries[e["id"]] = e
    return ok(serialize(e), 201)


@app.route("/marina/lottery-entries/<entry_id>", methods=["GET"])
def get_entry(entry_id):
    user_id, role = authn()
    e = get_or_404(store.entries, entry_id)
    require_owner(role, user_id, e["boater_id"])
    return ok(serialize(e))


@app.route("/marina/lottery-entries", methods=["GET"])
def list_entries():
    authn()
    items = list(store.entries.values())
    for key in ("round_id", "boater_id", "vessel_id", "status"):
        if key in request.args:
            items = [e for e in items if e.get(key) == request.args[key]]
    return list_response(items, serialize)


@app.route("/marina/lottery-entries/<entry_id>/claim", methods=["POST"])
def claim_entry(entry_id):
    user_id, role = authn()
    authz(role, {"Harbormaster", "Boater"})
    e = get_or_404(store.entries, entry_id)
    require_owner(role, user_id, e["boater_id"])
    data = body()
    if e["status"] != "WON":
        raise ApiError("ERR_ENTRY_NOT_WON", 409, "Entry is not WON")
    vessel = store.vessels[e["vessel_id"]]
    if vessel_reg_status(vessel) != "REGISTERED":
        raise ApiError("ERR_VESSEL_REGISTRATION_EXPIRED", 422, "Vessel registration is not current")
    if clock().date() > to_date(e["claim_deadline"]):
        raise ApiError("ERR_CLAIM_DEADLINE_PASSED", 409, "Claim deadline has passed")
    berth = get_or_404(store.berths, e["awarded_berth_id"])
    if berth["status"] != "AVAILABLE":
        raise ApiError("ERR_BERTH_NOT_AVAILABLE", 409, "Awarded berth no longer available")

    rnd = store.rounds[e["round_id"]]
    marina = store.marinas[rnd["marina_id"]]
    boater = store.boaters[e["boater_id"]]
    p = _new_permit_base(marina, boater, vessel, berth["berth_type"], berth["size_class"],
                         rnd["season_year"], data.get("is_liveaboard", False), "LOTTERY")
    store.permits[p["id"]] = p
    offer_permit(p, berth)
    e["status"] = "CLAIMED"
    e["permit_id"] = p["id"]
    touch(e)
    return ok(serialize(p), 201)


# ===========================================================================
# Derelict Report
# ===========================================================================
@app.route("/marina/derelict-reports", methods=["POST"])
def create_derelict():
    _, role = authn()
    authz(role, {"Harbormaster"})
    data = body()
    require_fields(data, ["vessel_id", "reason"])
    get_or_404(store.vessels, data["vessel_id"])
    d = base_common()
    d.update({
        "vessel_id": data["vessel_id"],
        "reason": data["reason"],
        "status": "OPEN",
        "notice_served_date": None,
        "closed_date": None,
        "estimated_cost_cents": None,
        "actual_cost_cents": None,
        "invoice_id": None,
    })
    store.derelicts[d["id"]] = d
    return ok(serialize(d), 201)


@app.route("/marina/derelict-reports/<report_id>", methods=["GET"])
def get_derelict(report_id):
    authn()
    d = get_or_404(store.derelicts, report_id)
    return ok(serialize(d))


@app.route("/marina/derelict-reports", methods=["GET"])
def list_derelicts():
    authn()
    items = list(store.derelicts.values())
    if "vessel_id" in request.args:
        items = [d for d in items if d["vessel_id"] == request.args["vessel_id"]]
    if "status" in request.args:
        items = [d for d in items if d["status"] == request.args["status"]]
    return list_response(items, serialize)


@app.route("/marina/derelict-reports/<report_id>/serve-notice", methods=["POST"])
def serve_notice(report_id):
    _, role = authn()
    authz(role, {"Harbormaster"})
    d = get_or_404(store.derelicts, report_id)
    if d["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE", 409, "Report is not OPEN")
    vessel = store.vessels[d["vessel_id"]]
    d["notice_served_date"] = iso(clock())
    d["estimated_cost_cents"] = NOTICE_FEE_CENTS
    inv = issue_invoice("DERELICT", d["id"], vessel["boater_id"], NOTICE_FEE_CENTS,
                        iso(clock() + timedelta(days=14)))
    d["invoice_id"] = inv["id"]
    d["status"] = "NOTICE_SERVED"
    touch(d)
    return ok(serialize(d))


@app.route("/marina/derelict-reports/<report_id>/close", methods=["POST"])
def close_derelict(report_id):
    _, role = authn()
    authz(role, {"Harbormaster"})
    d = get_or_404(store.derelicts, report_id)
    data = body()
    require_fields(data, ["disposition"])
    require_enum(data["disposition"], {"RESOLVED", "IMPOUNDED"}, "disposition")
    if d["status"] != "NOTICE_SERVED":
        raise ApiError("ERR_INVALID_STATE", 409, "Report is not NOTICE_SERVED")
    d["closed_date"] = iso(clock())
    if data["disposition"] == "RESOLVED":
        d["status"] = "RESOLVED"
        touch(d)
    else:
        d["status"] = "IMPOUNDED"
        actual = derelict_actual_cost(d)
        d["actual_cost_cents"] = actual
        inv = store.invoices.get(d.get("invoice_id")) if d.get("invoice_id") else None
        if inv is not None:
            inv["amount_due_cents"] = actual
            touch(inv)
        touch(d)
        # cascade: vessel REVOKED -> permits REVOKED -> berths freed -> promotion
        vessel = store.vessels[d["vessel_id"]]
        vessel["_revoked"] = True
        touch(vessel)
        affected = sorted(
            [p for p in store.permits.values()
             if p["vessel_id"] == vessel["id"] and p["status"] in ("ACTIVE", "SUSPENDED")],
            key=lambda p: p["_seq"])
        for p in affected:
            revoke_permit(p)
    return ok(serialize(d))


# ===========================================================================
# Ramp Pass
# ===========================================================================
@app.route("/marina/ramp-passes", methods=["POST"])
def create_ramp_pass():
    user_id, role = authn()
    authz(role, {"Harbormaster", "Boater"})
    data = body()
    require_fields(data, ["boater_id", "vessel_id", "pass_type", "valid_from_date", "valid_to_date"])
    require_enum(data["pass_type"], {"DAY", "SEASONAL"}, "pass_type")
    boater = get_or_404(store.boaters, data["boater_id"])
    vessel = get_or_404(store.vessels, data["vessel_id"])
    require_owner(role, user_id, boater["id"])
    if to_date(data["valid_to_date"]) < to_date(data["valid_from_date"]):
        raise ApiError("ERR_INVALID_DATE_RANGE", 400, "valid_to before valid_from")
    if vessel_reg_status(vessel) != "REGISTERED":
        raise ApiError("ERR_VESSEL_REGISTRATION_EXPIRED", 422, "Vessel registration is not current")
    if data["pass_type"] == "SEASONAL":
        nf = to_date(data["valid_from_date"])
        nt = to_date(data["valid_to_date"])
        for rp in store.ramppasses.values():
            if rp["boater_id"] == boater["id"] and rp["pass_type"] == "SEASONAL" and rp["status"] == "ACTIVE":
                if nf <= to_date(rp["valid_to_date"]) and to_date(rp["valid_from_date"]) <= nt:
                    raise ApiError("ERR_RAMP_PASS_OVERLAP", 409, "Overlapping seasonal ramp pass")
    fee_basis = boater["residency_status"]
    fee = ramp_pass_fee(data["pass_type"], fee_basis)
    rp = base_common()
    rp.update({
        "boater_id": boater["id"],
        "vessel_id": vessel["id"],
        "pass_type": data["pass_type"],
        "valid_from_date": data["valid_from_date"],
        "valid_to_date": data["valid_to_date"],
        "fee_basis": fee_basis,
        "fee_cents": fee,
        "invoice_id": None,
        "status": "ACTIVE",
    })
    store.ramppasses[rp["id"]] = rp
    inv = issue_invoice("RAMP_PASS", rp["id"], boater["id"], fee, data["valid_to_date"])
    rp["invoice_id"] = inv["id"]
    touch(rp)
    return ok(serialize(rp), 201)


@app.route("/marina/ramp-passes/<pass_id>", methods=["GET"])
def get_ramp_pass(pass_id):
    user_id, role = authn()
    rp = get_or_404(store.ramppasses, pass_id)
    require_owner(role, user_id, rp["boater_id"])
    return ok(serialize(rp))


@app.route("/marina/ramp-passes", methods=["GET"])
def list_ramp_passes():
    authn()
    items = list(store.ramppasses.values())
    for key in ("boater_id", "vessel_id", "status"):
        if key in request.args:
            items = [rp for rp in items if rp.get(key) == request.args[key]]
    return list_response(items, serialize)


@app.route("/marina/ramp-passes/<pass_id>/revoke", methods=["POST"])
def revoke_ramp_pass(pass_id):
    _, role = authn()
    authz(role, {"Harbormaster"})
    rp = get_or_404(store.ramppasses, pass_id)
    if rp["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "Ramp pass is not ACTIVE")
    rp["status"] = "REVOKED"
    touch(rp)
    inv = store.invoices.get(rp.get("invoice_id")) if rp.get("invoice_id") else None
    if inv is not None and inv["status"] == "UNPAID":
        inv["status"] = "VOID"
        touch(inv)
    return ok(serialize(rp))


# ===========================================================================
# Invoice / Billing
# ===========================================================================
@app.route("/marina/invoices/<invoice_id>", methods=["GET"])
def get_invoice(invoice_id):
    user_id, role = authn()
    inv = get_or_404(store.invoices, invoice_id)
    require_owner(role, user_id, inv["boater_id"])
    return ok(serialize(inv))


@app.route("/marina/invoices", methods=["GET"])
def list_invoices():
    authn()
    items = list(store.invoices.values())
    for key in ("boater_id", "status", "invoice_type"):
        if key in request.args:
            items = [inv for inv in items if inv.get(key) == request.args[key]]
    return list_response(items, serialize)


@app.route("/marina/invoices/<invoice_id>/pay", methods=["POST"])
def pay_invoice(invoice_id):
    user_id, role = authn()
    authz(role, {"Harbormaster", "FinanceClerk", "Boater"})
    inv = get_or_404(store.invoices, invoice_id)
    require_owner(role, user_id, inv["boater_id"])
    data = body()
    require_fields(data, ["amount_cents"])
    if inv["status"] != "UNPAID":
        raise ApiError("ERR_INVOICE_NOT_PAYABLE", 409, "Invoice is not payable")
    if data["amount_cents"] != inv["amount_due_cents"]:
        raise ApiError("ERR_PAYMENT_AMOUNT_MISMATCH", 422, "Payment amount must equal amount due")

    permit = None
    if inv["invoice_type"] == "PERMIT":
        permit = store.permits.get(inv["reference_id"])
        if permit is not None and permit["status"] == "OFFERED":
            check_activation(permit)  # raises before any commit

    inv["amount_paid_cents"] = inv["amount_due_cents"]
    inv["status"] = "PAID"
    touch(inv)
    if permit is not None and permit["status"] == "OFFERED":
        activate_permit(permit, inv, via_waive=False)
    return ok(serialize(inv))


@app.route("/marina/invoices/<invoice_id>/waive", methods=["POST"])
def waive_invoice(invoice_id):
    _, role = authn()
    authz(role, {"FinanceClerk"})
    inv = get_or_404(store.invoices, invoice_id)
    if inv["status"] != "UNPAID":
        raise ApiError("ERR_INVOICE_NOT_PAYABLE", 409, "Invoice is not payable")

    permit = None
    if inv["invoice_type"] == "PERMIT":
        permit = store.permits.get(inv["reference_id"])
        if permit is not None and permit["status"] == "OFFERED":
            check_activation(permit)

    inv["status"] = "WAIVED"
    touch(inv)
    if permit is not None and permit["status"] == "OFFERED":
        activate_permit(permit, inv, via_waive=True)
    return ok(serialize(inv))


# ===========================================================================
# Logical clock
# ===========================================================================
@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    _, role = authn()
    authz(role, {"Harbormaster"})
    data = body()
    require_fields(data, ["to_iso8601"])
    try:
        store.clock = parse_dt(data["to_iso8601"])
    except (ValueError, TypeError):
        raise ApiError("ERR_VALIDATION", 400, "Invalid to_iso8601")
    return ok({})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
