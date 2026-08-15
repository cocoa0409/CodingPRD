"""Branch Teller Operations API — Flask implementation (PRD: workspace/PRD.md).

In-memory store; logical clock with ms auto-increment; per-test fresh boot.
"""
import os
import re
import uuid
from datetime import datetime, timedelta, date
from fractions import Fraction

from flask import Flask, request, jsonify

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Constants (PRD §3)
# ---------------------------------------------------------------------------
CTR_THRESHOLD_CENTS = 1_000_000          # strictly-greater trigger
TELLER_TRANSACTION_LIMIT_CENTS = 500_000  # inclusive limit
MONEY_ORDER_MAX_CENTS = 100_000
CASHIERS_CHECK_FEE_CENTS = 800
MONEY_ORDER_FEE_CENTS = 200
NEXT_DAY_AVAILABILITY_CENTS = 20_000
LARGE_CHECK_FACE_CENTS = 500_000         # <= is STANDARD
STANDARD_HOLD_DAYS = 2
LARGE_CHECK_HOLD_DAYS = 7
WAIVED_HOLD_DAYS = 1
ORDER_STEP_CENTS = 100_000
VAULT_CAPACITY_CENTS = 100_000_000
OVER_SHORT_WAIVE_FACTOR = 2
FORECAST_WINDOW_DAYS = 28
FORECAST_MIN_SAMPLES = 3
DOW_WEIGHT_SAME = Fraction(7, 10)
DOW_WEIGHT_OTHER = Fraction(3, 10)
CLOCK_DEFAULT = "2026-08-01T00:00:00Z"

ROLES = {"BranchManager", "HeadTeller", "Teller", "Auditor"}

TXN_TYPES = {
    "CASH_DEPOSIT", "CASH_WITHDRAWAL", "CHECK_DEPOSIT",
    "CASHIERS_CHECK_PURCHASE", "MONEY_ORDER_PURCHASE",
}
INSTRUMENT_TXN_TYPES = {"CASHIERS_CHECK_PURCHASE", "MONEY_ORDER_PURCHASE"}
REQUEST_TYPES = {"ISSUE_INSTRUMENT", "FEE_WAIVER", "OVER_LIMIT_TRANSACTION"}

ERR_HTTP = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 400,
    "ERR_INVALID_STATE": 409,
    "ERR_ACCOUNT_CLOSED": 409,
    "ERR_ACCOUNT_NOT_SETTLED": 409,
    "ERR_OVER_SHORT_UNRESOLVED": 409,
    "ERR_HOLD_ALREADY_RELEASED": 409,
    "ERR_BRANCH_FROZEN": 409,
    "ERR_DUAL_CONTROL_VIOLATION": 409,
    "ERR_SOD_VIOLATION": 409,
    "ERR_TELLER_SUSPENDED": 409,
    "ERR_INSTRUMENT_REQUIRES_APPROVAL": 409,
    "ERR_DRAWER_ALREADY_OPEN": 409,
    "ERR_DUPLICATE_CASH_ORDER": 409,
    "ERR_AUDIT_IN_PROGRESS": 409,
    "ERR_WAIVER_NOT_ALLOWED": 422,
    "ERR_INVALID_DELIVERY_DATE": 422,
    "ERR_ORDER_NOT_DUE": 409,
    "ERR_INVALID_AUDIT_DATE": 422,
    "ERR_AUDIT_NOT_DUE": 409,
    "ERR_CLOCK_REGRESSION": 422,
    "ERR_CROSS_BRANCH": 422,
    "ERR_TRANSACTION_NOT_FOUND": 404,
    "ERR_INSUFFICIENT_DRAWER_CASH": 422,
    "ERR_INSUFFICIENT_FUNDS": 422,
    "ERR_TRANSACTION_OVER_LIMIT": 422,
    "ERR_DRAWER_LIMIT": 422,
    "ERR_INSUFFICIENT_VAULT_CASH": 422,
    "ERR_INSTRUMENT_LIMIT": 422,
    "ERR_ORDER_BELOW_MINIMUM": 422,
    "ERR_VAULT_CAPACITY_EXCEEDED": 422,
    "ERR_STALE_VERSION": 412,
}

# ---------------------------------------------------------------------------
# Store (in-memory; empty at every boot — no seeding)
# ---------------------------------------------------------------------------
class Store:
    def __init__(self):
        self.branches = {}
        self.tellers = {}
        self.accounts = {}
        self.drawers = {}
        self.transactions = {}
        self.cash_orders = {}
        self.teller_requests = {}
        self.holds = {}
        self.ctr_filings = {}
        self.over_short_cases = {}
        self.approvals = {}
        self.audits = {}
        self.now = datetime.strptime(CLOCK_DEFAULT, "%Y-%m-%dT%H:%M:%SZ")

    def tick(self):
        """Advance the logical clock by 1ms so created_at strictly increases."""
        self.now += timedelta(milliseconds=1)
        return self.now

DB = Store()

def iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"

def business_date(dt=None):
    return (dt or DB.now).date().isoformat()

def new_id():
    return str(uuid.uuid4())

def common_new():
    ts = iso(DB.tick())
    return {"id": new_id(), "created_at": ts, "updated_at": ts, "version": 1}

def touch(ent):
    ent["updated_at"] = iso(DB.tick())
    ent["version"] += 1

# ---------------------------------------------------------------------------
# Errors + envelope
# ---------------------------------------------------------------------------
class ApiError(Exception):
    def __init__(self, error_id, message=""):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http = ERR_HTTP[error_id]
        self.message = message or error_id

def fail(error_id, message=""):
    raise ApiError(error_id, message)

def _strip_internal(x):
    if isinstance(x, dict):
        return {k: _strip_internal(v) for k, v in x.items() if not k.startswith("_")}
    if isinstance(x, list):
        return [_strip_internal(v) for v in x]
    return x

def envelope_success(data, status=200, pagination=None):
    data = _strip_internal(data)
    meta = {
        "api_request_id": "req_" + uuid.uuid4().hex[:20],
        "api_request_timestamp": iso(DB.now),
    }
    if pagination is not None:
        meta.update(pagination)
    body = {
        "meta": meta,
        "response_type": "array" if isinstance(data, list) else "object",
        "data": data,
    }
    return jsonify(body), status

@app.errorhandler(ApiError)
def handle_api_error(e):
    body = {
        "meta": {
            "api_request_id": "req_" + uuid.uuid4().hex[:20],
            "api_request_timestamp": iso(DB.now),
        },
        "response_type": "error",
        "data": {"error_id": e.error_id, "message": e.message},
    }
    return jsonify(body), e.http

@app.errorhandler(404)
def handle_404(e):
    return handle_api_error(ApiError("ERR_NOT_FOUND", "resource not found"))

@app.errorhandler(405)
def handle_405(e):
    return handle_api_error(ApiError("ERR_NOT_FOUND", "resource not found"))

@app.errorhandler(Exception)
def handle_generic(e):
    return handle_api_error(ApiError("ERR_INVALID_REQUEST", str(e)))

# ---------------------------------------------------------------------------
# Auth / roles
# ---------------------------------------------------------------------------
def auth():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        fail("ERR_UNAUTHENTICATED", "missing or invalid X-User-ID / X-User-Role")
    return uid, role

def require_role(role, allowed):
    if role not in allowed:
        fail("ERR_FORBIDDEN", "role not permitted")

def payload_json(require_object=True):
    body = request.get_json(silent=True)
    if body is None:
        body = {}
    if require_object and not isinstance(body, dict):
        fail("ERR_INVALID_REQUEST", "body must be a JSON object")
    return body

def need_fields(body, fields):
    for f in fields:
        if f not in body or body[f] is None:
            fail("ERR_INVALID_REQUEST", f"missing required field {f}")

def need_positive_int(body, field):
    v = body.get(field)
    if not isinstance(v, int) or isinstance(v, bool) or v <= 0:
        fail("ERR_INVALID_REQUEST", f"{field} must be a positive integer")

def get_path(store, rid):
    ent = store.get(rid)
    if ent is None:
        fail("ERR_NOT_FOUND", "resource not found")
    return ent

def parse_iso(s):
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(\.\d+)?Z$", str(s))
    if not m:
        fail("ERR_INVALID_REQUEST", "to_iso8601 must be an ISO 8601 UTC timestamp")
    y, mo, d, h, mi, sec = (int(m.group(i)) for i in range(1, 7))
    frac = m.group(7) or ""
    micros = int((frac[1:] + "000000")[:6]) if frac else 0
    try:
        return datetime(y, mo, d, h, mi, sec, micros)
    except ValueError:
        fail("ERR_INVALID_REQUEST", "invalid timestamp")

def parse_date(s):
    try:
        return date.fromisoformat(str(s))
    except ValueError:
        return None

def is_weekday(d):
    return d.weekday() < 5

def add_business_days(d, n):
    cur = d
    added = 0
    while added < n:
        cur += timedelta(days=1)
        if cur.weekday() < 5:
            added += 1
    return cur

def paginate(items, query):
    def pint(name, default):
        raw = query.get(name)
        if raw is None:
            return default
        try:
            v = int(raw)
        except (TypeError, ValueError):
            fail("ERR_INVALID_REQUEST", f"{name} must be an integer")
        return v
    limit = pint("limit", 10)
    offset = pint("offset", 0)
    if limit < 1 or limit > 100 or offset < 0:
        fail("ERR_INVALID_REQUEST", "limit/offset out of range")
    total = len(items)
    page = items[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + len(page) < total,
    }
    return page, meta

# ---------------------------------------------------------------------------
# Domain helpers
# ---------------------------------------------------------------------------
def txn_cash_delta(t):
    """STRICT cash delta of a transaction on its drawer."""
    ty = t["type"]
    if ty == "CASH_DEPOSIT":
        return t["amount_cents"]
    if ty == "CASH_WITHDRAWAL":
        return -t["amount_cents"]
    if ty == "CHECK_DEPOSIT":
        return 0
    return t["amount_cents"] + t["fee_cents"]  # instrument purchases: face + fee in

def expected_cash(drawer, variant="STRICT"):
    total = drawer["_baseline_cash_cents"] + drawer["_buy_sell_net_cents"]
    for t in DB.transactions.values():
        if t["drawer_id"] == drawer["id"] and t["status"] == "POSTED":
            if variant == "LENIENT" and t["type"] in INSTRUMENT_TXN_TYPES:
                continue
            total += txn_cash_delta(t)
    return total

def ctr_totals(account_id, branch_id, bdate):
    cash_in = 0
    cash_out = 0
    ids = []
    txns = [t for t in DB.transactions.values()
            if t["account_id"] == account_id and t["branch_id"] == branch_id
            and t["_business_date"] == bdate and t["status"] == "POSTED"
            and not t["is_ctr_exempt"]]
    txns.sort(key=lambda t: (t["created_at"], t["id"]))
    for t in txns:
        if t["type"] == "CASH_DEPOSIT":
            cash_in += t["amount_cents"]
            ids.append(t["id"])
        elif t["type"] == "CASH_WITHDRAWAL":
            cash_out += t["amount_cents"]
            ids.append(t["id"])
        elif t["type"] in INSTRUMENT_TXN_TYPES:
            cash_in += t["amount_cents"]  # face only; fee excluded
            ids.append(t["id"])
    return cash_in, cash_out, ids

def ctr_reevaluate(account_id, branch_id, bdate):
    cash_in, cash_out, ids = ctr_totals(account_id, branch_id, bdate)
    crossed_in = cash_in > CTR_THRESHOLD_CENTS
    crossed_out = cash_out > CTR_THRESHOLD_CENTS
    existing = [f for f in DB.ctr_filings.values()
                if f["account_id"] == account_id and f["branch_id"] == branch_id
                and f["business_date"] == bdate]
    if crossed_in or crossed_out:
        direction = "BOTH" if (crossed_in and crossed_out) else ("CASH_IN" if crossed_in else "CASH_OUT")
        if existing:
            f = existing[0]
            f["total_cash_in_cents"] = cash_in
            f["total_cash_out_cents"] = cash_out
            f["transaction_ids"] = ids
            f["trigger_direction"] = direction
            f["status"] = "FILED"  # AMENDED returns to FILED
        else:
            f = {
                "id": new_id(), "created_at": iso(DB.tick()),
                "branch_id": branch_id, "account_id": account_id,
                "business_date": bdate,
                "total_cash_in_cents": cash_in,
                "total_cash_out_cents": cash_out,
                "trigger_direction": direction,
                "transaction_ids": ids,
                "status": "FILED",
            }
            DB.ctr_filings[f["id"]] = f
    else:
        for f in existing:
            if f["status"] == "FILED":
                f["total_cash_in_cents"] = cash_in
                f["total_cash_out_cents"] = cash_out
                f["transaction_ids"] = ids
                f["trigger_direction"] = "CASH_IN" if cash_in > CTR_THRESHOLD_CENTS else (
                    "CASH_OUT" if cash_out > CTR_THRESHOLD_CENTS else f["trigger_direction"])
                f["status"] = "AMENDED"

def forecast(branch, delivery_date_str, today_str):
    """Returns (projected_need_cents, weighted_need_cents). Exact rational math."""
    order_date = date.fromisoformat(today_str)
    delivery = date.fromisoformat(delivery_date_str)
    win_start = order_date - timedelta(days=FORECAST_WINDOW_DAYS)
    win_end = order_date - timedelta(days=1)
    nets = {}  # date -> net outflow for sampled days
    txns = [t for t in DB.transactions.values()
            if t["branch_id"] == branch["id"] and t["status"] == "POSTED"
            and t["type"] in ("CASH_DEPOSIT", "CASH_WITHDRAWAL")]
    by_date = {}
    for t in txns:
        d = date.fromisoformat(t["_business_date"])
        if win_start <= d <= win_end:
            by_date.setdefault(d, [0, 0])
            if t["type"] == "CASH_DEPOSIT":
                by_date[d][0] += t["amount_cents"]
            else:
                by_date[d][1] += t["amount_cents"]
    for d, (ci, co) in by_date.items():
        nets[d] = co - ci  # sampled iff >= 1 cash txn (guaranteed by construction)
    same = [v for d, v in nets.items() if d.weekday() == delivery.weekday()]
    other = [v for d, v in nets.items() if d.weekday() != delivery.weekday()]

    def mean(xs):
        return Fraction(sum(xs), len(xs)) if xs else None

    ms, mo = mean(same), mean(other)

    def ceil_frac(fr):
        return -(-fr.numerator // fr.denominator)  # ceil for any sign

    if len(same) >= FORECAST_MIN_SAMPLES:
        projected = ceil_frac(ms)
    elif ms is None and mo is None:
        projected = 0
    elif ms is None:
        projected = ceil_frac(mo)
    elif mo is None:
        projected = ceil_frac(ms)
    else:
        projected = ceil_frac(DOW_WEIGHT_SAME * ms + DOW_WEIGHT_OTHER * mo)
    weighted = ceil_frac(DOW_WEIGHT_SAME * (ms or Fraction(0)) + DOW_WEIGHT_OTHER * (mo or Fraction(0)))
    return projected, weighted

def active_holds_total(account_id):
    return sum(h["amount_cents"] for h in DB.holds.values()
               if h["account_id"] == account_id and h["status"] == "ACTIVE")

def create_approval(branch_id, action_type, subject_type, subject_id, requested_by, decided_by, status):
    a = {
        "id": new_id(), "created_at": iso(DB.tick()),
        "branch_id": branch_id,
        "action_type": action_type,
        "subject_type": subject_type,
        "subject_id": subject_id,
        "requested_by_user_id": requested_by,
        "approved_by_user_id": decided_by,
        "status": status,
    }
    DB.approvals[a["id"]] = a
    return a

def create_over_short_case(branch, drawer, variance, bdate):
    case = {
        **common_new(),
        "branch_id": branch["id"],
        "drawer_id": drawer["id"],
        "business_date": bdate,
        "variance_cents": variance,
        "status": "OPEN",
    }
    DB.over_short_cases[case["id"]] = case
    # Severity: |variance| >= 2x threshold auto-suspends the drawer's teller
    if abs(variance) >= OVER_SHORT_WAIVE_FACTOR * branch["over_short_investigation_threshold_cents"]:
        teller = DB.tellers.get(drawer["teller_id"])
        if teller is not None and teller["status"] == "ACTIVE":
            teller["status"] = "SUSPENDED"
            touch(teller)
    return case

# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------
@app.route("/api/_clock/set_current_utc", methods=["POST"])
def set_clock():
    uid, role = auth()
    body = payload_json()
    need_fields(body, ["to_iso8601"])
    target = parse_iso(body["to_iso8601"])
    if target < DB.now:
        fail("ERR_CLOCK_REGRESSION", "the logical clock never moves backward")
    old_date = DB.now.date()
    DB.now = target
    new_date = DB.now.date()
    if new_date > old_date:
        # Expire PENDING teller requests created on an earlier date
        for r in DB.teller_requests.values():
            if r["status"] == "PENDING" and date.fromisoformat(r["_created_date"]) < new_date:
                r["status"] = "EXPIRED"
                touch(r)
        # Release holds whose release day has been reached
        for h in DB.holds.values():
            if h["status"] in ("ACTIVE", "WAIVED") and date.fromisoformat(h["_release_date"]) <= new_date:
                h["status"] = "RELEASED"
                acct = DB.accounts.get(h["account_id"])
                if acct is not None:
                    acct["balance_cents"] += h["amount_cents"]
                    touch(acct)
    return envelope_success({"current_utc": iso(DB.now)})

# ---------------------------------------------------------------------------
# Branches
# ---------------------------------------------------------------------------
def branch_view(b):
    return b

@app.route("/api/branches", methods=["POST"])
def create_branch():
    uid, role = auth()
    require_role(role, {"BranchManager"})
    body = payload_json()
    need_fields(body, ["name", "drawer_limit_cents", "vault_cash_cents",
                       "over_short_investigation_threshold_cents"])
    for f in ("drawer_limit_cents", "vault_cash_cents", "over_short_investigation_threshold_cents"):
        v = body[f]
        if not isinstance(v, int) or isinstance(v, bool) or v < 0:
            fail("ERR_INVALID_REQUEST", f"{f} must be a non-negative integer")
    if not isinstance(body["name"], str) or not body["name"]:
        fail("ERR_INVALID_REQUEST", "name must be a non-empty string")
    b = {
        **common_new(),
        "name": body["name"],
        "drawer_limit_cents": body["drawer_limit_cents"],
        "vault_cash_cents": body["vault_cash_cents"],
        "over_short_investigation_threshold_cents": body["over_short_investigation_threshold_cents"],
        "status": "OPEN",
    }
    DB.branches[b["id"]] = b
    return envelope_success(b, 201)

@app.route("/api/branches", methods=["GET"])
def list_branches():
    uid, role = auth()
    items = sorted(DB.branches.values(), key=lambda x: (x["created_at"], x["id"]))
    page, meta = paginate(items, request.args)
    return envelope_success(page, 200, meta)

@app.route("/api/branches/<branchId>", methods=["GET"])
def get_branch(branchId):
    uid, role = auth()
    return envelope_success(get_path(DB.branches, branchId))

# ---------------------------------------------------------------------------
# Tellers
# ---------------------------------------------------------------------------
@app.route("/api/branches/<branchId>/tellers", methods=["POST"])
def create_teller(branchId):
    uid, role = auth()
    require_role(role, {"BranchManager"})
    branch = get_path(DB.branches, branchId)
    body = payload_json()
    need_fields(body, ["display_name"])
    t = {
        **common_new(),
        "branch_id": branch["id"],
        "display_name": body["display_name"],
        "status": "ACTIVE",
    }
    DB.tellers[t["id"]] = t
    return envelope_success(t, 201)

@app.route("/api/tellers", methods=["GET"])
def list_tellers():
    uid, role = auth()
    items = sorted(DB.tellers.values(), key=lambda x: (x["created_at"], x["id"]))
    if "branch_id" in request.args:
        items = [t for t in items if t["branch_id"] == request.args["branch_id"]]
    page, meta = paginate(items, request.args)
    return envelope_success(page, 200, meta)

@app.route("/api/tellers/<tellerId>", methods=["GET"])
def get_teller(tellerId):
    uid, role = auth()
    return envelope_success(get_path(DB.tellers, tellerId))

@app.route("/api/tellers/<tellerId>/suspend", methods=["POST"])
def suspend_teller(tellerId):
    uid, role = auth()
    require_role(role, {"BranchManager"})
    t = get_path(DB.tellers, tellerId)
    if t["status"] != "ACTIVE":
        fail("ERR_INVALID_STATE", "only an ACTIVE teller can be suspended")
    t["status"] = "SUSPENDED"
    touch(t)
    return envelope_success(t)

@app.route("/api/tellers/<tellerId>/reinstate", methods=["POST"])
def reinstate_teller(tellerId):
    uid, role = auth()
    require_role(role, {"BranchManager"})
    t = get_path(DB.tellers, tellerId)
    if t["status"] != "SUSPENDED":
        fail("ERR_INVALID_STATE", "only a SUSPENDED teller can be reinstated")
    t["status"] = "ACTIVE"
    touch(t)
    return envelope_success(t)

# ---------------------------------------------------------------------------
# Accounts
# ---------------------------------------------------------------------------
@app.route("/api/branches/<branchId>/accounts", methods=["POST"])
def create_account(branchId):
    uid, role = auth()
    require_role(role, {"BranchManager", "HeadTeller"})
    branch = get_path(DB.branches, branchId)
    body = payload_json()
    need_fields(body, ["owner_name", "balance_cents"])
    v = body["balance_cents"]
    if not isinstance(v, int) or isinstance(v, bool):
        fail("ERR_INVALID_REQUEST", "balance_cents must be an integer")
    a = {
        **common_new(),
        "branch_id": branch["id"],
        "owner_name": body["owner_name"],
        "balance_cents": v,
        "status": "OPEN",
    }
    DB.accounts[a["id"]] = a
    return envelope_success(a, 201)

@app.route("/api/accounts", methods=["GET"])
def list_accounts():
    uid, role = auth()
    items = sorted(DB.accounts.values(), key=lambda x: (x["created_at"], x["id"]))
    if "branch_id" in request.args:
        items = [a for a in items if a["branch_id"] == request.args["branch_id"]]
    page, meta = paginate(items, request.args)
    return envelope_success(page, 200, meta)

@app.route("/api/accounts/<accountId>", methods=["GET"])
def get_account(accountId):
    uid, role = auth()
    return envelope_success(get_path(DB.accounts, accountId))

@app.route("/api/accounts/<accountId>/close", methods=["POST"])
def close_account(accountId):
    uid, role = auth()
    require_role(role, {"BranchManager"})
    a = get_path(DB.accounts, accountId)
    if a["status"] != "OPEN":
        fail("ERR_INVALID_STATE", "only an OPEN account can be closed")
    if a["balance_cents"] != 0 or active_holds_total(a["id"]) > 0:
        fail("ERR_ACCOUNT_NOT_SETTLED", "balance must be zero and no hold ACTIVE")
    a["status"] = "CLOSED"
    touch(a)
    return envelope_success(a)

# ---------------------------------------------------------------------------
# Drawers
# ---------------------------------------------------------------------------
def drawer_view(d):
    d["expected_cash_cents"] = expected_cash(d, "STRICT")
    return d

@app.route("/api/tellers/<tellerId>/drawers", methods=["POST"])
def open_drawer(tellerId):
    uid, role = auth()
    require_role(role, {"HeadTeller", "BranchManager"})
    t = get_path(DB.tellers, tellerId)
    branch = DB.branches.get(t["branch_id"])
    if branch is None:
        fail("ERR_NOT_FOUND", "teller's branch not found")
    if branch["status"] == "AUDIT_FROZEN":
        fail("ERR_BRANCH_FROZEN", "branch is frozen for audit")
    if t["status"] != "ACTIVE":
        fail("ERR_TELLER_SUSPENDED", "suspended teller cannot open a drawer")
    today = business_date()
    for d in DB.drawers.values():
        if d["teller_id"] == t["id"] and d["status"] != "CLOSED":
            fail("ERR_DRAWER_ALREADY_OPEN", "teller already has an unclosed drawer")
        if d["teller_id"] == t["id"] and d["business_date"] == today:
            fail("ERR_DRAWER_ALREADY_OPEN", "teller already had a drawer session today")
    prior = [d for d in DB.drawers.values()
             if d["teller_id"] == t["id"] and d["status"] == "CLOSED"]
    prior.sort(key=lambda x: (x["created_at"], x["id"]))
    carry = prior[-1]["counted_cash_cents"] if prior else 0
    d = {
        **common_new(),
        "teller_id": t["id"],
        "branch_id": t["branch_id"],
        "cash_balance_cents": carry,
        "_baseline_cash_cents": carry,     # internal: expected-cash baseline
        "_buy_sell_net_cents": 0,          # internal: buys minus sells today
        "business_date": today,
        "status": "OPEN",
        "counted_cash_cents": None,
        "variance_cents": None,
        "last_close_variant": None,
    }
    DB.drawers[d["id"]] = d
    return envelope_success(drawer_view(d), 201)

@app.route("/api/drawers", methods=["GET"])
def list_drawers():
    uid, role = auth()
    items = sorted(DB.drawers.values(), key=lambda x: (x["created_at"], x["id"]))
    if "teller_id" in request.args:
        items = [d for d in items if d["teller_id"] == request.args["teller_id"]]
    if "branch_id" in request.args:
        items = [d for d in items if d["branch_id"] == request.args["branch_id"]]
    page, meta = paginate([drawer_view(dict(d)) for d in items], request.args)
    return envelope_success(page, 200, meta)

@app.route("/api/drawers/<drawerId>", methods=["GET"])
def get_drawer(drawerId):
    uid, role = auth()
    return envelope_success(drawer_view(get_path(DB.drawers, drawerId)))

@app.route("/api/drawers/<drawerId>/expected-cash", methods=["GET"])
def drawer_expected_cash(drawerId):
    uid, role = auth()
    d = get_path(DB.drawers, drawerId)
    variant = request.args.get("variant", "STRICT")
    if variant not in ("STRICT", "LENIENT"):
        fail("ERR_INVALID_REQUEST", "variant must be STRICT or LENIENT")
    return envelope_success({
        "expected_cash_cents": expected_cash(d, variant),
        "variant": variant,
    })

def own_open_drawer(d, uid):
    """Ownership + teller checks shared by transactions/buy/sell/count."""
    if uid != d["teller_id"]:
        fail("ERR_FORBIDDEN", "teller may only operate their own drawer")

def buy_sell_common(drawerId, direction):
    uid, role = auth()
    require_role(role, {"Teller"})
    d = get_path(DB.drawers, drawerId)
    branch = DB.branches[d["branch_id"]]
    if d["status"] != "OPEN":
        fail("ERR_INVALID_STATE", "drawer must be OPEN")
    if branch["status"] == "AUDIT_FROZEN":
        fail("ERR_BRANCH_FROZEN", "branch is frozen for audit")
    own_open_drawer(d, uid)
    body = payload_json()
    need_fields(body, ["amount_cents"])
    need_positive_int(body, "amount_cents")
    amt = body["amount_cents"]
    limit = branch["drawer_limit_cents"]
    if direction == "buy":
        if branch["vault_cash_cents"] < amt:
            fail("ERR_INSUFFICIENT_VAULT_CASH", "vault does not hold enough cash")
        if d["cash_balance_cents"] + amt >= limit:
            fail("ERR_DRAWER_LIMIT", "buy would leave drawer at or above the limit")
        branch["vault_cash_cents"] -= amt
        d["cash_balance_cents"] += amt
        d["_buy_sell_net_cents"] += amt
    else:
        if d["cash_balance_cents"] < amt:
            fail("ERR_INSUFFICIENT_DRAWER_CASH", "drawer does not hold enough cash")
        if d["cash_balance_cents"] < limit:
            fail("ERR_DRAWER_LIMIT", "no excess to sell: drawer is below the limit")
        if d["cash_balance_cents"] - amt >= limit:
            fail("ERR_DRAWER_LIMIT", "sell must bring the drawer strictly below the limit")
        d["cash_balance_cents"] -= amt
        d["_buy_sell_net_cents"] -= amt
        branch["vault_cash_cents"] += amt
    touch(branch)
    touch(d)
    return envelope_success(drawer_view(d))

@app.route("/api/drawers/<drawerId>/buy-from-vault", methods=["POST"])
def buy_from_vault(drawerId):
    return buy_sell_common(drawerId, "buy")

@app.route("/api/drawers/<drawerId>/sell-to-vault", methods=["POST"])
def sell_to_vault(drawerId):
    return buy_sell_common(drawerId, "sell")

@app.route("/api/drawers/<drawerId>/count", methods=["POST"])
def count_drawer(drawerId):
    uid, role = auth()
    require_role(role, {"Teller"})
    d = get_path(DB.drawers, drawerId)
    if d["status"] != "OPEN":
        fail("ERR_INVALID_STATE", "only an OPEN drawer can be counted")
    own_open_drawer(d, uid)
    body = payload_json()
    need_fields(body, ["counted_cash_cents"])
    v = body["counted_cash_cents"]
    if not isinstance(v, int) or isinstance(v, bool) or v < 0:
        fail("ERR_INVALID_REQUEST", "counted_cash_cents must be a non-negative integer")
    d["counted_cash_cents"] = v
    d["status"] = "COUNTING"
    touch(d)
    return envelope_success(drawer_view(d))

@app.route("/api/drawers/<drawerId>/attest", methods=["POST"])
def attest_drawer(drawerId):
    uid, role = auth()
    require_role(role, {"BranchManager", "Auditor"})
    d = get_path(DB.drawers, drawerId)
    if d["status"] != "COUNTING":
        fail("ERR_INVALID_STATE", "only a COUNTING drawer can be attested")
    if uid == d["teller_id"]:
        fail("ERR_DUAL_CONTROL_VIOLATION", "attestor must differ from the counting teller")
    branch = DB.branches[d["branch_id"]]
    exp = expected_cash(d, "STRICT")
    variance = d["counted_cash_cents"] - exp
    d["variance_cents"] = variance
    d["cash_balance_cents"] = d["counted_cash_cents"]
    d["last_close_variant"] = "STRICT"
    d["status"] = "BALANCED" if variance == 0 else "OUT_OF_BALANCE"
    touch(d)
    if abs(variance) >= branch["over_short_investigation_threshold_cents"]:
        create_over_short_case(branch, d, variance, d["business_date"])
    return envelope_success(drawer_view(d))

@app.route("/api/drawers/<drawerId>/close", methods=["POST"])
def close_drawer(drawerId):
    uid, role = auth()
    require_role(role, {"BranchManager"})
    d = get_path(DB.drawers, drawerId)
    if d["status"] not in ("BALANCED", "OUT_OF_BALANCE"):
        fail("ERR_INVALID_STATE", "only a BALANCED or OUT_OF_BALANCE drawer can be closed")
    if d["status"] == "OUT_OF_BALANCE":
        for c in DB.over_short_cases.values():
            if c["drawer_id"] == d["id"] and c["business_date"] == d["business_date"] \
                    and c["status"] not in ("RESOLVED", "WAIVED"):
                fail("ERR_OVER_SHORT_UNRESOLVED", "the over/short case must be RESOLVED or WAIVED first")
    body = payload_json()
    need_fields(body, ["expected_drawer_version"])
    ev = body["expected_drawer_version"]
    if not isinstance(ev, int) or isinstance(ev, bool):
        fail("ERR_INVALID_REQUEST", "expected_drawer_version must be an integer")
    if ev != d["version"]:
        fail("ERR_STALE_VERSION", "drawer version mismatch")
    d["status"] = "CLOSED"
    touch(d)
    return envelope_success(drawer_view(d))

# ---------------------------------------------------------------------------
# Transactions
# ---------------------------------------------------------------------------
def post_transaction(drawer, account, ttype, amount, is_ctr_exempt, skip_limit=False):
    """Shared posting path for direct window transactions and approved requests.

    Caller has already run auth/role/existence/state/frozen checks.
    Returns the created transaction (status POSTED).
    """
    branch = DB.branches[drawer["branch_id"]]
    if ttype in INSTRUMENT_TXN_TYPES and not skip_limit:
        fail("ERR_INSTRUMENT_REQUIRES_APPROVAL",
             "instruments are issued only via an approved teller request")
    if ttype == "CASH_WITHDRAWAL":
        if drawer["cash_balance_cents"] < amount:
            fail("ERR_INSUFFICIENT_DRAWER_CASH", "drawer does not hold enough cash")
        if account["balance_cents"] - active_holds_total(account["id"]) < amount:
            fail("ERR_INSUFFICIENT_FUNDS", "account available funds are insufficient")
        if not skip_limit and amount > TELLER_TRANSACTION_LIMIT_CENTS:
            fail("ERR_TRANSACTION_OVER_LIMIT", "amount exceeds the teller transaction limit")

    fee = 0
    if ttype in INSTRUMENT_TXN_TYPES:
        fee = 0  # fee set by the request-execution path
    t = {
        **common_new(),
        "drawer_id": drawer["id"],
        "account_id": account["id"],
        "branch_id": drawer["branch_id"],
        "type": ttype,
        "amount_cents": amount,
        "fee_waived": False,
        "is_ctr_exempt": bool(is_ctr_exempt),
        "fee_cents": fee,
        "status": "POSTED",
        "voided_by_user_id": None,
        "_business_date": business_date(),
    }
    DB.transactions[t["id"]] = t

    # Ledger + drawer effects
    if ttype == "CASH_DEPOSIT":
        account["balance_cents"] += amount
        drawer["cash_balance_cents"] += amount
    elif ttype == "CASH_WITHDRAWAL":
        account["balance_cents"] -= amount
        drawer["cash_balance_cents"] -= amount
    elif ttype == "CHECK_DEPOSIT":
        immediate = min(amount, NEXT_DAY_AVAILABILITY_CENTS)
        account["balance_cents"] += immediate
        hold_amount = amount - immediate
        hold_type = "STANDARD" if amount <= LARGE_CHECK_FACE_CENTS else "LARGE_CHECK"
        offset = STANDARD_HOLD_DAYS if hold_type == "STANDARD" else LARGE_CHECK_HOLD_DAYS
        rel = add_business_days(date.fromisoformat(t["_business_date"]), offset)
        h = {
            **common_new(),
            "account_id": account["id"],
            "branch_id": account["branch_id"],
            "transaction_id": t["id"],
            "amount_cents": hold_amount,
            "hold_type": hold_type,
            "release_day_offset": offset,
            "_release_date": rel.isoformat(),
            "status": "ACTIVE",
        }
        DB.holds[h["id"]] = h
    touch(account)
    touch(drawer)
    ctr_reevaluate(account["id"], drawer["branch_id"], t["_business_date"])
    return t

@app.route("/api/drawers/<drawerId>/transactions", methods=["POST"])
def create_transaction(drawerId):
    uid, role = auth()
    require_role(role, {"Teller"})
    d = get_path(DB.drawers, drawerId)
    body = payload_json()
    acct = None
    if body.get("account_id") is not None:
        acct = DB.accounts.get(body["account_id"])
        if acct is None:
            fail("ERR_NOT_FOUND", "account not found")
    if d["status"] != "OPEN":
        fail("ERR_INVALID_STATE", "drawer must be OPEN")
    if acct is not None and acct["status"] != "OPEN":
        fail("ERR_ACCOUNT_CLOSED", "account is closed")
    branch = DB.branches[d["branch_id"]]
    if branch["status"] == "AUDIT_FROZEN":
        fail("ERR_BRANCH_FROZEN", "branch is frozen for audit")
    teller = DB.tellers[d["teller_id"]]
    if teller["status"] != "ACTIVE":
        fail("ERR_TELLER_SUSPENDED", "suspended teller cannot post")
    own_open_drawer(d, uid)
    need_fields(body, ["account_id", "type", "amount_cents"])
    if body["type"] not in TXN_TYPES:
        fail("ERR_INVALID_REQUEST", "invalid transaction type")
    need_positive_int(body, "amount_cents")
    if acct["branch_id"] != d["branch_id"]:
        fail("ERR_CROSS_BRANCH", "account and drawer belong to different branches")
    t = post_transaction(d, acct, body["type"], body["amount_cents"],
                         body.get("is_ctr_exempt", False))
    return envelope_success(t, 201)

@app.route("/api/transactions", methods=["GET"])
def list_transactions():
    uid, role = auth()
    items = sorted(DB.transactions.values(), key=lambda x: (x["created_at"], x["id"]))
    for f in ("drawer_id", "account_id", "branch_id"):
        if f in request.args:
            items = [t for t in items if t[f] == request.args[f]]
    page, meta = paginate(items, request.args)
    return envelope_success(page, 200, meta)

@app.route("/api/transactions/<transactionId>", methods=["GET"])
def get_transaction(transactionId):
    uid, role = auth()
    return envelope_success(get_path(DB.transactions, transactionId))

@app.route("/api/transactions/<transactionId>/void", methods=["POST"])
def void_transaction(transactionId):
    uid, role = auth()
    require_role(role, {"BranchManager"})
    t = get_path(DB.transactions, transactionId)
    d = DB.drawers.get(t["drawer_id"])
    if t["status"] != "POSTED":
        fail("ERR_INVALID_STATE", "only a POSTED transaction can be voided")
    if d is None or d["status"] != "OPEN":
        fail("ERR_INVALID_STATE", "voids are same-day corrections; the drawer must be OPEN")
    if t["type"] == "CHECK_DEPOSIT":
        hold = next((h for h in DB.holds.values() if h["transaction_id"] == t["id"]), None)
        if hold is not None and hold["status"] != "ACTIVE":
            fail("ERR_HOLD_ALREADY_RELEASED", "the hold has already released")
    if uid == d["teller_id"]:
        fail("ERR_SOD_VIOLATION", "voiding manager must differ from the posting teller")

    account = DB.accounts.get(t["account_id"])
    amt = t["amount_cents"]
    if t["type"] == "CASH_DEPOSIT":
        account["balance_cents"] -= amt
        d["cash_balance_cents"] -= amt
    elif t["type"] == "CASH_WITHDRAWAL":
        account["balance_cents"] += amt
        d["cash_balance_cents"] += amt
    elif t["type"] == "CHECK_DEPOSIT":
        immediate = min(amt, NEXT_DAY_AVAILABILITY_CENTS)
        account["balance_cents"] -= immediate
        hold = next((h for h in DB.holds.values() if h["transaction_id"] == t["id"]), None)
        if hold is not None:
            hold["status"] = "RELEASED"  # void path: held amount is never credited
            touch(hold)
    else:  # instrument purchases: cash-in of face + fee
        d["cash_balance_cents"] -= (amt + t["fee_cents"])
    t["status"] = "VOIDED"
    t["voided_by_user_id"] = uid
    touch(t)
    touch(account)
    touch(d)
    ctr_reevaluate(account["id"], t["branch_id"], t["_business_date"])
    return envelope_success(t)

# ---------------------------------------------------------------------------
# Cash orders
# ---------------------------------------------------------------------------
@app.route("/api/branches/<branchId>/cash-orders", methods=["POST"])
def create_cash_order(branchId):
    uid, role = auth()
    require_role(role, {"Teller", "HeadTeller"})
    branch = get_path(DB.branches, branchId)
    if branch["status"] == "AUDIT_FROZEN":
        fail("ERR_BRANCH_FROZEN", "branch is frozen for audit")
    body = payload_json()
    need_fields(body, ["delivery_date", "expected_branch_version"])
    requested = body.get("requested_amount_cents")
    if requested is not None:
        if not isinstance(requested, int) or isinstance(requested, bool) or requested <= 0:
            fail("ERR_INVALID_REQUEST", "requested_amount_cents must be a positive integer")
    today = business_date()
    for o in DB.cash_orders.values():
        if o["branch_id"] == branch["id"] and o["delivery_date"] == body["delivery_date"] \
                and o["status"] in ("PENDING", "APPROVED"):
            fail("ERR_DUPLICATE_CASH_ORDER", "an open order already exists for that delivery date")
    dd = parse_date(body["delivery_date"])
    if dd is None or not is_weekday(dd) or dd.isoformat() <= today:
        fail("ERR_INVALID_DELIVERY_DATE",
             "delivery_date must be a weekday strictly later than the order date")
    # forecast (TRAILING official, WEIGHTED comparison)
    projected, _weighted = forecast(branch, body["delivery_date"], today)
    suggested = max(projected - branch["vault_cash_cents"], 0)
    # pinned order: step-floor raw, then step-floor headroom, then min
    raw = requested if requested is not None else suggested
    stepped = (raw // ORDER_STEP_CENTS) * ORDER_STEP_CENTS
    headroom = max(VAULT_CAPACITY_CENTS - branch["vault_cash_cents"], 0)
    capacity_stepped = (headroom // ORDER_STEP_CENTS) * ORDER_STEP_CENTS
    ordered = min(stepped, capacity_stepped)
    if ordered <= 0:
        fail("ERR_ORDER_BELOW_MINIMUM", "order quantity is zero after rounding and clamp")
    ev = body["expected_branch_version"]
    if not isinstance(ev, int) or isinstance(ev, bool):
        fail("ERR_INVALID_REQUEST", "expected_branch_version must be an integer")
    if ev != branch["version"]:
        fail("ERR_STALE_VERSION", "branch version mismatch")
    o = {
        **common_new(),
        "branch_id": branch["id"],
        "order_date": today,
        "created_by_user_id": uid,
        "delivery_date": body["delivery_date"],
        "projected_need_cents": projected,
        "suggested_order_cents": suggested,
        "ordered_amount_cents": ordered,
        "status": "PENDING",
        "decided_by_user_id": None,
    }
    DB.cash_orders[o["id"]] = o
    touch(branch)  # placing an order advances the branch version (OCC)
    return envelope_success(o, 201)

@app.route("/api/cash-orders", methods=["GET"])
def list_cash_orders():
    uid, role = auth()
    items = sorted(DB.cash_orders.values(), key=lambda x: (x["created_at"], x["id"]))
    if "branch_id" in request.args:
        items = [o for o in items if o["branch_id"] == request.args["branch_id"]]
    page, meta = paginate(items, request.args)
    return envelope_success(page, 200, meta)

@app.route("/api/cash-orders/<orderId>", methods=["GET"])
def get_cash_order(orderId):
    uid, role = auth()
    return envelope_success(get_path(DB.cash_orders, orderId))

@app.route("/api/branches/<branchId>/cash-forecast", methods=["GET"])
def cash_forecast(branchId):
    uid, role = auth()
    require_role(role, {"BranchManager", "HeadTeller", "Teller"})
    branch = get_path(DB.branches, branchId)
    dd_raw = request.args.get("delivery_date")
    if dd_raw is None:
        fail("ERR_INVALID_REQUEST", "delivery_date is required")
    dd = parse_date(dd_raw)
    if dd is None:
        fail("ERR_INVALID_REQUEST", "delivery_date must be an ISO date")
    projected, weighted = forecast(branch, dd_raw, business_date())
    suggested = max(projected - branch["vault_cash_cents"], 0)
    return envelope_success({
        "projected_need_cents": projected,
        "weighted_need_cents": weighted,
        "suggested_order_cents": suggested,
    })

def order_decision(orderId, target):
    uid, role = auth()
    require_role(role, {"BranchManager"})
    o = get_path(DB.cash_orders, orderId)
    if o["status"] != "PENDING":
        fail("ERR_INVALID_STATE", "only a PENDING order can be decided")
    if uid == o["created_by_user_id"]:
        fail("ERR_SOD_VIOLATION", "the ordering operator cannot decide their own order")
    o["status"] = target
    o["decided_by_user_id"] = uid
    touch(o)
    return envelope_success(o)

@app.route("/api/cash-orders/<orderId>/approve", methods=["POST"])
def approve_cash_order(orderId):
    return order_decision(orderId, "APPROVED")

@app.route("/api/cash-orders/<orderId>/reject", methods=["POST"])
def reject_cash_order(orderId):
    return order_decision(orderId, "REJECTED")

@app.route("/api/cash-orders/<orderId>/deliver", methods=["POST"])
def deliver_cash_order(orderId):
    uid, role = auth()
    require_role(role, {"HeadTeller"})
    o = get_path(DB.cash_orders, orderId)
    if o["status"] != "APPROVED":
        fail("ERR_INVALID_STATE", "only an APPROVED order can be delivered")
    branch = DB.branches[o["branch_id"]]
    if branch["status"] == "AUDIT_FROZEN":
        fail("ERR_BRANCH_FROZEN", "branch is frozen for audit")
    if business_date() != o["delivery_date"]:
        fail("ERR_ORDER_NOT_DUE", "the logical date must equal the delivery date")
    if branch["vault_cash_cents"] + o["ordered_amount_cents"] > VAULT_CAPACITY_CENTS:
        fail("ERR_VAULT_CAPACITY_EXCEEDED", "delivery would exceed vault capacity")
    branch["vault_cash_cents"] += o["ordered_amount_cents"]
    touch(branch)
    o["status"] = "DELIVERED"
    touch(o)
    return envelope_success(o)

@app.route("/api/cash-orders/<orderId>/cancel", methods=["POST"])
def cancel_cash_order(orderId):
    uid, role = auth()
    require_role(role, {"BranchManager"})
    o = get_path(DB.cash_orders, orderId)
    if o["status"] != "APPROVED":
        fail("ERR_INVALID_STATE", "only an APPROVED order can be cancelled")
    o["status"] = "CANCELLED"
    touch(o)
    return envelope_success(o)

# ---------------------------------------------------------------------------
# Teller requests (dual-control workflow)
# ---------------------------------------------------------------------------
def create_request(drawerId):
    uid, role = auth()
    require_role(role, {"Teller"})
    d = get_path(DB.drawers, drawerId)
    body = payload_json()
    params = body.get("params")
    acct = None
    if isinstance(params, dict) and params.get("account_id") is not None:
        acct = DB.accounts.get(params["account_id"])
        if acct is None:
            fail("ERR_NOT_FOUND", "account not found")
    if d["status"] != "OPEN":
        fail("ERR_INVALID_STATE", "drawer must be OPEN")
    if acct is not None and acct["status"] != "OPEN":
        fail("ERR_ACCOUNT_CLOSED", "account is closed")
    branch = DB.branches[d["branch_id"]]
    if branch["status"] == "AUDIT_FROZEN":
        fail("ERR_BRANCH_FROZEN", "branch is frozen for audit")
    teller = DB.tellers[d["teller_id"]]
    if teller["status"] != "ACTIVE":
        fail("ERR_TELLER_SUSPENDED", "suspended teller cannot create requests")
    own_open_drawer(d, uid)
    need_fields(body, ["type", "params"])
    if body["type"] not in REQUEST_TYPES:
        fail("ERR_INVALID_REQUEST", "invalid request type")
    if not isinstance(params, dict):
        fail("ERR_INVALID_REQUEST", "params must be an object")
    rtype = body["type"]
    if rtype in ("ISSUE_INSTRUMENT", "OVER_LIMIT_TRANSACTION"):
        need_fields(params, ["account_id", "amount_cents"])
        if acct is None:
            fail("ERR_NOT_FOUND", "account not found")
        if not isinstance(params["amount_cents"], int) or isinstance(params["amount_cents"], bool) \
                or params["amount_cents"] <= 0:
            fail("ERR_INVALID_REQUEST", "params.amount_cents must be a positive integer")
    if rtype == "ISSUE_INSTRUMENT":
        it = params.get("instrument_type")
        if it not in ("CASHIERS_CHECK", "MONEY_ORDER"):
            fail("ERR_INVALID_REQUEST", "instrument_type must be CASHIERS_CHECK or MONEY_ORDER")
    if rtype == "FEE_WAIVER":
        need_fields(params, ["transaction_id"])
        tx = DB.transactions.get(params["transaction_id"])
        if tx is None or tx["status"] != "POSTED" or tx["type"] not in INSTRUMENT_TXN_TYPES \
                or tx["branch_id"] != d["branch_id"]:
            fail("ERR_TRANSACTION_NOT_FOUND",
                 "fee waiver subject must be a POSTED instrument purchase on this branch")
    if acct is not None and acct["branch_id"] != d["branch_id"]:
        fail("ERR_CROSS_BRANCH", "account and drawer belong to different branches")
    if rtype == "ISSUE_INSTRUMENT" and params.get("instrument_type") == "MONEY_ORDER" \
            and params["amount_cents"] > MONEY_ORDER_MAX_CENTS:
        fail("ERR_INSTRUMENT_LIMIT", "money order face exceeds the 100000-cent cap")
    r = {
        **common_new(),
        "branch_id": d["branch_id"],
        "teller_id": d["teller_id"],
        "drawer_id": d["id"],
        "requested_by_user_id": uid,
        "type": rtype,
        "params": params,
        "status": "PENDING",
        "_created_date": business_date(),
    }
    DB.teller_requests[r["id"]] = r
    return envelope_success(r, 201)

@app.route("/api/drawers/<drawerId>/teller-requests", methods=["POST"])
def create_teller_request(drawerId):
    return create_request(drawerId)

@app.route("/api/teller-requests", methods=["GET"])
def list_teller_requests():
    uid, role = auth()
    items = sorted(DB.teller_requests.values(), key=lambda x: (x["created_at"], x["id"]))
    for f in ("branch_id", "teller_id", "drawer_id"):
        if f in request.args:
            items = [r for r in items if r[f] == request.args[f]]
    page, meta = paginate(items, request.args)
    return envelope_success(page, 200, meta)

@app.route("/api/teller-requests/<requestId>", methods=["GET"])
def get_teller_request(requestId):
    uid, role = auth()
    return envelope_success(get_path(DB.teller_requests, requestId))

def execute_request(r):
    """Perform the approved action atomically. Caller checked state + SoD."""
    d = DB.drawers[r["drawer_id"]]
    branch = DB.branches[r["branch_id"]]
    if branch["status"] == "AUDIT_FROZEN":
        fail("ERR_BRANCH_FROZEN", "branch is frozen for audit")
    if d["status"] != "OPEN":
        fail("ERR_INVALID_STATE", "the request's drawer must be OPEN at execution")
    params = r["params"]
    if r["type"] == "ISSUE_INSTRUMENT":
        acct = DB.accounts.get(params["account_id"])
        if acct is None or acct["branch_id"] != d["branch_id"]:
            fail("ERR_CROSS_BRANCH", "account and drawer belong to different branches")
        if acct["status"] != "OPEN":
            fail("ERR_ACCOUNT_CLOSED", "account is closed")
        if params["instrument_type"] == "MONEY_ORDER" and \
                params["amount_cents"] > MONEY_ORDER_MAX_CENTS:
            fail("ERR_INSTRUMENT_LIMIT", "money order face exceeds the 100000-cent cap")
        waived = bool(params.get("fee_waived", False))
        fee = 0 if waived else (CASHIERS_CHECK_FEE_CENTS
                                if params["instrument_type"] == "CASHIERS_CHECK"
                                else MONEY_ORDER_FEE_CENTS)
        ttype = "CASHIERS_CHECK_PURCHASE" if params["instrument_type"] == "CASHIERS_CHECK" \
            else "MONEY_ORDER_PURCHASE"
        t = post_transaction(d, acct, ttype, params["amount_cents"],
                             params.get("is_ctr_exempt", False), skip_limit=True)
        t["fee_cents"] = fee
        t["fee_waived"] = waived
        # the customer pays face + fee in cash; both land in the drawer
        d["cash_balance_cents"] += params["amount_cents"] + fee
        touch(t)
        touch(d)
        ctr_reevaluate(acct["id"], d["branch_id"], t["_business_date"])
    elif r["type"] == "FEE_WAIVER":
        tx = DB.transactions.get(params["transaction_id"])
        if tx is None or tx["status"] != "POSTED" or tx["type"] not in INSTRUMENT_TXN_TYPES \
                or tx["branch_id"] != r["branch_id"]:
            fail("ERR_TRANSACTION_NOT_FOUND", "fee waiver subject is not refundable")
        acct = DB.accounts[tx["account_id"]]
        acct["balance_cents"] += tx["fee_cents"]
        touch(acct)
    else:  # OVER_LIMIT_TRANSACTION
        acct = DB.accounts.get(params["account_id"])
        if acct is None or acct["branch_id"] != d["branch_id"]:
            fail("ERR_CROSS_BRANCH", "account and drawer belong to different branches")
        if acct["status"] != "OPEN":
            fail("ERR_ACCOUNT_CLOSED", "account is closed")
        post_transaction(d, acct, "CASH_WITHDRAWAL", params["amount_cents"],
                         params.get("is_ctr_exempt", False), skip_limit=True)

@app.route("/api/teller-requests/<requestId>/approve", methods=["POST"])
def approve_teller_request(requestId):
    uid, role = auth()
    require_role(role, {"HeadTeller", "BranchManager"})
    r = get_path(DB.teller_requests, requestId)
    if r["status"] != "PENDING":
        fail("ERR_INVALID_STATE", "only a PENDING request can be approved")
    if uid == r["requested_by_user_id"]:
        fail("ERR_SOD_VIOLATION", "the requester cannot approve their own request")
    execute_request(r)
    r["status"] = "EXECUTED"
    touch(r)
    create_approval(r["branch_id"], "TELLER_REQUEST", "TellerRequest", r["id"],
                    r["requested_by_user_id"], uid, "APPROVED")
    return envelope_success(r)

@app.route("/api/teller-requests/<requestId>/reject", methods=["POST"])
def reject_teller_request(requestId):
    uid, role = auth()
    require_role(role, {"HeadTeller", "BranchManager"})
    r = get_path(DB.teller_requests, requestId)
    if r["status"] != "PENDING":
        fail("ERR_INVALID_STATE", "only a PENDING request can be rejected")
    if uid == r["requested_by_user_id"]:
        fail("ERR_SOD_VIOLATION", "the requester cannot reject their own request")
    r["status"] = "REJECTED"
    touch(r)
    create_approval(r["branch_id"], "TELLER_REQUEST", "TellerRequest", r["id"],
                    r["requested_by_user_id"], uid, "REJECTED")
    return envelope_success(r)

# ---------------------------------------------------------------------------
# Holds
# ---------------------------------------------------------------------------
@app.route("/api/holds", methods=["GET"])
def list_holds():
    uid, role = auth()
    items = sorted(DB.holds.values(), key=lambda x: (x["created_at"], x["id"]))
    for f in ("account_id", "branch_id", "transaction_id"):
        if f in request.args:
            items = [h for h in items if h[f] == request.args[f]]
    page, meta = paginate(items, request.args)
    return envelope_success(page, 200, meta)

@app.route("/api/holds/<holdId>", methods=["GET"])
def get_hold(holdId):
    uid, role = auth()
    return envelope_success(get_path(DB.holds, holdId))

@app.route("/api/holds/<holdId>/waive", methods=["POST"])
def waive_hold(holdId):
    uid, role = auth()
    require_role(role, {"BranchManager"})
    h = get_path(DB.holds, holdId)
    if h["status"] != "ACTIVE":
        fail("ERR_INVALID_STATE", "only an ACTIVE hold can be waived")
    h["status"] = "WAIVED"
    h["release_day_offset"] = WAIVED_HOLD_DAYS
    dep_date = date.fromisoformat(
        DB.transactions[h["transaction_id"]]["_business_date"])
    h["_release_date"] = add_business_days(dep_date, WAIVED_HOLD_DAYS).isoformat()
    touch(h)
    create_approval(h["branch_id"], "HOLD_WAIVER", "Hold", h["id"], None, uid, "APPROVED")
    return envelope_success(h)

# ---------------------------------------------------------------------------
# CTR filings (read-only)
# ---------------------------------------------------------------------------
@app.route("/api/ctr-filings", methods=["GET"])
def list_ctr_filings():
    uid, role = auth()
    require_role(role, {"BranchManager", "HeadTeller", "Auditor"})
    items = sorted(DB.ctr_filings.values(), key=lambda x: (x["created_at"], x["id"]))
    for f in ("branch_id", "account_id"):
        if f in request.args:
            items = [x for x in items if x[f] == request.args[f]]
    page, meta = paginate(items, request.args)
    return envelope_success(page, 200, meta)

@app.route("/api/ctr-filings/<filingId>", methods=["GET"])
def get_ctr_filing(filingId):
    uid, role = auth()
    require_role(role, {"BranchManager", "HeadTeller", "Auditor"})
    return envelope_success(get_path(DB.ctr_filings, filingId))

# ---------------------------------------------------------------------------
# Over/short cases
# ---------------------------------------------------------------------------
@app.route("/api/over-short-cases", methods=["GET"])
def list_over_short_cases():
    uid, role = auth()
    require_role(role, {"BranchManager", "Auditor"})
    items = sorted(DB.over_short_cases.values(), key=lambda x: (x["created_at"], x["id"]))
    for f in ("branch_id", "drawer_id"):
        if f in request.args:
            items = [x for x in items if x[f] == request.args[f]]
    page, meta = paginate(items, request.args)
    return envelope_success(page, 200, meta)

@app.route("/api/over-short-cases/<caseId>", methods=["GET"])
def get_over_short_case(caseId):
    uid, role = auth()
    require_role(role, {"BranchManager", "Auditor"})
    return envelope_success(get_path(DB.over_short_cases, caseId))

@app.route("/api/over-short-cases/<caseId>/investigate", methods=["POST"])
def investigate_case(caseId):
    uid, role = auth()
    require_role(role, {"BranchManager"})
    c = get_path(DB.over_short_cases, caseId)
    if c["status"] != "OPEN":
        fail("ERR_INVALID_STATE", "only an OPEN case can move to UNDER_INVESTIGATION")
    c["status"] = "UNDER_INVESTIGATION"
    touch(c)
    return envelope_success(c)

@app.route("/api/over-short-cases/<caseId>/resolve", methods=["POST"])
def resolve_case(caseId):
    uid, role = auth()
    require_role(role, {"BranchManager"})
    c = get_path(DB.over_short_cases, caseId)
    if c["status"] != "UNDER_INVESTIGATION":
        fail("ERR_INVALID_STATE", "only an UNDER_INVESTIGATION case can be resolved")
    c["status"] = "RESOLVED"
    touch(c)
    return envelope_success(c)

@app.route("/api/over-short-cases/<caseId>/waive", methods=["POST"])
def waive_case(caseId):
    uid, role = auth()
    require_role(role, {"BranchManager"})
    c = get_path(DB.over_short_cases, caseId)
    if c["status"] not in ("OPEN", "UNDER_INVESTIGATION"):
        fail("ERR_INVALID_STATE", "only an OPEN or UNDER_INVESTIGATION case can be waived")
    branch = DB.branches[c["branch_id"]]
    if abs(c["variance_cents"]) >= OVER_SHORT_WAIVE_FACTOR * branch["over_short_investigation_threshold_cents"]:
        fail("ERR_WAIVER_NOT_ALLOWED", "variance at or beyond twice the threshold cannot be waived")
    c["status"] = "WAIVED"
    touch(c)
    create_approval(c["branch_id"], "OVER_SHORT_WAIVER", "OverShortCase", c["id"],
                    None, uid, "APPROVED")
    return envelope_success(c)

# ---------------------------------------------------------------------------
# Approvals (read-only decision record)
# ---------------------------------------------------------------------------
@app.route("/api/approvals", methods=["GET"])
def list_approvals():
    uid, role = auth()
    require_role(role, {"BranchManager", "Auditor"})
    items = sorted(DB.approvals.values(), key=lambda x: (x["created_at"], x["id"]))
    if "branch_id" in request.args:
        items = [a for a in items if a["branch_id"] == request.args["branch_id"]]
    page, meta = paginate(items, request.args)
    return envelope_success(page, 200, meta)

@app.route("/api/approvals/<approvalId>", methods=["GET"])
def get_approval(approvalId):
    uid, role = auth()
    require_role(role, {"BranchManager", "Auditor"})
    return envelope_success(get_path(DB.approvals, approvalId))

# ---------------------------------------------------------------------------
# Audits
# ---------------------------------------------------------------------------
@app.route("/api/branches/<branchId>/audits", methods=["POST"])
def create_audit(branchId):
    uid, role = auth()
    require_role(role, {"Auditor"})
    branch = get_path(DB.branches, branchId)
    body = payload_json()
    need_fields(body, ["type"])
    for a in DB.audits.values():
        if a["branch_id"] == branch["id"] and a["status"] in ("PLANNED", "IN_PROGRESS"):
            fail("ERR_AUDIT_IN_PROGRESS", "an audit is already planned or in progress")
    atype = body["type"]
    today = business_date()
    if atype == "SCHEDULED":
        sd = body.get("scheduled_date")
        sd_parsed = parse_date(sd) if sd is not None else None
        if sd_parsed is None or not is_weekday(sd_parsed) or sd_parsed.isoformat() <= today:
            fail("ERR_INVALID_AUDIT_DATE",
                 "scheduled_date must be a weekday strictly later than today")
        status = "PLANNED"
        freeze = False
        scheduled = sd
    elif atype == "SURPRISE":
        if body.get("scheduled_date") is not None:
            fail("ERR_INVALID_AUDIT_DATE", "a SURPRISE audit takes no scheduled_date")
        status = "IN_PROGRESS"
        freeze = True
        scheduled = None
    else:
        fail("ERR_INVALID_REQUEST", "type must be SCHEDULED or SURPRISE")
    a = {
        **common_new(),
        "branch_id": branch["id"],
        "type": atype,
        "scheduled_date": scheduled,
        "status": status,
        "freeze_applied": freeze,
        "discrepancy_total_cents": None,
    }
    DB.audits[a["id"]] = a
    if freeze:
        branch["status"] = "AUDIT_FROZEN"
        touch(branch)
    return envelope_success(a, 201)

@app.route("/api/audits", methods=["GET"])
def list_audits():
    uid, role = auth()
    require_role(role, {"BranchManager", "Auditor"})
    items = sorted(DB.audits.values(), key=lambda x: (x["created_at"], x["id"]))
    if "branch_id" in request.args:
        items = [a for a in items if a["branch_id"] == request.args["branch_id"]]
    page, meta = paginate(items, request.args)
    return envelope_success(page, 200, meta)

@app.route("/api/audits/<auditId>", methods=["GET"])
def get_audit(auditId):
    uid, role = auth()
    require_role(role, {"BranchManager", "Auditor"})
    return envelope_success(get_path(DB.audits, auditId))

@app.route("/api/audits/<auditId>/begin", methods=["POST"])
def begin_audit(auditId):
    uid, role = auth()
    require_role(role, {"Auditor"})
    a = get_path(DB.audits, auditId)
    if a["status"] != "PLANNED":
        fail("ERR_INVALID_STATE", "only a PLANNED audit can begin")
    if business_date() != a["scheduled_date"]:
        fail("ERR_AUDIT_NOT_DUE", "the logical date must equal the scheduled date")
    branch = DB.branches[a["branch_id"]]
    a["status"] = "IN_PROGRESS"
    a["freeze_applied"] = True
    touch(a)
    branch["status"] = "AUDIT_FROZEN"
    touch(branch)
    return envelope_success(a)

@app.route("/api/audits/<auditId>/complete", methods=["POST"])
def complete_audit(auditId):
    uid, role = auth()
    require_role(role, {"Auditor"})
    a = get_path(DB.audits, auditId)
    if a["status"] != "IN_PROGRESS":
        fail("ERR_INVALID_STATE", "only an IN_PROGRESS audit can complete")
    body = payload_json()
    need_fields(body, ["vault_counted_cents", "drawer_counts"])
    vc = body["vault_counted_cents"]
    if not isinstance(vc, int) or isinstance(vc, bool) or vc < 0:
        fail("ERR_INVALID_REQUEST", "vault_counted_cents must be a non-negative integer")
    counts = body["drawer_counts"]
    if not isinstance(counts, list):
        fail("ERR_INVALID_REQUEST", "drawer_counts must be a list")
    branch = DB.branches[a["branch_id"]]
    open_drawers = [d for d in DB.drawers.values()
                    if d["branch_id"] == branch["id"] and d["status"] != "CLOSED"]
    seen = {}
    for entry in counts:
        if not isinstance(entry, dict) or "drawer_id" not in entry or "counted_cash_cents" not in entry:
            fail("ERR_INVALID_REQUEST", "each drawer count needs drawer_id and counted_cash_cents")
        did = entry["drawer_id"]
        d = DB.drawers.get(did)
        if d is None or d["branch_id"] != branch["id"]:
            fail("ERR_INVALID_REQUEST", "drawer_counts references an unknown drawer")
        cv = entry["counted_cash_cents"]
        if not isinstance(cv, int) or isinstance(cv, bool) or cv < 0:
            fail("ERR_INVALID_REQUEST", "counted_cash_cents must be a non-negative integer")
        seen[did] = cv
    for d in open_drawers:
        if d["id"] not in seen:
            fail("ERR_INVALID_REQUEST", "every unclosed drawer must be counted")
    # Compute discrepancy against recorded balances, then adjust to reality.
    discrepancy = vc - branch["vault_cash_cents"]
    for d in open_drawers:
        discrepancy += seen[d["id"]] - d["cash_balance_cents"]
    branch["vault_cash_cents"] = vc
    branch["status"] = "OPEN"
    touch(branch)
    counted_drawers = sorted(open_drawers, key=lambda x: (x["created_at"], x["id"]))
    for d in open_drawers:
        d["cash_balance_cents"] = seen[d["id"]]
        touch(d)
    a["status"] = "COMPLETED"
    a["discrepancy_total_cents"] = discrepancy
    touch(a)
    if abs(discrepancy) >= branch["over_short_investigation_threshold_cents"] and counted_drawers:
        create_over_short_case(branch, counted_drawers[0], discrepancy, business_date())
    return envelope_success(a)

@app.route("/api/audits/<auditId>/cancel", methods=["POST"])
def cancel_audit(auditId):
    uid, role = auth()
    require_role(role, {"Auditor"})
    a = get_path(DB.audits, auditId)
    if a["status"] != "PLANNED":
        fail("ERR_INVALID_STATE", "only a PLANNED audit can be cancelled")
    a["status"] = "CANCELLED"
    touch(a)
    return envelope_success(a)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
