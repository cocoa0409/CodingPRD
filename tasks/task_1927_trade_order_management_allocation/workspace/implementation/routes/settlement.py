"""Settlement instructions, fail escalation, fail monitor (PRD §3.9)."""
from datetime import timedelta

from flask import Blueprint, request

import audit
import db
import services as svc
from errors import raise_err
from middleware import (ALL_ROLES, body, paged, pagination, require_enum,
                        require_roles)
from response import ok_list, ok_object
from util import parse_date, public

bp = Blueprint("settlement", __name__)

FAIL_REASONS = ("BROKER_NON_DELIVERY", "CUSTODIAN_MISMATCH", "INSUFFICIENT_POSITION", "OTHER")


def _escalate_if_needed(instruction):
    """fail_count reaching the threshold suspends the allocation's account."""
    if instruction["fail_count"] < svc.FAIL_ESCALATION_THRESHOLD:
        return
    line = db.store["allocations"].get(instruction["allocation_id"])
    if line is None:
        return
    account = db.store["accounts"].get(line["account_id"])
    if account is None or account["status"] != "ACTIVE":
        return
    svc.suspend_account(account, automatic=True)


def _fail_instruction(instruction, reason, automatic):
    instruction["instruction_status"] = "FAILED"
    instruction["fail_reason"] = reason
    instruction["fail_count"] += 1
    svc.touch(instruction)
    detail = (f"instruction_status: INSTRUCTED -> FAILED; fail_reason: {reason}; "
              f"fail_count: {instruction['fail_count']}")
    if automatic:
        audit.record_system("SettlementInstruction", instruction["id"],
                            "INSTRUCTION_FAILED", detail + " (fail monitor)")
    else:
        audit.record_request("SettlementInstruction", instruction["id"],
                             "INSTRUCTION_FAILED", detail)
    _escalate_if_needed(instruction)


@bp.get("/trading/settlement-instructions/<instructionId>")
@require_roles(*ALL_ROLES)
def get_instruction(instructionId):
    return ok_object(public(svc.fetch("instructions", instructionId, "ERR_INSTRUCTION_NOT_FOUND")))


@bp.get("/trading/settlement-instructions")
@require_roles(*ALL_ROLES)
def list_instructions():
    limit, offset = pagination()
    items = sorted(db.store["instructions"].values(), key=lambda r: r["_seq"])
    allocation_id = request.args.get("allocation_id")
    status = request.args.get("status")
    if allocation_id is not None:
        items = [i for i in items if i["allocation_id"] == allocation_id]
    if status is not None:
        items = [i for i in items if i["instruction_status"] == status]
    page, total = paged(items, limit, offset)
    return ok_list([public(i) for i in page], total, limit, offset)


@bp.post("/trading/settlement-instructions/<instructionId>/instruct")
@require_roles("SettlementOps")
def instruct(instructionId):
    ins = svc.fetch("instructions", instructionId, "ERR_INSTRUCTION_NOT_FOUND")
    if ins["instruction_status"] != "PENDING":
        raise_err("ERR_INVALID_STATE",
                  f"Cannot instruct an instruction in {ins['instruction_status']}")
    ins["instruction_status"] = "INSTRUCTED"
    svc.touch(ins)
    audit.record_request("SettlementInstruction", ins["id"], "INSTRUCTION_INSTRUCTED",
                         "instruction_status: PENDING -> INSTRUCTED")
    return ok_object(public(ins))


@bp.post("/trading/settlement-instructions/<instructionId>/settle")
@require_roles("SettlementOps")
def settle(instructionId):
    ins = svc.fetch("instructions", instructionId, "ERR_INSTRUCTION_NOT_FOUND")
    if ins["instruction_status"] != "INSTRUCTED":
        raise_err("ERR_INVALID_STATE",
                  f"Cannot settle an instruction in {ins['instruction_status']}")
    ins["instruction_status"] = "SETTLED"
    svc.touch(ins)
    audit.record_request("SettlementInstruction", ins["id"], "INSTRUCTION_SETTLED",
                         "instruction_status: INSTRUCTED -> SETTLED")
    line = db.store["allocations"].get(ins["allocation_id"])
    if line is not None and line["status"] == "POSTED":
        line["status"] = "SETTLED"
        svc.touch(line)
        audit.record_system("Allocation", line["id"], "ALLOCATION_SETTLED",
                            "status: POSTED -> SETTLED")
        order = db.store["orders"].get(line["order_id"])
        if order is not None:
            svc.maybe_settle_order(order)
    return ok_object(public(ins))


@bp.post("/trading/settlement-instructions/<instructionId>/fail")
@require_roles("SettlementOps")
def fail(instructionId):
    b = body()
    reason = require_enum(b, "fail_reason", FAIL_REASONS)
    ins = svc.fetch("instructions", instructionId, "ERR_INSTRUCTION_NOT_FOUND")
    if ins["instruction_status"] != "INSTRUCTED":
        raise_err("ERR_INVALID_STATE",
                  f"Cannot fail an instruction in {ins['instruction_status']}")
    _fail_instruction(ins, reason, automatic=False)
    return ok_object(public(ins))


@bp.post("/trading/settlement-instructions/<instructionId>/repair")
@require_roles("SettlementOps")
def repair(instructionId):
    ins = svc.fetch("instructions", instructionId, "ERR_INSTRUCTION_NOT_FOUND")
    if ins["instruction_status"] != "FAILED":
        raise_err("ERR_INVALID_STATE",
                  f"Cannot repair an instruction in {ins['instruction_status']}")
    ins["instruction_status"] = "INSTRUCTED"
    svc.touch(ins)
    audit.record_request("SettlementInstruction", ins["id"], "INSTRUCTION_REPAIRED",
                         "instruction_status: FAILED -> INSTRUCTED; fail_count kept")
    return ok_object(public(ins))


@bp.post("/trading/settlement-instructions/run-fail-monitor")
@require_roles("SettlementOps")
def run_fail_monitor():
    today = db.clock_now().date()
    candidates = sorted((i for i in db.store["instructions"].values()
                         if i["instruction_status"] == "INSTRUCTED"),
                        key=lambda i: i["_seq"])
    failed_ids = []
    for ins in candidates:
        settle = parse_date(ins["settle_date"])
        # strictly greater: exactly settle_date + grace is NOT yet failed
        if today > settle + timedelta(days=svc.FAIL_GRACE_DAYS):
            _fail_instruction(ins, "OTHER", automatic=True)
            failed_ids.append(ins["id"])
    return ok_object({"checked_count": len(candidates),
                      "failed_count": len(failed_ids),
                      "failed_instruction_ids": failed_ids})
