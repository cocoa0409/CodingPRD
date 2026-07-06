import os
import uuid
import math
import random
import string
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import Flask, request, jsonify

app = Flask(__name__)

# ---------------------------------------------------------------------------
# In-memory store (fresh on every boot — no seeding)
# ---------------------------------------------------------------------------
committees = {}
contributions = {}
expenditures = {}
reporting_periods = {}
reports = {}
registrants = {}
clients = {}
lobbying_periods = {}
activities = {}

_seq_counter = 0

STATE = {"clock": datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)}

KNOWN_ROLES = {"Treasurer", "RegulatorAuditor", "LobbyRegistrant", "PublicViewer"}
ALL_ROLES = ["Treasurer", "RegulatorAuditor", "LobbyRegistrant", "PublicViewer"]

CONTRIBUTOR_TYPES = {"INDIVIDUAL", "PAC", "PARTY", "CORPORATION", "UNION", "FOREIGN_NATIONAL"}
COMMITTEE_TYPES = {"CANDIDATE", "PAC", "PARTY"}

CONTRIBUTION_LIMIT_CENTS = {
    "INDIVIDUAL": {"CANDIDATE": 330000, "PAC": 500000, "PARTY": 4130000},
    "PAC": {"CANDIDATE": 500000, "PAC": 500000, "PARTY": 1500000},
    "PARTY": {"CANDIDATE": 500000, "PAC": 500000, "PARTY": 0},
    "CORPORATION": {"PAC": 500000},
    "UNION": {"PAC": 500000},
    "FOREIGN_NATIONAL": {},
}

MATCH_RATE = Decimal("0.3333333333333333")
MATCH_CAP_CENTS = 20000

BASE_FEE_CENTS = 2500
PER_DAY_RATE_CENTS = {"SMALL": 1000, "MEDIUM": 5000, "LARGE": 20000}
MAX_PENALTY_CENTS = 1000000
SMALL_MAX_CENTS = 500000
MEDIUM_MAX_CENTS = 5000000


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------
class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def next_seq():
    global _seq_counter
    _seq_counter += 1
    return _seq_counter


def new_id():
    return str(uuid.uuid4())


def gen_req_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def now_iso():
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def fmt_iso(dt):
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_dt(s):
    if isinstance(s, datetime):
        dt = s
    else:
        x = str(s).strip()
        if x.endswith("Z") or x.endswith("z"):
            x = x[:-1] + "+00:00"
        dt = datetime.fromisoformat(x)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def is_parseable_dt(s):
    try:
        parse_dt(s)
        return True
    except Exception:
        return False


def get_json_body():
    body = request.get_json(silent=True)
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise ApiError("ERR_VALIDATION", 422, "request body must be a JSON object")
    return body


def serialize(entity):
    return {k: v for k, v in entity.items() if not k.startswith("_")}


def touch(entity):
    entity["updated_at"] = now_iso()
    entity["version"] = entity.get("version", 1) + 1


# ---------------------------------------------------------------------------
# Auth / RBAC
# ---------------------------------------------------------------------------
def require_auth(allowed_roles):
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in KNOWN_ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", 401, "missing or invalid authentication headers")
    if role not in allowed_roles:
        raise ApiError("ERR_UNAUTHORIZED", 403, "role not permitted for this operation")
    return uid, role


# ---------------------------------------------------------------------------
# Existence getters
# ---------------------------------------------------------------------------
def get_committee(cid):
    c = committees.get(cid)
    if c is None:
        raise ApiError("ERR_COMMITTEE_NOT_FOUND", 404, "committee not found")
    return c


def get_contribution(cid):
    c = contributions.get(cid)
    if c is None:
        raise ApiError("ERR_CONTRIBUTION_NOT_FOUND", 404, "contribution not found")
    return c


def get_report(rid):
    r = reports.get(rid)
    if r is None:
        raise ApiError("ERR_REPORT_NOT_FOUND", 404, "report not found")
    return r


def get_period(pid):
    p = reporting_periods.get(pid)
    if p is None:
        raise ApiError("ERR_PERIOD_NOT_FOUND", 404, "reporting period not found")
    return p


def get_registrant(rid):
    r = registrants.get(rid)
    if r is None:
        raise ApiError("ERR_REGISTRANT_NOT_FOUND", 404, "registrant not found")
    return r


def get_client(cid):
    c = clients.get(cid)
    if c is None:
        raise ApiError("ERR_CLIENT_NOT_FOUND", 404, "client not found")
    return c


def get_lobbying_period(pid):
    p = lobbying_periods.get(pid)
    if p is None:
        raise ApiError("ERR_LOBBYING_PERIOD_NOT_FOUND", 404, "lobbying period not found")
    return p


def get_activity(aid):
    a = activities.get(aid)
    if a is None:
        raise ApiError("ERR_ACTIVITY_NOT_FOUND", 404, "activity not found")
    return a


# ---------------------------------------------------------------------------
# Body validation
# ---------------------------------------------------------------------------
def validate_body(body, spec):
    """spec: dict field -> {'type': 'str'|'int'|'datetime', 'enum': set(optional)}"""
    for name, rule in spec.items():
        if name not in body or body[name] is None:
            raise ApiError("ERR_VALIDATION", 422, f"missing required field: {name}")
        val = body[name]
        t = rule["type"]
        if t == "str":
            if not isinstance(val, str):
                raise ApiError("ERR_VALIDATION", 422, f"field {name} must be a string")
        elif t == "int":
            if not isinstance(val, int) or isinstance(val, bool):
                raise ApiError("ERR_VALIDATION", 422, f"field {name} must be an integer")
        elif t == "datetime":
            if not isinstance(val, str) or not is_parseable_dt(val):
                raise ApiError("ERR_VALIDATION", 422, f"field {name} must be an ISO datetime")
        if "enum" in rule and val not in rule["enum"]:
            raise ApiError("ERR_VALIDATION", 422, f"field {name} has an invalid value")


# ---------------------------------------------------------------------------
# Response helpers
# ---------------------------------------------------------------------------
def success(data, code=200, pagination=None):
    meta = {"api_request_id": gen_req_id(), "api_request_timestamp": now_iso()}
    if pagination is not None:
        meta.update(pagination)
    rtype = "array" if isinstance(data, list) else "object"
    return jsonify({"meta": meta, "response_type": rtype, "data": data}), code


def parse_int_arg(name, default):
    raw = request.args.get(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except (ValueError, TypeError):
        return default


def paginate(items):
    items = sorted(items, key=lambda e: e["_seq"])
    total = len(items)
    limit = parse_int_arg("limit", 10)
    offset = parse_int_arg("offset", 0)
    limit = max(1, min(100, limit))
    offset = max(0, offset)
    page = items[offset:offset + limit]
    pg = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }
    return [serialize(e) for e in page], pg


@app.errorhandler(ApiError)
def handle_api_error(err):
    meta = {"api_request_id": gen_req_id(), "api_request_timestamp": now_iso()}
    body = {
        "meta": meta,
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


# ---------------------------------------------------------------------------
# Derived computations
# ---------------------------------------------------------------------------
def recompute_committee(committee):
    cid = committee["id"]
    receipts = sum(
        c["amount_cents"] for c in contributions.values()
        if c["committee_id"] == cid and c["settlement_status"] in ("RECORDED", "DEPOSITED")
    )
    disb = sum(
        e["amount_cents"] for e in expenditures.values() if e["committee_id"] == cid
    )
    pen = sum(
        r["penalty_amount_cents"] for r in reports.values()
        if r["committee_id"] == cid and r["penalty_status"] == "ASSESSED"
    )
    committee["total_receipts_cents"] = receipts
    committee["total_disbursements_cents"] = disb
    committee["total_penalties_cents"] = pen
    cash = receipts - disb - pen
    committee["cash_on_hand_cents"] = cash
    committee["solvency_status"] = "DEFICIT" if cash < 0 else "SOLVENT"


def recompute_registrant(registrant):
    rid = registrant["id"]
    committed = 0
    certified = 0
    for a in activities.values():
        if a["registrant_id"] != rid or a["status"] != "RECORDED":
            continue
        committed += a["amount_cents"]
        period = lobbying_periods.get(a["period_id"])
        if period is not None and period["status"] == "CLOSED":
            certified += a["amount_cents"]
    registrant["total_committed_spend_cents"] = committed
    registrant["total_certified_spend_cents"] = certified


def round_half_up_match(matchable_cents):
    return int((Decimal(matchable_cents) * MATCH_RATE).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def compute_report_totals(report, period, final):
    cid = report["committee_id"]
    start = parse_dt(period["period_start"])
    end = parse_dt(period["period_end"])
    if final:
        settle_ok = {"DEPOSITED"}
    else:
        settle_ok = {"RECORDED", "DEPOSITED"}

    receipts = 0
    matching = 0
    for c in contributions.values():
        if c["committee_id"] != cid:
            continue
        cdate = parse_dt(c["contribution_date"])
        if not (start <= cdate < end):
            continue
        if c["settlement_status"] not in settle_ok:
            continue
        receipts += c["amount_cents"]
        if c["matchable_amount_cents"] > 0:
            matching += round_half_up_match(c["matchable_amount_cents"])

    disb = 0
    for e in expenditures.values():
        if e["committee_id"] != cid:
            continue
        edate = parse_dt(e["expenditure_date"])
        if start <= edate < end:
            disb += e["amount_cents"]

    report["total_receipts_cents"] = receipts
    report["total_disbursements_cents"] = disb
    report["matching_funds_cents"] = matching


def penalty_tier(receipts):
    if receipts <= SMALL_MAX_CENTS:
        return "SMALL"
    if receipts <= MEDIUM_MAX_CENTS:
        return "MEDIUM"
    return "LARGE"


def compute_penalty(receipts, days_late):
    tier = penalty_tier(receipts)
    raw = BASE_FEE_CENTS + PER_DAY_RATE_CENTS[tier] * days_late
    return min(raw, MAX_PENALTY_CENTS)


# ===========================================================================
# Logical clock
# ===========================================================================
@app.route("/disclosure/_clock/set_current_utc", methods=["POST"])
def set_clock():
    require_auth(["RegulatorAuditor"])
    body = get_json_body()
    validate_body(body, {"to_iso8601": {"type": "datetime"}})
    STATE["clock"] = parse_dt(body["to_iso8601"])
    return success({}, 200)


# ===========================================================================
# Committee
# ===========================================================================
@app.route("/disclosure/committees", methods=["POST"])
def create_committee():
    require_auth(["Treasurer"])
    body = get_json_body()
    validate_body(body, {
        "name": {"type": "str"},
        "committee_type": {"type": "str", "enum": COMMITTEE_TYPES},
        "election_cycle": {"type": "str"},
        "jurisdiction": {"type": "str"},
        "treasurer_name": {"type": "str"},
    })
    cid = new_id()
    ts = now_iso()
    committee = {
        "id": cid,
        "name": body["name"],
        "committee_type": body["committee_type"],
        "election_cycle": body["election_cycle"],
        "jurisdiction": body["jurisdiction"],
        "treasurer_name": body["treasurer_name"],
        "status": "PENDING",
        "total_receipts_cents": 0,
        "total_disbursements_cents": 0,
        "total_penalties_cents": 0,
        "cash_on_hand_cents": 0,
        "solvency_status": "SOLVENT",
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": next_seq(),
    }
    committees[cid] = committee
    return success(serialize(committee), 201)


@app.route("/disclosure/committees", methods=["GET"])
def list_committees():
    require_auth(ALL_ROLES)
    items = list(committees.values())
    status = request.args.get("status")
    ctype = request.args.get("committee_type")
    juris = request.args.get("jurisdiction")
    if status is not None:
        items = [c for c in items if c["status"] == status]
    if ctype is not None:
        items = [c for c in items if c["committee_type"] == ctype]
    if juris is not None:
        items = [c for c in items if c["jurisdiction"] == juris]
    data, pg = paginate(items)
    return success(data, 200, pg)


@app.route("/disclosure/committees/<cid>", methods=["GET"])
def fetch_committee(cid):
    require_auth(ALL_ROLES)
    return success(serialize(get_committee(cid)), 200)


@app.route("/disclosure/committees/<cid>/approve", methods=["POST"])
def approve_committee(cid):
    require_auth(["RegulatorAuditor"])
    c = get_committee(cid)
    if c["status"] != "PENDING":
        raise ApiError("ERR_COMMITTEE_NOT_PENDING", 409, "approve requires committee PENDING")
    c["status"] = "ACTIVE"
    touch(c)
    return success(serialize(c), 200)


@app.route("/disclosure/committees/<cid>/suspend", methods=["POST"])
def suspend_committee(cid):
    require_auth(["RegulatorAuditor"])
    c = get_committee(cid)
    if c["status"] != "ACTIVE":
        raise ApiError("ERR_COMMITTEE_NOT_ACTIVE", 409, "suspend requires committee ACTIVE")
    c["status"] = "SUSPENDED"
    touch(c)
    return success(serialize(c), 200)


@app.route("/disclosure/committees/<cid>/terminate", methods=["POST"])
def terminate_committee(cid):
    uid, role = require_auth(["Treasurer"])
    c = get_committee(cid)
    if uid != c["id"]:
        raise ApiError("ERR_FORBIDDEN_OWNER", 403, "treasurer does not own this committee")
    if c["status"] not in ("ACTIVE", "SUSPENDED"):
        raise ApiError("ERR_COMMITTEE_NOT_ACTIVE", 409, "terminate requires committee ACTIVE or SUSPENDED")
    c["status"] = "TERMINATED"
    touch(c)
    return success(serialize(c), 200)


# ===========================================================================
# Contribution
# ===========================================================================
@app.route("/disclosure/committees/<cid>/contributions", methods=["POST"])
def create_contribution(cid):
    uid, role = require_auth(["Treasurer"])
    committee = get_committee(cid)
    if uid != committee["id"]:
        raise ApiError("ERR_FORBIDDEN_OWNER", 403, "treasurer does not own this committee")
    body = get_json_body()
    validate_body(body, {
        "contributor_ref": {"type": "str"},
        "contributor_name": {"type": "str"},
        "contributor_type": {"type": "str", "enum": CONTRIBUTOR_TYPES},
        "amount_cents": {"type": "int"},
        "contribution_date": {"type": "datetime"},
    })
    amount = body["amount_cents"]
    if amount <= 0:
        raise ApiError("ERR_INVALID_AMOUNT", 422, "amount_cents must be > 0")
    if committee["status"] != "ACTIVE":
        raise ApiError("ERR_COMMITTEE_NOT_ACTIVE", 409, "committee is not ACTIVE")

    ctype = body["contributor_type"]
    committee_type = committee["committee_type"]

    # source prohibition
    prohibited = False
    if ctype == "FOREIGN_NATIONAL":
        prohibited = True
    elif ctype in ("CORPORATION", "UNION") and committee_type != "PAC":
        prohibited = True
    if prohibited:
        raise ApiError("ERR_PROHIBITED_SOURCE", 409, "source prohibited for this committee type")

    # per-contributor per-cycle limit
    prior = sum(
        c["amount_cents"] for c in contributions.values()
        if c["committee_id"] == committee["id"]
        and c["contributor_ref"] == body["contributor_ref"]
        and c["settlement_status"] in ("RECORDED", "DEPOSITED")
    )
    limit = CONTRIBUTION_LIMIT_CENTS.get(ctype, {}).get(committee_type, 0)
    if prior + amount > limit:
        raise ApiError("ERR_CONTRIBUTION_LIMIT_EXCEEDED", 409, "per-cycle contribution limit exceeded")

    matchable = min(amount, MATCH_CAP_CENTS) if ctype == "INDIVIDUAL" else 0

    cid_new = new_id()
    ts = now_iso()
    contribution = {
        "id": cid_new,
        "committee_id": committee["id"],
        "contributor_ref": body["contributor_ref"],
        "contributor_name": body["contributor_name"],
        "contributor_type": ctype,
        "amount_cents": amount,
        "contribution_date": body["contribution_date"],
        "matchable_amount_cents": matchable,
        "settlement_status": "RECORDED",
        "review_status": "UNREVIEWED",
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": next_seq(),
    }
    contributions[cid_new] = contribution
    recompute_committee(committee)
    touch(committee)
    return success(serialize(contribution), 201)


@app.route("/disclosure/committees/<cid>/contributions", methods=["GET"])
def list_committee_contributions(cid):
    require_auth(ALL_ROLES)
    get_committee(cid)
    items = [c for c in contributions.values() if c["committee_id"] == cid]
    settlement = request.args.get("settlement_status")
    review = request.args.get("review_status")
    if settlement is not None:
        items = [c for c in items if c["settlement_status"] == settlement]
    if review is not None:
        items = [c for c in items if c["review_status"] == review]
    data, pg = paginate(items)
    return success(data, 200, pg)


@app.route("/disclosure/contributions", methods=["GET"])
def search_contributions():
    require_auth(ALL_ROLES)
    items = list(contributions.values())
    committee_id = request.args.get("committee_id")
    contributor_ref = request.args.get("contributor_ref")
    contributor_type = request.args.get("contributor_type")
    settlement = request.args.get("settlement_status")
    min_amount = parse_int_arg("min_amount_cents", None)
    if committee_id is not None:
        items = [c for c in items if c["committee_id"] == committee_id]
    if contributor_ref is not None:
        items = [c for c in items if c["contributor_ref"] == contributor_ref]
    if contributor_type is not None:
        items = [c for c in items if c["contributor_type"] == contributor_type]
    if settlement is not None:
        items = [c for c in items if c["settlement_status"] == settlement]
    if min_amount is not None:
        items = [c for c in items if c["amount_cents"] >= min_amount]
    data, pg = paginate(items)
    return success(data, 200, pg)


@app.route("/disclosure/contributions/<cid>", methods=["GET"])
def fetch_contribution(cid):
    require_auth(ALL_ROLES)
    return success(serialize(get_contribution(cid)), 200)


@app.route("/disclosure/contributions/<cid>/deposit", methods=["POST"])
def deposit_contribution(cid):
    uid, role = require_auth(["Treasurer"])
    c = get_contribution(cid)
    if uid != c["committee_id"]:
        raise ApiError("ERR_FORBIDDEN_OWNER", 403, "treasurer does not own this contribution")
    if c["settlement_status"] != "RECORDED":
        raise ApiError("ERR_CONTRIBUTION_NOT_RECORDED", 409, "deposit requires RECORDED")
    c["settlement_status"] = "DEPOSITED"
    touch(c)
    committee = committees.get(c["committee_id"])
    if committee is not None:
        recompute_committee(committee)
        touch(committee)
    return success(serialize(c), 200)


@app.route("/disclosure/contributions/<cid>/refund", methods=["POST"])
def refund_contribution(cid):
    uid, role = require_auth(["Treasurer"])
    c = get_contribution(cid)
    if uid != c["committee_id"]:
        raise ApiError("ERR_FORBIDDEN_OWNER", 403, "treasurer does not own this contribution")
    if c["settlement_status"] != "DEPOSITED":
        raise ApiError("ERR_CONTRIBUTION_NOT_DEPOSITED", 409, "refund requires DEPOSITED")
    c["settlement_status"] = "REFUNDED"
    touch(c)
    committee = committees.get(c["committee_id"])
    if committee is not None:
        recompute_committee(committee)
        touch(committee)
    return success(serialize(c), 200)


@app.route("/disclosure/contributions/<cid>/void", methods=["POST"])
def void_contribution(cid):
    require_auth(["RegulatorAuditor"])
    c = get_contribution(cid)
    if c["settlement_status"] not in ("RECORDED", "DEPOSITED"):
        raise ApiError("ERR_CONTRIBUTION_NOT_VOIDABLE", 409, "void requires RECORDED or DEPOSITED")
    c["settlement_status"] = "VOIDED"
    touch(c)
    committee = committees.get(c["committee_id"])
    if committee is not None:
        recompute_committee(committee)
        touch(committee)
    return success(serialize(c), 200)


@app.route("/disclosure/contributions/<cid>/flag", methods=["POST"])
def flag_contribution(cid):
    require_auth(["RegulatorAuditor"])
    c = get_contribution(cid)
    if c["review_status"] != "UNREVIEWED":
        raise ApiError("ERR_CONTRIBUTION_REVIEW_INVALID", 409, "flag requires UNREVIEWED")
    c["review_status"] = "FLAGGED"
    touch(c)
    committee = committees.get(c["committee_id"])
    if committee is not None:
        touch(committee)
    return success(serialize(c), 200)


@app.route("/disclosure/contributions/<cid>/clear", methods=["POST"])
def clear_contribution(cid):
    require_auth(["RegulatorAuditor"])
    c = get_contribution(cid)
    if c["review_status"] != "FLAGGED":
        raise ApiError("ERR_CONTRIBUTION_REVIEW_INVALID", 409, "clear requires FLAGGED")
    c["review_status"] = "CLEARED"
    touch(c)
    committee = committees.get(c["committee_id"])
    if committee is not None:
        touch(committee)
    return success(serialize(c), 200)


# ===========================================================================
# Expenditure
# ===========================================================================
@app.route("/disclosure/committees/<cid>/expenditures", methods=["POST"])
def create_expenditure(cid):
    uid, role = require_auth(["Treasurer"])
    committee = get_committee(cid)
    if uid != committee["id"]:
        raise ApiError("ERR_FORBIDDEN_OWNER", 403, "treasurer does not own this committee")
    body = get_json_body()
    validate_body(body, {
        "payee_name": {"type": "str"},
        "amount_cents": {"type": "int"},
        "expenditure_date": {"type": "datetime"},
        "purpose": {"type": "str"},
    })
    amount = body["amount_cents"]
    if amount <= 0:
        raise ApiError("ERR_INVALID_AMOUNT", 422, "amount_cents must be > 0")
    if committee["status"] != "ACTIVE":
        raise ApiError("ERR_COMMITTEE_NOT_ACTIVE", 409, "committee is not ACTIVE")
    eid = new_id()
    ts = now_iso()
    expenditure = {
        "id": eid,
        "committee_id": committee["id"],
        "payee_name": body["payee_name"],
        "amount_cents": amount,
        "expenditure_date": body["expenditure_date"],
        "purpose": body["purpose"],
        "created_at": ts,
        "_seq": next_seq(),
    }
    expenditures[eid] = expenditure
    recompute_committee(committee)
    touch(committee)
    return success(serialize(expenditure), 201)


@app.route("/disclosure/committees/<cid>/expenditures", methods=["GET"])
def list_committee_expenditures(cid):
    require_auth(ALL_ROLES)
    get_committee(cid)
    items = [e for e in expenditures.values() if e["committee_id"] == cid]
    data, pg = paginate(items)
    return success(data, 200, pg)


# ===========================================================================
# ReportingPeriod (campaign finance)
# ===========================================================================
@app.route("/disclosure/reporting-periods", methods=["POST"])
def create_reporting_period():
    require_auth(["RegulatorAuditor"])
    body = get_json_body()
    validate_body(body, {
        "jurisdiction": {"type": "str"},
        "election_cycle": {"type": "str"},
        "period_label": {"type": "str"},
        "period_start": {"type": "datetime"},
        "period_end": {"type": "datetime"},
        "filing_deadline": {"type": "datetime"},
    })
    new_start = parse_dt(body["period_start"])
    new_end = parse_dt(body["period_end"])
    # half-open overlap scoped to (jurisdiction, election_cycle)
    for p in reporting_periods.values():
        if p["jurisdiction"] != body["jurisdiction"] or p["election_cycle"] != body["election_cycle"]:
            continue
        ex_start = parse_dt(p["period_start"])
        ex_end = parse_dt(p["period_end"])
        if new_start < ex_end and ex_start < new_end:
            raise ApiError("ERR_PERIOD_OVERLAP", 409, "reporting period overlaps an existing one")
    pid = new_id()
    ts = now_iso()
    period = {
        "id": pid,
        "jurisdiction": body["jurisdiction"],
        "election_cycle": body["election_cycle"],
        "period_label": body["period_label"],
        "period_start": body["period_start"],
        "period_end": body["period_end"],
        "filing_deadline": body["filing_deadline"],
        "status": "OPEN",
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": next_seq(),
    }
    reporting_periods[pid] = period
    return success(serialize(period), 201)


@app.route("/disclosure/reporting-periods/<pid>", methods=["GET"])
def fetch_reporting_period(pid):
    require_auth(ALL_ROLES)
    return success(serialize(get_period(pid)), 200)


@app.route("/disclosure/reporting-periods/<pid>/close", methods=["POST"])
def close_reporting_period(pid):
    require_auth(["RegulatorAuditor"])
    p = get_period(pid)
    if p["status"] != "OPEN":
        raise ApiError("ERR_PERIOD_NOT_OPEN", 409, "close requires OPEN")
    p["status"] = "CLOSED"
    touch(p)
    return success(serialize(p), 200)


@app.route("/disclosure/reporting-periods/<pid>/reports", methods=["GET"])
def list_period_reports(pid):
    require_auth(ALL_ROLES)
    get_period(pid)
    items = [r for r in reports.values() if r["period_id"] == pid]
    committee_id = request.args.get("committee_id")
    if committee_id is not None:
        items = [r for r in items if r["committee_id"] == committee_id]
    data, pg = paginate(items)
    return success(data, 200, pg)


# ===========================================================================
# Report
# ===========================================================================
@app.route("/disclosure/committees/<cid>/reports", methods=["POST"])
def create_report(cid):
    uid, role = require_auth(["Treasurer"])
    committee = get_committee(cid)
    if uid != committee["id"]:
        raise ApiError("ERR_FORBIDDEN_OWNER", 403, "treasurer does not own this committee")
    body = get_json_body()
    validate_body(body, {
        "period_id": {"type": "str"},
        "expected_committee_version": {"type": "int"},
    })
    period = get_period(body["period_id"])
    # OCC
    if body["expected_committee_version"] != committee["version"]:
        raise ApiError("ERR_STALE_VERSION", 412, "expected_committee_version does not match committee version")
    if committee["status"] != "ACTIVE":
        raise ApiError("ERR_COMMITTEE_NOT_ACTIVE", 409, "committee is not ACTIVE")

    # supersede any prior DRAFT report for same (committee, period)
    for r in reports.values():
        if r["committee_id"] == cid and r["period_id"] == period["id"] and r["status"] == "DRAFT":
            r["status"] = "SUPERSEDED"
            touch(r)

    rid = new_id()
    ts = now_iso()
    report = {
        "id": rid,
        "committee_id": cid,
        "period_id": period["id"],
        "supersedes_report_id": None,
        "amendment_seq": 0,
        "status": "DRAFT",
        "total_receipts_cents": 0,
        "total_disbursements_cents": 0,
        "matching_funds_cents": 0,
        "filed_at": None,
        "is_late": False,
        "days_late": 0,
        "penalty_status": "NONE",
        "penalty_amount_cents": 0,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": next_seq(),
    }
    compute_report_totals(report, period, final=False)
    reports[rid] = report
    touch(committee)
    return success(serialize(report), 201)


@app.route("/disclosure/committees/<cid>/reports", methods=["GET"])
def list_committee_reports(cid):
    require_auth(ALL_ROLES)
    get_committee(cid)
    items = [r for r in reports.values() if r["committee_id"] == cid]
    status = request.args.get("status")
    period_id = request.args.get("period_id")
    if status is not None:
        items = [r for r in items if r["status"] == status]
    if period_id is not None:
        items = [r for r in items if r["period_id"] == period_id]
    data, pg = paginate(items)
    return success(data, 200, pg)


@app.route("/disclosure/reports/<rid>", methods=["GET"])
def fetch_report(rid):
    require_auth(ALL_ROLES)
    return success(serialize(get_report(rid)), 200)


@app.route("/disclosure/reports/<rid>/revisions", methods=["GET"])
def list_report_revisions(rid):
    require_auth(ALL_ROLES)
    get_report(rid)
    items = [r for r in reports.values() if r["supersedes_report_id"] == rid]
    data, pg = paginate(items)
    return success(data, 200, pg)


@app.route("/disclosure/reports/<rid>/file", methods=["POST"])
def file_report(rid):
    uid, role = require_auth(["Treasurer"])
    report = get_report(rid)
    committee = committees.get(report["committee_id"])
    if committee is None or uid != committee["id"]:
        raise ApiError("ERR_FORBIDDEN_OWNER", 403, "treasurer does not own this report")
    if report["status"] != "DRAFT":
        raise ApiError("ERR_REPORT_NOT_DRAFT", 409, "file requires DRAFT")
    period = reporting_periods.get(report["period_id"])
    if period is None or period["status"] != "CLOSED":
        raise ApiError("ERR_PERIOD_NOT_CLOSED", 409, "filing requires the period to be CLOSED")

    compute_report_totals(report, period, final=True)
    clock = STATE["clock"]
    deadline = parse_dt(period["filing_deadline"])
    report["filed_at"] = fmt_iso(clock)
    report["status"] = "FILED"
    if clock > deadline:
        report["is_late"] = True
        delta = (clock - deadline).total_seconds()
        report["days_late"] = int(math.ceil(delta / 86400.0))
        report["penalty_status"] = "ASSESSED"
        report["penalty_amount_cents"] = compute_penalty(report["total_receipts_cents"], report["days_late"])
    else:
        report["is_late"] = False
        report["days_late"] = 0
        report["penalty_status"] = "NONE"
        report["penalty_amount_cents"] = 0
    touch(report)
    recompute_committee(committee)
    touch(committee)
    return success(serialize(report), 200)


@app.route("/disclosure/reports/<rid>/amend", methods=["POST"])
def amend_report(rid):
    uid, role = require_auth(["Treasurer"])
    report = get_report(rid)
    committee = committees.get(report["committee_id"])
    if committee is None or uid != committee["id"]:
        raise ApiError("ERR_FORBIDDEN_OWNER", 403, "treasurer does not own this report")
    if report["status"] != "FILED":
        raise ApiError("ERR_REPORT_NOT_FILED", 409, "amend requires FILED")
    report["status"] = "SUPERSEDED"
    touch(report)

    period = reporting_periods.get(report["period_id"])
    new_rid = new_id()
    ts = now_iso()
    amendment = {
        "id": new_rid,
        "committee_id": report["committee_id"],
        "period_id": report["period_id"],
        "supersedes_report_id": report["id"],
        "amendment_seq": report["amendment_seq"] + 1,
        "status": "DRAFT",
        "total_receipts_cents": 0,
        "total_disbursements_cents": 0,
        "matching_funds_cents": 0,
        "filed_at": None,
        "is_late": False,
        "days_late": 0,
        "penalty_status": "NONE",
        "penalty_amount_cents": 0,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": next_seq(),
    }
    if period is not None:
        compute_report_totals(amendment, period, final=False)
    reports[new_rid] = amendment
    touch(committee)
    return success(serialize(amendment), 201)


@app.route("/disclosure/reports/<rid>/audit-open", methods=["POST"])
def audit_open_report(rid):
    require_auth(["RegulatorAuditor"])
    report = get_report(rid)
    if report["status"] != "FILED":
        raise ApiError("ERR_REPORT_NOT_FILED", 409, "audit-open requires FILED")
    report["status"] = "UNDER_AUDIT"
    touch(report)
    return success(serialize(report), 200)


@app.route("/disclosure/reports/<rid>/audit-close", methods=["POST"])
def audit_close_report(rid):
    require_auth(["RegulatorAuditor"])
    report = get_report(rid)
    if report["status"] != "UNDER_AUDIT":
        raise ApiError("ERR_REPORT_NOT_UNDER_AUDIT", 409, "audit-close requires UNDER_AUDIT")
    report["status"] = "FILED"
    touch(report)
    return success(serialize(report), 200)


@app.route("/disclosure/reports/<rid>/penalty/waive", methods=["POST"])
def waive_penalty(rid):
    require_auth(["RegulatorAuditor"])
    report = get_report(rid)
    if report["penalty_status"] != "ASSESSED":
        raise ApiError("ERR_PENALTY_NOT_ASSESSED", 409, "waive requires penalty ASSESSED")
    report["penalty_status"] = "WAIVED"
    touch(report)
    committee = committees.get(report["committee_id"])
    if committee is not None:
        recompute_committee(committee)
        touch(committee)
    return success(serialize(report), 200)


# ===========================================================================
# LobbyingRegistrant
# ===========================================================================
@app.route("/disclosure/registrants", methods=["POST"])
def create_registrant():
    require_auth(["LobbyRegistrant"])
    body = get_json_body()
    validate_body(body, {
        "name": {"type": "str"},
        "registrant_contact": {"type": "str"},
        "jurisdiction": {"type": "str"},
    })
    rid = new_id()
    ts = now_iso()
    registrant = {
        "id": rid,
        "name": body["name"],
        "registrant_contact": body["registrant_contact"],
        "jurisdiction": body["jurisdiction"],
        "status": "ACTIVE",
        "total_committed_spend_cents": 0,
        "total_certified_spend_cents": 0,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": next_seq(),
    }
    registrants[rid] = registrant
    return success(serialize(registrant), 201)


@app.route("/disclosure/registrants/<rid>", methods=["GET"])
def fetch_registrant(rid):
    require_auth(ALL_ROLES)
    return success(serialize(get_registrant(rid)), 200)


@app.route("/disclosure/registrants/<rid>/terminate", methods=["POST"])
def terminate_registrant(rid):
    uid, role = require_auth(["LobbyRegistrant"])
    r = get_registrant(rid)
    if uid != r["id"]:
        raise ApiError("ERR_FORBIDDEN_OWNER", 403, "registrant does not own this registration")
    if r["status"] != "ACTIVE":
        raise ApiError("ERR_REGISTRANT_NOT_ACTIVE", 409, "terminate requires ACTIVE")
    r["status"] = "TERMINATED"
    touch(r)
    return success(serialize(r), 200)


# ===========================================================================
# Client
# ===========================================================================
@app.route("/disclosure/registrants/<rid>/clients", methods=["POST"])
def create_client(rid):
    uid, role = require_auth(["LobbyRegistrant"])
    registrant = get_registrant(rid)
    if uid != registrant["id"]:
        raise ApiError("ERR_FORBIDDEN_OWNER", 403, "registrant does not own this registrant")
    body = get_json_body()
    validate_body(body, {"client_name": {"type": "str"}})
    if registrant["status"] != "ACTIVE":
        raise ApiError("ERR_REGISTRANT_NOT_ACTIVE", 409, "registrant is not ACTIVE")
    cid = new_id()
    ts = now_iso()
    client = {
        "id": cid,
        "registrant_id": registrant["id"],
        "client_name": body["client_name"],
        "status": "ACTIVE",
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": next_seq(),
    }
    clients[cid] = client
    return success(serialize(client), 201)


@app.route("/disclosure/registrants/<rid>/clients", methods=["GET"])
def list_registrant_clients(rid):
    require_auth(ALL_ROLES)
    get_registrant(rid)
    items = [c for c in clients.values() if c["registrant_id"] == rid]
    status = request.args.get("status")
    if status is not None:
        items = [c for c in items if c["status"] == status]
    data, pg = paginate(items)
    return success(data, 200, pg)


@app.route("/disclosure/clients/<cid>", methods=["GET"])
def fetch_client(cid):
    require_auth(ALL_ROLES)
    return success(serialize(get_client(cid)), 200)


@app.route("/disclosure/clients/<cid>/deactivate", methods=["POST"])
def deactivate_client(cid):
    uid, role = require_auth(["LobbyRegistrant"])
    client = get_client(cid)
    if uid != client["registrant_id"]:
        raise ApiError("ERR_FORBIDDEN_OWNER", 403, "registrant does not own this client")
    if client["status"] != "ACTIVE":
        raise ApiError("ERR_CLIENT_NOT_ACTIVE", 409, "deactivate requires ACTIVE")
    client["status"] = "INACTIVE"
    touch(client)
    return success(serialize(client), 200)


# ===========================================================================
# LobbyingReportingPeriod
# ===========================================================================
@app.route("/disclosure/lobbying-periods", methods=["POST"])
def create_lobbying_period():
    require_auth(["RegulatorAuditor"])
    body = get_json_body()
    validate_body(body, {
        "jurisdiction": {"type": "str"},
        "period_label": {"type": "str"},
        "period_start": {"type": "datetime"},
        "period_end": {"type": "datetime"},
        "filing_deadline": {"type": "datetime"},
    })
    new_start = parse_dt(body["period_start"])
    new_end = parse_dt(body["period_end"])
    # closed-interval overlap scoped to jurisdiction (adjacency conflicts)
    for p in lobbying_periods.values():
        if p["jurisdiction"] != body["jurisdiction"]:
            continue
        ex_start = parse_dt(p["period_start"])
        ex_end = parse_dt(p["period_end"])
        if new_start <= ex_end and ex_start <= new_end:
            raise ApiError("ERR_PERIOD_OVERLAP", 409, "lobbying period overlaps an existing one")
    pid = new_id()
    ts = now_iso()
    period = {
        "id": pid,
        "jurisdiction": body["jurisdiction"],
        "period_label": body["period_label"],
        "period_start": body["period_start"],
        "period_end": body["period_end"],
        "filing_deadline": body["filing_deadline"],
        "status": "OPEN",
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": next_seq(),
    }
    lobbying_periods[pid] = period
    return success(serialize(period), 201)


@app.route("/disclosure/lobbying-periods/<pid>", methods=["GET"])
def fetch_lobbying_period(pid):
    require_auth(ALL_ROLES)
    return success(serialize(get_lobbying_period(pid)), 200)


@app.route("/disclosure/lobbying-periods/<pid>/close", methods=["POST"])
def close_lobbying_period(pid):
    require_auth(["RegulatorAuditor"])
    p = get_lobbying_period(pid)
    if p["status"] != "OPEN":
        raise ApiError("ERR_PERIOD_NOT_OPEN", 409, "close requires OPEN")
    p["status"] = "CLOSED"
    touch(p)
    # certify spend: recompute affected registrants
    affected = set()
    for a in activities.values():
        if a["period_id"] == pid and a["status"] == "RECORDED":
            affected.add(a["registrant_id"])
    for rid in affected:
        registrant = registrants.get(rid)
        if registrant is not None:
            recompute_registrant(registrant)
            touch(registrant)
    return success(serialize(p), 200)


@app.route("/disclosure/lobbying-periods/<pid>/activities", methods=["GET"])
def list_lobbying_period_activities(pid):
    require_auth(ALL_ROLES)
    get_lobbying_period(pid)
    items = [a for a in activities.values() if a["period_id"] == pid]
    registrant_id = request.args.get("registrant_id")
    if registrant_id is not None:
        items = [a for a in items if a["registrant_id"] == registrant_id]
    data, pg = paginate(items)
    return success(data, 200, pg)


# ===========================================================================
# LobbyingActivity
# ===========================================================================
@app.route("/disclosure/registrants/<rid>/activities", methods=["POST"])
def create_activity(rid):
    uid, role = require_auth(["LobbyRegistrant"])
    registrant = get_registrant(rid)
    if uid != registrant["id"]:
        raise ApiError("ERR_FORBIDDEN_OWNER", 403, "registrant does not own this registrant")
    body = get_json_body()
    validate_body(body, {
        "client_id": {"type": "str"},
        "period_id": {"type": "str"},
        "lobbyist_name": {"type": "str"},
        "subject": {"type": "str"},
        "amount_cents": {"type": "int"},
        "activity_date": {"type": "datetime"},
    })
    client = get_client(body["client_id"])
    period = get_lobbying_period(body["period_id"])
    amount = body["amount_cents"]
    if amount <= 0:
        raise ApiError("ERR_INVALID_AMOUNT", 422, "amount_cents must be > 0")
    if registrant["status"] != "ACTIVE":
        raise ApiError("ERR_REGISTRANT_NOT_ACTIVE", 409, "registrant is not ACTIVE")
    if client["status"] != "ACTIVE":
        raise ApiError("ERR_CLIENT_NOT_ACTIVE", 409, "client is not ACTIVE")

    # activity overlap: same (registrant, client), same day, another RECORDED activity
    new_day = parse_dt(body["activity_date"]).date()
    for a in activities.values():
        if a["registrant_id"] != registrant["id"] or a["client_id"] != client["id"]:
            continue
        if a["status"] != "RECORDED":
            continue
        if parse_dt(a["activity_date"]).date() == new_day:
            raise ApiError("ERR_ACTIVITY_OVERLAP", 409, "activity overlaps another recorded activity")

    aid = new_id()
    ts = now_iso()
    activity = {
        "id": aid,
        "registrant_id": registrant["id"],
        "client_id": client["id"],
        "period_id": period["id"],
        "lobbyist_name": body["lobbyist_name"],
        "subject": body["subject"],
        "amount_cents": amount,
        "activity_date": body["activity_date"],
        "status": "RECORDED",
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": next_seq(),
    }
    activities[aid] = activity
    recompute_registrant(registrant)
    touch(registrant)
    return success(serialize(activity), 201)


@app.route("/disclosure/registrants/<rid>/activities", methods=["GET"])
def list_registrant_activities(rid):
    require_auth(ALL_ROLES)
    get_registrant(rid)
    items = [a for a in activities.values() if a["registrant_id"] == rid]
    client_id = request.args.get("client_id")
    period_id = request.args.get("period_id")
    status = request.args.get("status")
    if client_id is not None:
        items = [a for a in items if a["client_id"] == client_id]
    if period_id is not None:
        items = [a for a in items if a["period_id"] == period_id]
    if status is not None:
        items = [a for a in items if a["status"] == status]
    data, pg = paginate(items)
    return success(data, 200, pg)


@app.route("/disclosure/clients/<cid>/activities", methods=["GET"])
def list_client_activities(cid):
    require_auth(ALL_ROLES)
    get_client(cid)
    items = [a for a in activities.values() if a["client_id"] == cid]
    status = request.args.get("status")
    if status is not None:
        items = [a for a in items if a["status"] == status]
    data, pg = paginate(items)
    return success(data, 200, pg)


@app.route("/disclosure/activities/<aid>", methods=["GET"])
def fetch_activity(aid):
    require_auth(ALL_ROLES)
    return success(serialize(get_activity(aid)), 200)


@app.route("/disclosure/activities", methods=["GET"])
def search_activities():
    require_auth(ALL_ROLES)
    items = list(activities.values())
    registrant_id = request.args.get("registrant_id")
    client_id = request.args.get("client_id")
    status = request.args.get("status")
    min_amount = parse_int_arg("min_amount_cents", None)
    if registrant_id is not None:
        items = [a for a in items if a["registrant_id"] == registrant_id]
    if client_id is not None:
        items = [a for a in items if a["client_id"] == client_id]
    if status is not None:
        items = [a for a in items if a["status"] == status]
    if min_amount is not None:
        items = [a for a in items if a["amount_cents"] >= min_amount]
    data, pg = paginate(items)
    return success(data, 200, pg)


@app.route("/disclosure/activities/<aid>/void", methods=["POST"])
def void_activity(aid):
    uid, role = require_auth(["LobbyRegistrant"])
    activity = get_activity(aid)
    if uid != activity["registrant_id"]:
        raise ApiError("ERR_FORBIDDEN_OWNER", 403, "registrant does not own this activity")
    if activity["status"] != "RECORDED":
        raise ApiError("ERR_ACTIVITY_NOT_VOIDABLE", 409, "void requires RECORDED")
    activity["status"] = "VOIDED"
    touch(activity)
    registrant = registrants.get(activity["registrant_id"])
    if registrant is not None:
        recompute_registrant(registrant)
        touch(registrant)
    return success(serialize(activity), 200)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
