#!/usr/bin/env python3
"""Multifamily Pest Control Program API — Flask implementation."""
import os
import uuid
import random
import string
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import Flask, request, jsonify

app = Flask(__name__)

# ============================================================================
# Logical clock
# ============================================================================
_clock = {"now": datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)}


def now():
    return _clock["now"]


def today():
    return now().date()


def fmt_ts(dt):
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def parse_dt(v, field):
    if not isinstance(v, str):
        err("ERR_INVALID_REQUEST", 400, "Field %s must be an ISO 8601 datetime string" % field)
    s = v.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        err("ERR_INVALID_REQUEST", 400, "Field %s is not a valid ISO 8601 datetime" % field)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_date(v, field):
    if not isinstance(v, str):
        err("ERR_INVALID_REQUEST", 400, "Field %s must be an ISO date string" % field)
    try:
        return datetime.strptime(v.strip(), "%Y-%m-%d").date()
    except ValueError:
        err("ERR_INVALID_REQUEST", 400, "Field %s is not a valid ISO date" % field)


# ============================================================================
# Errors & envelope
# ============================================================================
class ApiError(Exception):
    def __init__(self, error_id, status, message):
        super().__init__(message)
        self.error_id = error_id
        self.status = status
        self.message = message


def err(error_id, status, message):
    raise ApiError(error_id, status, message)


def meta():
    rid = "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))
    return {"api_request_id": rid, "api_request_timestamp": fmt_ts(now())}


@app.errorhandler(ApiError)
def handle_api_error(e):
    return jsonify({"meta": meta(), "response_type": "error",
                    "data": {"error_id": e.error_id, "message": e.message}}), e.status


@app.errorhandler(404)
def handle_404(e):
    return jsonify({"meta": meta(), "response_type": "error",
                    "data": {"error_id": "ERR_NOT_FOUND", "message": "Resource not found"}}), 404


@app.errorhandler(405)
def handle_405(e):
    return jsonify({"meta": meta(), "response_type": "error",
                    "data": {"error_id": "ERR_NOT_FOUND", "message": "Resource not found"}}), 404


@app.errorhandler(Exception)
def handle_generic(e):
    if isinstance(e, ApiError):
        return handle_api_error(e)
    return jsonify({"meta": meta(), "response_type": "error",
                    "data": {"error_id": "ERR_INVALID_REQUEST", "message": str(e)}}), 400


def ok(data, code=200):
    return jsonify({"meta": meta(), "response_type": "object", "data": data}), code


def ok_list(items, total, limit, offset):
    m = meta()
    m["limit"] = limit
    m["offset"] = offset
    m["total_count"] = total
    m["has_more"] = (offset + len(items)) < total
    return jsonify({"meta": m, "response_type": "array", "data": items}), 200


# ============================================================================
# Data store
# ============================================================================
db = {
    "properties": {},
    "contracts": {},
    "units": {},
    "leases": {},
    "residents": {},
    "technicians": {},
    "inspections": {},
    "treatments": {},
    "cases": {},
    "disposals": {},
    "chargebacks": {},
    "packets": {},
}

_seq = {"n": 0}


def new_rec():
    _seq["n"] += 1
    return {"id": str(uuid.uuid4()), "created_at": now(), "updated_at": now(),
            "version": 1, "seq": _seq["n"]}


def touch(rec):
    rec["updated_at"] = now()
    rec["version"] += 1


def get_or_404(coll, rid, label="Resource"):
    r = db[coll].get(rid)
    if r is None:
        err("ERR_NOT_FOUND", 404, "%s %s does not exist" % (label, rid))
    return r


# ============================================================================
# Constants
# ============================================================================
ROLES = {"ProgramAdmin", "PropertyManager", "Technician", "Resident",
         "BillingClerk", "ComplianceOfficer"}
PESTS = {"ANTS", "ROACHES", "RODENTS", "BED_BUGS", "TERMITES"}
TREATMENT_TYPES = {"CHEMICAL", "HEAT", "EXCLUSION", "TRAPPING"}
INSPECTION_KINDS = {"ROUTINE", "INITIAL", "FOLLOW_UP"}
CHARGEBACK_KINDS = {"NON_COMPLIANCE_FEE", "REPEAT_INFESTATION", "HEAT_SURCHARGE",
                    "FURNITURE_DISPOSAL", "LATE_FEE"}
OPEN_CASE_STATUSES = {"OPEN", "TREATING", "MONITORING", "REOPENED"}
BOOKED_STATUSES = {"SCHEDULED", "PREP_NOTIFIED", "PREP_VERIFIED", "NON_COMPLIANT"}
COST_ESTIMATE = {"CHEMICAL": 12000, "HEAT": 65000, "EXCLUSION": 9000, "TRAPPING": 6000}
RATE_CARD = {"NON_COMPLIANCE_FEE": 15000, "REPEAT_INFESTATION": 22000,
             "HEAT_SURCHARGE": 65000, "LATE_FEE": 5000}
DISPOSAL_RATE = 7995
OVERAGE_RATE = 175
SURCHARGE = Decimal("1.075")
LATE_FEE_THRESHOLD = 50000
RESCHEDULE_LIMIT = 2
PREP_NOTICE_HOURS = 48
DISPUTE_WINDOW_DAYS = 14


# ============================================================================
# Auth
# ============================================================================
def authenticate():
    role = request.headers.get("X-User-Role")
    uid = request.headers.get("X-User-ID")
    if request.path == "/_clock/set_current_utc":
        if not role or role not in ROLES:
            err("ERR_UNAUTHENTICATED", 401, "Missing or unknown X-User-Role header")
        return role, uid
    if not role or role not in ROLES or not uid:
        err("ERR_UNAUTHENTICATED", 401, "Missing or unknown X-User-Role / X-User-ID headers")
    return role, uid


def require(role, *allowed):
    if role not in allowed:
        err("ERR_FORBIDDEN_ROLE", 403, "Role %s is not permitted on this endpoint" % role)


def acting_resident(uid):
    r = db["residents"].get(uid)
    if r is None:
        err("ERR_FORBIDDEN_ROLE", 403, "Resident identity not recognized")
    return r


def acting_technician(uid):
    t = db["technicians"].get(uid)
    if t is None:
        err("ERR_FORBIDDEN_ROLE", 403, "Technician identity not recognized")
    return t


# ============================================================================
# Body validation helpers
# ============================================================================
def body():
    b = request.get_json(silent=True)
    if b is None:
        return {}
    if not isinstance(b, dict):
        err("ERR_INVALID_REQUEST", 400, "Request body must be a JSON object")
    return b


def need(b, name):
    if name not in b or b[name] is None:
        err("ERR_INVALID_REQUEST", 400, "Missing required field: %s" % name)
    return b[name]


def as_str(v, name):
    if not isinstance(v, str) or v == "":
        err("ERR_INVALID_REQUEST", 400, "Field %s must be a non-empty string" % name)
    return v


def as_int(v, name, minv=None):
    if isinstance(v, bool) or not isinstance(v, int):
        err("ERR_INVALID_REQUEST", 400, "Field %s must be an integer" % name)
    if minv is not None and v < minv:
        err("ERR_INVALID_REQUEST", 400, "Field %s must be >= %d" % (name, minv))
    return v


def as_bool(v, name):
    if not isinstance(v, bool):
        err("ERR_INVALID_REQUEST", 400, "Field %s must be a boolean" % name)
    return v


def as_enum(v, name, allowed):
    if not isinstance(v, str) or v not in allowed:
        err("ERR_INVALID_REQUEST", 400, "Field %s must be one of %s" % (name, sorted(allowed)))
    return v


def opt_str(b, name):
    v = b.get(name)
    if v is None:
        return None
    return as_str(v, name)


def opt_int(b, name, minv=None):
    v = b.get(name)
    if v is None:
        return None
    return as_int(v, name, minv)


def opt_bool(b, name, default=None):
    v = b.get(name)
    if v is None:
        return default
    return as_bool(v, name)


def pagination():
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            err("ERR_INVALID_REQUEST", 400, "limit must be an integer")
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            err("ERR_INVALID_REQUEST", 400, "offset must be an integer")
    limit = max(1, min(100, limit))
    offset = max(0, offset)
    return limit, offset


def page_out(recs, serializer):
    limit, offset = pagination()
    recs = sorted(recs, key=lambda r: (r["created_at"], r["seq"]))
    total = len(recs)
    page = recs[offset:offset + limit]
    return ok_list([serializer(r) for r in page], total, limit, offset)


# ============================================================================
# Lazy transitions & recomputes
# ============================================================================
def lazy_contract(c):
    if c["status"] == "ACTIVE" and today() > c["end_date"]:
        c["status"] = "EXPIRED"
        touch(c)


def lazy_lease(l):
    if l["status"] == "ACTIVE" and today() > l["end_date"]:
        l["status"] = "ENDED"
        touch(l)


def refresh_spend(c):
    m = now().strftime("%Y-%m")
    if c.get("spent_month") != m:
        c["spent_month"] = m
        if c["spent_cents"] != 0:
            c["spent_cents"] = 0
            touch(c)
        else:
            c["spent_cents"] = 0


def property_contracts(property_id):
    cs = [c for c in db["contracts"].values() if c["property_id"] == property_id]
    for c in cs:
        lazy_contract(c)
    return sorted(cs, key=lambda c: (c["created_at"], c["seq"]))


def active_contract(property_id):
    for c in property_contracts(property_id):
        if c["status"] == "ACTIVE":
            return c
    return None


def latest_contract(property_id):
    cs = property_contracts(property_id)
    if not cs:
        return None
    act = [c for c in cs if c["status"] == "ACTIVE"]
    return act[0] if act else cs[-1]


def recompute_property(p):
    cnt = 0
    for c in db["cases"].values():
        u = db["units"].get(c["unit_id"])
        if u and u["property_id"] == p["id"] and c["status"] in OPEN_CASE_STATUSES:
            cnt += 1
    posture = "RESTRICTED" if cnt >= 3 else ("ELEVATED" if cnt >= 1 else "STANDARD")
    if p["open_bed_bug_case_count"] != cnt or p["posture"] != posture:
        p["open_bed_bug_case_count"] = cnt
        p["posture"] = posture
        touch(p)


def recompute_pest_flag(u):
    infested = any(c["unit_id"] == u["id"] and c["status"] in OPEN_CASE_STATUSES
                   for c in db["cases"].values())
    if infested:
        flag = "INFESTED"
    else:
        mon = any(i["unit_id"] == u["id"] and i["kind"] == "INITIAL"
                  and i["status"] == "SCHEDULED" and i.get("auto_created")
                  for i in db["inspections"].values())
        flag = "MONITORING" if mon else "CLEAR"
    if u["pest_flag"] != flag:
        u["pest_flag"] = flag
        touch(u)


def recompute_booked(t):
    total = sum(x["planned_minutes"] for x in db["treatments"].values()
                if x["technician_id"] == t["id"] and x["status"] in BOOKED_STATUSES)
    if t["booked_minutes"] != total:
        t["booked_minutes"] = total
        touch(t)


def recompute_balance(lease, allow_late_fee=True):
    old = lease["outstanding_balance_cents"]
    prov = sum(c["provisional_amount_cents"] or 0 for c in db["chargebacks"].values()
               if c["lease_id"] == lease["id"] and c["status"] in ("ASSESSED", "DISPUTED"))
    fin = sum(c["final_amount_cents"] or 0 for c in db["chargebacks"].values()
              if c["lease_id"] == lease["id"] and c["status"] in ("UPHELD", "BILLED"))
    total = prov + fin
    delinq = total > 0
    if total != old or lease["delinquent"] != delinq:
        lease["outstanding_balance_cents"] = total
        lease["delinquent"] = delinq
        touch(lease)
    if allow_late_fee and total > old and total >= LATE_FEE_THRESHOLD:
        live = any(c["lease_id"] == lease["id"] and c["kind"] == "LATE_FEE"
                   and c["status"] in ("ASSESSED", "DISPUTED", "UPHELD", "BILLED")
                   for c in db["chargebacks"].values())
        if not live:
            create_chargeback(lease, "LATE_FEE", assessed_by="system")
            recompute_balance(lease, allow_late_fee=False)


def classify_severity(live, evidence):
    if live >= 10 or evidence >= 20:
        return "SEVERE"
    if live >= 4 or evidence >= 8:
        return "MODERATE"
    if live >= 1 or evidence >= 1:
        return "LOW"
    return "NONE"


def adjacent_selector(unit):
    out = []
    for u in db["units"].values():
        if u["property_id"] != unit["property_id"] or u["id"] == unit["id"]:
            continue
        if u["operational_status"] == "RENOVATION":
            continue
        if (u["floor"] == unit["floor"] and abs(u["stack_index"] - unit["stack_index"]) == 1) or \
           (u["stack_index"] == unit["stack_index"] and abs(u["floor"] - unit["floor"]) == 1):
            out.append(u)
    return sorted(out, key=lambda u: u["unit_number"])


def negative_run(case_id):
    fups = [i for i in db["inspections"].values()
            if i.get("bed_bug_case_id") == case_id and i["kind"] == "FOLLOW_UP"
            and i["status"] == "COMPLETED"]
    fups.sort(key=lambda i: (i["completed_at"], i["seq"]))
    run = []
    for i in fups:
        if (not i["bed_bug_positive"]) and i["severity"] == "NONE":
            run.append(i["completed_at"])
        else:
            run = []
    return run


def maybe_case_monitoring(case):
    if case["status"] != "TREATING":
        return
    ts = [t for t in db["treatments"].values() if t.get("bed_bug_case_id") == case["id"]]
    if ts and all(t["status"] == "COMPLETED" for t in ts):
        ds = [d for d in db["disposals"].values() if d["bed_bug_case_id"] == case["id"]]
        if all(d["status"] == "VERIFIED" for d in ds):
            case["status"] = "MONITORING"
            touch(case)


def round_cents(x):
    return int(x.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def compute_chargeback_amount(cb, variant):
    lease = db["leases"][cb["lease_id"]]
    unit = db["units"][lease["unit_id"]]
    kind = cb["kind"]
    if kind == "REPEAT_INFESTATION":
        contract = active_contract(unit["property_id"])
        cov = min(contract["coverage_per_incident_cents"], 22000) if contract else 0
        lines = [max(0, 22000 - cov)]
    elif kind == "FURNITURE_DISPOSAL":
        if variant == "provisional":
            lines = [DISPOSAL_RATE] * (cb.get("planned_item_count") or 0)
        else:
            n = sum(1 for d in db["disposals"].values()
                    if d["bed_bug_case_id"] == cb.get("bed_bug_case_id")
                    and d["status"] == "VERIFIED")
            lines = [DISPOSAL_RATE] * n
    else:
        lines = [RATE_CARD[kind]]
    if variant == "final" and cb.get("source_treatment_id"):
        t = db["treatments"].get(cb["source_treatment_id"])
        if t and t["status"] == "COMPLETED":
            over = max(0, (t["actual_minutes"] or 0) - t["planned_minutes"]) * OVERAGE_RATE
            lines.append(over)
    total = sum(round_cents(Decimal(l) * SURCHARGE) for l in lines)
    total = min(total, lease["chargeback_cap_cents"])
    return max(0, total)


def create_chargeback(lease, kind, assessed_by, source_treatment_id=None,
                      bed_bug_case_id=None, planned_item_count=None, note=None):
    cb = new_rec()
    cb.update({
        "lease_id": lease["id"],
        "source_treatment_id": source_treatment_id,
        "bed_bug_case_id": bed_bug_case_id,
        "kind": kind,
        "planned_item_count": planned_item_count,
        "note": note,
        "status": "ASSESSED",
        "provisional_amount_cents": None,
        "final_amount_cents": None,
        "assessed_at": now(),
        "assessed_by": assessed_by,
        "disputed_at": None,
        "dispute_reason": None,
        "resolved_by": None,
        "resolution": None,
        "billed_at": None,
        "paid_at": None,
    })
    db["chargebacks"][cb["id"]] = cb
    cb["provisional_amount_cents"] = compute_chargeback_amount(cb, "provisional")
    return cb


def check_conflicts(unit, tech_id, ttype, ws, we, exclude_id=None):
    # unit double-booking
    for t in db["treatments"].values():
        if t["id"] == exclude_id or t["status"] in ("COMPLETED", "CANCELLED"):
            continue
        if t["unit_id"] == unit["id"] and ws < t["window_end"] and t["window_start"] < we:
            err("ERR_UNIT_DOUBLE_BOOKED", 409,
                "Unit already has a non-terminal treatment intersecting the window")
    # technician buffered overlap
    buf = timedelta(minutes=15)
    s, e = ws - buf, we + buf
    for t in db["treatments"].values():
        if t["id"] == exclude_id or t["status"] in ("COMPLETED", "CANCELLED"):
            continue
        if t["technician_id"] == tech_id:
            ts, te = t["window_start"] - buf, t["window_end"] + buf
            if s < te and ts < e:
                err("ERR_TREATMENT_WINDOW_CONFLICT", 409,
                    "Technician has a conflicting buffered treatment window")
    # heat floor gap
    if ttype == "HEAT":
        for t in db["treatments"].values():
            if t["id"] == exclude_id or t["status"] in ("COMPLETED", "CANCELLED"):
                continue
            if t["treatment_type"] != "HEAT":
                continue
            tu = db["units"].get(t["unit_id"])
            if tu and tu["property_id"] == unit["property_id"] and tu["floor"] == unit["floor"]:
                if abs((t["window_start"] - ws).total_seconds()) < 24 * 3600:
                    err("ERR_HEAT_FLOOR_GAP_VIOLATION", 409,
                        "HEAT treatment within 24h of another HEAT treatment on this floor")


# ============================================================================
# Serializers
# ============================================================================
def ser_property(p):
    return {"id": p["id"], "name": p["name"], "address": p["address"],
            "timezone": p["timezone"], "posture": p["posture"],
            "open_bed_bug_case_count": p["open_bed_bug_case_count"],
            "created_at": fmt_ts(p["created_at"]), "updated_at": fmt_ts(p["updated_at"]),
            "version": p["version"]}


def ser_contract(c):
    lazy_contract(c)
    refresh_spend(c)
    return {"id": c["id"], "property_id": c["property_id"], "vendor_name": c["vendor_name"],
            "scope_pest_types": c["scope_pest_types"], "visits_per_month": c["visits_per_month"],
            "coverage_per_incident_cents": c["coverage_per_incident_cents"],
            "heat_treatment_included": c["heat_treatment_included"],
            "monthly_budget_cents": c["monthly_budget_cents"],
            "spent_cents": c["spent_cents"],
            "start_date": c["start_date"].isoformat(), "end_date": c["end_date"].isoformat(),
            "status": c["status"],
            "created_at": fmt_ts(c["created_at"]), "updated_at": fmt_ts(c["updated_at"]),
            "version": c["version"]}


def ser_unit(u):
    return {"id": u["id"], "property_id": u["property_id"], "unit_number": u["unit_number"],
            "floor": u["floor"], "stack_index": u["stack_index"], "bedrooms": u["bedrooms"],
            "operational_status": u["operational_status"], "pest_flag": u["pest_flag"],
            "no_access_strikes": u["no_access_strikes"],
            "created_at": fmt_ts(u["created_at"]), "updated_at": fmt_ts(u["updated_at"]),
            "version": u["version"]}


def ser_lease(l):
    lazy_lease(l)
    return {"id": l["id"], "unit_id": l["unit_id"],
            "start_date": l["start_date"].isoformat(), "end_date": l["end_date"].isoformat(),
            "pest_addendum_signed": l["pest_addendum_signed"],
            "chargeback_clause_version": l["chargeback_clause_version"],
            "chargeback_cap_cents": l["chargeback_cap_cents"], "status": l["status"],
            "outstanding_balance_cents": l["outstanding_balance_cents"],
            "delinquent": l["delinquent"],
            "created_at": fmt_ts(l["created_at"]), "updated_at": fmt_ts(l["updated_at"]),
            "version": l["version"]}


def ser_resident(r):
    return {"id": r["id"], "unit_id": r["unit_id"], "lease_id": r["lease_id"],
            "full_name": r["full_name"], "email": r["email"],
            "created_at": fmt_ts(r["created_at"]), "updated_at": fmt_ts(r["updated_at"]),
            "version": r["version"]}


def ser_technician(t):
    return {"id": t["id"], "full_name": t["full_name"], "vendor_name": t["vendor_name"],
            "active": t["active"], "booked_minutes": t["booked_minutes"],
            "created_at": fmt_ts(t["created_at"]), "updated_at": fmt_ts(t["updated_at"]),
            "version": t["version"]}


def opt_ts(v):
    return fmt_ts(v) if v is not None else None


def ser_inspection(i):
    return {"id": i["id"], "unit_id": i["unit_id"], "technician_id": i["technician_id"],
            "bed_bug_case_id": i["bed_bug_case_id"], "kind": i["kind"],
            "pest_type": i["pest_type"], "scheduled_for": fmt_ts(i["scheduled_for"]),
            "status": i["status"], "completed_at": opt_ts(i["completed_at"]),
            "live_sightings": i["live_sightings"], "evidence_count": i["evidence_count"],
            "bed_bug_positive": i["bed_bug_positive"], "severity": i["severity"],
            "created_at": fmt_ts(i["created_at"]), "updated_at": fmt_ts(i["updated_at"]),
            "version": i["version"]}


def ser_treatment(t):
    return {"id": t["id"], "unit_id": t["unit_id"], "technician_id": t["technician_id"],
            "inspection_id": t["inspection_id"], "bed_bug_case_id": t["bed_bug_case_id"],
            "pest_type": t["pest_type"], "treatment_type": t["treatment_type"],
            "window_start": fmt_ts(t["window_start"]), "window_end": fmt_ts(t["window_end"]),
            "planned_minutes": t["planned_minutes"], "vacancy_attested": t["vacancy_attested"],
            "status": t["status"], "prep_notified_at": opt_ts(t["prep_notified_at"]),
            "prep_acknowledged_at": opt_ts(t["prep_acknowledged_at"]),
            "reschedule_count": t["reschedule_count"], "actual_minutes": t["actual_minutes"],
            "created_at": fmt_ts(t["created_at"]), "updated_at": fmt_ts(t["updated_at"]),
            "version": t["version"]}


def ser_case(c):
    return {"id": c["id"], "unit_id": c["unit_id"], "status": c["status"],
            "consecutive_negative_count": c["consecutive_negative_count"],
            "cleared_at": opt_ts(c["cleared_at"]),
            "created_at": fmt_ts(c["created_at"]), "updated_at": fmt_ts(c["updated_at"]),
            "version": c["version"]}


def ser_disposal(d):
    return {"id": d["id"], "bed_bug_case_id": d["bed_bug_case_id"],
            "item_description": d["item_description"], "quantity": d["quantity"],
            "status": d["status"], "verified_at": opt_ts(d["verified_at"]),
            "created_at": fmt_ts(d["created_at"]), "updated_at": fmt_ts(d["updated_at"]),
            "version": d["version"]}


def ser_chargeback(c):
    return {"id": c["id"], "lease_id": c["lease_id"],
            "source_treatment_id": c["source_treatment_id"],
            "bed_bug_case_id": c["bed_bug_case_id"], "kind": c["kind"],
            "planned_item_count": c["planned_item_count"], "note": c["note"],
            "status": c["status"], "provisional_amount_cents": c["provisional_amount_cents"],
            "final_amount_cents": c["final_amount_cents"],
            "assessed_at": opt_ts(c["assessed_at"]), "assessed_by": c["assessed_by"],
            "disputed_at": opt_ts(c["disputed_at"]), "dispute_reason": c["dispute_reason"],
            "resolved_by": c["resolved_by"], "resolution": c["resolution"],
            "billed_at": opt_ts(c["billed_at"]), "paid_at": opt_ts(c["paid_at"]),
            "created_at": fmt_ts(c["created_at"]), "updated_at": fmt_ts(c["updated_at"]),
            "version": c["version"]}


def ser_packet(p):
    return {"id": p["id"], "property_id": p["property_id"],
            "claim_reference": p["claim_reference"], "references": p["references"],
            "pinned_references": p["pinned_references"], "status": p["status"],
            "finalized_at": opt_ts(p["finalized_at"]),
            "created_at": fmt_ts(p["created_at"]), "updated_at": fmt_ts(p["updated_at"]),
            "version": p["version"]}


def lookup_entity(etype, eid):
    coll = {"Inspection": "inspections", "Treatment": "treatments",
            "BedBugCase": "cases"}.get(etype)
    if coll is None:
        return None
    return db[coll].get(eid)


# ============================================================================
# Clock endpoint
# ============================================================================
@app.post("/_clock/set_current_utc")
def set_clock():
    role, uid = authenticate()
    require(role, "ProgramAdmin")
    b = body()
    v = parse_dt(need(b, "to_iso8601"), "to_iso8601")
    _clock["now"] = v
    return ok({"current_utc": fmt_ts(v)})


# ============================================================================
# Properties
# ============================================================================
@app.post("/pest/properties")
def create_property():
    role, uid = authenticate()
    require(role, "ProgramAdmin")
    b = body()
    name = as_str(need(b, "name"), "name")
    address = as_str(need(b, "address"), "address")
    tz = b.get("timezone", "America/Los_Angeles")
    if not isinstance(tz, str) or not tz:
        err("ERR_INVALID_REQUEST", 400, "Field timezone must be a string")
    p = new_rec()
    p.update({"name": name, "address": address, "timezone": tz,
              "posture": "STANDARD", "open_bed_bug_case_count": 0})
    db["properties"][p["id"]] = p
    return ok(ser_property(p), 201)


@app.get("/pest/properties")
def list_properties():
    role, uid = authenticate()
    require(role, "ProgramAdmin", "PropertyManager", "BillingClerk", "ComplianceOfficer")
    return page_out(list(db["properties"].values()), ser_property)


@app.get("/pest/properties/<pid>")
def get_property(pid):
    role, uid = authenticate()
    require(role, "ProgramAdmin", "PropertyManager", "BillingClerk", "ComplianceOfficer")
    p = get_or_404("properties", pid, "Property")
    recompute_property(p)
    return ok(ser_property(p))


@app.get("/pest/properties/<pid>/summary")
def property_summary(pid):
    role, uid = authenticate()
    require(role, "ProgramAdmin", "PropertyManager", "BillingClerk", "ComplianceOfficer")
    p = get_or_404("properties", pid, "Property")
    recompute_property(p)
    total = 0
    for l in db["leases"].values():
        u = db["units"].get(l["unit_id"])
        if u and u["property_id"] == pid:
            total += l["outstanding_balance_cents"]
    return ok({"posture": p["posture"],
               "open_bed_bug_case_count": p["open_bed_bug_case_count"],
               "total_outstanding_balance_cents": total})


# ============================================================================
# Contracts
# ============================================================================
@app.post("/pest/properties/<pid>/contracts")
def create_contract(pid):
    role, uid = authenticate()
    require(role, "ProgramAdmin")
    p = get_or_404("properties", pid, "Property")
    b = body()
    vendor_name = as_str(need(b, "vendor_name"), "vendor_name")
    scope = need(b, "scope_pest_types")
    if not isinstance(scope, list) or len(scope) == 0:
        err("ERR_INVALID_REQUEST", 400, "scope_pest_types must be a non-empty array")
    for s in scope:
        if s not in PESTS:
            err("ERR_INVALID_REQUEST", 400, "Unknown pest type: %s" % s)
    vpm = as_int(need(b, "visits_per_month"), "visits_per_month", minv=1)
    cov = as_int(need(b, "coverage_per_incident_cents"), "coverage_per_incident_cents", minv=0)
    hti = as_bool(need(b, "heat_treatment_included"), "heat_treatment_included")
    budget = as_int(need(b, "monthly_budget_cents"), "monthly_budget_cents", minv=1)
    sd = parse_date(need(b, "start_date"), "start_date")
    ed = parse_date(need(b, "end_date"), "end_date")
    if ed < sd:
        err("ERR_INVALID_REQUEST", 400, "end_date must be >= start_date")
    c = new_rec()
    c.update({"property_id": pid, "vendor_name": vendor_name, "scope_pest_types": scope,
              "visits_per_month": vpm, "coverage_per_incident_cents": cov,
              "heat_treatment_included": hti, "monthly_budget_cents": budget,
              "spent_cents": 0, "spent_month": now().strftime("%Y-%m"),
              "start_date": sd, "end_date": ed, "status": "DRAFT"})
    db["contracts"][c["id"]] = c
    return ok(ser_contract(c), 201)


@app.get("/pest/properties/<pid>/contracts")
def list_contracts(pid):
    role, uid = authenticate()
    require(role, "ProgramAdmin", "PropertyManager", "BillingClerk")
    get_or_404("properties", pid, "Property")
    return page_out([c for c in db["contracts"].values() if c["property_id"] == pid],
                    ser_contract)


@app.get("/pest/contracts/<cid>")
def get_contract(cid):
    role, uid = authenticate()
    require(role, "ProgramAdmin", "PropertyManager", "BillingClerk")
    c = get_or_404("contracts", cid, "ServiceContract")
    return ok(ser_contract(c))


def _contract_action(cid, fn):
    role, uid = authenticate()
    require(role, "ProgramAdmin")
    c = get_or_404("contracts", cid, "ServiceContract")
    lazy_contract(c)
    fn(c)
    return ok(ser_contract(c))


@app.post("/pest/contracts/<cid>/activate")
def activate_contract(cid):
    def fn(c):
        if c["status"] in ("TERMINATED", "EXPIRED"):
            err("ERR_ALREADY_TERMINAL", 409, "Contract is in a terminal state")
        if c["status"] != "DRAFT":
            err("ERR_INVALID_STATE", 409, "Contract is not in DRAFT")
        if not c["scope_pest_types"] or not (c["start_date"] <= today() <= c["end_date"]):
            err("ERR_INVALID_STATE", 409, "Activation preconditions not met")
        c["status"] = "ACTIVE"
        touch(c)
    return _contract_action(cid, fn)


@app.post("/pest/contracts/<cid>/suspend")
def suspend_contract(cid):
    def fn(c):
        if c["status"] in ("TERMINATED", "EXPIRED"):
            err("ERR_ALREADY_TERMINAL", 409, "Contract is in a terminal state")
        if c["status"] != "ACTIVE":
            err("ERR_INVALID_STATE", 409, "Contract is not ACTIVE")
        c["status"] = "SUSPENDED"
        touch(c)
    return _contract_action(cid, fn)


@app.post("/pest/contracts/<cid>/reactivate")
def reactivate_contract(cid):
    def fn(c):
        if c["status"] in ("TERMINATED", "EXPIRED"):
            err("ERR_ALREADY_TERMINAL", 409, "Contract is in a terminal state")
        if c["status"] != "SUSPENDED":
            err("ERR_INVALID_STATE", 409, "Contract is not SUSPENDED")
        if today() > c["end_date"]:
            err("ERR_INVALID_STATE", 409, "Contract end date has passed")
        c["status"] = "ACTIVE"
        touch(c)
    return _contract_action(cid, fn)


@app.post("/pest/contracts/<cid>/terminate")
def terminate_contract(cid):
    def fn(c):
        if c["status"] in ("TERMINATED", "EXPIRED"):
            err("ERR_ALREADY_TERMINAL", 409, "Contract is in a terminal state")
        if c["status"] not in ("ACTIVE", "SUSPENDED"):
            err("ERR_INVALID_STATE", 409, "Contract cannot be terminated from %s" % c["status"])
        c["status"] = "TERMINATED"
        touch(c)
    return _contract_action(cid, fn)


# ============================================================================
# Units
# ============================================================================
@app.post("/pest/properties/<pid>/units")
def create_unit(pid):
    role, uid = authenticate()
    require(role, "ProgramAdmin")
    get_or_404("properties", pid, "Property")
    b = body()
    unit_number = as_str(need(b, "unit_number"), "unit_number")
    floor = as_int(need(b, "floor"), "floor", minv=1)
    stack_index = as_int(need(b, "stack_index"), "stack_index", minv=1)
    bedrooms = as_int(need(b, "bedrooms"), "bedrooms", minv=0)
    op = b.get("operational_status", "OCCUPIED")
    if op not in ("OCCUPIED", "VACANT", "RENOVATION"):
        err("ERR_INVALID_REQUEST", 400, "Unknown operational_status: %s" % op)
    for u in db["units"].values():
        if u["property_id"] == pid and u["unit_number"] == unit_number:
            err("ERR_DUPLICATE_UNIT_NUMBER", 409,
                "unit_number already exists within the property")
    u = new_rec()
    u.update({"property_id": pid, "unit_number": unit_number, "floor": floor,
              "stack_index": stack_index, "bedrooms": bedrooms,
              "operational_status": op, "pest_flag": "CLEAR", "no_access_strikes": 0})
    db["units"][u["id"]] = u
    return ok(ser_unit(u), 201)


@app.get("/pest/properties/<pid>/units")
def list_units(pid):
    role, uid = authenticate()
    require(role, "ProgramAdmin", "PropertyManager", "Technician", "BillingClerk",
            "ComplianceOfficer")
    get_or_404("properties", pid, "Property")
    recs = [u for u in db["units"].values() if u["property_id"] == pid]
    raw_floor = request.args.get("floor")
    if raw_floor is not None:
        try:
            fl = int(raw_floor)
        except (TypeError, ValueError):
            err("ERR_INVALID_REQUEST", 400, "floor must be an integer")
        recs = [u for u in recs if u["floor"] == fl]
    return page_out(recs, ser_unit)


@app.get("/pest/units/<uid_>")
def get_unit(uid_):
    role, uid = authenticate()
    require(role, "ProgramAdmin", "PropertyManager", "Technician", "BillingClerk",
            "ComplianceOfficer", "Resident")
    u = get_or_404("units", uid_, "Unit")
    if role == "Resident":
        r = acting_resident(uid)
        if r["unit_id"] != u["id"]:
            err("ERR_FORBIDDEN_ROLE", 403, "Resident does not belong to this unit")
    return ok(ser_unit(u))


@app.get("/pest/units/<uid_>/risk-score")
def unit_risk_score(uid_):
    role, uid = authenticate()
    require(role, "ProgramAdmin", "PropertyManager")
    u = get_or_404("units", uid_, "Unit")
    variant = request.args.get("variant")
    if variant not in ("FORWARD", "HISTORICAL"):
        err("ERR_INVALID_REQUEST", 400, "variant must be FORWARD or HISTORICAL")
    n = now()
    # severe recent
    sev_cutoff = n - timedelta(days=90)
    severe_recent = 40 if any(
        i["unit_id"] == u["id"] and i["status"] == "COMPLETED"
        and i["severity"] == "SEVERE" and i["completed_at"] >= sev_cutoff
        for i in db["inspections"].values()) else 0
    # prior cases
    case_count = sum(1 for c in db["cases"].values() if c["unit_id"] == u["id"])
    prior_cases_points = 15 * min(3, case_count)
    # adjacent open
    adj = adjacent_selector(u)
    adj_ids = {a["id"] for a in adj}
    adj_open_count = sum(1 for c in db["cases"].values()
                         if c["unit_id"] in adj_ids and c["status"] in OPEN_CASE_STATUSES)
    adjacent_open_points = 10 * min(2, adj_open_count)
    # recency
    if variant == "FORWARD":
        rel = [t for t in db["treatments"].values() if t["unit_id"] == u["id"]
               and t["status"] in ("SCHEDULED", "PREP_NOTIFIED", "PREP_VERIFIED", "COMPLETED")]
    else:
        rel = [t for t in db["treatments"].values() if t["unit_id"] == u["id"]
               and t["status"] == "COMPLETED"]
    window_cutoff = n - timedelta(days=180)
    rel_in = [t for t in rel if t["window_start"] >= window_cutoff]
    if not rel_in:
        recency_points = 25
    else:
        most_recent = max(t["window_start"] for t in rel_in)
        days = max(0, (n - most_recent).days)
        recency_points = min(25, 5 * (days // 30))
    score = min(100, severe_recent + prior_cases_points + adjacent_open_points + recency_points)
    return ok({"score": score, "variant": variant, "severe_recent": severe_recent,
               "prior_cases_points": prior_cases_points,
               "adjacent_open_points": adjacent_open_points,
               "recency_points": recency_points})


@app.get("/pest/units/<uid_>/adjacent-exposure")
def unit_adjacent_exposure(uid_):
    role, uid = authenticate()
    require(role, "ProgramAdmin", "PropertyManager")
    u = get_or_404("units", uid_, "Unit")
    return page_out(adjacent_selector(u), ser_unit)


# ============================================================================
# Leases & Residents
# ============================================================================
@app.post("/pest/units/<uid_>/leases")
def create_lease(uid_):
    role, uid = authenticate()
    require(role, "PropertyManager")
    u = get_or_404("units", uid_, "Unit")
    b = body()
    sd = parse_date(need(b, "start_date"), "start_date")
    ed = parse_date(need(b, "end_date"), "end_date")
    if ed < sd:
        err("ERR_INVALID_REQUEST", 400, "end_date must be >= start_date")
    signed = as_bool(need(b, "pest_addendum_signed"), "pest_addendum_signed")
    ccv = as_str(need(b, "chargeback_clause_version"), "chargeback_clause_version")
    cap = as_int(need(b, "chargeback_cap_cents"), "chargeback_cap_cents", minv=0)
    prop = db["properties"][u["property_id"]]
    recompute_property(prop)
    if prop["posture"] == "RESTRICTED":
        err("ERR_PROPERTY_RESTRICTED", 409, "Property posture is RESTRICTED")
    l = new_rec()
    l.update({"unit_id": u["id"], "start_date": sd, "end_date": ed,
              "pest_addendum_signed": signed, "chargeback_clause_version": ccv,
              "chargeback_cap_cents": cap, "status": "ACTIVE",
              "outstanding_balance_cents": 0, "delinquent": False})
    db["leases"][l["id"]] = l
    return ok(ser_lease(l), 201)


@app.get("/pest/units/<uid_>/leases")
def list_unit_leases(uid_):
    role, uid = authenticate()
    require(role, "ProgramAdmin", "PropertyManager", "BillingClerk", "Resident")
    u = get_or_404("units", uid_, "Unit")
    if role == "Resident":
        r = acting_resident(uid)
        if r["unit_id"] != u["id"]:
            err("ERR_FORBIDDEN_ROLE", 403, "Resident does not belong to this unit")
    return page_out([l for l in db["leases"].values() if l["unit_id"] == u["id"]], ser_lease)


@app.get("/pest/leases/<lid>")
def get_lease(lid):
    role, uid = authenticate()
    require(role, "ProgramAdmin", "PropertyManager", "BillingClerk", "Resident")
    l = get_or_404("leases", lid, "Lease")
    if role == "Resident":
        r = acting_resident(uid)
        if r["lease_id"] != l["id"]:
            err("ERR_FORBIDDEN_ROLE", 403, "Lease does not belong to this resident")
    return ok(ser_lease(l))


@app.get("/pest/leases/<lid>/chargebacks")
def list_lease_chargebacks(lid):
    role, uid = authenticate()
    require(role, "ProgramAdmin", "PropertyManager", "BillingClerk", "Resident")
    l = get_or_404("leases", lid, "Lease")
    if role == "Resident":
        r = acting_resident(uid)
        if r["lease_id"] != l["id"]:
            err("ERR_FORBIDDEN_ROLE", 403, "Lease does not belong to this resident")
    recs = [c for c in db["chargebacks"].values() if c["lease_id"] == l["id"]]
    status = request.args.get("status")
    if status is not None:
        recs = [c for c in recs if c["status"] == status]
    return page_out(recs, ser_chargeback)


@app.post("/pest/units/<uid_>/residents")
def create_resident(uid_):
    role, uid = authenticate()
    require(role, "PropertyManager")
    u = get_or_404("units", uid_, "Unit")
    b = body()
    full_name = as_str(need(b, "full_name"), "full_name")
    email = as_str(need(b, "email"), "email")
    lease_id = as_str(need(b, "lease_id"), "lease_id")
    lease = get_or_404("leases", lease_id, "Lease")
    if lease["unit_id"] != u["id"]:
        err("ERR_NOT_FOUND", 404, "Lease %s does not belong to this unit" % lease_id)
    r = new_rec()
    r.update({"unit_id": u["id"], "lease_id": lease_id, "full_name": full_name,
              "email": email})
    db["residents"][r["id"]] = r
    return ok(ser_resident(r), 201)


@app.get("/pest/units/<uid_>/residents")
def list_unit_residents(uid_):
    role, uid = authenticate()
    require(role, "ProgramAdmin", "PropertyManager")
    u = get_or_404("units", uid_, "Unit")
    return page_out([r for r in db["residents"].values() if r["unit_id"] == u["id"]],
                    ser_resident)


@app.get("/pest/leases/<lid>/residents")
def list_lease_residents(lid):
    role, uid = authenticate()
    require(role, "ProgramAdmin", "PropertyManager", "BillingClerk")
    l = get_or_404("leases", lid, "Lease")
    return page_out([r for r in db["residents"].values() if r["lease_id"] == l["id"]],
                    ser_resident)


# ============================================================================
# Technicians
# ============================================================================
@app.post("/pest/technicians")
def create_technician():
    role, uid = authenticate()
    require(role, "ProgramAdmin")
    b = body()
    full_name = as_str(need(b, "full_name"), "full_name")
    vendor_name = as_str(need(b, "vendor_name"), "vendor_name")
    active = opt_bool(b, "active", True)
    t = new_rec()
    t.update({"full_name": full_name, "vendor_name": vendor_name, "active": active,
              "booked_minutes": 0})
    db["technicians"][t["id"]] = t
    return ok(ser_technician(t), 201)


@app.get("/pest/technicians/<tid>")
def get_technician(tid):
    role, uid = authenticate()
    require(role, "ProgramAdmin", "PropertyManager", "Technician")
    t = get_or_404("technicians", tid, "Technician")
    if role == "Technician" and tid != uid:
        err("ERR_FORBIDDEN_ROLE", 403, "Technician may only read own record")
    return ok(ser_technician(t))


@app.get("/pest/technicians/<tid>/treatments")
def list_technician_treatments(tid):
    role, uid = authenticate()
    require(role, "ProgramAdmin", "PropertyManager", "Technician")
    t = get_or_404("technicians", tid, "Technician")
    if role == "Technician" and tid != uid:
        err("ERR_FORBIDDEN_ROLE", 403, "Technician may only read own schedule")
    recs = [x for x in db["treatments"].values() if x["technician_id"] == t["id"]]
    status = request.args.get("status")
    if status is not None:
        recs = [x for x in recs if x["status"] == status]
    return page_out(recs, ser_treatment)


@app.get("/pest/technicians/<tid>/inspections")
def list_technician_inspections(tid):
    role, uid = authenticate()
    require(role, "ProgramAdmin", "PropertyManager", "Technician")
    t = get_or_404("technicians", tid, "Technician")
    if role == "Technician" and tid != uid:
        err("ERR_FORBIDDEN_ROLE", 403, "Technician may only read own schedule")
    recs = [x for x in db["inspections"].values() if x["technician_id"] == t["id"]]
    status = request.args.get("status")
    if status is not None:
        recs = [x for x in recs if x["status"] == status]
    return page_out(recs, ser_inspection)


# ============================================================================
# Inspections
# ============================================================================
@app.post("/pest/units/<uid_>/inspections")
def create_inspection(uid_):
    role, uid = authenticate()
    require(role, "PropertyManager")
    u = get_or_404("units", uid_, "Unit")
    b = body()
    technician_id = as_str(need(b, "technician_id"), "technician_id")
    kind = as_enum(need(b, "kind"), "kind", INSPECTION_KINDS)
    pest_type = as_enum(need(b, "pest_type"), "pest_type", PESTS)
    scheduled_for = parse_dt(need(b, "scheduled_for"), "scheduled_for")
    bbc = b.get("bed_bug_case_id")
    tech = get_or_404("technicians", technician_id, "Technician")
    if bbc is not None:
        get_or_404("cases", bbc, "BedBugCase")
    if not tech["active"]:
        err("ERR_INVALID_REQUEST", 400, "Technician is not active")
    contract = active_contract(u["property_id"])
    if contract is None or pest_type not in contract["scope_pest_types"]:
        err("ERR_CONTRACT_SCOPE_EXCLUDED", 422,
            "pest_type is not within the ACTIVE contract scope")
    i = new_rec()
    i.update({"unit_id": u["id"], "technician_id": technician_id, "bed_bug_case_id": bbc,
              "kind": kind, "pest_type": pest_type, "scheduled_for": scheduled_for,
              "status": "SCHEDULED", "completed_at": None, "live_sightings": None,
              "evidence_count": None, "bed_bug_positive": None, "severity": None,
              "auto_created": False})
    db["inspections"][i["id"]] = i
    return ok(ser_inspection(i), 201)


@app.get("/pest/units/<uid_>/inspections")
def list_unit_inspections(uid_):
    role, uid = authenticate()
    require(role, "ProgramAdmin", "PropertyManager", "Technician", "Resident")
    u = get_or_404("units", uid_, "Unit")
    if role == "Resident":
        r = acting_resident(uid)
        if r["unit_id"] != u["id"]:
            err("ERR_FORBIDDEN_ROLE", 403, "Resident does not belong to this unit")
    recs = [i for i in db["inspections"].values() if i["unit_id"] == u["id"]]
    kind = request.args.get("kind")
    if kind is not None:
        recs = [i for i in recs if i["kind"] == kind]
    status = request.args.get("status")
    if status is not None:
        recs = [i for i in recs if i["status"] == status]
    return page_out(recs, ser_inspection)


@app.get("/pest/inspections/<iid>")
def get_inspection(iid):
    role, uid = authenticate()
    require(role, "ProgramAdmin", "PropertyManager", "Technician", "Resident",
            "ComplianceOfficer")
    i = get_or_404("inspections", iid, "Inspection")
    if role == "Technician" and i["technician_id"] != uid:
        err("ERR_FORBIDDEN_ROLE", 403, "Inspection is not assigned to this technician")
    if role == "Resident":
        r = acting_resident(uid)
        if r["unit_id"] != i["unit_id"]:
            err("ERR_FORBIDDEN_ROLE", 403, "Inspection does not belong to this unit")
    return ok(ser_inspection(i))


@app.get("/pest/bed-bug-cases/<cid>/inspections")
def list_case_inspections(cid):
    role, uid = authenticate()
    require(role, "ProgramAdmin", "PropertyManager", "Technician")
    get_or_404("cases", cid, "BedBugCase")
    return page_out([i for i in db["inspections"].values()
                     if i.get("bed_bug_case_id") == cid], ser_inspection)


@app.get("/pest/inspections/<iid>/treatments")
def list_inspection_treatments(iid):
    role, uid = authenticate()
    require(role, "ProgramAdmin", "PropertyManager", "Technician")
    i = get_or_404("inspections", iid, "Inspection")
    return page_out([t for t in db["treatments"].values()
                     if t.get("inspection_id") == i["id"]], ser_treatment)


@app.post("/pest/inspections/<iid>/complete")
def complete_inspection(iid):
    role, uid = authenticate()
    require(role, "Technician")
    i = get_or_404("inspections", iid, "Inspection")
    tech = acting_technician(uid)
    if i["technician_id"] != tech["id"]:
        err("ERR_FORBIDDEN_ROLE", 403, "Inspection is not assigned to this technician")
    b = body()
    live = as_int(need(b, "live_sightings"), "live_sightings", minv=0)
    evidence = as_int(need(b, "evidence_count"), "evidence_count", minv=0)
    positive = as_bool(need(b, "bed_bug_positive"), "bed_bug_positive")
    if i["status"] in ("COMPLETED", "NO_ACCESS", "CANCELLED"):
        err("ERR_ALREADY_TERMINAL", 409, "Inspection is in a terminal state")
    if i["status"] != "SCHEDULED":
        err("ERR_INVALID_STATE", 409, "Inspection cannot be completed from %s" % i["status"])
    i["live_sightings"] = live
    i["evidence_count"] = evidence
    i["bed_bug_positive"] = positive
    i["completed_at"] = now()
    i["severity"] = classify_severity(live, evidence)
    i["status"] = "COMPLETED"
    touch(i)
    unit = db["units"][i["unit_id"]]
    if positive:
        live_cases = sorted(
            [c for c in db["cases"].values()
             if c["unit_id"] == unit["id"] and c["status"] in OPEN_CASE_STATUSES],
            key=lambda c: c["seq"])
        if not live_cases:
            case = new_rec()
            case.update({"unit_id": unit["id"], "status": "OPEN",
                         "consecutive_negative_count": 0, "cleared_at": None})
            db["cases"][case["id"]] = case
            for au in adjacent_selector(unit):
                ni = new_rec()
                ni.update({"unit_id": au["id"], "technician_id": tech["id"],
                           "bed_bug_case_id": case["id"], "kind": "INITIAL",
                           "pest_type": "BED_BUGS",
                           "scheduled_for": now() + timedelta(hours=24),
                           "status": "SCHEDULED", "completed_at": None,
                           "live_sightings": None, "evidence_count": None,
                           "bed_bug_positive": None, "severity": None,
                           "auto_created": True})
                db["inspections"][ni["id"]] = ni
                recompute_pest_flag(au)
        else:
            case = live_cases[0]
            if case["status"] == "MONITORING":
                case["status"] = "REOPENED"
                case["consecutive_negative_count"] = 0
                touch(case)
        recompute_pest_flag(unit)
        prop = db["properties"][unit["property_id"]]
        recompute_property(prop)
    if i["kind"] == "FOLLOW_UP" and i.get("bed_bug_case_id"):
        case = db["cases"].get(i["bed_bug_case_id"])
        if case is not None:
            cnt = len(negative_run(case["id"]))
            if case["consecutive_negative_count"] != cnt:
                case["consecutive_negative_count"] = cnt
                touch(case)
    return ok(ser_inspection(i))


@app.post("/pest/inspections/<iid>/no-access")
def no_access_inspection(iid):
    role, uid = authenticate()
    require(role, "Technician")
    i = get_or_404("inspections", iid, "Inspection")
    tech = acting_technician(uid)
    if i["technician_id"] != tech["id"]:
        err("ERR_FORBIDDEN_ROLE", 403, "Inspection is not assigned to this technician")
    body()
    if i["status"] in ("COMPLETED", "NO_ACCESS", "CANCELLED"):
        err("ERR_ALREADY_TERMINAL", 409, "Inspection is in a terminal state")
    if i["status"] != "SCHEDULED":
        err("ERR_INVALID_STATE", 409, "Inspection cannot be marked no-access from %s" % i["status"])
    i["status"] = "NO_ACCESS"
    touch(i)
    unit = db["units"][i["unit_id"]]
    unit["no_access_strikes"] += 1
    touch(unit)
    if unit["no_access_strikes"] >= 2:
        unit["no_access_strikes"] = 0
        touch(unit)
        lease = None
        for l in sorted([l for l in db["leases"].values() if l["unit_id"] == unit["id"]],
                        key=lambda l: l["seq"]):
            lazy_lease(l)
            if l["status"] == "ACTIVE" and l["pest_addendum_signed"]:
                lease = l
                break
        if lease is not None:
            create_chargeback(lease, "NON_COMPLIANCE_FEE", assessed_by="system")
            recompute_balance(lease)
    return ok(ser_inspection(i))


@app.post("/pest/inspections/<iid>/cancel")
def cancel_inspection(iid):
    role, uid = authenticate()
    require(role, "PropertyManager")
    i = get_or_404("inspections", iid, "Inspection")
    body()
    if i["status"] in ("COMPLETED", "NO_ACCESS", "CANCELLED"):
        err("ERR_ALREADY_TERMINAL", 409, "Inspection is in a terminal state")
    if i["status"] != "SCHEDULED":
        err("ERR_INVALID_STATE", 409, "Inspection cannot be cancelled from %s" % i["status"])
    i["status"] = "CANCELLED"
    touch(i)
    unit = db["units"][i["unit_id"]]
    recompute_pest_flag(unit)
    return ok(ser_inspection(i))


# ============================================================================
# Treatments
# ============================================================================
def _treatment_gates(unit, tech_id, ttype, pest_type, vacancy, ws, we, exclude_id=None):
    # state gate: contract ACTIVE
    contract = active_contract(unit["property_id"])
    if contract is None:
        err("ERR_CONTRACT_NOT_ACTIVE", 409, "The property's contract is not ACTIVE")
    # heat safety
    if ttype == "HEAT" and vacancy is not True:
        err("ERR_HEAT_SAFETY_VIOLATION", 422, "HEAT treatment requires vacancy_attested")
    # temporal conflicts
    check_conflicts(unit, tech_id, ttype, ws, we, exclude_id)
    # scope
    if pest_type not in contract["scope_pest_types"]:
        err("ERR_CONTRACT_SCOPE_EXCLUDED", 422,
            "pest_type is not within the ACTIVE contract scope")
    return contract


@app.post("/pest/units/<uid_>/treatments")
def create_treatment(uid_):
    role, uid = authenticate()
    require(role, "PropertyManager")
    u = get_or_404("units", uid_, "Unit")
    b = body()
    technician_id = as_str(need(b, "technician_id"), "technician_id")
    pest_type = as_enum(need(b, "pest_type"), "pest_type", PESTS)
    ttype = as_enum(need(b, "treatment_type"), "treatment_type", TREATMENT_TYPES)
    ws = parse_dt(need(b, "window_start"), "window_start")
    we = parse_dt(need(b, "window_end"), "window_end")
    if ws >= we:
        err("ERR_INVALID_REQUEST", 400, "window_start must be earlier than window_end")
    vacancy = opt_bool(b, "vacancy_attested", False)
    inspection_id = b.get("inspection_id")
    bbc = b.get("bed_bug_case_id")
    tech = get_or_404("technicians", technician_id, "Technician")
    if inspection_id is not None:
        get_or_404("inspections", inspection_id, "Inspection")
    if bbc is not None:
        get_or_404("cases", bbc, "BedBugCase")
    if not tech["active"]:
        err("ERR_INVALID_REQUEST", 400, "Technician is not active")
    contract = _treatment_gates(u, technician_id, ttype, pest_type, vacancy, ws, we)
    refresh_spend(contract)
    if contract["spent_cents"] + COST_ESTIMATE[ttype] > contract["monthly_budget_cents"]:
        err("ERR_CONTRACT_BUDGET_EXCEEDED", 422,
            "Treatment would exceed the contract monthly budget")
    t = new_rec()
    t.update({"unit_id": u["id"], "technician_id": technician_id,
              "inspection_id": inspection_id, "bed_bug_case_id": bbc,
              "pest_type": pest_type, "treatment_type": ttype,
              "window_start": ws, "window_end": we,
              "planned_minutes": int((we - ws).total_seconds() // 60),
              "vacancy_attested": vacancy, "status": "SCHEDULED",
              "prep_notified_at": None, "prep_acknowledged_at": None,
              "reschedule_count": 0, "actual_minutes": None})
    db["treatments"][t["id"]] = t
    recompute_booked(tech)
    if bbc is not None:
        case = db["cases"][bbc]
        if case["status"] in ("OPEN", "REOPENED"):
            case["status"] = "TREATING"
            touch(case)
    return ok(ser_treatment(t), 201)


@app.get("/pest/units/<uid_>/treatments")
def list_unit_treatments(uid_):
    role, uid = authenticate()
    require(role, "ProgramAdmin", "PropertyManager", "Technician", "Resident")
    u = get_or_404("units", uid_, "Unit")
    if role == "Resident":
        r = acting_resident(uid)
        if r["unit_id"] != u["id"]:
            err("ERR_FORBIDDEN_ROLE", 403, "Resident does not belong to this unit")
    recs = [t for t in db["treatments"].values() if t["unit_id"] == u["id"]]
    status = request.args.get("status")
    if status is not None:
        recs = [t for t in recs if t["status"] == status]
    return page_out(recs, ser_treatment)


@app.get("/pest/treatments/<tid>")
def get_treatment(tid):
    role, uid = authenticate()
    require(role, "ProgramAdmin", "PropertyManager", "Technician", "Resident",
            "BillingClerk", "ComplianceOfficer")
    t = get_or_404("treatments", tid, "Treatment")
    if role == "Technician" and t["technician_id"] != uid:
        err("ERR_FORBIDDEN_ROLE", 403, "Treatment is not assigned to this technician")
    if role == "Resident":
        r = acting_resident(uid)
        if r["unit_id"] != t["unit_id"]:
            err("ERR_FORBIDDEN_ROLE", 403, "Treatment does not belong to this unit")
    return ok(ser_treatment(t))


@app.get("/pest/bed-bug-cases/<cid>/treatments")
def list_case_treatments(cid):
    role, uid = authenticate()
    require(role, "ProgramAdmin", "PropertyManager", "Technician")
    get_or_404("cases", cid, "BedBugCase")
    return page_out([t for t in db["treatments"].values()
                     if t.get("bed_bug_case_id") == cid], ser_treatment)


@app.get("/pest/treatments/<tid>/chargebacks")
def list_treatment_chargebacks(tid):
    role, uid = authenticate()
    require(role, "ProgramAdmin", "PropertyManager", "BillingClerk")
    t = get_or_404("treatments", tid, "Treatment")
    return page_out([c for c in db["chargebacks"].values()
                     if c.get("source_treatment_id") == t["id"]], ser_chargeback)


@app.post("/pest/treatments/<tid>/notify-prep")
def notify_prep(tid):
    role, uid = authenticate()
    require(role, "PropertyManager")
    t = get_or_404("treatments", tid, "Treatment")
    body()
    if t["status"] in ("COMPLETED", "CANCELLED"):
        err("ERR_ALREADY_TERMINAL", 409, "Treatment is in a terminal state")
    if t["status"] != "SCHEDULED":
        err("ERR_INVALID_STATE", 409, "notify-prep requires status SCHEDULED")
    if t["window_start"] < now() + timedelta(hours=PREP_NOTICE_HOURS):
        err("ERR_PREP_NOTICE_TOO_LATE", 422, "Prep notice requires at least 48 hours")
    t["prep_notified_at"] = now()
    t["status"] = "PREP_NOTIFIED"
    touch(t)
    return ok(ser_treatment(t))


@app.post("/pest/treatments/<tid>/acknowledge-prep")
def acknowledge_prep(tid):
    role, uid = authenticate()
    require(role, "Resident")
    t = get_or_404("treatments", tid, "Treatment")
    r = acting_resident(uid)
    if r["unit_id"] != t["unit_id"]:
        err("ERR_FORBIDDEN_ROLE", 403, "Treatment does not belong to this resident's unit")
    body()
    if t["status"] in ("COMPLETED", "CANCELLED"):
        err("ERR_ALREADY_TERMINAL", 409, "Treatment is in a terminal state")
    if t["status"] != "PREP_NOTIFIED":
        err("ERR_INVALID_STATE", 409, "acknowledge-prep requires status PREP_NOTIFIED")
    if t["prep_acknowledged_at"] is not None:
        err("ERR_INVALID_STATE", 409, "Prep has already been acknowledged")
    t["prep_acknowledged_at"] = now()
    touch(t)
    return ok(ser_treatment(t))


@app.post("/pest/treatments/<tid>/verify-prep")
def verify_prep(tid):
    role, uid = authenticate()
    require(role, "PropertyManager")
    t = get_or_404("treatments", tid, "Treatment")
    b = body()
    compliant = as_bool(need(b, "compliant"), "compliant")
    if t["status"] in ("COMPLETED", "CANCELLED"):
        err("ERR_ALREADY_TERMINAL", 409, "Treatment is in a terminal state")
    if t["status"] == "SCHEDULED":
        err("ERR_PREP_NOT_NOTIFIED", 409, "Prep has not been notified")
    if t["status"] != "PREP_NOTIFIED":
        err("ERR_INVALID_STATE", 409, "verify-prep requires status PREP_NOTIFIED")
    if t["prep_acknowledged_at"] is None:
        err("ERR_PREP_NOT_ACKNOWLEDGED", 409, "Prep has not been acknowledged")
    if compliant:
        t["status"] = "PREP_VERIFIED"
        touch(t)
    else:
        t["status"] = "NON_COMPLIANT"
        touch(t)
        unit = db["units"][t["unit_id"]]
        lease = None
        for l in sorted([l for l in db["leases"].values() if l["unit_id"] == unit["id"]],
                        key=lambda l: l["seq"]):
            lazy_lease(l)
            if l["status"] == "ACTIVE" and l["pest_addendum_signed"]:
                lease = l
                break
        if lease is not None:
            create_chargeback(lease, "NON_COMPLIANCE_FEE", assessed_by="system",
                              source_treatment_id=t["id"])
            recompute_balance(lease)
    return ok(ser_treatment(t))


@app.post("/pest/treatments/<tid>/reschedule")
def reschedule_treatment(tid):
    role, uid = authenticate()
    require(role, "PropertyManager")
    t = get_or_404("treatments", tid, "Treatment")
    b = body()
    ws = parse_dt(need(b, "window_start"), "window_start")
    we = parse_dt(need(b, "window_end"), "window_end")
    if ws >= we:
        err("ERR_INVALID_REQUEST", 400, "window_start must be earlier than window_end")
    expv = as_int(need(b, "expected_treatment_version"), "expected_treatment_version")
    unit = db["units"][t["unit_id"]]
    if t["status"] in ("COMPLETED", "CANCELLED"):
        err("ERR_ALREADY_TERMINAL", 409, "Treatment is in a terminal state")
    if t["status"] not in ("SCHEDULED", "NON_COMPLIANT"):
        err("ERR_INVALID_STATE", 409,
            "reschedule requires status SCHEDULED or NON_COMPLIANT")
    contract = active_contract(unit["property_id"])
    if contract is None:
        err("ERR_CONTRACT_NOT_ACTIVE", 409, "The property's contract is not ACTIVE")
    if expv != t["version"]:
        err("ERR_STALE_VERSION", 412, "Treatment version is stale")
    if t["treatment_type"] == "HEAT" and not t["vacancy_attested"]:
        err("ERR_HEAT_SAFETY_VIOLATION", 422, "HEAT treatment requires vacancy_attested")
    check_conflicts(unit, t["technician_id"], t["treatment_type"], ws, we,
                    exclude_id=t["id"])
    if t["reschedule_count"] >= RESCHEDULE_LIMIT:
        err("ERR_RESCHEDULE_LIMIT_EXCEEDED", 422, "Reschedule limit reached")
    from_non = t["status"] == "NON_COMPLIANT"
    t["window_start"] = ws
    t["window_end"] = we
    t["planned_minutes"] = int((we - ws).total_seconds() // 60)
    t["reschedule_count"] += 1
    if from_non:
        t["prep_notified_at"] = None
        t["prep_acknowledged_at"] = None
        t["status"] = "SCHEDULED"
    touch(t)
    tech = db["technicians"].get(t["technician_id"])
    if tech is not None:
        recompute_booked(tech)
    return ok(ser_treatment(t))


@app.post("/pest/treatments/<tid>/complete")
def complete_treatment(tid):
    role, uid = authenticate()
    require(role, "Technician")
    t = get_or_404("treatments", tid, "Treatment")
    tech = acting_technician(uid)
    if t["technician_id"] != tech["id"]:
        err("ERR_FORBIDDEN_ROLE", 403, "Treatment is not assigned to this technician")
    b = body()
    actual = as_int(need(b, "actual_minutes"), "actual_minutes", minv=1)
    if t["status"] in ("COMPLETED", "CANCELLED"):
        err("ERR_ALREADY_TERMINAL", 409, "Treatment is in a terminal state")
    if t["status"] != "PREP_VERIFIED":
        err("ERR_INVALID_STATE", 409, "complete requires status PREP_VERIFIED")
    t["actual_minutes"] = actual
    t["status"] = "COMPLETED"
    touch(t)
    unit = db["units"][t["unit_id"]]
    contract = latest_contract(unit["property_id"])
    if contract is not None:
        refresh_spend(contract)
        contract["spent_cents"] += COST_ESTIMATE[t["treatment_type"]]
        touch(contract)
    recompute_booked(tech)
    if t.get("bed_bug_case_id"):
        case = db["cases"].get(t["bed_bug_case_id"])
        if case is not None:
            maybe_case_monitoring(case)
    return ok(ser_treatment(t))


@app.post("/pest/treatments/<tid>/cancel")
def cancel_treatment(tid):
    role, uid = authenticate()
    require(role, "PropertyManager")
    t = get_or_404("treatments", tid, "Treatment")
    body()
    if t["status"] in ("COMPLETED", "CANCELLED"):
        err("ERR_ALREADY_TERMINAL", 409, "Treatment is in a terminal state")
    if t["status"] not in ("SCHEDULED", "PREP_NOTIFIED", "NON_COMPLIANT"):
        err("ERR_INVALID_STATE", 409, "Treatment cannot be cancelled from %s" % t["status"])
    t["status"] = "CANCELLED"
    touch(t)
    tech = db["technicians"].get(t["technician_id"])
    if tech is not None:
        recompute_booked(tech)
    return ok(ser_treatment(t))


# ============================================================================
# Bed bug cases & furniture disposals
# ============================================================================
@app.get("/pest/units/<uid_>/bed-bug-cases")
def list_unit_cases(uid_):
    role, uid = authenticate()
    require(role, "ProgramAdmin", "PropertyManager", "Resident")
    u = get_or_404("units", uid_, "Unit")
    if role == "Resident":
        r = acting_resident(uid)
        if r["unit_id"] != u["id"]:
            err("ERR_FORBIDDEN_ROLE", 403, "Resident does not belong to this unit")
    recs = [c for c in db["cases"].values() if c["unit_id"] == u["id"]]
    status = request.args.get("status")
    if status is not None:
        recs = [c for c in recs if c["status"] == status]
    return page_out(recs, ser_case)


@app.get("/pest/bed-bug-cases/<cid>")
def get_case(cid):
    role, uid = authenticate()
    require(role, "ProgramAdmin", "PropertyManager", "Technician", "Resident")
    c = get_or_404("cases", cid, "BedBugCase")
    if role == "Resident":
        r = acting_resident(uid)
        if r["unit_id"] != c["unit_id"]:
            err("ERR_FORBIDDEN_ROLE", 403, "Case does not belong to this unit")
    return ok(ser_case(c))


@app.get("/pest/bed-bug-cases/<cid>/chargebacks")
def list_case_chargebacks(cid):
    role, uid = authenticate()
    require(role, "ProgramAdmin", "PropertyManager", "BillingClerk")
    get_or_404("cases", cid, "BedBugCase")
    return page_out([c for c in db["chargebacks"].values()
                     if c.get("bed_bug_case_id") == cid], ser_chargeback)


@app.post("/pest/bed-bug-cases/<cid>/furniture-disposals")
def create_disposal(cid):
    role, uid = authenticate()
    require(role, "PropertyManager")
    case = get_or_404("cases", cid, "BedBugCase")
    b = body()
    item = as_str(need(b, "item_description"), "item_description")
    qty = as_int(need(b, "quantity"), "quantity", minv=1)
    d = new_rec()
    d.update({"bed_bug_case_id": case["id"], "item_description": item, "quantity": qty,
              "status": "PENDING", "verified_at": None})
    db["disposals"][d["id"]] = d
    return ok(ser_disposal(d), 201)


@app.get("/pest/bed-bug-cases/<cid>/furniture-disposals")
def list_disposals(cid):
    role, uid = authenticate()
    require(role, "ProgramAdmin", "PropertyManager", "Resident")
    case = get_or_404("cases", cid, "BedBugCase")
    if role == "Resident":
        r = acting_resident(uid)
        if r["unit_id"] != case["unit_id"]:
            err("ERR_FORBIDDEN_ROLE", 403, "Case does not belong to this unit")
    recs = [d for d in db["disposals"].values() if d["bed_bug_case_id"] == case["id"]]
    status = request.args.get("status")
    if status is not None:
        recs = [d for d in recs if d["status"] == status]
    return page_out(recs, ser_disposal)


@app.post("/pest/furniture-disposals/<did>/verify")
def verify_disposal(did):
    role, uid = authenticate()
    require(role, "PropertyManager")
    d = get_or_404("disposals", did, "FurnitureDisposal")
    b = body()
    verified = as_bool(need(b, "verified"), "verified")
    if d["status"] in ("VERIFIED", "REJECTED"):
        err("ERR_ALREADY_TERMINAL", 409, "Disposal is in a terminal state")
    if verified:
        d["status"] = "VERIFIED"
        d["verified_at"] = now()
        touch(d)
        case = db["cases"].get(d["bed_bug_case_id"])
        if case is not None:
            maybe_case_monitoring(case)
    else:
        d["status"] = "REJECTED"
        touch(d)
    return ok(ser_disposal(d))


@app.post("/pest/bed-bug-cases/<cid>/evaluate-clearance")
def evaluate_clearance(cid):
    role, uid = authenticate()
    require(role, "PropertyManager")
    case = get_or_404("cases", cid, "BedBugCase")
    body()
    if case["status"] == "CLEARED":
        err("ERR_ALREADY_TERMINAL", 409, "Case is in a terminal state")
    if case["status"] != "MONITORING":
        err("ERR_CASE_NOT_MONITORING", 409, "Case is not MONITORING")
    run = negative_run(case["id"])
    if len(run) < 2 or (run[-1] - run[-2]) < timedelta(days=14):
        err("ERR_CLEARANCE_CRITERIA_UNMET", 422, "Clearance criteria are not met")
    ds = [d for d in db["disposals"].values() if d["bed_bug_case_id"] == case["id"]]
    if any(d["status"] != "VERIFIED" for d in ds):
        err("ERR_DISPOSAL_UNVERIFIED", 422, "Not all disposals are VERIFIED")
    case["status"] = "CLEARED"
    case["cleared_at"] = now()
    case["consecutive_negative_count"] = len(run)
    touch(case)
    unit = db["units"][case["unit_id"]]
    recompute_pest_flag(unit)
    prop = db["properties"][unit["property_id"]]
    recompute_property(prop)
    return ok(ser_case(case))


# ============================================================================
# Chargebacks
# ============================================================================
@app.post("/pest/leases/<lid>/chargebacks")
def assess_chargeback(lid):
    role, uid = authenticate()
    require(role, "BillingClerk")
    lease = get_or_404("leases", lid, "Lease")
    lazy_lease(lease)
    b = body()
    kind = as_enum(need(b, "kind"), "kind", CHARGEBACK_KINDS)
    src = b.get("source_treatment_id")
    bbc = b.get("bed_bug_case_id")
    note = opt_str(b, "note")
    pic = opt_int(b, "planned_item_count", minv=1)
    if src is not None:
        if not isinstance(src, str):
            err("ERR_INVALID_REQUEST", 400, "source_treatment_id must be a string")
        get_or_404("treatments", src, "Treatment")
    if bbc is not None:
        if not isinstance(bbc, str):
            err("ERR_INVALID_REQUEST", 400, "bed_bug_case_id must be a string")
        get_or_404("cases", bbc, "BedBugCase")
    if lease["status"] != "ACTIVE":
        err("ERR_LEASE_NOT_ACTIVE", 409, "Lease is not ACTIVE")
    if not lease["pest_addendum_signed"]:
        err("ERR_LEASE_CLAUSE_MISSING", 422, "Lease has no signed pest addendum")
    if kind == "LATE_FEE":
        err("ERR_INVALID_REQUEST", 400, "LATE_FEE may not be assessed manually")
    if kind == "HEAT_SURCHARGE":
        unit = db["units"][lease["unit_id"]]
        contract = active_contract(unit["property_id"])
        if contract is None or contract["heat_treatment_included"]:
            err("ERR_INVALID_REQUEST", 400,
                "HEAT_SURCHARGE requires contract heat_treatment_included == false")
    if kind == "FURNITURE_DISPOSAL" and (bbc is None or pic is None):
        err("ERR_INVALID_REQUEST", 400,
            "FURNITURE_DISPOSAL requires bed_bug_case_id and planned_item_count")
    cb = create_chargeback(lease, kind, assessed_by=uid, source_treatment_id=src,
                           bed_bug_case_id=bbc, planned_item_count=pic, note=note)
    recompute_balance(lease)
    return ok(ser_chargeback(cb), 201)


@app.get("/pest/chargebacks/<cid>")
def get_chargeback(cid):
    role, uid = authenticate()
    require(role, "ProgramAdmin", "PropertyManager", "BillingClerk", "ComplianceOfficer",
            "Resident")
    c = get_or_404("chargebacks", cid, "Chargeback")
    if role == "Resident":
        r = acting_resident(uid)
        if r["lease_id"] != c["lease_id"]:
            err("ERR_FORBIDDEN_ROLE", 403, "Chargeback does not belong to this resident")
    return ok(ser_chargeback(c))


@app.post("/pest/chargebacks/<cid>/dispute")
def dispute_chargeback(cid):
    role, uid = authenticate()
    require(role, "Resident")
    c = get_or_404("chargebacks", cid, "Chargeback")
    r = acting_resident(uid)
    if r["lease_id"] != c["lease_id"]:
        err("ERR_FORBIDDEN_ROLE", 403, "Chargeback does not belong to this resident")
    b = body()
    reason = as_str(need(b, "reason"), "reason")
    if c["status"] in ("WAIVED", "PAID"):
        err("ERR_ALREADY_TERMINAL", 409, "Chargeback is in a terminal state")
    if c["status"] != "ASSESSED":
        err("ERR_INVALID_STATE", 409, "dispute requires status ASSESSED")
    if now() > c["assessed_at"] + timedelta(days=DISPUTE_WINDOW_DAYS):
        err("ERR_DISPUTE_WINDOW_EXPIRED", 422, "Dispute window has expired")
    c["status"] = "DISPUTED"
    c["disputed_at"] = now()
    c["dispute_reason"] = reason
    touch(c)
    recompute_balance(db["leases"][c["lease_id"]])
    return ok(ser_chargeback(c))


@app.post("/pest/chargebacks/<cid>/resolve-dispute")
def resolve_dispute(cid):
    role, uid = authenticate()
    require(role, "ComplianceOfficer")
    c = get_or_404("chargebacks", cid, "Chargeback")
    b = body()
    resolution = as_enum(need(b, "resolution"), "resolution", ("UPHELD", "WAIVED"))
    expv = as_int(need(b, "expected_chargeback_version"), "expected_chargeback_version")
    if c["status"] in ("WAIVED", "PAID"):
        err("ERR_ALREADY_TERMINAL", 409, "Chargeback is in a terminal state")
    if c["status"] != "DISPUTED":
        err("ERR_INVALID_STATE", 409, "resolve-dispute requires status DISPUTED")
    if expv != c["version"]:
        err("ERR_STALE_VERSION", 412, "Chargeback version is stale")
    if uid == c["assessed_by"]:
        err("ERR_SEGREGATION_OF_DUTIES", 403,
            "Resolver must differ from the assessing clerk")
    c["status"] = resolution
    c["resolved_by"] = uid
    c["resolution"] = resolution
    touch(c)
    recompute_balance(db["leases"][c["lease_id"]])
    return ok(ser_chargeback(c))


@app.post("/pest/chargebacks/<cid>/bill")
def bill_chargeback(cid):
    role, uid = authenticate()
    require(role, "BillingClerk")
    c = get_or_404("chargebacks", cid, "Chargeback")
    body()
    if c["status"] in ("WAIVED", "PAID"):
        err("ERR_ALREADY_TERMINAL", 409, "Chargeback is in a terminal state")
    if c["status"] not in ("ASSESSED", "UPHELD"):
        err("ERR_INVALID_STATE", 409, "bill requires status ASSESSED or UPHELD")
    c["final_amount_cents"] = compute_chargeback_amount(c, "final")
    c["billed_at"] = now()
    c["status"] = "BILLED"
    touch(c)
    recompute_balance(db["leases"][c["lease_id"]])
    return ok(ser_chargeback(c))


@app.post("/pest/chargebacks/<cid>/record-payment")
def record_payment(cid):
    role, uid = authenticate()
    require(role, "BillingClerk")
    c = get_or_404("chargebacks", cid, "Chargeback")
    b = body()
    amount = as_int(need(b, "amount_cents"), "amount_cents")
    if c["status"] in ("WAIVED", "PAID"):
        err("ERR_ALREADY_TERMINAL", 409, "Chargeback is in a terminal state")
    if c["status"] != "BILLED":
        err("ERR_INVALID_STATE", 409, "record-payment requires status BILLED")
    if amount != c["final_amount_cents"]:
        err("ERR_PAYMENT_AMOUNT_MISMATCH", 422,
            "amount_cents must equal final_amount_cents")
    c["status"] = "PAID"
    c["paid_at"] = now()
    touch(c)
    recompute_balance(db["leases"][c["lease_id"]])
    return ok(ser_chargeback(c))


# ============================================================================
# Claim packets
# ============================================================================
@app.post("/pest/properties/<pid>/claim-packets")
def create_packet(pid):
    role, uid = authenticate()
    require(role, "ComplianceOfficer")
    get_or_404("properties", pid, "Property")
    b = body()
    claim_reference = as_str(need(b, "claim_reference"), "claim_reference")
    refs = need(b, "references")
    if not isinstance(refs, list):
        err("ERR_INVALID_REQUEST", 400, "references must be an array")
    pinned = []
    for entry in refs:
        if not isinstance(entry, dict):
            err("ERR_INVALID_REQUEST", 400, "Each reference must be an object")
        etype = entry.get("entity_type")
        eid = entry.get("entity_id")
        if etype not in ("Inspection", "Treatment", "BedBugCase"):
            err("ERR_INVALID_REQUEST", 400, "Unknown entity_type: %s" % etype)
        if not isinstance(eid, str):
            err("ERR_INVALID_REQUEST", 400, "entity_id must be a string")
        target = lookup_entity(etype, eid)
        if target is None:
            err("ERR_NOT_FOUND", 404, "Referenced %s %s does not exist" % (etype, eid))
        pinned.append({"entity_type": etype, "entity_id": eid,
                       "version": target["version"]})
    p = new_rec()
    p.update({"property_id": pid, "claim_reference": claim_reference,
              "references": refs, "pinned_references": pinned, "status": "DRAFT",
              "finalized_at": None})
    db["packets"][p["id"]] = p
    return ok(ser_packet(p), 201)


@app.get("/pest/properties/<pid>/claim-packets")
def list_packets(pid):
    role, uid = authenticate()
    require(role, "ProgramAdmin", "PropertyManager", "ComplianceOfficer")
    get_or_404("properties", pid, "Property")
    return page_out([p for p in db["packets"].values() if p["property_id"] == pid],
                    ser_packet)


@app.get("/pest/claim-packets/<pid>")
def get_packet(pid):
    role, uid = authenticate()
    require(role, "ProgramAdmin", "ComplianceOfficer")
    p = get_or_404("packets", pid, "ClaimPacket")
    return ok(ser_packet(p))


@app.post("/pest/claim-packets/<pid>/finalize")
def finalize_packet(pid):
    role, uid = authenticate()
    require(role, "ComplianceOfficer")
    p = get_or_404("packets", pid, "ClaimPacket")
    body()
    if p["status"] in ("FINALIZED", "DISCARDED"):
        err("ERR_ALREADY_TERMINAL", 409, "Claim packet is in a terminal state")
    if p["status"] != "DRAFT":
        err("ERR_INVALID_STATE", 409, "finalize requires status DRAFT")
    for pin in p["pinned_references"]:
        target = lookup_entity(pin["entity_type"], pin["entity_id"])
        if target is None or target["version"] != pin["version"]:
            err("ERR_CLAIM_PACKET_STALE_REFERENCE", 409,
                "A pinned reference version is no longer current")
    for pin in p["pinned_references"]:
        if pin["entity_type"] == "Inspection":
            target = lookup_entity(pin["entity_type"], pin["entity_id"])
            if target["status"] != "COMPLETED":
                err("ERR_INSPECTION_NOT_COMPLETED", 409,
                    "Referenced inspection is not COMPLETED")
    p["status"] = "FINALIZED"
    p["finalized_at"] = now()
    touch(p)
    return ok(ser_packet(p))


@app.post("/pest/claim-packets/<pid>/discard")
def discard_packet(pid):
    role, uid = authenticate()
    require(role, "ComplianceOfficer")
    p = get_or_404("packets", pid, "ClaimPacket")
    body()
    if p["status"] in ("FINALIZED", "DISCARDED"):
        err("ERR_ALREADY_TERMINAL", 409, "Claim packet is in a terminal state")
    if p["status"] != "DRAFT":
        err("ERR_INVALID_STATE", 409, "discard requires status DRAFT")
    p["status"] = "DISCARDED"
    touch(p)
    return ok(ser_packet(p))


# ============================================================================
# Entry
# ============================================================================
if __name__ == "__main__":
    from werkzeug.serving import make_server

    _port = int(os.environ.get("PORT", "10000"))
    _bind_fd = os.environ.get("WERKZEUG_BIND_FD")
    if _bind_fd is not None:
        # Launched via server_launch.py: the socket is already bound and
        # listening — adopt it so the port never goes unbound on restart.
        _srv = make_server("0.0.0.0", _port, app, fd=int(_bind_fd))
    else:
        _srv = make_server("0.0.0.0", _port, app)
    _srv.serve_forever()
