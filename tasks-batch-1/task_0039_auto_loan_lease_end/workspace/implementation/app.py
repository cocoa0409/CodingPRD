import os

from flask import Flask, request

import db
from db import new_id, next_seq
from errors import ApiError, err
from response import success, error_response, iso_now
import calculations as calc

app = Flask(__name__)

VALID_ROLES = {"FinanceManager", "Borrower", "Auditor"}

PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100


# ──────────────────────────────────────────────────────────────────────────
# Error handling
# ──────────────────────────────────────────────────────────────────────────
@app.errorhandler(ApiError)
def handle_api_error(e):
    return error_response(e.error_id, e.message, e.http_status)


@app.errorhandler(404)
def handle_404(e):
    return error_response("ERR_NOT_FOUND", "Resource not found.", 404)


@app.errorhandler(405)
def handle_405(e):
    return error_response("ERR_NOT_FOUND", "Method not allowed.", 404)


@app.errorhandler(Exception)
def handle_unexpected(e):
    if isinstance(e, ApiError):
        return error_response(e.error_id, e.message, e.http_status)
    return error_response("ERR_INVALID_REQUEST", str(e), 422)


# ──────────────────────────────────────────────────────────────────────────
# Auth helpers
# ──────────────────────────────────────────────────────────────────────────
def get_auth():
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in VALID_ROLES:
        raise err("ERR_UNAUTHENTICATED", "Missing or invalid auth headers.")
    return user_id, role


def require_role(role, allowed):
    if role not in allowed:
        raise err("ERR_FORBIDDEN", "Role not permitted for this operation.")


# ──────────────────────────────────────────────────────────────────────────
# Body / param helpers
# ──────────────────────────────────────────────────────────────────────────
def get_body():
    if request.data and request.data.strip():
        data = request.get_json(force=True, silent=True)
        if data is None:
            raise err("ERR_INVALID_REQUEST", "Malformed JSON body.")
        if not isinstance(data, dict):
            raise err("ERR_INVALID_REQUEST", "Body must be a JSON object.")
        return data
    return {}


def parse_pagination():
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    if limit_raw is None:
        limit = PAGINATION_DEFAULT_LIMIT
    else:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise err("ERR_INVALID_REQUEST", "limit must be an integer.")
        if limit < PAGINATION_MIN_LIMIT or limit > PAGINATION_MAX_LIMIT:
            raise err("ERR_INVALID_REQUEST", "limit out of range.")
    if offset_raw is None:
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise err("ERR_INVALID_REQUEST", "offset must be an integer.")
        if offset < 0:
            raise err("ERR_INVALID_REQUEST", "offset must be non-negative.")
    return limit, offset


def paginate(items, limit, offset):
    """items: list already sorted. Returns (slice, pagination_meta)."""
    total = len(items)
    page = items[offset:offset + limit]
    has_more = offset + limit < total
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": has_more,
    }
    return page, meta


def sort_by_created(items):
    return sorted(items, key=lambda r: (r["created_at"], r["_seq"]))


# ──────────────────────────────────────────────────────────────────────────
# Validation helpers
# ──────────────────────────────────────────────────────────────────────────
def require_fields(body, fields):
    for f in fields:
        if f not in body or body[f] is None:
            raise err("ERR_INVALID_REQUEST", f"Missing required field: {f}")


def require_str(body, field):
    v = body.get(field)
    if not isinstance(v, str) or v == "":
        raise err("ERR_INVALID_REQUEST", f"{field} must be a non-empty string.")
    return v


def require_int(body, field, non_negative=False):
    v = body.get(field)
    if isinstance(v, bool) or not isinstance(v, int):
        raise err("ERR_INVALID_REQUEST", f"{field} must be an integer.")
    if non_negative and v < 0:
        raise err("ERR_INVALID_REQUEST", f"{field} must be non-negative.")
    return v


def require_number(body, field):
    v = body.get(field)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise err("ERR_INVALID_REQUEST", f"{field} must be a number.")
    return v


def require_bool_optional(body, field, default=False):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if not isinstance(v, bool):
        raise err("ERR_INVALID_REQUEST", f"{field} must be a boolean.")
    return v


# ──────────────────────────────────────────────────────────────────────────
# System field helpers
# ──────────────────────────────────────────────────────────────────────────
def now():
    return iso_now()


def init_common(record):
    ts = now()
    record["id"] = new_id()
    record["created_at"] = ts
    record["updated_at"] = ts
    record["version"] = 1
    record["_seq"] = next_seq()
    return record


def touch(record):
    record["updated_at"] = now()
    record["version"] += 1


def active_rate_card():
    for rc in db.rate_cards.values():
        if rc["active"]:
            return rc
    return None


# ──────────────────────────────────────────────────────────────────────────
# Serializers (strip private fields like _seq)
# ──────────────────────────────────────────────────────────────────────────
def ser_customer(c):
    rc = active_rate_card()
    tier = calc.fico_tier(c["fico_score"], rc) if rc else None
    return {
        "id": c["id"],
        "full_name": c["full_name"],
        "email": c["email"],
        "fico_score": c["fico_score"],
        "fico_tier": tier,
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def ser_vehicle(v):
    return {
        "id": v["id"],
        "vin": v["vin"],
        "make_model": v["make_model"],
        "msrp_cents": v["msrp_cents"],
        "sale_price_cents": v["sale_price_cents"],
        "residual_value_cents": v["residual_value_cents"],
        "status": v["status"],
        "created_at": v["created_at"],
        "updated_at": v["updated_at"],
        "version": v["version"],
    }


def ser_rate_card(r):
    return {
        "id": r["id"],
        "name": r["name"],
        "tier_1_min_fico": r["tier_1_min_fico"],
        "tier_2_min_fico": r["tier_2_min_fico"],
        "tier_3_min_fico": r["tier_3_min_fico"],
        "tier_1_apr": r["tier_1_apr"],
        "tier_2_apr": r["tier_2_apr"],
        "tier_3_apr": r["tier_3_apr"],
        "tier_4_apr": r["tier_4_apr"],
        "lease_money_factor": r["lease_money_factor"],
        "default_rate_apr": r["default_rate_apr"],
        "lease_tax_rate": r["lease_tax_rate"],
        "active": r["active"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def ser_loan(l):
    return {
        "id": l["id"],
        "customer_id": l["customer_id"],
        "vehicle_id": l["vehicle_id"],
        "rate_card_id": l["rate_card_id"],
        "down_payment_cents": l["down_payment_cents"],
        "term_months": l["term_months"],
        "gap_insurance": l["gap_insurance"],
        "financed_principal_cents": l["financed_principal_cents"],
        "apr": l["apr"],
        "monthly_payment_cents": l["monthly_payment_cents"],
        "payments_made_count": l["payments_made_count"],
        "principal_balance_cents": l["principal_balance_cents"],
        "missed_payment_count": l["missed_payment_count"],
        "status": l["status"],
        "created_at": l["created_at"],
        "updated_at": l["updated_at"],
        "version": l["version"],
    }


def ser_lease(l):
    return {
        "id": l["id"],
        "customer_id": l["customer_id"],
        "vehicle_id": l["vehicle_id"],
        "rate_card_id": l["rate_card_id"],
        "down_payment_cents": l["down_payment_cents"],
        "term_months": l["term_months"],
        "annual_mileage_allowance": l["annual_mileage_allowance"],
        "per_mile_overage_rate_cents": l["per_mile_overage_rate_cents"],
        "disposition_fee_cents": l["disposition_fee_cents"],
        "purchase_option_fee_cents": l["purchase_option_fee_cents"],
        "gap_insurance": l["gap_insurance"],
        "adjusted_cap_cost_cents": l["adjusted_cap_cost_cents"],
        "base_monthly_cents": l["base_monthly_cents"],
        "monthly_payment_cents": l["monthly_payment_cents"],
        "odometer_miles": l["odometer_miles"],
        "status": l["status"],
        "created_at": l["created_at"],
        "updated_at": l["updated_at"],
        "version": l["version"],
    }


def ser_payment(p):
    return {
        "id": p["id"],
        "loan_id": p["loan_id"],
        "amount_cents": p["amount_cents"],
        "kind": p["kind"],
        "status": p["status"],
        "late_fee_cents": p["late_fee_cents"],
        "created_at": p["created_at"],
    }


def ser_settlement(s):
    return {
        "id": s["id"],
        "lease_id": s["lease_id"],
        "election": s["election"],
        "odometer_miles": s["odometer_miles"],
        "per_year_excess_miles": s["per_year_excess_miles"],
        "renew_term_months": s["renew_term_months"],
        "mileage_overage_cents": s["mileage_overage_cents"],
        "disposition_charge_cents": s["disposition_charge_cents"],
        "purchase_amount_cents": s["purchase_amount_cents"],
        "total_due_cents": s["total_due_cents"],
        "renewed_lease_id": s["renewed_lease_id"],
        "status": s["status"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


# ──────────────────────────────────────────────────────────────────────────
# Customer endpoints
# ──────────────────────────────────────────────────────────────────────────
@app.route("/customers", methods=["POST"])
def create_customer():
    _, role = get_auth()
    require_role(role, {"FinanceManager"})
    body = get_body()
    require_fields(body, ["full_name", "email", "fico_score"])
    full_name = require_str(body, "full_name")
    email = require_str(body, "email")
    fico = require_int(body, "fico_score")
    if fico < 300 or fico > 850:
        raise err("ERR_INVALID_REQUEST", "fico_score must be between 300 and 850.")
    # uniqueness
    for c in db.customers.values():
        if c["email"] == email:
            raise err("ERR_DUPLICATE_RESOURCE", "Email already in use.")
    rec = init_common({"full_name": full_name, "email": email, "fico_score": fico})
    db.customers[rec["id"]] = rec
    return success(ser_customer(rec), 201)


@app.route("/customers/<cid>", methods=["GET"])
def get_customer(cid):
    _, role = get_auth()
    require_role(role, {"FinanceManager", "Borrower", "Auditor"})
    c = db.customers.get(cid)
    if not c:
        raise err("ERR_NOT_FOUND", "Customer not found.")
    return success(ser_customer(c), 200)


@app.route("/customers", methods=["GET"])
def list_customers():
    _, role = get_auth()
    require_role(role, {"FinanceManager", "Auditor"})
    limit, offset = parse_pagination()
    items = sort_by_created(list(db.customers.values()))
    page, meta = paginate(items, limit, offset)
    return success([ser_customer(c) for c in page], 200, pagination=meta)


@app.route("/customers/<cid>/loans", methods=["GET"])
def list_customer_loans(cid):
    _, role = get_auth()
    require_role(role, {"FinanceManager", "Borrower", "Auditor"})
    if cid not in db.customers:
        raise err("ERR_NOT_FOUND", "Customer not found.")
    limit, offset = parse_pagination()
    items = sort_by_created([l for l in db.loans.values() if l["customer_id"] == cid])
    page, meta = paginate(items, limit, offset)
    return success([ser_loan(l) for l in page], 200, pagination=meta)


@app.route("/customers/<cid>/leases", methods=["GET"])
def list_customer_leases(cid):
    _, role = get_auth()
    require_role(role, {"FinanceManager", "Borrower", "Auditor"})
    if cid not in db.customers:
        raise err("ERR_NOT_FOUND", "Customer not found.")
    limit, offset = parse_pagination()
    items = sort_by_created([l for l in db.leases.values() if l["customer_id"] == cid])
    page, meta = paginate(items, limit, offset)
    return success([ser_lease(l) for l in page], 200, pagination=meta)


# ──────────────────────────────────────────────────────────────────────────
# Vehicle endpoints
# ──────────────────────────────────────────────────────────────────────────
@app.route("/vehicles", methods=["POST"])
def create_vehicle():
    _, role = get_auth()
    require_role(role, {"FinanceManager"})
    body = get_body()
    require_fields(body, ["vin", "make_model", "msrp_cents", "sale_price_cents",
                          "residual_value_cents"])
    vin = require_str(body, "vin")
    make_model = require_str(body, "make_model")
    msrp = require_int(body, "msrp_cents", non_negative=True)
    sale = require_int(body, "sale_price_cents", non_negative=True)
    residual = require_int(body, "residual_value_cents", non_negative=True)
    for v in db.vehicles.values():
        if v["vin"] == vin:
            raise err("ERR_DUPLICATE_RESOURCE", "VIN already in use.")
    rec = init_common({
        "vin": vin, "make_model": make_model, "msrp_cents": msrp,
        "sale_price_cents": sale, "residual_value_cents": residual,
        "status": "AVAILABLE",
    })
    db.vehicles[rec["id"]] = rec
    return success(ser_vehicle(rec), 201)


@app.route("/vehicles/<vid>", methods=["GET"])
def get_vehicle(vid):
    _, role = get_auth()
    require_role(role, {"FinanceManager", "Borrower", "Auditor"})
    v = db.vehicles.get(vid)
    if not v:
        raise err("ERR_NOT_FOUND", "Vehicle not found.")
    return success(ser_vehicle(v), 200)


@app.route("/vehicles", methods=["GET"])
def list_vehicles():
    _, role = get_auth()
    require_role(role, {"FinanceManager", "Auditor"})
    limit, offset = parse_pagination()
    status = request.args.get("status")
    items = list(db.vehicles.values())
    if status is not None:
        items = [v for v in items if v["status"] == status]
    items = sort_by_created(items)
    page, meta = paginate(items, limit, offset)
    return success([ser_vehicle(v) for v in page], 200, pagination=meta)


# ──────────────────────────────────────────────────────────────────────────
# RateCard endpoints
# ──────────────────────────────────────────────────────────────────────────
@app.route("/rate-cards", methods=["POST"])
def create_rate_card():
    _, role = get_auth()
    require_role(role, {"FinanceManager"})
    body = get_body()
    req = ["name", "tier_1_min_fico", "tier_2_min_fico", "tier_3_min_fico",
           "tier_1_apr", "tier_2_apr", "tier_3_apr", "tier_4_apr",
           "lease_money_factor", "default_rate_apr", "lease_tax_rate"]
    require_fields(body, req)
    name = require_str(body, "name")
    t1 = require_int(body, "tier_1_min_fico")
    t2 = require_int(body, "tier_2_min_fico")
    t3 = require_int(body, "tier_3_min_fico")
    rec = init_common({
        "name": name,
        "tier_1_min_fico": t1,
        "tier_2_min_fico": t2,
        "tier_3_min_fico": t3,
        "tier_1_apr": require_number(body, "tier_1_apr"),
        "tier_2_apr": require_number(body, "tier_2_apr"),
        "tier_3_apr": require_number(body, "tier_3_apr"),
        "tier_4_apr": require_number(body, "tier_4_apr"),
        "lease_money_factor": require_number(body, "lease_money_factor"),
        "default_rate_apr": require_number(body, "default_rate_apr"),
        "lease_tax_rate": require_number(body, "lease_tax_rate"),
        "active": False,
    })
    db.rate_cards[rec["id"]] = rec
    return success(ser_rate_card(rec), 201)


@app.route("/rate-cards/<rid>/activate", methods=["POST"])
def activate_rate_card(rid):
    _, role = get_auth()
    require_role(role, {"FinanceManager"})
    rc = db.rate_cards.get(rid)
    if not rc:
        raise err("ERR_NOT_FOUND", "Rate card not found.")
    # deactivate previously active card(s)
    for other in db.rate_cards.values():
        if other["id"] != rid and other["active"]:
            other["active"] = False
            touch(other)
    if not rc["active"]:
        rc["active"] = True
        touch(rc)
    return success(ser_rate_card(rc), 200)


@app.route("/rate-cards/<rid>", methods=["GET"])
def get_rate_card(rid):
    _, role = get_auth()
    require_role(role, {"FinanceManager", "Auditor"})
    rc = db.rate_cards.get(rid)
    if not rc:
        raise err("ERR_NOT_FOUND", "Rate card not found.")
    return success(ser_rate_card(rc), 200)


@app.route("/rate-cards", methods=["GET"])
def list_rate_cards():
    _, role = get_auth()
    require_role(role, {"FinanceManager", "Auditor"})
    limit, offset = parse_pagination()
    active_filter = request.args.get("active")
    items = list(db.rate_cards.values())
    if active_filter is not None:
        want = active_filter.lower() == "true"
        items = [r for r in items if r["active"] == want]
    items = sort_by_created(items)
    page, meta = paginate(items, limit, offset)
    return success([ser_rate_card(r) for r in page], 200, pagination=meta)


# ──────────────────────────────────────────────────────────────────────────
# Loan endpoints
# ──────────────────────────────────────────────────────────────────────────
@app.route("/loans", methods=["POST"])
def create_loan():
    _, role = get_auth()
    require_role(role, {"FinanceManager"})
    body = get_body()
    require_fields(body, ["customer_id", "vehicle_id", "down_payment_cents",
                          "term_months"])
    customer_id = require_str(body, "customer_id")
    vehicle_id = require_str(body, "vehicle_id")
    # existence: left-to-right (Customer, Vehicle)
    customer = db.customers.get(customer_id)
    if not customer:
        raise err("ERR_NOT_FOUND", "Customer not found.")
    vehicle = db.vehicles.get(vehicle_id)
    if not vehicle:
        raise err("ERR_NOT_FOUND", "Vehicle not found.")
    down = require_int(body, "down_payment_cents", non_negative=True)
    term = require_int(body, "term_months", non_negative=True)
    if term <= 0:
        raise err("ERR_INVALID_REQUEST", "term_months must be positive.")
    gap = require_bool_optional(body, "gap_insurance", False)
    # business: active rate card
    rc = active_rate_card()
    if not rc:
        raise err("ERR_NO_ACTIVE_RATE_CARD", "No active rate card.")
    # business: vehicle availability
    if vehicle["status"] != "AVAILABLE":
        raise err("ERR_VEHICLE_UNAVAILABLE", "Vehicle is not available.")

    tier = calc.fico_tier(customer["fico_score"], rc)
    apr = calc.apr_for_tier(tier, rc)
    financed = vehicle["sale_price_cents"] - down
    monthly = calc.loan_monthly_payment(financed, apr, term)

    rec = init_common({
        "customer_id": customer_id,
        "vehicle_id": vehicle_id,
        "rate_card_id": rc["id"],
        "down_payment_cents": down,
        "term_months": term,
        "gap_insurance": gap,
        "financed_principal_cents": financed,
        "apr": apr,
        "monthly_payment_cents": monthly,
        "payments_made_count": 0,
        "principal_balance_cents": financed,
        "missed_payment_count": 0,
        "status": "CURRENT",
    })
    db.loans[rec["id"]] = rec
    # cascade: vehicle -> FINANCED
    vehicle["status"] = "FINANCED"
    touch(vehicle)
    return success(ser_loan(rec), 201)


@app.route("/loans", methods=["GET"])
def list_loans():
    _, role = get_auth()
    require_role(role, {"FinanceManager", "Auditor"})
    limit, offset = parse_pagination()
    items = list(db.loans.values())
    for f in ("customer_id", "vehicle_id", "rate_card_id"):
        val = request.args.get(f)
        if val is not None:
            items = [l for l in items if l[f] == val]
    items = sort_by_created(items)
    page, meta = paginate(items, limit, offset)
    return success([ser_loan(l) for l in page], 200, pagination=meta)


@app.route("/loans/<lid>", methods=["GET"])
def get_loan(lid):
    _, role = get_auth()
    require_role(role, {"FinanceManager", "Borrower", "Auditor"})
    l = db.loans.get(lid)
    if not l:
        raise err("ERR_NOT_FOUND", "Loan not found.")
    return success(ser_loan(l), 200)


@app.route("/loans/<lid>/payoff-quote", methods=["GET"])
def loan_payoff_quote(lid):
    _, role = get_auth()
    require_role(role, {"FinanceManager", "Borrower", "Auditor"})
    l = db.loans.get(lid)
    if not l:
        raise err("ERR_NOT_FOUND", "Loan not found.")
    actuarial, gross, unearned = calc.loan_payoff_quotes(
        l["financed_principal_cents"], l["apr"], l["monthly_payment_cents"],
        l["term_months"], l["payments_made_count"])
    return success({
        "actuarial_payoff_cents": actuarial,
        "gross_payoff_cents": gross,
        "unearned_interest_cents": unearned,
        "loan_version": l["version"],
    }, 200)


@app.route("/loans/<lid>/payments", methods=["GET"])
def list_loan_payments(lid):
    _, role = get_auth()
    require_role(role, {"FinanceManager", "Borrower", "Auditor"})
    if lid not in db.loans:
        raise err("ERR_NOT_FOUND", "Loan not found.")
    limit, offset = parse_pagination()
    items = sort_by_created([p for p in db.payments.values() if p["loan_id"] == lid])
    page, meta = paginate(items, limit, offset)
    return success([ser_payment(p) for p in page], 200, pagination=meta)


@app.route("/loans/<lid>/payments", methods=["POST"])
def record_payment(lid):
    user_id, role = get_auth()
    require_role(role, {"Borrower"})
    l = db.loans.get(lid)
    if not l:
        raise err("ERR_NOT_FOUND", "Loan not found.")
    # ownership
    if l["customer_id"] != user_id:
        raise err("ERR_FORBIDDEN", "Borrower does not own this loan.")
    body = get_body()
    require_fields(body, ["amount_cents", "kind"])
    amount = require_int(body, "amount_cents", non_negative=True)
    kind = require_str(body, "kind")
    if kind not in ("SCHEDULED", "LATE_FEE", "PAYOFF"):
        raise err("ERR_INVALID_REQUEST", "Invalid kind.")
    # state
    if l["status"] not in ("CURRENT", "DELINQUENT"):
        raise err("ERR_LOAN_NOT_PAYABLE", "Loan is not payable.")
    # term complete
    if l["payments_made_count"] >= l["term_months"]:
        raise err("ERR_LOAN_TERM_COMPLETE", "Loan term complete.")
    # amount agreement
    if amount != l["monthly_payment_cents"]:
        raise err("ERR_PAYMENT_AMOUNT_MISMATCH", "Amount does not match monthly payment.")

    was_delinquent = l["status"] == "DELINQUENT"
    late_fee = calc.loan_late_fee(l["monthly_payment_cents"]) if was_delinquent else 0

    p = init_common({
        "loan_id": lid,
        "amount_cents": amount,
        "kind": "SCHEDULED",
        "status": "POSTED",
        "late_fee_cents": late_fee,
    })
    # Payment is append-only: only id + created_at
    db.payments[p["id"]] = p

    l["payments_made_count"] += 1
    if was_delinquent:
        l["status"] = "CURRENT"
        l["missed_payment_count"] = 0
    calc_recompute(l)
    touch(l)
    return success(ser_payment(p), 201)


def calc_recompute(loan):
    loan["principal_balance_cents"] = calc.loan_principal_balance(
        loan["financed_principal_cents"], loan["apr"],
        loan["monthly_payment_cents"], loan["payments_made_count"])


@app.route("/loans/<lid>/miss-payment", methods=["POST"])
def miss_payment(lid):
    _, role = get_auth()
    require_role(role, {"FinanceManager"})
    l = db.loans.get(lid)
    if not l:
        raise err("ERR_NOT_FOUND", "Loan not found.")
    if l["status"] not in ("CURRENT", "DELINQUENT"):
        raise err("ERR_LOAN_NOT_PAYABLE", "Loan is not in a missable state.")
    if l["status"] == "DELINQUENT" and l["missed_payment_count"] >= calc.DEFAULT_THRESHOLD:
        raise err("ERR_LOAN_NOT_PAYABLE", "Loan already eligible for default.")
    p = init_common({
        "loan_id": lid,
        "amount_cents": 0,
        "kind": "SCHEDULED",
        "status": "MISSED",
        "late_fee_cents": 0,
    })
    db.payments[p["id"]] = p
    l["missed_payment_count"] += 1
    l["status"] = "DELINQUENT"
    touch(l)
    return success(ser_payment(p), 201)


@app.route("/loans/<lid>/default", methods=["POST"])
def declare_default(lid):
    _, role = get_auth()
    require_role(role, {"FinanceManager"})
    l = db.loans.get(lid)
    if not l:
        raise err("ERR_NOT_FOUND", "Loan not found.")
    body = get_body()
    require_fields(body, ["insurance_settlement_cents"])
    settlement = require_int(body, "insurance_settlement_cents", non_negative=True)
    if l["status"] != "DELINQUENT":
        raise err("ERR_LOAN_NOT_PAYABLE", "Default only from DELINQUENT.")
    if l["missed_payment_count"] < calc.DEFAULT_THRESHOLD:
        raise err("ERR_DEFAULT_THRESHOLD_NOT_MET", "Default threshold not met.")
    l["status"] = "DEFAULT"
    touch(l)
    vehicle = db.vehicles.get(l["vehicle_id"])
    if vehicle:
        vehicle["status"] = "AVAILABLE"
        touch(vehicle)
    return success(ser_loan(l), 200)


@app.route("/loans/<lid>/payoff", methods=["POST"])
def payoff_loan(lid):
    user_id, role = get_auth()
    require_role(role, {"Borrower"})
    l = db.loans.get(lid)
    if not l:
        raise err("ERR_NOT_FOUND", "Loan not found.")
    if l["customer_id"] != user_id:
        raise err("ERR_FORBIDDEN", "Borrower does not own this loan.")
    body = get_body()
    require_fields(body, ["amount_cents", "expected_loan_version"])
    amount = require_int(body, "amount_cents", non_negative=True)
    expected_version = require_int(body, "expected_loan_version")
    # state
    if l["status"] != "CURRENT":
        raise err("ERR_LOAN_NOT_PAYABLE", "Payoff only from CURRENT.")
    # OCC freshness
    if expected_version != l["version"]:
        raise err("ERR_STALE_VERSION", "Loan version is stale.")
    # actuarial quote
    actuarial, _, _ = calc.loan_payoff_quotes(
        l["financed_principal_cents"], l["apr"], l["monthly_payment_cents"],
        l["term_months"], l["payments_made_count"])
    if amount != actuarial:
        raise err("ERR_PAYOFF_AMOUNT_MISMATCH", "Amount does not match actuarial payoff.")
    p = init_common({
        "loan_id": lid,
        "amount_cents": amount,
        "kind": "PAYOFF",
        "status": "POSTED",
        "late_fee_cents": 0,
    })
    db.payments[p["id"]] = p
    l["principal_balance_cents"] = 0
    l["status"] = "PAID_OFF"
    touch(l)
    vehicle = db.vehicles.get(l["vehicle_id"])
    if vehicle:
        vehicle["status"] = "AVAILABLE"
        touch(vehicle)
    return success(ser_loan(l), 200)


# ──────────────────────────────────────────────────────────────────────────
# Lease endpoints
# ──────────────────────────────────────────────────────────────────────────
@app.route("/leases", methods=["POST"])
def create_lease():
    _, role = get_auth()
    require_role(role, {"FinanceManager"})
    body = get_body()
    require_fields(body, ["customer_id", "vehicle_id", "down_payment_cents",
                          "term_months", "annual_mileage_allowance",
                          "per_mile_overage_rate_cents", "disposition_fee_cents",
                          "purchase_option_fee_cents"])
    customer_id = require_str(body, "customer_id")
    vehicle_id = require_str(body, "vehicle_id")
    customer = db.customers.get(customer_id)
    if not customer:
        raise err("ERR_NOT_FOUND", "Customer not found.")
    vehicle = db.vehicles.get(vehicle_id)
    if not vehicle:
        raise err("ERR_NOT_FOUND", "Vehicle not found.")
    down = require_int(body, "down_payment_cents", non_negative=True)
    term = require_int(body, "term_months", non_negative=True)
    if term <= 0:
        raise err("ERR_INVALID_REQUEST", "term_months must be positive.")
    mileage_allowance = require_int(body, "annual_mileage_allowance", non_negative=True)
    overage_rate = require_number(body, "per_mile_overage_rate_cents")
    if overage_rate < 0:
        raise err("ERR_INVALID_REQUEST", "per_mile_overage_rate_cents must be non-negative.")
    disposition_fee = require_int(body, "disposition_fee_cents", non_negative=True)
    purchase_fee = require_int(body, "purchase_option_fee_cents", non_negative=True)
    gap = require_bool_optional(body, "gap_insurance", False)
    rc = active_rate_card()
    if not rc:
        raise err("ERR_NO_ACTIVE_RATE_CARD", "No active rate card.")
    if vehicle["status"] != "AVAILABLE":
        raise err("ERR_VEHICLE_UNAVAILABLE", "Vehicle is not available.")

    adjusted, base_monthly, monthly = calc.lease_monthly_payment(
        vehicle["sale_price_cents"], vehicle["residual_value_cents"], down,
        term, rc["lease_money_factor"], rc["lease_tax_rate"])

    rec = init_common({
        "customer_id": customer_id,
        "vehicle_id": vehicle_id,
        "rate_card_id": rc["id"],
        "down_payment_cents": down,
        "term_months": term,
        "annual_mileage_allowance": mileage_allowance,
        "per_mile_overage_rate_cents": overage_rate,
        "disposition_fee_cents": disposition_fee,
        "purchase_option_fee_cents": purchase_fee,
        "gap_insurance": gap,
        "adjusted_cap_cost_cents": adjusted,
        "base_monthly_cents": base_monthly,
        "monthly_payment_cents": monthly,
        "odometer_miles": 0,
        "status": "ACTIVE",
    })
    db.leases[rec["id"]] = rec
    vehicle["status"] = "FINANCED"
    touch(vehicle)
    return success(ser_lease(rec), 201)


@app.route("/leases", methods=["GET"])
def list_leases():
    _, role = get_auth()
    require_role(role, {"FinanceManager", "Auditor"})
    limit, offset = parse_pagination()
    items = list(db.leases.values())
    for f in ("customer_id", "vehicle_id", "rate_card_id"):
        val = request.args.get(f)
        if val is not None:
            items = [l for l in items if l[f] == val]
    items = sort_by_created(items)
    page, meta = paginate(items, limit, offset)
    return success([ser_lease(l) for l in page], 200, pagination=meta)


@app.route("/leases/<lid>", methods=["GET"])
def get_lease(lid):
    _, role = get_auth()
    require_role(role, {"FinanceManager", "Borrower", "Auditor"})
    l = db.leases.get(lid)
    if not l:
        raise err("ERR_NOT_FOUND", "Lease not found.")
    return success(ser_lease(l), 200)


@app.route("/leases/<lid>/mature", methods=["POST"])
def mature_lease(lid):
    _, role = get_auth()
    require_role(role, {"FinanceManager"})
    l = db.leases.get(lid)
    if not l:
        raise err("ERR_NOT_FOUND", "Lease not found.")
    if l["status"] != "ACTIVE":
        raise err("ERR_LEASE_NOT_MATURABLE", "Lease is not ACTIVE.")
    l["status"] = "MATURING"
    touch(l)
    return success(ser_lease(l), 200)


@app.route("/leases/<lid>/settlements", methods=["GET"])
def list_lease_settlements(lid):
    _, role = get_auth()
    require_role(role, {"FinanceManager", "Borrower", "Auditor"})
    if lid not in db.leases:
        raise err("ERR_NOT_FOUND", "Lease not found.")
    limit, offset = parse_pagination()
    items = sort_by_created([s for s in db.settlements.values() if s["lease_id"] == lid])
    page, meta = paginate(items, limit, offset)
    return success([ser_settlement(s) for s in page], 200, pagination=meta)


# ──────────────────────────────────────────────────────────────────────────
# LeaseEndSettlement endpoints
# ──────────────────────────────────────────────────────────────────────────
@app.route("/lease-end-settlements", methods=["POST"])
def create_settlement():
    user_id, role = get_auth()
    require_role(role, {"Borrower"})
    body = get_body()
    require_fields(body, ["lease_id", "election", "odometer_miles",
                          "expected_lease_version"])
    lease_id = require_str(body, "lease_id")
    lease = db.leases.get(lease_id)
    if not lease:
        raise err("ERR_NOT_FOUND", "Lease not found.")
    # ownership
    if lease["customer_id"] != user_id:
        raise err("ERR_FORBIDDEN", "Borrower does not own this lease.")
    election = require_str(body, "election")
    if election not in ("RETURN", "PURCHASE", "RENEW"):
        raise err("ERR_INVALID_REQUEST", "Invalid election.")
    odometer = require_int(body, "odometer_miles", non_negative=True)
    expected_version = require_int(body, "expected_lease_version")
    per_year = body.get("per_year_excess_miles")
    renew_term = body.get("renew_term_months")
    # well-formedness of optional typed fields
    if per_year is not None:
        if not isinstance(per_year, list) or any(
                isinstance(m, bool) or not isinstance(m, (int, float)) or m < 0
                for m in per_year):
            raise err("ERR_INVALID_REQUEST", "per_year_excess_miles must be a list of non-negative numbers.")
    if renew_term is not None and (isinstance(renew_term, bool) or not isinstance(renew_term, int)):
        raise err("ERR_INVALID_REQUEST", "renew_term_months must be an integer.")

    # state: must be MATURING
    if lease["status"] != "MATURING":
        raise err("ERR_LEASE_NOT_ELECTABLE", "Lease is not in MATURING.")
    # OCC freshness
    if expected_version != lease["version"]:
        raise err("ERR_STALE_VERSION", "Lease version is stale.")

    expected_years = lease["term_months"] // 12

    rec_fields = {
        "lease_id": lease_id,
        "election": election,
        "odometer_miles": odometer,
        "per_year_excess_miles": per_year,
        "renew_term_months": renew_term,
        "mileage_overage_cents": 0,
        "disposition_charge_cents": 0,
        "purchase_amount_cents": 0,
        "total_due_cents": 0,
        "renewed_lease_id": None,
        "status": "FINALIZED",
    }

    if election == "RETURN":
        if not isinstance(per_year, list) or len(per_year) != expected_years:
            raise err("ERR_MILEAGE_SCHEDULE_INVALID", "per_year_excess_miles wrong length.")
        overage = calc.lease_mileage_overage(per_year, lease["per_mile_overage_rate_cents"])
        rec_fields["mileage_overage_cents"] = overage
        rec_fields["disposition_charge_cents"] = lease["disposition_fee_cents"]
        rec_fields["total_due_cents"] = lease["disposition_fee_cents"] + overage
        # cascade
        lease["odometer_miles"] = odometer
        lease["status"] = "SETTLED"
        touch(lease)
        vehicle = db.vehicles.get(lease["vehicle_id"])
        if vehicle:
            vehicle["status"] = "AVAILABLE"
            touch(vehicle)

    elif election == "PURCHASE":
        vehicle = db.vehicles.get(lease["vehicle_id"])
        residual = vehicle["residual_value_cents"] if vehicle else 0
        purchase_amount = residual + lease["purchase_option_fee_cents"]
        rec_fields["purchase_amount_cents"] = purchase_amount
        rec_fields["total_due_cents"] = purchase_amount
        lease["status"] = "SETTLED"
        touch(lease)
        # vehicle stays FINANCED

    else:  # RENEW
        if renew_term is None or renew_term <= 0:
            raise err("ERR_RENEW_TERM_INVALID", "renew_term_months must be > 0.")
        rec_fields["total_due_cents"] = 0
        # mint new ACTIVE lease on same vehicle with cap cost = residual_value_cents
        vehicle = db.vehicles.get(lease["vehicle_id"])
        rc = db.rate_cards.get(lease["rate_card_id"])
        residual = vehicle["residual_value_cents"] if vehicle else 0
        # New lease cap cost set to residual: model down_payment 0, sale=residual.
        if vehicle and rc:
            adjusted, base_monthly, monthly = calc.lease_monthly_payment(
                residual, residual, 0, renew_term,
                rc["lease_money_factor"], rc["lease_tax_rate"])
        else:
            adjusted, base_monthly, monthly = residual, 0, 0
        new_lease = init_common({
            "customer_id": lease["customer_id"],
            "vehicle_id": lease["vehicle_id"],
            "rate_card_id": lease["rate_card_id"],
            "down_payment_cents": 0,
            "term_months": renew_term,
            "annual_mileage_allowance": lease["annual_mileage_allowance"],
            "per_mile_overage_rate_cents": lease["per_mile_overage_rate_cents"],
            "disposition_fee_cents": lease["disposition_fee_cents"],
            "purchase_option_fee_cents": lease["purchase_option_fee_cents"],
            "gap_insurance": lease["gap_insurance"],
            "adjusted_cap_cost_cents": adjusted,
            "base_monthly_cents": base_monthly,
            "monthly_payment_cents": monthly,
            "odometer_miles": 0,
            "status": "ACTIVE",
        })
        db.leases[new_lease["id"]] = new_lease
        rec_fields["renewed_lease_id"] = new_lease["id"]
        lease["status"] = "SETTLED"
        touch(lease)

    rec = init_common(rec_fields)
    db.settlements[rec["id"]] = rec
    return success(ser_settlement(rec), 201)


@app.route("/lease-end-settlements/<sid>", methods=["GET"])
def get_settlement(sid):
    _, role = get_auth()
    require_role(role, {"FinanceManager", "Borrower", "Auditor"})
    s = db.settlements.get(sid)
    if not s:
        raise err("ERR_NOT_FOUND", "Settlement not found.")
    return success(ser_settlement(s), 200)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
