import os
import random
import string
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP
from uuid import uuid4

from flask import Flask, request, jsonify

app = Flask(__name__)

# =====================================================================
# Constants
# =====================================================================
ALL_ROLES = {"ProgramOfficer", "Panelist", "GrantsManager", "Subrecipient"}
MIN_PANEL_REVIEWS = 3
SUBAWARD_PERIOD_GAP_DAYS = 30
SINGLE_AUDIT_THRESHOLD_CENTS = 75000000
DE_MINIMIS_INDIRECT_RATE = Decimal("0.10")
MTDC_SUBAWARD_CAP_CENTS = 2500000
CLOCK_DEFAULT_UTC = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)

CATEGORIES = {"PERSONNEL", "FRINGE", "TRAVEL", "SUPPLIES", "EQUIPMENT", "CONTRACTUAL", "OTHER"}
INDIRECT_METHODS = {"DE_MINIMIS", "NEGOTIATED"}
SEVERITIES = {"LOW", "MODERATE", "HIGH", "CRITICAL"}
OUTCOMES = {"SATISFACTORY", "DEFICIENT"}


# =====================================================================
# In-memory store
# =====================================================================
class DB:
    def __init__(self):
        self.reset()

    def reset(self):
        self.nonprofits = {}
        self.nofos = {}
        self.applications = {}
        self.panel_reviews = {}
        self.subawards = {}
        self.budget_lines = {}
        self.drawdowns = {}
        self.risk_assessments = {}
        self.monitoring_visits = {}
        self.performance_reports = {}
        self.single_audits = {}
        self.findings = {}
        self.clock = CLOCK_DEFAULT_UTC
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


db = DB()


# =====================================================================
# Errors
# =====================================================================
class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# =====================================================================
# Time / rendering helpers
# =====================================================================
def now_iso():
    dt = db.clock.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_dt(s):
    if not isinstance(s, str) or not s:
        raise ApiError("ERR_VALIDATION", 422)
    txt = s.strip()
    if txt.endswith("Z"):
        txt = txt[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(txt)
    except ValueError:
        raise ApiError("ERR_VALIDATION", 422)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def gen_req_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def new_id():
    return str(uuid4())


# =====================================================================
# Entity helpers
# =====================================================================
def new_common(fields):
    ts = now_iso()
    obj = {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": db.next_seq(),
    }
    obj.update(fields)
    return obj


def new_light(fields):
    obj = {
        "id": new_id(),
        "created_at": now_iso(),
        "_seq": db.next_seq(),
    }
    obj.update(fields)
    return obj


def bump(obj):
    obj["updated_at"] = now_iso()
    obj["version"] += 1


def serialize(obj):
    return {k: v for k, v in obj.items() if not k.startswith("_")}


# =====================================================================
# Response helpers
# =====================================================================
def _meta(pagination=None):
    m = {"api_request_id": gen_req_id(), "api_request_timestamp": now_iso()}
    if pagination:
        m.update(pagination)
    return m


def ok(data, code=200):
    return jsonify({"meta": _meta(), "response_type": "object", "data": data}), code


def ok_list(items, pagination):
    return (
        jsonify({"meta": _meta(pagination), "response_type": "array", "data": items}),
        200,
    )


@app.errorhandler(ApiError)
def handle_api_error(e):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": e.error_id, "message": e.message},
    }
    return jsonify(body), e.http_status


@app.after_request
def add_conn_close(resp):
    resp.headers["Connection"] = "close"
    return resp


# =====================================================================
# Auth / RBAC
# =====================================================================
def auth():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role:
        raise ApiError("ERR_UNAUTHENTICATED", 401)
    return uid, role


def require(allowed):
    uid, role = auth()
    if role not in allowed:
        raise ApiError("ERR_UNAUTHORIZED", 403)
    return uid, role


def body_json():
    b = request.get_json(silent=True)
    return b if isinstance(b, dict) else {}


# =====================================================================
# Lookup helpers
# =====================================================================
def get_nonprofit(i):
    o = db.nonprofits.get(i)
    if o is None:
        raise ApiError("ERR_NONPROFIT_NOT_FOUND", 404)
    return o


def get_nofo(i):
    o = db.nofos.get(i)
    if o is None:
        raise ApiError("ERR_NOFO_NOT_FOUND", 404)
    return o


def get_application(i):
    o = db.applications.get(i)
    if o is None:
        raise ApiError("ERR_APPLICATION_NOT_FOUND", 404)
    return o


def get_subaward(i):
    o = db.subawards.get(i)
    if o is None:
        raise ApiError("ERR_SUBAWARD_NOT_FOUND", 404)
    return o


def get_drawdown(i):
    o = db.drawdowns.get(i)
    if o is None:
        raise ApiError("ERR_DRAWDOWN_NOT_FOUND", 404)
    return o


def get_visit(i):
    o = db.monitoring_visits.get(i)
    if o is None:
        raise ApiError("ERR_MONITORING_VISIT_NOT_FOUND", 404)
    return o


def get_finding(i):
    o = db.findings.get(i)
    if o is None:
        raise ApiError("ERR_FINDING_NOT_FOUND", 404)
    return o


def get_single_audit(i):
    o = db.single_audits.get(i)
    if o is None:
        raise ApiError("ERR_SINGLE_AUDIT_NOT_FOUND", 404)
    return o


# =====================================================================
# Pagination / listing
# =====================================================================
def get_pagination():
    args = request.args
    try:
        limit = int(args.get("limit", 10))
    except (TypeError, ValueError):
        limit = 10
    try:
        offset = int(args.get("offset", 0))
    except (TypeError, ValueError):
        offset = 0
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    return limit, offset


def sort_key(o):
    return (o["created_at"], o["_seq"])


def make_list(items):
    limit, offset = get_pagination()
    items = sorted(items, key=sort_key)
    total = len(items)
    page = items[offset:offset + limit]
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }
    return [serialize(o) for o in page], pagination


# =====================================================================
# Field validation helpers
# =====================================================================
def req_field(body, field):
    if field not in body or body[field] is None:
        raise ApiError("ERR_VALIDATION", 422, f"Missing required field: {field}")
    return body[field]


def as_int(v):
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError("ERR_VALIDATION", 422)
    return v


def positive_amount(v):
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError("ERR_VALIDATION", 422)
    if v <= 0:
        raise ApiError("ERR_AMOUNT_NOT_POSITIVE", 422)
    return v


def check_period(start, end):
    s = parse_dt(start)
    e = parse_dt(end)
    if e <= s:
        raise ApiError("ERR_INVALID_PERIOD", 422)
    return s, e


# =====================================================================
# Calculations
# =====================================================================
def rhu_mul(base, rate):
    return int((Decimal(base) * Decimal(str(rate))).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def budget_lines_of(sub_id):
    return sorted(
        [l for l in db.budget_lines.values() if l["subaward_id"] == sub_id],
        key=sort_key,
    )


def compute_indirect(sub, lines):
    base = 0
    for l in lines:
        c = l["category"]
        if c == "EQUIPMENT":
            continue
        elif c == "CONTRACTUAL":
            base += min(l["amount_cents"], MTDC_SUBAWARD_CAP_CENTS)
        else:
            base += l["amount_cents"]
    if sub["indirect_method"] == "DE_MINIMIS":
        rate = DE_MINIMIS_INDIRECT_RATE
    else:
        rate = sub["negotiated_indirect_rate"]
    return rhu_mul(base, rate)


def compute_federal_share(lines):
    total = 0
    for l in lines:
        total += rhu_mul(l["amount_cents"], l["federal_share_pct"])
    return total


def drawdowns_of(sub_id):
    return [d for d in db.drawdowns.values() if d["subaward_id"] == sub_id]


def subawards_of_nonprofit(np_id):
    return [s for s in db.subawards.values() if s["nonprofit_id"] == np_id]


def recompute_cumulative(np):
    total = 0
    for s in subawards_of_nonprofit(np["id"]):
        total += s["disbursed_cents"]
    np["cumulative_federal_expenditures_cents"] = total


# =====================================================================
# Cascade helpers
# =====================================================================
def cascade_return_pending(sub):
    """Suspension: SUBMITTED drawdowns -> RETURNED, credit obligation."""
    for dd in drawdowns_of(sub["id"]):
        if dd["status"] == "SUBMITTED":
            sub["obligated_cents"] -= dd["provisional_reimbursable_cents"]
            dd["reimbursable_cents"] = 0
            dd["status"] = "RETURNED"
            bump(dd)


def cascade_deny_leftover(sub):
    """Close/terminate from ACTIVE/SUSPENDED: SUBMITTED/RETURNED -> DENIED."""
    for dd in drawdowns_of(sub["id"]):
        if dd["status"] == "SUBMITTED":
            sub["obligated_cents"] -= dd["provisional_reimbursable_cents"]
            dd["reimbursable_cents"] = 0
            dd["status"] = "DENIED"
            bump(dd)
        elif dd["status"] == "RETURNED":
            dd["status"] = "DENIED"
            bump(dd)


# =====================================================================
# Clock
# =====================================================================
@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    require(["ProgramOfficer"])
    body = body_json()
    val = req_field(body, "to_iso8601")
    db.clock = parse_dt(val)
    return ok({}, 200)


# =====================================================================
# Nonprofit
# =====================================================================
@app.route("/nonprofits", methods=["POST"])
def create_nonprofit():
    require(["ProgramOfficer"])
    body = body_json()
    legal_name = req_field(body, "legal_name")
    uei = req_field(body, "uei")
    ein = req_field(body, "ein")
    for existing in db.nonprofits.values():
        if existing["uei"] == uei:
            raise ApiError("ERR_VALIDATION", 422, "uei must be unique")
    np = new_common({
        "legal_name": legal_name,
        "uei": uei,
        "ein": ein,
        "cumulative_federal_expenditures_cents": 0,
        "latest_risk_tier": None,
    })
    db.nonprofits[np["id"]] = np
    return ok(serialize(np), 201)


@app.route("/nonprofits/<i>", methods=["GET"])
def fetch_nonprofit(i):
    require(["ProgramOfficer", "GrantsManager", "Subrecipient", "Panelist"])
    return ok(serialize(get_nonprofit(i)), 200)


@app.route("/nonprofits/<i>/single-audits", methods=["GET"])
def list_nonprofit_audits(i):
    require(["ProgramOfficer", "GrantsManager", "Subrecipient"])
    get_nonprofit(i)
    items = [a for a in db.single_audits.values() if a["nonprofit_id"] == i]
    page, pagination = make_list(items)
    return ok_list(page, pagination)


# =====================================================================
# NOFO
# =====================================================================
@app.route("/nofos", methods=["POST"])
def create_nofo():
    require(["ProgramOfficer"])
    body = body_json()
    title = req_field(body, "title")
    cfda = req_field(body, "cfda_number")
    total_pool = req_field(body, "total_pool_cents")
    max_award = req_field(body, "max_award_cents")
    cap_pct = req_field(body, "indirect_cost_cap_pct")
    open_date = req_field(body, "open_date")
    close_date = req_field(body, "close_date")
    total_pool = positive_amount(total_pool)
    max_award = positive_amount(max_award)
    if not isinstance(cap_pct, (int, float)) or isinstance(cap_pct, bool) or not (0 <= cap_pct <= 1):
        raise ApiError("ERR_VALIDATION", 422)
    parse_dt(open_date)
    parse_dt(close_date)
    nofo = new_common({
        "title": title,
        "cfda_number": cfda,
        "total_pool_cents": total_pool,
        "remaining_pool_cents": total_pool,
        "max_award_cents": max_award,
        "indirect_cost_cap_pct": cap_pct,
        "open_date": open_date,
        "close_date": close_date,
        "intake_status": "OPEN",
    })
    db.nofos[nofo["id"]] = nofo
    return ok(serialize(nofo), 201)


@app.route("/nofos/<i>", methods=["GET"])
def fetch_nofo(i):
    require(["ProgramOfficer", "GrantsManager", "Subrecipient", "Panelist"])
    return ok(serialize(get_nofo(i)), 200)


@app.route("/nofos/<i>/close-intake", methods=["POST"])
def close_intake(i):
    require(["ProgramOfficer"])
    nofo = get_nofo(i)
    nofo["intake_status"] = "CLOSED"
    bump(nofo)
    return ok(serialize(nofo), 200)


# =====================================================================
# Application
# =====================================================================
@app.route("/nofos/<i>/applications", methods=["POST"])
def create_application(i):
    uid, role = require(["Subrecipient"])
    nofo = get_nofo(i)
    body = body_json()
    nonprofit_id = body.get("nonprofit_id")
    if nonprofit_id is not None and nonprofit_id != uid:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", 403)
    # field validation
    nonprofit_id = req_field(body, "nonprofit_id")
    project_title = req_field(body, "project_title")
    requested = req_field(body, "requested_amount_cents")
    period_start = req_field(body, "proposed_period_start")
    period_end = req_field(body, "proposed_period_end")
    indirect_method = req_field(body, "indirect_method")
    if indirect_method not in INDIRECT_METHODS:
        raise ApiError("ERR_VALIDATION", 422)
    check_period(period_start, period_end)
    requested = positive_amount(requested)
    neg_rate = body.get("negotiated_indirect_rate")
    if neg_rate is not None:
        if isinstance(neg_rate, bool) or not isinstance(neg_rate, (int, float)) or not (0 <= neg_rate <= 1):
            raise ApiError("ERR_VALIDATION", 422)
    if indirect_method == "NEGOTIATED" and neg_rate is not None:
        if neg_rate > nofo["indirect_cost_cap_pct"]:
            raise ApiError("ERR_INDIRECT_RATE_OVER_CAP", 422)
    stored_rate = neg_rate if indirect_method == "NEGOTIATED" else None
    app_obj = new_common({
        "nofo_id": i,
        "nonprofit_id": nonprofit_id,
        "project_title": project_title,
        "requested_amount_cents": requested,
        "proposed_period_start": period_start,
        "proposed_period_end": period_end,
        "indirect_method": indirect_method,
        "negotiated_indirect_rate": stored_rate,
        "status": "DRAFT",
        "review_count": 0,
        "average_score": None,
        "awarded_amount_cents": None,
    })
    db.applications[app_obj["id"]] = app_obj
    return ok(serialize(app_obj), 201)


@app.route("/applications", methods=["GET"])
def list_applications():
    require(["ProgramOfficer", "GrantsManager", "Subrecipient", "Panelist"])
    nofo_id = request.args.get("nofo_id")
    nonprofit_id = request.args.get("nonprofit_id")
    status = request.args.get("status")
    items = list(db.applications.values())
    if nofo_id is not None:
        items = [a for a in items if a["nofo_id"] == nofo_id]
    if nonprofit_id is not None:
        items = [a for a in items if a["nonprofit_id"] == nonprofit_id]
    if status is not None:
        items = [a for a in items if a["status"] == status]
    page, pagination = make_list(items)
    return ok_list(page, pagination)


@app.route("/applications/<i>", methods=["GET"])
def fetch_application(i):
    require(["ProgramOfficer", "GrantsManager", "Subrecipient", "Panelist"])
    return ok(serialize(get_application(i)), 200)


@app.route("/applications/<i>/submit", methods=["POST"])
def submit_application(i):
    uid, role = require(["Subrecipient"])
    app_obj = get_application(i)
    if app_obj["nonprofit_id"] != uid:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", 403)
    st = app_obj["status"]
    if st not in ("DRAFT", "REVISION_REQUESTED"):
        raise ApiError("ERR_INVALID_APPLICATION_STATE", 409)
    if st == "DRAFT":
        nofo = db.nofos.get(app_obj["nofo_id"])
        if nofo and nofo["intake_status"] != "OPEN":
            raise ApiError("ERR_INTAKE_CLOSED", 409)
    app_obj["status"] = "SUBMITTED"
    bump(app_obj)
    return ok(serialize(app_obj), 200)


@app.route("/applications/<i>/start-review", methods=["POST"])
def start_review(i):
    require(["ProgramOfficer"])
    app_obj = get_application(i)
    if app_obj["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_APPLICATION_STATE", 409)
    app_obj["status"] = "UNDER_REVIEW"
    bump(app_obj)
    return ok(serialize(app_obj), 200)


@app.route("/applications/<i>/request-revision", methods=["POST"])
def request_revision(i):
    require(["ProgramOfficer"])
    app_obj = get_application(i)
    if app_obj["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_INVALID_APPLICATION_STATE", 409)
    app_obj["status"] = "REVISION_REQUESTED"
    bump(app_obj)
    return ok(serialize(app_obj), 200)


def periods_overlap_with_gap(s1, e1, s2, e2):
    gap = timedelta(days=SUBAWARD_PERIOD_GAP_DAYS)
    return (s1 <= e2 + gap) and (s2 <= e1 + gap)


@app.route("/applications/<i>/award", methods=["POST"])
def award_application(i):
    require(["ProgramOfficer"])
    app_obj = get_application(i)
    if app_obj["status"] != "SCORED":
        raise ApiError("ERR_APPLICATION_NOT_SCORED", 409)
    nofo = get_nofo(app_obj["nofo_id"])
    requested = app_obj["requested_amount_cents"]
    s1 = parse_dt(app_obj["proposed_period_start"])
    e1 = parse_dt(app_obj["proposed_period_end"])
    # ERR_PERIOD_OVERLAP: another non-terminal subaward of same nonprofit under same NOFO
    for sub in db.subawards.values():
        if sub["nonprofit_id"] != app_obj["nonprofit_id"]:
            continue
        if sub["nofo_id"] != app_obj["nofo_id"]:
            continue
        if sub["status"] in ("CLOSED", "TERMINATED"):
            continue
        s2 = parse_dt(sub["period_start"])
        e2 = parse_dt(sub["period_end"])
        if periods_overlap_with_gap(s1, e1, s2, e2):
            raise ApiError("ERR_PERIOD_OVERLAP", 409)
    if requested > nofo["max_award_cents"]:
        raise ApiError("ERR_MAX_AWARD_EXCEEDED", 409)
    if requested > nofo["remaining_pool_cents"]:
        raise ApiError("ERR_POOL_EXCEEDED", 409)
    # side effects
    app_obj["awarded_amount_cents"] = requested
    app_obj["status"] = "AWARDED"
    bump(app_obj)
    nofo["remaining_pool_cents"] -= requested
    bump(nofo)
    sub = new_common({
        "application_id": app_obj["id"],
        "nonprofit_id": app_obj["nonprofit_id"],
        "nofo_id": app_obj["nofo_id"],
        "period_start": app_obj["proposed_period_start"],
        "period_end": app_obj["proposed_period_end"],
        "total_budget_cents": requested,
        "indirect_method": app_obj["indirect_method"],
        "negotiated_indirect_rate": app_obj["negotiated_indirect_rate"],
        "indirect_cost_cents": 0,
        "federal_share_cents": 0,
        "obligated_cents": 0,
        "disbursed_cents": 0,
        "status": "DRAFT",
    })
    db.subawards[sub["id"]] = sub
    return ok(serialize(app_obj), 200)


@app.route("/applications/<i>/reject", methods=["POST"])
def reject_application(i):
    require(["ProgramOfficer"])
    app_obj = get_application(i)
    if app_obj["status"] != "SCORED":
        raise ApiError("ERR_APPLICATION_NOT_SCORED", 409)
    app_obj["status"] = "REJECTED"
    bump(app_obj)
    return ok(serialize(app_obj), 200)


# =====================================================================
# Panel Reviews
# =====================================================================
def recompute_average(app_obj):
    scores = [
        r["score"]
        for r in db.panel_reviews.values()
        if r["application_id"] == app_obj["id"]
    ]
    app_obj["review_count"] = len(scores)
    if not scores:
        app_obj["average_score"] = None
    else:
        avg = (Decimal(sum(scores)) / Decimal(len(scores))).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        app_obj["average_score"] = float(avg)


@app.route("/applications/<i>/reviews", methods=["POST"])
def create_review(i):
    uid, role = require(["Panelist"])
    app_obj = get_application(i)
    if app_obj["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_INVALID_APPLICATION_STATE", 409)
    # duplicate review check
    for r in db.panel_reviews.values():
        if r["application_id"] == i and r["reviewer_user_id"] == uid:
            raise ApiError("ERR_DUPLICATE_REVIEW", 409)
    body = body_json()
    score = req_field(body, "score")
    if isinstance(score, bool) or not isinstance(score, int) or not (0 <= score <= 100):
        raise ApiError("ERR_VALIDATION", 422)
    comments = body.get("comments")
    review = new_light({
        "application_id": i,
        "reviewer_user_id": uid,
        "score": score,
        "comments": comments,
    })
    db.panel_reviews[review["id"]] = review
    recompute_average(app_obj)
    if app_obj["review_count"] >= MIN_PANEL_REVIEWS and app_obj["status"] == "UNDER_REVIEW":
        app_obj["status"] = "SCORED"
    bump(app_obj)
    return ok(serialize(review), 201)


@app.route("/applications/<i>/reviews", methods=["GET"])
def list_reviews(i):
    require(["ProgramOfficer", "Panelist"])
    get_application(i)
    items = [r for r in db.panel_reviews.values() if r["application_id"] == i]
    page, pagination = make_list(items)
    return ok_list(page, pagination)


# =====================================================================
# Subawards
# =====================================================================
@app.route("/subawards/<i>", methods=["GET"])
def fetch_subaward(i):
    require(["ProgramOfficer", "GrantsManager", "Subrecipient", "Panelist"])
    return ok(serialize(get_subaward(i)), 200)


@app.route("/subawards", methods=["GET"])
def list_subawards():
    require(["ProgramOfficer", "GrantsManager", "Subrecipient", "Panelist"])
    application_id = request.args.get("application_id")
    nonprofit_id = request.args.get("nonprofit_id")
    nofo_id = request.args.get("nofo_id")
    status = request.args.get("status")
    items = list(db.subawards.values())
    if application_id is not None:
        items = [s for s in items if s["application_id"] == application_id]
    if nonprofit_id is not None:
        items = [s for s in items if s["nonprofit_id"] == nonprofit_id]
    if nofo_id is not None:
        items = [s for s in items if s["nofo_id"] == nofo_id]
    if status is not None:
        items = [s for s in items if s["status"] == status]
    page, pagination = make_list(items)
    return ok_list(page, pagination)


@app.route("/subawards/<i>/budget-lines", methods=["POST"])
def create_budget_line(i):
    require(["ProgramOfficer"])
    sub = get_subaward(i)
    if sub["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_SUBAWARD_STATE", 409)
    body = body_json()
    category = req_field(body, "category")
    amount = req_field(body, "amount_cents")
    fed_pct = req_field(body, "federal_share_pct")
    if category not in CATEGORIES:
        raise ApiError("ERR_VALIDATION", 422)
    if isinstance(fed_pct, bool) or not isinstance(fed_pct, (int, float)) or not (0 <= fed_pct <= 1):
        raise ApiError("ERR_VALIDATION", 422)
    amount = positive_amount(amount)
    line = new_light({
        "subaward_id": i,
        "category": category,
        "amount_cents": amount,
        "federal_share_pct": fed_pct,
        "description": body.get("description"),
    })
    db.budget_lines[line["id"]] = line
    return ok(serialize(line), 201)


@app.route("/subawards/<i>/budget-lines", methods=["GET"])
def list_budget_lines(i):
    require(["ProgramOfficer", "GrantsManager", "Subrecipient"])
    get_subaward(i)
    items = [l for l in db.budget_lines.values() if l["subaward_id"] == i]
    page, pagination = make_list(items)
    return ok_list(page, pagination)


@app.route("/subawards/<i>/activate", methods=["POST"])
def activate_subaward(i):
    require(["ProgramOfficer"])
    sub = get_subaward(i)
    if sub["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_SUBAWARD_STATE", 409)
    lines = budget_lines_of(i)
    if not lines:
        raise ApiError("ERR_NO_BUDGET_LINES", 409)
    if sub["indirect_method"] == "NEGOTIATED" and sub["negotiated_indirect_rate"] is None:
        raise ApiError("ERR_INDIRECT_RATE_REQUIRED", 409)
    indirect = compute_indirect(sub, lines)
    direct_sum = sum(l["amount_cents"] for l in lines)
    if direct_sum + indirect != sub["total_budget_cents"]:
        raise ApiError("ERR_BUDGET_NOT_BALANCED", 409)
    sub["indirect_cost_cents"] = indirect
    sub["federal_share_cents"] = compute_federal_share(lines)
    sub["status"] = "ACTIVE"
    bump(sub)
    return ok(serialize(sub), 200)


@app.route("/subawards/<i>/suspend", methods=["POST"])
def suspend_subaward(i):
    require(["GrantsManager"])
    sub = get_subaward(i)
    if sub["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_SUBAWARD_STATE", 409)
    sub["status"] = "SUSPENDED"
    cascade_return_pending(sub)
    bump(sub)
    return ok(serialize(sub), 200)


@app.route("/subawards/<i>/reinstate", methods=["POST"])
def reinstate_subaward(i):
    require(["GrantsManager"])
    sub = get_subaward(i)
    if sub["status"] != "SUSPENDED":
        raise ApiError("ERR_INVALID_SUBAWARD_STATE", 409)
    sub["status"] = "ACTIVE"
    bump(sub)
    return ok(serialize(sub), 200)


@app.route("/subawards/<i>/terminate", methods=["POST"])
def terminate_subaward(i):
    require(["ProgramOfficer"])
    sub = get_subaward(i)
    st = sub["status"]
    if st not in ("DRAFT", "ACTIVE", "SUSPENDED"):
        raise ApiError("ERR_INVALID_SUBAWARD_STATE", 409)
    if st == "DRAFT":
        sub["status"] = "TERMINATED"
        app_obj = db.applications.get(sub["application_id"])
        nofo = db.nofos.get(sub["nofo_id"])
        if app_obj and nofo and app_obj.get("awarded_amount_cents") is not None:
            nofo["remaining_pool_cents"] += app_obj["awarded_amount_cents"]
            bump(nofo)
        bump(sub)
    else:
        sub["status"] = "TERMINATED"
        cascade_deny_leftover(sub)
        bump(sub)
    return ok(serialize(sub), 200)


@app.route("/subawards/<i>/initiate-closeout", methods=["POST"])
def initiate_closeout(i):
    require(["ProgramOfficer"])
    sub = get_subaward(i)
    if sub["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_SUBAWARD_STATE", 409)
    sub["status"] = "CLOSEOUT_PENDING"
    bump(sub)
    return ok(serialize(sub), 200)


@app.route("/subawards/<i>/close", methods=["POST"])
def close_subaward(i):
    require(["ProgramOfficer"])
    sub = get_subaward(i)
    if sub["status"] != "CLOSEOUT_PENDING":
        raise ApiError("ERR_INVALID_SUBAWARD_STATE", 409)
    for f in db.findings.values():
        if f["subaward_id"] == i and f["status"] != "RESOLVED":
            raise ApiError("ERR_OPEN_FINDINGS", 409)
    sub["status"] = "CLOSED"
    cascade_deny_leftover(sub)
    bump(sub)
    return ok(serialize(sub), 200)


# =====================================================================
# Drawdowns
# =====================================================================
@app.route("/subawards/<i>/drawdowns", methods=["POST"])
def create_drawdown(i):
    uid, role = require(["Subrecipient"])
    sub = get_subaward(i)
    if sub["nonprofit_id"] != uid:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", 403)
    if sub["status"] != "ACTIVE":
        raise ApiError("ERR_SUBAWARD_NOT_ACTIVE", 409)
    body = body_json()
    requested = body.get("requested_amount_cents")
    available = sub["total_budget_cents"] - sub["obligated_cents"]
    # business: INSUFFICIENT then STALE
    if isinstance(requested, int) and not isinstance(requested, bool) and requested >= 1:
        if requested > available:
            raise ApiError("ERR_INSUFFICIENT_BUDGET", 409)
    exp = body.get("expected_subaward_version")
    if exp is not None and exp != sub["version"]:
        raise ApiError("ERR_STALE_VERSION", 412)
    # field validation
    requested = req_field(body, "requested_amount_cents")
    pcs = req_field(body, "period_covered_start")
    pce = req_field(body, "period_covered_end")
    check_period(pcs, pce)
    requested = positive_amount(requested)
    provisional = min(requested, available)
    dd = new_common({
        "subaward_id": i,
        "requested_amount_cents": requested,
        "period_covered_start": pcs,
        "period_covered_end": pce,
        "disallowed_amount_cents": 0,
        "provisional_reimbursable_cents": provisional,
        "final_reimbursable_cents": None,
        "reimbursable_cents": provisional,
        "submitted_by_user_id": uid,
        "reviewed_by_user_id": None,
        "status": "SUBMITTED",
        "_available_at_submit": available,
    })
    db.drawdowns[dd["id"]] = dd
    sub["obligated_cents"] += provisional
    bump(sub)
    return ok(serialize(dd), 201)


@app.route("/subawards/<i>/drawdowns", methods=["GET"])
def list_drawdowns(i):
    require(["ProgramOfficer", "GrantsManager", "Subrecipient"])
    get_subaward(i)
    status = request.args.get("status")
    items = [d for d in db.drawdowns.values() if d["subaward_id"] == i]
    if status is not None:
        items = [d for d in items if d["status"] == status]
    page, pagination = make_list(items)
    return ok_list(page, pagination)


@app.route("/drawdowns/<i>", methods=["GET"])
def fetch_drawdown(i):
    require(["ProgramOfficer", "GrantsManager", "Subrecipient"])
    return ok(serialize(get_drawdown(i)), 200)


@app.route("/drawdowns/<i>/approve", methods=["POST"])
def approve_drawdown(i):
    uid, role = require(["GrantsManager"])
    dd = get_drawdown(i)
    if dd["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_DRAWDOWN_STATE", 409)
    sub = db.subawards[dd["subaward_id"]]
    # SoD four-eyes
    for ra in db.risk_assessments.values():
        if ra["subaward_id"] == sub["id"] and ra["assessed_by_user_id"] == uid:
            raise ApiError("ERR_SOD_CONFLICT", 403)
    body = body_json()
    disallowed = body.get("disallowed_amount_cents", 0)
    if disallowed is None:
        disallowed = 0
    if isinstance(disallowed, bool) or not isinstance(disallowed, int) or disallowed < 0:
        raise ApiError("ERR_VALIDATION", 422)
    available = dd["_available_at_submit"]
    final = min(dd["requested_amount_cents"] - disallowed, available)
    prior_provisional = dd["provisional_reimbursable_cents"]
    dd["disallowed_amount_cents"] = disallowed
    dd["final_reimbursable_cents"] = final
    dd["reimbursable_cents"] = final
    dd["reviewed_by_user_id"] = uid
    dd["status"] = "APPROVED"
    bump(dd)
    sub["obligated_cents"] += (final - prior_provisional)
    bump(sub)
    return ok(serialize(dd), 200)


@app.route("/drawdowns/<i>/return", methods=["POST"])
def return_drawdown(i):
    uid, role = require(["GrantsManager"])
    dd = get_drawdown(i)
    if dd["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_DRAWDOWN_STATE", 409)
    sub = db.subawards[dd["subaward_id"]]
    prior_provisional = dd["provisional_reimbursable_cents"]
    dd["reimbursable_cents"] = 0
    dd["reviewed_by_user_id"] = uid
    dd["status"] = "RETURNED"
    bump(dd)
    sub["obligated_cents"] -= prior_provisional
    bump(sub)
    return ok(serialize(dd), 200)


@app.route("/drawdowns/<i>/resubmit", methods=["POST"])
def resubmit_drawdown(i):
    uid, role = require(["Subrecipient"])
    dd = get_drawdown(i)
    sub = db.subawards[dd["subaward_id"]]
    if sub["nonprofit_id"] != uid:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", 403)
    if dd["status"] != "RETURNED":
        raise ApiError("ERR_INVALID_DRAWDOWN_STATE", 409)
    if sub["status"] != "ACTIVE":
        raise ApiError("ERR_SUBAWARD_NOT_ACTIVE", 409)
    available = sub["total_budget_cents"] - sub["obligated_cents"]
    if dd["requested_amount_cents"] > available:
        raise ApiError("ERR_INSUFFICIENT_BUDGET", 409)
    provisional = min(dd["requested_amount_cents"], available)
    dd["provisional_reimbursable_cents"] = provisional
    dd["reimbursable_cents"] = provisional
    dd["_available_at_submit"] = available
    dd["status"] = "SUBMITTED"
    bump(dd)
    sub["obligated_cents"] += provisional
    bump(sub)
    return ok(serialize(dd), 200)


@app.route("/drawdowns/<i>/pay", methods=["POST"])
def pay_drawdown(i):
    require(["ProgramOfficer"])
    dd = get_drawdown(i)
    if dd["status"] != "APPROVED":
        raise ApiError("ERR_INVALID_DRAWDOWN_STATE", 409)
    sub = db.subawards[dd["subaward_id"]]
    dd["status"] = "PAID"
    bump(dd)
    sub["disbursed_cents"] += dd["reimbursable_cents"]
    bump(sub)
    np = db.nonprofits.get(sub["nonprofit_id"])
    if np:
        recompute_cumulative(np)
        bump(np)
    return ok(serialize(dd), 200)


# =====================================================================
# Risk Assessments
# =====================================================================
def latest_single_audit(np_id):
    audits = [a for a in db.single_audits.values() if a["nonprofit_id"] == np_id]
    if not audits:
        return None
    audits.sort(key=lambda a: (a["fiscal_year"], a["created_at"], a["_seq"]))
    return audits[-1]


@app.route("/subawards/<i>/risk-assessments", methods=["POST"])
def create_risk_assessment(i):
    uid, role = require(["GrantsManager"])
    sub = get_subaward(i)
    np = db.nonprofits[sub["nonprofit_id"]]
    np_id = sub["nonprofit_id"]
    # findings_component
    np_sub_ids = {s["id"] for s in subawards_of_nonprofit(np_id)}
    open_findings = 0
    for f in db.findings.values():
        if f["subaward_id"] in np_sub_ids and f["status"] in ("OPEN", "CAP_SUBMITTED", "CAP_ACCEPTED"):
            open_findings += 1
    findings_component = min(open_findings * 15, 45)
    # audit_component
    latest = latest_single_audit(np_id)
    if latest is None and np["cumulative_federal_expenditures_cents"] >= SINGLE_AUDIT_THRESHOLD_CENTS:
        audit_component = 30
    elif latest is None:
        audit_component = 10
    elif latest["status"] == "ACCEPTED" and latest["reported_finding_count"] > 0:
        audit_component = 20
    elif latest["status"] == "ACCEPTED":
        audit_component = 0
    else:
        audit_component = 15
    # velocity_component
    if sub["total_budget_cents"] > 0:
        paid_ratio = sub["disbursed_cents"] / sub["total_budget_cents"]
    else:
        paid_ratio = 0
    if paid_ratio > 0.90:
        velocity_component = 20
    elif paid_ratio >= 0.50:
        velocity_component = 10
    else:
        velocity_component = 0
    # size_component
    size_component = 10 if sub["total_budget_cents"] >= 50000000 else 5
    risk_score = min(findings_component + audit_component + velocity_component + size_component, 100)
    if risk_score >= 60:
        risk_tier = "HIGH"
    elif risk_score >= 30:
        risk_tier = "MODERATE"
    else:
        risk_tier = "LOW"
    ra = new_common({
        "subaward_id": i,
        "assessed_by_user_id": uid,
        "findings_component": findings_component,
        "audit_component": audit_component,
        "velocity_component": velocity_component,
        "size_component": size_component,
        "risk_score": risk_score,
        "risk_tier": risk_tier,
    })
    db.risk_assessments[ra["id"]] = ra
    np["latest_risk_tier"] = risk_tier
    bump(np)
    return ok(serialize(ra), 201)


@app.route("/subawards/<i>/risk-assessments", methods=["GET"])
def list_risk_assessments(i):
    require(["ProgramOfficer", "GrantsManager"])
    get_subaward(i)
    items = [r for r in db.risk_assessments.values() if r["subaward_id"] == i]
    page, pagination = make_list(items)
    return ok_list(page, pagination)


# =====================================================================
# Monitoring Visits
# =====================================================================
@app.route("/subawards/<i>/monitoring-visits", methods=["POST"])
def create_monitoring_visit(i):
    uid, role = require(["GrantsManager"])
    sub = get_subaward(i)
    body = body_json()
    scheduled_start = req_field(body, "scheduled_start")
    scheduled_end = req_field(body, "scheduled_end")
    ns, ne = check_period(scheduled_start, scheduled_end)
    # overlap vs same monitor (half-open, any subaward)
    for v in db.monitoring_visits.values():
        if v["monitor_user_id"] != uid:
            continue
        vs = parse_dt(v["scheduled_start"])
        ve = parse_dt(v["scheduled_end"])
        if ns < ve and vs < ne:
            raise ApiError("ERR_VISIT_OVERLAP", 409)
    visit = new_common({
        "subaward_id": i,
        "monitor_user_id": uid,
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
        "outcome": None,
        "finding_severity": None,
        "status": "SCHEDULED",
    })
    db.monitoring_visits[visit["id"]] = visit
    return ok(serialize(visit), 201)


@app.route("/monitoring-visits/<i>/conduct", methods=["POST"])
def conduct_visit(i):
    require(["GrantsManager"])
    visit = get_visit(i)
    if visit["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_VISIT_STATE", 409)
    sub = db.subawards[visit["subaward_id"]]
    if sub["status"] not in ("ACTIVE", "SUSPENDED"):
        raise ApiError("ERR_INVALID_SUBAWARD_STATE", 409)
    body = body_json()
    outcome = req_field(body, "outcome")
    if outcome not in OUTCOMES:
        raise ApiError("ERR_VALIDATION", 422)
    finding_severity = body.get("finding_severity")
    if finding_severity is not None and finding_severity not in SEVERITIES:
        raise ApiError("ERR_VALIDATION", 422)
    visit["outcome"] = outcome
    visit["finding_severity"] = finding_severity
    visit["status"] = "CONDUCTED"
    bump(visit)
    if finding_severity is not None:
        finding = new_common({
            "subaward_id": sub["id"],
            "source_kind": "MONITORING",
            "origin_ref_id": visit["id"],
            "severity": finding_severity,
            "description": f"Finding raised from monitoring visit {visit['id']}",
            "corrective_action_plan": None,
            "cap_due_date": None,
            "status": "OPEN",
        })
        db.findings[finding["id"]] = finding
        if finding_severity == "CRITICAL" and sub["status"] == "ACTIVE":
            sub["status"] = "SUSPENDED"
            cascade_return_pending(sub)
            bump(sub)
    return ok(serialize(visit), 200)


@app.route("/subawards/<i>/monitoring-visits", methods=["GET"])
def list_monitoring_visits(i):
    require(["ProgramOfficer", "GrantsManager", "Subrecipient"])
    get_subaward(i)
    status = request.args.get("status")
    items = [v for v in db.monitoring_visits.values() if v["subaward_id"] == i]
    if status is not None:
        items = [v for v in items if v["status"] == status]
    page, pagination = make_list(items)
    return ok_list(page, pagination)


# =====================================================================
# Performance Reports
# =====================================================================
@app.route("/subawards/<i>/performance-reports", methods=["POST"])
def create_performance_report(i):
    uid, role = require(["Subrecipient"])
    sub = get_subaward(i)
    if sub["nonprofit_id"] != uid:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", 403)
    body = body_json()
    rps = req_field(body, "reporting_period_start")
    rpe = req_field(body, "reporting_period_end")
    metric_target = req_field(body, "metric_target")
    metric_actual = req_field(body, "metric_actual")
    check_period(rps, rpe)
    metric_target = as_int(metric_target)
    metric_actual = as_int(metric_actual)
    report = new_common({
        "subaward_id": i,
        "reporting_period_start": rps,
        "reporting_period_end": rpe,
        "metric_target": metric_target,
        "metric_actual": metric_actual,
        "outcome_narrative": body.get("outcome_narrative"),
        "on_track": metric_actual >= metric_target,
    })
    db.performance_reports[report["id"]] = report
    return ok(serialize(report), 201)


@app.route("/subawards/<i>/performance-reports", methods=["GET"])
def list_performance_reports(i):
    require(["ProgramOfficer", "GrantsManager", "Subrecipient"])
    get_subaward(i)
    items = [p for p in db.performance_reports.values() if p["subaward_id"] == i]
    page, pagination = make_list(items)
    return ok_list(page, pagination)


# =====================================================================
# Single Audits
# =====================================================================
@app.route("/nonprofits/<i>/single-audits", methods=["POST"])
def create_single_audit(i):
    uid, role = require(["Subrecipient"])
    np = get_nonprofit(i)
    if np["id"] != uid:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", 403)
    body = body_json()
    fiscal_year = req_field(body, "fiscal_year")
    total_exp = req_field(body, "total_federal_expenditures_cents")
    fiscal_year = as_int(fiscal_year)
    if isinstance(total_exp, bool) or not isinstance(total_exp, int) or total_exp < 0:
        raise ApiError("ERR_VALIDATION", 422)
    material_weakness = body.get("material_weakness", False)
    if material_weakness is None:
        material_weakness = False
    if not isinstance(material_weakness, bool):
        raise ApiError("ERR_VALIDATION", 422)
    reported_finding_count = body.get("reported_finding_count", 0)
    if reported_finding_count is None:
        reported_finding_count = 0
    if isinstance(reported_finding_count, bool) or not isinstance(reported_finding_count, int) or reported_finding_count < 0:
        raise ApiError("ERR_VALIDATION", 422)
    audit = new_common({
        "nonprofit_id": i,
        "fiscal_year": fiscal_year,
        "total_federal_expenditures_cents": total_exp,
        "audit_required": total_exp >= SINGLE_AUDIT_THRESHOLD_CENTS,
        "material_weakness": material_weakness,
        "reported_finding_count": reported_finding_count,
        "status": "SUBMITTED",
    })
    db.single_audits[audit["id"]] = audit
    return ok(serialize(audit), 201)


@app.route("/single-audits/<i>/accept", methods=["POST"])
def accept_single_audit(i):
    require(["GrantsManager"])
    audit = get_single_audit(i)
    if audit["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_AUDIT_STATE", 409)
    audit["status"] = "ACCEPTED"
    bump(audit)
    if audit["material_weakness"]:
        eligible = [
            s for s in db.subawards.values()
            if s["nonprofit_id"] == audit["nonprofit_id"] and s["status"] == "ACTIVE"
        ]
        if eligible:
            eligible.sort(key=sort_key)
            target = eligible[0]
            finding = new_common({
                "subaward_id": target["id"],
                "source_kind": "SINGLE_AUDIT",
                "origin_ref_id": audit["id"],
                "severity": "HIGH",
                "description": f"Material weakness reported in single audit {audit['id']}",
                "corrective_action_plan": None,
                "cap_due_date": None,
                "status": "OPEN",
            })
            db.findings[finding["id"]] = finding
    return ok(serialize(audit), 200)


# =====================================================================
# Findings
# =====================================================================
@app.route("/subawards/<i>/findings", methods=["GET"])
def list_findings(i):
    require(["ProgramOfficer", "GrantsManager", "Subrecipient"])
    get_subaward(i)
    status = request.args.get("status")
    items = [f for f in db.findings.values() if f["subaward_id"] == i]
    if status is not None:
        items = [f for f in items if f["status"] == status]
    page, pagination = make_list(items)
    return ok_list(page, pagination)


@app.route("/findings/<i>/submit-cap", methods=["POST"])
def submit_cap(i):
    uid, role = require(["Subrecipient"])
    finding = get_finding(i)
    sub = db.subawards[finding["subaward_id"]]
    if sub["nonprofit_id"] != uid:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", 403)
    if finding["status"] != "OPEN":
        raise ApiError("ERR_INVALID_FINDING_STATE", 409)
    body = body_json()
    cap = req_field(body, "corrective_action_plan")
    finding["corrective_action_plan"] = cap
    finding["cap_due_date"] = body.get("cap_due_date")
    finding["status"] = "CAP_SUBMITTED"
    bump(finding)
    return ok(serialize(finding), 200)


@app.route("/findings/<i>/accept-cap", methods=["POST"])
def accept_cap(i):
    require(["GrantsManager"])
    finding = get_finding(i)
    if finding["status"] != "CAP_SUBMITTED":
        raise ApiError("ERR_INVALID_FINDING_STATE", 409)
    finding["status"] = "CAP_ACCEPTED"
    bump(finding)
    return ok(serialize(finding), 200)


@app.route("/findings/<i>/reject-cap", methods=["POST"])
def reject_cap(i):
    require(["GrantsManager"])
    finding = get_finding(i)
    if finding["status"] != "CAP_SUBMITTED":
        raise ApiError("ERR_INVALID_FINDING_STATE", 409)
    finding["corrective_action_plan"] = None
    finding["status"] = "OPEN"
    bump(finding)
    return ok(serialize(finding), 200)


@app.route("/findings/<i>/resolve", methods=["POST"])
def resolve_finding(i):
    require(["GrantsManager"])
    finding = get_finding(i)
    if finding["status"] != "CAP_ACCEPTED":
        raise ApiError("ERR_INVALID_FINDING_STATE", 409)
    finding["status"] = "RESOLVED"
    bump(finding)
    return ok(serialize(finding), 200)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
