"""Expense and ExpenseAllocation endpoints."""

from flask import request

import services as S
from db import store
from errors import (
    err_expense_locked,
    err_expense_not_posted,
    err_fund_exceeded,
    err_invalid_state,
    err_line_exceeded,
    err_overallocated,
    err_restriction,
    err_segregation,
    err_validation,
)
from middleware import ALLOC_READ_ROLES, ALL_READ_ROLES, actor, body, require_roles
from response import ok, paginate
from util import get_dt, get_int, get_str


def create_expense(grant_id):
    uid, role = actor()
    require_roles(role, {"GrantsOfficer"})
    grant = S.get_grant(grant_id)
    S.require_grant_active(grant)
    data = body()
    exp = S.stamp({
        "grant_id": grant_id,
        "expense_date": get_dt(data, "expense_date"),
        "vendor": get_str(data, "vendor"),
        "description": get_str(data, "description"),
        "amount_cents": get_int(data, "amount_cents", min_v=1),
        "status": "DRAFT",
        "unallocated_cents": 0,
        "created_by_user_id": uid,
        "posted_by_user_id": None,
    })
    exp["unallocated_cents"] = exp["amount_cents"]
    store["expenses"][exp["id"]] = exp
    return ok(S.ser_expense(exp), code=201)


def list_expenses(grant_id):
    _, role = actor()
    require_roles(role, ALL_READ_ROLES)
    S.get_grant(grant_id)
    items = S.grant_expenses(grant_id)
    status = request.args.get("status")
    if status is not None:
        items = [e for e in items if e["status"] == status]
    page, meta = paginate(items)
    return ok([S.ser_expense(e) for e in page], pagination=meta)


def get_expense(expense_id):
    _, role = actor()
    require_roles(role, ALL_READ_ROLES)
    return ok(S.ser_expense(S.get_expense(expense_id)))


def post_expense(expense_id):
    uid, role = actor()
    require_roles(role, {"FinanceManager"})
    exp = S.get_expense(expense_id)
    # Segregation of duties (priority 4) precedes state checks (priority 5).
    if uid == exp["created_by_user_id"]:
        raise err_segregation("Expense poster must differ from expense creator")
    grant = S.get_grant(exp["grant_id"])
    S.require_grant_active(grant)
    if exp["status"] != "DRAFT":
        raise err_invalid_state("Only a DRAFT expense can be posted")
    exp["status"] = "POSTED"
    exp["posted_by_user_id"] = uid
    S.touch(exp)
    return ok(S.ser_expense(exp))


def void_expense(expense_id):
    _, role = actor()
    require_roles(role, {"FinanceManager"})
    exp = S.get_expense(expense_id)
    if exp["status"] != "POSTED":
        raise err_invalid_state("Only a POSTED expense can be voided")
    grant = S.get_grant(exp["grant_id"])
    # Locked when an ACTIVE allocation's expense_date falls in a period whose
    # report is SUBMITTED / UNDER_REVIEW / ACCEPTED.
    active = [a for a in S.expense_allocations(expense_id) if a["status"] == "ACTIVE"]
    if active:
        for rep in S.grant_reports(exp["grant_id"]):
            if rep["status"] in ("SUBMITTED", "UNDER_REVIEW", "ACCEPTED") and S.period_contains(rep, exp["expense_date"]):
                raise err_expense_locked()
    for a in active:
        a["status"] = "VOIDED"
        S.touch(a)
        line = store["budget_lines"].get(a["budget_line_id"])
        if line is not None:
            line["expended_cents"] -= a["amount_cents"]
            S.touch(line)
        fund = store["funds"].get(a["fund_id"])
        if fund is not None:
            fund["expended_cents"] -= a["amount_cents"]
            S.touch(fund)
    exp["status"] = "VOIDED"
    S.recompute_expense_unallocated(exp)
    S.touch(exp)
    S.recompute_grant_total(grant)
    S.touch(grant)
    return ok(S.ser_expense(exp))


def create_allocation(expense_id):
    uid, role = actor()
    require_roles(role, {"GrantsOfficer"})
    exp = S.get_expense(expense_id)
    if exp["status"] != "POSTED":
        raise err_expense_not_posted()
    data = body()
    line_id = get_str(data, "budget_line_id")
    fund_id = get_str(data, "fund_id")
    amount = get_int(data, "amount_cents", min_v=1)
    line = store["budget_lines"].get(line_id)
    fund = store["funds"].get(fund_id)
    if line is None or fund is None:
        raise err_validation("budget_line_id and fund_id must reference existing resources")
    # Priority 6: restriction gate precedes the cross-grant check (priority 9).
    if fund["fund_type"] == "RESTRICTED" and fund["allowed_categories"]:
        if line["category"] not in fund["allowed_categories"]:
            raise err_restriction()
    if line["grant_id"] != exp["grant_id"] or fund["grant_id"] != exp["grant_id"]:
        raise err_validation("budget_line and fund must belong to the expense's grant")
    # Priority 10: fiscal caps.
    if amount > exp["unallocated_cents"]:
        raise err_overallocated()
    if line["expended_cents"] + amount > line["adjusted_cents"]:
        raise err_line_exceeded()
    if fund["expended_cents"] + amount > fund["allocated_cents"]:
        raise err_fund_exceeded()
    alloc = S.stamp({
        "expense_id": expense_id,
        "budget_line_id": line_id,
        "fund_id": fund_id,
        "amount_cents": amount,
        "status": "ACTIVE",
        "created_by_user_id": uid,
    })
    store["allocations"][alloc["id"]] = alloc
    line["expended_cents"] += amount
    S.touch(line)
    fund["expended_cents"] += amount
    S.touch(fund)
    S.recompute_expense_unallocated(exp)
    S.touch(exp)
    grant = S.get_grant(exp["grant_id"])
    S.recompute_grant_total(grant)
    S.touch(grant)
    return ok(S.ser_allocation(alloc), code=201)


def list_allocations():
    _, role = actor()
    require_roles(role, ALLOC_READ_ROLES)
    items = sorted(store["allocations"].values(), key=lambda e: e["_order"])
    for f in ("expense_id", "budget_line_id", "fund_id"):
        v = request.args.get(f)
        if v is not None:
            items = [a for a in items if a[f] == v]
    page, meta = paginate(items)
    return ok([S.ser_allocation(a) for a in page], pagination=meta)


def get_allocation(allocation_id):
    _, role = actor()
    require_roles(role, ALLOC_READ_ROLES)
    return ok(S.ser_allocation(S.get_allocation(allocation_id)))


def register(app):
    app.add_url_rule("/grants/<grant_id>/expenses", "expenses_create", create_expense, methods=["POST"])
    app.add_url_rule("/grants/<grant_id>/expenses", "expenses_list", list_expenses, methods=["GET"])
    app.add_url_rule("/expenses/<expense_id>", "expenses_get", get_expense, methods=["GET"])
    app.add_url_rule("/expenses/<expense_id>/post", "expenses_post", post_expense, methods=["POST"])
    app.add_url_rule("/expenses/<expense_id>/void", "expenses_void", void_expense, methods=["POST"])
    app.add_url_rule("/expenses/<expense_id>/allocations", "allocations_create", create_allocation, methods=["POST"])
    app.add_url_rule("/allocations", "allocations_list", list_allocations, methods=["GET"])
    app.add_url_rule("/allocations/<allocation_id>", "allocations_get", get_allocation, methods=["GET"])
