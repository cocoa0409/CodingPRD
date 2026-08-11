"""Core primitives: logical clock, store, envelope, auth, validation, calculations.

All behavior here traces to PRD.md sections 2 and 3 and SCAFFOLD.yaml.
"""
import math
import random
import string
import uuid
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import jsonify, request

# --------------------------------------------------------------------------
# Logical clock (PRD 2.8): boots at 2026-05-01T00:00:00Z, never reads wall clock.
# --------------------------------------------------------------------------
CLOCK = {"now": datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)}


def now():
    return CLOCK["now"]


def iso(dt):
    """ISO 8601 UTC with three fractional digits (PRD 2.5)."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def parse_dt(value, field):
    if not isinstance(value, str):
        fail("ERR_INVALID_REQUEST", 400, "Field '%s' must be an ISO 8601 datetime string" % field)
    s = value.strip()
    if s.endswith(("Z", "z")):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        fail("ERR_INVALID_REQUEST", 400, "Field '%s' is not a valid ISO 8601 datetime" % field)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def whole_days(earlier, later):
    """Whole calendar days between two instants (floor)."""
    return math.floor((later - earlier).total_seconds() / 86400.0)


# --------------------------------------------------------------------------
# Errors (PRD 5 catalogue)
# --------------------------------------------------------------------------
class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


def fail(error_id, http_status, message):
    raise ApiError(error_id, http_status, message)


# --------------------------------------------------------------------------
# Response envelope (PRD 2.2)
# --------------------------------------------------------------------------
def req_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def meta():
    return {"api_request_id": req_id(), "api_request_timestamp": iso(now())}


def ok_object(data, code=200):
    return jsonify({"meta": meta(), "response_type": "object", "data": data}), code


def ok_list(items, limit, offset, total_count, code=200):
    m = meta()
    m["limit"] = limit
    m["offset"] = offset
    m["total_count"] = total_count
    m["has_more"] = (offset + len(items)) < total_count
    return jsonify({"meta": m, "response_type": "array", "data": items}), code


def error_body(error_id, message):
    return {"meta": meta(), "response_type": "error",
            "data": {"error_id": error_id, "message": message}}


# --------------------------------------------------------------------------
# In-memory store (fresh per process; no seeding)
# --------------------------------------------------------------------------
STORE = {
    "programs": {},
    "students": {},
    "agreements": {},
    "policies": {},
    "fleets": {},
    "units": {},
    "assignments": {},
    "reports": {},
    "fees": {},
    "loaners": {},
    "events": {},
    "sweeps": {},
}
SEQ = {"n": 0}


def next_seq():
    SEQ["n"] += 1
    return SEQ["n"]


def new_id():
    return str(uuid.uuid4())


def base_record(with_version=True):
    rec = {"id": new_id(), "_seq": next_seq(), "created_at": now()}
    if with_version:
        rec["updated_at"] = rec["created_at"]
        rec["version"] = 1
    return rec


def touch(rec):
    """Every mutation bumps updated_at and version (PRD 2.5)."""
    if "version" in rec:
        rec["updated_at"] = now()
        rec["version"] += 1


# --------------------------------------------------------------------------
# Auth (PRD 2.1) and RBAC
# --------------------------------------------------------------------------
ROLES = {"DistrictAdmin", "Registrar", "SiteTechnician", "Family"}


def auth(allowed_roles):
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        fail("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER", 400,
             "X-User-ID and X-User-Role headers are required and role must be recognized")
    if role not in allowed_roles:
        fail("ERR_UNAUTHORIZED", 403, "Role %s is not permitted to invoke this endpoint" % role)
    return uid, role


def family_path_scope(student_id, uid, role):
    """Family callers may only touch their own student (PRD 2.1)."""
    if role == "Family" and student_id != uid:
        fail("ERR_UNAUTHORIZED", 403, "Family callers are scoped to their own student")


def family_resource_scope(owner_student_id, uid, role):
    if role == "Family" and owner_student_id != uid:
        fail("ERR_UNAUTHORIZED", 403, "Family callers are scoped to their own student")


# --------------------------------------------------------------------------
# Request shape helpers (PRD 2.10: malformed body -> ERR_INVALID_REQUEST,
# evaluated before the numbered validation sequence)
# --------------------------------------------------------------------------
def body():
    if not request.data:
        return {}
    b = request.get_json(silent=True)
    if not isinstance(b, dict):
        fail("ERR_INVALID_REQUEST", 400, "Request body must be a JSON object")
    return b


def _present(b, name):
    return name in b and b[name] is not None


def req_str(b, name):
    if not _present(b, name):
        fail("ERR_INVALID_REQUEST", 400, "Required field '%s' is missing" % name)
    if not isinstance(b[name], str):
        fail("ERR_INVALID_REQUEST", 400, "Field '%s' must be a string" % name)
    return b[name]


def opt_str(b, name, default=None):
    if not _present(b, name):
        return default
    if not isinstance(b[name], str):
        fail("ERR_INVALID_REQUEST", 400, "Field '%s' must be a string" % name)
    return b[name]


def _is_int(v):
    if isinstance(v, bool):
        return False
    if isinstance(v, int):
        return True
    if isinstance(v, float) and v.is_integer():
        return True
    return False


def req_int(b, name, minimum=None, maximum=None):
    if not _present(b, name):
        fail("ERR_INVALID_REQUEST", 400, "Required field '%s' is missing" % name)
    return _int_val(b[name], name, minimum, maximum)


def opt_int(b, name, default=None, minimum=None, maximum=None):
    if not _present(b, name):
        return default
    return _int_val(b[name], name, minimum, maximum)


def _int_val(v, name, minimum, maximum):
    if not _is_int(v):
        fail("ERR_INVALID_REQUEST", 400, "Field '%s' must be an integer" % name)
    v = int(v)
    if minimum is not None and v < minimum:
        fail("ERR_INVALID_REQUEST", 400, "Field '%s' must be >= %s" % (name, minimum))
    if maximum is not None and v > maximum:
        fail("ERR_INVALID_REQUEST", 400, "Field '%s' must be <= %s" % (name, maximum))
    return v


def opt_bool(b, name, default=None):
    if not _present(b, name):
        return default
    if not isinstance(b[name], bool):
        fail("ERR_INVALID_REQUEST", 400, "Field '%s' must be a boolean" % name)
    return b[name]


def opt_num(b, name, default=None):
    if not _present(b, name):
        return default
    v = b[name]
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        fail("ERR_INVALID_REQUEST", 400, "Field '%s' must be a number" % name)
    return v


def req_enum(b, name, choices):
    v = req_str(b, name)
    if v not in choices:
        fail("ERR_INVALID_REQUEST", 400, "Field '%s' must be one of %s" % (name, sorted(choices)))
    return v


def opt_enum(b, name, choices, default=None):
    if not _present(b, name):
        return default
    return req_enum(b, name, choices)


def req_dt(b, name):
    if not _present(b, name):
        fail("ERR_INVALID_REQUEST", 400, "Required field '%s' is missing" % name)
    return parse_dt(b[name], name)


OCC_FIELDS = {"expected_student_version", "expected_asset_unit_version", "expected_program_version"}


def reject_stray_occ(b, allowed=None):
    """PRD 2.7: endpoints not listed do not accept a version field at all."""
    for f in OCC_FIELDS:
        if f != allowed and f in b:
            fail("ERR_INVALID_REQUEST", 400, "Field '%s' is not accepted by this endpoint" % f)


def check_occ(b, field, current_version):
    """Priority-4 concurrency check (PRD 2.7 / 2.10)."""
    expected = req_int(b, field)
    if expected != current_version:
        fail("ERR_STALE_VERSION", 412,
             "%s does not match the current version" % field)


# --------------------------------------------------------------------------
# Pagination (PRD 2.3): limit default 10 min 1 max 100; offset default 0;
# default sort created_at ascending.
# --------------------------------------------------------------------------
def page_params():
    limit = request.args.get("limit")
    offset = request.args.get("offset")
    if limit is None:
        limit = 10
    else:
        try:
            limit = int(limit)
        except (TypeError, ValueError):
            fail("ERR_INVALID_REQUEST", 400, "limit must be an integer")
        limit = max(1, min(100, limit))
    if offset is None:
        offset = 0
    else:
        try:
            offset = int(offset)
        except (TypeError, ValueError):
            fail("ERR_INVALID_REQUEST", 400, "offset must be an integer")
        offset = max(0, offset)
    return limit, offset


def list_response(records, serializer):
    records = sorted(records, key=lambda r: r["_seq"])
    limit, offset = page_params()
    total = len(records)
    page = records[offset:offset + limit]
    return ok_list([serializer(r) for r in page], limit, offset, total)


# --------------------------------------------------------------------------
# Entity lookups with left-to-right 404 resolution (PRD 2.4)
# --------------------------------------------------------------------------
def get_program(prog_id):
    rec = STORE["programs"].get(prog_id)
    if rec is None:
        fail("ERR_PROGRAM_NOT_FOUND", 404, "Program %s does not exist" % prog_id)
    return rec


def get_fleet(fleet_id, prog=None):
    rec = STORE["fleets"].get(fleet_id)
    if rec is None or (prog is not None and rec["program_id"] != prog["id"]):
        fail("ERR_FLEET_NOT_FOUND", 404, "Fleet %s does not exist" % fleet_id)
    return rec


def get_unit(asset_id, prog=None):
    rec = STORE["units"].get(asset_id)
    if rec is None:
        fail("ERR_ASSET_NOT_FOUND", 404, "Asset unit %s does not exist" % asset_id)
    if prog is not None:
        fleet = STORE["fleets"].get(rec["fleet_id"])
        if fleet is None or fleet["program_id"] != prog["id"]:
            fail("ERR_ASSET_NOT_FOUND", 404, "Asset unit %s does not exist" % asset_id)
    return rec


def get_student(student_id, prog=None):
    rec = STORE["students"].get(student_id)
    if rec is None or (prog is not None and rec["program_id"] != prog["id"]):
        fail("ERR_STUDENT_NOT_FOUND", 404, "Student %s does not exist" % student_id)
    return rec


def get_assignment(assignment_id, student=None):
    rec = STORE["assignments"].get(assignment_id)
    if rec is None or (student is not None and rec["student_account_id"] != student["id"]):
        fail("ERR_ASSIGNMENT_NOT_FOUND", 404, "Assignment %s does not exist" % assignment_id)
    return rec


def get_report(report_id, assignment=None):
    rec = STORE["reports"].get(report_id)
    if rec is None or (assignment is not None and rec["assignment_id"] != assignment["id"]):
        fail("ERR_DAMAGE_REPORT_NOT_FOUND", 404, "Damage report %s does not exist" % report_id)
    return rec


def get_fee(fee_id, student=None):
    rec = STORE["fees"].get(fee_id)
    if rec is None or (student is not None and rec["student_account_id"] != student["id"]):
        fail("ERR_FEE_NOT_FOUND", 404, "Fee %s does not exist" % fee_id)
    return rec


def get_loaner(checkout_id, student=None):
    rec = STORE["loaners"].get(checkout_id)
    if rec is None or (student is not None and rec["student_account_id"] != student["id"]):
        fail("ERR_LOANER_CHECKOUT_NOT_FOUND", 404, "Loaner checkout %s does not exist" % checkout_id)
    return rec


def get_policy(policy_id, student=None):
    rec = STORE["policies"].get(policy_id)
    if rec is None or (student is not None and rec["student_account_id"] != student["id"]):
        fail("ERR_POLICY_NOT_FOUND", 404, "Insurance policy %s does not exist" % policy_id)
    return rec


def get_sweep(sweep_id, prog=None):
    rec = STORE["sweeps"].get(sweep_id)
    if rec is None or (prog is not None and rec["program_id"] != prog["id"]):
        fail("ERR_SWEEP_NOT_FOUND", 404, "Audit sweep %s does not exist" % sweep_id)
    return rec


def get_agreement(agreement_id):
    rec = STORE["agreements"].get(agreement_id)
    if rec is None:
        fail("ERR_AGREEMENT_NOT_FOUND", 404, "Family agreement %s does not exist" % agreement_id)
    return rec


def get_event(event_id):
    rec = STORE["events"].get(event_id)
    if rec is None:
        fail("ERR_EVENT_NOT_FOUND", 404, "Lifecycle event %s does not exist" % event_id)
    return rec


def agreement_for_student(student_id):
    for a in STORE["agreements"].values():
        if a["student_account_id"] == student_id:
            return a
    return None


def fleet_of(unit):
    return STORE["fleets"][unit["fleet_id"]]


# --------------------------------------------------------------------------
# Calculations (SCAFFOLD 1.3, PRD 3.x)
# --------------------------------------------------------------------------
GRADE_RANK = {"A": 0, "B": 1, "C": 2, "D": 3, "F": 4}

SEVERITY = {"COSMETIC": Decimal("0.10"), "FUNCTIONAL": Decimal("0.45"),
            "LIQUID": Decimal("0.80"), "SCREEN": Decimal("0.55"),
            "LOSS": Decimal("1.00"), "THEFT": Decimal("1.00")}
CONDITION_DISCOUNT = {"A": Decimal("0.00"), "B": Decimal("0.10"), "C": Decimal("0.25"),
                      "D": Decimal("0.50"), "F": Decimal("0.75")}

DAILY_T1 = 100
DAILY_T2 = 250
DAILY_T3 = 500
SUSPEND_THRESHOLD_CENTS = 10000
WAIVER_RATE = Decimal("0.80")


def rhu(dec):
    """Round half up to whole cents (PRD 2.6)."""
    return int(Decimal(dec).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def months_in_service(unit):
    fleet = fleet_of(unit)
    ulm = fleet["useful_life_months"]
    days = (now() - fleet["in_service_date"]).total_seconds() / 86400.0
    months = math.floor(days / 30.44)
    if months < 0:
        months = 0
    if ulm > 0:
        months = min(months, ulm)
    return months


def depreciated_value(unit):
    fleet = fleet_of(unit)
    salvage = fleet["salvage_value_cents"]
    replacement = fleet["unit_replacement_cost_cents"]
    # Forced variants at end of life (PRD 3.9)
    if unit["lifecycle_status"] in ("DISPOSED", "DONATED"):
        return salvage
    if unit["lifecycle_status"] == "WRITTEN_OFF":
        return 0
    ulm = fleet["useful_life_months"]
    if ulm <= 0:
        return salvage
    months = months_in_service(unit)
    depreciable = replacement - salvage
    accrued = rhu(Decimal(months) * Decimal(depreciable) / Decimal(ulm))
    return max(salvage, replacement - accrued)


def provisional_fee(unit, damage_category):
    fleet = fleet_of(unit)
    base = Decimal(fleet["unit_replacement_cost_cents"])
    raw = base * SEVERITY[damage_category] * (Decimal("1") - CONDITION_DISCOUNT[unit["condition_grade"]])
    return rhu(raw)


def late_fee_cents(days_late, free_lunch_eligible):
    if days_late <= 0:
        return 0
    tier1 = min(days_late, 7)
    tier2 = min(max(days_late - 7, 0), 23)
    tier3 = max(days_late - 30, 0)
    fee = tier1 * DAILY_T1 + tier2 * DAILY_T2 + tier3 * DAILY_T3
    if free_lunch_eligible:
        fee = rhu(Decimal(fee) * Decimal("0.50"))
    return fee


def recompute_posture(student):
    """SCAFFOLD financial_posture_derivation; runs on every fee mutation."""
    outstanding = 0
    non_return_open = False
    for fee in STORE["fees"].values():
        if fee["student_account_id"] != student["id"]:
            continue
        if fee["status"] in ("ASSESSED", "APPEALED"):
            outstanding += fee["amount_cents"] - fee["waived_cents"] - fee["paid_cents"]
            if fee["fee_type"] == "NON_RETURN" and fee["status"] == "ASSESSED":
                non_return_open = True
    student["outstanding_balance_cents"] = outstanding
    if non_return_open:
        posture = "SUSPENDED"
    elif outstanding == 0:
        posture = "CLEAR"
    elif outstanding < SUSPEND_THRESHOLD_CENTS:
        posture = "FEES_OUTSTANDING"
    else:
        posture = "SUSPENDED"
    student["financial_posture"] = posture
    touch(student)


def create_fee(student, fee_type, amount_cents, source_damage_report_id=None, policy_id=None):
    fee = base_record()
    fee.update({
        "student_account_id": student["id"],
        "source_damage_report_id": source_damage_report_id,
        "fee_type": fee_type,
        "amount_cents": amount_cents,
        "waived_cents": 0,
        "paid_cents": 0,
        "status": "ASSESSED",
        "_insurance_policy_id": policy_id,
    })
    STORE["fees"][fee["id"]] = fee
    recompute_posture(student)
    return fee


# --------------------------------------------------------------------------
# Lifecycle events (PRD 2.9) and unit transitions
# --------------------------------------------------------------------------
def append_event(unit, event_type, payload=None, supersedes_event_id=None):
    ev = base_record(with_version=False)
    ev.update({
        "asset_unit_id": unit["id"],
        "event_type": event_type,
        "supersedes_event_id": supersedes_event_id,
        "event_payload": payload if payload is not None else {},
        "occurred_at": now(),
    })
    STORE["events"][ev["id"]] = ev
    return ev


def set_lifecycle(unit, status, event_type=None, payload=None, supersedes_event_id=None,
                  relocated=False):
    unit["lifecycle_status"] = status
    # assigned_to_student_id carries a value only while the unit is out
    # (DEPLOYED); it is null at every other point in the unit's life.
    if status != "DEPLOYED":
        unit["assigned_to_student_id"] = None
    # An unaccounted unit that physically resurfaces through a return flow
    # counts as re-located for audit reconciliation (PRD 3.9).
    if relocated:
        unit["_unaccounted"] = False
    if event_type:
        append_event(unit, event_type, payload, supersedes_event_id)
    touch(unit)


# --------------------------------------------------------------------------
# Scheduled (nightly-scan) transitions, fired when the clock advances (PRD 2.8)
# --------------------------------------------------------------------------
def run_scheduled_scans():
    for a in STORE["assignments"].values():
        if a["status"] == "ACTIVE" and a["checked_in_at"] is None and a["expected_return_date"] < now():
            a["status"] = "OVERDUE"
            touch(a)
    for c in STORE["loaners"].values():
        if c["status"] == "OPEN" and c["returned_at"] is None:
            if (now() - c["created_at"]).total_seconds() > c["max_loaner_days"] * 86400:
                c["status"] = "OVERDUE"
                touch(c)


# --------------------------------------------------------------------------
# Serializers (entity field lists from SCAFFOLD 1.1; internal keys excluded)
# --------------------------------------------------------------------------
def program_json(p):
    return {
        "id": p["id"],
        "program_name": p["program_name"],
        "school_year": p["school_year"],
        "loaner_pool_threshold_pct": p["loaner_pool_threshold_pct"],
        "status": p["status"],
        "created_at": iso(p["created_at"]),
        "updated_at": iso(p["updated_at"]),
        "version": p["version"],
    }


def student_json(s):
    return {
        "id": s["id"],
        "program_id": s["program_id"],
        "student_external_id": s["student_external_id"],
        "full_name": s["full_name"],
        "grade_level": s["grade_level"],
        "free_lunch_eligible": s["free_lunch_eligible"],
        "family_agreement_status": s["family_agreement_status"],
        "insurance_enrolled": s["insurance_enrolled"],
        "financial_posture": s["financial_posture"],
        "outstanding_balance_cents": s["outstanding_balance_cents"],
        "lifetime_damage_count": s["lifetime_damage_count"],
        "status": s["status"],
        "created_at": iso(s["created_at"]),
        "updated_at": iso(s["updated_at"]),
        "version": s["version"],
    }


def agreement_json(a):
    return {
        "id": a["id"],
        "student_account_id": a["student_account_id"],
        "acceptable_use_version": a["acceptable_use_version"],
        "signed_by_guardian_name": a["signed_by_guardian_name"],
        "signed_at": iso(a["signed_at"]),
        "signature_state": a["signature_state"],
        "created_at": iso(a["created_at"]),
    }


def policy_json(p):
    return {
        "id": p["id"],
        "student_account_id": p["student_account_id"],
        "premium_cents": p["premium_cents"],
        "deductible_cents": p["deductible_cents"],
        "coverage_cap_cents": p["coverage_cap_cents"],
        "academic_year": p["academic_year"],
        "status": p["status"],
        "created_at": iso(p["created_at"]),
        "updated_at": iso(p["updated_at"]),
        "version": p["version"],
    }


def fleet_json(f):
    return {
        "id": f["id"],
        "program_id": f["program_id"],
        "fleet_name": f["fleet_name"],
        "asset_class": f["asset_class"],
        "unit_replacement_cost_cents": f["unit_replacement_cost_cents"],
        "salvage_value_cents": f["salvage_value_cents"],
        "useful_life_months": f["useful_life_months"],
        "in_service_date": iso(f["in_service_date"]),
        "created_at": iso(f["created_at"]),
        "updated_at": iso(f["updated_at"]),
        "version": f["version"],
    }


def unit_json(u):
    return {
        "id": u["id"],
        "fleet_id": u["fleet_id"],
        "asset_tag_barcode": u["asset_tag_barcode"],
        "serial_number": u["serial_number"],
        "condition_grade": u["condition_grade"],
        "lifecycle_status": u["lifecycle_status"],
        "depreciated_value_cents": depreciated_value(u),
        "months_in_service": months_in_service(u),
        "assigned_to_student_id": u["assigned_to_student_id"],
        "created_at": iso(u["created_at"]),
        "updated_at": iso(u["updated_at"]),
        "version": u["version"],
    }


def assignment_json(a):
    return {
        "id": a["id"],
        "student_account_id": a["student_account_id"],
        "asset_unit_id": a["asset_unit_id"],
        "expected_return_date": iso(a["expected_return_date"]),
        "checked_out_at": iso(a["checked_out_at"]),
        "checked_in_at": iso(a["checked_in_at"]),
        "checkout_condition_grade": a["checkout_condition_grade"],
        "return_condition_grade": a["return_condition_grade"],
        "late_return_days": a["late_return_days"],
        "status": a["status"],
        "created_at": iso(a["created_at"]),
        "updated_at": iso(a["updated_at"]),
        "version": a["version"],
    }


def report_json(r):
    return {
        "id": r["id"],
        "assignment_id": r["assignment_id"],
        "reported_by_role": r["reported_by_role"],
        "damage_category": r["damage_category"],
        "observed_condition_grade": r["observed_condition_grade"],
        "provisional_fee_cents": r["provisional_fee_cents"],
        "final_fee_cents": r["final_fee_cents"],
        "status": r["status"],
        "created_at": iso(r["created_at"]),
        "updated_at": iso(r["updated_at"]),
        "version": r["version"],
    }


def fee_json(f):
    return {
        "id": f["id"],
        "student_account_id": f["student_account_id"],
        "source_damage_report_id": f["source_damage_report_id"],
        "fee_type": f["fee_type"],
        "amount_cents": f["amount_cents"],
        "waived_cents": f["waived_cents"],
        "paid_cents": f["paid_cents"],
        "status": f["status"],
        "created_at": iso(f["created_at"]),
        "updated_at": iso(f["updated_at"]),
        "version": f["version"],
    }


def loaner_json(c):
    return {
        "id": c["id"],
        "student_account_id": c["student_account_id"],
        "loaner_asset_unit_id": c["loaner_asset_unit_id"],
        "checkout_reason": c["checkout_reason"],
        "max_loaner_days": c["max_loaner_days"],
        "returned_at": iso(c["returned_at"]),
        "status": c["status"],
        "created_at": iso(c["created_at"]),
        "updated_at": iso(c["updated_at"]),
        "version": c["version"],
    }


def event_json(e):
    return {
        "id": e["id"],
        "asset_unit_id": e["asset_unit_id"],
        "event_type": e["event_type"],
        "supersedes_event_id": e["supersedes_event_id"],
        "event_payload": e["event_payload"],
        "occurred_at": iso(e["occurred_at"]),
        "created_at": iso(e["created_at"]),
    }


def sweep_json(s):
    return {
        "id": s["id"],
        "program_id": s["program_id"],
        "sweep_label": s["sweep_label"],
        "started_at": iso(s["started_at"]),
        "closed_at": iso(s["closed_at"]),
        "unaccounted_count": s["unaccounted_count"],
        "status": s["status"],
        "created_at": iso(s["created_at"]),
        "updated_at": iso(s["updated_at"]),
        "version": s["version"],
    }
