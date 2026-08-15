"""Core state, envelope, auth, and validation helpers.

In-memory only. No seeding: every store starts empty on boot.
"""
import os
import re
import uuid
import random
import string
from datetime import datetime, timezone

from decimal import Decimal, ROUND_HALF_UP, ROUND_FLOOR
from flask import Flask, request, g, jsonify

app = Flask(__name__)

# ---------------------------------------------------------------------------
# In-memory stores (start empty on every boot; nothing is ever seeded)
# ---------------------------------------------------------------------------
customers = {}
profiles = {}
dies = {}
lines = {}
lots = {}
formulations = {}
batches = {}
work_orders = {}
assignments = {}
runs = {}
samples = {}
bundles = {}
purge_events = {}
index_points = {}          # id -> point
index_by_month = {}        # "YYYY-MM" -> id

# Global monotonic insertion counter (internal tie-break, never serialized)
_seq = [0]

# Logical clock (PRD 2.5): startup default exactly 2026-08-01T00:00:00Z
CLOCK = {"now": datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)}

ROLES = {"PlantManager", "ProcessEngineer", "LineOperator",
         "QualityInspector", "SalesEngineer"}
ALL_ROLES = ["PlantManager", "ProcessEngineer", "LineOperator",
             "QualityInspector", "SalesEngineer"]

COLOR_RANK = {"NATURAL": 0, "WHITE": 1, "YELLOW": 2, "RED": 3,
              "BLUE": 4, "GREEN": 5, "BROWN": 6, "BLACK": 7}
COLOR_FAMILIES = set(COLOR_RANK.keys())


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------
class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


def err_bad(msg="Malformed request"):
    return ApiError("ERR_BAD_REQUEST", 400, msg)


def err_not_found(msg="Referenced resource does not exist"):
    return ApiError("ERR_NOT_FOUND", 404, msg)


# ---------------------------------------------------------------------------
# Numbers / time helpers
# ---------------------------------------------------------------------------
def D(x):
    if isinstance(x, Decimal):
        return x
    return Decimal(str(x))


def rhu(x, places):
    q = Decimal(1).scaleb(-places)
    return D(x).quantize(q, rounding=ROUND_HALF_UP)


def rhu_int(x):
    return int(rhu(x, 0))


def now_dt():
    return datetime.now(timezone.utc)


def ts3(dt):
    """ISO 8601 UTC with exactly three fractional digits and Z suffix."""
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def ts_iso(dt):
    """ISO 8601 UTC; fractional seconds only when nonzero (for echoed inputs)."""
    if dt.microsecond:
        return ts3(dt)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_dt(value):
    """Parse an ISO8601 string into an aware UTC datetime, or None."""
    if not isinstance(value, str):
        return None
    s = value.strip()
    if not s:
        return None
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def next_seq():
    _seq[0] += 1
    return _seq[0]


def new_id():
    return str(uuid.uuid4())


def clock_month():
    t = CLOCK["now"]
    return "%04d-%02d" % (t.year, t.month)


def months_inclusive(a, b):
    """List of YYYY-MM strings from a to b inclusive; [] if b < a."""
    y1, m1 = int(a[:4]), int(a[5:7])
    y2, m2 = int(b[:4]), int(b[5:7])
    out = []
    y, m = y1, m1
    while (y, m) <= (y2, m2):
        out.append("%04d-%02d" % (y, m))
        m += 1
        if m == 13:
            y, m = y + 1, 1
    return out


# ---------------------------------------------------------------------------
# Mutation bookkeeping: one version bump per entity per request (PRD 2.4/2.9)
# ---------------------------------------------------------------------------
def mark(entity):
    """Mark an entity as mutated this request; flushed once at the end."""
    if not hasattr(g, "touched"):
        g.touched = {}
    g.touched[id(entity)] = entity


def flush_touches():
    """Bump version/updated_at once per touched entity (PRD 2.4/2.9).

    Returns a map of entity id -> entity so the wrapper can refresh any
    already-serialized response body with the post-mutation values: the
    response of a mutating request must show the resource as it stands
    after the mutation, version increment included (PRD 2.4, 2.7).
    """
    touched = getattr(g, "touched", None) or {}
    ts_now = now_dt()
    for ent in touched.values():
        ent["version"] = ent.get("version", 1) + 1
        ent["updated_at"] = ts_now
    return {ent["id"]: ent for ent in touched.values() if "id" in ent}


def _refresh_serialized(node, by_id):
    """Copy post-flush version/updated_at onto serialized copies of
    touched entities anywhere inside a response payload."""
    if isinstance(node, dict):
        ent = by_id.get(node.get("id"))
        if ent is not None:
            if "version" in node:
                node["version"] = ent["version"]
            if "updated_at" in node:
                node["updated_at"] = ts3(ent["updated_at"])
        for v in node.values():
            _refresh_serialized(v, by_id)
    elif isinstance(node, list):
        for item in node:
            _refresh_serialized(item, by_id)


def touch_now(entity):
    mark(entity)


def stamp_new(entity):
    t = now_dt()
    entity["id"] = new_id()
    entity["created_at"] = t
    entity["updated_at"] = t
    entity["version"] = 1
    entity["_seq"] = next_seq()
    return entity


def stamp_new_lean(entity):
    t = now_dt()
    entity["id"] = new_id()
    entity["created_at"] = t
    entity["_seq"] = next_seq()
    return entity


# ---------------------------------------------------------------------------
# Response envelope (PRD 2.2)
# ---------------------------------------------------------------------------
def _meta():
    return {
        "api_request_id": "req_" + "".join(
            random.choice(string.ascii_letters + string.digits) for _ in range(20)),
        "api_request_timestamp": ts3(now_dt()),
    }


def envelope_object(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def envelope_list(items, limit, offset, total_count):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), 200


def envelope_error(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


@app.errorhandler(404)
def _nf(e):
    return envelope_error(ApiError("ERR_NOT_FOUND", 404, "Resource not found"))


@app.errorhandler(405)
def _mna(e):
    return envelope_error(ApiError("ERR_NOT_FOUND", 404, "Resource not found"))


@app.errorhandler(500)
def _ise(e):
    return envelope_error(ApiError("ERR_BAD_REQUEST", 500, "Internal error"))


# ---------------------------------------------------------------------------
# Auth (PRD 2.1) and route wrapper
# ---------------------------------------------------------------------------
def authenticate():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", 401,
                       "Missing or invalid X-User-ID / X-User-Role headers")
    return uid, role


def endpoint(path, methods, roles):
    """Route wrapper: auth -> role -> handler -> flush touches -> envelope."""
    def deco(fn):
        def wrapper(**kwargs):
            g.touched = {}
            try:
                uid, role = authenticate()
                if roles is not None and role not in roles:
                    raise ApiError("ERR_UNAUTHORIZED_ROLE", 403,
                                   "Role %s may not perform this operation" % role)
                result, status = fn(user_id=uid, **kwargs)
                by_id = flush_touches()
                if by_id:
                    if isinstance(result, _ListResult):
                        _refresh_serialized(result.items, by_id)
                    else:
                        _refresh_serialized(result, by_id)
                if isinstance(result, _ListResult):
                    return envelope_list(result.items, result.limit,
                                         result.offset, result.total)
                return envelope_object(result, status)
            except ApiError as e:
                return envelope_error(e)
        wrapper.__name__ = fn.__name__
        app.add_url_rule(path, fn.__name__, wrapper, methods=methods)
        return fn
    return deco


class _ListResult:
    def __init__(self, items, limit, offset, total):
        self.items = items
        self.limit = limit
        self.offset = offset
        self.total = total


def list_result(items, limit, offset, total):
    return _ListResult(items, limit, offset, total), 200


# ---------------------------------------------------------------------------
# Body / field validation (structural tier: PRD 2.8, runs last)
# ---------------------------------------------------------------------------
def get_body():
    data = request.get_json(silent=True, force=False)
    if data is None:
        data = request.get_json(silent=True, force=True)
    if not isinstance(data, dict):
        raise err_bad("Request body must be a JSON object")
    return data


def is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def is_intlike(v):
    if isinstance(v, bool):
        return False
    if isinstance(v, int):
        return True
    if isinstance(v, float):
        return v.is_integer()
    return False


class Fields:
    """Collects structural problems; domain checks run first per PRD 2.8."""

    def __init__(self, body):
        self.body = body if isinstance(body, dict) else {}
        self.problems = []
        self.values = {}

    def _bad(self, name):
        self.problems.append(name)
        self.values[name] = None
        return None

    def ok(self, *names):
        return all(n not in self.problems for n in names)

    def str_(self, name, required=True):
        b = self.body
        if name not in b or b[name] is None:
            if required:
                return self._bad(name)
            self.values[name] = None
            return None
        v = b[name]
        if not isinstance(v, str):
            return self._bad(name)
        self.values[name] = v
        return v

    def num(self, name, required=True, positive=False, nonnegative=False):
        b = self.body
        if name not in b or b[name] is None:
            if required:
                return self._bad(name)
            self.values[name] = None
            return None
        v = b[name]
        if not is_num(v):
            return self._bad(name)
        dv = D(v)
        if positive and dv <= 0:
            return self._bad(name)
        if nonnegative and dv < 0:
            return self._bad(name)
        self.values[name] = dv
        return dv

    def int_(self, name, required=True, min_v=None):
        b = self.body
        if name not in b or b[name] is None:
            if required:
                return self._bad(name)
            self.values[name] = None
            return None
        v = b[name]
        if not is_intlike(v):
            return self._bad(name)
        iv = int(v)
        if min_v is not None and iv < min_v:
            return self._bad(name)
        self.values[name] = iv
        return iv

    def enum(self, name, options, required=True):
        b = self.body
        if name not in b or b[name] is None:
            if required:
                return self._bad(name)
            self.values[name] = None
            return None
        v = b[name]
        if not isinstance(v, str) or v not in options:
            return self._bad(name)
        self.values[name] = v
        return v

    def arr(self, name, required=True, min_len=None):
        b = self.body
        if name not in b or b[name] is None:
            if required:
                return self._bad(name)
            self.values[name] = None
            return None
        v = b[name]
        if not isinstance(v, list):
            return self._bad(name)
        if min_len is not None and len(v) < min_len:
            return self._bad(name)
        self.values[name] = v
        return v

    def num_array(self, name, required=True):
        v = self.arr(name, required=required)
        if v is None:
            return None
        if any(not is_num(x) for x in v):
            return self._bad(name)
        self.values[name] = [D(x) for x in v]
        return self.values[name]

    def fail_if_problems(self):
        if self.problems:
            raise err_bad("Invalid or missing fields: %s"
                          % ", ".join(sorted(set(self.problems))))


# ---------------------------------------------------------------------------
# Existence helpers (priority 3)
# ---------------------------------------------------------------------------
def lookup(store, key):
    return store.get(key)


def require_exists(store, key, what="Resource"):
    if not isinstance(key, str) or key not in store:
        raise err_not_found("%s not found" % what)
    return store[key]


# ---------------------------------------------------------------------------
# Pagination (PRD 2.3)
# ---------------------------------------------------------------------------
def pagination():
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise err_bad("limit must be an integer")
        if limit < 1 or limit > 100:
            raise err_bad("limit must be between 1 and 100")
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise err_bad("offset must be an integer")
        if offset < 0:
            raise err_bad("offset must be >= 0")
    return limit, offset


def paginate(items, limit, offset):
    total = len(items)
    return items[offset:offset + limit], total


def sort_created(items):
    return sorted(items, key=lambda e: (e["created_at"], e.get("_seq", 0)))


# ---------------------------------------------------------------------------
# Serializers (exact field sets per scaffold; lean trio have no
# updated_at/version)
# ---------------------------------------------------------------------------
def ser_customer(c):
    return {
        "id": c["id"], "name": c["name"],
        "resin_index_basis": c["resin_index_basis"],
        "credit_limit_cents": c["credit_limit_cents"],
        "status": c["status"],
        "open_exposure_cents": c["open_exposure_cents"],
        "created_at": ts3(c["created_at"]),
        "updated_at": ts3(c["updated_at"]),
        "version": c["version"],
    }


def ser_profile(p):
    return {
        "id": p["id"], "customer_id": p["customer_id"],
        "profile_code": p["profile_code"],
        "critical_dimensions": p["critical_dimensions"],
        "spc_subgroup_size": p["spc_subgroup_size"],
        "sample_every_m": p["sample_every_m"],
        "resin_content_kg_per_m": float(D(p["resin_content_kg_per_m"])),
        "min_line_speed_mpm": float(D(p["min_line_speed_mpm"])),
        "max_line_speed_mpm": float(D(p["max_line_speed_mpm"])),
        "created_at": ts3(p["created_at"]),
        "updated_at": ts3(p["updated_at"]),
        "version": p["version"],
    }


def _fnum(v):
    return None if v is None else float(D(v))


def _inum(v):
    return None if v is None else int(v)


def ser_die(d):
    return {
        "id": d["id"], "profile_id": d["profile_id"],
        "die_code": d["die_code"],
        "tooling_cost_cents": d["tooling_cost_cents"],
        "committed_length_m": float(D(d["committed_length_m"])),
        "committed_weight_kg": float(D(d["committed_weight_kg"])),
        "amortization_mode": d["amortization_mode"],
        "buffer_hours": d["buffer_hours"],
        "min_screw_mm": float(D(d["min_screw_mm"])),
        "max_screw_mm": float(D(d["max_screw_mm"])),
        "amort_rate_cents_per_m": _fnum(d.get("amort_rate_cents_per_m")),
        "amort_rate_cents_per_kg": _fnum(d.get("amort_rate_cents_per_kg")),
        "amortized_cents": d["amortized_cents"],
        "remaining_balance_cents": d["remaining_balance_cents"],
        "status": d["status"],
        "created_at": ts3(d["created_at"]),
        "updated_at": ts3(d["updated_at"]),
        "version": d["version"],
    }


def ser_line(l):
    return {
        "id": l["id"], "line_code": l["line_code"],
        "screw_diameter_mm": float(D(l["screw_diameter_mm"])),
        "status": l["status"],
        "created_at": ts3(l["created_at"]),
        "updated_at": ts3(l["updated_at"]),
        "version": l["version"],
    }


def ser_lot(l):
    return {
        "id": l["id"], "lot_kind": l["lot_kind"],
        "resin_type": l["resin_type"],
        "color_family": l["color_family"],
        "received_kg": float(D(l["received_kg"])),
        "supplier_lot_ref": l.get("supplier_lot_ref"),
        "consumed_kg": float(D(l["consumed_kg"])),
        "available_kg": float(D(l["available_kg"])),
        "status": l["status"],
        "created_at": ts3(l["created_at"]),
        "updated_at": ts3(l["updated_at"]),
        "version": l["version"],
    }


def ser_formulation(f):
    return {
        "id": f["id"], "profile_id": f["profile_id"],
        "formula_code": f["formula_code"],
        "base_resin_type": f["base_resin_type"],
        "color_family": f["color_family"],
        "let_down_ratio": float(D(f["let_down_ratio"])),
        "max_regrind_pct": float(D(f["max_regrind_pct"])),
        "created_at": ts3(f["created_at"]),
        "updated_at": ts3(f["updated_at"]),
        "version": f["version"],
    }


def ser_batch(b):
    return {
        "id": b["id"], "formulation_id": b["formulation_id"],
        "virgin_lot_id": b["virgin_lot_id"],
        "regrind_lot_id": b.get("regrind_lot_id"),
        "colorant_lot_id": b["colorant_lot_id"],
        "target_batch_kg": float(D(b["target_batch_kg"])),
        "colorant_kg": float(D(b["colorant_kg"])),
        "regrind_kg": float(D(b["regrind_kg"])),
        "virgin_kg": float(D(b["virgin_kg"])),
        "actual_regrind_pct": float(D(b["actual_regrind_pct"])),
        "pre_quarantine_status": b.get("pre_quarantine_status"),
        "last_qc_user_id": b.get("last_qc_user_id"),
        "status": b["status"],
        "created_at": ts3(b["created_at"]),
        "updated_at": ts3(b["updated_at"]),
        "version": b["version"],
    }


def ser_work_order(w):
    return {
        "id": w["id"], "customer_id": w["customer_id"],
        "profile_id": w["profile_id"],
        "formulation_id": w["formulation_id"],
        "die_id": w["die_id"],
        "ordered_length_m": float(D(w["ordered_length_m"])),
        "cut_length_mm": w["cut_length_mm"],
        "pieces_per_bundle": w["pieces_per_bundle"],
        "base_unit_price_cents_per_m": float(D(w["base_unit_price_cents_per_m"])),
        "quote_month": w["quote_month"],
        "quote_index_cents_per_kg": float(D(w["quote_index_cents_per_kg"])),
        "pass_through_adj_cents_per_m": float(D(w["pass_through_adj_cents_per_m"])),
        "current_unit_price_cents_per_m": float(D(w["current_unit_price_cents_per_m"])),
        "produced_good_length_m": float(D(w["produced_good_length_m"])),
        "status": w["status"],
        "billing_status": w["billing_status"],
        "billed_length_m": _fnum(w.get("billed_length_m")),
        "invoice_total_cents": _inum(w.get("invoice_total_cents")),
        "created_at": ts3(w["created_at"]),
        "updated_at": ts3(w["updated_at"]),
        "version": w["version"],
    }


def ser_assignment(a):
    return {
        "id": a["id"], "work_order_id": a["work_order_id"],
        "die_id": a["die_id"], "line_id": a["line_id"],
        "planned_start": ts_iso(a["planned_start"]),
        "planned_end": ts_iso(a["planned_end"]),
        "status": a["status"],
        "created_at": ts3(a["created_at"]),
        "updated_at": ts3(a["updated_at"]),
        "version": a["version"],
    }


def ser_run(r):
    return {
        "id": r["id"], "assignment_id": r["assignment_id"],
        "batch_id": r["batch_id"],
        "line_speed_mpm": float(D(r["line_speed_mpm"])),
        "status": r["status"],
        "hold_origin": r.get("hold_origin"),
        "held_by_user_id": r.get("held_by_user_id"),
        "samples_posted": r["samples_posted"],
        "good_length_mm": _inum(r.get("good_length_mm")),
        "good_weight_kg": _fnum(r.get("good_weight_kg")),
        "trim_scrap_kg": _fnum(r.get("trim_scrap_kg")),
        "regrind_lot_id": r.get("regrind_lot_id"),
        "remnant_mm": _inum(r.get("remnant_mm")),
        "created_at": ts3(r["created_at"]),
        "updated_at": ts3(r["updated_at"]),
        "version": r["version"],
    }


def ser_sample(s):
    return {
        "id": s["id"], "run_id": s["run_id"],
        "dimension_name": s["dimension_name"],
        "measurements": s["measurements"],
        "xbar_mm": float(D(s["xbar_mm"])),
        "range_mm": float(D(s["range_mm"])),
        "ooc": s["ooc"],
        "spec_violations": s["spec_violations"],
        "created_at": ts3(s["created_at"]),
    }


def ser_bundle(b):
    return {
        "id": b["id"], "run_id": b["run_id"],
        "bundle_seq": b["bundle_seq"],
        "pieces": b["pieces"],
        "partial": b["partial"],
        "total_length_mm": b["total_length_mm"],
        "created_at": ts3(b["created_at"]),
    }


def ser_purge(p):
    return {
        "id": p["id"], "line_id": p["line_id"],
        "from_resin_type": p["from_resin_type"],
        "to_resin_type": p["to_resin_type"],
        "from_color_family": p["from_color_family"],
        "to_color_family": p["to_color_family"],
        "purge_grade": p["purge_grade"],
        "transition_class": p["transition_class"],
        "scrap_kg": float(D(p["scrap_kg"])),
        "created_at": ts3(p["created_at"]),
    }


def ser_index_point(p):
    return {
        "id": p["id"], "month": p["month"],
        "index_cents_per_kg": float(D(p["index_cents_per_kg"])),
        "created_at": ts3(p["created_at"]),
        "updated_at": ts3(p["updated_at"]),
        "version": p["version"],
    }
