"""Oversize/Overweight Load Permit API — Flask entry point."""
import json
import os
from datetime import timedelta

from flask import Flask, request, Response

import core
from core import (DB, ApiError, meta_base, to_jsonable, new_base, touch,
                  parse_dt, clock_now, KNOWN_ROLES, reset_clock,
                  classify_load, compute_escort_requirement, compute_permit_fee,
                  compute_bond_amount, compute_rating_factor,
                  compute_violation_penalty, to_decimal,
                  structure_available, structure_posture, carrier_standing,
                  CLEARED_MIN_RF, CONDITIONAL_MIN_RF,
                  STRUCTURE_CLEARANCE_BUFFER_MIN)
import serialize as S

app = Flask(__name__)
reset_clock()


# ===========================================================================
# Response helpers
# ===========================================================================
def respond(data, response_type="object", status=200, extra_meta=None):
    meta = meta_base()
    if extra_meta:
        meta.update(extra_meta)
    body = {"meta": meta, "response_type": response_type, "data": data}
    return Response(json.dumps(body), status=status, mimetype="application/json")


def respond_list(items, total, limit, offset):
    extra = {"limit": limit, "offset": offset, "total_count": total,
             "has_more": (offset + len(items)) < total}
    return respond(items, response_type="array", status=200, extra_meta=extra)


@app.errorhandler(ApiError)
def handle_api_error(err):
    meta = meta_base()
    body = {"meta": meta, "response_type": "error",
            "data": {"error_id": err.error_id, "message": err.message}}
    return Response(json.dumps(body), status=err.http_status,
                    mimetype="application/json")


@app.errorhandler(404)
def handle_404(err):
    meta = meta_base()
    body = {"meta": meta, "response_type": "error",
            "data": {"error_id": "ERR_INVALID_REQUEST", "message": "Not found."}}
    return Response(json.dumps(body), status=400, mimetype="application/json")


@app.errorhandler(405)
def handle_405(err):
    meta = meta_base()
    body = {"meta": meta, "response_type": "error",
            "data": {"error_id": "ERR_INVALID_REQUEST", "message": "Method not allowed."}}
    return Response(json.dumps(body), status=400, mimetype="application/json")


# ===========================================================================
# Auth / body helpers
# ===========================================================================
def authenticate():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in KNOWN_ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", "Missing or invalid auth headers.")
    return uid, role


def require_role(role, allowed):
    if role not in allowed:
        raise ApiError("ERR_UNAUTHORIZED", "Role not permitted for this operation.")


def get_body():
    if not request.data:
        return {}
    try:
        data = request.get_json(force=True, silent=True)
    except Exception:
        data = None
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ApiError("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return data


def check_fields(body, required, optional):
    allowed = set(required) | set(optional)
    for key in body:
        if key not in allowed:
            raise ApiError("ERR_INVALID_REQUEST", f"Unknown field: {key}")
    for key in required:
        if key not in body or body[key] is None:
            raise ApiError("ERR_INVALID_REQUEST", f"Missing required field: {key}")


def require_enum(value, allowed, field):
    if value not in allowed:
        raise ApiError("ERR_INVALID_REQUEST", f"Invalid value for {field}.")


def require_int(value, field):
    if isinstance(value, bool) or not isinstance(value, int):
        raise ApiError("ERR_INVALID_REQUEST", f"{field} must be an integer.")
    return value


def require_number(value, field):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ApiError("ERR_INVALID_REQUEST", f"{field} must be a number.")
    return value


def parse_required_dt(value, field):
    try:
        return parse_dt(value)
    except Exception:
        raise ApiError("ERR_INVALID_REQUEST", f"{field} must be an ISO 8601 datetime.")


# ===========================================================================
# Entity lookups (raise the correct 404)
# ===========================================================================
def get_carrier(cid):
    c = DB["carriers"].get(cid)
    if not c:
        raise ApiError("ERR_CARRIER_NOT_FOUND", "Carrier not found.")
    return c


def get_permit(pid):
    p = DB["permits"].get(pid)
    if not p:
        raise ApiError("ERR_PERMIT_NOT_FOUND", "Permit not found.")
    return p


def get_structure(sid):
    s = DB["structures"].get(sid)
    if not s:
        raise ApiError("ERR_STRUCTURE_NOT_FOUND", "Structure not found.")
    return s


def get_pilot_car(pid):
    pc = DB["pilot_cars"].get(pid)
    if not pc:
        raise ApiError("ERR_PILOT_CAR_NOT_FOUND", "Pilot car not found.")
    return pc


def get_route_segment(rid):
    r = DB["route_segments"].get(rid)
    if not r:
        raise ApiError("ERR_ROUTE_SEGMENT_NOT_FOUND", "Route segment not found.")
    return r


def get_bridge_analysis(bid):
    b = DB["bridge_analyses"].get(bid)
    if not b:
        raise ApiError("ERR_BRIDGE_ANALYSIS_NOT_FOUND", "Bridge analysis not found.")
    return b


def get_escort(eid):
    e = DB["escort_assignments"].get(eid)
    if not e:
        raise ApiError("ERR_ESCORT_ASSIGNMENT_NOT_FOUND", "Escort assignment not found.")
    return e


def get_bond_by_id(bid):
    b = DB["bonds"].get(bid)
    if not b:
        raise ApiError("ERR_INVALID_REQUEST", "Bond not found.")
    return b


def get_violation(vid):
    v = DB["violations"].get(vid)
    if not v:
        raise ApiError("ERR_VIOLATION_NOT_FOUND", "Violation not found.")
    return v


def permit_segments(pid):
    return [r for r in DB["route_segments"].values() if r["permit_id"] == pid]


def permit_analyses(pid):
    return [b for b in DB["bridge_analyses"].values() if b["permit_id"] == pid]


def permit_escorts(pid):
    return [e for e in DB["escort_assignments"].values() if e["permit_id"] == pid]


def permit_bond(pid):
    for b in DB["bonds"].values():
        if b["permit_id"] == pid:
            return b
    return None


# ===========================================================================
# Pagination
# ===========================================================================
def paginate(items):
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    if limit_raw is None:
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST", "limit must be an integer.")
        if limit < 1:
            limit = 1
        elif limit > 100:
            limit = 100
    if offset_raw is None:
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST", "offset must be an integer.")
        if offset < 0:
            offset = 0
    ordered = sorted(items, key=lambda r: r["_seq"])
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return page, total, limit, offset


# ===========================================================================
# Field-shape validators (ERR_INVALID_DIMENSIONS)
# ===========================================================================
def validate_load_dimensions(length_in, width_in, height_in, gross_weight_lbs,
                             num_axles, front_overhang_in, rear_overhang_in):
    if length_in is not None and length_in <= 0:
        raise ApiError("ERR_INVALID_DIMENSIONS", "length_in must be positive.")
    if width_in is not None and width_in <= 0:
        raise ApiError("ERR_INVALID_DIMENSIONS", "width_in must be positive.")
    if height_in is not None and height_in <= 0:
        raise ApiError("ERR_INVALID_DIMENSIONS", "height_in must be positive.")
    if gross_weight_lbs is not None and gross_weight_lbs <= 0:
        raise ApiError("ERR_INVALID_DIMENSIONS", "gross_weight_lbs must be positive.")
    if num_axles is not None and num_axles < 2:
        raise ApiError("ERR_INVALID_DIMENSIONS", "num_axles must be at least 2.")
    if front_overhang_in is not None and front_overhang_in < 0:
        raise ApiError("ERR_INVALID_DIMENSIONS", "front_overhang_in must be >= 0.")
    if rear_overhang_in is not None and rear_overhang_in < 0:
        raise ApiError("ERR_INVALID_DIMENSIONS", "rear_overhang_in must be >= 0.")


# ===========================================================================
# Reference data endpoints (DOTAdmin)
# ===========================================================================
@app.route("/carriers", methods=["POST"])
def create_carrier():
    _, role = authenticate()
    require_role(role, {"DOTAdmin"})
    body = get_body()
    check_fields(body, ["legal_name", "usdot_number"], [])
    rec = new_base()
    rec["legal_name"] = body["legal_name"]
    rec["usdot_number"] = body["usdot_number"]
    rec["total_escrow_deposited_cents"] = 0
    rec["escrow_balance_cents"] = 0
    rec["unpaid_fee_balance_cents"] = 0
    DB["carriers"][rec["id"]] = rec
    return respond(S.serialize_carrier(rec), status=201)


@app.route("/carriers/<cid>", methods=["GET"])
def read_carrier(cid):
    authenticate()
    c = get_carrier(cid)
    return respond(S.serialize_carrier(c))


@app.route("/carriers/<cid>/escrow-deposits", methods=["POST"])
def escrow_deposit(cid):
    _, role = authenticate()
    require_role(role, {"DOTAdmin"})
    c = get_carrier(cid)
    body = get_body()
    check_fields(body, ["amount_cents"], [])
    amount = require_int(body["amount_cents"], "amount_cents")
    c["escrow_balance_cents"] += amount
    c["total_escrow_deposited_cents"] += amount
    touch(c)
    return respond(S.serialize_carrier(c))


@app.route("/structures", methods=["POST"])
def create_structure():
    _, role = authenticate()
    require_role(role, {"DOTAdmin"})
    body = get_body()
    check_fields(body, ["name", "highway_id", "milepost",
                        "rated_capacity_tonnage", "dead_load_tonnage"], [])
    rated = require_number(body["rated_capacity_tonnage"], "rated_capacity_tonnage")
    dead = require_number(body["dead_load_tonnage"], "dead_load_tonnage")
    require_number(body["milepost"], "milepost")
    if rated <= 0:
        raise ApiError("ERR_INVALID_REQUEST", "rated_capacity_tonnage must be positive.")
    if dead < 0:
        raise ApiError("ERR_INVALID_REQUEST", "dead_load_tonnage must be >= 0.")
    rec = new_base()
    rec["name"] = body["name"]
    rec["highway_id"] = body["highway_id"]
    rec["milepost"] = to_decimal(body["milepost"])
    rec["rated_capacity_tonnage"] = to_decimal(rated)
    rec["dead_load_tonnage"] = to_decimal(dead)
    rec["committed_tonnage"] = to_decimal(0)
    DB["structures"][rec["id"]] = rec
    return respond(S.serialize_structure(rec), status=201)


@app.route("/structures/<sid>", methods=["GET"])
def read_structure(sid):
    authenticate()
    s = get_structure(sid)
    return respond(S.serialize_structure(s))


@app.route("/pilot-cars", methods=["POST"])
def create_pilot_car():
    _, role = authenticate()
    require_role(role, {"DOTAdmin"})
    body = get_body()
    check_fields(body, ["company_name", "cert_number"], ["status"])
    status = body.get("status", "AVAILABLE")
    if status is None:
        status = "AVAILABLE"
    require_enum(status, {"AVAILABLE", "OUT_OF_SERVICE"}, "status")
    rec = new_base()
    rec["company_name"] = body["company_name"]
    rec["cert_number"] = body["cert_number"]
    rec["status"] = status
    DB["pilot_cars"][rec["id"]] = rec
    return respond(S.serialize_pilot_car(rec), status=201)


@app.route("/pilot-cars/<pid>", methods=["GET"])
def read_pilot_car(pid):
    authenticate()
    pc = get_pilot_car(pid)
    return respond(S.serialize_pilot_car(pc))


@app.route("/travel-restrictions", methods=["POST"])
def create_travel_restriction():
    _, role = authenticate()
    require_role(role, {"DOTAdmin"})
    body = get_body()
    check_fields(body, ["restriction_type", "start_utc", "end_utc",
                        "applies_to_classification"], [])
    require_enum(body["restriction_type"], {"CURFEW", "HOLIDAY"}, "restriction_type")
    require_enum(body["applies_to_classification"],
                 {"ALL", "OVERSIZE", "OVERWEIGHT", "OVERSIZE_OVERWEIGHT", "SUPERLOAD"},
                 "applies_to_classification")
    start = parse_required_dt(body["start_utc"], "start_utc")
    end = parse_required_dt(body["end_utc"], "end_utc")
    if end <= start:
        raise ApiError("ERR_INVALID_REQUEST", "end_utc must be after start_utc.")
    rec = new_base(common_fields=False)
    rec["restriction_type"] = body["restriction_type"]
    rec["start_utc"] = body["start_utc"]
    rec["end_utc"] = body["end_utc"]
    rec["applies_to_classification"] = body["applies_to_classification"]
    rec["_start"] = start
    rec["_end"] = end
    DB["travel_restrictions"][rec["id"]] = rec
    return respond(S.serialize_travel_restriction(rec), status=201)


# ===========================================================================
# Permit create / read / list / edit
# ===========================================================================
PERMIT_LOAD_FIELDS = ["permit_type", "length_in", "width_in", "height_in",
                      "front_overhang_in", "rear_overhang_in", "gross_weight_lbs",
                      "num_axles", "valid_from", "valid_until"]


@app.route("/permits", methods=["POST"])
def create_permit():
    uid, role = authenticate()
    require_role(role, {"Carrier"})
    body = get_body()
    # ownership (403) then existence (404) of carrier_id
    cid = body.get("carrier_id")
    if cid is not None and cid != uid:
        raise ApiError("ERR_UNAUTHORIZED", "Carrier may only create permits for itself.")
    if cid is not None:
        get_carrier(cid)
    # well-formedness
    check_fields(body,
                 ["carrier_id", "permit_type", "length_in", "width_in", "height_in",
                  "gross_weight_lbs", "num_axles", "valid_from", "valid_until"],
                 ["front_overhang_in", "rear_overhang_in"])
    require_enum(body["permit_type"], {"SINGLE_TRIP", "ANNUAL"}, "permit_type")
    length_in = require_int(body["length_in"], "length_in")
    width_in = require_int(body["width_in"], "width_in")
    height_in = require_int(body["height_in"], "height_in")
    gross = require_int(body["gross_weight_lbs"], "gross_weight_lbs")
    num_axles = require_int(body["num_axles"], "num_axles")
    front = body.get("front_overhang_in", 0)
    if front is None:
        front = 0
    rear = body.get("rear_overhang_in", 0)
    if rear is None:
        rear = 0
    require_int(front, "front_overhang_in")
    require_int(rear, "rear_overhang_in")
    valid_from = parse_required_dt(body["valid_from"], "valid_from")
    valid_until = parse_required_dt(body["valid_until"], "valid_until")
    # dimension shape (422)
    validate_load_dimensions(length_in, width_in, height_in, gross, num_axles, front, rear)
    # validity window (422)
    if not (valid_from < valid_until):
        raise ApiError("ERR_VALIDITY_WINDOW_INVALID", "valid_from must be before valid_until.")

    rec = new_base()
    rec["carrier_id"] = body["carrier_id"]
    rec["permit_type"] = body["permit_type"]
    rec["length_in"] = length_in
    rec["width_in"] = width_in
    rec["height_in"] = height_in
    rec["front_overhang_in"] = front
    rec["rear_overhang_in"] = rear
    rec["gross_weight_lbs"] = gross
    rec["num_axles"] = num_axles
    rec["valid_from"] = body["valid_from"]
    rec["valid_until"] = body["valid_until"]
    rec["_valid_from"] = valid_from
    rec["_valid_until"] = valid_until
    rec["classification"] = None
    rec["requires_superload_review"] = False
    rec["fee_cents"] = 0
    rec["required_escort_count"] = 0
    rec["status"] = "DRAFT"
    rec["issued_at"] = None
    DB["permits"][rec["id"]] = rec
    return respond(S.serialize_permit(rec), status=201)


@app.route("/permits/<pid>", methods=["GET"])
def read_permit(pid):
    authenticate()
    p = get_permit(pid)
    return respond(S.serialize_permit(p))


@app.route("/permits", methods=["GET"])
def list_permits():
    authenticate()
    items = list(DB["permits"].values())
    carrier_id = request.args.get("carrier_id")
    status = request.args.get("status")
    if carrier_id is not None:
        items = [p for p in items if p["carrier_id"] == carrier_id]
    if status is not None:
        items = [p for p in items if p["status"] == status]
    page, total, limit, offset = paginate(items)
    return respond_list([S.serialize_permit(p) for p in page], total, limit, offset)


@app.route("/permits/<pid>", methods=["PATCH"])
def edit_permit(pid):
    uid, role = authenticate()
    require_role(role, {"Carrier"})
    p = get_permit(pid)
    if p["carrier_id"] != uid:
        raise ApiError("ERR_UNAUTHORIZED", "Carrier does not own this permit.")
    body = get_body()
    check_fields(body, ["expected_permit_version"], PERMIT_LOAD_FIELDS)
    expected = body["expected_permit_version"]
    if "permit_type" in body and body["permit_type"] is not None:
        require_enum(body["permit_type"], {"SINGLE_TRIP", "ANNUAL"}, "permit_type")
    # gather effective values
    eff = {}
    for f in ["length_in", "width_in", "height_in", "gross_weight_lbs",
              "num_axles", "front_overhang_in", "rear_overhang_in"]:
        if f in body and body[f] is not None:
            eff[f] = require_int(body[f], f)
    vf = p["_valid_from"]
    vu = p["_valid_until"]
    if "valid_from" in body and body["valid_from"] is not None:
        vf = parse_required_dt(body["valid_from"], "valid_from")
    if "valid_until" in body and body["valid_until"] is not None:
        vu = parse_required_dt(body["valid_until"], "valid_until")
    # dimension shape (422) on provided fields
    validate_load_dimensions(eff.get("length_in"), eff.get("width_in"),
                             eff.get("height_in"), eff.get("gross_weight_lbs"),
                             eff.get("num_axles"), eff.get("front_overhang_in"),
                             eff.get("rear_overhang_in"))
    # validity window (422)
    if not (vf < vu):
        raise ApiError("ERR_VALIDITY_WINDOW_INVALID", "valid_from must be before valid_until.")
    # OCC (412)
    if expected != p["version"]:
        raise ApiError("ERR_STALE_PERMIT_VERSION", "expected_permit_version is stale.")
    # state (409)
    if p["status"] not in ("DRAFT", "RETURNED_FOR_CORRECTION"):
        raise ApiError("ERR_INVALID_PERMIT_STATE", "Permit is not editable in its current state.")
    # apply
    if "permit_type" in body and body["permit_type"] is not None:
        p["permit_type"] = body["permit_type"]
    for f, v in eff.items():
        p[f] = v
    if "valid_from" in body and body["valid_from"] is not None:
        p["valid_from"] = body["valid_from"]
        p["_valid_from"] = vf
    if "valid_until" in body and body["valid_until"] is not None:
        p["valid_until"] = body["valid_until"]
        p["_valid_until"] = vu
    touch(p)
    return respond(S.serialize_permit(p))


# ===========================================================================
# Route segments
# ===========================================================================
@app.route("/permits/<pid>/route-segments", methods=["POST"])
def add_route_segment(pid):
    uid, role = authenticate()
    require_role(role, {"Carrier"})
    p = get_permit(pid)
    if p["carrier_id"] != uid:
        raise ApiError("ERR_UNAUTHORIZED", "Carrier does not own this permit.")
    body = get_body()
    # existence of structure FK (404)
    structure_id = body.get("structure_id")
    if structure_id is not None:
        get_structure(structure_id)
    # well-formedness (400)
    check_fields(body, ["sequence_index", "highway_id", "from_milepost", "to_milepost"],
                 ["structure_id", "planned_cross_start_utc", "planned_cross_end_utc"])
    sequence_index = require_int(body["sequence_index"], "sequence_index")
    from_mp = require_number(body["from_milepost"], "from_milepost")
    to_mp = require_number(body["to_milepost"], "to_milepost")
    pcs = None
    pce = None
    if structure_id is not None:
        if body.get("planned_cross_start_utc") is None:
            raise ApiError("ERR_INVALID_REQUEST",
                           "planned_cross_start_utc is required when structure_id is set.")
    if body.get("planned_cross_start_utc") is not None:
        pcs = parse_required_dt(body["planned_cross_start_utc"], "planned_cross_start_utc")
    if body.get("planned_cross_end_utc") is not None:
        pce = parse_required_dt(body["planned_cross_end_utc"], "planned_cross_end_utc")
    # dimension shape (422)
    if sequence_index < 1:
        raise ApiError("ERR_INVALID_DIMENSIONS", "sequence_index must be >= 1.")
    if from_mp < 0:
        raise ApiError("ERR_INVALID_DIMENSIONS", "from_milepost must be >= 0.")
    if not (to_mp > from_mp):
        raise ApiError("ERR_INVALID_DIMENSIONS", "to_milepost must be greater than from_milepost.")
    if pcs is not None and pce is not None and not (pce > pcs):
        raise ApiError("ERR_INVALID_DIMENSIONS",
                       "planned_cross_end_utc must be after planned_cross_start_utc.")
    # state (409)
    if p["status"] not in ("DRAFT", "RETURNED_FOR_CORRECTION"):
        raise ApiError("ERR_INVALID_PERMIT_STATE",
                       "Route segments can only be added while DRAFT or RETURNED_FOR_CORRECTION.")
    rec = new_base()
    rec["permit_id"] = pid
    rec["sequence_index"] = sequence_index
    rec["highway_id"] = body["highway_id"]
    rec["from_milepost"] = to_decimal(from_mp)
    rec["to_milepost"] = to_decimal(to_mp)
    rec["structure_id"] = structure_id
    rec["planned_cross_start_utc"] = body.get("planned_cross_start_utc")
    rec["planned_cross_end_utc"] = body.get("planned_cross_end_utc")
    rec["_pcs"] = pcs
    rec["_pce"] = pce
    rec["miles"] = to_decimal(to_mp) - to_decimal(from_mp)
    rec["load_tonnage"] = to_decimal(p["gross_weight_lbs"]) / to_decimal(2000)
    rec["reservation_status"] = "PLANNED"
    DB["route_segments"][rec["id"]] = rec
    touch(p)  # adding a segment advances the permit version
    return respond(S.serialize_route_segment(rec), status=201)


@app.route("/route-segments", methods=["GET"])
def list_route_segments():
    authenticate()
    items = list(DB["route_segments"].values())
    permit_id = request.args.get("permit_id")
    structure_id = request.args.get("structure_id")
    if permit_id is not None:
        items = [r for r in items if r["permit_id"] == permit_id]
    if structure_id is not None:
        items = [r for r in items if r["structure_id"] == structure_id]
    page, total, limit, offset = paginate(items)
    return respond_list([S.serialize_route_segment(r) for r in page], total, limit, offset)


@app.route("/route-segments/<rid>", methods=["GET"])
def read_route_segment(rid):
    authenticate()
    r = get_route_segment(rid)
    return respond(S.serialize_route_segment(r))


# ===========================================================================
# Escort assignments
# ===========================================================================
@app.route("/permits/<pid>/escort-assignments", methods=["POST"])
def add_escort(pid):
    uid, role = authenticate()
    require_role(role, {"Carrier"})
    p = get_permit(pid)
    if p["carrier_id"] != uid:
        raise ApiError("ERR_UNAUTHORIZED", "Carrier does not own this permit.")
    body = get_body()
    pilot_car_id = body.get("pilot_car_id")
    if pilot_car_id is not None:
        get_pilot_car(pilot_car_id)
    check_fields(body, ["pilot_car_id", "role", "window_start_utc", "window_end_utc"], [])
    require_enum(body["role"], {"FRONT", "REAR", "POLICE"}, "role")
    ws = parse_required_dt(body["window_start_utc"], "window_start_utc")
    we = parse_required_dt(body["window_end_utc"], "window_end_utc")
    if not (we > ws):
        raise ApiError("ERR_INVALID_DIMENSIONS",
                       "window_end_utc must be after window_start_utc.")
    rec = new_base()
    rec["permit_id"] = pid
    rec["pilot_car_id"] = pilot_car_id
    rec["role"] = body["role"]
    rec["window_start_utc"] = body["window_start_utc"]
    rec["window_end_utc"] = body["window_end_utc"]
    rec["_ws"] = ws
    rec["_we"] = we
    rec["status"] = "PENDING"
    DB["escort_assignments"][rec["id"]] = rec
    return respond(S.serialize_escort(rec), status=201)


@app.route("/escort-assignments", methods=["GET"])
def list_escorts():
    authenticate()
    items = list(DB["escort_assignments"].values())
    permit_id = request.args.get("permit_id")
    pilot_car_id = request.args.get("pilot_car_id")
    if permit_id is not None:
        items = [e for e in items if e["permit_id"] == permit_id]
    if pilot_car_id is not None:
        items = [e for e in items if e["pilot_car_id"] == pilot_car_id]
    page, total, limit, offset = paginate(items)
    return respond_list([S.serialize_escort(e) for e in page], total, limit, offset)


@app.route("/escort-assignments/<eid>", methods=["GET"])
def read_escort(eid):
    authenticate()
    e = get_escort(eid)
    return respond(S.serialize_escort(e))


@app.route("/escort-assignments/<eid>/confirm", methods=["POST"])
def confirm_escort(eid):
    uid, role = authenticate()
    require_role(role, {"Carrier"})
    e = get_escort(eid)
    p = get_permit(e["permit_id"])
    if p["carrier_id"] != uid:
        raise ApiError("ERR_UNAUTHORIZED", "Carrier does not own this permit.")
    if e["status"] != "PENDING":
        raise ApiError("ERR_INVALID_ESCORT_STATE", "Escort cannot be confirmed from its state.")
    pc = get_pilot_car(e["pilot_car_id"])
    if pc["status"] != "AVAILABLE":
        raise ApiError("ERR_PILOT_CAR_UNAVAILABLE", "Pilot car is not available.")
    # half-open overlap [start, end) with other CONFIRMED assignments on same pilot car
    for other in DB["escort_assignments"].values():
        if other["id"] == e["id"]:
            continue
        if other["pilot_car_id"] != e["pilot_car_id"]:
            continue
        if other["status"] != "CONFIRMED":
            continue
        if e["_ws"] < other["_we"] and other["_ws"] < e["_we"]:
            raise ApiError("ERR_PILOT_CAR_DOUBLE_BOOKED", "Pilot car is double booked.")
    e["status"] = "CONFIRMED"
    touch(e)
    return respond(S.serialize_escort(e))


@app.route("/escort-assignments/<eid>/cancel", methods=["POST"])
def cancel_escort(eid):
    uid, role = authenticate()
    require_role(role, {"Carrier"})
    e = get_escort(eid)
    p = get_permit(e["permit_id"])
    if p["carrier_id"] != uid:
        raise ApiError("ERR_UNAUTHORIZED", "Carrier does not own this permit.")
    if e["status"] == "PENDING":
        e["status"] = "CANCELLED"
        touch(e)
        return respond(S.serialize_escort(e))
    if e["status"] == "CONFIRMED":
        if p["status"] == "ISSUED":
            raise ApiError("ERR_INVALID_ESCORT_STATE",
                           "Confirmed escorts are locked once the permit is issued.")
        e["status"] = "CANCELLED"
        touch(e)
        return respond(S.serialize_escort(e))
    raise ApiError("ERR_INVALID_ESCORT_STATE", "Escort cannot be cancelled from its state.")


# ===========================================================================
# Permit lifecycle transitions
# ===========================================================================
@app.route("/permits/<pid>/submit", methods=["POST"])
def submit_permit(pid):
    uid, role = authenticate()
    require_role(role, {"Carrier"})
    p = get_permit(pid)
    if p["carrier_id"] != uid:
        raise ApiError("ERR_UNAUTHORIZED", "Carrier does not own this permit.")
    # state (409)
    if p["status"] not in ("DRAFT", "RETURNED_FOR_CORRECTION"):
        raise ApiError("ERR_INVALID_PERMIT_STATE", "Permit cannot be submitted from its state.")
    carrier = DB["carriers"].get(p["carrier_id"])
    # business rules in narrative order
    if carrier and carrier_standing(carrier["id"]) == "SUSPENDED":
        raise ApiError("ERR_CARRIER_SUSPENDED", "Carrier is suspended.")
    segments = permit_segments(pid)
    if len(segments) < 1:
        raise ApiError("ERR_ROUTE_EMPTY", "Permit has no route segments.")
    classification = classify_load(p)
    if p["permit_type"] == "ANNUAL" and classification == "SUPERLOAD":
        raise ApiError("ERR_ANNUAL_SUPERLOAD_FORBIDDEN",
                       "Annual permits cannot be superloads.")
    if carrier and carrier["unpaid_fee_balance_cents"] != 0:
        raise ApiError("ERR_UNPAID_FEES", "Carrier has unpaid fees.")
    # side effects
    p["classification"] = classification
    p["requires_superload_review"] = (classification == "SUPERLOAD")
    p["required_escort_count"] = compute_escort_requirement(p)
    p["fee_cents"] = compute_permit_fee(p, segments)
    # create/keep BridgeAnalysis for each segment naming a structure
    for seg in segments:
        if seg["structure_id"]:
            existing = [b for b in permit_analyses(pid)
                        if b["structure_id"] == seg["structure_id"]]
            if not existing:
                ba = new_base()
                ba["permit_id"] = pid
                ba["structure_id"] = seg["structure_id"]
                ba["method"] = None
                ba["rating_factor"] = None
                ba["status"] = "REQUESTED"
                ba["conditions_note"] = None
                DB["bridge_analyses"][ba["id"]] = ba
    # superload bond
    if classification == "SUPERLOAD" and permit_bond(pid) is None:
        bond = new_base()
        bond["permit_id"] = pid
        bond["amount_cents"] = compute_bond_amount(p)
        bond["status"] = "DRAFT"
        DB["bonds"][bond["id"]] = bond
    p["status"] = "SUBMITTED"
    touch(p)
    return respond(S.serialize_permit(p))


@app.route("/permits/<pid>/begin-review", methods=["POST"])
def begin_review(pid):
    _, role = authenticate()
    require_role(role, {"PermitOfficer", "BridgeEngineer"})
    p = get_permit(pid)
    if p["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_PERMIT_STATE", "Permit is not awaiting review.")
    if p["requires_superload_review"]:
        if role != "BridgeEngineer":
            raise ApiError("ERR_UNAUTHORIZED", "Superload review requires a BridgeEngineer.")
        p["status"] = "UNDER_SUPERLOAD_REVIEW"
    else:
        if role != "PermitOfficer":
            raise ApiError("ERR_UNAUTHORIZED", "Standard review requires a PermitOfficer.")
        p["status"] = "UNDER_STANDARD_REVIEW"
    touch(p)
    return respond(S.serialize_permit(p))


@app.route("/permits/<pid>/return", methods=["POST"])
def return_permit(pid):
    _, role = authenticate()
    require_role(role, {"PermitOfficer", "BridgeEngineer"})
    p = get_permit(pid)
    if p["status"] not in ("UNDER_STANDARD_REVIEW", "UNDER_SUPERLOAD_REVIEW"):
        raise ApiError("ERR_INVALID_PERMIT_STATE", "Permit is not under review.")
    body = get_body()
    check_fields(body, [], ["reason"])
    p["status"] = "RETURNED_FOR_CORRECTION"
    touch(p)
    return respond(S.serialize_permit(p))


@app.route("/permits/<pid>/approve", methods=["POST"])
def approve_permit(pid):
    _, role = authenticate()
    require_role(role, {"PermitOfficer", "BridgeEngineer"})
    p = get_permit(pid)
    if p["status"] not in ("UNDER_STANDARD_REVIEW", "UNDER_SUPERLOAD_REVIEW"):
        raise ApiError("ERR_INVALID_PERMIT_STATE", "Permit is not under review.")
    analyses = permit_analyses(pid)
    if any(b["status"] == "REJECTED" for b in analyses):
        raise ApiError("ERR_BRIDGE_REJECTED", "A bridge analysis is rejected.")
    if any(b["status"] != "CLEARED" for b in analyses):
        raise ApiError("ERR_BRIDGE_ANALYSIS_INCOMPLETE", "A bridge analysis is not cleared.")
    confirmed = sum(1 for e in permit_escorts(pid) if e["status"] == "CONFIRMED")
    if confirmed < p["required_escort_count"]:
        raise ApiError("ERR_ESCORT_REQUIREMENT_UNMET", "Escort requirement not met.")
    if p["status"] == "UNDER_SUPERLOAD_REVIEW":
        if permit_bond(pid) is None:
            raise ApiError("ERR_INVALID_PERMIT_STATE", "Superload requires a bond.")
    p["status"] = "APPROVED"
    touch(p)
    return respond(S.serialize_permit(p))


@app.route("/permits/<pid>/reject", methods=["POST"])
def reject_permit(pid):
    _, role = authenticate()
    require_role(role, {"PermitOfficer", "BridgeEngineer"})
    p = get_permit(pid)
    if p["status"] not in ("UNDER_STANDARD_REVIEW", "UNDER_SUPERLOAD_REVIEW"):
        raise ApiError("ERR_INVALID_PERMIT_STATE", "Permit is not under review.")
    body = get_body()
    check_fields(body, [], ["reason"])
    p["status"] = "REJECTED"
    touch(p)
    return respond(S.serialize_permit(p))


def _recompute_structure(structure):
    touch(structure)


@app.route("/permits/<pid>/issue", methods=["POST"])
def issue_permit(pid):
    _, role = authenticate()
    require_role(role, {"PermitOfficer"})
    p = get_permit(pid)
    if p["status"] != "APPROVED":
        raise ApiError("ERR_INVALID_PERMIT_STATE", "Permit is not approved.")
    analyses = permit_analyses(pid)
    if any(b["status"] == "REJECTED" for b in analyses):
        raise ApiError("ERR_BRIDGE_REJECTED", "A bridge analysis is rejected.")
    if any(b["status"] != "CLEARED" for b in analyses):
        raise ApiError("ERR_BRIDGE_ANALYSIS_INCOMPLETE", "A bridge analysis is not cleared.")
    clock = clock_now()
    if not (p["_valid_until"] > clock and p["_valid_from"] < p["_valid_until"]):
        raise ApiError("ERR_VALIDITY_WINDOW_INVALID",
                       "Validity window is invalid at issuance.")
    segments = sorted(permit_segments(pid), key=lambda s: s["sequence_index"])
    buffer = timedelta(minutes=STRUCTURE_CLEARANCE_BUFFER_MIN)
    crossing = [s for s in segments if s["structure_id"]]
    # per-segment structural checks
    for seg in crossing:
        structure = DB["structures"].get(seg["structure_id"])
        if structure_posture(structure) == "CLOSED":
            raise ApiError("ERR_STRUCTURE_CLOSED", "A crossed structure is closed.")
        if structure_available(structure) < to_decimal(seg["load_tonnage"]):
            raise ApiError("ERR_STRUCTURE_CAPACITY_EXCEEDED",
                           "A crossed structure lacks capacity.")
        # window conflict against other RESERVED segments on same structure
        seg_start = seg["_pcs"]
        seg_end = seg["_pce"] if seg["_pce"] is not None else seg["_pcs"]
        if seg_start is not None:
            lo = seg_start - buffer
            hi = seg_end + buffer
            for other in DB["route_segments"].values():
                if other["id"] == seg["id"]:
                    continue
                if other["structure_id"] != seg["structure_id"]:
                    continue
                if other["reservation_status"] != "RESERVED":
                    continue
                o_start = other["_pcs"]
                o_end = other["_pce"] if other["_pce"] is not None else other["_pcs"]
                if o_start is None:
                    continue
                if o_start <= hi and o_end >= lo:
                    raise ApiError("ERR_STRUCTURE_WINDOW_CONFLICT",
                                   "Structure crossing window conflict.")
    # travel restriction check across crossing windows
    for seg in crossing:
        seg_start = seg["_pcs"]
        seg_end = seg["_pce"] if seg["_pce"] is not None else seg["_pcs"]
        if seg_start is None:
            continue
        for r in DB["travel_restrictions"].values():
            if r["applies_to_classification"] not in ("ALL", p["classification"]):
                continue
            if seg_start <= r["_end"] and seg_end >= r["_start"]:
                raise ApiError("ERR_TRAVEL_TIME_RESTRICTED",
                               "A crossing window intersects a travel restriction.")
    # superload escrow
    bond = permit_bond(pid)
    carrier = DB["carriers"].get(p["carrier_id"])
    if p["classification"] == "SUPERLOAD":
        if bond is None:
            raise ApiError("ERR_INVALID_PERMIT_STATE", "Superload requires a bond.")
        if carrier["escrow_balance_cents"] < bond["amount_cents"]:
            raise ApiError("ERR_INSUFFICIENT_ESCROW", "Insufficient escrow for the bond.")
    # ---- apply side effects ----
    p["issued_at"] = clock
    p["status"] = "ISSUED"
    for seg in segments:
        seg["reservation_status"] = "RESERVED"
        if seg["structure_id"]:
            structure = DB["structures"].get(seg["structure_id"])
            structure["committed_tonnage"] = (to_decimal(structure["committed_tonnage"])
                                              + to_decimal(seg["load_tonnage"]))
            _recompute_structure(structure)
        touch(seg)
    if p["classification"] == "SUPERLOAD" and bond is not None:
        bond["status"] = "ACTIVE"
        touch(bond)
        carrier["escrow_balance_cents"] -= bond["amount_cents"]
        touch(carrier)
    touch(p)
    return respond(S.serialize_permit(p))


def _release_segments(pid, target_status):
    for seg in permit_segments(pid):
        if seg["reservation_status"] == "RESERVED":
            seg["reservation_status"] = target_status
            if seg["structure_id"]:
                structure = DB["structures"].get(seg["structure_id"])
                structure["committed_tonnage"] = (to_decimal(structure["committed_tonnage"])
                                                  - to_decimal(seg["load_tonnage"]))
                _recompute_structure(structure)
            touch(seg)


@app.route("/permits/<pid>/complete", methods=["POST"])
def complete_permit(pid):
    uid, role = authenticate()
    require_role(role, {"Carrier"})
    p = get_permit(pid)
    if p["carrier_id"] != uid:
        raise ApiError("ERR_UNAUTHORIZED", "Carrier does not own this permit.")
    if p["status"] != "ISSUED":
        raise ApiError("ERR_INVALID_PERMIT_STATE", "Permit is not issued.")
    if clock_now() > p["_valid_until"]:
        raise ApiError("ERR_INVALID_PERMIT_STATE", "Permit validity has elapsed.")
    _release_segments(pid, "COMPLETED")
    for e in permit_escorts(pid):
        if e["status"] == "CONFIRMED":
            e["status"] = "COMPLETED"
            touch(e)
    bond = permit_bond(pid)
    if bond is not None and bond["status"] == "ACTIVE":
        bond["status"] = "RELEASED"
        touch(bond)
        carrier = DB["carriers"].get(p["carrier_id"])
        carrier["escrow_balance_cents"] += bond["amount_cents"]
        touch(carrier)
    p["status"] = "COMPLETED"
    touch(p)
    return respond(S.serialize_permit(p))


# ===========================================================================
# Bridge analyses
# ===========================================================================
@app.route("/bridge-analyses", methods=["GET"])
def list_bridge_analyses():
    authenticate()
    items = list(DB["bridge_analyses"].values())
    permit_id = request.args.get("permit_id")
    structure_id = request.args.get("structure_id")
    if permit_id is not None:
        items = [b for b in items if b["permit_id"] == permit_id]
    if structure_id is not None:
        items = [b for b in items if b["structure_id"] == structure_id]
    page, total, limit, offset = paginate(items)
    return respond_list([S.serialize_bridge_analysis(b) for b in page], total, limit, offset)


@app.route("/bridge-analyses/<bid>", methods=["GET"])
def read_bridge_analysis(bid):
    authenticate()
    b = get_bridge_analysis(bid)
    return respond(S.serialize_bridge_analysis(b))


@app.route("/bridge-analyses/<bid>/review", methods=["POST"])
def review_bridge_analysis(bid):
    _, role = authenticate()
    require_role(role, {"BridgeEngineer"})
    b = get_bridge_analysis(bid)
    body = get_body()
    check_fields(body, ["method"], [])
    require_enum(body["method"], {"LFR", "LRFR"}, "method")
    p = get_permit(b["permit_id"])
    if b["status"] != "REQUESTED":
        raise ApiError("ERR_INVALID_ANALYSIS_STATE", "Analysis cannot be reviewed from its state.")
    if p["status"] not in ("UNDER_STANDARD_REVIEW", "UNDER_SUPERLOAD_REVIEW"):
        raise ApiError("ERR_INVALID_ANALYSIS_STATE", "Owning permit is not under review.")
    structure = DB["structures"].get(b["structure_id"])
    rf = compute_rating_factor(structure, p, body["method"])
    b["method"] = body["method"]
    b["rating_factor"] = rf
    if rf >= CLEARED_MIN_RF:
        b["status"] = "CLEARED"
    elif rf >= CONDITIONAL_MIN_RF:
        b["status"] = "CONDITIONAL"
        b["conditions_note"] = "Reduced speed / single-lane crossing required."
    else:
        b["status"] = "REJECTED"
    touch(b)
    return respond(S.serialize_bridge_analysis(b))


@app.route("/bridge-analyses/<bid>/accept-conditions", methods=["POST"])
def accept_conditions(bid):
    uid, role = authenticate()
    require_role(role, {"Carrier"})
    b = get_bridge_analysis(bid)
    p = get_permit(b["permit_id"])
    if p["carrier_id"] != uid:
        raise ApiError("ERR_UNAUTHORIZED", "Carrier does not own this permit.")
    if b["status"] != "CONDITIONAL":
        raise ApiError("ERR_INVALID_ANALYSIS_STATE",
                       "Analysis is not in a conditional state.")
    b["status"] = "CLEARED"
    touch(b)
    return respond(S.serialize_bridge_analysis(b))


# ===========================================================================
# Bonds
# ===========================================================================
@app.route("/bonds", methods=["GET"])
def list_bonds():
    authenticate()
    items = list(DB["bonds"].values())
    permit_id = request.args.get("permit_id")
    if permit_id is not None:
        items = [b for b in items if b["permit_id"] == permit_id]
    page, total, limit, offset = paginate(items)
    return respond_list([S.serialize_bond(b) for b in page], total, limit, offset)


@app.route("/bonds/<bid>", methods=["GET"])
def read_bond(bid):
    authenticate()
    b = DB["bonds"].get(bid)
    if not b:
        raise ApiError("ERR_INVALID_REQUEST", "Bond not found.")
    return respond(S.serialize_bond(b))


# ===========================================================================
# Violations
# ===========================================================================
def _revoke_permit(p):
    _release_segments(p["id"], "RELEASED")
    bond = permit_bond(p["id"])
    if bond is not None and bond["status"] == "ACTIVE":
        bond["status"] = "FORFEITED"
        touch(bond)
        carrier = DB["carriers"].get(p["carrier_id"])
        # escrow retained by DOT (not refunded); active_bond derived from ACTIVE bonds
        touch(carrier)
    p["status"] = "REVOKED"
    touch(p)


@app.route("/violations", methods=["POST"])
def create_violation():
    _, role = authenticate()
    require_role(role, {"EnforcementOfficer"})
    body = get_body()
    permit_id = body.get("permit_id")
    if permit_id is not None:
        get_permit(permit_id)
    check_fields(body, ["permit_id", "violation_type", "severity"], [])
    require_enum(body["violation_type"],
                 {"OVER_DIMENSION", "OFF_ROUTE", "OFF_SCHEDULE", "NO_ESCORT", "EXPIRED_PERMIT"},
                 "violation_type")
    require_enum(body["severity"], {"MINOR", "MAJOR", "CRITICAL"}, "severity")
    p = DB["permits"][permit_id]
    rec = new_base()
    rec["permit_id"] = permit_id
    rec["carrier_id"] = p["carrier_id"]
    rec["violation_type"] = body["violation_type"]
    rec["severity"] = body["severity"]
    rec["penalty_cents"] = compute_violation_penalty(p["carrier_id"],
                                                     body["violation_type"], body["severity"])
    rec["status"] = "OPEN"
    DB["violations"][rec["id"]] = rec
    if body["severity"] in ("MAJOR", "CRITICAL") and p["status"] == "ISSUED":
        p["status"] = "SUSPENDED"
        touch(p)
    return respond(S.serialize_violation(rec), status=201)


@app.route("/violations/<vid>", methods=["GET"])
def read_violation(vid):
    authenticate()
    v = get_violation(vid)
    return respond(S.serialize_violation(v))


@app.route("/violations", methods=["GET"])
def list_violations():
    authenticate()
    items = list(DB["violations"].values())
    permit_id = request.args.get("permit_id")
    carrier_id = request.args.get("carrier_id")
    status = request.args.get("status")
    if permit_id is not None:
        items = [v for v in items if v["permit_id"] == permit_id]
    if carrier_id is not None:
        items = [v for v in items if v["carrier_id"] == carrier_id]
    if status is not None:
        items = [v for v in items if v["status"] == status]
    page, total, limit, offset = paginate(items)
    return respond_list([S.serialize_violation(v) for v in page], total, limit, offset)


@app.route("/violations/<vid>/contest", methods=["POST"])
def contest_violation(vid):
    uid, role = authenticate()
    require_role(role, {"Carrier"})
    v = get_violation(vid)
    p = get_permit(v["permit_id"])
    if p["carrier_id"] != uid:
        raise ApiError("ERR_UNAUTHORIZED", "Carrier does not own the cited permit.")
    if v["status"] != "OPEN":
        raise ApiError("ERR_INVALID_VIOLATION_STATE", "Violation cannot be contested from its state.")
    v["status"] = "CONTESTED"
    touch(v)
    return respond(S.serialize_violation(v))


@app.route("/violations/<vid>/uphold", methods=["POST"])
def uphold_violation(vid):
    _, role = authenticate()
    require_role(role, {"EnforcementOfficer"})
    v = get_violation(vid)
    if v["status"] not in ("OPEN", "CONTESTED"):
        raise ApiError("ERR_INVALID_VIOLATION_STATE", "Violation cannot be upheld from its state.")
    v["status"] = "UPHELD"
    touch(v)
    carrier = DB["carriers"].get(v["carrier_id"])
    if carrier:
        carrier["unpaid_fee_balance_cents"] += v["penalty_cents"]
        touch(carrier)
    p = DB["permits"].get(v["permit_id"])
    if v["severity"] == "CRITICAL" and p and p["status"] == "SUSPENDED":
        _revoke_permit(p)
    return respond(S.serialize_violation(v))


@app.route("/violations/<vid>/dismiss", methods=["POST"])
def dismiss_violation(vid):
    _, role = authenticate()
    require_role(role, {"EnforcementOfficer"})
    v = get_violation(vid)
    if v["status"] not in ("OPEN", "CONTESTED"):
        raise ApiError("ERR_INVALID_VIOLATION_STATE", "Violation cannot be dismissed from its state.")
    v["status"] = "DISMISSED"
    touch(v)
    p = DB["permits"].get(v["permit_id"])
    if p and p["status"] == "SUSPENDED":
        others = [ov for ov in DB["violations"].values()
                  if ov["permit_id"] == p["id"] and ov["id"] != v["id"]
                  and ov["status"] != "DISMISSED"]
        if not others:
            p["status"] = "ISSUED"
            touch(p)
    return respond(S.serialize_violation(v))


# ===========================================================================
# Clock
# ===========================================================================
@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    _, role = authenticate()
    require_role(role, {"DOTAdmin"})
    body = get_body()
    check_fields(body, ["to_iso8601"], [])
    new_clock = parse_required_dt(body["to_iso8601"], "to_iso8601")
    core.CLOCK["now"] = new_clock
    # expire ISSUED permits whose valid_until < new clock
    for p in sorted(DB["permits"].values(), key=lambda x: x["_seq"]):
        if p["status"] == "ISSUED" and new_clock > p["_valid_until"]:
            _expire_permit(p)
    return respond({}, status=200)


def _expire_permit(p):
    _release_segments(p["id"], "RELEASED")
    bond = permit_bond(p["id"])
    if bond is not None and bond["status"] == "ACTIVE":
        bond["status"] = "RELEASED"
        touch(bond)
        carrier = DB["carriers"].get(p["carrier_id"])
        carrier["escrow_balance_cents"] += bond["amount_cents"]
        touch(carrier)
    p["status"] = "EXPIRED"
    touch(p)


# ===========================================================================
# Entrypoint
# ===========================================================================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
