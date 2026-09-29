"""Transfer agent coordination: record dates, dividends and reversal (PRD §3.9)."""
from datetime import timedelta
from decimal import Decimal

from flask import Blueprint

import validation as V
from envelope import created, ok, ok_list, paginate
from errors import ApiError
from serializers import instruction_out
from store import (FUNDING_MODES, HOLDER_TYPES, INSTRUCTION_STATUSES,
                   INSTRUCTION_TYPES, MIN_PAYABLE_LAG_DAYS, REVERSAL_WINDOW_HOURS,
                   floor4, new_row, rhu, sorted_rows, store, touch)

bp = Blueprint("instructions", __name__)

DECISIONS = ["ACKNOWLEDGE", "REJECT"]
CYCLE_STATUSES = ("SUBMITTED", "ACKNOWLEDGED", "EXECUTED")


def _holders(company_id):
    """Issuer contacts that are holders of record with a strictly positive position."""
    return [c for c in sorted_rows(store.contacts)
            if c["company_id"] == company_id
            and c["contact_type"] in HOLDER_TYPES
            and c["shares_held"] > 0]


@bp.post("/transfer-agent-instructions")
def create_instruction():
    actor = V.authorize("IRAdmin", "TransferAgentLiaison")
    b = V.body()
    company_id = V.f_str(b, "company_id", required=True)
    instruction_type = V.f_enum(b, "instruction_type", INSTRUCTION_TYPES, required=True)
    is_dividend = instruction_type == "DIVIDEND_PAYMENT"
    record_date = V.f_dt(b, "record_date",
                         required=instruction_type in ("RECORD_DATE_SET", "DIVIDEND_PAYMENT"))
    payable_date = V.f_dt(b, "payable_date", required=is_dividend)
    declared_rate = V.f_num(b, "declared_rate_cents_per_share",
                            required=is_dividend, exclusive_min=0)
    funding_mode = V.f_enum(b, "funding_mode", FUNDING_MODES,
                            default="DECLARED_RATE" if is_dividend else None)
    notes = V.f_str(b, "notes", default=None)

    company = V.get_company(company_id)

    # 13 -- temporal validity, at UTC calendar-date granularity
    if record_date is not None and record_date.date() < store.now().date():
        raise ApiError("ERR_RECORD_DATE_IN_PAST",
                       "record_date may not fall before the current calendar date")
    if record_date is not None and payable_date is not None:
        if (payable_date.date() - record_date.date()).days < MIN_PAYABLE_LAG_DAYS:
            raise ApiError("ERR_PAYABLE_DATE_TOO_EARLY",
                           "payable_date must be at least %d days after record_date"
                           % MIN_PAYABLE_LAG_DAYS)

    # 14 -- the closed dividend cycle interval may not overlap another live cycle
    if is_dividend:
        for other in sorted_rows(store.instructions):
            if (other["company_id"] != company["id"]
                    or other["instruction_type"] != "DIVIDEND_PAYMENT"
                    or other["status"] not in CYCLE_STATUSES):
                continue
            if other["record_date"] is None or other["payable_date"] is None:
                continue
            if (record_date.date() <= other["payable_date"].date()
                    and other["record_date"].date() <= payable_date.date()):
                raise ApiError("ERR_DIVIDEND_CYCLE_OVERLAP",
                               "this dividend cycle overlaps an existing one")

    instruction = new_row({
        "company_id": company["id"],
        "instruction_type": instruction_type,
        "record_date": record_date,
        "payable_date": payable_date,
        "declared_rate_cents_per_share": declared_rate,
        "funding_mode": funding_mode,
        "notes": notes,
        "submitted_by_user_id": actor.user_id,
        "acknowledged_by_user_id": None,
        "executed_by_user_id": None,
        "snapshot_holder_count": None,
        "snapshot_shares_total": None,
        "payout_ledger": None,
        "total_payout_cents": None,
        "executed_at": None,
        "status": "SUBMITTED",
        "decision_reason": None,
    })
    store.instructions[instruction["id"]] = instruction
    return created(instruction_out(instruction))


@bp.get("/transfer-agent-instructions")
def list_instructions():
    V.authorize("IRAdmin", "DisclosureOfficer", "TransferAgentLiaison")
    limit, offset = V.q_pagination()
    company_id = V.q_str("company_id")
    instruction_type = V.q_enum("instruction_type", INSTRUCTION_TYPES)
    status = V.q_enum("status", INSTRUCTION_STATUSES)
    rows = sorted_rows(store.instructions)
    if company_id is not None:
        rows = [r for r in rows if r["company_id"] == company_id]
    if instruction_type is not None:
        rows = [r for r in rows if r["instruction_type"] == instruction_type]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, total = paginate(rows, limit, offset)
    return ok_list([instruction_out(r) for r in page], limit, offset, total)


@bp.get("/transfer-agent-instructions/<instruction_id>")
def read_instruction(instruction_id):
    V.authorize("IRAdmin", "DisclosureOfficer", "TransferAgentLiaison")
    return ok(instruction_out(V.get_instruction(instruction_id)))


@bp.post("/transfer-agent-instructions/<instruction_id>/acknowledge")
def acknowledge(instruction_id):
    actor = V.authorize("TransferAgentLiaison")
    b = V.body()
    decision = V.f_enum(b, "decision", DECISIONS, required=True)
    rejection_reason = V.f_str(b, "rejection_reason", default=None)
    if decision == "REJECT" and rejection_reason is None:
        V.bad("rejection_reason is required when rejecting an instruction")

    instruction = V.get_instruction(instruction_id)
    if instruction["status"] != "SUBMITTED":
        raise ApiError("ERR_INSTRUCTION_ALREADY_DECIDED",
                       "this instruction has already been decided")
    if actor.user_id == instruction["submitted_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "the submitter of an instruction may not decide it")

    instruction["acknowledged_by_user_id"] = actor.user_id
    if decision == "ACKNOWLEDGE":
        holders = _holders(instruction["company_id"])
        instruction["status"] = "ACKNOWLEDGED"
        instruction["snapshot_holder_count"] = len(holders)
        instruction["snapshot_shares_total"] = sum(h["shares_held"] for h in holders)
    else:
        instruction["status"] = "REJECTED"
        instruction["decision_reason"] = rejection_reason
    touch(instruction)
    return ok(instruction_out(instruction))


@bp.post("/transfer-agent-instructions/<instruction_id>/execute")
def execute(instruction_id):
    actor = V.authorize("TransferAgentLiaison")
    instruction = V.get_instruction(instruction_id)

    if instruction["status"] != "ACKNOWLEDGED":
        raise ApiError("ERR_INSTRUCTION_NOT_ACKNOWLEDGED",
                       "only an ACKNOWLEDGED instruction may be executed")
    if actor.user_id == instruction["submitted_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "the submitter of an instruction may not execute it")
    payable_date = instruction["payable_date"]
    if payable_date is not None and store.now().date() < payable_date.date():
        raise ApiError("ERR_PAYABLE_DATE_NOT_REACHED",
                       "the logical clock has not yet reached payable_date")
    if instruction["instruction_type"] != "DIVIDEND_PAYMENT":
        raise ApiError("ERR_INSTRUCTION_TYPE_NOT_PAYABLE",
                       "only a DIVIDEND_PAYMENT instruction has a payout step")

    company = store.companies.get(instruction["company_id"])
    reserve = company["dividend_reserve_cents"] if company is not None else 0

    if instruction["funding_mode"] == "RESERVE_CAPPED":
        snapshot_total = instruction["snapshot_shares_total"] or 0
        if snapshot_total > 0:
            rate = floor4(Decimal(reserve) / Decimal(snapshot_total))
        else:
            rate = Decimal(0)
    else:
        rate = instruction["declared_rate_cents_per_share"] or Decimal(0)

    ledger = []
    total = 0
    for holder in _holders(instruction["company_id"]):
        amount = int(rhu(Decimal(holder["shares_held"]) * rate, 0))
        ledger.append({
            "contact_id": holder["id"],
            "shares_held": holder["shares_held"],
            "amount_cents": amount,
        })
        total += amount

    if total > reserve:
        raise ApiError("ERR_DIVIDEND_RESERVE_INSUFFICIENT",
                       "the payout total exceeds the issuer's dividend reserve")

    instruction["payout_ledger"] = ledger
    instruction["total_payout_cents"] = total
    instruction["status"] = "EXECUTED"
    instruction["executed_by_user_id"] = actor.user_id
    instruction["executed_at"] = store.now()
    touch(instruction)

    if company is not None:
        company["dividend_reserve_cents"] = company["dividend_reserve_cents"] - total
        company["dividend_paid_cents"] = company["dividend_paid_cents"] + total
        touch(company)

    for row in ledger:
        contact = store.contacts.get(row["contact_id"])
        if contact is None:
            continue
        contact["dividend_received_cents"] = \
            contact["dividend_received_cents"] + row["amount_cents"]
        touch(contact)

    return ok(instruction_out(instruction))


@bp.post("/transfer-agent-instructions/<instruction_id>/reverse")
def reverse(instruction_id):
    V.authorize("TransferAgentLiaison")
    b = V.body()
    reason = V.f_str(b, "reason", required=True)

    instruction = V.get_instruction(instruction_id)
    if instruction["status"] != "EXECUTED":
        raise ApiError("ERR_INSTRUCTION_NOT_EXECUTED",
                       "only an EXECUTED instruction may be reversed")
    deadline = instruction["executed_at"] + timedelta(hours=REVERSAL_WINDOW_HOURS)
    if store.now() >= deadline:
        raise ApiError("ERR_REVERSAL_WINDOW_EXPIRED",
                       "the %d-hour reversal window has closed" % REVERSAL_WINDOW_HOURS)

    total = instruction["total_payout_cents"] or 0
    instruction["status"] = "REVERSED"
    instruction["decision_reason"] = reason
    touch(instruction)

    company = store.companies.get(instruction["company_id"])
    if company is not None:
        company["dividend_reserve_cents"] = company["dividend_reserve_cents"] + total
        company["dividend_paid_cents"] = company["dividend_paid_cents"] - total
        touch(company)

    for row in (instruction["payout_ledger"] or []):
        contact = store.contacts.get(row["contact_id"])
        if contact is None:
            continue
        contact["dividend_received_cents"] = \
            contact["dividend_received_cents"] - row["amount_cents"]
        touch(contact)

    return ok(instruction_out(instruction))
