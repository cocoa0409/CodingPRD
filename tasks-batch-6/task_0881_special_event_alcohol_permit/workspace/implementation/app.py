"""Special-Event Alcohol & Temporary Permit API (Expert PRD-bench task 0881)."""
import os
import uuid
import random
import string
import itertools
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP

from flask import Flask, request, jsonify

app = Flask(__name__)

# =============================================================================
# Constants
# =============================================================================
MIN_SUBMISSION_LEAD_DAYS = 14
DEPOSIT_CENTS = 20000
REQUIRED_AGENCIES = ["POLICE", "FIRE", "ALCOHOL_BOARD"]

BASE_PERMIT_FEE_CENTS = 5000
PER_ATTENDEE_SURCHARGE_CENTS = Decimal("37.5")
SALES_SURCHARGE_RATE = Decimal("0.0125")

ATTENDEES_PER_GUARD = 75
MIN_GUARDS = 2
LONG_EVENT_HOURS = 5
HIGH_OCCUPANCY_FRACTION = Decimal("0.90")

FINE_MINOR_CENTS = 2500
FINE_MAJOR_CENTS = 10000
FINE_CRITICAL_CENTS = 25000
REPEAT_MULTIPLIER = Decimal("1.5")

COVERAGE_TIER_1_CENTS = 100000000
COVERAGE_TIER_2_CENTS = 200000000
COVERAGE_TIER_3_CENTS = 500000000

CLEANUP_FEE_CENTS = 15000
INSPECTION_BUFFER_MINUTES = 60

AGENCY_ENUM = ["POLICE", "FIRE", "ALCOHOL_BOARD", "HEALTH"]
TRAINING_PROVIDER_ENUM = ["TIPS", "SERVSAFE_ALCOHOL", "STATE_APPROVED"]
SEVERITY_ENUM = ["MINOR", "MAJOR", "CRITICAL"]
DECISION_ENUM = ["APPROVE", "APPROVE_WITH_CONDITIONS", "REJECT"]
RESULT_ENUM = ["PASSED", "FAILED"]
RESOLVE_ENUM = ["UPHELD", "DISMISSED"]

ROLES = ["Applicant", "PermitClerk", "AgencyReviewer", "Inspector"]
READ_ROLES = ["Applicant", "PermitClerk", "AgencyReviewer", "Inspector"]

VENUE_ACTIVE_STATUSES = {"SUBMITTED", "UNDER_REVIEW", "REVISIONS_REQUESTED",
                         "APPROVED", "PERMIT_ISSUED"}

# =============================================================================
# In-memory store (empty at boot — never seeded)
# =============================================================================
venues = {}
inspectors = {}
applications = {}
servers = {}
insurance_policies = {}
security_plans = {}
agency_reviews = {}
inspections = {}
violations = {}
reports = {}
ledger_entries = {}

_seq = itertools.count(1)
_permit_seq = itertools.count(1000)

# Logical clock (business-time). Default at or before every default fixture date.
current_clock = None  # set in reset/startup


def _default_clock():
    return datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)


current_clock = _default_clock()


# =============================================================================
# Errors
# =============================================================================
class ApiError(Exception):
    def __init__(self, error_id, http_status, message=""):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# =============================================================================
# Helpers: time / ids / envelope
# =============================================================================
def now_iso():
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def new_id():
    return str(uuid.uuid4())


def req_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def make_meta(pagination=None):
    m = {"api_request_id": req_id(), "api_request_timestamp": now_iso()}
    if pagination:
        m.update(pagination)
    return m


def success(data, response_type="object", status=200, pagination=None):
    body = {"meta": make_meta(pagination), "response_type": response_type, "data": data}
    return jsonify(body), status


def serialize(obj):
    return {k: v for k, v in obj.items() if not k.startswith("_")}


def new_common(entity_type):
    ts = now_iso()
    return {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": next(_seq),
        "_type": entity_type,
    }


def touch(obj):
    obj["version"] += 1
    obj["updated_at"] = now_iso()


def parse_iso(s):
    if not isinstance(s, str):
        raise ValueError("not a string")
    t = s.strip()
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    dt = datetime.fromisoformat(t)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


# =============================================================================
# Auth / RBAC
# =============================================================================
def require_auth(allowed_roles):
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role:
        raise ApiError("ERR_UNAUTHENTICATED", 401, "Missing authentication headers")
    if role not in ROLES:
        raise ApiError("ERR_UNAUTHORIZED", 403, "Role not permitted")
    if role not in allowed_roles:
        raise ApiError("ERR_UNAUTHORIZED", 403, "Role not permitted for this operation")
    return user_id, role


# =============================================================================
# Body validation helpers
# =============================================================================
def get_body():
    return request.get_json(silent=True) or {}


def require_present(body, field):
    if field not in body or body[field] is None:
        raise ApiError("ERR_VALIDATION", 400, f"Missing required field: {field}")
    return body[field]


def require_int(body, field):
    v = require_present(body, field)
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError("ERR_VALIDATION", 400, f"Field {field} must be an integer")
    return v


def require_number(body, field):
    v = require_present(body, field)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ApiError("ERR_VALIDATION", 400, f"Field {field} must be a number")
    return v


def require_str(body, field):
    v = require_present(body, field)
    if not isinstance(v, str):
        raise ApiError("ERR_VALIDATION", 400, f"Field {field} must be a string")
    return v


def require_dt(body, field):
    v = require_str(body, field)
    try:
        dt = parse_iso(v)
    except Exception:
        raise ApiError("ERR_VALIDATION", 400, f"Field {field} must be ISO8601")
    return v, dt


def require_enum(body, field, allowed):
    v = require_present(body, field)
    if not isinstance(v, str):
        raise ApiError("ERR_VALIDATION", 400, f"Field {field} must be a string")
    if v not in allowed:
        raise ApiError("ERR_INVALID_ENUM", 422, f"Field {field} value not allowed")
    return v


def optional_bool(body, field, default):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if not isinstance(v, bool):
        raise ApiError("ERR_VALIDATION", 400, f"Field {field} must be a boolean")
    return v


def optional_int(body, field, default):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError("ERR_VALIDATION", 400, f"Field {field} must be an integer")
    return v


# =============================================================================
# Lookups
# =============================================================================
def get_or_404(store, ident, err_id):
    obj = store.get(ident)
    if obj is None:
        raise ApiError(err_id, 404, "Resource not found")
    return obj


# =============================================================================
# Ledger / balance
# =============================================================================
def append_ledger(application_id, entry_type, amount_cents, memo):
    entry = {
        "id": new_id(),
        "created_at": now_iso(),
        "_seq": next(_seq),
        "_type": "LedgerEntry",
        "application_id": application_id,
        "entry_type": entry_type,
        "amount_cents": amount_cents,
        "memo": memo,
    }
    ledger_entries[entry["id"]] = entry
    return entry


def app_ledger(application_id):
    return [e for e in ledger_entries.values() if e["application_id"] == application_id]


def recompute_balance(app_obj):
    total = sum(e["amount_cents"] for e in app_ledger(app_obj["id"]))
    app_obj["balance_due_cents"] = total


# =============================================================================
# Calculations
# =============================================================================
def rhu(value):
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def permit_fee(attendance, sales_cents):
    base_line = BASE_PERMIT_FEE_CENTS
    attendance_line = rhu(Decimal(attendance) * PER_ATTENDEE_SURCHARGE_CENTS)
    sales_line = rhu(Decimal(sales_cents) * SALES_SURCHARGE_RATE)
    return base_line + attendance_line + sales_line


def required_security_guards(app_obj, venue):
    attendance = app_obj["expected_attendance"]
    base_guards = (attendance + ATTENDEES_PER_GUARD - 1) // ATTENDEES_PER_GUARD
    duration_bonus = 1 if app_obj["alcohol_service_hours"] > LONG_EVENT_HOURS else 0
    # expected_attendance >= occupancy_limit * 0.90  (inclusive), integer-safe
    high_occ_bonus = 1 if attendance * 10 >= venue["occupancy_limit"] * 9 else 0
    return max(MIN_GUARDS, base_guards + duration_bonus + high_occ_bonus)


def required_insurance_coverage(attendance):
    if attendance < 100:
        return COVERAGE_TIER_1_CENTS
    elif attendance < 500:
        return COVERAGE_TIER_2_CENTS
    return COVERAGE_TIER_3_CENTS


def violation_base_fine(severity):
    return {"MINOR": FINE_MINOR_CENTS, "MAJOR": FINE_MAJOR_CENTS,
            "CRITICAL": FINE_CRITICAL_CENTS}[severity]


# =============================================================================
# Pagination
# =============================================================================
def paginate(items):
    items = sorted(items, key=lambda o: (o["created_at"], o["_seq"]))
    total = len(items)
    try:
        limit = int(request.args.get("limit", 10))
    except (TypeError, ValueError):
        limit = 10
    try:
        offset = int(request.args.get("offset", 0))
    except (TypeError, ValueError):
        offset = 0
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    page = items[offset:offset + limit]
    has_more = (offset + len(page)) < total
    pagination = {"limit": limit, "offset": offset,
                  "total_count": total, "has_more": has_more}
    return page, pagination


def list_response(items):
    page, pagination = paginate(items)
    data = [serialize(o) for o in page]
    return success(data, response_type="array", status=200, pagination=pagination)


# =============================================================================
# Error handler
# =============================================================================
@app.errorhandler(ApiError)
def handle_api_error(err):
    body = {
        "meta": make_meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


@app.errorhandler(404)
def handle_404(e):
    body = {
        "meta": make_meta(),
        "response_type": "error",
        "data": {"error_id": "ERR_NOT_FOUND", "message": "Route not found"},
    }
    return jsonify(body), 404


@app.errorhandler(405)
def handle_405(e):
    body = {
        "meta": make_meta(),
        "response_type": "error",
        "data": {"error_id": "ERR_METHOD_NOT_ALLOWED", "message": "Method not allowed"},
    }
    return jsonify(body), 405


@app.after_request
def add_conn_close(resp):
    resp.headers["Connection"] = "close"
    return resp


# =============================================================================
# Clock endpoint
# =============================================================================
@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    require_auth(READ_ROLES)
    body = get_body()
    _, dt = require_dt(body, "to_iso8601")
    global current_clock
    current_clock = dt
    return success({}, status=200)


# =============================================================================
# Venue
# =============================================================================
@app.route("/permits/venues", methods=["POST"])
def create_venue():
    require_auth(["PermitClerk"])
    body = get_body()
    name = require_str(body, "name")
    address = require_str(body, "address")
    occupancy_limit = require_int(body, "occupancy_limit")
    indoor = optional_bool(body, "indoor", True)
    v = new_common("Venue")
    v.update({"name": name, "address": address,
              "occupancy_limit": occupancy_limit, "indoor": indoor})
    venues[v["id"]] = v
    return success(serialize(v), status=201)


@app.route("/permits/venues/<vid>", methods=["GET"])
def get_venue(vid):
    require_auth(READ_ROLES)
    v = get_or_404(venues, vid, "ERR_VENUE_NOT_FOUND")
    return success(serialize(v), status=200)


# =============================================================================
# Inspector
# =============================================================================
@app.route("/permits/inspectors", methods=["POST"])
def create_inspector():
    require_auth(["PermitClerk"])
    body = get_body()
    name = require_str(body, "name")
    badge_number = require_str(body, "badge_number")
    agency = require_enum(body, "agency", AGENCY_ENUM)
    ins = new_common("Inspector")
    ins.update({"name": name, "badge_number": badge_number, "agency": agency})
    inspectors[ins["id"]] = ins
    return success(serialize(ins), status=201)


@app.route("/permits/inspectors/<iid>", methods=["GET"])
def get_inspector(iid):
    require_auth(READ_ROLES)
    ins = get_or_404(inspectors, iid, "ERR_INSPECTOR_NOT_FOUND")
    return success(serialize(ins), status=200)


# =============================================================================
# PermitApplication
# =============================================================================
@app.route("/permits/applications", methods=["POST"])
def create_application():
    require_auth(["Applicant"])
    body = get_body()
    venue_id = require_str(body, "venue_id")
    organizer_name = require_str(body, "organizer_name")
    event_name = require_str(body, "event_name")
    event_start_raw, event_start_dt = require_dt(body, "event_start")
    event_end_raw, event_end_dt = require_dt(body, "event_end")
    alcohol_service_hours = require_number(body, "alcohol_service_hours")
    expected_attendance = require_int(body, "expected_attendance")
    requested_sales_limit_cents = require_int(body, "requested_sales_limit_cents")

    get_or_404(venues, venue_id, "ERR_VENUE_NOT_FOUND")

    if not (event_end_dt > event_start_dt):
        raise ApiError("ERR_INVALID_DATE_RANGE", 400, "event_end must be after event_start")

    a = new_common("PermitApplication")
    a.update({
        "venue_id": venue_id,
        "organizer_name": organizer_name,
        "event_name": event_name,
        "event_start": event_start_raw,
        "event_end": event_end_raw,
        "alcohol_service_hours": alcohol_service_hours,
        "expected_attendance": expected_attendance,
        "requested_sales_limit_cents": requested_sales_limit_cents,
        "status": "DRAFT",
        "permit_fee_cents": None,
        "fee_basis": None,
        "deposit_cents": None,
        "balance_due_cents": 0,
        "deposit_status": "NONE",
        "pending_review_count": 0,
        "approved_review_count": 0,
        "rejected_review_count": 0,
        "total_review_count": 0,
        "has_conditions": False,
        "permit_number": None,
    })
    applications[a["id"]] = a
    return success(serialize(a), status=201)


@app.route("/permits/applications", methods=["GET"])
def list_applications():
    require_auth(READ_ROLES)
    items = list(applications.values())
    vid = request.args.get("venue_id")
    if vid is not None:
        items = [a for a in items if a["venue_id"] == vid]
    status = request.args.get("status")
    if status is not None:
        items = [a for a in items if a["status"] == status]
    return list_response(items)


@app.route("/permits/applications/<aid>", methods=["GET"])
def get_application(aid):
    require_auth(READ_ROLES)
    a = get_or_404(applications, aid, "ERR_APPLICATION_NOT_FOUND")
    return success(serialize(a), status=200)


def app_children(store, application_id):
    return [o for o in store.values() if o.get("application_id") == application_id]


@app.route("/permits/applications/<aid>/submit", methods=["POST"])
def submit_application(aid):
    require_auth(["Applicant"])
    a = get_or_404(applications, aid, "ERR_APPLICATION_NOT_FOUND")
    if a["status"] != "DRAFT":
        raise ApiError("ERR_APPLICATION_NOT_DRAFT", 409, "Application is not DRAFT")

    event_start_dt = parse_iso(a["event_start"])
    event_end_dt = parse_iso(a["event_end"])
    # 1. date coherence
    if not (event_end_dt > event_start_dt):
        raise ApiError("ERR_INVALID_DATE_RANGE", 400, "event_end must be after event_start")
    # 2. required documents
    has_server = len(app_children(servers, aid)) >= 1
    has_insurance = len(app_children(insurance_policies, aid)) >= 1
    has_security = len(app_children(security_plans, aid)) >= 1
    if not (has_server and has_insurance and has_security):
        raise ApiError("ERR_MISSING_REQUIRED_DOCUMENTS", 422, "Missing required documents")
    # 3. attendance <= occupancy
    venue = venues.get(a["venue_id"])
    if venue is not None and a["expected_attendance"] > venue["occupancy_limit"]:
        raise ApiError("ERR_VALIDATION", 400, "expected_attendance exceeds venue occupancy_limit")
    # 4. submission lead time
    threshold = event_start_dt - timedelta(days=MIN_SUBMISSION_LEAD_DAYS)
    if current_clock > threshold:
        raise ApiError("ERR_SUBMISSION_TOO_LATE", 409, "Submission too late")
    # 5. venue not double-booked (half-open overlap)
    for other in applications.values():
        if other["id"] == aid:
            continue
        if other["venue_id"] != a["venue_id"]:
            continue
        if other["status"] not in VENUE_ACTIVE_STATUSES:
            continue
        os_dt = parse_iso(other["event_start"])
        oe_dt = parse_iso(other["event_end"])
        if event_start_dt < oe_dt and os_dt < event_end_dt:
            raise ApiError("ERR_VENUE_DOUBLE_BOOKED", 409, "Venue already booked")

    # side effects
    fee = permit_fee(a["expected_attendance"], a["requested_sales_limit_cents"])
    a["permit_fee_cents"] = fee
    a["fee_basis"] = "ESTIMATED"
    a["deposit_cents"] = DEPOSIT_CENTS
    append_ledger(aid, "FEE", fee, "Estimated permit fee at submission")
    append_ledger(aid, "DEPOSIT", DEPOSIT_CENTS, "Refundable security deposit")
    recompute_balance(a)
    if venue is not None:
        for plan in app_children(security_plans, aid):
            plan["required_guard_count"] = required_security_guards(a, venue)
            touch(plan)
    a["status"] = "SUBMITTED"
    touch(a)
    return success(serialize(a), status=200)


@app.route("/permits/applications/<aid>/open-review", methods=["POST"])
def open_review(aid):
    require_auth(["PermitClerk"])
    a = get_or_404(applications, aid, "ERR_APPLICATION_NOT_FOUND")
    if a["status"] != "SUBMITTED":
        raise ApiError("ERR_APPLICATION_NOT_SUBMITTED", 409, "Application is not SUBMITTED")
    for agency in REQUIRED_AGENCIES:
        r = new_common("AgencyReview")
        r.update({
            "application_id": aid,
            "agency": agency,
            "status": "PENDING",
            "conditions": None,
            "recorded_by": None,
        })
        agency_reviews[r["id"]] = r
    a["total_review_count"] = len(REQUIRED_AGENCIES)
    a["pending_review_count"] = len(REQUIRED_AGENCIES)
    a["approved_review_count"] = 0
    a["rejected_review_count"] = 0
    a["status"] = "UNDER_REVIEW"
    touch(a)
    return success(serialize(a), status=200)


@app.route("/permits/applications/<aid>/request-revisions", methods=["POST"])
def request_revisions(aid):
    require_auth(["PermitClerk"])
    a = get_or_404(applications, aid, "ERR_APPLICATION_NOT_FOUND")
    if a["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_APPLICATION_NOT_UNDER_REVIEW", 409, "Application is not UNDER_REVIEW")
    for r in app_children(agency_reviews, aid):
        if r["status"] != "PENDING":
            r["status"] = "PENDING"
            r["conditions"] = None
            r["recorded_by"] = None
            touch(r)
    a["pending_review_count"] = a["total_review_count"]
    a["approved_review_count"] = 0
    a["rejected_review_count"] = 0
    a["has_conditions"] = False
    a["status"] = "REVISIONS_REQUESTED"
    touch(a)
    return success(serialize(a), status=200)


@app.route("/permits/applications/<aid>/resubmit", methods=["POST"])
def resubmit_application(aid):
    require_auth(["Applicant"])
    a = get_or_404(applications, aid, "ERR_APPLICATION_NOT_FOUND")
    if a["status"] != "REVISIONS_REQUESTED":
        raise ApiError("ERR_INVALID_STATE", 409, "Application is not REVISIONS_REQUESTED")
    a["status"] = "UNDER_REVIEW"
    touch(a)
    return success(serialize(a), status=200)


@app.route("/permits/applications/<aid>/approve", methods=["POST"])
def approve_application(aid):
    user_id, _ = require_auth(["PermitClerk"])
    a = get_or_404(applications, aid, "ERR_APPLICATION_NOT_FOUND")
    if a["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_APPLICATION_NOT_UNDER_REVIEW", 409, "Application is not UNDER_REVIEW")
    if a["approved_review_count"] != a["total_review_count"]:
        raise ApiError("ERR_REVIEWS_NOT_ALL_APPROVED", 409, "Not all reviews approved")
    app_servers = app_children(servers, aid)
    if not all(s["status"] == "VERIFIED" for s in app_servers):
        raise ApiError("ERR_SERVERS_NOT_ALL_VERIFIED", 409, "Not all servers verified")
    if not any(p["status"] == "ACCEPTED" for p in app_children(insurance_policies, aid)):
        raise ApiError("ERR_INSURANCE_NOT_ACCEPTED", 409, "No accepted insurance policy")
    if not any(p["status"] == "APPROVED" for p in app_children(security_plans, aid)):
        raise ApiError("ERR_SECURITY_PLAN_NOT_APPROVED", 409, "No approved security plan")
    for r in app_children(agency_reviews, aid):
        if r["recorded_by"] is not None and r["recorded_by"] == user_id:
            raise ApiError("ERR_SEGREGATION_OF_DUTIES", 409, "Approver acted as reviewer")
    a["status"] = "APPROVED"
    touch(a)
    return success(serialize(a), status=200)


@app.route("/permits/applications/<aid>/deny", methods=["POST"])
def deny_application(aid):
    require_auth(["PermitClerk"])
    a = get_or_404(applications, aid, "ERR_APPLICATION_NOT_FOUND")
    if a["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_APPLICATION_NOT_UNDER_REVIEW", 409, "Application is not UNDER_REVIEW")
    if a["rejected_review_count"] < 1:
        raise ApiError("ERR_NO_REJECTED_REVIEW", 409, "No rejected review")
    for e in list(app_ledger(aid)):
        if e["entry_type"] == "PAYMENT":
            append_ledger(aid, "REFUND", -e["amount_cents"], "Refund on denial")
    recompute_balance(a)
    a["deposit_status"] = "NONE"
    a["status"] = "DENIED"
    touch(a)
    return success(serialize(a), status=200)


@app.route("/permits/applications/<aid>/issue-permit", methods=["POST"])
def issue_permit(aid):
    require_auth(["PermitClerk"])
    a = get_or_404(applications, aid, "ERR_APPLICATION_NOT_FOUND")
    if a["status"] != "APPROVED":
        raise ApiError("ERR_APPLICATION_NOT_APPROVED", 409, "Application is not APPROVED")
    if not any(i["result"] == "PASSED" for i in app_children(inspections, aid)):
        raise ApiError("ERR_INSPECTION_NOT_PASSED", 409, "No passed inspection")
    if a["balance_due_cents"] != 0:
        raise ApiError("ERR_OUTSTANDING_BALANCE", 402, "Outstanding balance")
    a["permit_number"] = f"PERMIT-{next(_permit_seq)}"
    a["deposit_status"] = "HELD"
    a["status"] = "PERMIT_ISSUED"
    touch(a)
    return success(serialize(a), status=200)


@app.route("/permits/applications/<aid>/close", methods=["POST"])
def close_application(aid):
    require_auth(["PermitClerk"])
    a = get_or_404(applications, aid, "ERR_APPLICATION_NOT_FOUND")
    if a["status"] != "EVENT_COMPLETE":
        raise ApiError("ERR_INVALID_STATE", 409, "Application is not EVENT_COMPLETE")
    for v in app_children(violations, aid):
        if v["status"] in ("ISSUED", "CONTESTED"):
            raise ApiError("ERR_UNRESOLVED_VIOLATIONS", 409, "Unresolved violations")

    report = next((r for r in reports.values() if r["application_id"] == aid), None)
    incident_count = report["incident_count"] if report else 0
    upheld_fines = sum(v["fine_cents"] for v in app_children(violations, aid)
                       if v["status"] == "UPHELD")
    deposit = a["deposit_cents"] or 0
    deductions = (CLEANUP_FEE_CENTS if incident_count > 0 else 0) + upheld_fines
    refund = max(0, deposit - deductions)
    forfeited = deposit - refund
    if refund > 0:
        append_ledger(aid, "DEPOSIT_REFUND", -refund, "Deposit refund at closeout")
    if forfeited > 0:
        append_ledger(aid, "DEPOSIT_FORFEIT", forfeited, "Deposit forfeit at closeout")
    a["deposit_status"] = "REFUNDED" if refund == deposit else "FORFEITED"
    if report:
        report["status"] = "ACCEPTED"
        touch(report)
    recompute_balance(a)
    a["status"] = "CLOSED"
    touch(a)
    return success(serialize(a), status=200)


@app.route("/permits/applications/<aid>/payments", methods=["POST"])
def record_payment(aid):
    require_auth(["Applicant"])
    a = get_or_404(applications, aid, "ERR_APPLICATION_NOT_FOUND")
    body = get_body()
    amount_cents = require_int(body, "amount_cents")
    expected_version = require_int(body, "expected_application_version")
    if expected_version != a["version"]:
        raise ApiError("ERR_STALE_VERSION", 412, "Stale application version")
    if amount_cents <= 0:
        raise ApiError("ERR_INVALID_PAYMENT_AMOUNT", 400, "Payment amount must be positive")
    entry = append_ledger(aid, "PAYMENT", -amount_cents, "Payment against balance")
    recompute_balance(a)
    touch(a)
    return success(serialize(entry), status=201)


# =============================================================================
# EventServer
# =============================================================================
@app.route("/permits/servers", methods=["POST"])
def create_server():
    require_auth(["Applicant"])
    body = get_body()
    application_id = require_str(body, "application_id")
    full_name = require_str(body, "full_name")
    cert_number = require_str(body, "cert_number")
    training_provider = require_enum(body, "training_provider", TRAINING_PROVIDER_ENUM)
    cert_issued_raw, _ = require_dt(body, "cert_issued_date")
    cert_expiry_raw, _ = require_dt(body, "cert_expiry_date")
    get_or_404(applications, application_id, "ERR_APPLICATION_NOT_FOUND")
    s = new_common("EventServer")
    s.update({
        "application_id": application_id,
        "full_name": full_name,
        "cert_number": cert_number,
        "training_provider": training_provider,
        "cert_issued_date": cert_issued_raw,
        "cert_expiry_date": cert_expiry_raw,
        "status": "PENDING",
    })
    servers[s["id"]] = s
    return success(serialize(s), status=201)


@app.route("/permits/servers", methods=["GET"])
def list_servers():
    require_auth(READ_ROLES)
    items = list(servers.values())
    application_id = request.args.get("application_id")
    if application_id is not None:
        items = [s for s in items if s["application_id"] == application_id]
    return list_response(items)


@app.route("/permits/servers/<sid>", methods=["GET"])
def get_server(sid):
    require_auth(READ_ROLES)
    s = get_or_404(servers, sid, "ERR_SERVER_NOT_FOUND")
    return success(serialize(s), status=200)


@app.route("/permits/servers/<sid>/verify", methods=["POST"])
def verify_server(sid):
    require_auth(["PermitClerk"])
    s = get_or_404(servers, sid, "ERR_SERVER_NOT_FOUND")
    if s["status"] != "PENDING":
        raise ApiError("ERR_INVALID_STATE", 409, "Server is not PENDING")
    a = applications.get(s["application_id"])
    event_end_dt = parse_iso(a["event_end"])
    cert_expiry_dt = parse_iso(s["cert_expiry_date"])
    if s["training_provider"] not in TRAINING_PROVIDER_ENUM or cert_expiry_dt < event_end_dt:
        raise ApiError("ERR_CERT_EXPIRED", 422, "Certificate expired before event end")
    s["status"] = "VERIFIED"
    touch(s)
    return success(serialize(s), status=200)


# =============================================================================
# InsurancePolicy
# =============================================================================
@app.route("/permits/insurance-policies", methods=["POST"])
def create_insurance():
    require_auth(["Applicant"])
    body = get_body()
    application_id = require_str(body, "application_id")
    insurer_name = require_str(body, "insurer_name")
    coverage_cents = require_int(body, "coverage_cents")
    effective_raw, _ = require_dt(body, "effective_date")
    expiry_raw, _ = require_dt(body, "expiry_date")
    get_or_404(applications, application_id, "ERR_APPLICATION_NOT_FOUND")
    p = new_common("InsurancePolicy")
    p.update({
        "application_id": application_id,
        "insurer_name": insurer_name,
        "coverage_cents": coverage_cents,
        "effective_date": effective_raw,
        "expiry_date": expiry_raw,
        "status": "SUBMITTED",
    })
    insurance_policies[p["id"]] = p
    return success(serialize(p), status=201)


@app.route("/permits/insurance-policies", methods=["GET"])
def list_insurance():
    require_auth(READ_ROLES)
    items = list(insurance_policies.values())
    application_id = request.args.get("application_id")
    if application_id is not None:
        items = [p for p in items if p["application_id"] == application_id]
    return list_response(items)


@app.route("/permits/insurance-policies/<pid>", methods=["GET"])
def get_insurance(pid):
    require_auth(READ_ROLES)
    p = get_or_404(insurance_policies, pid, "ERR_INSURANCE_NOT_FOUND")
    return success(serialize(p), status=200)


@app.route("/permits/insurance-policies/<pid>/accept", methods=["POST"])
def accept_insurance(pid):
    require_auth(["PermitClerk"])
    p = get_or_404(insurance_policies, pid, "ERR_INSURANCE_NOT_FOUND")
    if p["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE", 409, "Policy is not SUBMITTED")
    a = applications.get(p["application_id"])
    required = required_insurance_coverage(a["expected_attendance"])
    if p["coverage_cents"] < required:
        raise ApiError("ERR_INSUFFICIENT_COVERAGE", 422, "Insufficient coverage")
    effective_dt = parse_iso(p["effective_date"])
    expiry_dt = parse_iso(p["expiry_date"])
    event_start_dt = parse_iso(a["event_start"])
    event_end_dt = parse_iso(a["event_end"])
    if not (effective_dt <= event_start_dt and expiry_dt >= event_end_dt):
        raise ApiError("ERR_INSURANCE_DATES_INVALID", 422, "Policy dates do not span the event")
    p["status"] = "ACCEPTED"
    touch(p)
    return success(serialize(p), status=200)


# =============================================================================
# SecurityPlan
# =============================================================================
@app.route("/permits/security-plans", methods=["POST"])
def create_security_plan():
    require_auth(["Applicant"])
    body = get_body()
    application_id = require_str(body, "application_id")
    planned_guard_count = require_int(body, "planned_guard_count")
    plan_summary = require_str(body, "plan_summary")
    has_medical_staff = optional_bool(body, "has_medical_staff", False)
    a = get_or_404(applications, application_id, "ERR_APPLICATION_NOT_FOUND")
    p = new_common("SecurityPlan")
    p.update({
        "application_id": application_id,
        "planned_guard_count": planned_guard_count,
        "has_medical_staff": has_medical_staff,
        "plan_summary": plan_summary,
        "required_guard_count": None,
        "status": "SUBMITTED",
    })
    venue = venues.get(a["venue_id"])
    if venue is not None:
        p["required_guard_count"] = required_security_guards(a, venue)
    security_plans[p["id"]] = p
    return success(serialize(p), status=201)


@app.route("/permits/security-plans", methods=["GET"])
def list_security_plans():
    require_auth(READ_ROLES)
    items = list(security_plans.values())
    application_id = request.args.get("application_id")
    if application_id is not None:
        items = [p for p in items if p["application_id"] == application_id]
    return list_response(items)


@app.route("/permits/security-plans/<pid>", methods=["GET"])
def get_security_plan(pid):
    require_auth(READ_ROLES)
    p = get_or_404(security_plans, pid, "ERR_SECURITY_PLAN_NOT_FOUND")
    return success(serialize(p), status=200)


@app.route("/permits/security-plans/<pid>/approve", methods=["POST"])
def approve_security_plan(pid):
    require_auth(["PermitClerk"])
    p = get_or_404(security_plans, pid, "ERR_SECURITY_PLAN_NOT_FOUND")
    if p["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE", 409, "Plan is not SUBMITTED")
    a = applications.get(p["application_id"])
    venue = venues.get(a["venue_id"])
    required = required_security_guards(a, venue)
    if p["planned_guard_count"] < required:
        raise ApiError("ERR_INSUFFICIENT_SECURITY", 422, "Insufficient security guards")
    p["required_guard_count"] = required
    p["status"] = "APPROVED"
    touch(p)
    return success(serialize(p), status=200)


# =============================================================================
# AgencyReview
# =============================================================================
@app.route("/permits/agency-reviews", methods=["GET"])
def list_agency_reviews():
    require_auth(READ_ROLES)
    items = list(agency_reviews.values())
    application_id = request.args.get("application_id")
    if application_id is not None:
        items = [r for r in items if r["application_id"] == application_id]
    return list_response(items)


@app.route("/permits/agency-reviews/<rid>", methods=["GET"])
def get_agency_review(rid):
    require_auth(READ_ROLES)
    r = get_or_404(agency_reviews, rid, "ERR_AGENCY_REVIEW_NOT_FOUND")
    return success(serialize(r), status=200)


@app.route("/permits/agency-reviews/<rid>/decide", methods=["POST"])
def decide_agency_review(rid):
    user_id, _ = require_auth(["AgencyReviewer"])
    r = get_or_404(agency_reviews, rid, "ERR_AGENCY_REVIEW_NOT_FOUND")
    body = get_body()
    decision = require_enum(body, "decision", DECISION_ENUM)
    expected_version = require_int(body, "expected_application_version")
    a = applications.get(r["application_id"])
    # state
    if r["status"] != "PENDING":
        raise ApiError("ERR_REVIEW_NOT_PENDING", 409, "Review is not PENDING")
    if a["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_APPLICATION_NOT_UNDER_REVIEW", 409, "Application is not UNDER_REVIEW")
    # conditions (for APPROVE_WITH_CONDITIONS) before OCC
    conditions = body.get("conditions")
    if decision == "APPROVE_WITH_CONDITIONS":
        if not isinstance(conditions, str) or conditions.strip() == "":
            raise ApiError("ERR_VALIDATION", 400, "conditions required for APPROVE_WITH_CONDITIONS")
    # OCC
    if expected_version != a["version"]:
        raise ApiError("ERR_STALE_VERSION", 412, "Stale application version")

    if decision == "APPROVE":
        r["status"] = "APPROVED"
        r["recorded_by"] = user_id
        a["approved_review_count"] += 1
        a["pending_review_count"] -= 1
    elif decision == "APPROVE_WITH_CONDITIONS":
        r["status"] = "APPROVED_WITH_CONDITIONS"
        r["recorded_by"] = user_id
        r["conditions"] = conditions
        a["has_conditions"] = True
        a["approved_review_count"] += 1
        a["pending_review_count"] -= 1
    else:  # REJECT
        r["status"] = "REJECTED"
        r["recorded_by"] = user_id
        a["rejected_review_count"] += 1
        a["pending_review_count"] -= 1
    touch(r)
    touch(a)  # OCC-governed single version increment
    return success(serialize(r), status=200)


# =============================================================================
# Inspection
# =============================================================================
@app.route("/permits/inspections", methods=["POST"])
def create_inspection():
    require_auth(["PermitClerk"])
    body = get_body()
    application_id = require_str(body, "application_id")
    inspector_id = require_str(body, "inspector_id")
    start_raw, start_dt = require_dt(body, "scheduled_start")
    end_raw, end_dt = require_dt(body, "scheduled_end")
    get_or_404(applications, application_id, "ERR_APPLICATION_NOT_FOUND")
    get_or_404(inspectors, inspector_id, "ERR_INSPECTOR_NOT_FOUND")
    if not (end_dt > start_dt):
        raise ApiError("ERR_INVALID_DATE_RANGE", 400, "scheduled_end must be after scheduled_start")
    buffer = timedelta(minutes=INSPECTION_BUFFER_MINUTES)
    for other in inspections.values():
        if other["inspector_id"] != inspector_id:
            continue
        o_start = parse_iso(other["scheduled_start"])
        o_end = parse_iso(other["scheduled_end"])
        # conflict when the two windows are less than 60 minutes apart
        if (end_dt + buffer) > o_start and (o_end + buffer) > start_dt:
            raise ApiError("ERR_INSPECTOR_UNAVAILABLE", 409, "Inspector unavailable")
    i = new_common("Inspection")
    i.update({
        "application_id": application_id,
        "inspector_id": inspector_id,
        "scheduled_start": start_raw,
        "scheduled_end": end_raw,
        "result": "SCHEDULED",
        "recorded_by": None,
    })
    inspections[i["id"]] = i
    return success(serialize(i), status=201)


@app.route("/permits/inspections", methods=["GET"])
def list_inspections():
    require_auth(READ_ROLES)
    items = list(inspections.values())
    application_id = request.args.get("application_id")
    if application_id is not None:
        items = [i for i in items if i["application_id"] == application_id]
    inspector_id = request.args.get("inspector_id")
    if inspector_id is not None:
        items = [i for i in items if i["inspector_id"] == inspector_id]
    return list_response(items)


@app.route("/permits/inspections/<iid>", methods=["GET"])
def get_inspection(iid):
    require_auth(READ_ROLES)
    i = get_or_404(inspections, iid, "ERR_INSPECTION_NOT_FOUND")
    return success(serialize(i), status=200)


@app.route("/permits/inspections/<iid>/record-result", methods=["POST"])
def record_inspection_result(iid):
    user_id, _ = require_auth(["Inspector"])
    i = get_or_404(inspections, iid, "ERR_INSPECTION_NOT_FOUND")
    body = get_body()
    result = require_enum(body, "result", RESULT_ENUM)
    if i["result"] != "SCHEDULED":
        raise ApiError("ERR_INSPECTION_NOT_SCHEDULED", 409, "Inspection is not SCHEDULED")
    if user_id != i["inspector_id"]:
        raise ApiError("ERR_INSPECTOR_MISMATCH", 403, "Inspector does not match")
    i["recorded_by"] = user_id
    i["result"] = result
    touch(i)
    if result == "FAILED":
        a = applications.get(i["application_id"])
        if a is not None and a["status"] == "APPROVED":
            _revoke_on_failure(a)
    return success(serialize(i), status=200)


def _revoke_on_failure(a):
    aid = a["id"]
    total_paid = sum(-e["amount_cents"] for e in app_ledger(aid) if e["entry_type"] == "PAYMENT")
    deposit = a["deposit_cents"] or 0
    forfeit = min(deposit, max(0, total_paid))
    if forfeit > 0:
        append_ledger(aid, "DEPOSIT_FORFEIT", forfeit, "Deposit forfeited on revocation")
    a["deposit_status"] = "FORFEITED"
    recompute_balance(a)
    a["status"] = "REVOKED"
    touch(a)


# =============================================================================
# Violation
# =============================================================================
@app.route("/permits/violations", methods=["POST"])
def create_violation():
    require_auth(["Inspector"])
    body = get_body()
    inspection_id = require_str(body, "inspection_id")
    severity = require_enum(body, "severity", SEVERITY_ENUM)
    description = require_str(body, "description")
    insp = get_or_404(inspections, inspection_id, "ERR_INSPECTION_NOT_FOUND")
    application_id = insp["application_id"]
    base = violation_base_fine(severity)
    prior = [v for v in violations.values()
             if v["application_id"] == application_id
             and v["status"] in ("ISSUED", "CONTESTED", "UPHELD")]
    if len(prior) == 0:
        fine = base
        variant = "STANDARD"
    else:
        fine = rhu(Decimal(base) * REPEAT_MULTIPLIER)
        variant = "REPEAT"
    v = new_common("Violation")
    v.update({
        "inspection_id": inspection_id,
        "application_id": application_id,
        "severity": severity,
        "description": description,
        "fine_cents": fine,
        "penalty_variant": variant,
        "status": "ISSUED",
    })
    violations[v["id"]] = v
    append_ledger(application_id, "FINE", fine, f"Fine for {severity} violation")
    a = applications.get(application_id)
    if a is not None:
        recompute_balance(a)
        touch(a)
    return success(serialize(v), status=201)


@app.route("/permits/violations", methods=["GET"])
def list_violations():
    require_auth(READ_ROLES)
    items = list(violations.values())
    inspection_id = request.args.get("inspection_id")
    if inspection_id is not None:
        items = [v for v in items if v["inspection_id"] == inspection_id]
    return list_response(items)


@app.route("/permits/violations/<vid>", methods=["GET"])
def get_violation(vid):
    require_auth(READ_ROLES)
    v = get_or_404(violations, vid, "ERR_VIOLATION_NOT_FOUND")
    return success(serialize(v), status=200)


@app.route("/permits/violations/<vid>/contest", methods=["POST"])
def contest_violation(vid):
    require_auth(["Applicant"])
    v = get_or_404(violations, vid, "ERR_VIOLATION_NOT_FOUND")
    if v["status"] != "ISSUED":
        raise ApiError("ERR_VIOLATION_NOT_CONTESTABLE", 409, "Violation is not contestable")
    v["status"] = "CONTESTED"
    touch(v)
    return success(serialize(v), status=200)


@app.route("/permits/violations/<vid>/resolve", methods=["POST"])
def resolve_violation(vid):
    require_auth(["PermitClerk"])
    v = get_or_404(violations, vid, "ERR_VIOLATION_NOT_FOUND")
    if v["status"] != "CONTESTED":
        raise ApiError("ERR_INVALID_STATE", 409, "Violation is not CONTESTED")
    body = get_body()
    decision = require_enum(body, "decision", RESOLVE_ENUM)
    if decision == "UPHELD":
        v["status"] = "UPHELD"
    else:
        v["status"] = "DISMISSED"
        append_ledger(v["application_id"], "FINE_REVERSAL", -v["fine_cents"],
                      "Fine reversal on dismissal")
        a = applications.get(v["application_id"])
        if a is not None:
            recompute_balance(a)
            touch(a)
    touch(v)
    return success(serialize(v), status=200)


# =============================================================================
# LedgerEntry
# =============================================================================
@app.route("/permits/ledger-entries", methods=["GET"])
def list_ledger_entries():
    require_auth(READ_ROLES)
    items = list(ledger_entries.values())
    application_id = request.args.get("application_id")
    if application_id is not None:
        items = [e for e in items if e["application_id"] == application_id]
    return list_response(items)


@app.route("/permits/ledger-entries/<eid>", methods=["GET"])
def get_ledger_entry(eid):
    require_auth(READ_ROLES)
    e = ledger_entries.get(eid)
    if e is None:
        raise ApiError("ERR_LEDGER_ENTRY_NOT_FOUND", 404, "Ledger entry not found")
    return success(serialize(e), status=200)


# =============================================================================
# PostEventReport
# =============================================================================
@app.route("/permits/reports", methods=["POST"])
def create_report():
    require_auth(["Applicant"])
    body = get_body()
    application_id = require_str(body, "application_id")
    actual_attendance = require_int(body, "actual_attendance")
    gross_sales_cents = require_int(body, "gross_sales_cents")
    incident_count = optional_int(body, "incident_count", 0)
    a = get_or_404(applications, application_id, "ERR_APPLICATION_NOT_FOUND")
    if a["status"] != "PERMIT_ISSUED":
        raise ApiError("ERR_INVALID_STATE", 409, "Application is not PERMIT_ISSUED")
    event_end_dt = parse_iso(a["event_end"])
    if current_clock < event_end_dt:
        raise ApiError("ERR_EVENT_NOT_ENDED", 409, "Event has not ended")

    reconciled = permit_fee(actual_attendance, gross_sales_cents)
    rep = new_common("PostEventReport")
    rep.update({
        "application_id": application_id,
        "actual_attendance": actual_attendance,
        "gross_sales_cents": gross_sales_cents,
        "incident_count": incident_count,
        "reconciled_fee_cents": reconciled,
        "status": "FILED",
    })
    reports[rep["id"]] = rep

    previous_fee = a["permit_fee_cents"] or 0
    delta = reconciled - previous_fee
    a["permit_fee_cents"] = reconciled
    a["fee_basis"] = "RECONCILED"
    append_ledger(application_id, "FEE_ADJUSTMENT", delta, "Fee reconciliation from actuals")
    recompute_balance(a)
    a["status"] = "EVENT_COMPLETE"
    touch(a)
    return success(serialize(rep), status=201)


@app.route("/permits/reports", methods=["GET"])
def list_reports():
    require_auth(READ_ROLES)
    items = list(reports.values())
    application_id = request.args.get("application_id")
    if application_id is not None:
        items = [r for r in items if r["application_id"] == application_id]
    return list_response(items)


@app.route("/permits/reports/<rid>", methods=["GET"])
def get_report(rid):
    require_auth(READ_ROLES)
    r = get_or_404(reports, rid, "ERR_REPORT_NOT_FOUND")
    return success(serialize(r), status=200)


# =============================================================================
# Entrypoint
# =============================================================================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)
