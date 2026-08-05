"""Precinct Boundary & Redistricting Management API (Flask, in-memory)."""

import os
import random
import string
from datetime import datetime
from uuid import uuid4

from flask import Flask, request, jsonify

import core
from core import (
    db, VALID_ROLES, ALL_ROLES, SETUP_BUFFER_MINUTES,
    parse_iso, render_ts, rhu, num, new_base, touch,
)
from decimal import Decimal

app = Flask(__name__)


# ---------------------------------------------------------------------------
# Errors + response envelope
# ---------------------------------------------------------------------------
class ApiError(Exception):
    def __init__(self, error_id, http_status, message=""):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


def _meta(extra=None):
    rid = "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))
    m = {"api_request_id": rid, "api_request_timestamp": render_ts(db.clock)}
    if extra:
        m.update(extra)
    return m


def ok(data, response_type="object", status=200, pagination=None):
    body = {"meta": _meta(pagination), "response_type": response_type, "data": data}
    return jsonify(body), status


def err_response(error_id, http_status, message):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), http_status


@app.errorhandler(ApiError)
def handle_api_error(e):
    return err_response(e.error_id, e.http_status, e.message)


@app.errorhandler(404)
def handle_404(e):
    return err_response("ERR_VALIDATION", 404, "Not found")


@app.errorhandler(405)
def handle_405(e):
    return err_response("ERR_VALIDATION", 405, "Method not allowed")


@app.errorhandler(Exception)
def handle_unexpected(e):
    if isinstance(e, ApiError):
        return handle_api_error(e)
    return err_response("ERR_VALIDATION", 500, "Internal error: %s" % e)


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
def authenticate(allowed_roles):
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in VALID_ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", 401, "Missing or unrecognized credentials")
    if role not in allowed_roles:
        raise ApiError("ERR_UNAUTHORIZED", 403, "Role not permitted for this operation")
    return uid, role


def body():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return {}
    return data


# ---------------------------------------------------------------------------
# Lookup helpers (raise the correct not-found error)
# ---------------------------------------------------------------------------
def get_or_404(store, key, error_id):
    rec = store.get(key)
    if rec is None:
        raise ApiError(error_id, 404, "Resource not found")
    return rec


def require_fields(data, fields):
    for f in fields:
        if data.get(f) is None:
            raise ApiError("ERR_VALIDATION", 422, "Missing required field: %s" % f)


def require_int(value, name, minimum=None):
    if not isinstance(value, int) or isinstance(value, bool):
        raise ApiError("ERR_VALIDATION", 422, "%s must be an integer" % name)
    if minimum is not None and value < minimum:
        raise ApiError("ERR_VALIDATION", 422, "%s must be >= %s" % (name, minimum))
    return value


def paginate(items):
    args = request.args
    try:
        limit = int(args.get("limit", 10))
    except (TypeError, ValueError):
        limit = 10
    try:
        offset = int(args.get("offset", 0))
    except (TypeError, ValueError):
        offset = 0
    if limit > 100:
        limit = 100
    if limit < 1:
        limit = 1
    if offset < 0:
        offset = 0
    items = sorted(items, key=lambda r: r["_seq"])
    total = len(items)
    page = items[offset:offset + limit]
    meta = {"limit": limit, "offset": offset, "total_count": total,
            "has_more": offset + limit < total}
    return page, meta


def list_response(items, serializer):
    page, meta = paginate(items)
    return ok([serializer(r) for r in page], response_type="array",
              status=200, pagination=meta)


# ---------------------------------------------------------------------------
# Cascade helpers
# ---------------------------------------------------------------------------
def dismiss_pending_comments(plan_id):
    for c in db.comments.values():
        if c["plan_id"] == plan_id and c["disposition"] == "PENDING":
            c["disposition"] = "DISMISSED"
            touch(c)


def cancel_scheduled_hearings(plan_id):
    for h in db.hearings.values():
        if h["plan_id"] == plan_id and h["status"] == "SCHEDULED":
            h["status"] = "CANCELLED"
            touch(h)


def supersede_sibling_plans(jurisdiction_id, adopted_plan_id):
    terminal = {"ADOPTED", "REJECTED", "SUPERSEDED"}
    for p in db.plans.values():
        if p["jurisdiction_id"] != jurisdiction_id:
            continue
        if p["id"] == adopted_plan_id:
            continue
        if p["status"] in terminal:
            continue
        p["status"] = "SUPERSEDED"
        touch(p)
        dismiss_pending_comments(p["id"])
        cancel_scheduled_hearings(p["id"])


def set_block_precinct(block, precinct_id):
    if block.get("precinct_id") != precinct_id:
        block["precinct_id"] = precinct_id
        touch(block)


# ===========================================================================
# ROUTES
# ===========================================================================

@app.post("/_clock/set_current_utc")
def set_clock():
    authenticate(["Cartographer", "Demographer", "CommissionChair", "ElectionClerk"])
    data = body()
    val = data.get("to_iso8601")
    if val is None:
        raise ApiError("ERR_VALIDATION", 422, "to_iso8601 required")
    try:
        db.clock = parse_iso(val)
    except Exception:
        raise ApiError("ERR_VALIDATION", 422, "invalid to_iso8601")
    return ok({}, response_type="object", status=200)


# --- Jurisdiction ---
@app.post("/jurisdictions")
def create_jurisdiction():
    authenticate(["Cartographer"])
    data = body()
    require_fields(data, ["name", "state_code", "target_district_count"])
    tc = data["target_district_count"]
    require_int(tc, "target_district_count", minimum=1)
    rmm = data.get("required_majority_minority_districts", 0)
    if rmm is None:
        rmm = 0
    require_int(rmm, "required_majority_minority_districts", minimum=0)
    if not isinstance(data["name"], str) or not isinstance(data["state_code"], str):
        raise ApiError("ERR_VALIDATION", 422, "name/state_code must be strings")
    rec = new_base()
    rec.update({
        "name": data["name"],
        "state_code": data["state_code"],
        "target_district_count": tc,
        "required_majority_minority_districts": rmm,
    })
    db.jurisdictions[rec["id"]] = rec
    return ok(core.ser_jurisdiction(rec), status=201)


@app.get("/jurisdictions/<jurisdiction_id>")
def read_jurisdiction(jurisdiction_id):
    authenticate(ALL_ROLES)
    j = get_or_404(db.jurisdictions, jurisdiction_id, "ERR_JURISDICTION_NOT_FOUND")
    return ok(core.ser_jurisdiction(j))


# --- CensusBlock ---
@app.post("/jurisdictions/<jurisdiction_id>/census-blocks")
def create_census_block(jurisdiction_id):
    authenticate(["Cartographer"])
    j = get_or_404(db.jurisdictions, jurisdiction_id, "ERR_JURISDICTION_NOT_FOUND")
    data = body()
    geoid = data.get("geoid")
    # uniqueness (priority 7) before field validity (priority 12)
    if geoid is not None:
        for b in db.census_blocks.values():
            if b["jurisdiction_id"] == j["id"] and b["geoid"] == geoid:
                raise ApiError("ERR_DUPLICATE_GEOID", 409, "geoid already used in jurisdiction")
    require_fields(data, ["geoid", "population", "voting_age_population",
                          "minority_vap", "registered_voters"])
    pop = require_int(data["population"], "population", minimum=0)
    vap = require_int(data["voting_age_population"], "voting_age_population", minimum=0)
    mvap = require_int(data["minority_vap"], "minority_vap", minimum=0)
    rv = require_int(data["registered_voters"], "registered_voters", minimum=0)
    if vap > pop:
        raise ApiError("ERR_VALIDATION", 422, "voting_age_population may not exceed population")
    if mvap > vap:
        raise ApiError("ERR_VALIDATION", 422, "minority_vap may not exceed voting_age_population")
    rec = new_base()
    rec.update({
        "jurisdiction_id": j["id"],
        "geoid": geoid,
        "population": pop,
        "voting_age_population": vap,
        "minority_vap": mvap,
        "registered_voters": rv,
        "precinct_id": None,
    })
    db.census_blocks[rec["id"]] = rec
    return ok(core.ser_census_block(rec), status=201)


@app.get("/census-blocks/<census_block_id>")
def read_census_block(census_block_id):
    authenticate(ALL_ROLES)
    b = get_or_404(db.census_blocks, census_block_id, "ERR_CENSUS_BLOCK_NOT_FOUND")
    return ok(core.ser_census_block(b))


@app.get("/census-blocks")
def list_census_blocks():
    authenticate(ALL_ROLES)
    jid = request.args.get("jurisdiction_id")
    pid = request.args.get("precinct_id")
    items = list(db.census_blocks.values())
    if jid is not None:
        items = [b for b in items if b["jurisdiction_id"] == jid]
    if pid is not None:
        items = [b for b in items if b.get("precinct_id") == pid]
    return list_response(items, core.ser_census_block)


# --- Precinct ---
@app.post("/jurisdictions/<jurisdiction_id>/precincts")
def create_precinct(jurisdiction_id):
    authenticate(["ElectionClerk"])
    j = get_or_404(db.jurisdictions, jurisdiction_id, "ERR_JURISDICTION_NOT_FOUND")
    data = body()
    require_fields(data, ["name"])
    block_ids = data.get("census_block_ids") or []
    if not isinstance(block_ids, list):
        raise ApiError("ERR_VALIDATION", 422, "census_block_ids must be a list")
    blocks = []
    for bid in block_ids:
        b = db.census_blocks.get(bid)
        if b is None:
            raise ApiError("ERR_CENSUS_BLOCK_NOT_FOUND", 404, "census block not found")
        blocks.append(b)
    rec = new_base()
    rec.update({
        "jurisdiction_id": j["id"],
        "name": data["name"],
        "parent_precinct_id": None,
        "status": "ACTIVE",
        "voter_count_basis": "PROVISIONAL",
    })
    db.precincts[rec["id"]] = rec
    for b in blocks:
        set_block_precinct(b, rec["id"])
    return ok(core.ser_precinct(rec), status=201)


@app.get("/precincts")
def list_precincts():
    authenticate(ALL_ROLES)
    jid = request.args.get("jurisdiction_id")
    parent = request.args.get("parent_precinct_id")
    items = list(db.precincts.values())
    if jid is not None:
        items = [p for p in items if p["jurisdiction_id"] == jid]
    if parent is not None:
        items = [p for p in items if p.get("parent_precinct_id") == parent]
    return list_response(items, core.ser_precinct)


@app.get("/precincts/<precinct_id>")
def read_precinct(precinct_id):
    authenticate(ALL_ROLES)
    p = get_or_404(db.precincts, precinct_id, "ERR_PRECINCT_NOT_FOUND")
    return ok(core.ser_precinct(p))


@app.post("/precincts/<precinct_id>/split")
def split_precinct(precinct_id):
    authenticate(["ElectionClerk"])
    p = get_or_404(db.precincts, precinct_id, "ERR_PRECINCT_NOT_FOUND")
    if p["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "precinct is not ACTIVE")
    data = body()
    require_fields(data, ["child_a_name", "child_a_block_geoids",
                          "child_b_name", "child_b_block_geoids"])
    a_geoids = data["child_a_block_geoids"]
    b_geoids = data["child_b_block_geoids"]
    if not isinstance(a_geoids, list) or not isinstance(b_geoids, list):
        raise ApiError("ERR_VALIDATION", 422, "block geoid groups must be lists")
    cur_blocks = core.precinct_blocks(p["id"])
    cur_geoids = [b["geoid"] for b in cur_blocks]
    # partition constraint (priority 7)
    combined = list(a_geoids) + list(b_geoids)
    if sorted(combined) != sorted(cur_geoids) or len(set(combined)) != len(combined):
        raise ApiError("ERR_INCOMPLETE_PARTITION", 409,
                       "split groups do not exactly partition the precinct's blocks")
    # >= 2 active blocks (priority 12)
    if len(cur_blocks) < 2:
        raise ApiError("ERR_VALIDATION", 422, "cannot split fewer than 2 blocks")
    geoid_to_block = {b["geoid"]: b for b in cur_blocks}
    child_a = new_base()
    child_a.update({
        "jurisdiction_id": p["jurisdiction_id"],
        "name": data["child_a_name"],
        "parent_precinct_id": p["id"],
        "status": "ACTIVE",
        "voter_count_basis": "PROVISIONAL",
    })
    child_b = new_base()
    child_b.update({
        "jurisdiction_id": p["jurisdiction_id"],
        "name": data["child_b_name"],
        "parent_precinct_id": p["id"],
        "status": "ACTIVE",
        "voter_count_basis": "PROVISIONAL",
    })
    db.precincts[child_a["id"]] = child_a
    db.precincts[child_b["id"]] = child_b
    for g in a_geoids:
        set_block_precinct(geoid_to_block[g], child_a["id"])
    for g in b_geoids:
        set_block_precinct(geoid_to_block[g], child_b["id"])
    p["status"] = "SPLIT"
    touch(p)
    return ok(core.ser_precinct(p), status=201)


@app.post("/precincts/<precinct_id>/merge")
def merge_precinct(precinct_id):
    authenticate(["ElectionClerk"])
    p = get_or_404(db.precincts, precinct_id, "ERR_PRECINCT_NOT_FOUND")
    data = body()
    target_id = data.get("target_precinct_id")
    if target_id is None:
        raise ApiError("ERR_VALIDATION", 422, "target_precinct_id required")
    target = db.precincts.get(target_id)
    if target is None:
        raise ApiError("ERR_PRECINCT_NOT_FOUND", 404, "target precinct not found")
    if p["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "precinct is not ACTIVE")
    if target["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "target precinct is not ACTIVE")
    if target["jurisdiction_id"] != p["jurisdiction_id"]:
        raise ApiError("ERR_PRECINCT_JURISDICTION_MISMATCH", 422,
                       "target precinct in a different jurisdiction")
    if target_id == p["id"]:
        raise ApiError("ERR_VALIDATION", 422, "cannot merge a precinct into itself")
    for b in core.precinct_blocks(p["id"]):
        set_block_precinct(b, target["id"])
    p["status"] = "MERGED"
    touch(p)
    return ok(core.ser_precinct(p), status=200)


@app.post("/precincts/<precinct_id>/retire")
def retire_precinct(precinct_id):
    authenticate(["ElectionClerk"])
    p = get_or_404(db.precincts, precinct_id, "ERR_PRECINCT_NOT_FOUND")
    if p["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "precinct is not ACTIVE")
    if core.precinct_blocks(p["id"]):
        raise ApiError("ERR_PRECINCT_NOT_EMPTY", 409, "precinct still holds blocks")
    has_active_pa = any(pa["precinct_id"] == p["id"] and pa["status"] == "ACTIVE"
                        for pa in db.polling_assignments.values())
    if has_active_pa:
        raise ApiError("ERR_PRECINCT_NOT_EMPTY", 409, "precinct has an active polling assignment")
    p["status"] = "RETIRED"
    touch(p)
    return ok(core.ser_precinct(p), status=200)


@app.post("/precincts/<precinct_id>/certify")
def certify_precinct(precinct_id):
    authenticate(["ElectionClerk"])
    p = get_or_404(db.precincts, precinct_id, "ERR_PRECINCT_NOT_FOUND")
    if p["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "precinct is not ACTIVE")
    p["voter_count_basis"] = "CERTIFIED"
    touch(p)
    return ok(core.ser_precinct(p), status=200)


# --- Venue ---
@app.post("/jurisdictions/<jurisdiction_id>/venues")
def create_venue(jurisdiction_id):
    authenticate(["ElectionClerk"])
    j = get_or_404(db.jurisdictions, jurisdiction_id, "ERR_JURISDICTION_NOT_FOUND")
    data = body()
    require_fields(data, ["name", "capacity"])
    cap = require_int(data["capacity"], "capacity", minimum=1)
    rec = new_base()
    rec.update({"jurisdiction_id": j["id"], "name": data["name"], "capacity": cap})
    db.venues[rec["id"]] = rec
    return ok(core.ser_venue(rec), status=201)


@app.get("/venues/<venue_id>")
def read_venue(venue_id):
    authenticate(ALL_ROLES)
    v = get_or_404(db.venues, venue_id, "ERR_POLLING_PLACE_NOT_FOUND")
    return ok(core.ser_venue(v))


@app.get("/venues")
def list_venues():
    authenticate(ALL_ROLES)
    jid = request.args.get("jurisdiction_id")
    items = list(db.venues.values())
    if jid is not None:
        items = [v for v in items if v["jurisdiction_id"] == jid]
    return list_response(items, core.ser_venue)


# --- PollingPlace ---
@app.post("/jurisdictions/<jurisdiction_id>/polling-places")
def create_polling_place(jurisdiction_id):
    authenticate(["ElectionClerk"])
    j = get_or_404(db.jurisdictions, jurisdiction_id, "ERR_JURISDICTION_NOT_FOUND")
    data = body()
    require_fields(data, ["name", "address", "capacity"])
    cap = require_int(data["capacity"], "capacity", minimum=1)
    rec = new_base()
    rec.update({
        "jurisdiction_id": j["id"],
        "name": data["name"],
        "address": data["address"],
        "capacity": cap,
        "status": "ACTIVE",
    })
    db.polling_places[rec["id"]] = rec
    return ok(core.ser_polling_place(rec), status=201)


@app.get("/polling-places/<polling_place_id>")
def read_polling_place(polling_place_id):
    authenticate(ALL_ROLES)
    pp = get_or_404(db.polling_places, polling_place_id, "ERR_POLLING_PLACE_NOT_FOUND")
    return ok(core.ser_polling_place(pp))


@app.get("/polling-places")
def list_polling_places():
    authenticate(ALL_ROLES)
    jid = request.args.get("jurisdiction_id")
    items = list(db.polling_places.values())
    if jid is not None:
        items = [pp for pp in items if pp["jurisdiction_id"] == jid]
    return list_response(items, core.ser_polling_place)


@app.post("/polling-places/<polling_place_id>/close")
def close_polling_place(polling_place_id):
    authenticate(["ElectionClerk"])
    pp = get_or_404(db.polling_places, polling_place_id, "ERR_POLLING_PLACE_NOT_FOUND")
    if pp["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "polling place is not ACTIVE")
    if core.active_place_assignments(pp["id"]):
        raise ApiError("ERR_POLLING_PLACE_IN_USE", 409, "polling place has an active assignment")
    pp["status"] = "CLOSED"
    touch(pp)
    return ok(core.ser_polling_place(pp), status=200)


# --- PollingAssignment ---
def _valid_date(s):
    try:
        datetime.strptime(s, "%Y-%m-%d")
        return True
    except (TypeError, ValueError):
        return False


@app.post("/precincts/<precinct_id>/polling-assignments")
def create_polling_assignment(precinct_id):
    authenticate(["ElectionClerk"])
    p = get_or_404(db.precincts, precinct_id, "ERR_PRECINCT_NOT_FOUND")
    data = body()
    place_id = data.get("polling_place_id")
    # body FK existence (priority 4)
    if place_id is not None:
        place = db.polling_places.get(place_id)
        if place is None:
            raise ApiError("ERR_POLLING_PLACE_NOT_FOUND", 404, "polling place not found")
    else:
        place = None
    # state (priority 5): referenced polling place must be ACTIVE
    if place is not None and place["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "polling place is not ACTIVE")
    ev_start = data.get("ev_start_date")
    ev_end = data.get("ev_end_date")
    # temporal overlap (priority 8) — only when we have a valid window + place
    if place is not None and _valid_date(ev_start) and _valid_date(ev_end):
        for pa in core.active_place_assignments(place["id"]):
            if pa["precinct_id"] == p["id"]:
                continue
            if ev_start <= pa["ev_end_date"] and pa["ev_start_date"] <= ev_end:
                raise ApiError("ERR_EV_WINDOW_CONFLICT", 409,
                               "early-voting window overlaps another precinct's window")
        # capacity (priority 9)
        prospective = 0
        for pa in core.active_place_assignments(place["id"]):
            if pa["precinct_id"] == p["id"]:
                continue
            pr = db.precincts.get(pa["precinct_id"])
            if pr:
                prospective += core.precinct_registered_voters(pr)
        prospective += core.precinct_registered_voters(p)
        if prospective > place["capacity"]:
            raise ApiError("ERR_POLLING_CAPACITY_EXCEEDED", 409,
                           "assignment would exceed polling place capacity")
    # field validity (priority 12)
    require_fields(data, ["polling_place_id", "ev_start_date", "ev_end_date",
                          "expected_precinct_version"])
    if not _valid_date(ev_start) or not _valid_date(ev_end):
        raise ApiError("ERR_VALIDATION", 422, "ev dates must be YYYY-MM-DD")
    if ev_end < ev_start:
        raise ApiError("ERR_INVALID_DATE_RANGE", 422, "ev_end_date before ev_start_date")
    # OCC (priority 13)
    epv = data["expected_precinct_version"]
    if not isinstance(epv, int) or isinstance(epv, bool) or epv != p["version"]:
        raise ApiError("ERR_STALE_PRECINCT_VERSION", 412, "stale precinct version")
    # supersede prior ACTIVE assignment for this precinct
    for pa in db.polling_assignments.values():
        if pa["precinct_id"] == p["id"] and pa["status"] == "ACTIVE":
            pa["status"] = "SUPERSEDED"
            touch(pa)
    rec = new_base()
    rec.update({
        "precinct_id": p["id"],
        "polling_place_id": place["id"],
        "ev_start_date": ev_start,
        "ev_end_date": ev_end,
        "status": "ACTIVE",
    })
    db.polling_assignments[rec["id"]] = rec
    touch(p)  # increments precinct version
    return ok(core.ser_polling_assignment(rec), status=201)


@app.get("/polling-assignments/<polling_assignment_id>")
def read_polling_assignment(polling_assignment_id):
    authenticate(ALL_ROLES)
    pa = get_or_404(db.polling_assignments, polling_assignment_id,
                    "ERR_POLLING_ASSIGNMENT_NOT_FOUND")
    return ok(core.ser_polling_assignment(pa))


@app.get("/polling-assignments")
def list_polling_assignments():
    authenticate(ALL_ROLES)
    pid = request.args.get("precinct_id")
    place_id = request.args.get("polling_place_id")
    items = list(db.polling_assignments.values())
    if pid is not None:
        items = [pa for pa in items if pa["precinct_id"] == pid]
    if place_id is not None:
        items = [pa for pa in items if pa["polling_place_id"] == place_id]
    return list_response(items, core.ser_polling_assignment)


# --- RedistrictingPlan ---
@app.post("/jurisdictions/<jurisdiction_id>/plans")
def create_plan(jurisdiction_id):
    uid, role = authenticate(["Cartographer"])
    j = get_or_404(db.jurisdictions, jurisdiction_id, "ERR_JURISDICTION_NOT_FOUND")
    data = body()
    require_fields(data, ["name"])
    parent_id = data.get("parent_plan_id")
    parent = None
    if parent_id is not None:
        parent = db.plans.get(parent_id)
        if parent is None:
            raise ApiError("ERR_PLAN_NOT_FOUND", 404, "parent plan not found")
    rec = new_base()
    rec.update({
        "jurisdiction_id": j["id"],
        "name": data["name"],
        "parent_plan_id": parent_id,
        "created_by_user_id": uid,
        "status": "DRAFT",
        "comment_opened_at": None,
        "adopted_at": None,
    })
    db.plans[rec["id"]] = rec
    if parent is not None:
        old_to_new = {}
        for d in core.plan_districts(parent["id"]):
            nd = new_base()
            nd.update({
                "plan_id": rec["id"],
                "district_number": d["district_number"],
                "name": d.get("name"),
                "is_contiguous": d["is_contiguous"],
                "incumbent_name": d.get("incumbent_name"),
                "incumbent_home_geoid": d.get("incumbent_home_geoid"),
            })
            db.districts[nd["id"]] = nd
            old_to_new[d["id"]] = nd["id"]
        for ba in list(db.block_assignments.values()):
            if ba["plan_id"] == parent["id"] and ba["status"] == "ACTIVE":
                nba = new_base()
                nba.update({
                    "plan_id": rec["id"],
                    "district_id": old_to_new.get(ba["district_id"]),
                    "census_block_id": ba["census_block_id"],
                    "status": "ACTIVE",
                })
                db.block_assignments[nba["id"]] = nba
    return ok(core.ser_plan(rec), status=201)


@app.get("/plans")
def list_plans():
    authenticate(ALL_ROLES)
    jid = request.args.get("jurisdiction_id")
    parent = request.args.get("parent_plan_id")
    items = list(db.plans.values())
    if jid is not None:
        items = [p for p in items if p["jurisdiction_id"] == jid]
    if parent is not None:
        items = [p for p in items if p.get("parent_plan_id") == parent]
    return list_response(items, core.ser_plan)


@app.get("/plans/<plan_id>")
def read_plan(plan_id):
    authenticate(ALL_ROLES)
    p = get_or_404(db.plans, plan_id, "ERR_PLAN_NOT_FOUND")
    return ok(core.ser_plan(p))


@app.get("/plans/<plan_id>/comparison")
def compare_plans(plan_id):
    authenticate(ALL_ROLES)
    p = get_or_404(db.plans, plan_id, "ERR_PLAN_NOT_FOUND")
    other_id = request.args.get("other_plan_id")
    if other_id is None:
        raise ApiError("ERR_VALIDATION", 422, "other_plan_id required")
    other = db.plans.get(other_id)
    if other is None:
        raise ApiError("ERR_PLAN_NOT_FOUND", 404, "other plan not found")
    m1 = core.plan_metrics(p)
    m2 = core.plan_metrics(other)
    data = {
        "plan_id": p["id"],
        "other_plan_id": other["id"],
        "max_abs_deviation_pct_delta": num(m1["max_abs_deviation_pct"] - m2["max_abs_deviation_pct"]),
        "overall_deviation_range_pct_delta": num(m1["overall_deviation_range_pct"] - m2["overall_deviation_range_pct"]),
        "majority_minority_district_count_delta":
            m1["majority_minority_district_count"] - m2["majority_minority_district_count"],
    }
    return ok(data)


# --- District ---
@app.post("/plans/<plan_id>/districts")
def create_district(plan_id):
    authenticate(["Cartographer"])
    p = get_or_404(db.plans, plan_id, "ERR_PLAN_NOT_FOUND")
    if p["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", 409, "districts may only be added to a DRAFT plan")
    data = body()
    dn = data.get("district_number")
    # uniqueness (priority 7) then field validity (priority 12)
    if isinstance(dn, int) and not isinstance(dn, bool):
        for d in db.districts.values():
            if d["plan_id"] == p["id"] and d["district_number"] == dn:
                raise ApiError("ERR_DUPLICATE_DISTRICT_NUMBER", 409,
                               "district_number already used in plan")
    require_fields(data, ["district_number"])
    require_int(dn, "district_number", minimum=1)
    is_contig = data.get("is_contiguous", True)
    if is_contig is None:
        is_contig = True
    if not isinstance(is_contig, bool):
        raise ApiError("ERR_VALIDATION", 422, "is_contiguous must be boolean")
    rec = new_base()
    rec.update({
        "plan_id": p["id"],
        "district_number": dn,
        "name": data.get("name"),
        "is_contiguous": is_contig,
        "incumbent_name": data.get("incumbent_name"),
        "incumbent_home_geoid": data.get("incumbent_home_geoid"),
    })
    db.districts[rec["id"]] = rec
    return ok(core.ser_district(rec), status=201)


@app.get("/plans/<plan_id>/districts")
def list_districts(plan_id):
    authenticate(ALL_ROLES)
    p = get_or_404(db.plans, plan_id, "ERR_PLAN_NOT_FOUND")
    items = [d for d in db.districts.values() if d["plan_id"] == p["id"]]
    return list_response(items, core.ser_district)


# --- BlockAssignment ---
@app.post("/plans/<plan_id>/block-assignments")
def create_block_assignment(plan_id):
    authenticate(["Cartographer"])
    p = get_or_404(db.plans, plan_id, "ERR_PLAN_NOT_FOUND")
    data = body()
    district_id = data.get("district_id")
    block_id = data.get("census_block_id")
    # body FK existence (priority 4): district then block
    district = None
    if district_id is not None:
        district = db.districts.get(district_id)
        if district is None:
            raise ApiError("ERR_DISTRICT_NOT_FOUND", 404, "district not found")
    block = None
    if block_id is not None:
        block = db.census_blocks.get(block_id)
        if block is None:
            raise ApiError("ERR_CENSUS_BLOCK_NOT_FOUND", 404, "census block not found")
    # state (priority 5)
    if p["status"] not in ("DRAFT", "UNDER_REVIEW"):
        raise ApiError("ERR_INVALID_STATE", 409,
                       "block assignments only in DRAFT/UNDER_REVIEW plans")
    # cross-aggregate (priority 6)
    if district is not None and district["plan_id"] != p["id"]:
        raise ApiError("ERR_DISTRICT_PLAN_MISMATCH", 422, "district belongs to another plan")
    if block is not None and block["jurisdiction_id"] != p["jurisdiction_id"]:
        raise ApiError("ERR_BLOCK_JURISDICTION_MISMATCH", 422,
                       "census block belongs to another jurisdiction")
    # field validity (priority 12)
    require_fields(data, ["district_id", "census_block_id", "expected_plan_version"])
    # OCC (priority 13)
    epv = data["expected_plan_version"]
    if not isinstance(epv, int) or isinstance(epv, bool) or epv != p["version"]:
        raise ApiError("ERR_STALE_PLAN_VERSION", 412, "stale plan version")
    # supersede prior ACTIVE assignment for (plan, block)
    for ba in db.block_assignments.values():
        if (ba["plan_id"] == p["id"] and ba["census_block_id"] == block["id"]
                and ba["status"] == "ACTIVE"):
            ba["status"] = "SUPERSEDED"
            touch(ba)
    rec = new_base()
    rec.update({
        "plan_id": p["id"],
        "district_id": district["id"],
        "census_block_id": block["id"],
        "status": "ACTIVE",
    })
    db.block_assignments[rec["id"]] = rec
    touch(p)  # increments plan version
    return ok(core.ser_block_assignment(rec), status=201)


@app.get("/block-assignments/<block_assignment_id>")
def read_block_assignment(block_assignment_id):
    authenticate(ALL_ROLES)
    ba = get_or_404(db.block_assignments, block_assignment_id,
                    "ERR_BLOCK_ASSIGNMENT_NOT_FOUND")
    return ok(core.ser_block_assignment(ba))


@app.get("/block-assignments")
def list_block_assignments():
    authenticate(ALL_ROLES)
    plan_id = request.args.get("plan_id")
    district_id = request.args.get("district_id")
    block_id = request.args.get("census_block_id")
    items = list(db.block_assignments.values())
    if plan_id is not None:
        items = [ba for ba in items if ba["plan_id"] == plan_id]
    if district_id is not None:
        items = [ba for ba in items if ba["district_id"] == district_id]
    if block_id is not None:
        items = [ba for ba in items if ba["census_block_id"] == block_id]
    return list_response(items, core.ser_block_assignment)


@app.post("/block-assignments/<block_assignment_id>/remove")
def remove_block_assignment(block_assignment_id):
    authenticate(["Cartographer"])
    ba = get_or_404(db.block_assignments, block_assignment_id,
                    "ERR_BLOCK_ASSIGNMENT_NOT_FOUND")
    plan = db.plans[ba["plan_id"]]
    if plan["status"] not in ("DRAFT", "UNDER_REVIEW"):
        raise ApiError("ERR_INVALID_STATE", 409,
                       "removal only in DRAFT/UNDER_REVIEW plans")
    if ba["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "assignment is not ACTIVE")
    ba["status"] = "REMOVED"
    touch(ba)
    touch(plan)
    return ok(core.ser_block_assignment(ba), status=200)


# --- ComplianceCheck ---
def _compute_check(plan, check_type):
    m = core.plan_metrics(plan)
    j = db.jurisdictions[plan["jurisdiction_id"]]
    max_abs = m["max_abs_deviation_pct"]
    mm_count = m["majority_minority_district_count"]
    ds = core.plan_districts(plan["id"])
    if check_type == "POPULATION_DEVIATION":
        if max_abs <= Decimal("5.0"):
            status = "PASS"
        elif max_abs <= Decimal("10.0"):
            status = "WARN"
        else:
            status = "FAIL"
        detail = "max_abs_deviation_pct=%s" % num(max_abs)
    elif check_type == "VRA_MINORITY":
        if mm_count < j["required_majority_minority_districts"]:
            status = "FAIL"
        else:
            has_opp = False
            for d in ds:
                mvp = core.district_metrics(d)["minority_vap_pct"]
                if Decimal("45.0") < mvp <= Decimal("50.0"):
                    has_opp = True
                    break
            status = "WARN" if has_opp else "PASS"
        detail = "majority_minority_district_count=%s" % mm_count
    else:  # CONTIGUITY
        all_contig = all(d["is_contiguous"] for d in ds)
        status = "PASS" if all_contig else "FAIL"
        detail = "all_contiguous=%s" % all_contig
    return status, detail, m


@app.post("/plans/<plan_id>/compliance-checks")
def create_compliance_check(plan_id):
    authenticate(["Demographer"])
    p = get_or_404(db.plans, plan_id, "ERR_PLAN_NOT_FOUND")
    data = body()
    check_type = data.get("check_type")
    if check_type not in ("POPULATION_DEVIATION", "VRA_MINORITY", "CONTIGUITY"):
        raise ApiError("ERR_VALIDATION", 422, "invalid check_type")
    status, detail, m = _compute_check(p, check_type)
    rec = {
        "id": str(uuid4()),
        "created_at": db.clock,
        "_seq": db.next_seq(),
        "plan_id": p["id"],
        "check_type": check_type,
        "result_status": status,
        "max_abs_deviation_pct": m["max_abs_deviation_pct"],
        "overall_deviation_range_pct": m["overall_deviation_range_pct"],
        "majority_minority_district_count": m["majority_minority_district_count"],
        "detail": detail,
    }
    db.compliance_checks[rec["id"]] = rec
    return ok(core.ser_compliance_check(rec), status=201)


@app.get("/plans/<plan_id>/compliance-checks")
def list_compliance_checks(plan_id):
    authenticate(ALL_ROLES)
    p = get_or_404(db.plans, plan_id, "ERR_PLAN_NOT_FOUND")
    items = [c for c in db.compliance_checks.values() if c["plan_id"] == p["id"]]
    return list_response(items, core.ser_compliance_check)


# --- Plan lifecycle ---
@app.post("/plans/<plan_id>/submit-review")
def submit_review(plan_id):
    authenticate(["Cartographer"])
    p = get_or_404(db.plans, plan_id, "ERR_PLAN_NOT_FOUND")
    if p["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", 409, "plan is not DRAFT")
    if not core.plan_districts(p["id"]):
        raise ApiError("ERR_INCOMPLETE_PARTITION", 409, "plan has no districts")
    if not core.full_partition(p):
        raise ApiError("ERR_INCOMPLETE_PARTITION", 409,
                       "plan does not form a complete partition")
    p["status"] = "UNDER_REVIEW"
    touch(p)
    return ok(core.ser_plan(p), status=200)


@app.post("/plans/<plan_id>/open-comment")
def open_comment(plan_id):
    authenticate(["CommissionChair"])
    p = get_or_404(db.plans, plan_id, "ERR_PLAN_NOT_FOUND")
    if p["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_INVALID_STATE", 409, "plan is not UNDER_REVIEW")
    checks = [c for c in db.compliance_checks.values()
              if c["plan_id"] == p["id"] and c["check_type"] == "POPULATION_DEVIATION"]
    if not checks:
        raise ApiError("ERR_DEVIATION_CHECK_FAILED", 422,
                       "no POPULATION_DEVIATION compliance check exists")
    latest = max(checks, key=lambda c: c["_seq"])
    if latest["result_status"] == "FAIL":
        raise ApiError("ERR_DEVIATION_CHECK_FAILED", 422,
                       "latest POPULATION_DEVIATION check failed")
    p["status"] = "COMMENT_OPEN"
    p["comment_opened_at"] = db.clock
    touch(p)
    return ok(core.ser_plan(p), status=200)


@app.post("/plans/<plan_id>/request-revision")
def request_revision(plan_id):
    authenticate(["Demographer"])
    p = get_or_404(db.plans, plan_id, "ERR_PLAN_NOT_FOUND")
    if p["status"] != "HEARING_SCHEDULED":
        raise ApiError("ERR_INVALID_STATE", 409, "plan is not HEARING_SCHEDULED")
    cancel_scheduled_hearings(p["id"])
    p["status"] = "UNDER_REVIEW"
    touch(p)
    return ok(core.ser_plan(p), status=200)


@app.post("/plans/<plan_id>/reject")
def reject_plan(plan_id):
    authenticate(["CommissionChair"])
    p = get_or_404(db.plans, plan_id, "ERR_PLAN_NOT_FOUND")
    if p["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_INVALID_STATE", 409, "plan is not UNDER_REVIEW")
    dismiss_pending_comments(p["id"])
    cancel_scheduled_hearings(p["id"])
    p["status"] = "REJECTED"
    touch(p)
    return ok(core.ser_plan(p), status=200)


@app.post("/plans/<plan_id>/adopt")
def adopt_plan(plan_id):
    uid, role = authenticate(["CommissionChair"])
    p = get_or_404(db.plans, plan_id, "ERR_PLAN_NOT_FOUND")
    if p["status"] != "HEARING_SCHEDULED":
        raise ApiError("ERR_INVALID_STATE", 409, "plan is not HEARING_SCHEDULED")
    has_held = any(h["plan_id"] == p["id"] and h["status"] == "HELD"
                   for h in db.hearings.values())
    if not has_held:
        raise ApiError("ERR_NO_HELD_HEARING", 422, "no HELD hearing on the plan")
    # SoD (priority 10) before compliance gate (priority 11)
    if uid == p["created_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES", 403,
                       "plan creator may not adopt (four-eyes)")
    if not core.plan_is_compliant(p):
        raise ApiError("ERR_PLAN_NOT_COMPLIANT", 422, "plan is not compliant")
    p["status"] = "ADOPTED"
    p["adopted_at"] = db.clock
    touch(p)
    supersede_sibling_plans(p["jurisdiction_id"], p["id"])
    _create_export(p, "GEOJSON")
    return ok(core.ser_plan(p), status=200)


# --- Hearing ---
@app.post("/plans/<plan_id>/hearings")
def schedule_hearing(plan_id):
    authenticate(["CommissionChair"])
    p = get_or_404(db.plans, plan_id, "ERR_PLAN_NOT_FOUND")
    data = body()
    venue_id = data.get("venue_id")
    # body FK existence (priority 4)
    venue = None
    if venue_id is not None:
        venue = db.venues.get(venue_id)
        if venue is None:
            raise ApiError("ERR_POLLING_PLACE_NOT_FOUND", 404, "venue not found")
    # state (priority 5)
    if p["status"] not in ("COMMENT_OPEN", "HEARING_SCHEDULED"):
        raise ApiError("ERR_INVALID_STATE", 409,
                       "hearings may only be scheduled while COMMENT_OPEN or HEARING_SCHEDULED")
    # cross-aggregate (priority 6)
    if venue is not None and venue["jurisdiction_id"] != p["jurisdiction_id"]:
        raise ApiError("ERR_VENUE_JURISDICTION_MISMATCH", 422,
                       "venue in a different jurisdiction")
    ss = data.get("scheduled_start")
    se = data.get("scheduled_end")
    start_dt = end_dt = None
    try:
        if ss is not None:
            start_dt = parse_iso(ss)
        if se is not None:
            end_dt = parse_iso(se)
    except Exception:
        start_dt = end_dt = None
    # temporal overlap (priority 8)
    if venue is not None and start_dt is not None and end_dt is not None:
        buf = SETUP_BUFFER_MINUTES
        from datetime import timedelta
        for h in db.hearings.values():
            if h["status"] != "SCHEDULED" or h["venue_id"] != venue["id"]:
                continue
            e_start = h["_start_dt"]
            e_end = h["_end_dt"]
            if (start_dt < e_end + timedelta(minutes=buf)
                    and e_start < end_dt + timedelta(minutes=buf)):
                raise ApiError("ERR_VENUE_TIME_CONFLICT", 409,
                               "hearing overlaps another at the same venue")
    # field validity (priority 12)
    require_fields(data, ["venue_id", "scheduled_start", "scheduled_end"])
    if start_dt is None or end_dt is None:
        raise ApiError("ERR_VALIDATION", 422, "invalid scheduled_start/scheduled_end")
    if not (end_dt > start_dt):
        raise ApiError("ERR_INVALID_DATE_RANGE", 422, "scheduled_end must be after scheduled_start")
    rec = new_base()
    rec.update({
        "plan_id": p["id"],
        "venue_id": venue["id"],
        "scheduled_start": ss,
        "scheduled_end": se,
        "_start_dt": start_dt,
        "_end_dt": end_dt,
        "status": "SCHEDULED",
    })
    db.hearings[rec["id"]] = rec
    if p["status"] == "COMMENT_OPEN":
        p["status"] = "HEARING_SCHEDULED"
        touch(p)
    return ok(core.ser_hearing(rec), status=201)


@app.get("/hearings/<hearing_id>")
def read_hearing(hearing_id):
    authenticate(ALL_ROLES)
    h = get_or_404(db.hearings, hearing_id, "ERR_HEARING_NOT_FOUND")
    return ok(core.ser_hearing(h))


@app.get("/hearings")
def list_hearings():
    authenticate(ALL_ROLES)
    plan_id = request.args.get("plan_id")
    venue_id = request.args.get("venue_id")
    items = list(db.hearings.values())
    if plan_id is not None:
        items = [h for h in items if h["plan_id"] == plan_id]
    if venue_id is not None:
        items = [h for h in items if h["venue_id"] == venue_id]
    return list_response(items, core.ser_hearing)


@app.post("/hearings/<hearing_id>/hold")
def hold_hearing(hearing_id):
    authenticate(["CommissionChair"])
    h = get_or_404(db.hearings, hearing_id, "ERR_HEARING_NOT_FOUND")
    if h["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE", 409, "hearing is not SCHEDULED")
    if db.clock < h["_start_dt"]:
        raise ApiError("ERR_HEARING_NOT_STARTED", 409, "clock has not reached scheduled_start")
    h["status"] = "HELD"
    touch(h)
    return ok(core.ser_hearing(h), status=200)


@app.post("/hearings/<hearing_id>/cancel")
def cancel_hearing(hearing_id):
    authenticate(["CommissionChair"])
    h = get_or_404(db.hearings, hearing_id, "ERR_HEARING_NOT_FOUND")
    if h["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE", 409, "hearing is not SCHEDULED")
    h["status"] = "CANCELLED"
    touch(h)
    plan = db.plans.get(h["plan_id"])
    if plan and plan["status"] == "HEARING_SCHEDULED":
        others = any(oh["plan_id"] == plan["id"] and oh["status"] == "SCHEDULED"
                     for oh in db.hearings.values())
        if not others:
            plan["status"] = "COMMENT_OPEN"
            touch(plan)
    return ok(core.ser_hearing(h), status=200)


# --- PublicComment ---
@app.post("/plans/<plan_id>/comments")
def create_comment(plan_id):
    authenticate(["PublicParticipant"])
    p = get_or_404(db.plans, plan_id, "ERR_PLAN_NOT_FOUND")
    data = body()
    require_fields(data, ["commenter_name", "comment_text"])
    rec = new_base()
    rec.update({
        "plan_id": p["id"],
        "commenter_name": data["commenter_name"],
        "comment_text": data["comment_text"],
        "disposition": "PENDING",
    })
    db.comments[rec["id"]] = rec
    return ok(core.ser_comment(rec), status=201)


@app.get("/plans/<plan_id>/comments")
def list_comments(plan_id):
    authenticate(ALL_ROLES)
    p = get_or_404(db.plans, plan_id, "ERR_PLAN_NOT_FOUND")
    items = [c for c in db.comments.values() if c["plan_id"] == p["id"]]
    return list_response(items, core.ser_comment)


@app.post("/comments/<comment_id>/disposition")
def disposition_comment(comment_id):
    authenticate(["CommissionChair"])
    c = get_or_404(db.comments, comment_id, "ERR_COMMENT_NOT_FOUND")
    if c["disposition"] != "PENDING":
        raise ApiError("ERR_INVALID_STATE", 409, "comment is not PENDING")
    data = body()
    disp = data.get("disposition")
    if disp not in ("ACKNOWLEDGED", "INCORPORATED", "DISMISSED"):
        raise ApiError("ERR_VALIDATION", 422, "invalid disposition")
    c["disposition"] = disp
    touch(c)
    return ok(core.ser_comment(c), status=200)


# --- GISExport ---
def _create_export(plan, export_format):
    checksum, block_count = core.gis_checksum(plan)
    rec = new_base()
    rec.update({
        "plan_id": plan["id"],
        "export_format": export_format,
        "status": "COMPLETE" if plan["status"] == "ADOPTED" else "FAILED",
        "block_count": block_count,
        "district_count": len(core.plan_districts(plan["id"])),
        "checksum": checksum,
    })
    db.gis_exports[rec["id"]] = rec
    return rec


@app.post("/plans/<plan_id>/exports")
def create_export(plan_id):
    authenticate(["ElectionClerk"])
    p = get_or_404(db.plans, plan_id, "ERR_PLAN_NOT_FOUND")
    data = body()
    fmt = data.get("export_format")
    if fmt not in ("GEOJSON", "SHAPEFILE"):
        raise ApiError("ERR_VALIDATION", 422, "invalid export_format")
    rec = _create_export(p, fmt)
    return ok(core.ser_gis_export(rec), status=201)


@app.get("/plans/<plan_id>/exports")
def list_exports(plan_id):
    authenticate(ALL_ROLES)
    p = get_or_404(db.plans, plan_id, "ERR_PLAN_NOT_FOUND")
    items = [g for g in db.gis_exports.values() if g["plan_id"] == p["id"]]
    return list_response(items, core.ser_gis_export)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
