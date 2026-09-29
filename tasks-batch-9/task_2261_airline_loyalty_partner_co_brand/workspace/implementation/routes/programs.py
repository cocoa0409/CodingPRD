"""Loyalty programmes, the accounting-period posture, and deferred revenue
postings (PRD 3.1 and 3.9)."""

from flask import Blueprint

import calc
import validators as v
from db import store
from errors import fail
from middleware import authenticate, body, page_params, qfilter
from response import created, ok, ok_list
from services.core import (base_row, dump, dump_all, find, finish_row, fk,
                           next_period, ordered, paginate, pdate, touch,
                           trailing_window)

bp = Blueprint("programs", __name__)

READ_ROLES = ("ProgramAdmin", "PartnerManager", "ContractsOfficer",
              "RevenueAccountant", "FraudAnalyst")
RECOGNITION_STATES = ("OPEN", "CLOSING", "LOCKED")


# --------------------------------------------------------------------------
# /loyalty-programs
# --------------------------------------------------------------------------


@bp.post("/loyalty-programs")
def create_program():
    authenticate(("ProgramAdmin",))
    data = body()
    name = v.req_str(data, "name", max_len=120)
    currency_code = v.opt_currency(data, "currency_code", "USD")
    current_period = v.opt_period(data, "current_period", "2026-08")
    policy = v.opt_enum(data, "breakage_policy_mode", calc.BREAKAGE_METHODS,
                        "HISTORICAL_ATTRITION")
    saver_share = v.opt_int(data, "saver_share_default_bps", 3000, minimum=0, maximum=10000)

    row = base_row()
    row["name"] = name
    row["currency_code"] = currency_code
    row["current_period"] = current_period
    row["breakage_policy_mode"] = policy
    row["saver_share_default_bps"] = saver_share
    row["revenue_recognition_state"] = "OPEN"
    row["outstanding_miles"] = 0
    row["deferred_revenue_cents"] = 0
    row["last_breakage_rate_bps"] = 0
    row["lifetime_breakage_income_cents"] = 0
    finish_row(row)
    store.programs[row["id"]] = row
    return created(dump(row))


@bp.get("/loyalty-programs")
def list_programs():
    authenticate(READ_ROLES)
    limit, offset = page_params()
    rows = ordered(store.programs)
    page, total = paginate(rows, limit, offset)
    return ok_list(dump_all(page), limit, offset, total)


@bp.get("/loyalty-programs/<program_id>")
def read_program(program_id):
    authenticate(READ_ROLES)
    program = find(store.programs, program_id, "ERR_PROGRAM_NOT_FOUND")
    return ok(dump(program))


@bp.post("/loyalty-programs/<program_id>/recognition-transitions")
def recognition_transition(program_id):
    authenticate(("RevenueAccountant",))
    program = find(store.programs, program_id, "ERR_PROGRAM_NOT_FOUND")
    data = body()
    target = v.req_enum(data, "target_state", RECOGNITION_STATES)
    current = program["revenue_recognition_state"]

    if current == "OPEN" and target == "CLOSING":
        pass
    elif current == "CLOSING" and target == "LOCKED":
        posted = any(p["program_id"] == program["id"]
                     and p["period"] == program["current_period"]
                     for p in store.postings.values())
        if not posted:
            fail("ERR_INVALID_STATE",
                 "the current period has no deferred revenue posting yet")
    elif current == "CLOSING" and target == "OPEN":
        pass
    elif current == "LOCKED" and target == "OPEN":
        program["current_period"] = next_period(program["current_period"])
    else:
        fail("ERR_INVALID_STATE",
             "cannot move revenue_recognition_state from %s to %s" % (current, target))

    program["revenue_recognition_state"] = target
    touch(program)
    return ok(dump(program))


# --------------------------------------------------------------------------
# /deferred-revenue-postings
# --------------------------------------------------------------------------


@bp.post("/deferred-revenue-postings")
def create_posting():
    authenticate(("RevenueAccountant",))
    data = body()
    program = fk(store.programs, data, "program_id", "ERR_PROGRAM_NOT_FOUND", required=True)

    period = v.req_period(data, "period")
    expected = v.req_int(data, "expected_program_version")
    method = v.opt_enum(data, "method", calc.BREAKAGE_METHODS)

    # Rung 8 -- a posting is permitted only once the period is being closed.
    # LOCKED is owned by rung 13, so only OPEN fails here.
    if program["revenue_recognition_state"] == "OPEN":
        fail("ERR_INVALID_STATE",
             "the programme must be CLOSING before breakage may be recognised")

    # Rung 9
    if expected != program["version"]:
        fail("ERR_STALE_VERSION", "expected_program_version does not match the programme")

    # Rung 13
    if program["revenue_recognition_state"] == "LOCKED":
        fail("ERR_PERIOD_LOCKED", "the accounting period is locked")

    # Rung 36
    for existing in store.postings.values():
        if existing["program_id"] == program["id"] and existing["period"] == period:
            fail("ERR_PERIOD_ALREADY_POSTED",
                 "a posting already exists for this programme and period")

    method_applied = method or program["breakage_policy_mode"]

    start, end = trailing_window(period)
    expired = 0
    redeemed = 0
    issued = 0
    member_ids = set(m["id"] for m in store.members.values()
                     if m["program_id"] == program["id"])
    for txn in store.transactions.values():
        if txn["member_id"] not in member_ids:
            continue
        activity = pdate(txn["activity_date"])
        if activity < start or activity > end:
            continue
        if txn["txn_type"] == "EXPIRY":
            expired += -txn["total_miles"]
        elif txn["txn_type"] == "REDEEM":
            redeemed += -txn["total_miles"]
        elif txn["txn_type"] in calc.EARN_TYPES:
            issued += txn["total_miles"]

    rate = calc.breakage_rate(method_applied, expired, redeemed, issued)
    before = program["deferred_revenue_cents"]
    income = calc.rhu(before * rate, 10000)
    after = before - income

    row = base_row(versioned=False)
    row["program_id"] = program["id"]
    row["period"] = period
    row["method"] = method
    row["method_applied"] = method_applied
    row["outstanding_miles_snapshot"] = program["outstanding_miles"]
    row["expired_miles_trailing"] = expired
    row["redeemed_miles_trailing"] = redeemed
    row["issued_miles_trailing"] = issued
    row["breakage_rate_bps"] = rate
    row["deferred_balance_before_cents"] = before
    row["breakage_income_cents"] = income
    row["deferred_balance_after_cents"] = after
    finish_row(row)
    store.postings[row["id"]] = row

    program["deferred_revenue_cents"] = after
    program["last_breakage_rate_bps"] = rate
    program["lifetime_breakage_income_cents"] += income
    touch(program)

    return created(dump(row))


@bp.get("/deferred-revenue-postings")
def list_postings():
    authenticate(("RevenueAccountant", "ProgramAdmin"))
    limit, offset = page_params()
    rows = ordered(store.postings)
    program_id = qfilter("program_id")
    if program_id is not None:
        rows = [r for r in rows if r["program_id"] == program_id]
    period = qfilter("period")
    if period is not None:
        rows = [r for r in rows if r["period"] == period]
    page, total = paginate(rows, limit, offset)
    return ok_list(dump_all(page), limit, offset, total)


@bp.get("/deferred-revenue-postings/<posting_id>")
def read_posting(posting_id):
    authenticate(("RevenueAccountant", "ProgramAdmin"))
    row = find(store.postings, posting_id, "ERR_POSTING_NOT_FOUND")
    return ok(dump(row))
