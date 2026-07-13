"""Solid-Waste & Landfill Scale/Ticketing API — Flask reference implementation.

All storage is in-memory (dicts keyed by id). No seeding at startup; every entity
is built by the test via the declared API surface. Storage is wiped on every boot.
"""
import os
import re
import string
import random
import uuid
import itertools
from datetime import datetime, timezone
from decimal import Decimal

from flask import Flask, request, jsonify

import calc
from calc import D

app = Flask(__name__)

# --------------------------------------------------------------------------- #
# In-memory store
# --------------------------------------------------------------------------- #
ROLES = {"FacilityAdmin", "GateOperator", "EnvironmentalOfficer", "BillingClerk", "Hauler"}

MATERIALS = {"MSW", "CONSTRUCTION_DEBRIS", "GREEN_WASTE", "CLEAN_WOOD", "TIRE", "ASBESTOS"}
SPECIAL_MATERIALS = {"TIRE", "ASBESTOS"}
WASTE_TYPES = {"TIRE", "ASBESTOS"}
PAYMENT_METHODS = {"ACH", "CARD", "CHECK"}


class Store:
    def __init__(self):
        self.facilities = {}
        self.cells = {}
        self.hauler_accounts = {}
        self.manifests = {}
        self.approvals = {}
        self.tickets = {}
        self.gas_readings = {}
        self.disposal_windows = {}
        self.scale_reservations = {}
        self.invoices = {}
        self.payments = {}
        self.fill_seq = {}  # facility_id -> next fill_sequence


db = Store()
_seq_counter = itertools.count(1)


# --------------------------------------------------------------------------- #
# Errors
# --------------------------------------------------------------------------- #
class ApiError(Exception):
    def __init__(self, error_id, http_status, message=""):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def now_iso():
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def gen_id():
    return str(uuid.uuid4())


def gen_req_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def num(v):
    """Serialize a Decimal/number: int if integral, else float. None passthrough."""
    if v is None:
        return None
    d = v if isinstance(v, Decimal) else Decimal(str(v))
    if d == d.to_integral_value():
        return int(d)
    return float(d)


def stamp_new(obj, common=True):
    obj["id"] = gen_id()
    obj["created_at"] = now_iso()
    obj["_seq"] = next(_seq_counter)
    if common:
        obj["updated_at"] = obj["created_at"]
        obj["version"] = 1
    return obj


def touch(obj):
    obj["updated_at"] = now_iso()
    obj["version"] = obj.get("version", 1) + 1


def parse_dt(s):
    if not isinstance(s, str) or not s.strip():
        raise ValueError("bad datetime")
    t = s.strip()
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    dt = datetime.fromisoformat(t)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


# --------------------------------------------------------------------------- #
# Response envelope
# --------------------------------------------------------------------------- #
def envelope(response_type, data, extra_meta=None):
    meta = {"api_request_id": gen_req_id(), "api_request_timestamp": now_iso()}
    if extra_meta:
        meta.update(extra_meta)
    return {"meta": meta, "response_type": response_type, "data": data}


def ok(data, status=200):
    return jsonify(envelope("object", data)), status


def ok_list(items):
    page, meta = paginate(items)
    return jsonify(envelope("array", page, meta)), 200


@app.errorhandler(ApiError)
def handle_api_error(e):
    data = {"error_id": e.error_id, "message": e.message}
    return jsonify(envelope("error", data)), e.http_status


@app.errorhandler(404)
def handle_404(e):
    data = {"error_id": "ERR_NOT_FOUND", "message": "Resource not found"}
    return jsonify(envelope("error", data)), 404


@app.errorhandler(405)
def handle_405(e):
    data = {"error_id": "ERR_NOT_FOUND", "message": "Method not allowed"}
    return jsonify(envelope("error", data)), 405


# --------------------------------------------------------------------------- #
# Auth / RBAC / body / pagination
# --------------------------------------------------------------------------- #
def auth():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", 401, "Missing or unrecognized auth headers")
    return uid, role


def authz(role, allowed):
    if role not in allowed:
        raise ApiError("ERR_UNAUTHORIZED", 403, "Role not permitted for this operation")


def body():
    j = request.get_json(force=True, silent=True)
    return j if isinstance(j, dict) else {}


def require_fields(b, fields):
    for f in fields:
        if f not in b or b[f] is None:
            raise ApiError("ERR_VALIDATION", 422, f"Missing required field: {f}")


def get_number(b, field, required=True, non_negative=True):
    if field not in b or b[field] is None:
        if required:
            raise ApiError("ERR_VALIDATION", 422, f"Missing required field: {field}")
        return None
    v = b[field]
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ApiError("ERR_VALIDATION", 422, f"Invalid number: {field}")
    if non_negative and v < 0:
        raise ApiError("ERR_VALIDATION", 422, f"Must be non-negative: {field}")
    return D(str(v))


def get_int(b, field, required=True, non_negative=True):
    if field not in b or b[field] is None:
        if required:
            raise ApiError("ERR_VALIDATION", 422, f"Missing required field: {field}")
        return None
    v = b[field]
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError("ERR_VALIDATION", 422, f"Invalid integer: {field}")
    if non_negative and v < 0:
        raise ApiError("ERR_VALIDATION", 422, f"Must be non-negative: {field}")
    return v


def get_string(b, field, required=True):
    if field not in b or b[field] is None:
        if required:
            raise ApiError("ERR_VALIDATION", 422, f"Missing required field: {field}")
        return None
    v = b[field]
    if not isinstance(v, str) or v == "":
        raise ApiError("ERR_VALIDATION", 422, f"Invalid string: {field}")
    return v


def get_enum(b, field, allowed, required=True):
    v = get_string(b, field, required=required)
    if v is None:
        return None
    if v not in allowed:
        raise ApiError("ERR_VALIDATION", 422, f"Invalid enum value for {field}")
    return v


def parse_limit():
    raw = request.args.get("limit")
    if raw is None:
        return 10
    try:
        v = int(raw)
    except (ValueError, TypeError):
        return 10
    if v < 1:
        v = 1
    if v > 100:
        v = 100
    return v


def parse_offset():
    raw = request.args.get("offset")
    if raw is None:
        return 0
    try:
        v = int(raw)
    except (ValueError, TypeError):
        return 0
    return max(v, 0)


def sort_created(items):
    return sorted(items, key=lambda o: (o["created_at"], o["_seq"]))


def paginate(items):
    items = sort_created(items)
    limit = parse_limit()
    offset = parse_offset()
    total = len(items)
    page = items[offset:offset + limit]
    meta = {"limit": limit, "offset": offset, "total_count": total,
            "has_more": offset + limit < total}
    return [serialize(o) for o in page], meta


# --------------------------------------------------------------------------- #
# Existence lookups
# --------------------------------------------------------------------------- #
def get_or_404(coll, rid):
    obj = coll.get(rid)
    if obj is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Resource not found")
    return obj


# --------------------------------------------------------------------------- #
# Computed facility helpers
# --------------------------------------------------------------------------- #
def facility_cells(fac_id):
    return [c for c in db.cells.values() if c["facility_id"] == fac_id]


def facility_tickets(fac_id):
    return [t for t in db.tickets.values() if t["facility_id"] == fac_id]


def facility_consumed(fac_id):
    total = D(0)
    for c in facility_cells(fac_id):
        total += c["consumed_cubic_yards"]
    return total


def facility_latest_ppm(fac_id):
    readings = [r for r in db.gas_readings.values() if r["facility_id"] == fac_id]
    if not readings:
        return 0
    latest = max(readings, key=lambda r: (r["_reading_dt"], r["created_at"], r["_seq"]))
    return latest["methane_ppm"]


def facility_computed(fac):
    fid = fac["id"]
    total = fac["total_airspace_cubic_yards"]
    consumed = facility_consumed(fid)
    remaining = total - consumed
    ppm = facility_latest_ppm(fid)
    gas = calc.gas_status_for(ppm)
    posture = calc.acceptance_posture(gas, remaining, total)

    prov_scope, final_scope = [], []
    prov_flags, final_flags = [], []
    for t in facility_tickets(fid):
        if t["net_weight_tons"] is None:
            continue
        if t["status"] in ("INSPECTED", "POSTED"):
            prov_scope.append(t["net_weight_tons"])
            prov_flags.append(t["is_diverted"])
        if t["status"] == "POSTED":
            final_scope.append(t["net_weight_tons"])
            final_flags.append(t["is_diverted"])
    d_prov = calc.diversion_rate(prov_scope, prov_flags)
    d_final = calc.diversion_rate(final_scope, final_flags)
    return {
        "consumed": consumed, "remaining": remaining, "ppm": ppm,
        "gas_status": gas, "posture": posture,
        "d_prov": d_prov, "d_final": d_final,
    }


# --------------------------------------------------------------------------- #
# Serializers
# --------------------------------------------------------------------------- #
def serialize(obj):
    return obj["_serialize"](obj)


def ser_facility(f):
    c = facility_computed(f)
    return {
        "id": f["id"],
        "name": f["name"],
        "total_airspace_cubic_yards": num(f["total_airspace_cubic_yards"]),
        "consumed_airspace_cubic_yards": num(c["consumed"]),
        "remaining_airspace_cubic_yards": num(c["remaining"]),
        "latest_methane_ppm": c["ppm"],
        "gas_status": c["gas_status"],
        "acceptance_posture": c["posture"],
        "diversion_rate_provisional": num(c["d_prov"]),
        "diversion_rate_final": num(c["d_final"]),
        "created_at": f["created_at"],
        "updated_at": f["updated_at"],
        "version": f["version"],
    }


def ser_cell(c):
    remaining = c["capacity_cubic_yards"] - c["consumed_cubic_yards"]
    return {
        "id": c["id"],
        "facility_id": c["facility_id"],
        "name": c["name"],
        "capacity_cubic_yards": num(c["capacity_cubic_yards"]),
        "consumed_cubic_yards": num(c["consumed_cubic_yards"]),
        "remaining_cubic_yards": num(remaining),
        "fill_sequence": c["fill_sequence"],
        "status": c["status"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def ser_hauler(h):
    return {
        "id": h["id"],
        "name": h["name"],
        "credit_limit_cents": h["credit_limit_cents"],
        "balance_cents": h["balance_cents"],
        "status": h["status"],
        "created_at": h["created_at"],
        "updated_at": h["updated_at"],
        "version": h["version"],
    }


def ser_manifest(m):
    return {
        "id": m["id"],
        "hauler_account_id": m["hauler_account_id"],
        "declared_material": m["declared_material"],
        "declared_weight_tons": num(m["declared_weight_tons"]),
        "is_special_waste": m["is_special_waste"],
        "special_waste_cleared": m["special_waste_cleared"],
        "status": m["status"],
        "created_at": m["created_at"],
        "updated_at": m["updated_at"],
        "version": m["version"],
    }


def ser_approval(a):
    return {
        "id": a["id"],
        "manifest_id": a["manifest_id"],
        "waste_type": a["waste_type"],
        "profile_ref": a["profile_ref"],
        "status": a["status"],
        "decided_by": a["decided_by"],
        "decision_note": a["decision_note"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


def ser_ticket(t):
    return {
        "id": t["id"],
        "facility_id": t["facility_id"],
        "hauler_account_id": t["hauler_account_id"],
        "manifest_id": t["manifest_id"],
        "cell_id": t["cell_id"],
        "invoice_id": t["invoice_id"],
        "material": t["material"],
        "gross_weight_tons": num(t["gross_weight_tons"]),
        "tare_weight_tons": num(t["tare_weight_tons"]),
        "net_weight_tons": num(t["net_weight_tons"]),
        "is_diverted": t["is_diverted"],
        "estimated_fee_cents": t["estimated_fee_cents"],
        "tipping_fee_cents": t["tipping_fee_cents"],
        "posted_airspace_cy": num(t["posted_airspace_cy"]),
        "inspected_by": t["inspected_by"],
        "status": t["status"],
        "created_at": t["created_at"],
        "updated_at": t["updated_at"],
        "version": t["version"],
    }


def ser_gas_reading(g):
    return {
        "id": g["id"],
        "facility_id": g["facility_id"],
        "methane_ppm": g["methane_ppm"],
        "reading_at": g["reading_at"],
        "resulting_gas_status": g["resulting_gas_status"],
        "created_at": g["created_at"],
    }


def ser_disposal_window(w):
    return {
        "id": w["id"],
        "cell_id": w["cell_id"],
        "waste_type": w["waste_type"],
        "window_start": w["window_start"],
        "window_end": w["window_end"],
        "status": w["status"],
        "created_at": w["created_at"],
        "updated_at": w["updated_at"],
        "version": w["version"],
    }


def ser_scale_reservation(r):
    return {
        "id": r["id"],
        "facility_id": r["facility_id"],
        "lane_number": r["lane_number"],
        "truck_ref": r["truck_ref"],
        "window_start": r["window_start"],
        "window_end": r["window_end"],
        "status": r["status"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def ser_invoice(inv):
    paid = invoice_amount_paid(inv)
    return {
        "id": inv["id"],
        "hauler_account_id": inv["hauler_account_id"],
        "line_ticket_ids": list(inv["line_ticket_ids"]),
        "line_count": inv["line_count"],
        "tipping_subtotal_cents": inv["tipping_subtotal_cents"],
        "total_cents": inv["total_cents"],
        "amount_paid_cents": paid,
        "status": inv["status"],
        "created_at": inv["created_at"],
        "updated_at": inv["updated_at"],
        "version": inv["version"],
    }


def ser_payment(p):
    return {
        "id": p["id"],
        "invoice_id": p["invoice_id"],
        "amount_cents": p["amount_cents"],
        "method": p["method"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def invoice_amount_paid(inv):
    return sum(p["amount_cents"] for p in db.payments.values()
               if p["invoice_id"] == inv["id"])


# =========================================================================== #
# Facility endpoints
# =========================================================================== #
@app.post("/landfill/facilities")
def create_facility():
    _, role = auth()
    authz(role, {"FacilityAdmin"})
    b = body()
    require_fields(b, ["name", "total_airspace_cubic_yards"])
    name = get_string(b, "name")
    total = get_number(b, "total_airspace_cubic_yards")
    f = {"name": name, "total_airspace_cubic_yards": total, "_serialize": ser_facility}
    stamp_new(f)
    db.facilities[f["id"]] = f
    db.fill_seq[f["id"]] = itertools.count(1)
    return ok(ser_facility(f), 201)


@app.get("/landfill/facilities/<fid>")
def get_facility(fid):
    _, role = auth()
    authz(role, ROLES)
    f = get_or_404(db.facilities, fid)
    return ok(ser_facility(f))


# =========================================================================== #
# Cell endpoints
# =========================================================================== #
@app.post("/landfill/facilities/<fid>/cells")
def create_cell(fid):
    _, role = auth()
    authz(role, {"FacilityAdmin"})
    b = body()
    require_fields(b, ["name", "capacity_cubic_yards"])
    name = get_string(b, "name")
    capacity = get_number(b, "capacity_cubic_yards")
    f = get_or_404(db.facilities, fid)
    seq = next(db.fill_seq[f["id"]])
    c = {
        "facility_id": f["id"], "name": name,
        "capacity_cubic_yards": capacity, "consumed_cubic_yards": D(0),
        "fill_sequence": seq, "status": "OPEN", "_serialize": ser_cell,
    }
    stamp_new(c)
    db.cells[c["id"]] = c
    return ok(ser_cell(c), 201)


@app.get("/landfill/facilities/<fid>/cells")
def list_cells(fid):
    _, role = auth()
    authz(role, {"FacilityAdmin", "GateOperator", "EnvironmentalOfficer"})
    get_or_404(db.facilities, fid)
    items = [c for c in db.cells.values() if c["facility_id"] == fid]
    return ok_list(items)


@app.get("/landfill/cells/<cid>")
def get_cell(cid):
    _, role = auth()
    authz(role, {"FacilityAdmin", "GateOperator", "EnvironmentalOfficer"})
    c = get_or_404(db.cells, cid)
    return ok(ser_cell(c))


# =========================================================================== #
# HaulerAccount endpoints
# =========================================================================== #
@app.post("/landfill/hauler-accounts")
def create_hauler():
    _, role = auth()
    authz(role, {"FacilityAdmin"})
    b = body()
    require_fields(b, ["name", "credit_limit_cents"])
    name = get_string(b, "name")
    limit = get_int(b, "credit_limit_cents")
    h = {"name": name, "credit_limit_cents": limit, "balance_cents": 0,
         "status": "ACTIVE", "_serialize": ser_hauler}
    stamp_new(h)
    db.hauler_accounts[h["id"]] = h
    return ok(ser_hauler(h), 201)


@app.get("/landfill/hauler-accounts/<hid>")
def get_hauler(hid):
    _, role = auth()
    authz(role, {"FacilityAdmin", "BillingClerk", "Hauler"})
    h = get_or_404(db.hauler_accounts, hid)
    return ok(ser_hauler(h))


# =========================================================================== #
# Manifest endpoints
# =========================================================================== #
@app.post("/landfill/manifests")
def create_manifest():
    uid, role = auth()
    authz(role, {"Hauler"})
    b = body()
    require_fields(b, ["hauler_account_id", "declared_material", "declared_weight_tons"])
    hauler_id = get_string(b, "hauler_account_id")
    material = get_enum(b, "declared_material", MATERIALS)
    weight = get_number(b, "declared_weight_tons")
    # existence
    h = get_or_404(db.hauler_accounts, hauler_id)
    # ownership (Hauler on its own account)
    if uid != h["id"]:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", 403, "Hauler may only act on its own account")
    m = {
        "hauler_account_id": h["id"], "declared_material": material,
        "declared_weight_tons": weight,
        "is_special_waste": material in SPECIAL_MATERIALS,
        "special_waste_cleared": False, "status": "DRAFT", "_serialize": ser_manifest,
    }
    stamp_new(m)
    db.manifests[m["id"]] = m
    return ok(ser_manifest(m), 201)


@app.get("/landfill/manifests/<mid>")
def get_manifest(mid):
    _, role = auth()
    authz(role, {"Hauler", "GateOperator", "EnvironmentalOfficer"})
    m = get_or_404(db.manifests, mid)
    return ok(ser_manifest(m))


@app.get("/landfill/manifests")
def list_manifests():
    _, role = auth()
    authz(role, {"Hauler", "GateOperator", "EnvironmentalOfficer"})
    items = list(db.manifests.values())
    hauler_id = request.args.get("hauler_account_id")
    if hauler_id is not None:
        items = [m for m in items if m["hauler_account_id"] == hauler_id]
    return ok_list(items)


@app.post("/landfill/manifests/<mid>/submit")
def submit_manifest(mid):
    uid, role = auth()
    authz(role, {"Hauler"})
    m = get_or_404(db.manifests, mid)
    # ownership
    if uid != m["hauler_account_id"]:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", 403, "Hauler may only act on its own manifest")
    # state
    if m["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", 409, "Manifest not in DRAFT")
    # cross-entity guard: hauler must be ACTIVE
    h = db.hauler_accounts[m["hauler_account_id"]]
    if h["status"] != "ACTIVE":
        raise ApiError("ERR_HAULER_SUSPENDED", 409, "Hauler account is not ACTIVE")
    m["status"] = "SUBMITTED"
    touch(m)
    return ok(ser_manifest(m))


# =========================================================================== #
# SpecialWasteApproval endpoints
# =========================================================================== #
@app.post("/landfill/manifests/<mid>/special-waste-approvals")
def create_approval(mid):
    _, role = auth()
    authz(role, {"Hauler", "EnvironmentalOfficer"})
    b = body()
    require_fields(b, ["waste_type", "profile_ref"])
    waste_type = get_enum(b, "waste_type", WASTE_TYPES)
    profile_ref = get_string(b, "profile_ref")
    m = get_or_404(db.manifests, mid)
    a = {
        "manifest_id": m["id"], "waste_type": waste_type, "profile_ref": profile_ref,
        "status": "PENDING", "decided_by": None, "decision_note": None,
        "_serialize": ser_approval,
    }
    stamp_new(a)
    db.approvals[a["id"]] = a
    return ok(ser_approval(a), 201)


@app.get("/landfill/manifests/<mid>/special-waste-approvals")
def list_approvals(mid):
    _, role = auth()
    authz(role, {"Hauler", "EnvironmentalOfficer", "GateOperator"})
    get_or_404(db.manifests, mid)
    items = [a for a in db.approvals.values() if a["manifest_id"] == mid]
    return ok_list(items)


@app.post("/landfill/special-waste-approvals/<aid>/decide")
def decide_approval(aid):
    uid, role = auth()
    authz(role, {"EnvironmentalOfficer"})
    b = body()
    require_fields(b, ["decision"])
    decision = get_enum(b, "decision", {"APPROVE", "DENY"})
    note = get_string(b, "decision_note", required=False)
    a = get_or_404(db.approvals, aid)
    if a["status"] != "PENDING":
        raise ApiError("ERR_INVALID_STATE", 409, "Approval already decided")
    a["decided_by"] = uid
    a["decision_note"] = note
    if decision == "APPROVE":
        a["status"] = "APPROVED"
        m = db.manifests.get(a["manifest_id"])
        if m is not None:
            m["special_waste_cleared"] = True
            touch(m)
    else:
        a["status"] = "DENIED"
    touch(a)
    return ok(ser_approval(a))


# =========================================================================== #
# Ticket endpoints
# =========================================================================== #
@app.post("/landfill/tickets")
def create_ticket():
    _, role = auth()
    authz(role, {"GateOperator"})
    b = body()
    require_fields(b, ["facility_id", "hauler_account_id", "material", "gross_weight_tons"])
    facility_id = get_string(b, "facility_id")
    hauler_id = get_string(b, "hauler_account_id")
    material = get_enum(b, "material", MATERIALS)
    gross = get_number(b, "gross_weight_tons")
    manifest_id = get_string(b, "manifest_id", required=False)
    # special-waste materials require a manifest_id (PRD §3.3)
    if material in SPECIAL_MATERIALS and not manifest_id:
        raise ApiError("ERR_VALIDATION", 422, "manifest_id required for special-waste material")
    # existence (left to right): facility, hauler, manifest
    fac = get_or_404(db.facilities, facility_id)
    h = get_or_404(db.hauler_accounts, hauler_id)
    if manifest_id is not None:
        get_or_404(db.manifests, manifest_id)

    is_diverted = material in calc.DIVERTED_MATERIALS
    if manifest_id is not None:
        est_weight = db.manifests[manifest_id]["declared_weight_tons"]
    else:
        est_weight = gross
    estimated = calc.tipping_fee_cents(material, est_weight, "provisional", None)

    t = {
        "facility_id": fac["id"], "hauler_account_id": h["id"],
        "manifest_id": manifest_id, "cell_id": None, "invoice_id": None,
        "material": material, "gross_weight_tons": gross,
        "tare_weight_tons": None, "net_weight_tons": None,
        "is_diverted": is_diverted, "estimated_fee_cents": estimated,
        "tipping_fee_cents": None, "posted_airspace_cy": None,
        "inspected_by": None, "reject_reason": None,
        "status": "CREATED", "_serialize": ser_ticket,
    }
    stamp_new(t)
    db.tickets[t["id"]] = t
    return ok(ser_ticket(t), 201)


@app.get("/landfill/tickets/<tid>")
def get_ticket(tid):
    _, role = auth()
    authz(role, {"GateOperator", "EnvironmentalOfficer", "BillingClerk", "Hauler"})
    t = get_or_404(db.tickets, tid)
    return ok(ser_ticket(t))


@app.get("/landfill/tickets")
def list_tickets():
    _, role = auth()
    authz(role, {"GateOperator", "EnvironmentalOfficer", "BillingClerk", "Hauler"})
    items = list(db.tickets.values())
    for key in ("facility_id", "hauler_account_id", "manifest_id", "cell_id", "invoice_id"):
        val = request.args.get(key)
        if val is not None:
            items = [t for t in items if t[key] == val]
    return ok_list(items)


@app.post("/landfill/tickets/<tid>/weigh-out")
def weigh_out(tid):
    _, role = auth()
    authz(role, {"GateOperator"})
    b = body()
    require_fields(b, ["tare_weight_tons"])
    tare = get_number(b, "tare_weight_tons")
    t = get_or_404(db.tickets, tid)
    if t["status"] != "CREATED":
        raise ApiError("ERR_INVALID_STATE", 409, "Ticket not in CREATED")
    gross = t["gross_weight_tons"]
    if tare > gross:
        raise ApiError("ERR_INVALID_WEIGHT", 409, "Tare exceeds gross")
    net = gross - tare
    if net <= 0:
        raise ApiError("ERR_EMPTY_LOAD", 409, "Net weight not positive")
    t["tare_weight_tons"] = tare
    t["net_weight_tons"] = net
    t["is_diverted"] = t["material"] in calc.DIVERTED_MATERIALS
    fac = db.facilities[t["facility_id"]]
    gas = facility_computed(fac)["gas_status"]
    t["tipping_fee_cents"] = calc.tipping_fee_cents(t["material"], net, "final", gas)
    t["status"] = "WEIGHED"
    touch(t)
    return ok(ser_ticket(t))


@app.post("/landfill/tickets/<tid>/inspect")
def inspect(tid):
    uid, role = auth()
    authz(role, {"GateOperator"})
    b = body()
    require_fields(b, ["result"])
    result = get_enum(b, "result", {"PASS", "REJECT"})
    reject_reason = get_string(b, "reject_reason", required=False)
    t = get_or_404(db.tickets, tid)
    if t["status"] != "WEIGHED":
        raise ApiError("ERR_INVALID_STATE", 409, "Ticket not in WEIGHED")
    if result == "PASS":
        t["status"] = "INSPECTED"
        t["inspected_by"] = uid
    else:
        t["status"] = "REJECTED"
        t["reject_reason"] = reject_reason
    touch(t)
    return ok(ser_ticket(t))


@app.post("/landfill/tickets/<tid>/post")
def post_ticket(tid):
    uid, role = auth()
    authz(role, {"GateOperator"})
    b = body()
    require_fields(b, ["expected_facility_version"])
    expected = get_int(b, "expected_facility_version")
    t = get_or_404(db.tickets, tid)
    # state
    if t["status"] != "INSPECTED":
        raise ApiError("ERR_INVALID_STATE", 409, "Ticket not in INSPECTED")
    fac = db.facilities[t["facility_id"]]
    # facility version (412)
    if expected != fac["version"]:
        raise ApiError("ERR_STALE_FACILITY_VERSION", 412, "Stale facility version")
    # segregation of duties (409)
    if uid == t["inspected_by"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES", 409, "Poster equals inspector")
    # posture safety (409)
    comp = facility_computed(fac)
    if comp["posture"] == "CLOSED":
        raise ApiError("ERR_FACILITY_CLOSED", 409, "Facility acceptance posture is CLOSED")
    # special-waste clearance (409)
    if t["material"] in SPECIAL_MATERIALS:
        m = db.manifests.get(t["manifest_id"]) if t["manifest_id"] else None
        if m is None or not m["special_waste_cleared"]:
            raise ApiError("ERR_SPECIAL_WASTE_NOT_APPROVED", 409, "Special waste not cleared")
    # manifest mismatch (409)
    if t["manifest_id"] is not None:
        m = db.manifests[t["manifest_id"]]
        if m["hauler_account_id"] != t["hauler_account_id"]:
            raise ApiError("ERR_MANIFEST_MISMATCH", 409, "Manifest hauler mismatch")
    # airspace / cell selection (409) — landfilled only
    net = t["net_weight_tons"]
    is_diverted = t["is_diverted"]
    airspace = calc.posted_airspace_cy(net, is_diverted)
    selected_cell = None
    if not is_diverted:
        candidates = [c for c in facility_cells(fac["id"])
                      if c["status"] == "OPEN"
                      and (c["capacity_cubic_yards"] - c["consumed_cubic_yards"]) >= airspace]
        if not candidates:
            raise ApiError("ERR_NO_AIRSPACE", 409, "No open cell with sufficient airspace")
        selected_cell = min(candidates, key=lambda c: c["fill_sequence"])
    # credit (402)
    h = db.hauler_accounts[t["hauler_account_id"]]
    fee = t["tipping_fee_cents"]
    if h["balance_cents"] + fee > h["credit_limit_cents"]:
        raise ApiError("ERR_CREDIT_LIMIT_EXCEEDED", 402, "Credit limit exceeded")

    # ---- commit ----
    t["posted_airspace_cy"] = airspace
    if selected_cell is not None:
        selected_cell["consumed_cubic_yards"] += airspace
        if selected_cell["consumed_cubic_yards"] >= selected_cell["capacity_cubic_yards"]:
            selected_cell["status"] = "FULL"
        touch(selected_cell)
        t["cell_id"] = selected_cell["id"]
    # facility mutation (version +1)
    touch(fac)
    # hauler balance
    h["balance_cents"] += fee
    if h["balance_cents"] >= h["credit_limit_cents"]:
        h["status"] = "SUSPENDED"
    touch(h)
    # manifest consumed
    if t["manifest_id"] is not None:
        m = db.manifests[t["manifest_id"]]
        m["status"] = "CONSUMED"
        touch(m)
    t["status"] = "POSTED"
    touch(t)
    return ok(ser_ticket(t))


@app.post("/landfill/tickets/<tid>/void")
def void_ticket(tid):
    _, role = auth()
    authz(role, {"GateOperator"})
    t = get_or_404(db.tickets, tid)
    if t["status"] not in ("CREATED", "POSTED"):
        raise ApiError("ERR_INVALID_STATE", 409, "Ticket not voidable from current state")
    if t["status"] == "POSTED":
        # reverse airspace
        if t["cell_id"] is not None:
            c = db.cells[t["cell_id"]]
            c["consumed_cubic_yards"] -= t["posted_airspace_cy"]
            remaining = c["capacity_cubic_yards"] - c["consumed_cubic_yards"]
            if c["status"] == "FULL" and remaining > 0:
                c["status"] = "OPEN"
            touch(c)
        fac = db.facilities[t["facility_id"]]
        touch(fac)
        # reverse balance
        h = db.hauler_accounts[t["hauler_account_id"]]
        h["balance_cents"] -= t["tipping_fee_cents"]
        if h["balance_cents"] < h["credit_limit_cents"] and h["status"] == "SUSPENDED":
            h["status"] = "ACTIVE"
        touch(h)
    t["status"] = "VOIDED"
    touch(t)
    return ok(ser_ticket(t))


# =========================================================================== #
# GasReading endpoints
# =========================================================================== #
@app.post("/landfill/facilities/<fid>/gas-readings")
def create_gas_reading(fid):
    _, role = auth()
    authz(role, {"EnvironmentalOfficer"})
    b = body()
    require_fields(b, ["methane_ppm", "reading_at"])
    ppm = get_int(b, "methane_ppm")
    reading_at = get_string(b, "reading_at")
    try:
        rdt = parse_dt(reading_at)
    except ValueError:
        raise ApiError("ERR_VALIDATION", 422, "Invalid reading_at datetime")
    f = get_or_404(db.facilities, fid)
    g = {
        "facility_id": f["id"], "methane_ppm": ppm, "reading_at": reading_at,
        "_reading_dt": rdt, "resulting_gas_status": calc.gas_status_for(ppm),
        "_serialize": ser_gas_reading,
    }
    stamp_new(g, common=False)
    db.gas_readings[g["id"]] = g
    return ok(ser_gas_reading(g), 201)


@app.get("/landfill/facilities/<fid>/gas-readings")
def list_gas_readings(fid):
    _, role = auth()
    authz(role, {"EnvironmentalOfficer", "FacilityAdmin"})
    get_or_404(db.facilities, fid)
    items = [g for g in db.gas_readings.values() if g["facility_id"] == fid]
    return ok_list(items)


# =========================================================================== #
# DisposalWindow endpoints
# =========================================================================== #
@app.post("/landfill/cells/<cid>/disposal-windows")
def create_disposal_window(cid):
    _, role = auth()
    authz(role, {"EnvironmentalOfficer"})
    b = body()
    require_fields(b, ["waste_type", "window_start", "window_end"])
    waste_type = get_enum(b, "waste_type", WASTE_TYPES)
    ws = get_string(b, "window_start")
    we = get_string(b, "window_end")
    try:
        wsd = parse_dt(ws)
        wed = parse_dt(we)
    except ValueError:
        raise ApiError("ERR_VALIDATION", 422, "Invalid window datetime")
    if wed <= wsd:
        raise ApiError("ERR_VALIDATION", 422, "window_end must be > window_start")
    c = get_or_404(db.cells, cid)
    # closed-interval conflict against existing windows on the same cell
    for w in db.disposal_windows.values():
        if w["cell_id"] != c["id"] or w["status"] != "SCHEDULED":
            continue
        if wsd <= w["_end_dt"] and w["_start_dt"] <= wed:
            raise ApiError("ERR_WINDOW_CONFLICT", 409, "Disposal window conflict")
    w = {
        "cell_id": c["id"], "waste_type": waste_type,
        "window_start": ws, "window_end": we,
        "_start_dt": wsd, "_end_dt": wed, "status": "SCHEDULED",
        "_serialize": ser_disposal_window,
    }
    stamp_new(w)
    db.disposal_windows[w["id"]] = w
    return ok(ser_disposal_window(w), 201)


@app.get("/landfill/cells/<cid>/disposal-windows")
def list_disposal_windows(cid):
    _, role = auth()
    authz(role, {"EnvironmentalOfficer", "FacilityAdmin"})
    get_or_404(db.cells, cid)
    items = [w for w in db.disposal_windows.values() if w["cell_id"] == cid]
    return ok_list(items)


# =========================================================================== #
# ScaleReservation endpoints
# =========================================================================== #
@app.post("/landfill/facilities/<fid>/scale-reservations")
def create_scale_reservation(fid):
    _, role = auth()
    authz(role, {"Hauler", "GateOperator"})
    b = body()
    require_fields(b, ["lane_number", "truck_ref", "window_start", "window_end"])
    lane = get_int(b, "lane_number")
    truck_ref = get_string(b, "truck_ref")
    ws = get_string(b, "window_start")
    we = get_string(b, "window_end")
    try:
        wsd = parse_dt(ws)
        wed = parse_dt(we)
    except ValueError:
        raise ApiError("ERR_VALIDATION", 422, "Invalid window datetime")
    if wed <= wsd:
        raise ApiError("ERR_VALIDATION", 422, "window_end must be > window_start")
    f = get_or_404(db.facilities, fid)
    # posture safety
    if facility_computed(f)["posture"] == "CLOSED":
        raise ApiError("ERR_FACILITY_CLOSED", 409, "Facility acceptance posture is CLOSED")
    # half-open interval overlap on same facility+lane
    for r in db.scale_reservations.values():
        if r["facility_id"] != f["id"] or r["lane_number"] != lane or r["status"] != "RESERVED":
            continue
        if wsd < r["_end_dt"] and r["_start_dt"] < wed:
            raise ApiError("ERR_LANE_OCCUPIED", 409, "Lane occupied for overlapping window")
    r = {
        "facility_id": f["id"], "lane_number": lane, "truck_ref": truck_ref,
        "window_start": ws, "window_end": we,
        "_start_dt": wsd, "_end_dt": wed, "status": "RESERVED",
        "_serialize": ser_scale_reservation,
    }
    stamp_new(r)
    db.scale_reservations[r["id"]] = r
    return ok(ser_scale_reservation(r), 201)


@app.get("/landfill/facilities/<fid>/scale-reservations")
def list_scale_reservations(fid):
    _, role = auth()
    authz(role, {"Hauler", "GateOperator", "FacilityAdmin"})
    get_or_404(db.facilities, fid)
    items = [r for r in db.scale_reservations.values() if r["facility_id"] == fid]
    lane = request.args.get("lane_number")
    if lane is not None:
        try:
            lane_i = int(lane)
            items = [r for r in items if r["lane_number"] == lane_i]
        except (ValueError, TypeError):
            items = []
    return ok_list(items)


# =========================================================================== #
# Invoice endpoints
# =========================================================================== #
@app.post("/landfill/invoices")
def create_invoice():
    _, role = auth()
    authz(role, {"BillingClerk"})
    b = body()
    require_fields(b, ["hauler_account_id"])
    hauler_id = get_string(b, "hauler_account_id")
    h = get_or_404(db.hauler_accounts, hauler_id)
    lines = [t for t in db.tickets.values()
             if t["hauler_account_id"] == h["id"]
             and t["status"] == "POSTED" and t["invoice_id"] is None]
    if not lines:
        raise ApiError("ERR_NO_BILLABLE_TICKETS", 409, "No billable tickets")
    lines = sort_created(lines)
    line_ids = [t["id"] for t in lines]
    subtotal = sum(t["tipping_fee_cents"] for t in lines)
    total = calc.invoice_total_cents([t["tipping_fee_cents"] for t in lines])
    inv = {
        "hauler_account_id": h["id"], "line_ticket_ids": line_ids,
        "line_count": len(line_ids), "tipping_subtotal_cents": subtotal,
        "total_cents": total, "status": "ISSUED", "_serialize": ser_invoice,
    }
    stamp_new(inv)
    db.invoices[inv["id"]] = inv
    for t in lines:
        t["invoice_id"] = inv["id"]
        touch(t)
    return ok(ser_invoice(inv), 201)


@app.get("/landfill/invoices/<iid>")
def get_invoice(iid):
    _, role = auth()
    authz(role, {"BillingClerk", "Hauler"})
    inv = get_or_404(db.invoices, iid)
    return ok(ser_invoice(inv))


@app.get("/landfill/invoices")
def list_invoices():
    _, role = auth()
    authz(role, {"BillingClerk", "Hauler"})
    items = list(db.invoices.values())
    hauler_id = request.args.get("hauler_account_id")
    if hauler_id is not None:
        items = [i for i in items if i["hauler_account_id"] == hauler_id]
    return ok_list(items)


# =========================================================================== #
# Payment endpoints
# =========================================================================== #
@app.post("/landfill/invoices/<iid>/payments")
def create_payment(iid):
    uid, role = auth()
    authz(role, {"BillingClerk", "Hauler"})
    b = body()
    require_fields(b, ["amount_cents", "method"])
    amount = get_int(b, "amount_cents")
    method = get_enum(b, "method", PAYMENT_METHODS)
    inv = get_or_404(db.invoices, iid)
    # ownership (Hauler pays only own invoice)
    if role == "Hauler" and uid != inv["hauler_account_id"]:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", 403, "Hauler may only pay its own invoice")
    # state
    if inv["status"] != "ISSUED":
        raise ApiError("ERR_INVALID_STATE", 409, "Invoice not in ISSUED")
    p = {"invoice_id": inv["id"], "amount_cents": amount, "method": method,
         "_serialize": ser_payment}
    stamp_new(p)
    db.payments[p["id"]] = p
    # settlement
    if invoice_amount_paid(inv) >= inv["total_cents"]:
        inv["status"] = "PAID"
        touch(inv)
        h = db.hauler_accounts[inv["hauler_account_id"]]
        released = 0
        for tid in inv["line_ticket_ids"]:
            t = db.tickets.get(tid)
            if t is not None:
                released += t["tipping_fee_cents"]
        h["balance_cents"] -= released
        if h["balance_cents"] < h["credit_limit_cents"] and h["status"] == "SUSPENDED":
            h["status"] = "ACTIVE"
        touch(h)
    return ok(ser_payment(p), 201)


@app.get("/landfill/invoices/<iid>/payments")
def list_payments(iid):
    _, role = auth()
    authz(role, {"BillingClerk", "Hauler"})
    get_or_404(db.invoices, iid)
    items = [p for p in db.payments.values() if p["invoice_id"] == iid]
    return ok_list(items)


# --------------------------------------------------------------------------- #
if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
