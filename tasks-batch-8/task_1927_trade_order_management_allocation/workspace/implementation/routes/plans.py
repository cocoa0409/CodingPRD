"""Allocation plans and allocation lines (PRD §3.7)."""
from flask import Blueprint, request

import audit
import db
import services as svc
from errors import raise_err
from middleware import (ALL_ROLES, body, paged, pagination, require_enum,
                        require_roles)
from response import ok_list, ok_object
from util import commission_cents, is_int, parse_dt, public, render_date, vwap_cents

bp = Blueprint("plans", __name__)

PLAN_METHODS = ("PRO_RATA", "EQUAL_SPLIT")
NONTERMINAL_PLAN_STATES = ("DRAFT", "PROPOSED", "APPROVED")


def _covered_fills(plan, block):
    return [f for f in svc.block_fills(block["id"])
            if plan["covered_from_seq"] < f["fill_seq"] <= plan["covered_to_seq"]]


def _plan_trade_date(plan, block):
    """Calendar date of the latest executed_at across the covered fills."""
    fills = _covered_fills(plan, block)
    latest = max(parse_dt(f["executed_at"]) for f in fills)
    return latest.date()


@bp.post("/trading/blocks/<blockId>/allocation-plans")
@require_roles("Trader")
def create_plan(blockId):
    b = body()
    method = require_enum(b, "method", PLAN_METHODS)
    expected = b.get("expected_block_version")
    if not is_int(expected):
        raise_err("ERR_INVALID_REQUEST", "Field 'expected_block_version' is required and must be an integer")
    block = svc.fetch("blocks", blockId, "ERR_BLOCK_NOT_FOUND")
    if block["status"] not in ("PARTIALLY_FILLED", "FILLED"):
        raise_err("ERR_INVALID_STATE",
                  f"Cannot create an allocation plan for a block in {block['status']}")
    if expected != block["version"]:
        raise_err("ERR_STALE_VERSION",
                  f"expected_block_version {expected} does not match block version {block['version']}")
    for plan in sorted(db.store["plans"].values(), key=lambda p: p["_seq"]):
        if plan["block_id"] == block["id"] and plan["status"] in NONTERMINAL_PLAN_STATES:
            frm = plan["status"]
            plan["status"] = "SUPERSEDED"
            svc.touch(plan)
            for line in [a for a in db.store["allocations"].values()
                         if a["plan_id"] == plan["id"] and a["status"] == "PROPOSED"]:
                del db.store["allocations"][line["id"]]
            audit.record_system("AllocationPlan", plan["id"], "PLAN_SUPERSEDED",
                                f"status: {frm} -> SUPERSEDED")
    from middleware import actor
    _, user_id = actor()
    rec = svc.new_record()
    rec.update({"block_id": block["id"], "method": method, "status": "DRAFT",
                "covered_from_seq": block["allocated_through_seq"],
                "covered_to_seq": None, "batch_qty": None,
                "batch_avg_price_cents": None, "max_deviation_bp": None,
                "created_by_user_id": user_id, "approved_by_user_id": None})
    db.store["plans"][rec["id"]] = rec
    svc.touch(block)
    return ok_object(public(rec), 201)


@bp.get("/trading/allocation-plans/<planId>")
@require_roles(*ALL_ROLES)
def get_plan(planId):
    return ok_object(public(svc.fetch("plans", planId, "ERR_PLAN_NOT_FOUND")))


@bp.get("/trading/blocks/<blockId>/allocation-plans")
@require_roles(*ALL_ROLES)
def list_block_plans(blockId):
    svc.fetch("blocks", blockId, "ERR_BLOCK_NOT_FOUND")
    limit, offset = pagination()
    items = sorted((p for p in db.store["plans"].values() if p["block_id"] == blockId),
                   key=lambda p: p["_seq"])
    page, total = paged(items, limit, offset)
    return ok_list([public(p) for p in page], total, limit, offset)


@bp.post("/trading/allocation-plans/<planId>/propose")
@require_roles("Trader")
def propose_plan(planId):
    plan = svc.fetch("plans", planId, "ERR_PLAN_NOT_FOUND")
    if plan["status"] != "DRAFT":
        raise_err("ERR_INVALID_STATE", f"Cannot propose a plan in {plan['status']}")
    block = db.store["blocks"][plan["block_id"]]
    members = svc.block_members(block["id"])
    if not members:
        raise_err("ERR_EMPTY_BLOCK", "Block has no member orders")
    uncovered = [f for f in svc.block_fills(block["id"])
                 if f["fill_seq"] > plan["covered_from_seq"]]
    if not uncovered:
        raise_err("ERR_NOTHING_TO_ALLOCATE", "No uncovered fills to allocate")
    plan["covered_to_seq"] = max(f["fill_seq"] for f in uncovered)
    batch = [f for f in uncovered if f["fill_seq"] <= plan["covered_to_seq"]]
    plan["batch_qty"] = sum(f["fill_qty"] for f in batch)
    plan["batch_avg_price_cents"] = vwap_cents(
        [(f["fill_qty"], f["fill_price_cents"]) for f in batch])
    alloc_qtys, max_dev = svc.allocation_split(plan["batch_qty"], plan["method"], members)
    for order, qty in zip(members, alloc_qtys):
        line = svc.new_record()
        line.update({"plan_id": plan["id"], "account_id": order["account_id"],
                     "order_id": order["id"], "alloc_qty": qty,
                     "alloc_price_cents": plan["batch_avg_price_cents"],
                     "commission_cents": None, "status": "PROPOSED",
                     "corrects_allocation_id": None})
        db.store["allocations"][line["id"]] = line
    plan["max_deviation_bp"] = max_dev
    plan["status"] = "PROPOSED"
    svc.touch(plan)
    audit.record_request("AllocationPlan", plan["id"], "PLAN_PROPOSED",
                         f"status: DRAFT -> PROPOSED; method: {plan['method']}; "
                         f"batch: ({plan['covered_from_seq']}, {plan['covered_to_seq']}]; "
                         f"batch_qty: {plan['batch_qty']}; "
                         f"batch_avg_price_cents: {plan['batch_avg_price_cents']}; "
                         f"max_deviation_bp: {max_dev}")
    return ok_object(public(plan))


@bp.post("/trading/allocation-plans/<planId>/approve")
@require_roles("ComplianceOfficer")
def approve_plan(planId):
    plan = svc.fetch("plans", planId, "ERR_PLAN_NOT_FOUND")
    from middleware import actor
    _, user_id = actor()
    # segregation of duties outranks the state check (validation priority 5 < 6)
    if user_id == plan["created_by_user_id"]:
        raise_err("ERR_SEGREGATION_OF_DUTIES",
                  "Plan approver must differ from plan creator")
    if plan["status"] != "PROPOSED":
        raise_err("ERR_INVALID_STATE", f"Cannot approve a plan in {plan['status']}")
    if plan["max_deviation_bp"] is not None and \
            plan["max_deviation_bp"] > svc.FAIRNESS_TOLERANCE_BP:
        raise_err("ERR_UNFAIR_ALLOCATION",
                  f"max_deviation_bp {plan['max_deviation_bp']} exceeds tolerance "
                  f"{svc.FAIRNESS_TOLERANCE_BP}")
    plan["approved_by_user_id"] = user_id
    plan["status"] = "APPROVED"
    svc.touch(plan)
    audit.record_request("AllocationPlan", plan["id"], "PLAN_APPROVED",
                         f"status: PROPOSED -> APPROVED; approved_by_user_id: {user_id}")
    return ok_object(public(plan))


@bp.post("/trading/allocation-plans/<planId>/return")
@require_roles("ComplianceOfficer")
def return_plan(planId):
    plan = svc.fetch("plans", planId, "ERR_PLAN_NOT_FOUND")
    if plan["status"] != "PROPOSED":
        raise_err("ERR_INVALID_STATE", f"Cannot return a plan in {plan['status']}")
    for line in [a for a in db.store["allocations"].values()
                 if a["plan_id"] == plan["id"] and a["status"] == "PROPOSED"]:
        del db.store["allocations"][line["id"]]
    plan["covered_to_seq"] = None
    plan["batch_qty"] = None
    plan["batch_avg_price_cents"] = None
    plan["max_deviation_bp"] = None
    plan["status"] = "DRAFT"
    svc.touch(plan)
    audit.record_request("AllocationPlan", plan["id"], "PLAN_RETURNED",
                         "status: PROPOSED -> DRAFT; proposed lines discarded")
    return ok_object(public(plan))


@bp.post("/trading/allocation-plans/<planId>/post")
@require_roles("Trader")
def post_plan(planId):
    plan = svc.fetch("plans", planId, "ERR_PLAN_NOT_FOUND")
    if plan["status"] != "APPROVED":
        raise_err("ERR_PLAN_NOT_POSTABLE", f"Cannot post a plan in {plan['status']}")
    block = db.store["blocks"][plan["block_id"]]
    lines = sorted((a for a in db.store["allocations"].values()
                    if a["plan_id"] == plan["id"] and a["status"] == "PROPOSED"),
                   key=lambda a: a["_seq"])
    accounts = {}
    for line in lines:
        acc = db.store["accounts"][line["account_id"]]
        if acc["status"] != "ACTIVE":
            raise_err("ERR_ACCOUNT_SUSPENDED",
                      f"Account {acc['account_code']} of an allocation line is not ACTIVE")
        accounts[acc["id"]] = acc
    max_seq = max((f["fill_seq"] for f in svc.block_fills(block["id"])), default=0)
    if max_seq > plan["covered_to_seq"] and block["status"] != "FILLED":
        raise_err("ERR_PLAN_STALE_BATCH",
                  "New fills arrived beyond the proposed batch; return and re-propose")
    trade_date = _plan_trade_date(plan, block)
    broker = db.store["brokers"][block["broker_id"]]
    for line in lines:  # pinned per-line rounding happens before any summation
        line["_new_commission"] = commission_cents(
            line["alloc_qty"], line["alloc_price_cents"], broker["commission_rate_bp"])
    per_account = {}
    for line in lines:
        per_account.setdefault(line["account_id"], 0)
        per_account[line["account_id"]] += line["_new_commission"]
    budgets = {}
    for account_id, amount in per_account.items():
        budget = svc.find_open_budget(account_id, trade_date)
        if budget is None:
            raise_err("ERR_NO_ACTIVE_BUDGET",
                      f"No OPEN commission budget covers trade_date {render_date(trade_date)} "
                      f"for account {account_id}")
        if budget["accrued_commission_cents"] + amount > budget["budget_amount_cents"]:
            raise_err("ERR_COMMISSION_BUDGET_EXCEEDED",
                      "Projected commission accrual exceeds budget_amount_cents")
        budgets[account_id] = budget
    # ---- all gates passed; mutate ----
    security = db.store["securities"][block["security_id"]]
    settle_date = svc.settle_dates_for(security, trade_date)
    for line in lines:
        line["commission_cents"] = line.pop("_new_commission")
        line["status"] = "POSTED"
        svc.touch(line)
    for account_id, amount in per_account.items():
        svc.budget_accrue(budgets[account_id], amount)
    for line in lines:
        svc.position_apply(line["account_id"], block["security_id"],
                           svc.signed_qty(block, line["alloc_qty"]))
    covered_orders = {}
    for line in lines:
        order = db.store["orders"][line["order_id"]]
        covered_orders[order["id"]] = order
    for order in sorted(covered_orders.values(), key=lambda o: o["_seq"]):
        was = order["status"]
        svc.recompute_order_stats(order)
        if was == "BLOCKED":
            order["status"] = "ALLOCATED"
            svc.touch(order)
            audit.record_system("Order", order["id"], "ORDER_ALLOCATED",
                                f"status: BLOCKED -> ALLOCATED; "
                                f"allocated_qty: {order['allocated_qty']}; "
                                f"avg_executed_price_cents: {order['avg_executed_price_cents']}")
        else:
            svc.touch(order)
    block["allocated_through_seq"] = plan["covered_to_seq"]
    block["allocation_status"] = "FULL" if block["allocated_through_seq"] == max_seq else "PARTIAL"
    svc.touch(block)
    for line in lines:
        svc.create_instruction(line, db.store["accounts"][line["account_id"]],
                               render_date(trade_date), render_date(settle_date))
    plan["status"] = "POSTED"
    svc.touch(plan)
    audit.record_request("AllocationPlan", plan["id"], "PLAN_POSTED",
                         f"status: APPROVED -> POSTED; lines posted: {len(lines)}; "
                         f"allocated_through_seq: {block['allocated_through_seq']}; "
                         f"allocation_status: {block['allocation_status']}")
    return ok_object(public(plan))


@bp.get("/trading/allocations/<allocationId>")
@require_roles(*ALL_ROLES)
def get_allocation(allocationId):
    return ok_object(public(svc.fetch("allocations", allocationId, "ERR_ALLOCATION_NOT_FOUND")))


@bp.get("/trading/allocations")
@require_roles(*ALL_ROLES)
def list_allocations():
    limit, offset = pagination()
    items = sorted(db.store["allocations"].values(), key=lambda r: r["_seq"])
    for param in ("plan_id", "account_id", "order_id", "corrects_allocation_id", "status"):
        v = request.args.get(param)
        if v is not None:
            items = [a for a in items if a[param] == v]
    page, total = paged(items, limit, offset)
    return ok_list([public(a) for a in page], total, limit, offset)
