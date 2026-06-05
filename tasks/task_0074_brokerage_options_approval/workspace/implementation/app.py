import os
import random
import string
import uuid
from datetime import datetime, timezone

from flask import Flask, request, jsonify

app = Flask(__name__)

# =============================================================================
# In-memory store (reset on every process boot; no seeding)
# =============================================================================
DB = {
    "accounts": {},
    "options_approvals": {},
    "margin_upgrades": {},
    "positions": {},
    "orders": {},
    "day_trades": {},
    "acat_transfers": {},
}

# =============================================================================
# Constants
# =============================================================================
PMA_INITIAL_MARGIN_RATE = 0.15
PMA_MIN_EQUITY_CENTS = 15000000
EQUITY_MAINT_RATE = 0.25
OPTION_MAINT_RATE = 1.00
PDT_DAYTRADE_THRESHOLD = 4
PDT_WINDOW_BUSINESS_DAYS = 5
PDT_MIN_EQUITY_CENTS = 2500000
OPTION_CONTRACT_MULTIPLIER = 100

LEVEL_MIN_COMBINED_CENTS = {1: 0, 2: 5000000, 3: 10000000, 4: 25000000}
LEVEL_MIN_EXP_RANK = {1: 0, 2: 1, 3: 2, 4: 3}
EXP_RANK = {"NONE": 0, "LIMITED": 1, "GOOD": 2, "EXTENSIVE": 3}

ROLES = {"AccountHolder", "ComplianceOfficer", "Custodian"}

PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0


# =============================================================================
# Errors
# =============================================================================
class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


def err(error_id, http_status, message=None):
    return ApiError(error_id, http_status, message)


# =============================================================================
# Helpers
# =============================================================================
def _ts():
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def gen_request_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def new_id():
    return str(uuid.uuid4())


def meta(pagination=None):
    m = {"api_request_id": gen_request_id(), "api_request_timestamp": _ts()}
    if pagination:
        m.update(pagination)
    return m


def success(data, response_type="object", status=200, pagination=None):
    body = {
        "meta": meta(pagination),
        "response_type": response_type,
        "data": data,
    }
    return jsonify(body), status


def error_response(e):
    body = {
        "meta": meta(),
        "response_type": "error",
        "data": {"error_id": e.error_id, "message": e.message},
    }
    return jsonify(body), e.http_status


@app.errorhandler(ApiError)
def handle_api_error(e):
    return error_response(e)


@app.errorhandler(404)
def handle_404(e):
    return error_response(ApiError("ERR_NOT_FOUND", 404, "Resource not found"))


@app.errorhandler(405)
def handle_405(e):
    return error_response(ApiError("ERR_NOT_FOUND", 404, "Resource not found"))


@app.errorhandler(Exception)
def handle_unexpected(e):
    if isinstance(e, ApiError):
        return error_response(e)
    return error_response(ApiError("ERR_VALIDATION", 422, str(e)))


# =============================================================================
# Auth / RBAC
# =============================================================================
def auth():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role:
        raise err("ERR_UNAUTHENTICATED", 401, "Missing X-User-ID or X-User-Role")
    return uid, role


def require_roles(role, allowed):
    if role not in allowed:
        raise err("ERR_FORBIDDEN_ROLE", 403, "Role not permitted for this operation")


def get_json():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise err("ERR_VALIDATION", 422, "Malformed request body")
    return data


def parse_pagination():
    args = request.args
    limit = args.get("limit", None)
    offset = args.get("offset", None)
    try:
        limit = int(limit) if limit is not None else PAGINATION_DEFAULT_LIMIT
    except (ValueError, TypeError):
        raise err("ERR_VALIDATION", 422, "Invalid limit")
    try:
        offset = int(offset) if offset is not None else PAGINATION_DEFAULT_OFFSET
    except (ValueError, TypeError):
        raise err("ERR_VALIDATION", 422, "Invalid offset")
    if limit < PAGINATION_MIN_LIMIT:
        limit = PAGINATION_MIN_LIMIT
    if limit > PAGINATION_MAX_LIMIT:
        limit = PAGINATION_MAX_LIMIT
    if offset < 0:
        offset = 0
    return limit, offset


def paginate(items, limit, offset):
    total = len(items)
    page = items[offset:offset + limit]
    pag = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }
    return page, pag


def sorted_by_created(items):
    return sorted(items, key=lambda r: (r.get("created_at", ""), r.get("_seq", 0)))


# Monotonic sequence to keep created_at-ascending stable across same-ms creates
_SEQ = [0]


def next_seq():
    _SEQ[0] += 1
    return _SEQ[0]


# =============================================================================
# Computed-field engine
# =============================================================================
def account_open_positions(account_id):
    return [p for p in DB["positions"].values()
            if p["account_id"] == account_id and p["status"] == "OPEN"]


def compute_maintenance_margin(account_id):
    positions = account_open_positions(account_id)
    positions = sorted(positions, key=lambda p: (p["created_at"], p["_seq"]))
    total = 0
    for p in positions:
        mv = abs(p["market_value_cents"])
        if p["instrument_type"] == "EQUITY":
            # floor(mv * 0.25) computed with exact integer math
            total += (mv * 25) // 100
        else:  # OPTION
            # floor(mv * 1.00)
            total += mv
    return total


def compute_equity(account_id):
    acct = DB["accounts"][account_id]
    total = acct["cash_balance_cents"]
    for p in account_open_positions(account_id):
        total += p["market_value_cents"]
    return total


def reserved_order_notional(account_id):
    total = 0
    for o in DB["orders"].values():
        if o["account_id"] != account_id:
            continue
        if o["status"] == "ACCEPTED":
            total += o["notional_cents"] or 0
        elif o["status"] == "PARTIALLY_FILLED":
            notional = o["notional_cents"] or 0
            qty = o["quantity"]
            unfilled = qty - o["filled_quantity"]
            if qty > 0:
                total += (notional * unfilled) // qty
    return total


def compute_buying_power(account_id):
    acct = DB["accounts"][account_id]
    equity = compute_equity(account_id)
    maint = compute_maintenance_margin(account_id)
    reserved = reserved_order_notional(account_id)
    margin_type = acct["margin_type"]
    excess_equity = equity - maint - reserved
    if margin_type == "CASH":
        return max(0, acct["cash_balance_cents"] - reserved)
    elif margin_type == "REG_T":
        return max(0, 2 * excess_equity)
    elif margin_type == "PMA":
        # equity / 0.15, floored toward zero. Exact integer floor for non-negative
        # equity: equity * 100 // 15. For negative equity, floor toward zero.
        if equity >= 0:
            pma_pool = (equity * 100) // 15
        else:
            pma_pool = -((abs(equity) * 100) // 15)
        return max(0, pma_pool - maint - reserved)
    return 0


def recompute_account_money(account_id):
    acct = DB["accounts"][account_id]
    acct["maintenance_margin_cents"] = compute_maintenance_margin(account_id)
    acct["equity_cents"] = compute_equity(account_id)
    acct["buying_power_cents"] = compute_buying_power(account_id)


def account_day_trades(account_id):
    return [d for d in DB["day_trades"].values() if d["account_id"] == account_id]


def compute_day_trade_count(account_id):
    from datetime import date
    rows = account_day_trades(account_id)
    if not rows:
        return 0
    dates = []
    for r in rows:
        try:
            dates.append(date.fromisoformat(r["trade_date"]))
        except (ValueError, TypeError):
            pass
    if not dates:
        return 0
    anchor = max(dates)
    from datetime import timedelta
    window_start = anchor - timedelta(days=PDT_WINDOW_BUSINESS_DAYS)
    count = 0
    for d in dates:
        if window_start <= d <= anchor:
            count += 1
    return count


def recompute_pdt(account_id):
    """Recompute day_trade_count and pdt_flagged; apply ACTIVE->RESTRICTED cascade
    if newly flagged under min equity. Returns True if status changed."""
    acct = DB["accounts"][account_id]
    count = compute_day_trade_count(account_id)
    acct["day_trade_count"] = count
    newly_flagged = False
    if count >= PDT_DAYTRADE_THRESHOLD and not acct["pdt_flagged"]:
        acct["pdt_flagged"] = True
        newly_flagged = True
    elif count >= PDT_DAYTRADE_THRESHOLD:
        acct["pdt_flagged"] = True

    status_changed = False
    if newly_flagged:
        recompute_account_money(account_id)
        if acct["equity_cents"] < PDT_MIN_EQUITY_CENTS and acct["status"] == "ACTIVE":
            cascade_restrict(account_id)
            status_changed = True
    return status_changed


def touch(rec):
    rec["updated_at"] = _ts()
    if "version" in rec:
        rec["version"] += 1


# =============================================================================
# Serialization
# =============================================================================
def serialize_account(a):
    recompute_account_money(a["id"])
    a["day_trade_count"] = compute_day_trade_count(a["id"])
    return {
        "id": a["id"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
        "account_holder_user_id": a["account_holder_user_id"],
        "legal_name": a["legal_name"],
        "tax_id": a["tax_id"],
        "date_of_birth": a["date_of_birth"],
        "w9_certified": a["w9_certified"],
        "liquid_net_worth_cents": a["liquid_net_worth_cents"],
        "annual_income_cents": a["annual_income_cents"],
        "investment_experience": a["investment_experience"],
        "status": a["status"],
        "options_level": a["options_level"],
        "margin_type": a["margin_type"],
        "cash_balance_cents": a["cash_balance_cents"],
        "maintenance_margin_cents": a["maintenance_margin_cents"],
        "buying_power_cents": a["buying_power_cents"],
        "equity_cents": a["equity_cents"],
        "day_trade_count": a["day_trade_count"],
        "pdt_flagged": a["pdt_flagged"],
    }


def serialize_options_approval(o):
    return {
        "id": o["id"],
        "created_at": o["created_at"],
        "updated_at": o["updated_at"],
        "version": o["version"],
        "account_id": o["account_id"],
        "requested_level": o["requested_level"],
        "submitted_by_user_id": o["submitted_by_user_id"],
        "decided_by_user_id": o["decided_by_user_id"],
        "status": o["status"],
        "rejection_reason": o["rejection_reason"],
    }


def serialize_margin_upgrade(m):
    return {
        "id": m["id"],
        "created_at": m["created_at"],
        "updated_at": m["updated_at"],
        "version": m["version"],
        "account_id": m["account_id"],
        "requested_margin_type": m["requested_margin_type"],
        "submitted_by_user_id": m["submitted_by_user_id"],
        "decided_by_user_id": m["decided_by_user_id"],
        "status": m["status"],
        "expected_account_version": m["expected_account_version"],
    }


def serialize_position(p):
    return {
        "id": p["id"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
        "account_id": p["account_id"],
        "symbol": p["symbol"],
        "instrument_type": p["instrument_type"],
        "quantity": p["quantity"],
        "market_value_cents": p["market_value_cents"],
        "status": p["status"],
    }


def serialize_order(o):
    return {
        "id": o["id"],
        "created_at": o["created_at"],
        "updated_at": o["updated_at"],
        "version": o["version"],
        "account_id": o["account_id"],
        "symbol": o["symbol"],
        "instrument_type": o["instrument_type"],
        "side": o["side"],
        "order_type": o["order_type"],
        "quantity": o["quantity"],
        "limit_price_cents": o["limit_price_cents"],
        "stop_price_cents": o["stop_price_cents"],
        "notional_cents": o["notional_cents"],
        "opened_position_same_day": o["opened_position_same_day"],
        "trade_date": o["trade_date"],
        "status": o["status"],
        "filled_quantity": o["filled_quantity"],
    }


def serialize_day_trade(d):
    return {
        "id": d["id"],
        "created_at": d["created_at"],
        "account_id": d["account_id"],
        "closing_order_id": d["closing_order_id"],
        "symbol": d["symbol"],
        "trade_date": d["trade_date"],
    }


def serialize_acat(t):
    return {
        "id": t["id"],
        "created_at": t["created_at"],
        "updated_at": t["updated_at"],
        "version": t["version"],
        "account_id": t["account_id"],
        "direction": t["direction"],
        "counterparty_dtc": t["counterparty_dtc"],
        "transfer_value_cents": t["transfer_value_cents"],
        "status": t["status"],
        "reject_code": t["reject_code"],
    }


# =============================================================================
# Lookups
# =============================================================================
def get_account_or_404(account_id):
    a = DB["accounts"].get(account_id)
    if a is None:
        raise err("ERR_NOT_FOUND", 404, "Account not found")
    return a


def get_or_404(collection, rid, label="Resource"):
    r = DB[collection].get(rid)
    if r is None:
        raise err("ERR_NOT_FOUND", 404, label + " not found")
    return r


# =============================================================================
# Cascade: restrict
# =============================================================================
def cascade_restrict(account_id):
    acct = DB["accounts"][account_id]
    acct["status"] = "RESTRICTED"
    # cancel working orders
    for o in DB["orders"].values():
        if o["account_id"] != account_id:
            continue
        if o["status"] in ("DRAFT", "ACCEPTED", "PARTIALLY_FILLED"):
            o["status"] = "CANCELLED"
            touch(o)
    # reject pending options approvals
    for oa in DB["options_approvals"].values():
        if oa["account_id"] != account_id:
            continue
        if oa["status"] in ("DRAFT", "SUBMITTED"):
            oa["status"] = "REJECTED"
            oa["rejection_reason"] = "ACCOUNT_RESTRICTED"
            touch(oa)
    touch(acct)
    recompute_account_money(account_id)


# =============================================================================
# Required-field extraction
# =============================================================================
def require_field(body, name):
    if name not in body or body[name] is None:
        raise err("ERR_VALIDATION", 422, "Missing required field: " + name)
    return body[name]


def require_enum(body, name, allowed):
    value = require_field(body, name)
    if value not in allowed:
        raise err("ERR_VALIDATION", 422, "Invalid value for " + name + ": " + str(value))
    return value


# =============================================================================
# ACCOUNT endpoints
# =============================================================================
@app.route("/accounts", methods=["POST"])
def create_account():
    uid, role = auth()
    require_roles(role, {"AccountHolder"})
    body = get_json()
    aid = new_id()
    ts = _ts()
    acct = {
        "id": aid,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": next_seq(),
        "account_holder_user_id": require_field(body, "account_holder_user_id"),
        "legal_name": require_field(body, "legal_name"),
        "tax_id": require_field(body, "tax_id"),
        "date_of_birth": require_field(body, "date_of_birth"),
        "w9_certified": bool(body.get("w9_certified", False)),
        "liquid_net_worth_cents": require_field(body, "liquid_net_worth_cents"),
        "annual_income_cents": require_field(body, "annual_income_cents"),
        "investment_experience": require_field(body, "investment_experience"),
        "status": "PENDING_KYC",
        "options_level": 0,
        "margin_type": "CASH",
        "cash_balance_cents": int(body.get("cash_balance_cents", 0) or 0),
        "maintenance_margin_cents": 0,
        "buying_power_cents": 0,
        "equity_cents": 0,
        "day_trade_count": 0,
        "pdt_flagged": False,
    }
    DB["accounts"][aid] = acct
    return success(serialize_account(acct), "object", 201)


@app.route("/accounts/<account_id>", methods=["GET"])
def get_account(account_id):
    uid, role = auth()
    require_roles(role, {"AccountHolder", "ComplianceOfficer", "Custodian"})
    a = get_account_or_404(account_id)
    return success(serialize_account(a), "object", 200)


@app.route("/accounts", methods=["GET"])
def list_accounts():
    uid, role = auth()
    require_roles(role, {"ComplianceOfficer"})
    limit, offset = parse_pagination()
    items = list(DB["accounts"].values())
    holder = request.args.get("account_holder_user_id")
    if holder is not None:
        items = [a for a in items if a["account_holder_user_id"] == holder]
    items = sorted_by_created(items)
    page, pag = paginate(items, limit, offset)
    return success([serialize_account(a) for a in page], "array", 200, pag)


@app.route("/accounts/<account_id>/activate", methods=["POST"])
def activate_account(account_id):
    uid, role = auth()
    require_roles(role, {"ComplianceOfficer"})
    a = get_account_or_404(account_id)
    status = a["status"]
    if status == "PENDING_KYC":
        # KYC gate
        if not a["w9_certified"]:
            raise err("ERR_W9_NOT_CERTIFIED", 422, "W-9 not certified")
        if not _is_at_least_18(a["date_of_birth"], a["created_at"]):
            raise err("ERR_KYC_AGE", 422, "Account holder under 18")
        if not a["tax_id"]:
            raise err("ERR_KYC_INCOMPLETE", 422, "tax_id missing")
        a["status"] = "ACTIVE"
        touch(a)
        recompute_account_money(account_id)
        return success(serialize_account(a), "object", 200)
    elif status == "RESTRICTED":
        recompute_account_money(account_id)
        if a["pdt_flagged"] and a["equity_cents"] < PDT_MIN_EQUITY_CENTS:
            raise err("ERR_PDT_EQUITY_CALL", 409, "PDT equity call: below minimum equity")
        a["status"] = "ACTIVE"
        touch(a)
        recompute_account_money(account_id)
        return success(serialize_account(a), "object", 200)
    else:
        raise err("ERR_INVALID_STATE", 409, "Account not activatable from " + status)


def _is_at_least_18(dob_str, created_at_str):
    from datetime import date
    try:
        dob = date.fromisoformat(dob_str)
    except (ValueError, TypeError):
        return False
    created = date.fromisoformat(created_at_str[:10])
    eighteenth = date(dob.year + 18, dob.month, dob.day) if not (dob.month == 2 and dob.day == 29) \
        else date(dob.year + 18, 3, 1)
    return eighteenth <= created


@app.route("/accounts/<account_id>/restrict", methods=["POST"])
def restrict_account(account_id):
    uid, role = auth()
    require_roles(role, {"ComplianceOfficer"})
    a = get_account_or_404(account_id)
    if a["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", 409, "Account not ACTIVE")
    cascade_restrict(account_id)
    return success(serialize_account(a), "object", 200)


@app.route("/accounts/<account_id>/close", methods=["POST"])
def close_account(account_id):
    uid, role = auth()
    require_roles(role, {"ComplianceOfficer"})
    a = get_account_or_404(account_id)
    if a["status"] not in ("ACTIVE", "RESTRICTED"):
        raise err("ERR_INVALID_STATE", 409, "Account not in a closable state")
    # preconditions
    open_positions = [p for p in DB["positions"].values()
                      if p["account_id"] == account_id and p["status"] == "OPEN"]
    if open_positions:
        raise err("ERR_OPEN_POSITIONS", 409, "Account has open positions")
    pending = [t for t in DB["acat_transfers"].values()
               if t["account_id"] == account_id and t["status"] in ("REQUESTED", "VALIDATED")]
    if pending:
        raise err("ERR_PENDING_TRANSFER", 409, "Account has pending transfers")
    a["status"] = "CLOSED"
    touch(a)
    return success(serialize_account(a), "object", 200)


# =============================================================================
# OPTIONS APPROVAL endpoints
# =============================================================================
@app.route("/options-approvals", methods=["POST"])
def create_options_approval():
    uid, role = auth()
    require_roles(role, {"ComplianceOfficer"})
    body = get_json()
    account_id = require_field(body, "account_id")
    requested_level = require_field(body, "requested_level")
    get_account_or_404(account_id)
    oid = new_id()
    ts = _ts()
    oa = {
        "id": oid,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": next_seq(),
        "account_id": account_id,
        "requested_level": requested_level,
        "submitted_by_user_id": None,
        "decided_by_user_id": None,
        "status": "DRAFT",
        "rejection_reason": None,
    }
    DB["options_approvals"][oid] = oa
    return success(serialize_options_approval(oa), "object", 201)


@app.route("/options-approvals/<approval_id>", methods=["GET"])
def get_options_approval(approval_id):
    uid, role = auth()
    require_roles(role, {"ComplianceOfficer", "AccountHolder"})
    oa = get_or_404("options_approvals", approval_id, "OptionsApproval")
    return success(serialize_options_approval(oa), "object", 200)


@app.route("/options-approvals", methods=["GET"])
def list_options_approvals():
    uid, role = auth()
    require_roles(role, {"ComplianceOfficer", "AccountHolder"})
    limit, offset = parse_pagination()
    items = list(DB["options_approvals"].values())
    acct = request.args.get("account_id")
    if acct is not None:
        items = [o for o in items if o["account_id"] == acct]
    items = sorted_by_created(items)
    page, pag = paginate(items, limit, offset)
    return success([serialize_options_approval(o) for o in page], "array", 200, pag)


@app.route("/options-approvals/<approval_id>/submit", methods=["POST"])
def submit_options_approval(approval_id):
    uid, role = auth()
    require_roles(role, {"ComplianceOfficer"})
    oa = get_or_404("options_approvals", approval_id, "OptionsApproval")
    if oa["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", 409, "OptionsApproval not in DRAFT")
    acct = get_account_or_404(oa["account_id"])
    if acct["status"] != "ACTIVE":
        raise err("ERR_ACCOUNT_NOT_ACTIVE", 409, "Account not ACTIVE")
    if oa["requested_level"] != acct["options_level"] + 1:
        raise err("ERR_LEVEL_SKIP", 422, "Levels granted one rung at a time")
    oa["status"] = "SUBMITTED"
    oa["submitted_by_user_id"] = uid
    touch(oa)
    return success(serialize_options_approval(oa), "object", 200)


@app.route("/options-approvals/<approval_id>/approve", methods=["POST"])
def approve_options_approval(approval_id):
    uid, role = auth()
    require_roles(role, {"ComplianceOfficer"})
    oa = get_or_404("options_approvals", approval_id, "OptionsApproval")
    if oa["status"] != "SUBMITTED":
        raise err("ERR_INVALID_STATE", 409, "OptionsApproval not SUBMITTED")
    # segregation of duties first
    if uid == oa["submitted_by_user_id"]:
        raise err("ERR_SEGREGATION_OF_DUTIES", 403, "Submitter cannot approve")
    acct = get_account_or_404(oa["account_id"])
    # suitability gate
    if not _suitability_ok(acct, oa["requested_level"]):
        raise err("ERR_SUITABILITY_NOT_MET", 422, "Suitability gate failed")
    oa["status"] = "APPROVED"
    oa["decided_by_user_id"] = uid
    touch(oa)
    acct["options_level"] = oa["requested_level"]
    touch(acct)
    recompute_account_money(acct["id"])
    return success(serialize_options_approval(oa), "object", 200)


def _suitability_ok(acct, level):
    combined = acct["liquid_net_worth_cents"] + acct["annual_income_cents"]
    exp_rank = EXP_RANK.get(acct["investment_experience"], 0)
    if combined < LEVEL_MIN_COMBINED_CENTS.get(level, 0):
        return False
    if exp_rank < LEVEL_MIN_EXP_RANK.get(level, 0):
        return False
    return True


@app.route("/options-approvals/<approval_id>/reject", methods=["POST"])
def reject_options_approval(approval_id):
    uid, role = auth()
    require_roles(role, {"ComplianceOfficer"})
    oa = get_or_404("options_approvals", approval_id, "OptionsApproval")
    if oa["status"] != "SUBMITTED":
        raise err("ERR_INVALID_STATE", 409, "OptionsApproval not SUBMITTED")
    if uid == oa["submitted_by_user_id"]:
        raise err("ERR_SEGREGATION_OF_DUTIES", 403, "Submitter cannot reject")
    body = get_json()
    oa["status"] = "REJECTED"
    oa["decided_by_user_id"] = uid
    oa["rejection_reason"] = body.get("rejection_reason")
    touch(oa)
    return success(serialize_options_approval(oa), "object", 200)


# =============================================================================
# MARGIN UPGRADE endpoints
# =============================================================================
@app.route("/margin-upgrades", methods=["POST"])
def create_margin_upgrade():
    uid, role = auth()
    require_roles(role, {"ComplianceOfficer"})
    body = get_json()
    account_id = require_field(body, "account_id")
    requested_margin_type = require_field(body, "requested_margin_type")
    get_account_or_404(account_id)
    mid = new_id()
    ts = _ts()
    m = {
        "id": mid,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": next_seq(),
        "account_id": account_id,
        "requested_margin_type": requested_margin_type,
        "submitted_by_user_id": None,
        "decided_by_user_id": None,
        "status": "DRAFT",
        "expected_account_version": None,
    }
    DB["margin_upgrades"][mid] = m
    return success(serialize_margin_upgrade(m), "object", 201)


@app.route("/margin-upgrades/<upgrade_id>", methods=["GET"])
def get_margin_upgrade(upgrade_id):
    uid, role = auth()
    require_roles(role, {"ComplianceOfficer", "AccountHolder"})
    m = get_or_404("margin_upgrades", upgrade_id, "MarginUpgrade")
    return success(serialize_margin_upgrade(m), "object", 200)


@app.route("/margin-upgrades", methods=["GET"])
def list_margin_upgrades():
    uid, role = auth()
    require_roles(role, {"ComplianceOfficer", "AccountHolder"})
    limit, offset = parse_pagination()
    items = list(DB["margin_upgrades"].values())
    acct = request.args.get("account_id")
    if acct is not None:
        items = [m for m in items if m["account_id"] == acct]
    items = sorted_by_created(items)
    page, pag = paginate(items, limit, offset)
    return success([serialize_margin_upgrade(m) for m in page], "array", 200, pag)


@app.route("/margin-upgrades/<upgrade_id>/submit", methods=["POST"])
def submit_margin_upgrade(upgrade_id):
    uid, role = auth()
    require_roles(role, {"ComplianceOfficer"})
    m = get_or_404("margin_upgrades", upgrade_id, "MarginUpgrade")
    if m["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", 409, "MarginUpgrade not DRAFT")
    acct = get_account_or_404(m["account_id"])
    if acct["status"] != "ACTIVE":
        raise err("ERR_ACCOUNT_NOT_ACTIVE", 409, "Account not ACTIVE")
    if m["requested_margin_type"] == acct["margin_type"]:
        raise err("ERR_MARGIN_NOOP", 422, "Requested margin type already in force")
    if m["requested_margin_type"] == "PMA":
        recompute_account_money(acct["id"])
        if acct["equity_cents"] < PMA_MIN_EQUITY_CENTS:
            raise err("ERR_PMA_EQUITY_MINIMUM", 422, "Below PMA equity minimum")
    m["status"] = "SUBMITTED"
    m["submitted_by_user_id"] = uid
    touch(m)
    return success(serialize_margin_upgrade(m), "object", 200)


@app.route("/margin-upgrades/<upgrade_id>/approve", methods=["POST"])
def approve_margin_upgrade(upgrade_id):
    uid, role = auth()
    require_roles(role, {"ComplianceOfficer"})
    m = get_or_404("margin_upgrades", upgrade_id, "MarginUpgrade")
    if m["status"] != "SUBMITTED":
        raise err("ERR_INVALID_STATE", 409, "MarginUpgrade not SUBMITTED")
    body = get_json()
    # segregation of duties first
    if uid == m["submitted_by_user_id"]:
        raise err("ERR_SEGREGATION_OF_DUTIES", 403, "Submitter cannot approve")
    acct = get_account_or_404(m["account_id"])
    expected = body.get("expected_account_version")
    m["expected_account_version"] = expected
    if expected != acct["version"]:
        raise err("ERR_STALE_ACCOUNT_VERSION", 412, "Stale account version")
    m["status"] = "APPROVED"
    m["decided_by_user_id"] = uid
    touch(m)
    acct["margin_type"] = m["requested_margin_type"]
    touch(acct)
    recompute_account_money(acct["id"])
    return success(serialize_margin_upgrade(m), "object", 200)


@app.route("/margin-upgrades/<upgrade_id>/reject", methods=["POST"])
def reject_margin_upgrade(upgrade_id):
    uid, role = auth()
    require_roles(role, {"ComplianceOfficer"})
    m = get_or_404("margin_upgrades", upgrade_id, "MarginUpgrade")
    if m["status"] != "SUBMITTED":
        raise err("ERR_INVALID_STATE", 409, "MarginUpgrade not SUBMITTED")
    if uid == m["submitted_by_user_id"]:
        raise err("ERR_SEGREGATION_OF_DUTIES", 403, "Submitter cannot reject")
    m["status"] = "REJECTED"
    m["decided_by_user_id"] = uid
    touch(m)
    return success(serialize_margin_upgrade(m), "object", 200)


# =============================================================================
# POSITION endpoints
# =============================================================================
@app.route("/positions", methods=["POST"])
def create_position():
    uid, role = auth()
    require_roles(role, {"AccountHolder", "ComplianceOfficer"})
    body = get_json()
    account_id = require_field(body, "account_id")
    get_account_or_404(account_id)
    pid = new_id()
    ts = _ts()
    p = {
        "id": pid,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": next_seq(),
        "account_id": account_id,
        "symbol": require_field(body, "symbol"),
        "instrument_type": require_field(body, "instrument_type"),
        "quantity": require_field(body, "quantity"),
        "market_value_cents": require_field(body, "market_value_cents"),
        "status": "OPEN",
    }
    DB["positions"][pid] = p
    recompute_account_money(account_id)
    return success(serialize_position(p), "object", 201)


@app.route("/positions/<position_id>", methods=["GET"])
def get_position(position_id):
    uid, role = auth()
    require_roles(role, {"AccountHolder", "ComplianceOfficer"})
    p = get_or_404("positions", position_id, "Position")
    return success(serialize_position(p), "object", 200)


@app.route("/positions", methods=["GET"])
def list_positions():
    uid, role = auth()
    require_roles(role, {"AccountHolder", "ComplianceOfficer"})
    limit, offset = parse_pagination()
    items = list(DB["positions"].values())
    acct = request.args.get("account_id")
    if acct is not None:
        items = [p for p in items if p["account_id"] == acct]
    items = sorted_by_created(items)
    page, pag = paginate(items, limit, offset)
    return success([serialize_position(p) for p in page], "array", 200, pag)


@app.route("/positions/<position_id>/close", methods=["POST"])
def close_position(position_id):
    uid, role = auth()
    require_roles(role, {"AccountHolder", "ComplianceOfficer"})
    p = get_or_404("positions", position_id, "Position")
    if p["status"] != "OPEN":
        raise err("ERR_INVALID_STATE", 409, "Position not OPEN")
    acct = get_account_or_404(p["account_id"])
    if acct["status"] not in ("ACTIVE", "RESTRICTED"):
        raise err("ERR_ACCOUNT_NOT_ACTIVE", 409, "Account not ACTIVE/RESTRICTED")
    p["status"] = "CLOSED"
    touch(p)
    recompute_account_money(acct["id"])
    return success(serialize_position(p), "object", 200)


# =============================================================================
# ORDER endpoints
# =============================================================================
@app.route("/orders", methods=["POST"])
def create_order():
    uid, role = auth()
    require_roles(role, {"AccountHolder"})
    body = get_json()
    account_id = require_field(body, "account_id")
    get_account_or_404(account_id)
    oid = new_id()
    ts = _ts()
    o = {
        "id": oid,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": next_seq(),
        "account_id": account_id,
        "symbol": require_field(body, "symbol"),
        "instrument_type": require_field(body, "instrument_type"),
        "side": require_field(body, "side"),
        "order_type": require_enum(body, "order_type", {"LIMIT", "STOP", "TAKE_PROFIT"}),
        "quantity": require_field(body, "quantity"),
        "limit_price_cents": body.get("limit_price_cents"),
        "stop_price_cents": body.get("stop_price_cents"),
        "notional_cents": None,
        "opened_position_same_day": bool(body.get("opened_position_same_day", False)),
        "trade_date": require_field(body, "trade_date"),
        "status": "DRAFT",
        "filled_quantity": 0,
    }
    DB["orders"][oid] = o
    return success(serialize_order(o), "object", 201)


@app.route("/orders/<order_id>", methods=["GET"])
def get_order(order_id):
    uid, role = auth()
    require_roles(role, {"AccountHolder", "ComplianceOfficer"})
    o = get_or_404("orders", order_id, "Order")
    return success(serialize_order(o), "object", 200)


@app.route("/orders", methods=["GET"])
def list_orders():
    uid, role = auth()
    require_roles(role, {"AccountHolder", "ComplianceOfficer"})
    limit, offset = parse_pagination()
    items = list(DB["orders"].values())
    acct = request.args.get("account_id")
    if acct is not None:
        items = [o for o in items if o["account_id"] == acct]
    items = sorted_by_created(items)
    page, pag = paginate(items, limit, offset)
    return success([serialize_order(o) for o in page], "array", 200, pag)


def _price_for_notional(o):
    if o["order_type"] == "LIMIT":
        return o["limit_price_cents"]
    elif o["order_type"] == "STOP":
        return o["stop_price_cents"]
    elif o["order_type"] == "TAKE_PROFIT":
        return max(o["limit_price_cents"], o["stop_price_cents"])
    return 0


def _compute_notional(o):
    # SELL against existing OPEN long position in same symbol reserves 0
    if o["side"] == "SELL":
        for p in DB["positions"].values():
            if (p["account_id"] == o["account_id"] and p["status"] == "OPEN"
                    and p["symbol"] == o["symbol"] and p["quantity"] > 0):
                return 0
    price = _price_for_notional(o)
    base = o["quantity"] * price
    if o["instrument_type"] == "OPTION":
        base = base * OPTION_CONTRACT_MULTIPLIER
    return base


def _prices_complete(o):
    ot = o["order_type"]
    lp = o["limit_price_cents"]
    sp = o["stop_price_cents"]
    if ot == "LIMIT":
        return lp is not None and lp > 0
    elif ot == "STOP":
        return sp is not None and sp > 0
    elif ot == "TAKE_PROFIT":
        return lp is not None and lp > 0 and sp is not None and sp > 0
    return False


@app.route("/orders/<order_id>/accept", methods=["POST"])
def accept_order(order_id):
    uid, role = auth()
    require_roles(role, {"AccountHolder"})
    o = get_or_404("orders", order_id, "Order")
    if o["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", 409, "Order not DRAFT")
    acct = get_account_or_404(o["account_id"])
    # 1. account ACTIVE
    if acct["status"] != "ACTIVE":
        raise err("ERR_ACCOUNT_NOT_ACTIVE", 409, "Account not ACTIVE")
    # 2. options gating
    if o["instrument_type"] == "OPTION" and acct["options_level"] < 1:
        raise err("ERR_OPTIONS_NOT_APPROVED", 422, "Options not approved")
    # 3. price completeness
    if not _prices_complete(o):
        raise err("ERR_MISSING_PRICE", 422, "Required price field missing")
    # 4. PDT preventive block
    recompute_account_money(acct["id"])
    if o["opened_position_same_day"]:
        if not acct["pdt_flagged"] and acct["equity_cents"] < PDT_MIN_EQUITY_CENTS:
            same_date = [d for d in DB["day_trades"].values()
                         if d["account_id"] == acct["id"] and d["trade_date"] == o["trade_date"]]
            prospective = len(same_date) + 1
            if prospective >= PDT_DAYTRADE_THRESHOLD:
                raise err("ERR_PDT_RULE_BLOCK", 409, "PDT rule block")
    # 5. buying power
    notional = _compute_notional(o)
    if notional > acct["buying_power_cents"]:
        raise err("ERR_INSUFFICIENT_BUYING_POWER", 409, "Insufficient buying power")
    o["notional_cents"] = notional
    o["status"] = "ACCEPTED"
    touch(o)
    recompute_account_money(acct["id"])
    return success(serialize_order(o), "object", 200)


@app.route("/orders/<order_id>/fill", methods=["POST"])
def fill_order(order_id):
    uid, role = auth()
    require_roles(role, {"ComplianceOfficer"})
    o = get_or_404("orders", order_id, "Order")
    if o["status"] not in ("ACCEPTED", "PARTIALLY_FILLED"):
        raise err("ERR_INVALID_STATE", 409, "Order not fillable")
    body = get_json()
    fq = body.get("fill_quantity")
    if fq is None or not isinstance(fq, int) or fq <= 0:
        raise err("ERR_FILL_QUANTITY", 422, "Invalid fill_quantity")
    new_total = o["filled_quantity"] + fq
    if new_total > o["quantity"]:
        raise err("ERR_FILL_QUANTITY", 422, "Fill exceeds order quantity")
    if new_total == o["quantity"]:
        o["filled_quantity"] = o["quantity"]
        o["status"] = "FILLED"
        touch(o)
        acct = get_account_or_404(o["account_id"])
        recompute_account_money(acct["id"])
        if o["opened_position_same_day"]:
            _create_day_trade(o)
            recompute_pdt(acct["id"])
        recompute_account_money(acct["id"])
    else:
        o["filled_quantity"] = new_total
        o["status"] = "PARTIALLY_FILLED"
        touch(o)
        recompute_account_money(o["account_id"])
    return success(serialize_order(o), "object", 200)


def _create_day_trade(order):
    did = new_id()
    ts = _ts()
    d = {
        "id": did,
        "created_at": ts,
        "_seq": next_seq(),
        "account_id": order["account_id"],
        "closing_order_id": order["id"],
        "symbol": order["symbol"],
        "trade_date": order["trade_date"],
    }
    DB["day_trades"][did] = d
    return d


@app.route("/orders/<order_id>/cancel", methods=["POST"])
def cancel_order(order_id):
    uid, role = auth()
    require_roles(role, {"AccountHolder"})
    o = get_or_404("orders", order_id, "Order")
    if o["status"] not in ("ACCEPTED", "PARTIALLY_FILLED"):
        raise err("ERR_INVALID_STATE", 409, "Order not cancellable")
    o["status"] = "CANCELLED"
    touch(o)
    recompute_account_money(o["account_id"])
    return success(serialize_order(o), "object", 200)


@app.route("/orders/<order_id>/reject", methods=["POST"])
def reject_order(order_id):
    uid, role = auth()
    require_roles(role, {"AccountHolder"})
    o = get_or_404("orders", order_id, "Order")
    if o["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", 409, "Order not DRAFT")
    o["status"] = "REJECTED"
    touch(o)
    return success(serialize_order(o), "object", 200)


# =============================================================================
# DAY TRADE endpoints
# =============================================================================
@app.route("/_day-trades/seed", methods=["POST"])
def seed_day_trades():
    uid, role = auth()
    require_roles(role, {"ComplianceOfficer"})
    body = get_json()
    account_id = require_field(body, "account_id")
    trade_date = require_field(body, "trade_date")
    count = require_field(body, "count")
    acct = get_account_or_404(account_id)
    for _ in range(int(count)):
        did = new_id()
        ts = _ts()
        d = {
            "id": did,
            "created_at": ts,
            "_seq": next_seq(),
            "account_id": account_id,
            "closing_order_id": None,
            "symbol": body.get("symbol", "SEED"),
            "trade_date": trade_date,
        }
        DB["day_trades"][did] = d
    recompute_pdt(account_id)
    recompute_account_money(account_id)
    return success(serialize_account(acct), "object", 201)


@app.route("/day-trades/<day_trade_id>", methods=["GET"])
def get_day_trade(day_trade_id):
    uid, role = auth()
    require_roles(role, {"ComplianceOfficer", "AccountHolder"})
    d = get_or_404("day_trades", day_trade_id, "DayTrade")
    return success(serialize_day_trade(d), "object", 200)


@app.route("/day-trades", methods=["GET"])
def list_day_trades():
    uid, role = auth()
    require_roles(role, {"ComplianceOfficer", "AccountHolder"})
    limit, offset = parse_pagination()
    items = list(DB["day_trades"].values())
    acct = request.args.get("account_id")
    if acct is not None:
        items = [d for d in items if d["account_id"] == acct]
    coid = request.args.get("closing_order_id")
    if coid is not None:
        items = [d for d in items if d["closing_order_id"] == coid]
    items = sorted_by_created(items)
    page, pag = paginate(items, limit, offset)
    return success([serialize_day_trade(d) for d in page], "array", 200, pag)


# =============================================================================
# ACAT TRANSFER endpoints
# =============================================================================
@app.route("/acat-transfers", methods=["POST"])
def create_acat():
    uid, role = auth()
    require_roles(role, {"AccountHolder", "Custodian"})
    body = get_json()
    account_id = require_field(body, "account_id")
    get_account_or_404(account_id)
    tid = new_id()
    ts = _ts()
    t = {
        "id": tid,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": next_seq(),
        "account_id": account_id,
        "direction": require_field(body, "direction"),
        "counterparty_dtc": require_field(body, "counterparty_dtc"),
        "transfer_value_cents": require_field(body, "transfer_value_cents"),
        "status": "REQUESTED",
        "reject_code": None,
    }
    DB["acat_transfers"][tid] = t
    return success(serialize_acat(t), "object", 201)


@app.route("/acat-transfers/<transfer_id>", methods=["GET"])
def get_acat(transfer_id):
    uid, role = auth()
    require_roles(role, {"AccountHolder", "Custodian", "ComplianceOfficer"})
    t = get_or_404("acat_transfers", transfer_id, "AcatTransfer")
    return success(serialize_acat(t), "object", 200)


@app.route("/acat-transfers", methods=["GET"])
def list_acat():
    uid, role = auth()
    require_roles(role, {"AccountHolder", "Custodian", "ComplianceOfficer"})
    limit, offset = parse_pagination()
    items = list(DB["acat_transfers"].values())
    acct = request.args.get("account_id")
    if acct is not None:
        items = [t for t in items if t["account_id"] == acct]
    items = sorted_by_created(items)
    page, pag = paginate(items, limit, offset)
    return success([serialize_acat(t) for t in page], "array", 200, pag)


@app.route("/acat-transfers/<transfer_id>/validate", methods=["POST"])
def validate_acat(transfer_id):
    uid, role = auth()
    require_roles(role, {"Custodian"})
    t = get_or_404("acat_transfers", transfer_id, "AcatTransfer")
    if t["status"] != "REQUESTED":
        raise err("ERR_INVALID_STATE", 409, "Transfer not REQUESTED")
    acct = get_account_or_404(t["account_id"])
    if acct["status"] not in ("ACTIVE", "RESTRICTED"):
        raise err("ERR_ACCOUNT_NOT_ACTIVE", 409, "Account not ACTIVE/RESTRICTED")
    t["status"] = "VALIDATED"
    touch(t)
    return success(serialize_acat(t), "object", 200)


@app.route("/acat-transfers/<transfer_id>/settle", methods=["POST"])
def settle_acat(transfer_id):
    uid, role = auth()
    require_roles(role, {"Custodian"})
    t = get_or_404("acat_transfers", transfer_id, "AcatTransfer")
    if t["status"] != "VALIDATED":
        raise err("ERR_INVALID_STATE", 409, "Transfer not VALIDATED")
    acct = get_account_or_404(t["account_id"])
    if acct["status"] != "ACTIVE":
        raise err("ERR_ACCOUNT_NOT_ACTIVE", 409, "Account not ACTIVE")
    t["status"] = "SETTLED"
    touch(t)
    if t["direction"] == "IN":
        acct["cash_balance_cents"] += t["transfer_value_cents"]
    else:
        acct["cash_balance_cents"] -= t["transfer_value_cents"]
    touch(acct)
    recompute_account_money(acct["id"])
    return success(serialize_acat(t), "object", 200)


@app.route("/acat-transfers/<transfer_id>/reject", methods=["POST"])
def reject_acat(transfer_id):
    uid, role = auth()
    require_roles(role, {"Custodian"})
    t = get_or_404("acat_transfers", transfer_id, "AcatTransfer")
    if t["status"] not in ("REQUESTED", "VALIDATED"):
        raise err("ERR_INVALID_STATE", 409, "Transfer not rejectable")
    body = get_json()
    reject_code = body.get("reject_code")
    if not reject_code:
        raise err("ERR_MISSING_REJECT_CODE", 422, "Missing reject_code")
    t["status"] = "REJECTED"
    t["reject_code"] = reject_code
    touch(t)
    return success(serialize_acat(t), "object", 200)


@app.route("/acat-transfers/<transfer_id>/cancel", methods=["POST"])
def cancel_acat(transfer_id):
    uid, role = auth()
    require_roles(role, {"AccountHolder"})
    t = get_or_404("acat_transfers", transfer_id, "AcatTransfer")
    if t["status"] != "REQUESTED":
        raise err("ERR_INVALID_STATE", 409, "Transfer not REQUESTED")
    t["status"] = "CANCELLED"
    touch(t)
    return success(serialize_acat(t), "object", 200)


# =============================================================================
# Main
# =============================================================================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
