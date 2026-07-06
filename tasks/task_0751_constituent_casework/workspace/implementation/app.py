"""Constituent Casework API — Python + Flask, in-memory only.

Boots with an EMPTY store on every process start. No seeding. All state is
constructed by clients via the declared API surface.
"""
import os
import random
import string
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import Flask, request, jsonify

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
KNOWN_ROLES = {"OfficeAdmin", "Caseworker", "Constituent", "Anonymous"}
CATEGORIES = {"IMMIGRATION", "HEALTHCARE", "HOUSING", "TAX", "BENEFITS", "OTHER"}
CHAMBERS = {"HOUSE", "SENATE"}
PRIORITIES = {"LOW", "NORMAL", "HIGH", "URGENT"}
AGENCY_STATUSES = {"ACTIVE", "INACTIVE"}

DEFAULT_WINDOW_HOURS = {
    "IMMIGRATION": 168, "HEALTHCARE": 120, "HOUSING": 120,
    "TAX": 72, "BENEFITS": 96, "OTHER": 168,
}
PRIORITY_MULTIPLIER = {"LOW": 1.5, "NORMAL": 1.0, "HIGH": 0.5, "URGENT": 0.25}
CATEGORY_SURCHARGE_HOURS = {
    "IMMIGRATION": 24, "HEALTHCARE": 12, "HOUSING": 12,
    "TAX": 0, "BENEFITS": 0, "OTHER": 0,
}
MAX_WINDOW_HOURS = 720

PRIORITY_WEIGHT = {"LOW": 0.5, "NORMAL": 1.0, "HIGH": 2.0, "URGENT": 3.5}
RECENCY_BONUS = 1.25
DEFAULT_WINDOW_DAYS = 30

BASE_POSTAGE_CENTS = 55
PRINT_CENTS_PER_PAGE = 8

VENUE_BUFFER_MINUTES = 30

PAGE_LIMIT_DEFAULT = 10
PAGE_LIMIT_MIN = 1
PAGE_LIMIT_MAX = 100

CLOCK_DEFAULT = datetime(2026, 3, 1, 0, 0, 0, tzinfo=timezone.utc)

# ---------------------------------------------------------------------------
# In-memory store (empty on boot)
# ---------------------------------------------------------------------------
class DB:
    def __init__(self):
        self.reset()

    def reset(self):
        self.representatives = {}
        self.constituents = {}
        self.agencies = {}
        self.templates = {}
        self.cases = {}
        self.referrals = {}
        self.venues = {}
        self.events = {}
        self.registrations = {}
        self.newsletters = {}
        self.clock = CLOCK_DEFAULT
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


db = DB()


def now():
    return db.clock


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------
class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# ---------------------------------------------------------------------------
# Time / number helpers
# ---------------------------------------------------------------------------
def parse_iso(s):
    if not isinstance(s, str):
        raise ApiError("ERR_INVALID_REQUEST", 400, "invalid datetime")
    txt = s.strip()
    if txt.endswith("Z"):
        txt = txt[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(txt)
    except ValueError:
        raise ApiError("ERR_INVALID_REQUEST", 400, "invalid datetime: %s" % s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def iso(dt):
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    millis = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % millis


def round2(x):
    return float(Decimal(str(x)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def hours_between(a, b):
    return (a - b).total_seconds() / 3600.0


# ---------------------------------------------------------------------------
# Response envelope
# ---------------------------------------------------------------------------
def _request_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def _meta(extra=None):
    m = {
        "api_request_id": _request_id(),
        "api_request_timestamp": iso(datetime.now(timezone.utc)),
    }
    if extra:
        m.update(extra)
    return m


def ok(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def ok_list(items, page_meta):
    body = {"meta": _meta(page_meta), "response_type": "array", "data": items}
    return jsonify(body), 200


@app.errorhandler(ApiError)
def _handle_api_error(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


@app.errorhandler(404)
def _handle_404(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": "ERR_NOT_FOUND", "message": "resource not found"},
    }
    return jsonify(body), 404


@app.errorhandler(405)
def _handle_405(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": "ERR_METHOD_NOT_ALLOWED", "message": "method not allowed"},
    }
    return jsonify(body), 405


# ---------------------------------------------------------------------------
# Common record helpers
# ---------------------------------------------------------------------------
def base_record():
    ts = now()
    return {
        "id": str(uuid.uuid4()),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": db.next_seq(),
    }


def touch(rec):
    rec["updated_at"] = now()
    rec["version"] += 1


# ---------------------------------------------------------------------------
# Auth / body helpers
# ---------------------------------------------------------------------------
def get_role_uid():
    return request.headers.get("X-User-Role"), request.headers.get("X-User-ID")


def authenticate(allowed_roles, anon_exempt=False):
    role, uid = get_role_uid()
    if anon_exempt:
        if not role or role not in KNOWN_ROLES:
            role = "Anonymous"
    else:
        if not role or not uid or role not in KNOWN_ROLES:
            raise ApiError("ERR_UNAUTHENTICATED", 401, "missing or invalid auth headers")
    if role not in allowed_roles:
        raise ApiError("ERR_UNAUTHORIZED", 403, "role not permitted for this operation")
    return role, uid


def get_body():
    if request.method in ("POST", "PATCH", "PUT"):
        body = request.get_json(silent=True)
        if body is None:
            body = {}
        if not isinstance(body, dict):
            raise ApiError("ERR_INVALID_REQUEST", 400, "body must be a JSON object")
        return body
    return {}


def require_str(body, field):
    if field not in body or not isinstance(body[field], str) or body[field] == "":
        raise ApiError("ERR_INVALID_REQUEST", 400, "missing/invalid field: %s" % field)
    return body[field]


def opt_str(body, field):
    if field not in body or body[field] is None:
        return None
    if not isinstance(body[field], str):
        raise ApiError("ERR_INVALID_REQUEST", 400, "invalid field: %s" % field)
    return body[field]


def require_enum(body, field, allowed):
    v = require_str(body, field)
    if v not in allowed:
        raise ApiError("ERR_INVALID_REQUEST", 400, "invalid enum value for %s" % field)
    return v


def require_int(body, field, minimum=None):
    if field not in body or isinstance(body[field], bool) or not isinstance(body[field], int):
        raise ApiError("ERR_INVALID_REQUEST", 400, "missing/invalid integer: %s" % field)
    if minimum is not None and body[field] < minimum:
        raise ApiError("ERR_INVALID_REQUEST", 400, "value out of range: %s" % field)
    return body[field]


def opt_bool(body, field, default=False):
    if field not in body or body[field] is None:
        return default
    if not isinstance(body[field], bool):
        raise ApiError("ERR_INVALID_REQUEST", 400, "invalid boolean: %s" % field)
    return body[field]


# ---------------------------------------------------------------------------
# Pagination / listing
# ---------------------------------------------------------------------------
def parse_pagination():
    args = request.args
    try:
        limit = int(args.get("limit", PAGE_LIMIT_DEFAULT))
    except (TypeError, ValueError):
        limit = PAGE_LIMIT_DEFAULT
    try:
        offset = int(args.get("offset", 0))
    except (TypeError, ValueError):
        offset = 0
    if limit < PAGE_LIMIT_MIN:
        limit = PAGE_LIMIT_MIN
    if limit > PAGE_LIMIT_MAX:
        limit = PAGE_LIMIT_MAX
    if offset < 0:
        offset = 0
    return limit, offset


def list_response(all_items, serializer):
    all_items = sorted(all_items, key=lambda r: (r["created_at"], r["_seq"]))
    limit, offset = parse_pagination()
    total = len(all_items)
    page = all_items[offset:offset + limit]
    has_more = (offset + limit) < total
    meta = {"limit": limit, "offset": offset, "total_count": total, "has_more": has_more}
    return ok_list([serializer(r) for r in page], meta)


# ---------------------------------------------------------------------------
# Existence fetchers (raise type-specific 404)
# ---------------------------------------------------------------------------
def fetch(store, key, err_id):
    rec = store.get(key)
    if rec is None:
        raise ApiError(err_id, 404, "resource not found")
    return rec


def get_representative(i):
    return fetch(db.representatives, i, "ERR_REPRESENTATIVE_NOT_FOUND")


def get_constituent(i):
    return fetch(db.constituents, i, "ERR_CONSTITUENT_NOT_FOUND")


def get_agency(i):
    return fetch(db.agencies, i, "ERR_AGENCY_NOT_FOUND")


def get_template(i):
    return fetch(db.templates, i, "ERR_TEMPLATE_NOT_FOUND")


def get_case(i):
    return fetch(db.cases, i, "ERR_CASE_NOT_FOUND")


def get_referral(i):
    return fetch(db.referrals, i, "ERR_REFERRAL_NOT_FOUND")


def get_venue(i):
    return fetch(db.venues, i, "ERR_VENUE_NOT_FOUND")


def get_event(i):
    return fetch(db.events, i, "ERR_EVENT_NOT_FOUND")


def get_registration(i):
    return fetch(db.registrations, i, "ERR_REGISTRATION_NOT_FOUND")


def get_newsletter(i):
    return fetch(db.newsletters, i, "ERR_NEWSLETTER_NOT_FOUND")


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------
def _common(rec):
    return {
        "id": rec["id"],
        "created_at": iso(rec["created_at"]),
        "updated_at": iso(rec["updated_at"]),
        "version": rec["version"],
    }


def ser_representative(r):
    out = _common(r)
    out.update({
        "full_name": r["full_name"], "chamber": r["chamber"],
        "district_name": r["district_name"], "state_code": r["state_code"],
        "office_email": r["office_email"],
    })
    return out


def ser_constituent(r):
    out = _common(r)
    out.update({
        "representative_id": r["representative_id"], "full_name": r["full_name"],
        "email": r["email"], "address": r["address"], "phone": r["phone"],
        "contact_consent": r["contact_consent"],
        "data_sharing_consent": r["data_sharing_consent"],
        "status": r["status"], "upcoming_event_count": r["upcoming_event_count"],
    })
    return out


def ser_agency(r):
    out = _common(r)
    out.update({
        "name": r["name"], "jurisdiction": r["jurisdiction"],
        "status": r["status"], "open_referral_count": r["open_referral_count"],
    })
    return out


def ser_template(r):
    out = _common(r)
    out.update({
        "category": r["category"], "body_template": r["body_template"],
        "response_window_hours": r["response_window_hours"], "active": r["active"],
    })
    return out


def compute_elapsed(c):
    """Returns (gross, net, breached) computed against the current clock."""
    if c["triaged_at"] is None:
        return 0, 0, False
    if c["status"] in ("RESOLVED", "CLOSED"):
        reference_end = c["resolved_at"] if c["resolved_at"] is not None else now()
    else:
        reference_end = now()
    gross = hours_between(reference_end, c["triaged_at"])
    if c["status"] in ("AWAITING_CONSTITUENT", "AWAITING_AGENCY") and c["paused_since"] is not None:
        open_pause = hours_between(now(), c["paused_since"])
    else:
        open_pause = 0
    net = gross - c["cumulative_paused_hours"] - open_pause
    gross_r = round2(gross)
    net_r = round2(net)
    eff = c["effective_window_hours"]
    breached = (eff is not None) and (net_r > eff)
    return gross_r, net_r, breached


def ser_case(c):
    out = _common(c)
    gross, net, breached = compute_elapsed(c)
    out.update({
        "constituent_id": c["constituent_id"],
        "representative_id": c["representative_id"],
        "subject": c["subject"], "description": c["description"],
        "category": c["category"], "priority": c["priority"], "status": c["status"],
        "assigned_template_id": c["assigned_template_id"],
        "assignee_staff_id": c["assignee_staff_id"],
        "response_window_hours": c["response_window_hours"],
        "effective_window_hours": c["effective_window_hours"],
        "provisional_due_at": iso(c["provisional_due_at"]),
        "final_due_at": iso(c["final_due_at"]),
        "cumulative_paused_hours": round2(c["cumulative_paused_hours"]),
        "paused_since": iso(c["paused_since"]),
        "gross_elapsed_hours": gross,
        "net_elapsed_hours": net,
        "breached": breached,
        "last_agency_outcome": c["last_agency_outcome"],
        "reject_count": c["reject_count"],
        "triaged_at": iso(c["triaged_at"]),
        "resolved_at": iso(c["resolved_at"]),
        "closed_at": iso(c["closed_at"]),
        "withdrawn_at": iso(c["withdrawn_at"]),
    })
    return out


def ser_referral(r):
    out = _common(r)
    out.update({
        "case_id": r["case_id"], "agency_id": r["agency_id"],
        "referral_notes": r["referral_notes"], "status": r["status"],
        "response_summary": r["response_summary"],
        "sent_at": iso(r["sent_at"]), "closed_reason": r["closed_reason"],
    })
    return out


def ser_venue(r):
    out = _common(r)
    out.update({"name": r["name"], "capacity": r["capacity"], "address": r["address"]})
    return out


def ser_event(e):
    out = _common(e)
    out.update({
        "representative_id": e["representative_id"], "venue_id": e["venue_id"],
        "title": e["title"], "start_at": iso(e["start_at"]), "end_at": iso(e["end_at"]),
        "capacity": e["capacity"], "lifecycle_status": e["lifecycle_status"],
        "registration_status": e["registration_status"],
        "registered_count": e["registered_count"],
    })
    return out


def ser_registration(r):
    out = _common(r)
    out.update({
        "event_id": r["event_id"], "constituent_id": r["constituent_id"],
        "status": r["status"], "registered_at": iso(r["registered_at"]),
    })
    return out


def ser_newsletter(n):
    out = _common(n)
    out.update({
        "representative_id": n["representative_id"], "subject": n["subject"],
        "body": n["body"], "page_count": n["page_count"], "status": n["status"],
        "recipient_count": n["recipient_count"], "send_cost_cents": n["send_cost_cents"],
    })
    return out


# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------
@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    authenticate(["OfficeAdmin"])
    body = get_body()
    ts = require_str(body, "to_iso8601")
    db.clock = parse_iso(ts)
    return ok({})


# ---------------------------------------------------------------------------
# Representatives
# ---------------------------------------------------------------------------
@app.route("/representatives", methods=["POST"])
def create_representative():
    authenticate(["OfficeAdmin"])
    body = get_body()
    rec = base_record()
    rec.update({
        "full_name": require_str(body, "full_name"),
        "chamber": require_enum(body, "chamber", CHAMBERS),
        "district_name": require_str(body, "district_name"),
        "state_code": require_str(body, "state_code"),
        "office_email": require_str(body, "office_email"),
    })
    db.representatives[rec["id"]] = rec
    return ok(ser_representative(rec), 201)


@app.route("/representatives/<rid>", methods=["GET"])
def get_representative_ep(rid):
    authenticate(["OfficeAdmin", "Caseworker"])
    return ok(ser_representative(get_representative(rid)))


# ---------------------------------------------------------------------------
# Constituents
# ---------------------------------------------------------------------------
@app.route("/constituents", methods=["POST"])
def create_constituent():
    role, uid = authenticate(["Anonymous", "OfficeAdmin"], anon_exempt=True)
    body = get_body()
    rep_id = require_str(body, "representative_id")
    full_name = require_str(body, "full_name")
    email = require_str(body, "email")
    address = require_str(body, "address")
    phone = opt_str(body, "phone")
    contact_consent = opt_bool(body, "contact_consent", False)
    data_sharing_consent = opt_bool(body, "data_sharing_consent", False)
    get_representative(rep_id)  # existence
    rec = base_record()
    rec.update({
        "representative_id": rep_id, "full_name": full_name, "email": email,
        "address": address, "phone": phone, "contact_consent": contact_consent,
        "data_sharing_consent": data_sharing_consent, "status": "ACTIVE",
        "upcoming_event_count": 0,
    })
    db.constituents[rec["id"]] = rec
    return ok(ser_constituent(rec), 201)


@app.route("/constituents/<cid>", methods=["GET"])
def get_constituent_ep(cid):
    role, uid = authenticate(["Constituent", "Caseworker", "OfficeAdmin"])
    rec = db.constituents.get(cid)
    if role == "Constituent" and rec is not None and rec["id"] != uid:
        raise ApiError("ERR_FORBIDDEN", 403, "not owner")
    if rec is None:
        raise ApiError("ERR_CONSTITUENT_NOT_FOUND", 404, "not found")
    return ok(ser_constituent(rec))


@app.route("/constituents", methods=["GET"])
def list_constituents():
    authenticate(["Caseworker", "OfficeAdmin"])
    rep_id = request.args.get("representative_id")
    status = request.args.get("status")
    items = list(db.constituents.values())
    if rep_id is not None:
        items = [c for c in items if c["representative_id"] == rep_id]
    if status is not None:
        items = [c for c in items if c["status"] == status]
    return list_response(items, ser_constituent)


@app.route("/constituents/<cid>", methods=["PATCH"])
def update_constituent(cid):
    role, uid = authenticate(["Constituent", "OfficeAdmin"])
    rec = db.constituents.get(cid)
    if role == "Constituent" and rec is not None and rec["id"] != uid:
        raise ApiError("ERR_FORBIDDEN", 403, "not owner")
    body = get_body()
    # validate shape of any supplied fields
    updates = {}
    for f in ("full_name", "email", "address"):
        if f in body:
            updates[f] = require_str(body, f)
    if "phone" in body:
        updates["phone"] = opt_str(body, "phone")
    for f in ("contact_consent", "data_sharing_consent"):
        if f in body and body[f] is not None:
            if not isinstance(body[f], bool):
                raise ApiError("ERR_INVALID_REQUEST", 400, "invalid boolean: %s" % f)
            updates[f] = body[f]
    if rec is None:
        raise ApiError("ERR_CONSTITUENT_NOT_FOUND", 404, "not found")
    rec.update(updates)
    touch(rec)
    return ok(ser_constituent(rec))


@app.route("/constituents/<cid>/purge", methods=["POST"])
def purge_constituent(cid):
    role, uid = authenticate(["Constituent", "OfficeAdmin"])
    rec = db.constituents.get(cid)
    if role == "Constituent" and rec is not None and rec["id"] != uid:
        raise ApiError("ERR_FORBIDDEN", 403, "not owner")
    if rec is None:
        raise ApiError("ERR_CONSTITUENT_NOT_FOUND", 404, "not found")
    if rec["status"] != "ACTIVE":
        raise ApiError("ERR_CONSTITUENT_PURGED", 409, "constituent already purged")

    ts = now()
    # 1. redact PII + status
    rec["full_name"] = "REDACTED"
    rec["email"] = "REDACTED"
    rec["address"] = "REDACTED"
    if rec["phone"] is not None:
        rec["phone"] = "REDACTED"
    rec["status"] = "PURGED"
    touch(rec)

    # 2/3/4. case sweep -> referral recall -> agency counter
    for case in db.cases.values():
        if case["constituent_id"] != cid:
            continue
        if case["status"] in ("NEW", "IN_PROGRESS", "AWAITING_CONSTITUENT", "AWAITING_AGENCY"):
            case["status"] = "WITHDRAWN"
            case["withdrawn_at"] = ts
            touch(case)
            _recall_open_referrals(case)

    # parallel: cancel REGISTERED event registrations
    for reg in db.registrations.values():
        if reg["constituent_id"] != cid or reg["status"] != "REGISTERED":
            continue
        reg["status"] = "CANCELLED"
        touch(reg)
        event = db.events.get(reg["event_id"])
        if event is not None:
            event["registered_count"] -= 1
            touch(event)
        rec["upcoming_event_count"] -= 1
        touch(rec)

    return ok(ser_constituent(rec))


def _recall_open_referrals(case):
    for ref in db.referrals.values():
        if ref["case_id"] != case["id"]:
            continue
        if ref["status"] in ("DRAFT", "SENT"):
            was_sent = ref["status"] == "SENT"
            ref["status"] = "RECALLED"
            ref["closed_reason"] = "RECALLED"
            touch(ref)
            if was_sent:
                agency = db.agencies.get(ref["agency_id"])
                if agency is not None:
                    agency["open_referral_count"] -= 1
                    touch(agency)


# ---------------------------------------------------------------------------
# Agencies
# ---------------------------------------------------------------------------
@app.route("/agencies", methods=["POST"])
def create_agency():
    authenticate(["OfficeAdmin"])
    body = get_body()
    status = "ACTIVE"
    if "status" in body and body["status"] is not None:
        status = require_enum(body, "status", AGENCY_STATUSES)
    rec = base_record()
    rec.update({
        "name": require_str(body, "name"),
        "jurisdiction": require_str(body, "jurisdiction"),
        "status": status, "open_referral_count": 0,
    })
    db.agencies[rec["id"]] = rec
    return ok(ser_agency(rec), 201)


@app.route("/agencies/<aid>", methods=["GET"])
def get_agency_ep(aid):
    authenticate(["Caseworker", "OfficeAdmin"])
    return ok(ser_agency(get_agency(aid)))


# ---------------------------------------------------------------------------
# Response templates
# ---------------------------------------------------------------------------
@app.route("/response-templates", methods=["POST"])
def create_template():
    authenticate(["OfficeAdmin"])
    body = get_body()
    rec = base_record()
    rec.update({
        "category": require_enum(body, "category", CATEGORIES),
        "body_template": require_str(body, "body_template"),
        "response_window_hours": require_int(body, "response_window_hours", minimum=1),
        "active": opt_bool(body, "active", True),
    })
    db.templates[rec["id"]] = rec
    return ok(ser_template(rec), 201)


@app.route("/response-templates/<tid>", methods=["GET"])
def get_template_ep(tid):
    authenticate(["Caseworker", "OfficeAdmin"])
    return ok(ser_template(get_template(tid)))


# ---------------------------------------------------------------------------
# Cases
# ---------------------------------------------------------------------------
@app.route("/cases", methods=["POST"])
def create_case():
    role, uid = authenticate(["Constituent", "Caseworker", "OfficeAdmin"])
    body = get_body()
    # ownership (pri 3): constituent files own case
    if role == "Constituent" and isinstance(body.get("constituent_id"), str):
        if body["constituent_id"] != uid:
            raise ApiError("ERR_FORBIDDEN", 403, "not owner")
    constituent_id = require_str(body, "constituent_id")
    subject = require_str(body, "subject")
    description = require_str(body, "description")
    category = require_enum(body, "category", CATEGORIES)
    if role == "Constituent" and constituent_id != uid:
        raise ApiError("ERR_FORBIDDEN", 403, "not owner")
    con = get_constituent(constituent_id)  # existence (pri 6)
    if con["status"] != "ACTIVE":  # pri 9
        raise ApiError("ERR_CONSTITUENT_PURGED", 409, "constituent purged")

    rec = base_record()
    rec.update({
        "constituent_id": constituent_id,
        "representative_id": con["representative_id"],
        "subject": subject, "description": description, "category": category,
        "priority": "NORMAL", "status": "NEW",
        "assigned_template_id": None, "assignee_staff_id": None,
        "response_window_hours": None, "effective_window_hours": None,
        "provisional_due_at": rec_provisional(rec_created_at=rec["created_at"], category=category),
        "final_due_at": None,
        "cumulative_paused_hours": 0, "paused_since": None,
        "last_agency_outcome": None, "reject_count": 0,
        "triaged_at": None, "resolved_at": None, "closed_at": None, "withdrawn_at": None,
    })
    db.cases[rec["id"]] = rec
    return ok(ser_case(rec), 201)


def rec_provisional(rec_created_at, category):
    return rec_created_at + timedelta(hours=DEFAULT_WINDOW_HOURS[category])


@app.route("/cases/<cid>", methods=["GET"])
def get_case_ep(cid):
    role, uid = authenticate(["Constituent", "Caseworker", "OfficeAdmin"])
    rec = db.cases.get(cid)
    if role == "Constituent" and rec is not None and rec["constituent_id"] != uid:
        raise ApiError("ERR_FORBIDDEN", 403, "not owner")
    if rec is None:
        raise ApiError("ERR_CASE_NOT_FOUND", 404, "not found")
    return ok(ser_case(rec))


@app.route("/cases", methods=["GET"])
def list_cases():
    authenticate(["Caseworker", "OfficeAdmin"])
    args = request.args
    items = list(db.cases.values())
    for key in ("constituent_id", "representative_id", "status", "category"):
        val = args.get(key)
        if val is not None:
            items = [c for c in items if c[key] == val]
    return list_response(items, ser_case)


@app.route("/cases/<cid>/triage", methods=["POST"])
def triage_case(cid):
    authenticate(["Caseworker", "OfficeAdmin"])
    body = get_body()
    template_id = require_str(body, "template_id")
    priority = require_enum(body, "priority", PRIORITIES)
    assignee_staff_id = require_str(body, "assignee_staff_id")
    case = get_case(cid)                         # existence (pri6)
    template = get_template(template_id)         # existence (pri6)
    if case["status"] != "NEW":                  # state (pri7)
        raise ApiError("ERR_CASE_INVALID_STATE", 409, "case not in NEW")
    con = db.constituents.get(case["constituent_id"])
    if con is None or con["status"] != "ACTIVE":  # pri9
        raise ApiError("ERR_CONSTITUENT_PURGED", 409, "constituent not active")
    if (not template["active"]) or template["category"] != case["category"]:  # pri11
        raise ApiError("ERR_TEMPLATE_MISMATCH", 422, "template inactive or category mismatch")

    ts = now()
    window = template["response_window_hours"]
    raw = window * PRIORITY_MULTIPLIER[priority] + CATEGORY_SURCHARGE_HOURS[case["category"]]
    eff = round2(min(raw, MAX_WINDOW_HOURS))
    case["assigned_template_id"] = template_id
    case["assignee_staff_id"] = assignee_staff_id
    case["priority"] = priority
    case["response_window_hours"] = window
    case["effective_window_hours"] = eff
    case["triaged_at"] = ts
    case["final_due_at"] = ts + timedelta(hours=eff)
    case["status"] = "IN_PROGRESS"
    touch(case)
    return ok(ser_case(case))


@app.route("/cases/<cid>/request-info", methods=["POST"])
def request_info(cid):
    authenticate(["Caseworker", "OfficeAdmin"])
    get_body()
    case = get_case(cid)
    if case["status"] != "IN_PROGRESS":
        raise ApiError("ERR_CASE_INVALID_STATE", 409, "case not IN_PROGRESS")
    case["paused_since"] = now()
    case["status"] = "AWAITING_CONSTITUENT"
    touch(case)
    return ok(ser_case(case))


@app.route("/cases/<cid>/constituent-reply", methods=["POST"])
def constituent_reply(cid):
    role, uid = authenticate(["Constituent"])
    get_body()
    case = db.cases.get(cid)
    if case is not None and case["constituent_id"] != uid:
        raise ApiError("ERR_FORBIDDEN", 403, "not owner")
    if case is None:
        raise ApiError("ERR_CASE_NOT_FOUND", 404, "not found")
    if case["status"] != "AWAITING_CONSTITUENT":
        raise ApiError("ERR_CASE_INVALID_STATE", 409, "case not AWAITING_CONSTITUENT")
    _resume_clock(case)
    case["status"] = "IN_PROGRESS"
    touch(case)
    return ok(ser_case(case))


def _resume_clock(case):
    if case["paused_since"] is not None:
        case["cumulative_paused_hours"] += hours_between(now(), case["paused_since"])
        case["paused_since"] = None


@app.route("/cases/<cid>/respond", methods=["POST"])
def respond_case(cid):
    authenticate(["Caseworker", "OfficeAdmin"])
    get_body()
    case = get_case(cid)
    if case["status"] != "IN_PROGRESS":
        raise ApiError("ERR_CASE_INVALID_STATE", 409, "case not IN_PROGRESS")
    case["resolved_at"] = now()
    case["status"] = "RESOLVED"
    touch(case)
    return ok(ser_case(case))


@app.route("/cases/<cid>/close", methods=["POST"])
def close_case(cid):
    authenticate(["OfficeAdmin"])
    get_body()
    case = get_case(cid)
    if case["status"] != "RESOLVED":
        raise ApiError("ERR_CASE_INVALID_STATE", 409, "case not RESOLVED")
    case["closed_at"] = now()
    case["status"] = "CLOSED"
    touch(case)
    # cascade: DRAFT/SENT referrals -> CLOSED
    for ref in db.referrals.values():
        if ref["case_id"] != case["id"]:
            continue
        if ref["status"] in ("DRAFT", "SENT"):
            was_sent = ref["status"] == "SENT"
            ref["status"] = "CLOSED"
            ref["closed_reason"] = "CASE_CLOSED"
            touch(ref)
            if was_sent:
                agency = db.agencies.get(ref["agency_id"])
                if agency is not None:
                    agency["open_referral_count"] -= 1
                    touch(agency)
    return ok(ser_case(case))


@app.route("/cases/<cid>/withdraw", methods=["POST"])
def withdraw_case(cid):
    role, uid = authenticate(["Constituent"])
    get_body()
    case = db.cases.get(cid)
    if case is not None and case["constituent_id"] != uid:
        raise ApiError("ERR_FORBIDDEN", 403, "not owner")
    if case is None:
        raise ApiError("ERR_CASE_NOT_FOUND", 404, "not found")
    if case["status"] not in ("NEW", "IN_PROGRESS", "AWAITING_CONSTITUENT", "AWAITING_AGENCY"):
        raise ApiError("ERR_CASE_INVALID_STATE", 409, "case is terminal")
    case["withdrawn_at"] = now()
    case["status"] = "WITHDRAWN"
    touch(case)
    _recall_open_referrals(case)
    return ok(ser_case(case))


@app.route("/cases/<cid>/referrals", methods=["POST"])
def create_referral(cid):
    authenticate(["Caseworker", "OfficeAdmin"])
    body = get_body()
    agency_id = require_str(body, "agency_id")
    referral_notes = opt_str(body, "referral_notes")
    case = get_case(cid)                       # existence (pri6)
    agency = get_agency(agency_id)             # existence (pri6)
    if case["status"] != "IN_PROGRESS":        # state (pri7)
        raise ApiError("ERR_CASE_INVALID_STATE", 409, "case not IN_PROGRESS")
    con = db.constituents.get(case["constituent_id"])
    if con is None or not con["data_sharing_consent"]:  # consent (pri8)
        raise ApiError("ERR_CONSENT_REQUIRED", 403, "data sharing consent required")
    if agency["status"] != "ACTIVE":           # agency inactive (pri10)
        raise ApiError("ERR_AGENCY_INACTIVE", 409, "agency inactive")

    ref = base_record()
    ref.update({
        "case_id": case["id"], "agency_id": agency_id, "referral_notes": referral_notes,
        "status": "DRAFT", "response_summary": None, "sent_at": None, "closed_reason": None,
    })
    db.referrals[ref["id"]] = ref
    case["paused_since"] = now()
    case["status"] = "AWAITING_AGENCY"
    touch(case)
    return ok(ser_referral(ref), 201)


@app.route("/cases/<cid>/referrals", methods=["GET"])
def list_case_referrals(cid):
    authenticate(["Caseworker", "OfficeAdmin"])
    get_case(cid)
    items = [r for r in db.referrals.values() if r["case_id"] == cid]
    return list_response(items, ser_referral)


# ---------------------------------------------------------------------------
# Agency referrals
# ---------------------------------------------------------------------------
@app.route("/agency-referrals/<rid>", methods=["GET"])
def get_referral_ep(rid):
    authenticate(["Caseworker", "OfficeAdmin"])
    return ok(ser_referral(get_referral(rid)))


@app.route("/agency-referrals", methods=["GET"])
def list_referrals():
    authenticate(["Caseworker", "OfficeAdmin"])
    args = request.args
    items = list(db.referrals.values())
    for key in ("agency_id", "case_id", "status"):
        val = args.get(key)
        if val is not None:
            items = [r for r in items if r[key] == val]
    return list_response(items, ser_referral)


@app.route("/agency-referrals/<rid>/send", methods=["POST"])
def send_referral(rid):
    authenticate(["Caseworker", "OfficeAdmin"])
    get_body()
    ref = get_referral(rid)
    if ref["status"] != "DRAFT":
        raise ApiError("ERR_REFERRAL_INVALID_STATE", 409, "referral not DRAFT")
    case = db.cases.get(ref["case_id"])
    if case is None or case["status"] != "AWAITING_AGENCY":
        raise ApiError("ERR_REFERRAL_INVALID_STATE", 409, "case not AWAITING_AGENCY")
    agency = db.agencies.get(ref["agency_id"])
    if agency is None or agency["status"] != "ACTIVE":
        raise ApiError("ERR_AGENCY_INACTIVE", 409, "agency inactive")
    ref["sent_at"] = now()
    ref["status"] = "SENT"
    touch(ref)
    agency["open_referral_count"] += 1
    touch(agency)
    return ok(ser_referral(ref))


@app.route("/agency-referrals/<rid>/resolve", methods=["POST"])
def resolve_referral(rid):
    authenticate(["Caseworker", "OfficeAdmin"])
    body = get_body()
    summary = opt_str(body, "response_summary")
    ref = get_referral(rid)
    if ref["status"] != "SENT":
        raise ApiError("ERR_REFERRAL_INVALID_STATE", 409, "referral not SENT")
    ref["status"] = "RESOLVED"
    ref["closed_reason"] = "RESOLVED"
    ref["response_summary"] = summary
    touch(ref)
    agency = db.agencies.get(ref["agency_id"])
    if agency is not None:
        agency["open_referral_count"] -= 1
        touch(agency)
    _return_case_from_agency(ref, "RESOLVED")
    return ok(ser_referral(ref))


@app.route("/agency-referrals/<rid>/reject", methods=["POST"])
def reject_referral(rid):
    authenticate(["Caseworker", "OfficeAdmin"])
    get_body()
    ref = get_referral(rid)
    if ref["status"] != "SENT":
        raise ApiError("ERR_REFERRAL_INVALID_STATE", 409, "referral not SENT")
    ref["status"] = "REJECTED"
    ref["closed_reason"] = "REJECTED"
    touch(ref)
    agency = db.agencies.get(ref["agency_id"])
    if agency is not None:
        agency["open_referral_count"] -= 1
        touch(agency)
    _return_case_from_agency(ref, "REJECTED")
    return ok(ser_referral(ref))


def _return_case_from_agency(ref, outcome):
    case = db.cases.get(ref["case_id"])
    if case is None:
        return
    if case["status"] == "AWAITING_AGENCY":
        _resume_clock(case)
        case["status"] = "IN_PROGRESS"
        case["last_agency_outcome"] = outcome
        if outcome == "REJECTED":
            case["reject_count"] += 1
        touch(case)


# ---------------------------------------------------------------------------
# Analytics
# ---------------------------------------------------------------------------
@app.route("/analytics/recurring-issues", methods=["GET"])
def recurring_issues():
    authenticate(["Caseworker", "OfficeAdmin"])
    args = request.args
    rep_id = args.get("representative_id")
    if not rep_id:
        raise ApiError("ERR_INVALID_REQUEST", 400, "representative_id required")
    category = args.get("category")
    variant = args.get("variant") or "RAW"
    if variant not in ("RAW", "TREND"):
        raise ApiError("ERR_INVALID_REQUEST", 400, "invalid variant")
    window_days = DEFAULT_WINDOW_DAYS
    if args.get("window_days") is not None:
        try:
            window_days = int(args.get("window_days"))
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST", 400, "invalid window_days")
    get_representative(rep_id)  # existence

    pool = [c for c in db.cases.values()
            if c["representative_id"] == rep_id and c["status"] != "WITHDRAWN"]
    if category is not None:
        pool = [c for c in pool if c["category"] == category]

    if variant == "TREND":
        cutoff = now() - timedelta(days=window_days)
        pool = [c for c in pool if c["created_at"] >= cutoff]
        total = Decimal("0")
        for c in pool:
            contrib = Decimal(str(PRIORITY_WEIGHT[c["priority"]] * RECENCY_BONUS)).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP)
            total += contrib
        index = float(total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
    else:
        total = Decimal("0")
        for c in pool:
            contrib = Decimal(str(PRIORITY_WEIGHT[c["priority"]])).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP)
            total += contrib
        index = float(total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))

    data = {
        "representative_id": rep_id,
        "category": category,
        "variant": variant,
        "index": index,
        "case_count": len(pool),
    }
    return ok(data)


# ---------------------------------------------------------------------------
# Venues
# ---------------------------------------------------------------------------
@app.route("/venues", methods=["POST"])
def create_venue():
    authenticate(["OfficeAdmin"])
    body = get_body()
    rec = base_record()
    rec.update({
        "name": require_str(body, "name"),
        "capacity": require_int(body, "capacity", minimum=0),
        "address": opt_str(body, "address"),
    })
    db.venues[rec["id"]] = rec
    return ok(ser_venue(rec), 201)


@app.route("/venues/<vid>", methods=["GET"])
def get_venue_ep(vid):
    authenticate(["OfficeAdmin", "Caseworker"])
    return ok(ser_venue(get_venue(vid)))


# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------
def _intervals_overlap(s1, e1, s2, e2):
    # half-open [s,e) overlap
    return s1 < e2 and s2 < e1


def _check_event_conflicts(rep_id, venue_id, start_at, end_at, capacity, venue, exclude_id=None):
    # venue conflict (buffered) — pri13
    buf = timedelta(minutes=VENUE_BUFFER_MINUTES)
    bstart, bend = start_at - buf, end_at + buf
    for ev in db.events.values():
        if ev["id"] == exclude_id or ev["lifecycle_status"] != "SCHEDULED":
            continue
        if ev["venue_id"] == venue_id and _intervals_overlap(bstart, bend, ev["start_at"], ev["end_at"]):
            raise ApiError("ERR_VENUE_CONFLICT", 409, "venue schedule conflict")
    # representative conflict (raw half-open) — pri14
    for ev in db.events.values():
        if ev["id"] == exclude_id or ev["lifecycle_status"] != "SCHEDULED":
            continue
        if ev["representative_id"] == rep_id and _intervals_overlap(start_at, end_at, ev["start_at"], ev["end_at"]):
            raise ApiError("ERR_REPRESENTATIVE_CONFLICT", 409, "representative schedule conflict")
    # capacity ceiling — pri15
    if capacity > venue["capacity"]:
        raise ApiError("ERR_EVENT_FULL", 409, "capacity exceeds venue capacity")


@app.route("/events", methods=["POST"])
def create_event():
    authenticate(["OfficeAdmin"])
    body = get_body()
    rep_id = require_str(body, "representative_id")
    venue_id = require_str(body, "venue_id")
    title = require_str(body, "title")
    start_raw = require_str(body, "start_at")
    end_raw = require_str(body, "end_at")
    capacity = require_int(body, "capacity", minimum=0)
    start_at = parse_iso(start_raw)
    end_at = parse_iso(end_raw)
    if not (start_at < end_at):                # time-range (pri5)
        raise ApiError("ERR_INVALID_TIME_RANGE", 422, "start_at must be before end_at")
    get_representative(rep_id)                  # existence (pri6)
    venue = get_venue(venue_id)                 # existence (pri6)
    _check_event_conflicts(rep_id, venue_id, start_at, end_at, capacity, venue)

    rec = base_record()
    rec.update({
        "representative_id": rep_id, "venue_id": venue_id, "title": title,
        "start_at": start_at, "end_at": end_at, "capacity": capacity,
        "lifecycle_status": "SCHEDULED", "registration_status": "CLOSED",
        "registered_count": 0,
    })
    db.events[rec["id"]] = rec
    return ok(ser_event(rec), 201)


@app.route("/events/<eid>", methods=["GET"])
def get_event_ep(eid):
    authenticate(["Constituent", "Caseworker", "OfficeAdmin"])
    return ok(ser_event(get_event(eid)))


@app.route("/events", methods=["GET"])
def list_events():
    authenticate(["Constituent", "Caseworker", "OfficeAdmin"])
    args = request.args
    items = list(db.events.values())
    for key in ("representative_id", "venue_id", "lifecycle_status"):
        val = args.get(key)
        if val is not None:
            items = [e for e in items if e[key] == val]
    return list_response(items, ser_event)


@app.route("/events/<eid>/reschedule", methods=["POST"])
def reschedule_event(eid):
    authenticate(["OfficeAdmin"])
    body = get_body()
    expected_version = require_int(body, "expected_event_version")
    start_raw = require_str(body, "start_at")
    end_raw = require_str(body, "end_at")
    new_venue_id = opt_str(body, "venue_id")
    start_at = parse_iso(start_raw)
    end_at = parse_iso(end_raw)
    if not (start_at < end_at):                        # time-range (pri5)
        raise ApiError("ERR_INVALID_TIME_RANGE", 422, "start_at must be before end_at")
    event = get_event(eid)                              # existence (pri6)
    venue_id = new_venue_id if new_venue_id is not None else event["venue_id"]
    venue = get_venue(venue_id)                         # existence (pri6)
    if event["lifecycle_status"] != "SCHEDULED":        # state (pri7)
        raise ApiError("ERR_EVENT_INVALID_STATE", 409, "event not SCHEDULED")
    _check_event_conflicts(event["representative_id"], venue_id, start_at, end_at,
                           event["capacity"], venue, exclude_id=event["id"])
    if expected_version != event["version"]:            # OCC (pri16)
        raise ApiError("ERR_STALE_VERSION", 412, "stale event version")

    event["start_at"] = start_at
    event["end_at"] = end_at
    if new_venue_id is not None:
        event["venue_id"] = new_venue_id
    touch(event)
    return ok(ser_event(event))


@app.route("/events/<eid>/open-registration", methods=["POST"])
def open_registration(eid):
    authenticate(["OfficeAdmin"])
    get_body()
    event = get_event(eid)
    if event["lifecycle_status"] != "SCHEDULED" or event["registration_status"] != "CLOSED":
        raise ApiError("ERR_EVENT_INVALID_STATE", 409, "cannot open registration")
    if event["registered_count"] >= event["capacity"]:
        event["registration_status"] = "FULL"
    else:
        event["registration_status"] = "OPEN"
    touch(event)
    return ok(ser_event(event))


@app.route("/events/<eid>/cancel", methods=["POST"])
def cancel_event(eid):
    authenticate(["OfficeAdmin"])
    get_body()
    event = get_event(eid)
    if event["lifecycle_status"] != "SCHEDULED":
        raise ApiError("ERR_EVENT_INVALID_STATE", 409, "event not SCHEDULED")
    event["lifecycle_status"] = "CANCELLED"
    event["registration_status"] = "CLOSED"
    touch(event)
    for reg in db.registrations.values():
        if reg["event_id"] != event["id"] or reg["status"] != "REGISTERED":
            continue
        reg["status"] = "CANCELLED"
        touch(reg)
        event["registered_count"] -= 1
        touch(event)
        con = db.constituents.get(reg["constituent_id"])
        if con is not None:
            con["upcoming_event_count"] -= 1
            touch(con)
    return ok(ser_event(event))


@app.route("/events/<eid>/registrations", methods=["POST"])
def create_registration(eid):
    role, uid = authenticate(["Constituent", "OfficeAdmin"])
    body = get_body()
    if role == "Constituent" and isinstance(body.get("constituent_id"), str):
        if body["constituent_id"] != uid:
            raise ApiError("ERR_FORBIDDEN", 403, "not owner")
    constituent_id = require_str(body, "constituent_id")
    if role == "Constituent" and constituent_id != uid:
        raise ApiError("ERR_FORBIDDEN", 403, "not owner")
    event = get_event(eid)                       # existence (pri6)
    con = get_constituent(constituent_id)        # existence (pri6)
    # state (pri7): scheduled & registration open (or full -> capacity check)
    if event["lifecycle_status"] != "SCHEDULED" or event["registration_status"] == "CLOSED":
        raise ApiError("ERR_EVENT_INVALID_STATE", 409, "registration not open")
    if con["status"] != "ACTIVE":                # pri9
        raise ApiError("ERR_CONSTITUENT_PURGED", 409, "constituent purged")
    # duplicate (pri12)
    for r in db.registrations.values():
        if r["event_id"] == eid and r["constituent_id"] == constituent_id and r["status"] == "REGISTERED":
            raise ApiError("ERR_DUPLICATE_REGISTRATION", 409, "already registered")
    # capacity (pri15)
    if event["registered_count"] >= event["capacity"]:
        raise ApiError("ERR_EVENT_FULL", 409, "event full")

    rec = base_record()
    rec.update({
        "event_id": eid, "constituent_id": constituent_id,
        "status": "REGISTERED", "registered_at": now(),
    })
    db.registrations[rec["id"]] = rec
    event["registered_count"] += 1
    if event["registered_count"] >= event["capacity"]:
        event["registration_status"] = "FULL"
    touch(event)
    con["upcoming_event_count"] += 1
    touch(con)
    return ok(ser_registration(rec), 201)


@app.route("/events/<eid>/registrations", methods=["GET"])
def list_event_registrations(eid):
    authenticate(["Caseworker", "OfficeAdmin"])
    get_event(eid)
    items = [r for r in db.registrations.values() if r["event_id"] == eid]
    return list_response(items, ser_registration)


# ---------------------------------------------------------------------------
# Event registrations
# ---------------------------------------------------------------------------
@app.route("/event-registrations/<rid>", methods=["GET"])
def get_registration_ep(rid):
    role, uid = authenticate(["Constituent", "OfficeAdmin"])
    rec = db.registrations.get(rid)
    if role == "Constituent" and rec is not None and rec["constituent_id"] != uid:
        raise ApiError("ERR_FORBIDDEN", 403, "not owner")
    if rec is None:
        raise ApiError("ERR_REGISTRATION_NOT_FOUND", 404, "not found")
    return ok(ser_registration(rec))


@app.route("/event-registrations", methods=["GET"])
def list_registrations():
    role, uid = authenticate(["Constituent", "OfficeAdmin"])
    args = request.args
    items = list(db.registrations.values())
    if role == "Constituent":
        items = [r for r in items if r["constituent_id"] == uid]
    for key in ("constituent_id", "event_id", "status"):
        val = args.get(key)
        if val is not None:
            items = [r for r in items if r[key] == val]
    return list_response(items, ser_registration)


@app.route("/event-registrations/<rid>/cancel", methods=["POST"])
def cancel_registration(rid):
    role, uid = authenticate(["Constituent", "OfficeAdmin"])
    get_body()
    rec = db.registrations.get(rid)
    if role == "Constituent" and rec is not None and rec["constituent_id"] != uid:
        raise ApiError("ERR_FORBIDDEN", 403, "not owner")
    if rec is None:
        raise ApiError("ERR_REGISTRATION_NOT_FOUND", 404, "not found")
    if rec["status"] != "REGISTERED":
        raise ApiError("ERR_REGISTRATION_INVALID_STATE", 409, "registration not REGISTERED")
    rec["status"] = "CANCELLED"
    touch(rec)
    event = db.events.get(rec["event_id"])
    if event is not None:
        event["registered_count"] -= 1
        if event["registration_status"] == "FULL" and event["lifecycle_status"] == "SCHEDULED":
            event["registration_status"] = "OPEN"
        touch(event)
    con = db.constituents.get(rec["constituent_id"])
    if con is not None:
        con["upcoming_event_count"] -= 1
        touch(con)
    return ok(ser_registration(rec))


# ---------------------------------------------------------------------------
# Newsletters
# ---------------------------------------------------------------------------
@app.route("/representatives/<rid>/newsletters", methods=["POST"])
def create_newsletter(rid):
    authenticate(["OfficeAdmin"])
    body = get_body()
    subject = require_str(body, "subject")
    text = require_str(body, "body")
    page_count = require_int(body, "page_count", minimum=1)
    get_representative(rid)  # existence
    recipient_count = sum(
        1 for c in db.constituents.values()
        if c["representative_id"] == rid and c["status"] == "ACTIVE" and c["contact_consent"]
    )
    send_cost_cents = recipient_count * (BASE_POSTAGE_CENTS + PRINT_CENTS_PER_PAGE * page_count)
    rec = base_record()
    rec.update({
        "representative_id": rid, "subject": subject, "body": text,
        "page_count": page_count, "status": "SENT",
        "recipient_count": recipient_count, "send_cost_cents": send_cost_cents,
    })
    db.newsletters[rec["id"]] = rec
    return ok(ser_newsletter(rec), 201)


@app.route("/representatives/<rid>/newsletters", methods=["GET"])
def list_newsletters(rid):
    authenticate(["OfficeAdmin"])
    get_representative(rid)
    items = [n for n in db.newsletters.values() if n["representative_id"] == rid]
    return list_response(items, ser_newsletter)


@app.route("/newsletters/<nid>", methods=["GET"])
def get_newsletter_ep(nid):
    authenticate(["OfficeAdmin"])
    return ok(ser_newsletter(get_newsletter(nid)))


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
