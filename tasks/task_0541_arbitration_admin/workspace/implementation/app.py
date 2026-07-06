"""Mediation & Arbitration Case Administration API (task_0541).

In-memory only. The store starts empty on every boot; nothing is seeded.
"""
import os
import re
import random
import string
import uuid
import itertools
from decimal import Decimal, ROUND_HALF_UP, ROUND_FLOOR
from datetime import datetime, timezone, timedelta

from flask import Flask, request, jsonify

app = Flask(__name__)
app.url_map.strict_slashes = False

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
KNOWN_ROLES = {"CaseAdministrator", "Party", "Neutral"}

CASE_TYPE = {"ARBITRATION", "MEDIATION"}
PARTY_ROLE = {"CLAIMANT", "RESPONDENT"}
NEUTRAL_TYPE = {"ARBITRATOR", "MEDIATOR", "BOTH"}
ROSTER_STATUS = {"ACTIVE", "SUSPENDED", "RETIRED"}
RANK_ACTION = {"STRIKE", "RANK"}
HEARING_TYPE = {"PREHEARING", "EVIDENTIARY", "MEDIATION_SESSION"}
EXCHANGE_TYPE = {"EXHIBITS", "WITNESS_LIST", "BRIEFS"}
AWARD_TYPE = {"MONETARY", "SETTLEMENT", "DISMISSAL"}
APPEAL_GROUND = {"EVIDENT_PARTIALITY", "EXCEEDED_POWERS", "PROCEDURAL"}

CASE_STATUSES = {"FILED", "SELECTION", "APPOINTED", "HEARING",
                 "AWARD_ISSUED", "CLOSED", "WITHDRAWN"}
CANDIDATE_STATUSES = {"PROPOSED", "DISCLOSED", "CLEARED", "OBJECTED",
                      "DISQUALIFIED", "APPOINTED", "NOT_SELECTED"}
HEARING_STATUSES = {"SCHEDULED", "HELD", "CANCELLED"}
AWARD_STATUSES = {"DRAFT", "ISSUED", "FINAL", "VACATED"}
APPEAL_STATUSES = {"FILED", "UNDER_REVIEW", "GRANTED", "DENIED"}

BASE = {"TIER_1": 75000, "TIER_2": 175000, "TIER_3": 400000, "TIER_4": 700000}
TIER_2_FLOOR = 1000000
TIER_3_FLOOR = 7500000
TIER_4_FLOOR = 50000000

HEARING_NOTICE_DAYS = 7
APPEAL_WINDOW_DAYS = 30
NEUTRAL_BUFFER_MINUTES = 30

CLOCK_DEFAULT = "2026-05-01T00:00:00Z"

# ---------------------------------------------------------------------------
# In-memory store (empty on boot)
# ---------------------------------------------------------------------------
STORE = {
    "cases": {},
    "parties": {},
    "neutrals": {},
    "candidates": {},
    "rankings": {},
    "hearings": {},
    "exchanges": {},
    "deposits": {},
    "feecharges": {},
    "awards": {},
    "appeals": {},
}
_seq_counter = itertools.count(1)


def next_seq():
    return next(_seq_counter)


# Logical clock (server-held). Defaults to CLOCK_DEFAULT until advanced.
_clock = None  # datetime aware UTC


def clock_now():
    global _clock
    if _clock is None:
        _clock = parse_iso(CLOCK_DEFAULT)
    return _clock


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------
class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


def err(error_id, status, msg=None):
    raise ApiError(error_id, status, msg)


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------
_ISO_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.(\d+))?(Z|[+-]\d{2}:\d{2})$"
)


def parse_iso(s):
    if not isinstance(s, str):
        raise ValueError("not a string")
    m = _ISO_RE.match(s.strip())
    if not m:
        raise ValueError("bad iso8601: %r" % s)
    year, mon, day, hh, mm, ss = (int(m.group(i)) for i in range(1, 7))
    frac = m.group(7)
    micros = 0
    if frac:
        micros = int((frac + "000000")[:6])
    tz = m.group(8)
    if tz == "Z":
        offset = timezone.utc
    else:
        sign = 1 if tz[0] == "+" else -1
        oh = int(tz[1:3])
        om = int(tz[4:6])
        offset = timezone(sign * timedelta(hours=oh, minutes=om))
    dt = datetime(year, mon, day, hh, mm, ss, micros, tzinfo=offset)
    return dt.astimezone(timezone.utc)


def fmt_ts(dt):
    dt = dt.astimezone(timezone.utc)
    ms = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + ".%03dZ" % ms


def now_ts():
    return fmt_ts(datetime.now(timezone.utc))


# ---------------------------------------------------------------------------
# Money helpers
# ---------------------------------------------------------------------------
def round_half_up(dec):
    return int(Decimal(dec).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def tier_of(amount_cents):
    if amount_cents < TIER_2_FLOOR:
        return "TIER_1"
    if amount_cents < TIER_3_FLOOR:
        return "TIER_2"
    if amount_cents < TIER_4_FLOOR:
        return "TIER_3"
    return "TIER_4"


def compute_admin_fee(amount_cents, case_type, panel_size):
    base = BASE[tier_of(amount_cents)]
    ctm = Decimal("0.5") if case_type == "MEDIATION" else Decimal("1")
    pm = Decimal("1.5") if panel_size == 3 else Decimal("1")
    return round_half_up(Decimal(base) * ctm * pm)


# ---------------------------------------------------------------------------
# Response envelope
# ---------------------------------------------------------------------------
def gen_req_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def base_meta():
    return {"api_request_id": gen_req_id(), "api_request_timestamp": now_ts()}


def public(entity):
    return {k: v for k, v in entity.items() if not k.startswith("_")}


def ok(data, code=200):
    body = {"meta": base_meta(), "response_type": "object", "data": data}
    return jsonify(body), code


def ok_list(items, pagination):
    meta = base_meta()
    meta.update(pagination)
    body = {"meta": meta, "response_type": "array",
            "data": [public(i) for i in items]}
    return jsonify(body), 200


@app.errorhandler(ApiError)
def handle_api_error(e):
    body = {
        "meta": base_meta(),
        "response_type": "error",
        "data": {"error_id": e.error_id, "message": e.message},
    }
    return jsonify(body), e.http_status


@app.errorhandler(404)
def handle_404(e):
    body = {
        "meta": base_meta(),
        "response_type": "error",
        "data": {"error_id": "ERR_NOT_FOUND", "message": "Resource not found"},
    }
    return jsonify(body), 404


@app.errorhandler(405)
def handle_405(e):
    body = {
        "meta": base_meta(),
        "response_type": "error",
        "data": {"error_id": "ERR_NOT_FOUND", "message": "Method not allowed"},
    }
    return jsonify(body), 404


# ---------------------------------------------------------------------------
# Auth / request helpers
# ---------------------------------------------------------------------------
def auth(allowed_roles):
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in KNOWN_ROLES:
        err("ERR_UNAUTHENTICATED", 401, "Missing or unknown authentication headers")
    if role not in allowed_roles:
        err("ERR_UNAUTHORIZED", 403, "Role not permitted for this operation")
    return uid, role


def get_body():
    d = request.get_json(silent=True)
    return d if isinstance(d, dict) else {}


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def is_num(v):
    return (isinstance(v, (int, float)) and not isinstance(v, bool))


def require_str(d, key):
    if key not in d or not isinstance(d[key], str) or d[key] == "":
        err("ERR_VALIDATION", 400, "Missing or invalid field: %s" % key)
    return d[key]


def require_int(d, key):
    if key not in d or not is_int(d[key]):
        err("ERR_VALIDATION", 400, "Missing or invalid integer field: %s" % key)
    return d[key]


def require_enum(d, key, allowed):
    if key not in d or not isinstance(d[key], str):
        err("ERR_VALIDATION", 400, "Missing field: %s" % key)
    if d[key] not in allowed:
        err("ERR_INVALID_ENUM", 422, "Invalid enum value for %s" % key)
    return d[key]


def fk_lookup(collection, id_val, key):
    if not isinstance(id_val, str) or id_val == "":
        err("ERR_VALIDATION", 400, "Missing or invalid FK field: %s" % key)
    obj = STORE[collection].get(id_val)
    if obj is None:
        err("ERR_NOT_FOUND", 404, "Referenced %s not found" % key)
    return obj


def path_lookup(collection, id_val):
    obj = STORE[collection].get(id_val)
    if obj is None:
        err("ERR_NOT_FOUND", 404, "Resource not found")
    return obj


def stamp_new():
    ts = now_ts()
    return {"id": uuid.uuid4().hex, "created_at": ts, "updated_at": ts,
            "version": 1, "_seq": next_seq()}


def touch(entity):
    entity["version"] += 1
    entity["updated_at"] = now_ts()


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------
def parse_pagination():
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args:
        try:
            limit = int(args["limit"])
        except (ValueError, TypeError):
            err("ERR_PAGINATION_INVALID", 400, "limit must be an integer")
        if limit < 1 or limit > 100:
            err("ERR_PAGINATION_INVALID", 400, "limit out of range")
    if "offset" in args:
        try:
            offset = int(args["offset"])
        except (ValueError, TypeError):
            err("ERR_PAGINATION_INVALID", 400, "offset must be an integer")
        if offset < 0:
            err("ERR_PAGINATION_INVALID", 400, "offset out of range")
    return limit, offset


def list_response(items, default_all=False):
    """items: full filtered list (unsorted). Sort by _seq, paginate."""
    items = sorted(items, key=lambda e: e["_seq"])
    has_params = ("limit" in request.args) or ("offset" in request.args)
    total = len(items)
    if default_all and not has_params:
        pagination = {"limit": total, "offset": 0,
                      "total_count": total, "has_more": False}
        return ok_list(items, pagination)
    limit, offset = parse_pagination()
    page = items[offset:offset + limit]
    pagination = {"limit": limit, "offset": offset,
                  "total_count": total, "has_more": offset + limit < total}
    return ok_list(page, pagination)


# ---------------------------------------------------------------------------
# Derived-field recomputation
# ---------------------------------------------------------------------------
def case_parties(case_id):
    return sorted([p for p in STORE["parties"].values() if p["case_id"] == case_id],
                  key=lambda e: e["_seq"])


def case_candidates(case_id):
    return [c for c in STORE["candidates"].values() if c["case_id"] == case_id]


def candidate_rankings(candidate_id):
    return [r for r in STORE["rankings"].values() if r["candidate_id"] == candidate_id]


def recompute_candidate(cand):
    active = [r for r in candidate_rankings(cand["id"]) if r["status"] == "ACTIVE"]
    cand["aggregate_rank_score"] = sum(
        (r["rank_value"] or 0) for r in active if r["action"] == "RANK")
    cand["is_struck"] = any(r["action"] == "STRIKE" for r in active)


def recompute_party_strikes(party):
    case = STORE["cases"].get(party["case_id"])
    used = sum(1 for r in STORE["rankings"].values()
               if r["party_id"] == party["id"]
               and r["action"] == "STRIKE" and r["status"] == "ACTIVE")
    party["strikes_used"] = used
    spp = case["strikes_per_party"] if case else 0
    party["strikes_remaining"] = spp - used


def recompute_party_allocations(case):
    total = case["posted_fee_cents"]
    parties = case_parties(case["id"])
    if not parties:
        return
    base_shares = []
    for p in parties:
        share = (Decimal(total) * Decimal(p["share_pct"]) / Decimal(100)).to_integral_value(
            rounding=ROUND_FLOOR)
        base_shares.append(int(share))
    remainder = total - sum(base_shares)
    for i in range(len(parties)):
        if remainder <= 0:
            break
        base_shares[i] += 1
        remainder -= 1
    for p, amt in zip(parties, base_shares):
        if p.get("allocated_fee_share_cents") != amt:
            p["allocated_fee_share_cents"] = amt


def recompute_case_aggregates(case):
    cid = case["id"]
    paid = sum(d["amount_cents"] for d in STORE["deposits"].values()
               if d["case_id"] == cid and d["status"] == "PAID")
    posted = sum(fc["amount_cents"] for fc in STORE["feecharges"].values()
                 if fc["case_id"] == cid and fc["status"] == "POSTED")
    case["paid_deposit_cents"] = paid
    case["posted_fee_cents"] = posted
    case["actual_neutral_fee_cents"] = posted
    admin = case["final_admin_fee_cents"] if case["status"] in ("AWARD_ISSUED", "CLOSED") else 0
    case["deposit_balance_cents"] = paid - posted - admin
    # estimated neutral compensation over SCHEDULED hearings
    est = 0
    nid = case["appointed_neutral_id"]
    if nid and nid in STORE["neutrals"]:
        rate = STORE["neutrals"][nid]["hourly_rate_cents"]
        total_seconds = Decimal(0)
        for h in STORE["hearings"].values():
            if h["case_id"] == cid and h["status"] == "SCHEDULED":
                total_seconds += Decimal(h["_seconds"])
        hours = total_seconds / Decimal(3600)
        est = round_half_up(Decimal(rate) * hours)
    case["estimated_neutral_fee_cents"] = est


# ===========================================================================
# CLOCK
# ===========================================================================
@app.route("/_clock/set_current_utc", methods=["POST"])
def clock_set():
    global _clock
    auth({"CaseAdministrator"})
    body = get_body()
    if "to_iso8601" not in body:
        err("ERR_VALIDATION", 400, "Missing to_iso8601")
    try:
        dt = parse_iso(body["to_iso8601"])
    except ValueError:
        err("ERR_VALIDATION", 400, "Invalid to_iso8601")
    _clock = dt
    return ok({"current_utc": fmt_ts(dt)})


# ===========================================================================
# CASES
# ===========================================================================
@app.route("/cases", methods=["POST"])
def create_case():
    auth({"CaseAdministrator"})
    body = get_body()
    # presence / type
    if "case_type" not in body or not isinstance(body["case_type"], str):
        err("ERR_VALIDATION", 400, "Missing case_type")
    title = require_str(body, "title")
    claim = require_int(body, "claim_amount_cents")
    if claim < 0:
        err("ERR_VALIDATION", 400, "claim_amount_cents must be >= 0")
    panel_size = body.get("panel_size", 1)
    if not is_int(panel_size):
        err("ERR_VALIDATION", 400, "panel_size must be an integer")
    strikes = body.get("strikes_per_party", 2)
    if not is_int(strikes) or strikes < 0:
        err("ERR_VALIDATION", 400, "strikes_per_party must be an integer >= 0")
    # enum
    if body["case_type"] not in CASE_TYPE:
        err("ERR_INVALID_ENUM", 422, "Invalid case_type")
    case_type = body["case_type"]
    if panel_size not in (1, 3):
        err("ERR_VALIDATION", 400, "panel_size must be 1 or 3")
    if case_type == "MEDIATION" and panel_size != 1:
        err("ERR_VALIDATION", 400, "MEDIATION requires panel_size 1")

    fee_tier = tier_of(claim)
    filing_fee = compute_admin_fee(claim, case_type, panel_size)
    case = stamp_new()
    case.update({
        "case_type": case_type,
        "title": title,
        "claim_amount_cents": claim,
        "panel_size": panel_size,
        "strikes_per_party": strikes,
        "fee_tier": fee_tier,
        "filing_fee_cents": filing_fee,
        "final_admin_fee_cents": 0,
        "appointed_neutral_id": None,
        "paid_deposit_cents": 0,
        "posted_fee_cents": 0,
        "deposit_balance_cents": 0,
        "estimated_neutral_fee_cents": 0,
        "actual_neutral_fee_cents": 0,
        "status": "FILED",
    })
    STORE["cases"][case["id"]] = case
    return ok(public(case), 201)


@app.route("/cases/<cid>", methods=["GET"])
def get_case(cid):
    auth(KNOWN_ROLES)
    case = path_lookup("cases", cid)
    return ok(public(case))


@app.route("/cases", methods=["GET"])
def list_cases():
    auth(KNOWN_ROLES)
    items = list(STORE["cases"].values())
    status = request.args.get("status")
    if status is not None:
        items = [c for c in items if c["status"] == status]
    return list_response(items)


@app.route("/cases/<cid>/transition", methods=["POST"])
def case_transition(cid):
    auth({"CaseAdministrator"})
    case = path_lookup("cases", cid)
    body = get_body()
    if "to_status" not in body or not isinstance(body["to_status"], str):
        err("ERR_VALIDATION", 400, "Missing to_status")
    to = body["to_status"]
    if to not in CASE_STATUSES:
        err("ERR_INVALID_ENUM", 422, "Invalid to_status")
    cur = case["status"]

    if to == "SELECTION":
        if cur != "FILED":
            err("ERR_INVALID_STATE", 409, "Case cannot open selection from %s" % cur)
        parties = case_parties(cid)
        has_claimant = any(p["role"] == "CLAIMANT" for p in parties)
        has_respondent = any(p["role"] == "RESPONDENT" for p in parties)
        if not (has_claimant and has_respondent):
            err("ERR_PARTIES_INCOMPLETE", 409, "Need a claimant and a respondent")
        case["status"] = "SELECTION"
        touch(case)
    elif to == "WITHDRAWN":
        if cur not in ("FILED", "SELECTION"):
            err("ERR_INVALID_STATE", 409, "Case cannot be withdrawn from %s" % cur)
        if cur == "SELECTION":
            for c in case_candidates(cid):
                if c["status"] in ("PROPOSED", "DISCLOSED", "CLEARED", "OBJECTED"):
                    c["status"] = "NOT_SELECTED"
                    touch(c)
        case["status"] = "WITHDRAWN"
        touch(case)
    elif to == "HEARING":
        if cur != "APPOINTED":
            err("ERR_INVALID_STATE", 409, "Case cannot enter hearing from %s" % cur)
        if not case["appointed_neutral_id"]:
            err("ERR_INVALID_STATE", 409, "No appointed neutral")
        case["status"] = "HEARING"
        touch(case)
    else:
        err("ERR_INVALID_STATE", 409, "Unsupported manual transition to %s" % to)
    return ok(public(case))


@app.route("/cases/<cid>/appoint", methods=["POST"])
def case_appoint(cid):
    auth({"CaseAdministrator"})
    case = path_lookup("cases", cid)
    body = get_body()
    # OCC (optional here)
    if "expected_case_version" in body:
        v = body["expected_case_version"]
        if not is_int(v):
            err("ERR_VALIDATION", 400, "expected_case_version must be an integer")
        if v != case["version"]:
            err("ERR_STALE_VERSION", 412, "Case version has advanced")
    if case["status"] != "SELECTION":
        err("ERR_INVALID_STATE", 409, "Appointment requires SELECTION")
    eligible = [c for c in case_candidates(cid)
                if c["status"] == "CLEARED" and not c["is_struck"]]
    if not eligible:
        err("ERR_NO_ELIGIBLE_CANDIDATE", 422, "No eligible candidate")
    winner = sorted(eligible, key=lambda c: (-c["aggregate_rank_score"], c["_seq"]))[0]
    winner["status"] = "APPOINTED"
    touch(winner)
    for c in case_candidates(cid):
        if c["id"] != winner["id"] and c["status"] in (
                "PROPOSED", "DISCLOSED", "CLEARED", "OBJECTED"):
            c["status"] = "NOT_SELECTED"
            touch(c)
    case["appointed_neutral_id"] = winner["neutral_id"]
    case["status"] = "APPOINTED"
    recompute_case_aggregates(case)
    touch(case)
    return ok(public(case))


# ===========================================================================
# PARTIES
# ===========================================================================
@app.route("/parties", methods=["POST"])
def create_party():
    auth({"CaseAdministrator"})
    body = get_body()
    case = fk_lookup("cases", body.get("case_id"), "case_id")
    if "role" not in body or not isinstance(body["role"], str):
        err("ERR_VALIDATION", 400, "Missing role")
    display_name = require_str(body, "display_name")
    share_pct = require_int(body, "share_pct")
    if share_pct < 0 or share_pct > 100:
        err("ERR_VALIDATION", 400, "share_pct must be 0..100")
    if body["role"] not in PARTY_ROLE:
        err("ERR_INVALID_ENUM", 422, "Invalid role")
    party = stamp_new()
    party.update({
        "case_id": case["id"],
        "role": body["role"],
        "display_name": display_name,
        "share_pct": share_pct,
        "strikes_used": 0,
        "strikes_remaining": case["strikes_per_party"],
        "allocated_fee_share_cents": 0,
    })
    STORE["parties"][party["id"]] = party
    return ok(public(party), 201)


@app.route("/cases/<cid>/parties", methods=["GET"])
def list_case_parties(cid):
    auth(KNOWN_ROLES)
    path_lookup("cases", cid)
    items = [p for p in STORE["parties"].values() if p["case_id"] == cid]
    return list_response(items, default_all=True)


# ===========================================================================
# NEUTRALS
# ===========================================================================
@app.route("/neutrals", methods=["POST"])
def create_neutral():
    auth({"CaseAdministrator"})
    body = get_body()
    full_name = require_str(body, "full_name")
    if "neutral_type" not in body or not isinstance(body["neutral_type"], str):
        err("ERR_VALIDATION", 400, "Missing neutral_type")
    rate = require_int(body, "hourly_rate_cents")
    if rate <= 0:
        err("ERR_VALIDATION", 400, "hourly_rate_cents must be > 0")
    if body["neutral_type"] not in NEUTRAL_TYPE:
        err("ERR_INVALID_ENUM", 422, "Invalid neutral_type")
    neutral = stamp_new()
    neutral.update({
        "full_name": full_name,
        "neutral_type": body["neutral_type"],
        "hourly_rate_cents": rate,
        "roster_status": "ACTIVE",
    })
    STORE["neutrals"][neutral["id"]] = neutral
    return ok(public(neutral), 201)


@app.route("/neutrals/<nid>", methods=["GET"])
def get_neutral(nid):
    auth(KNOWN_ROLES)
    n = path_lookup("neutrals", nid)
    return ok(public(n))


@app.route("/neutrals", methods=["GET"])
def list_neutrals():
    auth(KNOWN_ROLES)
    items = list(STORE["neutrals"].values())
    rs = request.args.get("roster_status")
    if rs is not None:
        items = [n for n in items if n["roster_status"] == rs]
    return list_response(items)


@app.route("/neutrals/<nid>/transition", methods=["POST"])
def neutral_transition(nid):
    auth({"CaseAdministrator"})
    n = path_lookup("neutrals", nid)
    body = get_body()
    if "roster_status" not in body or not isinstance(body["roster_status"], str):
        err("ERR_VALIDATION", 400, "Missing roster_status")
    if body["roster_status"] not in ROSTER_STATUS:
        err("ERR_INVALID_ENUM", 422, "Invalid roster_status")
    n["roster_status"] = body["roster_status"]
    touch(n)
    return ok(public(n))


@app.route("/neutrals/<nid>/candidates", methods=["GET"])
def list_neutral_candidates(nid):
    auth(KNOWN_ROLES)
    path_lookup("neutrals", nid)
    items = [c for c in STORE["candidates"].values() if c["neutral_id"] == nid]
    return list_response(items, default_all=True)


# ===========================================================================
# CANDIDATES
# ===========================================================================
@app.route("/cases/<cid>/candidates", methods=["POST"])
def add_candidate(cid):
    auth({"CaseAdministrator"})
    case = path_lookup("cases", cid)
    body = get_body()
    neutral = fk_lookup("neutrals", body.get("neutral_id"), "neutral_id")
    # required: expected_case_version
    if "expected_case_version" not in body:
        err("ERR_VALIDATION", 400, "Missing expected_case_version")
    v = body["expected_case_version"]
    if not is_int(v):
        err("ERR_VALIDATION", 400, "expected_case_version must be an integer")
    # concurrency
    if v != case["version"]:
        err("ERR_STALE_VERSION", 412, "Case version has advanced")
    # compliance: neutral_type compatible with case_type
    nt = neutral["neutral_type"]
    if case["case_type"] == "ARBITRATION" and nt not in ("ARBITRATOR", "BOTH"):
        err("ERR_NEUTRAL_TYPE_MISMATCH", 409, "Neutral type incompatible with case")
    if case["case_type"] == "MEDIATION" and nt not in ("MEDIATOR", "BOTH"):
        err("ERR_NEUTRAL_TYPE_MISMATCH", 409, "Neutral type incompatible with case")

    cand = stamp_new()
    cand.update({
        "case_id": case["id"],
        "neutral_id": neutral["id"],
        "disclosure_text": None,
        "has_conflict": False,
        "aggregate_rank_score": 0,
        "is_struck": False,
        "status": "PROPOSED",
    })
    STORE["candidates"][cand["id"]] = cand
    touch(case)  # candidate add regenerates the pool -> version bump
    return ok(public(cand), 201)


@app.route("/cases/<cid>/candidates", methods=["GET"])
def list_case_candidates(cid):
    auth(KNOWN_ROLES)
    path_lookup("cases", cid)
    items = case_candidates(cid)
    return list_response(items, default_all=True)


@app.route("/candidates/<cand_id>/disclose", methods=["POST"])
def candidate_disclose(cand_id):
    uid, role = auth({"Neutral"})
    cand = path_lookup("candidates", cand_id)
    if cand["neutral_id"] != uid:
        err("ERR_UNAUTHORIZED", 403, "Neutral does not own this candidacy")
    body = get_body()
    # state
    if cand["status"] != "PROPOSED":
        err("ERR_INVALID_STATE", 409, "Candidate cannot disclose from %s" % cand["status"])
    # compliance: neutral roster ACTIVE
    neutral = STORE["neutrals"].get(cand["neutral_id"])
    if not neutral or neutral["roster_status"] != "ACTIVE":
        err("ERR_NEUTRAL_NOT_ACTIVE", 409, "Neutral roster status is not ACTIVE")
    has_conflict = body.get("has_conflict", False)
    if not isinstance(has_conflict, bool):
        err("ERR_VALIDATION", 400, "has_conflict must be a boolean")
    disclosure_text = body.get("disclosure_text")
    if disclosure_text is not None and not isinstance(disclosure_text, str):
        err("ERR_VALIDATION", 400, "disclosure_text must be a string")
    cand["disclosure_text"] = disclosure_text
    cand["has_conflict"] = has_conflict
    cand["status"] = "DISCLOSED"
    touch(cand)
    return ok(public(cand))


@app.route("/candidates/<cand_id>/transition", methods=["POST"])
def candidate_transition(cand_id):
    auth({"CaseAdministrator"})
    cand = path_lookup("candidates", cand_id)
    body = get_body()
    if "to_status" not in body or not isinstance(body["to_status"], str):
        err("ERR_VALIDATION", 400, "Missing to_status")
    to = body["to_status"]
    if to not in CANDIDATE_STATUSES:
        err("ERR_INVALID_ENUM", 422, "Invalid to_status")
    cur = cand["status"]

    if to == "CLEARED":
        if cur not in ("DISCLOSED", "OBJECTED"):
            err("ERR_INVALID_STATE", 409, "Cannot clear from %s" % cur)
        if cand["has_conflict"]:
            err("ERR_CANDIDATE_HAS_CONFLICT", 409, "Candidate has an unresolved conflict")
        cand["status"] = "CLEARED"
    elif to == "OBJECTED":
        if cur != "DISCLOSED":
            err("ERR_INVALID_STATE", 409, "Cannot object from %s" % cur)
        cand["status"] = "OBJECTED"
    elif to == "DISQUALIFIED":
        if cur != "OBJECTED":
            err("ERR_INVALID_STATE", 409, "Cannot disqualify from %s" % cur)
        cand["status"] = "DISQUALIFIED"
    else:
        err("ERR_INVALID_STATE", 409, "Unsupported candidate transition to %s" % to)
    touch(cand)
    return ok(public(cand))


# ===========================================================================
# RANKINGS
# ===========================================================================
@app.route("/rankings", methods=["POST"])
def create_ranking():
    uid, role = auth({"Party"})
    body = get_body()
    # ownership (authz): acting party can only rank as itself
    if "party_id" in body and isinstance(body["party_id"], str) and body["party_id"] != uid:
        err("ERR_UNAUTHORIZED", 403, "Party may only act as itself")
    # existence
    cand = fk_lookup("candidates", body.get("candidate_id"), "candidate_id")
    party = fk_lookup("parties", body.get("party_id"), "party_id")
    if party["id"] != uid:
        err("ERR_UNAUTHORIZED", 403, "Party may only act as itself")
    # validation
    action = require_enum(body, "action", RANK_ACTION)
    rank_value = None
    if action == "RANK":
        rank_value = require_int(body, "rank_value")
        if rank_value < 1:
            err("ERR_VALIDATION", 400, "rank_value must be >= 1")
    else:
        rank_value = None
    # business gates (priority 9 order per PRD: duplicate, budget, then case membership)
    existing = [r for r in candidate_rankings(cand["id"])
                if r["party_id"] == party["id"] and r["status"] == "ACTIVE"]
    if existing:
        err("ERR_DUPLICATE_RANKING", 409, "Party already ranked this candidate")
    if action == "STRIKE":
        case = STORE["cases"].get(party["case_id"])
        spp = case["strikes_per_party"] if case else 0
        if party["strikes_used"] + 1 > spp:
            err("ERR_STRIKE_BUDGET_EXCEEDED", 409, "Strike allowance exceeded")
    if party["case_id"] != cand["case_id"]:
        err("ERR_NOT_CASE_PARTY", 409, "Party does not belong to the candidate's case")

    ranking = stamp_new()
    ranking.update({
        "candidate_id": cand["id"],
        "party_id": party["id"],
        "action": action,
        "rank_value": rank_value,
        "status": "ACTIVE",
    })
    STORE["rankings"][ranking["id"]] = ranking
    recompute_candidate(cand)
    touch(cand)
    recompute_party_strikes(party)
    touch(party)
    return ok(public(ranking), 201)


@app.route("/rankings/<rid>", methods=["GET"])
def get_ranking(rid):
    auth(KNOWN_ROLES)
    r = path_lookup("rankings", rid)
    return ok(public(r))


@app.route("/rankings", methods=["GET"])
def list_rankings():
    auth(KNOWN_ROLES)
    items = list(STORE["rankings"].values())
    cand_id = request.args.get("candidate_id")
    if cand_id is not None:
        items = [r for r in items if r["candidate_id"] == cand_id]
    party_id = request.args.get("party_id")
    if party_id is not None:
        items = [r for r in items if r["party_id"] == party_id]
    return list_response(items)


@app.route("/rankings/<rid>/withdraw", methods=["POST"])
def withdraw_ranking(rid):
    uid, role = auth({"Party"})
    r = path_lookup("rankings", rid)
    if r["party_id"] != uid:
        err("ERR_UNAUTHORIZED", 403, "Party does not own this ranking")
    if r["status"] != "ACTIVE":
        err("ERR_INVALID_STATE", 409, "Ranking is not active")
    r["status"] = "WITHDRAWN"
    touch(r)
    cand = STORE["candidates"].get(r["candidate_id"])
    if cand:
        recompute_candidate(cand)
        touch(cand)
    party = STORE["parties"].get(r["party_id"])
    if party:
        recompute_party_strikes(party)
        touch(party)
    return ok(public(r))


# ===========================================================================
# HEARINGS
# ===========================================================================
@app.route("/cases/<cid>/hearings", methods=["POST"])
def schedule_hearing(cid):
    auth({"CaseAdministrator"})
    case = path_lookup("cases", cid)
    body = get_body()
    if "hearing_type" not in body or not isinstance(body["hearing_type"], str):
        err("ERR_VALIDATION", 400, "Missing hearing_type")
    location = require_str(body, "location")
    if "start_at" not in body or "end_at" not in body:
        err("ERR_VALIDATION", 400, "Missing start_at/end_at")
    try:
        start = parse_iso(body["start_at"])
        end = parse_iso(body["end_at"])
    except (ValueError, TypeError):
        err("ERR_VALIDATION", 400, "Invalid datetime")
    if body["hearing_type"] not in HEARING_TYPE:
        err("ERR_INVALID_ENUM", 422, "Invalid hearing_type")
    if not (end > start):
        err("ERR_HEARING_END_BEFORE_START", 400, "end_at must be after start_at")
    # temporal: notice window
    threshold = clock_now() + timedelta(days=HEARING_NOTICE_DAYS)
    if start < threshold:
        err("ERR_HEARING_NOTICE_TOO_SHORT", 422, "Insufficient hearing notice")
    # business: overlap on same case (non-cancelled)
    for h in STORE["hearings"].values():
        if h["case_id"] == cid and h["status"] != "CANCELLED":
            if start < h["_end"] and h["_start"] < end:
                err("ERR_HEARING_OVERLAP", 409, "Hearing overlaps another on this case")
    # business: neutral buffer across cases sharing the appointed neutral
    nid = case["appointed_neutral_id"]
    if nid:
        buffer = timedelta(minutes=NEUTRAL_BUFFER_MINUTES)
        for h in STORE["hearings"].values():
            if h["status"] == "CANCELLED":
                continue
            other_case = STORE["cases"].get(h["case_id"])
            if not other_case or other_case["appointed_neutral_id"] != nid:
                continue
            # overlap => within buffer
            if start < h["_end"] and h["_start"] < end:
                err("ERR_NEUTRAL_UNAVAILABLE", 409, "Neutral unavailable (buffer)")
            if start >= h["_end"]:
                gap = start - h["_end"]
            else:
                gap = h["_start"] - end
            if gap < buffer:
                err("ERR_NEUTRAL_UNAVAILABLE", 409, "Neutral unavailable (buffer)")

    duration_hours = (end - start).total_seconds() / 3600.0
    hearing = stamp_new()
    hearing.update({
        "case_id": case["id"],
        "hearing_type": body["hearing_type"],
        "start_at": body["start_at"],
        "end_at": body["end_at"],
        "location": location,
        "duration_hours": duration_hours,
        "status": "SCHEDULED",
        "_start": start,
        "_end": end,
        "_seconds": (end - start).total_seconds(),
    })
    STORE["hearings"][hearing["id"]] = hearing
    recompute_case_aggregates(case)
    touch(case)
    return ok(public(hearing), 201)


@app.route("/cases/<cid>/hearings", methods=["GET"])
def list_case_hearings(cid):
    auth(KNOWN_ROLES)
    path_lookup("cases", cid)
    items = [h for h in STORE["hearings"].values() if h["case_id"] == cid]
    return list_response(items, default_all=True)


@app.route("/hearings/<hid>/transition", methods=["POST"])
def hearing_transition(hid):
    auth({"CaseAdministrator"})
    h = path_lookup("hearings", hid)
    body = get_body()
    if "to_status" not in body or not isinstance(body["to_status"], str):
        err("ERR_VALIDATION", 400, "Missing to_status")
    to = body["to_status"]
    if to not in HEARING_STATUSES:
        err("ERR_INVALID_ENUM", 422, "Invalid to_status")
    if h["status"] != "SCHEDULED":
        err("ERR_INVALID_STATE", 409, "Hearing is not scheduled")
    if to == "HELD":
        h["status"] = "HELD"
        touch(h)
    elif to == "CANCELLED":
        h["status"] = "CANCELLED"
        touch(h)
        case = STORE["cases"].get(h["case_id"])
        if case:
            recompute_case_aggregates(case)
            touch(case)
    else:
        err("ERR_INVALID_STATE", 409, "Unsupported hearing transition to %s" % to)
    return ok(public(h))


# ===========================================================================
# EXCHANGES
# ===========================================================================
@app.route("/cases/<cid>/exchanges", methods=["POST"])
def create_exchange(cid):
    auth({"CaseAdministrator"})
    case = path_lookup("cases", cid)
    body = get_body()
    if "exchange_type" not in body or not isinstance(body["exchange_type"], str):
        err("ERR_VALIDATION", 400, "Missing exchange_type")
    if "due_at" not in body:
        err("ERR_VALIDATION", 400, "Missing due_at")
    try:
        due = parse_iso(body["due_at"])
    except (ValueError, TypeError):
        err("ERR_VALIDATION", 400, "Invalid due_at")
    if body["exchange_type"] not in EXCHANGE_TYPE:
        err("ERR_INVALID_ENUM", 422, "Invalid exchange_type")
    ex = stamp_new()
    ex.update({
        "case_id": case["id"],
        "exchange_type": body["exchange_type"],
        "due_at": body["due_at"],
        "submitted_at": None,
        "status": "PENDING",
        "_due": due,
    })
    STORE["exchanges"][ex["id"]] = ex
    return ok(public(ex), 201)


@app.route("/cases/<cid>/exchanges", methods=["GET"])
def list_case_exchanges(cid):
    auth(KNOWN_ROLES)
    path_lookup("cases", cid)
    items = [e for e in STORE["exchanges"].values() if e["case_id"] == cid]
    return list_response(items, default_all=True)


@app.route("/exchanges/<eid>/submit", methods=["POST"])
def submit_exchange(eid):
    auth({"Party", "CaseAdministrator"})
    ex = path_lookup("exchanges", eid)
    if ex["status"] != "PENDING":
        err("ERR_INVALID_STATE", 409, "Exchange is not pending")
    now = clock_now()
    ex["submitted_at"] = fmt_ts(now)
    ex["status"] = "SUBMITTED" if now <= ex["_due"] else "LATE"
    touch(ex)
    return ok(public(ex))


# ===========================================================================
# DEPOSITS
# ===========================================================================
@app.route("/deposits", methods=["POST"])
def create_deposit():
    auth({"CaseAdministrator"})
    body = get_body()
    case = fk_lookup("cases", body.get("case_id"), "case_id")
    amount = require_int(body, "amount_cents")
    if amount <= 0:
        err("ERR_VALIDATION", 400, "amount_cents must be > 0")
    dep = stamp_new()
    dep.update({
        "case_id": case["id"],
        "amount_cents": amount,
        "paid_at": None,
        "status": "REQUESTED",
    })
    STORE["deposits"][dep["id"]] = dep
    return ok(public(dep), 201)


@app.route("/deposits/<did>", methods=["GET"])
def get_deposit(did):
    auth(KNOWN_ROLES)
    d = path_lookup("deposits", did)
    return ok(public(d))


@app.route("/deposits", methods=["GET"])
def list_deposits():
    auth(KNOWN_ROLES)
    items = list(STORE["deposits"].values())
    cid = request.args.get("case_id")
    if cid is not None:
        items = [d for d in items if d["case_id"] == cid]
    return list_response(items)


@app.route("/deposits/<did>/pay", methods=["POST"])
def pay_deposit(did):
    auth({"Party"})
    dep = path_lookup("deposits", did)
    if dep["status"] != "REQUESTED":
        err("ERR_INVALID_STATE", 409, "Deposit is not requested")
    dep["status"] = "PAID"
    dep["paid_at"] = fmt_ts(clock_now())
    touch(dep)
    case = STORE["cases"].get(dep["case_id"])
    if case:
        recompute_case_aggregates(case)
        touch(case)
    return ok(public(dep))


@app.route("/deposits/<did>/refund", methods=["POST"])
def refund_deposit(did):
    auth({"CaseAdministrator"})
    dep = path_lookup("deposits", did)
    if dep["status"] != "PAID":
        err("ERR_INVALID_STATE", 409, "Deposit is not paid")
    case = STORE["cases"].get(dep["case_id"])
    if not case or case["status"] != "CLOSED":
        err("ERR_INVALID_STATE", 409, "Case is not closed")
    dep["status"] = "REFUNDED"
    touch(dep)
    recompute_case_aggregates(case)
    touch(case)
    return ok(public(dep))


# ===========================================================================
# FEE CHARGES
# ===========================================================================
@app.route("/cases/<cid>/fee-charges", methods=["POST"])
def post_fee_charge(cid):
    auth({"CaseAdministrator"})
    case = path_lookup("cases", cid)
    body = get_body()
    neutral = fk_lookup("neutrals", body.get("neutral_id"), "neutral_id")
    # validation
    if "hours" not in body or not is_num(body["hours"]):
        err("ERR_VALIDATION", 400, "Missing or invalid hours")
    hours = body["hours"]
    if hours <= 0:
        err("ERR_VALIDATION", 400, "hours must be > 0")
    if "expected_case_version" not in body:
        err("ERR_VALIDATION", 400, "Missing expected_case_version")
    v = body["expected_case_version"]
    if not is_int(v):
        err("ERR_VALIDATION", 400, "expected_case_version must be an integer")
    if neutral["id"] != case["appointed_neutral_id"]:
        err("ERR_VALIDATION", 400, "neutral_id must equal appointed neutral")
    # concurrency
    if v != case["version"]:
        err("ERR_STALE_VERSION", 412, "Case version has advanced")
    amount = round_half_up(Decimal(str(hours)) * Decimal(neutral["hourly_rate_cents"]))
    # fiscal gate
    if amount > case["deposit_balance_cents"]:
        err("ERR_INSUFFICIENT_DEPOSIT", 402, "Charge exceeds deposit balance")
    fc = stamp_new()
    fc.update({
        "case_id": case["id"],
        "neutral_id": neutral["id"],
        "hours": hours,
        "amount_cents": amount,
        "status": "POSTED",
    })
    STORE["feecharges"][fc["id"]] = fc
    recompute_case_aggregates(case)
    recompute_party_allocations(case)
    touch(case)
    for p in case_parties(cid):
        touch(p)
    return ok(public(fc), 201)


@app.route("/fee-charges/<fid>", methods=["GET"])
def get_fee_charge(fid):
    auth(KNOWN_ROLES)
    fc = path_lookup("feecharges", fid)
    return ok(public(fc))


@app.route("/fee-charges", methods=["GET"])
def list_fee_charges():
    auth(KNOWN_ROLES)
    items = list(STORE["feecharges"].values())
    cid = request.args.get("case_id")
    if cid is not None:
        items = [f for f in items if f["case_id"] == cid]
    nid = request.args.get("neutral_id")
    if nid is not None:
        items = [f for f in items if f["neutral_id"] == nid]
    return list_response(items)


@app.route("/fee-charges/<fid>/reverse", methods=["POST"])
def reverse_fee_charge(fid):
    auth({"CaseAdministrator"})
    fc = path_lookup("feecharges", fid)
    if fc["status"] != "POSTED":
        err("ERR_INVALID_STATE", 409, "Fee charge is not posted")
    fc["status"] = "REVERSED"
    touch(fc)
    case = STORE["cases"].get(fc["case_id"])
    if case:
        recompute_case_aggregates(case)
        recompute_party_allocations(case)
        touch(case)
        for p in case_parties(case["id"]):
            touch(p)
    return ok(public(fc))


# ===========================================================================
# AWARDS
# ===========================================================================
@app.route("/cases/<cid>/awards", methods=["POST"])
def draft_award(cid):
    auth({"CaseAdministrator"})
    case = path_lookup("cases", cid)
    body = get_body()
    if "award_type" not in body or not isinstance(body["award_type"], str):
        err("ERR_VALIDATION", 400, "Missing award_type")
    amount = body.get("award_amount_cents", 0)
    if not is_int(amount) or amount < 0:
        err("ERR_VALIDATION", 400, "award_amount_cents must be an integer >= 0")
    if body["award_type"] not in AWARD_TYPE:
        err("ERR_INVALID_ENUM", 422, "Invalid award_type")
    if case["status"] != "HEARING":
        err("ERR_INVALID_STATE", 409, "Award requires case in HEARING")
    for a in STORE["awards"].values():
        if a["case_id"] == cid and a["status"] != "VACATED":
            err("ERR_AWARD_EXISTS", 409, "Case already has a standing award")
    if body["award_type"] == "DISMISSAL":
        amount = 0
    award = stamp_new()
    award.update({
        "case_id": case["id"],
        "award_type": body["award_type"],
        "award_amount_cents": amount,
        "issued_at": None,
        "status": "DRAFT",
    })
    STORE["awards"][award["id"]] = award
    return ok(public(award), 201)


@app.route("/cases/<cid>/awards", methods=["GET"])
def list_case_awards(cid):
    auth(KNOWN_ROLES)
    path_lookup("cases", cid)
    items = [a for a in STORE["awards"].values() if a["case_id"] == cid]
    return list_response(items, default_all=True)


def _award_has_open_appeal(award_id):
    return any(ap["award_id"] == award_id and ap["status"] in ("FILED", "UNDER_REVIEW")
               for ap in STORE["appeals"].values())


@app.route("/awards/<aid>/transition", methods=["POST"])
def award_transition(aid):
    auth({"CaseAdministrator"})
    award = path_lookup("awards", aid)
    body = get_body()
    if "to_status" not in body or not isinstance(body["to_status"], str):
        err("ERR_VALIDATION", 400, "Missing to_status")
    to = body["to_status"]
    if to not in AWARD_STATUSES:
        err("ERR_INVALID_ENUM", 422, "Invalid to_status")
    cur = award["status"]
    case = STORE["cases"].get(award["case_id"])

    if to == "ISSUED":
        if cur != "DRAFT":
            err("ERR_INVALID_STATE", 409, "Award cannot be issued from %s" % cur)
        if not case or case["status"] != "HEARING":
            err("ERR_INVALID_STATE", 409, "Case must be in HEARING to issue")
        award["issued_at"] = fmt_ts(clock_now())
        award["status"] = "ISSUED"
        touch(award)
        case["final_admin_fee_cents"] = compute_admin_fee(
            award["award_amount_cents"], case["case_type"], case["panel_size"])
        case["status"] = "AWARD_ISSUED"
        recompute_case_aggregates(case)
        touch(case)
    elif to == "FINAL":
        if cur != "ISSUED":
            err("ERR_INVALID_STATE", 409, "Award cannot be finalized from %s" % cur)
        if _award_has_open_appeal(aid):
            err("ERR_INVALID_STATE", 409, "Award has an open appeal")
        award["status"] = "FINAL"
        touch(award)
        if case and case["status"] == "AWARD_ISSUED":
            case["status"] = "CLOSED"
            recompute_case_aggregates(case)
            touch(case)
    elif to == "DRAFT":
        if cur != "VACATED":
            err("ERR_INVALID_STATE", 409, "Award cannot be re-drafted from %s" % cur)
        if not case or case["status"] != "HEARING":
            err("ERR_INVALID_STATE", 409, "Case must be in HEARING to re-draft")
        award["status"] = "DRAFT"
        touch(award)
    else:
        err("ERR_INVALID_STATE", 409, "Unsupported award transition to %s" % to)
    return ok(public(award))


# ===========================================================================
# APPEALS
# ===========================================================================
@app.route("/appeals", methods=["POST"])
def create_appeal():
    uid, role = auth({"Party"})
    body = get_body()
    award = fk_lookup("awards", body.get("award_id"), "award_id")
    ground = require_enum(body, "ground", APPEAL_GROUND)
    # temporal: appeal window
    if award["issued_at"] is None:
        err("ERR_APPEAL_WINDOW_CLOSED", 422, "Award is not issued")
    issued = parse_iso(award["issued_at"])
    if clock_now() > issued + timedelta(days=APPEAL_WINDOW_DAYS):
        err("ERR_APPEAL_WINDOW_CLOSED", 422, "Appeal window has closed")
    appeal = stamp_new()
    appeal.update({
        "award_id": award["id"],
        "ground": ground,
        "filed_by_party_id": uid,
        "filed_at": fmt_ts(clock_now()),
        "status": "FILED",
    })
    STORE["appeals"][appeal["id"]] = appeal
    return ok(public(appeal), 201)


@app.route("/appeals/<apid>", methods=["GET"])
def get_appeal(apid):
    auth(KNOWN_ROLES)
    ap = path_lookup("appeals", apid)
    return ok(public(ap))


@app.route("/appeals", methods=["GET"])
def list_appeals():
    auth(KNOWN_ROLES)
    items = list(STORE["appeals"].values())
    aid = request.args.get("award_id")
    if aid is not None:
        items = [a for a in items if a["award_id"] == aid]
    return list_response(items)


@app.route("/appeals/<apid>/transition", methods=["POST"])
def appeal_transition(apid):
    auth({"CaseAdministrator"})
    ap = path_lookup("appeals", apid)
    body = get_body()
    if "to_status" not in body or not isinstance(body["to_status"], str):
        err("ERR_VALIDATION", 400, "Missing to_status")
    to = body["to_status"]
    if to not in APPEAL_STATUSES:
        err("ERR_INVALID_ENUM", 422, "Invalid to_status")
    cur = ap["status"]

    if to == "UNDER_REVIEW":
        if cur != "FILED":
            err("ERR_INVALID_STATE", 409, "Appeal cannot move to review from %s" % cur)
        ap["status"] = "UNDER_REVIEW"
        touch(ap)
    elif to == "GRANTED":
        if cur != "UNDER_REVIEW":
            err("ERR_INVALID_STATE", 409, "Appeal cannot be granted from %s" % cur)
        ap["status"] = "GRANTED"
        touch(ap)
        # vacatur cascade
        award = STORE["awards"].get(ap["award_id"])
        if award and award["status"] == "ISSUED":
            award["status"] = "VACATED"
            touch(award)
            case = STORE["cases"].get(award["case_id"])
            if case and case["status"] == "AWARD_ISSUED":
                case["status"] = "HEARING"
                case["final_admin_fee_cents"] = 0
                recompute_case_aggregates(case)
                touch(case)
    elif to == "DENIED":
        if cur != "UNDER_REVIEW":
            err("ERR_INVALID_STATE", 409, "Appeal cannot be denied from %s" % cur)
        ap["status"] = "DENIED"
        touch(ap)
    else:
        err("ERR_INVALID_STATE", 409, "Unsupported appeal transition to %s" % to)
    return ok(public(ap))


# ===========================================================================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
