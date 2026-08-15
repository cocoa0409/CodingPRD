"""Core infrastructure: in-memory store, logical clock, envelope, errors, auth,
validators, decimal helpers, serialization, pagination, domain recomputes."""
import re
import secrets
import string
import uuid
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP, ROUND_CEILING, getcontext

from flask import request, jsonify, g

getcontext().prec = 40

ALL_ROLES = [
    "PlantManager", "SawOperator", "FurnaceOperator", "ForgeOperator",
    "DieShopTechnician", "QualityEngineer", "SalesPlanner",
]
ROLE_SET = set(ALL_ROLES)

DEFAULT_CLOCK_STR = "2026-08-01T00:00:00Z"
TURNAROUND = timedelta(minutes=30)
SCRAP_CREDIT_CAP = Decimal("0.05")
TON_LBS = Decimal("2000")

# --------------------------------------------------------------------------
# In-memory store (starts empty on every boot; no seeding)
# --------------------------------------------------------------------------
STORE_KEYS = (
    "alloy_specs", "mill_heats", "billets", "furnaces", "furnace_charges",
    "die_sets", "work_centers", "work_orders", "forge_runs", "forge_heats",
    "trim_tickets", "part_serials", "quality_certs", "surcharge_indices",
    "invoices",
)
DB = {k: {} for k in STORE_KEYS}
_SEQ = {"n": 0}


def _next_seq():
    _SEQ["n"] += 1
    return _SEQ["n"]


# --------------------------------------------------------------------------
# Errors
# --------------------------------------------------------------------------
class ApiError(Exception):
    def __init__(self, error_id, status, message):
        super().__init__(message)
        self.error_id = error_id
        self.status = status
        self.message = message


def err(error_id, status, message):
    return ApiError(error_id, status, message)


# --------------------------------------------------------------------------
# Time: wall clock for envelope/created_at, logical clock for business stamps
# --------------------------------------------------------------------------
def wall_iso():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def parse_dt(value, field="datetime"):
    if not isinstance(value, str) or not value.strip():
        raise err("ERR_INVALID_REQUEST", 400, f"{field} must be an ISO 8601 timestamp string")
    t = value.strip()
    if t.endswith(("Z", "z")):
        t = t[:-1] + "+00:00"
    try:
        d = datetime.fromisoformat(t)
    except ValueError:
        raise err("ERR_INVALID_REQUEST", 400, f"{field} is not a valid ISO 8601 timestamp")
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d.astimezone(timezone.utc)


def fmt_dt(d):
    d = d.astimezone(timezone.utc)
    if d.microsecond:
        return d.isoformat(timespec="milliseconds").replace("+00:00", "Z")
    return d.strftime("%Y-%m-%dT%H:%M:%SZ")


LOGICAL = {"now": parse_dt(DEFAULT_CLOCK_STR)}


def clock_now():
    return LOGICAL["now"]


# --------------------------------------------------------------------------
# Envelope
# --------------------------------------------------------------------------
def _req_id():
    return "req_" + "".join(secrets.choice(string.ascii_letters + string.digits) for _ in range(20))


def success(data, code=200, response_type="object", page_meta=None):
    meta = {"api_request_id": _req_id(), "api_request_timestamp": wall_iso()}
    if page_meta is not None:
        meta.update(page_meta)
    return jsonify({"meta": meta, "response_type": response_type, "data": data}), code


def error_body(e):
    return jsonify({
        "meta": {"api_request_id": _req_id(), "api_request_timestamp": wall_iso()},
        "response_type": "error",
        "data": {"error_id": e.error_id, "message": e.message},
    }), e.status


# --------------------------------------------------------------------------
# Auth
# --------------------------------------------------------------------------
def auth(allowed_roles):
    uid = (request.headers.get("X-User-ID") or "").strip()
    role = (request.headers.get("X-User-Role") or "").strip()
    if not uid or not role:
        raise err("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER", 400,
                  "X-User-ID and X-User-Role headers must be present and non-empty")
    if role not in ROLE_SET or role not in allowed_roles:
        raise err("ERR_FORBIDDEN_FOR_ROLE", 403,
                  f"role '{role}' is not permitted for this endpoint")
    return uid


# --------------------------------------------------------------------------
# Body + field validators
# --------------------------------------------------------------------------
def body():
    if not request.data:
        return {}
    d = request.get_json(silent=True)
    if not isinstance(d, dict):
        raise err("ERR_INVALID_REQUEST", 400, "request body must be a JSON object")
    return d


def f_req(d, name):
    if name not in d or d[name] is None:
        raise err("ERR_INVALID_REQUEST", 400, f"missing required field: {name}")
    return d[name]


def f_str(d, name, required=True):
    v = f_req(d, name) if required else d.get(name)
    if v is None:
        return None
    if not isinstance(v, str) or not v.strip():
        raise err("ERR_INVALID_REQUEST", 400, f"field {name} must be a non-empty string")
    return v


def f_num(d, name, required=True, min_inclusive=None, min_exclusive=None):
    v = f_req(d, name) if required else d.get(name)
    if v is None:
        return None
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise err("ERR_INVALID_REQUEST", 400, f"field {name} must be a number")
    dec = Decimal(str(v))
    if min_inclusive is not None and dec < Decimal(str(min_inclusive)):
        raise err("ERR_INVALID_REQUEST", 400, f"field {name} must be >= {min_inclusive}")
    if min_exclusive is not None and dec <= Decimal(str(min_exclusive)):
        raise err("ERR_INVALID_REQUEST", 400, f"field {name} must be > {min_exclusive}")
    return dec


def f_int(d, name, required=True, min_inclusive=None, max_inclusive=None):
    v = f_req(d, name) if required else d.get(name)
    if v is None:
        return None
    if isinstance(v, bool) or not isinstance(v, int):
        raise err("ERR_INVALID_REQUEST", 400, f"field {name} must be an integer")
    if min_inclusive is not None and v < min_inclusive:
        raise err("ERR_INVALID_REQUEST", 400, f"field {name} must be >= {min_inclusive}")
    if max_inclusive is not None and v > max_inclusive:
        raise err("ERR_INVALID_REQUEST", 400, f"field {name} must be <= {max_inclusive}")
    return v


def f_bool(d, name, required=True):
    v = f_req(d, name) if required else d.get(name)
    if v is None:
        return None
    if not isinstance(v, bool):
        raise err("ERR_INVALID_REQUEST", 400, f"field {name} must be a boolean")
    return v


def f_list(d, name, required=True, non_empty=False):
    v = f_req(d, name) if required else d.get(name)
    if v is None:
        return None
    if not isinstance(v, list) or (non_empty and len(v) == 0):
        raise err("ERR_INVALID_REQUEST", 400, f"field {name} must be a {'non-empty ' if non_empty else ''}array")
    return v


def f_enum(d, name, values, required=True):
    v = f_str(d, name, required=required)
    if v is None:
        return None
    if v not in values:
        raise err("ERR_INVALID_REQUEST", 400, f"field {name} must be one of {sorted(values)}")
    return v


def f_id_list(d, name):
    v = f_list(d, name, non_empty=True)
    for item in v:
        if not isinstance(item, str) or not item:
            raise err("ERR_INVALID_REQUEST", 400, f"field {name} must contain string ids")
    if len(set(v)) != len(v):
        raise err("ERR_INVALID_REQUEST", 400, f"field {name} contains duplicate ids")
    return v


# --------------------------------------------------------------------------
# Decimal helpers
# --------------------------------------------------------------------------
def D(v):
    if isinstance(v, Decimal):
        return v
    if isinstance(v, bool):
        raise err("ERR_INVALID_REQUEST", 400, "boolean is not a number")
    return Decimal(str(v))


def q2(x):
    return D(x).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def q3(x):
    return D(x).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)


def q0(x):
    return int(D(x).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def ceil_int(x):
    return int(D(x).to_integral_value(rounding=ROUND_CEILING))


# --------------------------------------------------------------------------
# Records
# --------------------------------------------------------------------------
def new_record(store, common=True):
    rec = {"id": str(uuid.uuid4()), "_seq": _next_seq()}
    ts = wall_iso()
    rec["created_at"] = ts
    if common:
        rec["updated_at"] = ts
        rec["version"] = 1
    DB[store][rec["id"]] = rec
    return rec


def touch(store, rec):
    """Bump version/updated_at at most once per record per request."""
    if "version" not in rec:
        return
    if "_touched" not in g:
        g._touched = set()
    key = (store, rec["id"])
    if key in g._touched:
        return
    g._touched.add(key)
    rec["version"] += 1
    rec["updated_at"] = wall_iso()


def get_or_404(store, rid, label=None):
    rec = DB[store].get(rid)
    if rec is None:
        raise err("ERR_NOT_FOUND", 404, f"{label or store} resource '{rid}' not found")
    return rec


def _js(v):
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, datetime):
        return fmt_dt(v)
    if isinstance(v, dict):
        return {k: _js(x) for k, x in v.items() if not k.startswith("_")}
    if isinstance(v, list):
        return [_js(x) for x in v]
    return v


def view(rec):
    return _js(rec)


# --------------------------------------------------------------------------
# Pagination + list helpers
# --------------------------------------------------------------------------
def paginate(items):
    limit = 10
    offset = 0
    raw_l = request.args.get("limit")
    if raw_l is not None:
        try:
            limit = int(raw_l)
        except (TypeError, ValueError):
            raise err("ERR_INVALID_REQUEST", 400, "limit must be an integer")
        if limit < 1:
            raise err("ERR_INVALID_REQUEST", 400, "limit must be >= 1")
        if limit > 100:
            limit = 100
    raw_o = request.args.get("offset")
    if raw_o is not None:
        try:
            offset = int(raw_o)
        except (TypeError, ValueError):
            raise err("ERR_INVALID_REQUEST", 400, "offset must be an integer")
        if offset < 0:
            raise err("ERR_INVALID_REQUEST", 400, "offset must be >= 0")
    total = len(items)
    page = items[offset:offset + limit]
    return page, {"limit": limit, "offset": offset, "total_count": total,
                  "has_more": offset + limit < total}


def apply_filters(recs, allowed):
    """Filter records by query-string equality on the allowed field names."""
    out = list(recs)
    for key in allowed:
        raw = request.args.get(key)
        if raw is None:
            continue
        out = [r for r in out if _filter_value(r, key) == raw]
    return out


def _filter_value(rec, key):
    v = rec.get(key)
    if isinstance(v, Decimal):
        return str(float(v))
    if v is None:
        return None
    return str(v)


def list_response(recs, data_key=None):
    recs = sorted(recs, key=lambda r: r["_seq"])
    page, meta = paginate(recs)
    return success([view(r) for r in page], 200, "array", meta)


# --------------------------------------------------------------------------
# Domain recomputes / cascades
# --------------------------------------------------------------------------
def order_runs(wo_id):
    return [r for r in DB["forge_runs"].values() if r["work_order_id"] == wo_id]


def order_parts(wo_id):
    return [p for p in DB["part_serials"].values() if p["work_order_id"] == wo_id]


def order_certs(wo_id):
    return [c for c in DB["quality_certs"].values() if c["work_order_id"] == wo_id]


def order_tickets(wo_id):
    run_ids = {r["id"] for r in order_runs(wo_id)}
    return [t for t in DB["trim_tickets"].values() if t["forge_run_id"] in run_ids]


def recompute_order(wo):
    parts = order_parts(wo["id"])
    forged = sum(1 for p in parts if p["status"] in ("FORGED", "TRIMMED", "INSPECTED", "SHIPPED"))
    trimmed = sum(1 for p in parts if p["status"] in ("TRIMMED", "INSPECTED", "SHIPPED"))
    shipped = sum(1 for p in parts if p["status"] == "SHIPPED")
    scrapped = sum(1 for p in parts if p["status"] == "SCRAPPED")
    run_ids = {r["id"] for r in order_runs(wo["id"])}
    consumed = q2(sum((b["cut_weight_lbs"] for b in DB["billets"].values()
                       if b.get("consumed_by_run_id") in run_ids), Decimal("0")))
    trimmed_net = q2(sum((t["net_trimmed_lbs"] for t in order_tickets(wo["id"])
                          if t["status"] == "ACCEPTED"), Decimal("0")))
    changed = (
        wo["forged_qty"] != forged or wo["trimmed_qty"] != trimmed
        or wo["shipped_qty"] != shipped or wo["scrapped_qty"] != scrapped
        or wo["consumed_billet_weight_lbs"] != consumed or wo["trimmed_net_lbs"] != trimmed_net
    )
    wo["forged_qty"] = forged
    wo["trimmed_qty"] = trimmed
    wo["shipped_qty"] = shipped
    wo["scrapped_qty"] = scrapped
    wo["consumed_billet_weight_lbs"] = consumed
    wo["trimmed_net_lbs"] = trimmed_net
    if changed:
        touch("work_orders", wo)


def update_heat_remaining(heat):
    total = sum((b["cut_weight_lbs"] for b in DB["billets"].values()
                 if b["mill_heat_id"] == heat["id"]), Decimal("0"))
    rem = q2(D(heat["received_weight_lbs"]) - total)
    if rem != heat["remaining_weight_lbs"]:
        heat["remaining_weight_lbs"] = rem
        touch("mill_heats", heat)


def reeval_heat_depleted(heat):
    if heat["status"] != "CERT_VERIFIED":
        return
    if heat["remaining_weight_lbs"] != Decimal("0"):
        return
    for b in DB["billets"].values():
        if b["mill_heat_id"] == heat["id"] and b["status"] in ("CUT", "CHARGED", "DISCHARGED"):
            return
    heat["status"] = "DEPLETED"
    touch("mill_heats", heat)


def heat_cert_coverage_complete(wo):
    used = {p["mill_heat_id"] for p in order_parts(wo["id"]) if p["status"] != "SCRAPPED"}
    certed = {c["mill_heat_id"] for c in order_certs(wo["id"]) if c["status"] == "CERTIFIED"}
    return bool(used) and used.issubset(certed)


def reeval_coverage(wo):
    complete = heat_cert_coverage_complete(wo)
    if complete and wo["status"] == "PRODUCED":
        wo["status"] = "CERTIFIED"
        touch("work_orders", wo)
    elif not complete and wo["status"] == "CERTIFIED":
        wo["status"] = "PRODUCED"
        touch("work_orders", wo)


def maybe_produced(wo):
    """After a trim acceptance: IN_PROGRESS -> PRODUCED + cert auto-creation."""
    if wo["status"] != "IN_PROGRESS":
        return
    if wo["trimmed_qty"] < wo["ordered_qty"]:
        return
    wo["status"] = "PRODUCED"
    touch("work_orders", wo)
    seen = []
    for p in sorted(order_parts(wo["id"]), key=lambda x: x["_seq"]):
        if p["status"] == "SCRAPPED":
            continue
        if p["mill_heat_id"] not in seen:
            seen.append(p["mill_heat_id"])
    existing = {c["mill_heat_id"] for c in order_certs(wo["id"])}
    for mh in seen:
        if mh in existing:
            continue
        cert = new_record("quality_certs")
        cert.update({
            "work_order_id": wo["id"],
            "mill_heat_id": mh,
            "sample_part_serial_id": None,
            "grain_flow_rating": None,
            "macro_etch_result": None,
            "submitter_id": None,
            "certifier_id": None,
            "status": "PENDING",
        })


def furnace_active_charge_id(furnace_id):
    act = [c for c in DB["furnace_charges"].values()
           if c["furnace_id"] == furnace_id and c["status"] in ("LOADING", "SOAKING", "READY")]
    if not act:
        return None
    act.sort(key=lambda c: c["_seq"])
    return act[-1]["id"]


def furnace_view(f):
    v = view(f)
    v["active_charge_id"] = furnace_active_charge_id(f["id"])
    return v


def turnaround_ok(center_id, start, end):
    """30-minute turnaround gap between runs on one work center.

    OK iff new.start >= existing.end + 30min OR new.end <= existing.start - 30min.
    A gap of exactly 30 minutes is allowed; CANCELLED runs are excluded.
    """
    for r in DB["forge_runs"].values():
        if r["work_center_id"] != center_id or r["status"] == "CANCELLED":
            continue
        if start >= r["planned_end"] + TURNAROUND:
            continue
        if end <= r["planned_start"] - TURNAROUND:
            continue
        return False
    return True


def accepted_flash_total(wo_id):
    return sum((t["flash_scrap_lbs"] for t in order_tickets(wo_id)
                if t["status"] == "ACCEPTED" and t["flash_scrap_lbs"] is not None), Decimal("0"))


def trim_allocation(ticket):
    """per_part_net_allocation: run's FORGED parts -> TRIMMED with net weight."""
    run = get_or_404("forge_runs", ticket["forge_run_id"])
    wo = get_or_404("work_orders", run["work_order_id"])
    parts = [p for p in DB["part_serials"].values()
             if p["forge_run_id"] == run["id"] and p["status"] == "FORGED"]
    parts.sort(key=lambda p: p["serial_seq"])
    n = len(parts)
    if n:
        net = D(ticket["net_trimmed_lbs"])
        per_part = q2(net / n)
        residual = q2(net - per_part * n)
        for p in parts:
            p["net_weight_lbs"] = per_part
            p["status"] = "TRIMMED"
            touch("part_serials", p)
        parts[-1]["net_weight_lbs"] = per_part + residual
    recompute_order(wo)
    maybe_produced(wo)
