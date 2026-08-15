"""Forest Nursery & Reforestation Contract API — in-memory Flask implementation."""
import itertools
import os
import re
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP

from flask import Flask, jsonify, request

app = Flask(__name__)
app.url_map.strict_slashes = False

# ---------------------------------------------------------------------------
# In-memory store (empty on every boot; no seeding)
# ---------------------------------------------------------------------------
STORE = {
    "landowners": {},
    "seed_zones": {},
    "seed_lots": {},
    "crop_batches": {},
    "seedling_orders": {},
    "allocations": {},
    "storage_units": {},
    "storage_placements": {},
    "planting_contracts": {},
    "crews": {},
    "crew_assignments": {},
    "shipments": {},
    "survival_surveys": {},
    "cost_share_enrollments": {},
}
SEQ = itertools.count(1)

# Logical clock: server-startup default, never wall clock.
CLOCK = {"now": datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)}

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
ROLE_NAMES = ("NurseryManager", "ContractOfficer", "FieldAuditor", "ProgramAdministrator", "Landowner")
SPECIES = ("DOUGLAS_FIR", "LOBLOLLY_PINE", "WHITE_OAK")
SEEDS_PER_GRAM = {"DOUGLAS_FIR": Decimal("88"), "LOBLOLLY_PINE": Decimal("55"), "WHITE_OAK": Decimal("0.2")}
UNIT_PRICE_CENTS = {"DOUGLAS_FIR": 320, "LOBLOLLY_PINE": 280, "WHITE_OAK": 540}
LEAD_DAYS = {"DOUGLAS_FIR": 210, "LOBLOLLY_PINE": 210, "WHITE_OAK": 120}
EXPECTED_CULL_FACTOR = Decimal("0.88")  # 1 - 0.12
TIER1_MIN_CENTS = 2000000
TIER2_MIN_CENTS = 5000000
LARGE_SITE_ACRES = Decimal("50")
STEWARDSHIP_BONUS_PCT = Decimal("0.10")
STANDARD_THRESHOLD = Decimal("70.00")
COST_SHARE_THRESHOLD = Decimal("80.00")
REPEAT_FAILURE_FACTOR = Decimal("1.25")
ESCALATION_CAP_MULT = 2
HANDLING_WINDOW_HOURS = 72
COLD_STORAGE_MAX_DAYS = 45
SPOILAGE_REASONS = ("TEMP_EXCURSION", "WINDOW_EXPIRED", "HANDLING_DAMAGE")


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------
def fmt_dt(dt):
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def now_iso():
    return fmt_dt(CLOCK["now"])


def today():
    return CLOCK["now"].date()


DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def parse_date(v):
    if not isinstance(v, str) or not DATE_RE.match(v):
        return None
    try:
        return date.fromisoformat(v)
    except ValueError:
        return None


def parse_datetime(v):
    if not isinstance(v, str):
        return None
    s = v.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# ---------------------------------------------------------------------------
# Errors and envelope
# ---------------------------------------------------------------------------
class ApiError(Exception):
    def __init__(self, error_id, status, message):
        super().__init__(message)
        self.error_id = error_id
        self.status = status
        self.message = message


def err(error_id, status, message):
    raise ApiError(error_id, status, message)


def bad_request(msg):
    err("ERR_INVALID_REQUEST", 400, msg)


def not_found(msg="resource not found"):
    err("ERR_NOT_FOUND", 404, msg)


def invalid_state(msg="state forbids this transition"):
    err("ERR_INVALID_STATE", 409, msg)


def meta():
    return {
        "api_request_id": "req_" + uuid.uuid4().hex[:24],
        "api_request_timestamp": now_iso(),
    }


def success(data, code=200):
    return jsonify({"meta": meta(), "response_type": "object", "data": data}), code


def success_list(records, serialize):
    args = request.args
    try:
        limit = int(args.get("limit", 10))
        offset = int(args.get("offset", 0))
    except (TypeError, ValueError):
        bad_request("limit/offset must be integers")
    limit = max(1, min(100, limit))
    offset = max(0, offset)
    items = sorted(records, key=lambda r: r["_seq"])
    total = len(items)
    page = items[offset:offset + limit]
    m = meta()
    m.update({
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + len(page) < total,
    })
    return jsonify({"meta": m, "response_type": "array", "data": [serialize(r) for r in page]}), 200


@app.errorhandler(ApiError)
def handle_api_error(e):
    body = {"meta": meta(), "response_type": "error",
            "data": {"error_id": e.error_id, "message": e.message}}
    return jsonify(body), e.status


@app.errorhandler(404)
def handle_404(e):
    body = {"meta": meta(), "response_type": "error",
            "data": {"error_id": "ERR_NOT_FOUND", "message": "resource not found"}}
    return jsonify(body), 404


@app.errorhandler(405)
def handle_405(e):
    body = {"meta": meta(), "response_type": "error",
            "data": {"error_id": "ERR_NOT_FOUND", "message": "method not allowed"}}
    return jsonify(body), 405


@app.errorhandler(Exception)
def handle_500(e):
    body = {"meta": meta(), "response_type": "error",
            "data": {"error_id": "ERR_INTERNAL", "message": str(e)}}
    return jsonify(body), 500


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
def authenticate():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLE_NAMES:
        err("ERR_UNAUTHENTICATED", 401, "missing or invalid X-User-ID / X-User-Role headers")
    if role == "Landowner" and uid not in STORE["landowners"]:
        err("ERR_UNAUTHENTICATED", 401, "Landowner id does not resolve")
    return uid, role


def require_role(roles):
    uid, role = authenticate()
    if role not in roles:
        err("ERR_UNAUTHORIZED", 403, "role not permitted for this endpoint")
    return uid, role


def require_owner(resource, uid):
    if resource.get("landowner_id") != uid:
        err("ERR_UNAUTHORIZED", 403, "Landowner may only touch its own resources")


# ---------------------------------------------------------------------------
# Request-body field validators (raise ERR_INVALID_REQUEST)
# ---------------------------------------------------------------------------
def body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        bad_request("request body must be a JSON object")
    return data


def is_int(v):
    if isinstance(v, bool):
        return False
    if isinstance(v, int):
        return True
    if isinstance(v, float) and v.is_integer():
        return True
    return False


def v_str(d, name, required=True, nonempty=True):
    v = d.get(name)
    if v is None:
        if required:
            bad_request("missing required field: %s" % name)
        return None
    if not isinstance(v, str) or (nonempty and v == ""):
        bad_request("field %s must be a non-empty string" % name)
    return v


def v_int(d, name, required=True, minimum=None, maximum=None):
    v = d.get(name)
    if v is None:
        if required:
            bad_request("missing required field: %s" % name)
        return None
    if not is_int(v):
        bad_request("field %s must be an integer" % name)
    v = int(v)
    if minimum is not None and v < minimum:
        bad_request("field %s below minimum" % name)
    if maximum is not None and v > maximum:
        bad_request("field %s above maximum" % name)
    return v


def v_num(d, name, required=True):
    v = d.get(name)
    if v is None:
        if required:
            bad_request("missing required field: %s" % name)
        return None
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        bad_request("field %s must be a number" % name)
    return v


def v_bool(d, name, default=None):
    v = d.get(name)
    if v is None:
        return default
    if not isinstance(v, bool):
        bad_request("field %s must be a boolean" % name)
    return v


def v_date(d, name, required=True):
    v = d.get(name)
    if v is None:
        if required:
            bad_request("missing required field: %s" % name)
        return None
    parsed = parse_date(v)
    if parsed is None:
        bad_request("field %s must be an ISO date (YYYY-MM-DD)" % name)
    return parsed


def v_datetime(d, name, required=True):
    v = d.get(name)
    if v is None:
        if required:
            bad_request("missing required field: %s" % name)
        return None
    parsed = parse_datetime(v)
    if parsed is None:
        bad_request("field %s must be an ISO 8601 datetime" % name)
    return parsed


def v_enum(d, name, allowed, required=True):
    v = v_str(d, name, required=required)
    if v is None:
        return None
    if v not in allowed:
        bad_request("field %s must be one of %s" % (name, ", ".join(allowed)))
    return v


def v_fk(d, name, coll):
    """Body foreign key: missing/wrong type -> 400; unresolvable -> 404."""
    v = d.get(name)
    if v is None:
        bad_request("missing required field: %s" % name)
    if not isinstance(v, str):
        bad_request("field %s must be a string id" % name)
    rec = STORE[coll].get(v)
    if rec is None:
        not_found("%s does not resolve" % name)
    return rec


def get_path(coll, rid):
    rec = STORE[coll].get(rid)
    if rec is None:
        not_found("resource not found: %s" % rid)
    return rec


def dec(x):
    return Decimal(str(x))


# ---------------------------------------------------------------------------
# Record helpers
# ---------------------------------------------------------------------------
def create_record(coll, fields):
    rec = dict(fields)
    rec["id"] = str(uuid.uuid4())
    ts = now_iso()
    rec["created_at"] = ts
    rec["updated_at"] = ts
    rec["version"] = 1
    rec["_seq"] = next(SEQ)
    STORE[coll][rec["id"]] = rec
    return rec


def touch(rec):
    rec["updated_at"] = now_iso()
    rec["version"] += 1


# ---------------------------------------------------------------------------
# Derived (computed) values
# ---------------------------------------------------------------------------
def lot_remaining(lot):
    sown = sum(b.get("sown_grams") or 0 for b in STORE["crop_batches"].values()
               if b["seed_lot_id"] == lot["id"])
    return lot["quantity_grams"] - sown


def batch_reserved(batch_id):
    return sum(a["quantity"] for a in STORE["allocations"].values()
               if a["crop_batch_id"] == batch_id and a["status"] == "ACTIVE")


def batch_placed_remainder_capacity(batch_id):
    """Quantity already placed on non-discarded placements of the batch."""
    return sum(p["quantity"] for p in STORE["storage_placements"].values()
               if p["crop_batch_id"] == batch_id and p["status"] != "DISCARDED")


def unit_load(unit_id):
    return sum(p["quantity"] - p["withdrawn_quantity"]
               for p in STORE["storage_placements"].values()
               if p["storage_unit_id"] == unit_id and p["status"] == "ACTIVE")


def order_allocated(order_id):
    return sum(a["quantity"] for a in STORE["allocations"].values()
               if a["seedling_order_id"] == order_id and a["status"] == "ACTIVE")


def order_contracts(order_id):
    return [c for c in STORE["planting_contracts"].values() if c["seedling_order_id"] == order_id]


def order_shipped(order_id):
    cids = {c["id"] for c in order_contracts(order_id)}
    return sum(s["quantity"] for s in STORE["shipments"].values()
               if s["planting_contract_id"] in cids
               and s["status"] in ("DISPATCHED", "DELIVERED", "PLANTED"))


def contract_obligation_count(contract_id):
    return sum(1 for s in STORE["survival_surveys"].values()
               if s["planting_contract_id"] == contract_id and s["below_threshold"])


def batch_allocatable_basis(batch):
    if batch["status"] == "GRADED":
        return batch.get("plantable_count") or 0
    return batch.get("projected_plantable") or 0


# ---------------------------------------------------------------------------
# Calculations
# ---------------------------------------------------------------------------
def calc_projected_plantable(sown_grams, germination_pct, species):
    val = (Decimal(sown_grams) * SEEDS_PER_GRAM[species] * dec(germination_pct)
           * EXPECTED_CULL_FACTOR)
    return int(val.to_integral_value(rounding=ROUND_FLOOR))


def calc_order_total(quantity, species):
    subtotal = quantity * UNIT_PRICE_CENTS[species]
    if subtotal >= TIER2_MIN_CENTS:
        tier = Decimal("0.15")
    elif subtotal >= TIER1_MIN_CENTS:
        tier = Decimal("0.10")
    else:
        tier = Decimal("0")
    return int((Decimal(subtotal) * (1 - tier)).to_integral_value(rounding=ROUND_HALF_UP))


def calc_required_seedlings(acres, trees_per_acre, contingency_pct):
    a = dec(acres)
    c_eff = dec(contingency_pct) + (Decimal("0.05") if a >= LARGE_SITE_ACRES else Decimal("0"))
    val = a * trees_per_acre * (1 + c_eff)
    return int(val.to_integral_value(rounding=ROUND_CEILING))


def calc_award(basis_acres, rate_per_acre_cents, cap_cents):
    base = int((dec(basis_acres) * rate_per_acre_cents).to_integral_value(rounding=ROUND_HALF_UP))
    bonus = int((Decimal(base) * STEWARDSHIP_BONUS_PCT).to_integral_value(rounding=ROUND_HALF_UP))
    return min(cap_cents, base + bonus)


def ceil_div(a, b):
    return -(-a // b)


# ---------------------------------------------------------------------------
# Cascades
# ---------------------------------------------------------------------------
def release_allocation(alloc):
    """Release one ACTIVE allocation; demote order/contracts when coverage drops."""
    if alloc["status"] != "ACTIVE":
        return
    alloc["status"] = "RELEASED"
    touch(alloc)
    order = STORE["seedling_orders"].get(alloc["seedling_order_id"])
    if order is None:
        return
    if order["status"] == "ALLOCATED" and order_allocated(order["id"]) < order["quantity"]:
        order["status"] = "CONFIRMED"
        touch(order)
        for c in order_contracts(order["id"]):
            if c["status"] == "READY_TO_PLANT":
                c["status"] = "BLOCKED"
                touch(c)


def check_batch_depleted(batch):
    if batch["status"] != "GRADED":
        return
    plantable = batch.get("plantable_count") or 0
    total_shipped = sum(s["quantity"] for s in STORE["shipments"].values()
                        if s["crop_batch_id"] == batch["id"])
    any_active = any(p["status"] == "ACTIVE" for p in STORE["storage_placements"].values()
                     if p["crop_batch_id"] == batch["id"])
    if total_shipped == plantable and not any_active:
        batch["status"] = "DEPLETED"
        touch(batch)


def release_payment_holds(landowner_id):
    cids = {c["id"] for c in STORE["planting_contracts"].values()
            if c["landowner_id"] == landowner_id}
    open_obligation = any(
        s["planting_contract_id"] in cids and s["obligation_status"] in ("OPEN", "SCHEDULED")
        for s in STORE["survival_surveys"].values())
    if not open_obligation:
        for e in STORE["cost_share_enrollments"].values():
            if e["landowner_id"] == landowner_id and e["status"] == "PAYMENT_HELD":
                e["status"] = "APPROVED"
                touch(e)


def seed_transfer_ok(batch, order, dest_zone):
    lot = STORE["seed_lots"].get(batch["seed_lot_id"])
    src_zone = STORE["seed_zones"].get(lot["source_zone_id"]) if lot else None
    if lot is None or src_zone is None:
        return False
    if batch_species(batch) != order["species"]:
        return False
    return abs(src_zone["band_midpoint_ft"] - dest_zone["band_midpoint_ft"]) <= 500


def batch_species(batch):
    lot = STORE["seed_lots"].get(batch["seed_lot_id"])
    return lot["species"] if lot else None


# ---------------------------------------------------------------------------
# Serializers (exact scaffold field sets + common fields)
# ---------------------------------------------------------------------------
def common(rec):
    return {"id": rec["id"], "created_at": rec["created_at"],
            "updated_at": rec["updated_at"], "version": rec["version"]}


def ser_landowner(r):
    out = {"legal_name": r["legal_name"], "contact_email": r["contact_email"],
           "tax_id": r["tax_id"], "cost_share_eligible": r["cost_share_eligible"]}
    out.update(common(r))
    return out


def ser_seed_zone(r):
    out = {"zone_code": r["zone_code"], "min_elevation_ft": r["min_elevation_ft"],
           "max_elevation_ft": r["max_elevation_ft"], "band_midpoint_ft": r["band_midpoint_ft"]}
    out.update(common(r))
    return out


def ser_seed_lot(r):
    out = {"source_zone_id": r["source_zone_id"], "species": r["species"],
           "collected_on": r["collected_on"].isoformat(), "quantity_grams": r["quantity_grams"],
           "germination_pct": r["germination_pct"], "remaining_grams": lot_remaining(r),
           "status": r["status"]}
    out.update(common(r))
    return out


def ser_crop_batch(r):
    out = {"seed_lot_id": r["seed_lot_id"],
           "planned_sow_date": r["planned_sow_date"].isoformat(),
           "lift_window_start": r["lift_window_start"].isoformat(),
           "lift_window_end": r["lift_window_end"].isoformat(),
           "actual_sow_date": r["actual_sow_date"].isoformat() if r.get("actual_sow_date") else None,
           "sown_grams": r.get("sown_grams"),
           "projected_plantable": r.get("projected_plantable"),
           "lifted_on": r["lifted_on"].isoformat() if r.get("lifted_on") else None,
           "lifted_count": r.get("lifted_count"),
           "plantable_count": r.get("plantable_count"),
           "cull_count": (r["lifted_count"] - r["plantable_count"]
                          if r.get("lifted_count") is not None and r.get("plantable_count") is not None
                          else None),
           "reserved_plantable": batch_reserved(r["id"]),
           "status": r["status"]}
    out.update(common(r))
    return out


def ser_order(r):
    out = {"landowner_id": r["landowner_id"], "destination_zone_id": r["destination_zone_id"],
           "species": r["species"], "quantity": r["quantity"],
           "requested_ship_date": r["requested_ship_date"].isoformat(),
           "unit_price_cents": r["unit_price_cents"], "total_price_cents": r["total_price_cents"],
           "allocated_quantity": order_allocated(r["id"]),
           "shipped_quantity": order_shipped(r["id"]),
           "status": r["status"]}
    out.update(common(r))
    return out


def ser_allocation(r):
    out = {"seedling_order_id": r["seedling_order_id"], "crop_batch_id": r["crop_batch_id"],
           "quantity": r["quantity"], "status": r["status"]}
    out.update(common(r))
    return out


def ser_storage_unit(r):
    out = {"unit_code": r["unit_code"], "capacity_units": r["capacity_units"],
           "temp_min_c": r["temp_min_c"], "temp_max_c": r["temp_max_c"],
           "current_load": unit_load(r["id"])}
    out.update(common(r))
    return out


def ser_storage_placement(r):
    out = {"crop_batch_id": r["crop_batch_id"], "storage_unit_id": r["storage_unit_id"],
           "quantity": r["quantity"], "placed_on": r["placed_on"].isoformat(),
           "withdrawn_quantity": r["withdrawn_quantity"], "status": r["status"]}
    out.update(common(r))
    return out


def ser_contract(r):
    out = {"landowner_id": r["landowner_id"], "seedling_order_id": r["seedling_order_id"],
           "site_zone_id": r["site_zone_id"], "acres": r["acres"],
           "trees_per_acre": r["trees_per_acre"], "contingency_pct": r["contingency_pct"],
           "required_seedlings": r["required_seedlings"],
           "planting_window_start": r["planting_window_start"].isoformat(),
           "planting_window_end": r["planting_window_end"].isoformat(),
           "herbicide_applied_on": r["herbicide_applied_on"].isoformat() if r.get("herbicide_applied_on") else None,
           "site_prep_status": r["site_prep_status"],
           "last_planted_on": r["last_planted_on"].isoformat() if r.get("last_planted_on") else None,
           "planted_quantity": r["planted_quantity"],
           "obligation_count": contract_obligation_count(r["id"]),
           "status": r["status"]}
    out.update(common(r))
    return out


def ser_crew(r):
    out = {"crew_code": r["crew_code"], "capacity_per_day": r["capacity_per_day"],
           "active": r["active"]}
    out.update(common(r))
    return out


def ser_assignment(r):
    out = {"crew_id": r["crew_id"], "planting_contract_id": r["planting_contract_id"],
           "start_date": r["start_date"].isoformat(), "end_date": r["end_date"].isoformat(),
           "planned_seedlings": r["planned_seedlings"], "status": r["status"]}
    out.update(common(r))
    return out


def ser_shipment(r):
    out = {"planting_contract_id": r["planting_contract_id"], "crop_batch_id": r["crop_batch_id"],
           "quantity": r["quantity"],
           "dispatched_at": fmt_dt(r["dispatched_at"]) if r.get("dispatched_at") else None,
           "handling_deadline": fmt_dt(r["handling_deadline"]) if r.get("handling_deadline") else None,
           "delivered_at": fmt_dt(r["delivered_at"]) if r.get("delivered_at") else None,
           "planted_confirmed_at": fmt_dt(r["planted_confirmed_at"]) if r.get("planted_confirmed_at") else None,
           "spoilage_reason": r.get("spoilage_reason"),
           "status": r["status"]}
    out.update(common(r))
    return out


def ser_survey(r):
    out = {"planting_contract_id": r["planting_contract_id"],
           "surveyed_on": r["surveyed_on"].isoformat(),
           "planted_count_snapshot": r["planted_count_snapshot"],
           "alive_count": r["alive_count"], "survival_pct": r["survival_pct"],
           "threshold_pct": r["threshold_pct"], "below_threshold": r["below_threshold"],
           "owed_quantity": r["owed_quantity"],
           "replant_date": r["replant_date"].isoformat() if r.get("replant_date") else None,
           "waiver_reason": r.get("waiver_reason"),
           "obligation_status": r["obligation_status"]}
    out.update(common(r))
    return out


def ser_enrollment(r):
    out = {"landowner_id": r["landowner_id"], "program_code": r["program_code"],
           "enrolled_acres": r["enrolled_acres"], "rate_per_acre_cents": r["rate_per_acre_cents"],
           "cap_cents": r["cap_cents"], "documented_acres": r.get("documented_acres"),
           "documented_cost_cents": r.get("documented_cost_cents"),
           "provisional_award_cents": r["provisional_award_cents"],
           "final_award_cents": r.get("final_award_cents"),
           "paid_cents": r["paid_cents"], "status": r["status"]}
    out.update(common(r))
    return out


def request_arg(name):
    return request.args.get(name)

