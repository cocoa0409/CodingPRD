"""Trade errors: flagging, correction accounting, dismissal (PRD §3.8)."""
from flask import Blueprint, request

import audit
import db
import services as svc
from errors import raise_err
from middleware import (ALL_ROLES, body, paged, pagination, require_enum,
                        require_roles)
from response import ok_list, ok_object
from util import commission_cents, is_int, parse_date, public, render_date

bp = Blueprint("corrections", __name__)

ERROR_TYPES = ("WRONG_ACCOUNT", "WRONG_QTY", "WRONG_PRICE")


@bp.post("/trading/allocations/<allocationId>/flag-error")
@require_roles("SettlementOps", "ComplianceOfficer")
def flag_error(allocationId):
    b = body()
    error_type = require_enum(b, "error_type", ERROR_TYPES)
    note = b.get("note")
    if note is not None and not isinstance(note, str):
        raise_err("ERR_INVALID_REQUEST", "Field 'note' must be a string")
    line = svc.fetch("allocations", allocationId, "ERR_ALLOCATION_NOT_FOUND")
    if line["status"] != "POSTED":
        raise_err("ERR_INVALID_STATE", f"Cannot flag an allocation in {line['status']}")
    for e in db.store["trade_errors"].values():
        if e["allocation_id"] == line["id"] and e["status"] == "OPEN":
            raise_err("ERR_ERROR_ALREADY_OPEN", "Allocation already has an OPEN trade error")
    from middleware import actor
    _, user_id = actor()
    err = svc.new_record()
    err.update({"allocation_id": line["id"], "error_type": error_type,
                "note": note, "status": "OPEN", "flagged_by_user_id": user_id})
    db.store["trade_errors"][err["id"]] = err
    line["status"] = "ERROR_FLAGGED"
    svc.touch(line)
    order = db.store["orders"][line["order_id"]]
    if order["status"] == "ALLOCATED":
        order["status"] = "UNDER_CORRECTION"
        svc.touch(order)
        audit.record_system("Order", order["id"], "ORDER_UNDER_CORRECTION",
                            "status: ALLOCATED -> UNDER_CORRECTION")
    audit.record_request("TradeError", err["id"], "ERROR_FLAGGED",
                         f"allocation_id: {line['id']}; error_type: {error_type}; "
                         f"allocation status: POSTED -> ERROR_FLAGGED")
    return ok_object(public(err), 201)


@bp.get("/trading/trade-errors/<errorId>")
@require_roles(*ALL_ROLES)
def get_trade_error(errorId):
    return ok_object(public(svc.fetch("trade_errors", errorId, "ERR_TRADE_ERROR_NOT_FOUND")))


@bp.get("/trading/trade-errors")
@require_roles(*ALL_ROLES)
def list_trade_errors():
    limit, offset = pagination()
    items = sorted(db.store["trade_errors"].values(), key=lambda r: r["_seq"])
    allocation_id = request.args.get("allocation_id")
    status = request.args.get("status")
    if allocation_id is not None:
        items = [e for e in items if e["allocation_id"] == allocation_id]
    if status is not None:
        items = [e for e in items if e["status"] == status]
    page, total = paged(items, limit, offset)
    return ok_list([public(e) for e in page], total, limit, offset)


def _desk_error_account():
    candidates = [a for a in db.store["accounts"].values()
                  if a["account_type"] == "ERROR" and a["status"] == "ACTIVE"]
    if not candidates:
        raise_err("ERR_NO_ERROR_ACCOUNT", "No ACTIVE ERROR account exists to absorb the residual")
    return sorted(candidates, key=lambda a: a["_seq"])[0]


@bp.post("/trading/trade-errors/<errorId>/correct")
@require_roles("DeskAdmin")
def correct_trade_error(errorId):
    err = svc.fetch("trade_errors", errorId, "ERR_TRADE_ERROR_NOT_FOUND")
    b = body()
    error_type = err["error_type"]
    # conditional field requirements keyed off the stored error_type
    target_account_id = b.get("target_account_id")
    corrected_qty = b.get("corrected_qty")
    corrected_price = b.get("corrected_price_cents")
    if error_type == "WRONG_ACCOUNT":
        if not isinstance(target_account_id, str) or not target_account_id:
            raise_err("ERR_INVALID_REQUEST", "target_account_id is required for WRONG_ACCOUNT")
    elif error_type == "WRONG_QTY":
        if not is_int(corrected_qty):
            raise_err("ERR_INVALID_REQUEST", "corrected_qty is required for WRONG_QTY")
    elif error_type == "WRONG_PRICE":
        if not is_int(corrected_price) or corrected_price <= 0:
            raise_err("ERR_INVALID_REQUEST",
                      "corrected_price_cents is required and must be positive for WRONG_PRICE")
    orig = db.store["allocations"][err["allocation_id"]]
    target = None
    if error_type == "WRONG_ACCOUNT":
        target = svc.fetch("accounts", target_account_id, "ERR_ACCOUNT_NOT_FOUND")
        if target_account_id == orig["account_id"]:
            raise_err("ERR_INVALID_REQUEST", "target_account_id must differ from the original account")
    if err["status"] != "OPEN":
        raise_err("ERR_INVALID_STATE", f"Cannot correct a trade error in {err['status']}")
    instruction = svc.instruction_for_allocation(orig["id"])
    if instruction is not None and instruction["instruction_status"] == "SETTLED":
        raise_err("ERR_ALLOCATION_ALREADY_SETTLED",
                  "The original line's settlement instruction is already SETTLED")
    if error_type == "WRONG_ACCOUNT" and target["status"] != "ACTIVE":
        raise_err("ERR_ACCOUNT_SUSPENDED", "Target account is not ACTIVE")
    error_account = None
    if error_type == "WRONG_QTY":
        if corrected_qty <= 0 or corrected_qty >= orig["alloc_qty"]:
            raise_err("ERR_CORRECTION_QTY_EXCEEDS",
                      "corrected_qty must be > 0 and < original alloc_qty")
        error_account = _desk_error_account()

    # plan/block context for commission + instruction recomputation
    plan = db.store["plans"][orig["plan_id"]]
    block = db.store["blocks"][plan["block_id"]]
    broker = db.store["brokers"][block["broker_id"]]
    trade_date_raw = instruction["trade_date"]
    trade_date = parse_date(trade_date_raw)

    # build the correction line specs in creation order: primary first, residual second
    specs = []
    if error_type == "WRONG_ACCOUNT":
        specs.append({"account_id": target["id"], "alloc_qty": orig["alloc_qty"],
                      "alloc_price_cents": orig["alloc_price_cents"]})
    elif error_type == "WRONG_QTY":
        specs.append({"account_id": orig["account_id"], "alloc_qty": corrected_qty,
                      "alloc_price_cents": orig["alloc_price_cents"]})
        specs.append({"account_id": error_account["id"],
                      "alloc_qty": orig["alloc_qty"] - corrected_qty,
                      "alloc_price_cents": orig["alloc_price_cents"]})
    else:  # WRONG_PRICE
        specs.append({"account_id": orig["account_id"], "alloc_qty": orig["alloc_qty"],
                      "alloc_price_cents": corrected_price})
    for s in specs:
        s["commission_cents"] = commission_cents(
            s["alloc_qty"], s["alloc_price_cents"], broker["commission_rate_bp"])

    # referential + fiscal gates per receiving account, computed against the
    # post-correction accrual (original line's commission unwinds first)
    per_account = {}
    for s in specs:
        per_account.setdefault(s["account_id"], 0)
        per_account[s["account_id"]] += s["commission_cents"]
    budgets = {}
    for account_id, amount in per_account.items():
        budget = svc.find_open_budget(account_id, trade_date)
        if budget is None:
            raise_err("ERR_NO_ACTIVE_BUDGET",
                      f"No OPEN commission budget covers trade_date {trade_date_raw} "
                      f"for account {account_id}")
        projected = budget["accrued_commission_cents"] + amount
        if account_id == orig["account_id"]:
            projected -= (orig["commission_cents"] or 0)
        if projected > budget["budget_amount_cents"]:
            raise_err("ERR_COMMISSION_BUDGET_EXCEEDED",
                      "Recomputed commissions exceed budget_amount_cents")
        budgets[account_id] = budget

    # ---- all gates passed; mutate ----
    # 1. reverse the original line: position/budget unwind, instruction cancel
    orig["status"] = "REVERSED"
    svc.touch(orig)
    svc.position_apply(orig["account_id"], block["security_id"],
                       -svc.signed_qty(block, orig["alloc_qty"]))
    orig_budget = svc.find_covering_budget(orig["account_id"], trade_date)
    if orig_budget is not None and orig["commission_cents"]:
        orig_budget["accrued_commission_cents"] -= orig["commission_cents"]
        svc.touch(orig_budget)
    if instruction is not None and \
            instruction["instruction_status"] in ("PENDING", "INSTRUCTED", "FAILED"):
        frm = instruction["instruction_status"]
        instruction["instruction_status"] = "CANCELLED"
        svc.touch(instruction)
        audit.record_system("SettlementInstruction", instruction["id"],
                            "INSTRUCTION_CANCELLED",
                            f"instruction_status: {frm} -> CANCELLED (error correction)")
    # 2. correction lines POSTED in order, with accrual, positions, instructions
    security = db.store["securities"][block["security_id"]]
    settle_date = svc.settle_dates_for(security, trade_date)
    for s in specs:
        line = svc.new_record()
        line.update({"plan_id": orig["plan_id"], "account_id": s["account_id"],
                     "order_id": orig["order_id"], "alloc_qty": s["alloc_qty"],
                     "alloc_price_cents": s["alloc_price_cents"],
                     "commission_cents": s["commission_cents"], "status": "POSTED",
                     "corrects_allocation_id": orig["id"]})
        db.store["allocations"][line["id"]] = line
        svc.budget_accrue(budgets[s["account_id"]], s["commission_cents"])
        svc.position_apply(s["account_id"], block["security_id"],
                           svc.signed_qty(block, s["alloc_qty"]))
        svc.create_instruction(line, db.store["accounts"][s["account_id"]],
                               trade_date_raw, render_date(settle_date))
    # 3. order correction context
    order = db.store["orders"][orig["order_id"]]
    svc.clear_correction_context_if_done(order)
    err["status"] = "RESOLVED"
    svc.touch(err)
    audit.record_request("TradeError", err["id"], "ERROR_CORRECTED",
                         f"status: OPEN -> RESOLVED; allocation_id: {orig['id']}; "
                         f"original REVERSED; correction lines: {len(specs)}")
    return ok_object(public(err))


@bp.post("/trading/trade-errors/<errorId>/dismiss")
@require_roles("DeskAdmin")
def dismiss_trade_error(errorId):
    err = svc.fetch("trade_errors", errorId, "ERR_TRADE_ERROR_NOT_FOUND")
    if err["status"] != "OPEN":
        raise_err("ERR_INVALID_STATE", f"Cannot dismiss a trade error in {err['status']}")
    orig = db.store["allocations"][err["allocation_id"]]
    orig["status"] = "POSTED"  # compensation restores the line exactly
    svc.touch(orig)
    order = db.store["orders"][orig["order_id"]]
    svc.clear_correction_context_if_done(order)
    err["status"] = "DISMISSED"
    svc.touch(err)
    audit.record_request("TradeError", err["id"], "ERROR_DISMISSED",
                         f"status: OPEN -> DISMISSED; allocation_id: {orig['id']} "
                         f"restored to POSTED")
    return ok_object(public(err))
