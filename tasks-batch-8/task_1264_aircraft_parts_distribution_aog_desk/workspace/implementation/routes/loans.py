"""LoanAgreement endpoints: desk-direct create, list, get, return."""

from datetime import timedelta

from flask import Blueprint, request

from auth import require_roles, ALL_BUSINESS
from calc import loan_settlement
from db import store, clock
from errors import (ApiError, ERR_INVALID_REQUEST, ERR_INVALID_STATE,
                    ERR_CUSTOMER_NOT_FOUND, ERR_UNIT_NOT_FOUND,
                    ERR_LOAN_NOT_FOUND, ERR_CUSTOMER_SUSPENDED,
                    ERR_UNIT_NOT_AVAILABLE, ERR_LOAN_WINDOW_OVERLAP,
                    ERR_LOAN_WINDOW_IN_PAST)
from helpers import (new_record, touch, get_or_404, bump_unit_status,
                     post_ledger, ser_loan, sort_asc, maybe_close_order)
from util import (success, get_body, page_params, paged, req_present, as_str,
                  as_int, as_enum, as_dt, fmt_dt, bad)

bp = Blueprint("loans", __name__)


@bp.post("/aog/loans")
def create_loan():
    require_roles("AogDeskAgent")
    body = get_body()
    customer_id = as_str(req_present(body, "customer_id"), "customer_id")
    unit_id = as_str(req_present(body, "unit_id"), "unit_id")
    loan_type = as_enum(req_present(body, "loan_type"), "loan_type",
                        {"LOAN", "LEASE"})
    rate = as_int(req_present(body, "daily_rate_cents"), "daily_rate_cents")
    if rate <= 0:
        bad("daily_rate_cents must be > 0")
    lease_periods = body.get("lease_periods")
    if loan_type == "LEASE":
        lease_periods = as_int(req_present(body, "lease_periods"),
                               "lease_periods")
        if lease_periods < 1:
            bad("lease_periods must be >= 1")
    elif lease_periods is not None:
        bad("lease_periods is forbidden for LOAN")
    start_raw = req_present(body, "start_at")
    due_raw = req_present(body, "due_at")
    start_dt = as_dt(start_raw, "start_at")
    due_dt = as_dt(due_raw, "due_at")
    customer = get_or_404("customers", customer_id, ERR_CUSTOMER_NOT_FOUND,
                          "Customer")
    unit = get_or_404("units", unit_id, ERR_UNIT_NOT_FOUND, "InventoryUnit")
    # state gate
    if customer["status"] != "ACTIVE":
        raise ApiError(ERR_CUSTOMER_SUSPENDED, 409, "Customer is suspended")
    # temporal window rules
    if start_dt < clock.current:
        raise ApiError(ERR_LOAN_WINDOW_IN_PAST, 422,
                       "start_at must not be in the past")
    if due_dt <= start_dt:
        raise ApiError(ERR_LOAN_WINDOW_IN_PAST, 422,
                       "due_at must be strictly after start_at")
    if loan_type == "LEASE" and \
            due_dt != start_dt + timedelta(days=30 * lease_periods):
        raise ApiError(ERR_LOAN_WINDOW_IN_PAST, 422,
                       "LEASE due_at must equal start_at + lease_periods * "
                       "30 days")
    part = store["parts"].get(unit["part_id"])
    if part is not None and not part["rotable"]:
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "Only rotable units may be loaned or leased")
    # constraints
    if unit["status"] in ("SOLD", "SCRAPPED", "QUARANTINED"):
        raise ApiError(ERR_UNIT_NOT_AVAILABLE, 409,
                       "Unit is not available for lending")
    for other in store["loans"].values():
        if other["unit_id"] != unit["id"]:
            continue
        if other["status"] not in ("ACTIVE", "OVERDUE"):
            continue
        # half-open window intersection: touching endpoints allowed
        if other["_start_dt"] < due_dt and start_dt < other["_due_dt"]:
            raise ApiError(ERR_LOAN_WINDOW_OVERLAP, 409,
                           "Loan window overlaps an existing loan of the "
                           "unit")
    rec = new_record("loans", {
        "customer_id": customer["id"],
        "unit_id": unit["id"],
        "order_line_id": None,
        "loan_type": loan_type,
        "daily_rate_cents": rate,
        "lease_periods": lease_periods if loan_type == "LEASE" else None,
        "start_at": start_raw,
        "due_at": due_raw,
        "returned_at": None,
        "billed_cents": 0,
        "status": "ACTIVE",
        "_start_dt": start_dt,
        "_due_dt": due_dt,
        "_returned_dt": None,
        "_periods_billed": 0,
    })
    if loan_type == "LEASE":
        post_ledger(customer["id"], "LEASE_DEBIT", 30 * rate,
                    "LOAN_AGREEMENT", rec["id"])
        rec["_periods_billed"] = 1
    return success(ser_loan(rec), 201)


@bp.get("/aog/loans")
def list_loans():
    uid, role = require_roles(*ALL_BUSINESS)
    limit, offset = page_params()
    recs = list(store["loans"].values())
    if role == "CustomerContact":
        recs = [l for l in recs if l["customer_id"] == uid]
    q = request.args
    if q.get("customer_id") is not None:
        recs = [l for l in recs if l["customer_id"] == q.get("customer_id")]
    if q.get("unit_id") is not None:
        recs = [l for l in recs if l["unit_id"] == q.get("unit_id")]
    if q.get("order_line_id") is not None:
        recs = [l for l in recs
                if l.get("order_line_id") == q.get("order_line_id")]
    if q.get("status") is not None:
        recs = [l for l in recs if l["status"] == q.get("status")]
    return paged([ser_loan(l) for l in sort_asc(recs)], limit, offset)


@bp.get("/aog/loans/<lid>")
def get_loan(lid):
    require_roles(*ALL_BUSINESS)
    rec = get_or_404("loans", lid, ERR_LOAN_NOT_FOUND, "LoanAgreement")
    return success(ser_loan(rec))


@bp.post("/aog/loans/<lid>/return")
def return_loan(lid):
    require_roles("WarehouseOperator")
    loan = get_or_404("loans", lid, ERR_LOAN_NOT_FOUND, "LoanAgreement")
    body = get_body()
    if "damage_flag" not in body or not isinstance(body["damage_flag"], bool):
        bad("damage_flag must be a boolean")
    damage = body["damage_flag"]
    if loan["status"] not in ("ACTIVE", "OVERDUE"):
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Only an ACTIVE or OVERDUE loan can be returned")
    now = clock.current
    billed = loan_settlement(loan, now)
    already = loan["_periods_billed"] * 30 * loan["daily_rate_cents"]
    remainder = billed - already
    if remainder > 0:
        entry_type = "LOAN_DEBIT" if loan["loan_type"] == "LOAN" \
            else "LEASE_DEBIT"
        post_ledger(loan["customer_id"], entry_type, remainder,
                    "LOAN_AGREEMENT", loan["id"])
    loan["billed_cents"] = billed
    loan["returned_at"] = fmt_dt(now)
    loan["_returned_dt"] = now
    unit = store["units"].get(loan["unit_id"])
    if not damage:
        loan["status"] = "RETURNED"
        touch(loan)
        if unit is not None and unit["status"] == "ON_LOAN":
            bump_unit_status(unit, "UNDER_INSPECTION")
            bump_unit_status(unit, "AVAILABLE")
        loan["status"] = "SETTLED"
        touch(loan)
    else:
        loan["status"] = "DAMAGE_REVIEW"
        touch(loan)
        if unit is not None and unit["status"] == "ON_LOAN":
            bump_unit_status(unit, "UNDER_INSPECTION")
            bump_unit_status(unit, "QUARANTINED")
    if loan.get("order_line_id"):
        line = store["order_lines"].get(loan["order_line_id"])
        order = store["orders"].get(line["order_id"]) if line else None
        if order is not None:
            maybe_close_order(order)
    return success(ser_loan(loan))
