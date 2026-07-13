import os
import uuid
import random
import string
import itertools
from datetime import datetime, timezone, date, timedelta
from decimal import Decimal, ROUND_HALF_UP

from flask import Flask, request, jsonify, g

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
ROLES = {"Author", "Narrator", "QCReviewer", "PlatformAdmin"}
TERRITORIES = {"WORLD", "US", "UK", "EU"}
MAX_REVISIONS = 3
MAX_RETAIL_SAMPLE_SEC = 300
DISTRIBUTION_GAP_DAYS = 1
TIER1_UNITS = 1000
TIER2_UNITS = 5000
SHARE_CAP = Decimal("0.50")
EXCLUSIVE_BONUS = Decimal("0.05")

# ---------------------------------------------------------------------------
# In-memory store (wiped on every process boot)
# ---------------------------------------------------------------------------
AUTHORS = {}
NARRATORS = {}
TITLES = {}
AUDITIONS = {}
CONTRACTS = {}
BOOKINGS = {}
MILESTONES = {}
QCREVIEWS = {}
CHANNELS = {}
LISTINGS = {}
SALES = {}
STATEMENTS = {}

_seq_counter = itertools.count(1)

# Logical clock (UTC). Startup default is 2026-03-01T00:00:00Z.
CLOCK = {"now": datetime(2026, 3, 1, 0, 0, 0, tzinfo=timezone.utc)}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def now_dt():
    return CLOCK["now"]


def iso(dt):
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{int(dt.microsecond / 1000):03d}Z"


def now_iso():
    return iso(now_dt())


def new_id():
    return str(uuid.uuid4())


def new_request_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def next_seq():
    return next(_seq_counter)


def parse_dt(value):
    """Parse an ISO-8601 datetime into an aware UTC datetime."""
    if not isinstance(value, str):
        raise ApiError("ERR_VALIDATION", 400, "invalid datetime")
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        raise ApiError("ERR_VALIDATION", 400, "invalid datetime: %s" % value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_date(value):
    if not isinstance(value, str):
        raise ApiError("ERR_VALIDATION", 400, "invalid date")
    try:
        return date.fromisoformat(value.strip())
    except ValueError:
        raise ApiError("ERR_VALIDATION", 400, "invalid date: %s" % value)


def round_half_up(dec):
    return int(Decimal(dec).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Errors & response envelope
# ---------------------------------------------------------------------------
class ApiError(Exception):
    def __init__(self, error_id, http_status, message=""):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


def meta_block(extra=None):
    m = {
        "api_request_id": new_request_id(),
        "api_request_timestamp": now_iso(),
    }
    if extra:
        m.update(extra)
    return m


def success(data, response_type="object", status=200, meta_extra=None):
    body = {
        "meta": meta_block(meta_extra),
        "response_type": response_type,
        "data": data,
    }
    return jsonify(body), status


def clean(rec):
    return {k: v for k, v in rec.items() if not k.startswith("_")}


@app.errorhandler(ApiError)
def handle_api_error(err):
    body = {
        "meta": meta_block(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


@app.errorhandler(404)
def handle_404(err):
    body = {
        "meta": meta_block(),
        "response_type": "error",
        "data": {"error_id": "ERR_RESOURCE_NOT_FOUND", "message": "not found"},
    }
    return jsonify(body), 404


@app.errorhandler(405)
def handle_405(err):
    body = {
        "meta": meta_block(),
        "response_type": "error",
        "data": {"error_id": "ERR_VALIDATION", "message": "method not allowed"},
    }
    return jsonify(body), 405


@app.errorhandler(Exception)
def handle_uncaught(err):
    if isinstance(err, ApiError):
        return handle_api_error(err)
    body = {
        "meta": meta_block(),
        "response_type": "error",
        "data": {"error_id": "ERR_INTERNAL", "message": str(err)},
    }
    return jsonify(body), 500


# ---------------------------------------------------------------------------
# Auth / RBAC
# ---------------------------------------------------------------------------
def authenticate(allowed_roles):
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", 401, "missing or invalid auth headers")
    if role not in allowed_roles:
        raise ApiError("ERR_UNAUTHORIZED", 403, "role %s not permitted" % role)
    return user_id, role


# ---------------------------------------------------------------------------
# Body parsing / validation
# ---------------------------------------------------------------------------
def get_body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ApiError("ERR_VALIDATION", 400, "body must be a JSON object")
    return data


def require_present(body, field):
    if field not in body or body[field] is None:
        raise ApiError("ERR_VALIDATION", 400, "missing required field: %s" % field)
    return body[field]


def req_str(body, field):
    v = require_present(body, field)
    if not isinstance(v, str) or v == "":
        raise ApiError("ERR_VALIDATION", 400, "field %s must be a non-empty string" % field)
    return v


def req_int(body, field):
    v = require_present(body, field)
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError("ERR_VALIDATION", 400, "field %s must be an integer" % field)
    return v


def req_number(body, field):
    v = require_present(body, field)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ApiError("ERR_VALIDATION", 400, "field %s must be a number" % field)
    return v


def req_enum(body, field, allowed):
    v = req_str(body, field)
    if v not in allowed:
        raise ApiError("ERR_VALIDATION", 400, "field %s must be one of %s" % (field, allowed))
    return v


# ---------------------------------------------------------------------------
# Common-field record construction
# ---------------------------------------------------------------------------
def new_full_record(extra):
    ts = now_iso()
    rec = {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": next_seq(),
    }
    rec.update(extra)
    return rec


def new_light_record(extra):
    rec = {
        "id": new_id(),
        "created_at": now_iso(),
        "_seq": next_seq(),
    }
    rec.update(extra)
    return rec


def bump(rec):
    rec["version"] += 1
    rec["updated_at"] = now_iso()


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------
def paginate(items):
    """items: already-filtered list of raw records. Returns (page_records, meta)."""
    items = sorted(items, key=lambda r: r["_seq"])
    args = request.args
    limit = args.get("limit")
    offset = args.get("offset")
    if limit is None:
        limit = 10
    else:
        try:
            limit = int(limit)
        except (TypeError, ValueError):
            raise ApiError("ERR_VALIDATION", 400, "limit must be an integer")
        if limit < 1:
            limit = 1
        if limit > 100:
            limit = 100
    if offset is None:
        offset = 0
    else:
        try:
            offset = int(offset)
        except (TypeError, ValueError):
            raise ApiError("ERR_VALIDATION", 400, "offset must be an integer")
        if offset < 0:
            offset = 0
    total = len(items)
    page = items[offset:offset + limit]
    has_more = (offset + len(page)) < total
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": has_more,
    }
    return page, meta


def list_response(records):
    page, meta = paginate(records)
    return success([clean(r) for r in page], response_type="array", status=200, meta_extra=meta)


# ---------------------------------------------------------------------------
# Existence lookups
# ---------------------------------------------------------------------------
def find(store, _id, error_id):
    rec = store.get(_id)
    if rec is None:
        raise ApiError(error_id, 404, "%s not found" % _id)
    return rec


# ---------------------------------------------------------------------------
# Business calculations
# ---------------------------------------------------------------------------
def title_cumulative_units(title_id):
    """Lifetime sum of units_sold across every sales event on every listing of the title."""
    listing_ids = {l["id"] for l in LISTINGS.values() if l["title_id"] == title_id}
    total = 0
    for se in SALES.values():
        if se["listing_id"] in listing_ids:
            total += se["units_sold"]
    return total


def effective_narrator_share(contract, title):
    """Returns a Decimal share (full precision)."""
    if contract["deal_type"] == "PER_HOUR":
        return Decimal("0")
    base = Decimal(str(contract["royalty_share_pct"]))
    bonus = EXCLUSIVE_BONUS if title["exclusivity"] == "EXCLUSIVE" else Decimal("0")
    cumulative = title_cumulative_units(title["id"])
    if cumulative < TIER1_UNITS:
        tier_mult = Decimal("1.00")
    elif cumulative < TIER2_UNITS:
        tier_mult = Decimal("1.10")
    else:
        tier_mult = Decimal("1.20")
    value = (base + bonus) * tier_mult
    return value if value < SHARE_CAP else SHARE_CAP


def included_sales_events(title_id, period_start_dt, period_end_dt):
    listing_ids = {l["id"] for l in LISTINGS.values() if l["title_id"] == title_id}
    events = []
    for se in SALES.values():
        if se["listing_id"] not in listing_ids:
            continue
        occ = parse_dt(se["occurred_at"])
        if period_start_dt <= occ <= period_end_dt:
            events.append(se)
    events.sort(key=lambda se: (parse_dt(se["occurred_at"]), se["_seq"]))
    return events


def compute_statement_amounts(title, contract, period_start, period_end, variant):
    """Returns dict of computed *_cents fields plus narrator_share_pct_applied."""
    share = effective_narrator_share(contract, title)
    ps = parse_dt(period_start)
    pe = parse_dt(period_end)
    events = included_sales_events(title["id"], ps, pe)
    gross_sales_cents = 0
    statement_net_cents = 0
    for se in events:
        if variant == "PROVISIONAL":
            line_units = se["units_sold"]
        else:
            line_units = se["units_sold"] - se["units_returned"]
        line_gross = line_units * se["unit_price_cents"]
        gross_sales_cents += line_gross
        listing = LISTINGS.get(se["listing_id"])
        channel = CHANNELS.get(listing["channel_id"]) if listing else None
        cut = Decimal(str(channel["retailer_cut_pct"])) if channel else Decimal("0")
        statement_net_cents += round_half_up(Decimal(line_gross) * (Decimal("1") - cut))
    narrator_royalty_cents = round_half_up(Decimal(statement_net_cents) * share)
    author_royalty_cents = statement_net_cents - narrator_royalty_cents
    return {
        "narrator_share_pct_applied": float(share),
        "gross_sales_cents": gross_sales_cents,
        "statement_net_cents": statement_net_cents,
        "narrator_royalty_cents": narrator_royalty_cents,
        "author_royalty_cents": author_royalty_cents,
    }


def recompute_active_booked_days(narrator_id):
    narrator = NARRATORS.get(narrator_id)
    if narrator is None:
        return
    total = 0
    for b in BOOKINGS.values():
        if b["narrator_id"] == narrator_id and b["status"] == "ACTIVE":
            total += (parse_date(b["end_date"]) - parse_date(b["start_date"])).days
    narrator["active_booked_days"] = total


def contract_for_title(title_id, status=None):
    """Return the most-recently-created contract on the title (optionally filtered by status)."""
    matches = [c for c in CONTRACTS.values()
               if c["title_id"] == title_id and (status is None or c["status"] == status)]
    if not matches:
        return None
    return sorted(matches, key=lambda c: c["_seq"])[-1]


def require_title_active(title):
    if title["rights_status"] != "ACTIVE":
        raise ApiError("ERR_RIGHTS_REVERTED", 409, "title rights have been reverted")


# ===========================================================================
# Routes: Onboarding (Author / Narrator)
# ===========================================================================
@app.route("/authors", methods=["POST"])
def create_author():
    authenticate({"PlatformAdmin"})
    body = get_body()
    name = req_str(body, "name")
    email = req_str(body, "email")
    for a in AUTHORS.values():
        if a["email"] == email:
            raise ApiError("ERR_VALIDATION", 400, "email already registered")
    rec = new_full_record({
        "name": name,
        "email": email,
        "payout_balance_cents": 0,
    })
    AUTHORS[rec["id"]] = rec
    return success(clean(rec), status=201)


@app.route("/authors/<aid>", methods=["GET"])
def get_author(aid):
    authenticate({"PlatformAdmin", "Author"})
    rec = find(AUTHORS, aid, "ERR_AUTHOR_NOT_FOUND")
    return success(clean(rec), status=200)


@app.route("/narrators", methods=["POST"])
def create_narrator():
    authenticate({"PlatformAdmin"})
    body = get_body()
    name = req_str(body, "name")
    email = req_str(body, "email")
    hourly = req_int(body, "hourly_rate_cents")
    if hourly < 0:
        raise ApiError("ERR_VALIDATION", 400, "hourly_rate_cents must be >= 0")
    for n in NARRATORS.values():
        if n["email"] == email:
            raise ApiError("ERR_VALIDATION", 400, "email already registered")
    rec = new_full_record({
        "name": name,
        "email": email,
        "hourly_rate_cents": hourly,
        "payout_balance_cents": 0,
        "active_booked_days": 0,
    })
    NARRATORS[rec["id"]] = rec
    return success(clean(rec), status=201)


@app.route("/narrators/<nid>", methods=["GET"])
def get_narrator(nid):
    authenticate({"PlatformAdmin", "Narrator", "Author"})
    rec = find(NARRATORS, nid, "ERR_NARRATOR_NOT_FOUND")
    return success(clean(rec), status=200)


# ===========================================================================
# Routes: Title
# ===========================================================================
@app.route("/titles", methods=["POST"])
def create_title():
    user_id, role = authenticate({"Author"})
    body = get_body()
    title_name = req_str(body, "title_name")
    isbn = req_str(body, "isbn")
    exclusivity = req_enum(body, "exclusivity", {"EXCLUSIVE", "NON_EXCLUSIVE"})
    territory = req_enum(body, "territory", TERRITORIES)
    list_price = req_int(body, "list_price_cents")
    if list_price <= 0:
        raise ApiError("ERR_VALIDATION", 400, "list_price_cents must be > 0")
    rec = new_full_record({
        "author_id": user_id,
        "title_name": title_name,
        "isbn": isbn,
        "exclusivity": exclusivity,
        "territory": territory,
        "list_price_cents": list_price,
        "status": "DRAFT",
        "rights_status": "ACTIVE",
        "finished_hours": 0,
        "retail_sample_start_sec": None,
        "retail_sample_end_sec": None,
    })
    TITLES[rec["id"]] = rec
    return success(clean(rec), status=201)


@app.route("/titles/<tid>", methods=["GET"])
def get_title(tid):
    authenticate({"Author", "Narrator", "PlatformAdmin"})
    rec = find(TITLES, tid, "ERR_TITLE_NOT_FOUND")
    return success(clean(rec), status=200)


@app.route("/titles", methods=["GET"])
def list_titles():
    authenticate({"Author", "PlatformAdmin"})
    author_id = request.args.get("author_id")
    status = request.args.get("status")
    items = [t for t in TITLES.values()
             if (author_id is None or t["author_id"] == author_id)
             and (status is None or t["status"] == status)]
    return list_response(items)


@app.route("/titles/<tid>/open", methods=["POST"])
def open_title(tid):
    user_id, role = authenticate({"Author"})
    title = find(TITLES, tid, "ERR_TITLE_NOT_FOUND")
    if title["author_id"] != user_id:
        raise ApiError("ERR_UNAUTHORIZED", 403, "not the title owner")
    require_title_active(title)
    if title["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", 409, "title is not in DRAFT")
    title["status"] = "OPEN_FOR_AUDITION"
    bump(title)
    return success(clean(title), status=200)


@app.route("/titles/<tid>/retail-sample", methods=["POST"])
def set_retail_sample(tid):
    user_id, role = authenticate({"Author"})
    title = find(TITLES, tid, "ERR_TITLE_NOT_FOUND")
    if title["author_id"] != user_id:
        raise ApiError("ERR_UNAUTHORIZED", 403, "not the title owner")
    body = get_body()
    start_sec = req_int(body, "retail_sample_start_sec")
    end_sec = req_int(body, "retail_sample_end_sec")
    length = end_sec - start_sec
    if length <= 0 or length > MAX_RETAIL_SAMPLE_SEC:
        raise ApiError("ERR_SAMPLE_TOO_LONG", 422, "invalid retail sample length")
    title["retail_sample_start_sec"] = start_sec
    title["retail_sample_end_sec"] = end_sec
    bump(title)
    return success(clean(title), status=200)


@app.route("/titles/<tid>/publish", methods=["POST"])
def publish_title(tid):
    authenticate({"PlatformAdmin"})
    title = find(TITLES, tid, "ERR_TITLE_NOT_FOUND")
    if title["status"] != "IN_QC":
        raise ApiError("ERR_TITLE_NOT_IN_QC", 409, "title is not in IN_QC")
    contract = contract_for_title(tid, "ACCEPTED")
    approved_full = None
    if contract is not None:
        for m in MILESTONES.values():
            if (m["contract_id"] == contract["id"] and m["milestone_type"] == "FULL"
                    and m["status"] == "APPROVED"):
                approved_full = m
                break
    if approved_full is None:
        raise ApiError("ERR_INVALID_STATE", 409, "no approved FULL milestone")
    title["status"] = "PUBLISHED"
    bump(title)
    # complete active bookings for the title
    affected_narrators = set()
    for b in BOOKINGS.values():
        if b["title_id"] == tid and b["status"] == "ACTIVE":
            b["status"] = "COMPLETED"
            bump(b)
            affected_narrators.add(b["narrator_id"])
    for nid in affected_narrators:
        recompute_active_booked_days(nid)
    return success(clean(title), status=200)


@app.route("/titles/<tid>/revert-rights", methods=["POST"])
def revert_rights(tid):
    user_id, role = authenticate({"Author"})
    title = find(TITLES, tid, "ERR_TITLE_NOT_FOUND")
    if title["author_id"] != user_id:
        raise ApiError("ERR_UNAUTHORIZED", 403, "not the title owner")
    if title["status"] != "PUBLISHED":
        raise ApiError("ERR_TITLE_NOT_REVERTABLE", 409, "title is not PUBLISHED")
    require_title_active(title)
    # cascade root
    title["rights_status"] = "REVERTED"
    title["status"] = "REVERTED"
    bump(title)
    # link 1: ACCEPTED contract -> TERMINATED
    for c in CONTRACTS.values():
        if c["title_id"] == tid and c["status"] == "ACCEPTED":
            c["status"] = "TERMINATED"
            bump(c)
    # link 2: ACTIVE listings -> WITHDRAWN
    for l in LISTINGS.values():
        if l["title_id"] == tid and l["status"] == "ACTIVE":
            l["status"] = "WITHDRAWN"
            bump(l)
    # link 3: PROVISIONAL/FINALIZED statements -> FROZEN
    for s in STATEMENTS.values():
        if s["title_id"] == tid and s["status"] in ("PROVISIONAL", "FINALIZED"):
            s["status"] = "FROZEN"
            bump(s)
    return success(clean(title), status=200)


# ===========================================================================
# Routes: Audition
# ===========================================================================
@app.route("/auditions", methods=["POST"])
def create_audition():
    user_id, role = authenticate({"Narrator"})
    body = get_body()
    title_id = req_str(body, "title_id")
    sample_url = req_str(body, "sample_url")
    title = find(TITLES, title_id, "ERR_TITLE_NOT_FOUND")
    require_title_active(title)
    if title["status"] != "OPEN_FOR_AUDITION":
        raise ApiError("ERR_TITLE_NOT_OPEN", 409, "title is not open for audition")
    rec = new_full_record({
        "title_id": title_id,
        "narrator_id": user_id,
        "sample_url": sample_url,
        "status": "SUBMITTED",
    })
    AUDITIONS[rec["id"]] = rec
    return success(clean(rec), status=201)


@app.route("/auditions/<aid>", methods=["GET"])
def get_audition(aid):
    authenticate({"Author", "Narrator", "PlatformAdmin"})
    rec = find(AUDITIONS, aid, "ERR_AUDITION_NOT_FOUND")
    return success(clean(rec), status=200)


@app.route("/auditions", methods=["GET"])
def list_auditions():
    authenticate({"Author", "Narrator", "PlatformAdmin"})
    title_id = request.args.get("title_id")
    narrator_id = request.args.get("narrator_id")
    status = request.args.get("status")
    items = [a for a in AUDITIONS.values()
             if (title_id is None or a["title_id"] == title_id)
             and (narrator_id is None or a["narrator_id"] == narrator_id)
             and (status is None or a["status"] == status)]
    return list_response(items)


@app.route("/auditions/<aid>/decision", methods=["POST"])
def decide_audition(aid):
    user_id, role = authenticate({"Author"})
    body = get_body()
    decision = req_enum(body, "decision", {"ACCEPT", "DECLINE"})
    audition = find(AUDITIONS, aid, "ERR_AUDITION_NOT_FOUND")
    title = TITLES.get(audition["title_id"])
    if title is None or title["author_id"] != user_id:
        raise ApiError("ERR_UNAUTHORIZED", 403, "not the title owner")
    if audition["status"] != "SUBMITTED":
        raise ApiError("ERR_AUDITION_NOT_SUBMITTED", 409, "audition is not SUBMITTED")
    if decision == "ACCEPT":
        if title["status"] != "OPEN_FOR_AUDITION":
            raise ApiError("ERR_TITLE_NOT_OPEN", 409, "title is not open for audition")
        audition["status"] = "ACCEPTED"
    else:
        audition["status"] = "DECLINED"
    bump(audition)
    return success(clean(audition), status=200)


# ===========================================================================
# Routes: Contract
# ===========================================================================
@app.route("/contracts", methods=["POST"])
def create_contract():
    user_id, role = authenticate({"Author"})
    body = get_body()
    title_id = req_str(body, "title_id")
    narrator_id = req_str(body, "narrator_id")
    deal_type = req_enum(body, "deal_type", {"ROYALTY_SHARE", "PER_HOUR"})
    expected_version = req_int(body, "expected_title_version")
    # value-range validation (bad values -> ERR_VALIDATION)
    royalty_share_pct = body.get("royalty_share_pct")
    per_hour_rate_cents = body.get("per_hour_rate_cents")
    if royalty_share_pct is not None:
        if isinstance(royalty_share_pct, bool) or not isinstance(royalty_share_pct, (int, float)):
            raise ApiError("ERR_VALIDATION", 400, "royalty_share_pct must be a number")
        if not (0 < royalty_share_pct <= 0.50):
            raise ApiError("ERR_VALIDATION", 400, "royalty_share_pct out of range")
    if per_hour_rate_cents is not None:
        if isinstance(per_hour_rate_cents, bool) or not isinstance(per_hour_rate_cents, int):
            raise ApiError("ERR_VALIDATION", 400, "per_hour_rate_cents must be an integer")
        if per_hour_rate_cents <= 0:
            raise ApiError("ERR_VALIDATION", 400, "per_hour_rate_cents must be > 0")
    # existence
    title = find(TITLES, title_id, "ERR_TITLE_NOT_FOUND")
    narrator = find(NARRATORS, narrator_id, "ERR_NARRATOR_NOT_FOUND")
    # ownership
    if title["author_id"] != user_id:
        raise ApiError("ERR_UNAUTHORIZED", 403, "not the title owner")
    # rights
    require_title_active(title)
    # state
    if title["status"] not in ("OPEN_FOR_AUDITION", "CASTING"):
        raise ApiError("ERR_INVALID_STATE", 409, "title is not castable")
    # OCC
    if expected_version != title["version"]:
        raise ApiError("ERR_STALE_TITLE_VERSION", 412, "stale title version")
    # cross-entity linkage: ACCEPTED audition for (title, narrator)
    has_accepted = any(a["title_id"] == title_id and a["narrator_id"] == narrator_id
                       and a["status"] == "ACCEPTED" for a in AUDITIONS.values())
    if not has_accepted:
        raise ApiError("ERR_AUDITION_NOT_ACCEPTED", 409, "no accepted audition for narrator")
    # deal-type coherence
    if deal_type == "ROYALTY_SHARE":
        if royalty_share_pct is None or per_hour_rate_cents is not None:
            raise ApiError("ERR_DEAL_TYPE_FIELDS", 422, "ROYALTY_SHARE requires royalty_share_pct only")
    else:  # PER_HOUR
        if per_hour_rate_cents is None or royalty_share_pct is not None:
            raise ApiError("ERR_DEAL_TYPE_FIELDS", 422, "PER_HOUR requires per_hour_rate_cents only")
    # supersede existing OFFERED contracts on this title
    for c in CONTRACTS.values():
        if c["title_id"] == title_id and c["status"] == "OFFERED":
            c["status"] = "SUPERSEDED"
            bump(c)
    rec = new_full_record({
        "title_id": title_id,
        "narrator_id": narrator_id,
        "deal_type": deal_type,
        "royalty_share_pct": royalty_share_pct if deal_type == "ROYALTY_SHARE" else None,
        "per_hour_rate_cents": per_hour_rate_cents if deal_type == "PER_HOUR" else None,
        "status": "OFFERED",
    })
    CONTRACTS[rec["id"]] = rec
    # title -> CASTING
    title["status"] = "CASTING"
    bump(title)
    return success(clean(rec), status=201)


@app.route("/contracts/<cid>", methods=["GET"])
def get_contract(cid):
    authenticate({"Author", "Narrator", "PlatformAdmin"})
    rec = find(CONTRACTS, cid, "ERR_CONTRACT_NOT_FOUND")
    return success(clean(rec), status=200)


@app.route("/contracts", methods=["GET"])
def list_contracts():
    authenticate({"Author", "Narrator", "PlatformAdmin"})
    title_id = request.args.get("title_id")
    narrator_id = request.args.get("narrator_id")
    status = request.args.get("status")
    items = [c for c in CONTRACTS.values()
             if (title_id is None or c["title_id"] == title_id)
             and (narrator_id is None or c["narrator_id"] == narrator_id)
             and (status is None or c["status"] == status)]
    return list_response(items)


@app.route("/contracts/<cid>/respond", methods=["POST"])
def respond_contract(cid):
    user_id, role = authenticate({"Narrator"})
    body = get_body()
    decision = req_enum(body, "decision", {"ACCEPT", "DECLINE"})
    contract = find(CONTRACTS, cid, "ERR_CONTRACT_NOT_FOUND")
    if contract["narrator_id"] != user_id:
        raise ApiError("ERR_UNAUTHORIZED", 403, "not the contract narrator")
    if contract["status"] != "OFFERED":
        raise ApiError("ERR_CONTRACT_NOT_OFFERED", 409, "contract is not OFFERED")
    title = TITLES.get(contract["title_id"])
    if decision == "ACCEPT":
        contract["status"] = "ACCEPTED"
        if title is not None:
            title["status"] = "IN_PRODUCTION"
            bump(title)
    else:
        contract["status"] = "DECLINED"
        if title is not None:
            title["status"] = "OPEN_FOR_AUDITION"
            bump(title)
    bump(contract)
    return success(clean(contract), status=200)


# ===========================================================================
# Routes: Production Booking
# ===========================================================================
@app.route("/production-bookings", methods=["POST"])
def create_booking():
    user_id, role = authenticate({"Narrator"})
    body = get_body()
    title_id = req_str(body, "title_id")
    start_date = req_str(body, "start_date")
    end_date = req_str(body, "end_date")
    find(TITLES, title_id, "ERR_TITLE_NOT_FOUND")
    sd = parse_date(start_date)
    ed = parse_date(end_date)
    if not (sd < ed):
        raise ApiError("ERR_INVALID_DATE_RANGE", 422, "start_date must be before end_date")
    # overlap check against this narrator's ACTIVE bookings (half-open intervals)
    for b in BOOKINGS.values():
        if b["narrator_id"] == user_id and b["status"] == "ACTIVE":
            bs = parse_date(b["start_date"])
            be = parse_date(b["end_date"])
            if sd < be and bs < ed:
                raise ApiError("ERR_BOOKING_OVERLAP", 409, "booking overlaps an active booking")
    rec = new_full_record({
        "narrator_id": user_id,
        "title_id": title_id,
        "start_date": start_date,
        "end_date": end_date,
        "status": "ACTIVE",
    })
    BOOKINGS[rec["id"]] = rec
    recompute_active_booked_days(user_id)
    return success(clean(rec), status=201)


@app.route("/production-bookings/<bid>", methods=["GET"])
def get_booking(bid):
    authenticate({"Narrator", "PlatformAdmin"})
    rec = find(BOOKINGS, bid, "ERR_BOOKING_NOT_FOUND")
    return success(clean(rec), status=200)


@app.route("/production-bookings", methods=["GET"])
def list_bookings():
    authenticate({"Narrator", "PlatformAdmin"})
    narrator_id = request.args.get("narrator_id")
    title_id = request.args.get("title_id")
    status = request.args.get("status")
    items = [b for b in BOOKINGS.values()
             if (narrator_id is None or b["narrator_id"] == narrator_id)
             and (title_id is None or b["title_id"] == title_id)
             and (status is None or b["status"] == status)]
    return list_response(items)


@app.route("/production-bookings/<bid>/cancel", methods=["POST"])
def cancel_booking(bid):
    user_id, role = authenticate({"Narrator"})
    booking = find(BOOKINGS, bid, "ERR_BOOKING_NOT_FOUND")
    if booking["narrator_id"] != user_id:
        raise ApiError("ERR_UNAUTHORIZED", 403, "not the booking owner")
    if booking["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "booking is not ACTIVE")
    booking["status"] = "CANCELLED"
    bump(booking)
    recompute_active_booked_days(user_id)
    return success(clean(booking), status=200)


# ===========================================================================
# Routes: Production Milestone
# ===========================================================================
@app.route("/production-milestones", methods=["POST"])
def create_milestone():
    user_id, role = authenticate({"Narrator"})
    body = get_body()
    contract_id = req_str(body, "contract_id")
    milestone_type = req_enum(body, "milestone_type", {"FIFTEEN_MIN", "FULL"})
    audio_url = req_str(body, "audio_url")
    finished_hours = body.get("finished_hours")
    contract = find(CONTRACTS, contract_id, "ERR_CONTRACT_NOT_FOUND")
    # ownership
    if contract["narrator_id"] != user_id:
        raise ApiError("ERR_UNAUTHORIZED", 403, "not the contract narrator")
    title = TITLES.get(contract["title_id"])
    if title is not None:
        require_title_active(title)
    # state: contract must be ACCEPTED
    if contract["status"] != "ACCEPTED":
        raise ApiError("ERR_CONTRACT_NOT_ACCEPTED", 409, "contract is not ACCEPTED")
    # finished_hours validity for FULL
    if milestone_type == "FULL":
        if finished_hours is None or isinstance(finished_hours, bool) \
                or not isinstance(finished_hours, (int, float)) or finished_hours <= 0:
            raise ApiError("ERR_INVALID_FINISHED_HOURS", 422, "FULL milestone needs finished_hours > 0")
        stored_hours = finished_hours
    else:
        stored_hours = None
    rec = new_full_record({
        "contract_id": contract_id,
        "milestone_type": milestone_type,
        "audio_url": audio_url,
        "finished_hours": stored_hours,
        "status": "SUBMITTED",
        "revision_count": 0,
    })
    MILESTONES[rec["id"]] = rec
    if milestone_type == "FULL" and title is not None and title["status"] == "IN_PRODUCTION":
        title["status"] = "IN_QC"
        bump(title)
    return success(clean(rec), status=201)


@app.route("/production-milestones/<mid>", methods=["GET"])
def get_milestone(mid):
    authenticate({"Narrator", "Author", "QCReviewer", "PlatformAdmin"})
    rec = find(MILESTONES, mid, "ERR_MILESTONE_NOT_FOUND")
    return success(clean(rec), status=200)


@app.route("/production-milestones", methods=["GET"])
def list_milestones():
    authenticate({"Narrator", "Author", "QCReviewer", "PlatformAdmin"})
    contract_id = request.args.get("contract_id")
    status = request.args.get("status")
    items = [m for m in MILESTONES.values()
             if (contract_id is None or m["contract_id"] == contract_id)
             and (status is None or m["status"] == status)]
    return list_response(items)


@app.route("/production-milestones/<mid>/resubmit", methods=["POST"])
def resubmit_milestone(mid):
    user_id, role = authenticate({"Narrator"})
    milestone = find(MILESTONES, mid, "ERR_MILESTONE_NOT_FOUND")
    body = get_body()
    audio_url = req_str(body, "audio_url")
    contract = CONTRACTS.get(milestone["contract_id"])
    if contract is None or contract["narrator_id"] != user_id:
        raise ApiError("ERR_UNAUTHORIZED", 403, "not the contract narrator")
    if milestone["status"] != "REVISION_REQUESTED":
        raise ApiError("ERR_MILESTONE_NOT_REVISABLE", 409, "milestone is not REVISION_REQUESTED")
    milestone["audio_url"] = audio_url
    milestone["status"] = "SUBMITTED"
    bump(milestone)
    if milestone["milestone_type"] == "FULL":
        title = TITLES.get(contract["title_id"])
        if title is not None and title["status"] == "IN_PRODUCTION":
            title["status"] = "IN_QC"
            bump(title)
    return success(clean(milestone), status=200)


# ===========================================================================
# Routes: QC Review
# ===========================================================================
@app.route("/production-milestones/<mid>/qc-reviews", methods=["POST"])
def create_qc_review(mid):
    authenticate({"QCReviewer"})
    milestone = find(MILESTONES, mid, "ERR_MILESTONE_NOT_FOUND")
    body = get_body()
    outcome = req_enum(body, "outcome", {"PASS", "FAIL"})
    notes = body.get("notes")
    if outcome == "FAIL":
        if notes is None or not isinstance(notes, str) or notes == "":
            raise ApiError("ERR_VALIDATION", 400, "notes required on FAIL")
    if milestone["status"] != "SUBMITTED":
        raise ApiError("ERR_MILESTONE_NOT_SUBMITTED", 409, "milestone is not SUBMITTED")
    review = new_light_record({
        "milestone_id": mid,
        "outcome": outcome,
        "notes": notes if notes is not None else None,
    })
    QCREVIEWS[review["id"]] = review
    contract = CONTRACTS.get(milestone["contract_id"])
    title = TITLES.get(contract["title_id"]) if contract else None
    if outcome == "PASS":
        milestone["status"] = "APPROVED"
        bump(milestone)
        if milestone["milestone_type"] == "FULL":
            if title is not None:
                title["finished_hours"] = milestone["finished_hours"]
                bump(title)
            if contract is not None and contract["deal_type"] == "PER_HOUR":
                fee = round_half_up(Decimal(str(milestone["finished_hours"]))
                                    * Decimal(contract["per_hour_rate_cents"]))
                narrator = NARRATORS.get(contract["narrator_id"])
                if narrator is not None:
                    narrator["payout_balance_cents"] += fee
    else:  # FAIL
        if milestone["revision_count"] < MAX_REVISIONS:
            milestone["status"] = "REVISION_REQUESTED"
        else:
            milestone["status"] = "REJECTED"
        milestone["revision_count"] += 1
        bump(milestone)
        if milestone["milestone_type"] == "FULL" and title is not None and title["status"] == "IN_QC":
            title["status"] = "IN_PRODUCTION"
            bump(title)
    return success(clean(review), status=201)


@app.route("/qc-reviews/<qid>", methods=["GET"])
def get_qc_review(qid):
    authenticate({"QCReviewer", "Author", "PlatformAdmin"})
    rec = find(QCREVIEWS, qid, "ERR_RESOURCE_NOT_FOUND")
    return success(clean(rec), status=200)


@app.route("/qc-reviews", methods=["GET"])
def list_qc_reviews():
    authenticate({"QCReviewer", "Author", "PlatformAdmin"})
    milestone_id = request.args.get("milestone_id")
    items = [q for q in QCREVIEWS.values()
             if (milestone_id is None or q["milestone_id"] == milestone_id)]
    return list_response(items)


# ===========================================================================
# Routes: Distribution Channel
# ===========================================================================
@app.route("/distribution-channels", methods=["POST"])
def create_channel():
    authenticate({"PlatformAdmin"})
    body = get_body()
    name = req_str(body, "name")
    supported = require_present(body, "supported_territories")
    if not isinstance(supported, list) or not supported:
        raise ApiError("ERR_VALIDATION", 400, "supported_territories must be a non-empty array")
    for t in supported:
        if t not in TERRITORIES:
            raise ApiError("ERR_VALIDATION", 400, "invalid territory: %s" % t)
    cut = req_number(body, "retailer_cut_pct")
    if not (0 <= cut < 1):
        raise ApiError("ERR_VALIDATION", 400, "retailer_cut_pct must be in [0, 1)")
    rec = new_full_record({
        "name": name,
        "supported_territories": list(supported),
        "retailer_cut_pct": cut,
    })
    CHANNELS[rec["id"]] = rec
    return success(clean(rec), status=201)


@app.route("/distribution-channels/<cid>", methods=["GET"])
def get_channel(cid):
    authenticate({"PlatformAdmin", "Author"})
    rec = find(CHANNELS, cid, "ERR_CHANNEL_NOT_FOUND")
    return success(clean(rec), status=200)


# ===========================================================================
# Routes: Distribution Listing
# ===========================================================================
@app.route("/distribution-listings", methods=["POST"])
def create_listing():
    authenticate({"PlatformAdmin"})
    body = get_body()
    title_id = req_str(body, "title_id")
    channel_id = req_str(body, "channel_id")
    territory = req_enum(body, "territory", TERRITORIES)
    effective_from = req_str(body, "effective_from")
    effective_until = req_str(body, "effective_until")
    title = find(TITLES, title_id, "ERR_TITLE_NOT_FOUND")
    channel = find(CHANNELS, channel_id, "ERR_CHANNEL_NOT_FOUND")
    # rights
    require_title_active(title)
    # state: title must be PUBLISHED
    if title["status"] != "PUBLISHED":
        raise ApiError("ERR_TITLE_NOT_PUBLISHED", 409, "title is not PUBLISHED")
    # cross-entity: territory supported by channel and within title grant
    if territory not in channel["supported_territories"]:
        raise ApiError("ERR_TERRITORY_NOT_SUPPORTED", 409, "territory not served by channel")
    if title["territory"] != "WORLD" and territory != title["territory"]:
        raise ApiError("ERR_TERRITORY_NOT_SUPPORTED", 409, "territory outside title grant")
    # date validity
    ef = parse_date(effective_from)
    eu = parse_date(effective_until)
    if ef > eu:
        raise ApiError("ERR_INVALID_DATE_RANGE", 422, "effective_from after effective_until")
    # gap check against non-WITHDRAWN listings on same (title, channel)
    latest_until = None
    for l in LISTINGS.values():
        if l["title_id"] == title_id and l["channel_id"] == channel_id and l["status"] != "WITHDRAWN":
            lu = parse_date(l["effective_until"])
            if latest_until is None or lu > latest_until:
                latest_until = lu
    if latest_until is not None:
        if not (ef > latest_until + timedelta(days=DISTRIBUTION_GAP_DAYS)):
            raise ApiError("ERR_LISTING_GAP_CONFLICT", 409, "listing violates distribution gap")
    rec = new_full_record({
        "title_id": title_id,
        "channel_id": channel_id,
        "territory": territory,
        "effective_from": effective_from,
        "effective_until": effective_until,
        "status": "ACTIVE",
    })
    LISTINGS[rec["id"]] = rec
    return success(clean(rec), status=201)


@app.route("/distribution-listings/<lid>", methods=["GET"])
def get_listing(lid):
    authenticate({"PlatformAdmin", "Author"})
    rec = find(LISTINGS, lid, "ERR_LISTING_NOT_FOUND")
    return success(clean(rec), status=200)


@app.route("/distribution-listings", methods=["GET"])
def list_listings():
    authenticate({"PlatformAdmin", "Author"})
    title_id = request.args.get("title_id")
    channel_id = request.args.get("channel_id")
    status = request.args.get("status")
    items = [l for l in LISTINGS.values()
             if (title_id is None or l["title_id"] == title_id)
             and (channel_id is None or l["channel_id"] == channel_id)
             and (status is None or l["status"] == status)]
    return list_response(items)


@app.route("/distribution-listings/<lid>/withdraw", methods=["POST"])
def withdraw_listing(lid):
    authenticate({"PlatformAdmin"})
    listing = find(LISTINGS, lid, "ERR_LISTING_NOT_FOUND")
    if listing["status"] != "ACTIVE":
        raise ApiError("ERR_LISTING_NOT_ACTIVE", 409, "listing is not ACTIVE")
    listing["status"] = "WITHDRAWN"
    bump(listing)
    return success(clean(listing), status=200)


# ===========================================================================
# Routes: Sales Event
# ===========================================================================
@app.route("/sales-events", methods=["POST"])
def create_sales_event():
    authenticate({"PlatformAdmin"})
    body = get_body()
    listing_id = req_str(body, "listing_id")
    units_sold = req_int(body, "units_sold")
    if units_sold < 0:
        raise ApiError("ERR_VALIDATION", 400, "units_sold must be >= 0")
    units_returned = body.get("units_returned", 0)
    if units_returned is None:
        units_returned = 0
    if isinstance(units_returned, bool) or not isinstance(units_returned, int):
        raise ApiError("ERR_VALIDATION", 400, "units_returned must be an integer")
    if units_returned < 0 or units_returned > units_sold:
        raise ApiError("ERR_VALIDATION", 400, "units_returned out of range")
    unit_price = req_int(body, "unit_price_cents")
    if unit_price <= 0:
        raise ApiError("ERR_VALIDATION", 400, "unit_price_cents must be > 0")
    occurred_at = body.get("occurred_at")
    if occurred_at is None:
        occurred_at = now_iso()
    else:
        parse_dt(occurred_at)  # validate format
    listing = find(LISTINGS, listing_id, "ERR_LISTING_NOT_FOUND")
    if listing["status"] != "ACTIVE":
        raise ApiError("ERR_LISTING_NOT_ACTIVE", 409, "listing is not ACTIVE")
    rec = new_light_record({
        "listing_id": listing_id,
        "units_sold": units_sold,
        "units_returned": units_returned,
        "unit_price_cents": unit_price,
        "occurred_at": occurred_at,
    })
    SALES[rec["id"]] = rec
    return success(clean(rec), status=201)


@app.route("/sales-events/<sid>", methods=["GET"])
def get_sales_event(sid):
    authenticate({"PlatformAdmin"})
    rec = find(SALES, sid, "ERR_RESOURCE_NOT_FOUND")
    return success(clean(rec), status=200)


@app.route("/sales-events", methods=["GET"])
def list_sales_events():
    authenticate({"PlatformAdmin", "Author"})
    listing_id = request.args.get("listing_id")
    items = [s for s in SALES.values()
             if (listing_id is None or s["listing_id"] == listing_id)]
    return list_response(items)


# ===========================================================================
# Routes: Royalty Statement
# ===========================================================================
@app.route("/royalty-statements", methods=["POST"])
def create_statement():
    authenticate({"PlatformAdmin"})
    body = get_body()
    title_id = req_str(body, "title_id")
    period_start = req_str(body, "period_start")
    period_end = req_str(body, "period_end")
    parse_dt(period_start)
    parse_dt(period_end)
    title = find(TITLES, title_id, "ERR_TITLE_NOT_FOUND")
    require_title_active(title)
    contract = contract_for_title(title_id, "ACCEPTED")
    if contract is None:
        contract = contract_for_title(title_id, "TERMINATED")
    amounts = compute_statement_amounts(title, contract, period_start, period_end, "PROVISIONAL") \
        if contract is not None else {
            "narrator_share_pct_applied": 0,
            "gross_sales_cents": 0,
            "statement_net_cents": 0,
            "narrator_royalty_cents": 0,
            "author_royalty_cents": 0,
        }
    rec = new_full_record({
        "title_id": title_id,
        "period_start": period_start,
        "period_end": period_end,
        "variant": "PROVISIONAL",
        "status": "PROVISIONAL",
        "narrator_share_pct_applied": amounts["narrator_share_pct_applied"],
        "gross_sales_cents": amounts["gross_sales_cents"],
        "statement_net_cents": amounts["statement_net_cents"],
        "narrator_royalty_cents": amounts["narrator_royalty_cents"],
        "author_royalty_cents": amounts["author_royalty_cents"],
        "_author_id": title["author_id"],
        "_narrator_id": contract["narrator_id"] if contract is not None else None,
    })
    STATEMENTS[rec["id"]] = rec
    return success(clean(rec), status=201)


@app.route("/royalty-statements/<sid>", methods=["GET"])
def get_statement(sid):
    authenticate({"PlatformAdmin", "Author", "Narrator"})
    rec = find(STATEMENTS, sid, "ERR_STATEMENT_NOT_FOUND")
    return success(clean(rec), status=200)


@app.route("/royalty-statements", methods=["GET"])
def list_statements():
    authenticate({"PlatformAdmin", "Author", "Narrator"})
    title_id = request.args.get("title_id")
    status = request.args.get("status")
    items = [s for s in STATEMENTS.values()
             if (title_id is None or s["title_id"] == title_id)
             and (status is None or s["status"] == status)]
    return list_response(items)


@app.route("/royalty-statements/<sid>/finalize", methods=["POST"])
def finalize_statement(sid):
    authenticate({"PlatformAdmin"})
    stmt = find(STATEMENTS, sid, "ERR_STATEMENT_NOT_FOUND")
    if stmt["status"] != "PROVISIONAL":
        raise ApiError("ERR_STATEMENT_NOT_PROVISIONAL", 409, "statement is not PROVISIONAL")
    title = TITLES.get(stmt["title_id"])
    contract = contract_for_title(stmt["title_id"], "ACCEPTED")
    if contract is None:
        contract = contract_for_title(stmt["title_id"], "TERMINATED")
    if title is not None and contract is not None:
        amounts = compute_statement_amounts(title, contract, stmt["period_start"],
                                             stmt["period_end"], "FINAL")
        stmt.update({
            "narrator_share_pct_applied": amounts["narrator_share_pct_applied"],
            "gross_sales_cents": amounts["gross_sales_cents"],
            "statement_net_cents": amounts["statement_net_cents"],
            "narrator_royalty_cents": amounts["narrator_royalty_cents"],
            "author_royalty_cents": amounts["author_royalty_cents"],
        })
    stmt["variant"] = "FINAL"
    stmt["status"] = "FINALIZED"
    bump(stmt)
    return success(clean(stmt), status=200)


@app.route("/royalty-statements/<sid>/pay", methods=["POST"])
def pay_statement(sid):
    authenticate({"PlatformAdmin"})
    stmt = find(STATEMENTS, sid, "ERR_STATEMENT_NOT_FOUND")
    if stmt["status"] != "FINALIZED":
        raise ApiError("ERR_STATEMENT_NOT_FINALIZED", 409, "statement is not FINALIZED")
    if stmt["narrator_royalty_cents"] + stmt["author_royalty_cents"] <= 0:
        raise ApiError("ERR_NOTHING_TO_PAY", 402, "nothing to distribute")
    author = AUTHORS.get(stmt.get("_author_id"))
    if author is not None:
        author["payout_balance_cents"] += stmt["author_royalty_cents"]
    narrator = NARRATORS.get(stmt.get("_narrator_id"))
    if narrator is not None:
        narrator["payout_balance_cents"] += stmt["narrator_royalty_cents"]
    stmt["status"] = "PAID"
    bump(stmt)
    return success(clean(stmt), status=200)


@app.route("/royalty-statements/<sid>/reverse", methods=["POST"])
def reverse_statement(sid):
    authenticate({"PlatformAdmin"})
    stmt = find(STATEMENTS, sid, "ERR_STATEMENT_NOT_FOUND")
    if stmt["status"] != "PAID":
        raise ApiError("ERR_STATEMENT_NOT_PAID", 409, "statement is not PAID")
    author = AUTHORS.get(stmt.get("_author_id"))
    if author is not None:
        author["payout_balance_cents"] -= stmt["author_royalty_cents"]
    narrator = NARRATORS.get(stmt.get("_narrator_id"))
    if narrator is not None:
        narrator["payout_balance_cents"] -= stmt["narrator_royalty_cents"]
    stmt["status"] = "REVERSED"
    bump(stmt)
    return success(clean(stmt), status=200)


# ===========================================================================
# Routes: Logical clock (test harness)
# ===========================================================================
@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    authenticate({"PlatformAdmin"})
    body = get_body()
    to_iso = req_str(body, "to_iso8601")
    CLOCK["now"] = parse_dt(to_iso)
    return success({}, status=200)


# ===========================================================================
# Entrypoint
# ===========================================================================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
