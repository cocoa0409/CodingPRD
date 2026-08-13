"""Portfolios, case assignment, premium schedules and payments (PRD §3.6, §3.7)."""

from datetime import timedelta

from flask import Blueprint

import calc
from cascade import CASE_TERMINAL
from db import stamp, store, touch
from errors import (
    ApiError,
    ERR_ALREADY_TERMINAL,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE_TRANSITION,
    ERR_INVESTOR_NOT_ALLOCATED,
    ERR_NOT_FOUND,
    ERR_PAYMENT_AMOUNT_MISMATCH,
    ERR_POLICY_NOT_ACQUIRED,
    ERR_STALE_VERSION,
)
from middleware import (
    PORTFOLIO_READERS,
    READ_ALL,
    auth,
    get_body,
    lookup,
    opt,
    page_args,
    req,
    require_role,
    v_enum,
    v_int,
    v_str,
)
from response import ok, ok_list
from serialize import ser_case, ser_payment, ser_portfolio, ser_schedule

bp = Blueprint("portfolios", __name__)


def _sorted(items):
    return sorted(items, key=lambda e: (e["created_at"], e["_seq"]))


def _list(items, serializer):
    limit, offset = page_args()
    items = _sorted(items)
    page = items[offset : offset + limit]
    return ok_list([serializer(e) for e in page], len(items), limit, offset)


def _investor_allocated(uid, portfolio):
    if not any(a["investor_id"] == uid for a in portfolio["allocations"]):
        raise ApiError(ERR_INVESTOR_NOT_ALLOCATED, 403, "Investor holds no allocation in this portfolio")


# ---------------------------------------------------------------------------
# Portfolios
# ---------------------------------------------------------------------------


@bp.post("/api/portfolios")
def create_portfolio():
    uid, role = auth()
    require_role(role, ["PortfolioManager", "PlatformAdmin"])
    body = get_body()
    name = v_str(req(body, "name"), "name")
    method = v_enum(req(body, "valuation_method"), "valuation_method", ["PROSPECTIVE", "INVESTMENT"])
    discount = v_int(opt(body, "discount_rate_bps", 1200), "discount_rate_bps", min_v=1)
    allocations = opt(body, "allocations", [])
    if not isinstance(allocations, list):
        raise ApiError(ERR_INVALID_REQUEST, 400, "allocations must be an array")
    clean_allocations = []
    for entry in allocations:
        if not isinstance(entry, dict):
            raise ApiError(ERR_INVALID_REQUEST, 400, "allocation entries must be objects")
        investor_id = v_str(req(entry, "investor_id"), "investor_id")
        units = v_int(req(entry, "units"), "units", min_v=1)
        clean_allocations.append({"investor_id": investor_id, "units": units})
    for entry in clean_allocations:
        if entry["investor_id"] not in store.investors:
            raise ApiError(ERR_NOT_FOUND, 404, "Investor not found: %s" % entry["investor_id"])
    portfolio = {
        "name": name,
        "discount_rate_bps": discount,
        "valuation_method": method,
        "allocations": clean_allocations,
        "holding_count": 0,
        "invested_capital_cents": 0,
        "cached_nav_cents": None,
        "nav_stale": False,
    }
    stamp(portfolio)
    store.portfolios[portfolio["id"]] = portfolio
    return ok(ser_portfolio(portfolio), 201)


@bp.get("/api/portfolios")
def list_portfolios():
    uid, role = auth()
    require_role(role, PORTFOLIO_READERS)
    items = list(store.portfolios.values())
    if role == "Investor":
        items = [p for p in items if any(a["investor_id"] == uid for a in p["allocations"])]
    return _list(items, ser_portfolio)


@bp.get("/api/portfolios/<pid>")
def get_portfolio(pid):
    uid, role = auth()
    require_role(role, PORTFOLIO_READERS)
    portfolio = lookup(store.portfolios, pid, "Portfolio")
    if role == "Investor":
        _investor_allocated(uid, portfolio)
    return ok(ser_portfolio(portfolio))


@bp.get("/api/portfolios/<pid>/cases")
def portfolio_cases_endpoint(pid):
    uid, role = auth()
    require_role(role, READ_ALL)
    lookup(store.portfolios, pid, "Portfolio")
    return _list([c for c in store.cases.values() if c["portfolio_id"] == pid], ser_case)


# ---------------------------------------------------------------------------
# Case assignment
# ---------------------------------------------------------------------------


@bp.post("/api/cases/<cid>/assign-portfolio")
def assign_portfolio(cid):
    uid, role = auth()
    require_role(role, ["PortfolioManager"])
    body = get_body()
    portfolio_id = v_str(req(body, "portfolio_id"), "portfolio_id")
    case = lookup(store.cases, cid, "PolicyCase")
    portfolio = lookup(store.portfolios, portfolio_id, "Portfolio")
    if case["status"] in CASE_TERMINAL:
        raise ApiError(ERR_ALREADY_TERMINAL, 409, "Case is in terminal state %s" % case["status"])
    if case["status"] != "IN_CLOSING":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409, "Case is not IN_CLOSING")
    case["portfolio_id"] = portfolio["id"]
    touch(case)
    touch(portfolio)
    return ok(ser_case(case))


# ---------------------------------------------------------------------------
# Premium schedules and payments
# ---------------------------------------------------------------------------


@bp.post("/api/cases/<cid>/premium-schedules")
def create_premium_schedule(cid):
    uid, role = auth()
    require_role(role, ["PortfolioManager"])
    body = get_body()
    expected_version = v_int(req(body, "expected_case_version"), "expected_case_version")
    case = lookup(store.cases, cid, "PolicyCase")
    if case["status"] in CASE_TERMINAL:
        raise ApiError(ERR_ALREADY_TERMINAL, 409, "Case is in terminal state %s" % case["status"])
    if case["status"] != "ACQUIRED":
        raise ApiError(ERR_POLICY_NOT_ACQUIRED, 409, "Case is not ACQUIRED")
    if expected_version != case["version"]:
        raise ApiError(ERR_STALE_VERSION, 412, "Case version has advanced")
    policy = store.policies[case["policy_id"]]
    portfolio = store.portfolios[case["portfolio_id"]]
    plan = calc.premium_optimization(case, policy, portfolio)
    prior = calc.active_schedule(cid)
    if prior:
        prior["status"] = "SUPERSEDED"
        touch(prior)
    schedule = {
        "case_id": cid,
        "strategy": plan["strategy"],
        "optimized_monthly_premium_cents": plan["optimized_monthly_premium_cents"],
        "planned_months": plan["planned_months"],
        "reduced_face_cents": plan["reduced_face_cents"],
        "expected_net_value_cents": plan["expected_net_value_cents"],
        "missed_payment_count": 0,
        "total_paid_cents": 0,
        "status": "ACTIVE",
    }
    stamp(schedule)
    store.schedules[schedule["id"]] = schedule
    monthly = plan["optimized_monthly_premium_cents"]
    if monthly > 0:
        rows = min(plan["planned_months"], calc.PAYMENT_ROW_CAP)
        for idx in range(rows):
            due = store.clock + timedelta(days=calc.PREMIUM_DUE_STEP_DAYS * (idx + 1))
            payment = {
                "schedule_id": schedule["id"],
                "due_date": due,
                "amount_cents": monthly,
                "grace_deadline": due + timedelta(days=calc.PREMIUM_GRACE_DAYS),
                "status": "SCHEDULED",
                "paid_at": None,
            }
            stamp(payment)
            store.payments[payment["id"]] = payment
    touch(case)
    return ok(ser_schedule(schedule), 201)


@bp.get("/api/cases/<cid>/premium-schedules")
def list_schedules(cid):
    uid, role = auth()
    require_role(role, READ_ALL)
    lookup(store.cases, cid, "PolicyCase")
    return _list([s for s in store.schedules.values() if s["case_id"] == cid], ser_schedule)


@bp.get("/api/premium-schedules/<sid>")
def get_schedule(sid):
    uid, role = auth()
    require_role(role, READ_ALL)
    return ok(ser_schedule(lookup(store.schedules, sid, "PremiumSchedule")))


@bp.get("/api/premium-schedules/<sid>/payments")
def list_payments(sid):
    from flask import request

    uid, role = auth()
    require_role(role, READ_ALL)
    lookup(store.schedules, sid, "PremiumSchedule")
    items = [p for p in store.payments.values() if p["schedule_id"] == sid]
    status = request.args.get("status")
    if status is not None:
        items = [p for p in items if p["status"] == status]
    limit, offset = page_args()
    items.sort(key=lambda p: (p["due_date"], p["_seq"]))
    page = items[offset : offset + limit]
    return ok_list([ser_payment(p) for p in page], len(items), limit, offset)


@bp.get("/api/premium-payments/<pid>")
def get_payment(pid):
    uid, role = auth()
    require_role(role, READ_ALL)
    return ok(ser_payment(lookup(store.payments, pid, "PremiumPayment")))


@bp.post("/api/premium-payments/<pid>/pay")
def pay_premium(pid):
    uid, role = auth()
    require_role(role, ["FinanceOfficer"])
    body = get_body()
    amount = v_int(req(body, "amount_cents"), "amount_cents", min_v=1)
    payment = lookup(store.payments, pid, "PremiumPayment")
    if payment["status"] in ("PAID", "MISSED"):
        raise ApiError(ERR_ALREADY_TERMINAL, 409, "Payment is %s" % payment["status"])
    schedule = store.schedules[payment["schedule_id"]]
    if schedule["status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409, "Parent schedule is not ACTIVE")
    if amount != payment["amount_cents"]:
        raise ApiError(ERR_PAYMENT_AMOUNT_MISMATCH, 422, "Payment amount must equal the scheduled amount")
    payment["status"] = "PAID"
    payment["paid_at"] = store.clock
    touch(payment)
    schedule["total_paid_cents"] += amount
    touch(schedule)
    case = store.cases[schedule["case_id"]]
    pf = store.portfolios.get(case["portfolio_id"])
    if pf:
        pf["invested_capital_cents"] += amount
        pf["nav_stale"] = True
        touch(pf)
    return ok(ser_payment(payment))
