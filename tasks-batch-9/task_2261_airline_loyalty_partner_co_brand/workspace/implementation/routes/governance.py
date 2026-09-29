"""Programme change notices and fraud cases (PRD 3.7 and 3.8)."""

from datetime import timedelta

from flask import Blueprint

import calc
import validators as v
from db import store
from errors import fail
from middleware import authenticate, body, page_params, qfilter
from response import created, ok, ok_list
from services.core import (base_row, cancel_held_bookings, dump, dump_all, find,
                           finish_row, fk, insert_transaction, member_scope, now,
                           ordered, paginate, pdate, program_add_outstanding, today,
                           touch)

bp = Blueprint("governance", __name__)

NOTICE_READ_ROLES = ("ProgramAdmin", "PartnerManager", "RevenueAccountant", "Member")
CASE_READ_ROLES = ("FraudAnalyst", "ProgramAdmin", "Member")
LIVE_CASE_STATUSES = ("OPEN", "INVESTIGATING", "SUBSTANTIATED")


# --------------------------------------------------------------------------
# /program-change-notices
# --------------------------------------------------------------------------


@bp.post("/program-change-notices")
def create_notice():
    authenticate(("ProgramAdmin",))
    data = body()
    program = fk(store.programs, data, "program_id", "ERR_PROGRAM_NOT_FOUND", required=True)
    change_type = v.req_enum(data, "change_type", calc.CHANGE_TYPES)
    effective_at = v.req_dt(data, "effective_at")
    expected = v.req_int(data, "expected_program_version")
    grandfather_until = v.opt_dt(data, "grandfather_until")
    tier_floor = v.opt_enum(data, "grandfathered_tier_floor", calc.TIERS)

    # Rung 9
    if expected != program["version"]:
        fail("ERR_STALE_VERSION", "expected_program_version does not match the programme")
    # Rung 16
    if effective_at <= now() or (grandfather_until is not None
                                 and grandfather_until < effective_at):
        fail("ERR_INVALID_NOTICE_SCHEDULE",
             "effective_at must be in the future and grandfather_until at or after it")

    row = base_row()
    row["program_id"] = program["id"]
    row["change_type"] = change_type
    row["effective_at"] = effective_at
    row["grandfather_until"] = grandfather_until
    row["grandfathered_tier_floor"] = tier_floor
    row["announced_at"] = None
    row["notice_days"] = 0
    row["exposed_member_count"] = 0
    row["member_reaction_index"] = 0
    row["status"] = "DRAFT"
    row["rollback_reason"] = None
    finish_row(row)
    store.notices[row["id"]] = row

    touch(program)
    return created(dump(row))


@bp.get("/program-change-notices")
def list_notices():
    authenticate(NOTICE_READ_ROLES)
    limit, offset = page_params()
    rows = ordered(store.notices)
    program_id = qfilter("program_id")
    if program_id is not None:
        rows = [r for r in rows if r["program_id"] == program_id]
    status = qfilter("status")
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, total = paginate(rows, limit, offset)
    return ok_list(dump_all(page), limit, offset, total)


@bp.get("/program-change-notices/<notice_id>")
def read_notice(notice_id):
    authenticate(NOTICE_READ_ROLES)
    row = find(store.notices, notice_id, "ERR_NOTICE_NOT_FOUND")
    return ok(dump(row))


@bp.post("/program-change-notices/<notice_id>/announce")
def announce_notice(notice_id):
    authenticate(("ProgramAdmin",))
    notice = find(store.notices, notice_id, "ERR_NOTICE_NOT_FOUND")
    # Rung 8
    if notice["status"] != "DRAFT":
        fail("ERR_INVALID_STATE", "only a DRAFT notice may be announced")
    # Rung 16
    announced_at = now()
    if notice["effective_at"] <= announced_at or (
            notice["grandfather_until"] is not None
            and notice["grandfather_until"] < notice["effective_at"]):
        fail("ERR_INVALID_NOTICE_SCHEDULE",
             "effective_at must still be in the future to announce this notice")

    notice_days = int((notice["effective_at"] - announced_at).total_seconds() // 86400)
    exposed = 0
    for member in store.members.values():
        if (member["program_id"] == notice["program_id"]
                and member["elite_tier"] != "BASE"
                and member["security_state"] in ("NORMAL", "WATCH")):
            exposed += 1

    index = calc.reaction_index(notice["change_type"], notice_days,
                                notice["grandfather_until"], notice["effective_at"],
                                exposed)

    # Rung 35
    if index >= calc.REACTION_RISK_BLOCK_THRESHOLD and notice["grandfather_until"] is None:
        fail("ERR_REACTION_RISK_EXCEEDED",
             "the member reaction index is too high to announce without grandfathering")

    notice["announced_at"] = announced_at
    notice["notice_days"] = notice_days
    notice["exposed_member_count"] = exposed
    notice["member_reaction_index"] = index
    notice["status"] = "ANNOUNCED"
    touch(notice)
    return ok(dump(notice))


@bp.post("/program-change-notices/<notice_id>/rollback")
def rollback_notice(notice_id):
    authenticate(("ProgramAdmin",))
    notice = find(store.notices, notice_id, "ERR_NOTICE_NOT_FOUND")
    data = body()
    reason = v.req_str(data, "reason")
    if notice["status"] not in ("ANNOUNCED", "IN_GRANDFATHER", "EFFECTIVE"):
        fail("ERR_INVALID_STATE",
             "only an announced, grandfathered or effective notice may be rolled back")

    notice["status"] = "ROLLED_BACK"
    notice["rollback_reason"] = reason
    touch(notice)

    if notice["change_type"] == "EARN_STRUCTURE":
        for campaign in ordered(store.campaigns):
            if (campaign["program_id"] == notice["program_id"]
                    and campaign["status"] == "SCHEDULED"
                    and campaign["earn_channel"] == "CARD_SPEND"):
                campaign["status"] = "CANCELLED"
                touch(campaign)

    return ok(dump(notice))


# --------------------------------------------------------------------------
# /fraud-cases
# --------------------------------------------------------------------------


@bp.post("/fraud-cases")
def create_case():
    caller = authenticate(("FraudAnalyst",))
    data = body()
    member = fk(store.members, data, "member_id", "ERR_MEMBER_NOT_FOUND", required=True)
    case_type = v.req_enum(data, "case_type", calc.CASE_TYPES)
    geo = v.req_int(data, "login_geo_velocity", minimum=0)
    redemption = v.req_int(data, "redemption_velocity_24h", minimum=0)
    brokering = v.req_int(data, "brokering_pattern_hits", minimum=0)
    dormancy = v.req_int(data, "dormancy_days", minimum=0)

    score = calc.detection_score(geo, redemption, brokering, dormancy)

    row = base_row()
    row["member_id"] = member["id"]
    row["case_type"] = case_type
    row["login_geo_velocity"] = geo
    row["redemption_velocity_24h"] = redemption
    row["brokering_pattern_hits"] = brokering
    row["dormancy_days"] = dormancy
    row["detection_score"] = score
    row["freeze_applied"] = False
    row["clawback_miles"] = 0
    row["opened_by_user_id"] = caller.user_id
    row["adjudicated_by_user_id"] = None
    row["status"] = "OPEN"
    finish_row(row)
    store.cases[row["id"]] = row

    # Immediate security posture on the member
    if score >= calc.RISK_FREEZE_THRESHOLD:
        if member["security_state"] in ("NORMAL", "WATCH"):
            member["security_state"] = "FROZEN"
            row["freeze_applied"] = True
    elif score >= calc.RISK_WATCH_THRESHOLD:
        if member["security_state"] == "NORMAL":
            member["security_state"] = "WATCH"
    member["risk_score"] = score
    touch(member)

    if member["security_state"] == "FROZEN" and row["freeze_applied"]:
        cancel_held_bookings(member)

    return created(dump(row))


@bp.get("/fraud-cases")
def list_cases():
    caller = authenticate(CASE_READ_ROLES)
    limit, offset = page_params()
    rows = ordered(store.cases)
    member_id = qfilter("member_id")
    if member_id is not None:
        member_scope(caller, member_id)
        rows = [r for r in rows if r["member_id"] == member_id]
    status = qfilter("status")
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    case_type = qfilter("case_type")
    if case_type is not None:
        rows = [r for r in rows if r["case_type"] == case_type]
    if caller.is_member:
        rows = [r for r in rows if r["member_id"] == caller.user_id]
    page, total = paginate(rows, limit, offset)
    return ok_list(dump_all(page), limit, offset, total)


@bp.get("/fraud-cases/<case_id>")
def read_case(case_id):
    caller = authenticate(CASE_READ_ROLES)
    row = find(store.cases, case_id, "ERR_FRAUD_CASE_NOT_FOUND")
    member_scope(caller, row["member_id"])
    return ok(dump(row))


@bp.post("/fraud-cases/<case_id>/investigate")
def investigate_case(case_id):
    authenticate(("FraudAnalyst",))
    case = find(store.cases, case_id, "ERR_FRAUD_CASE_NOT_FOUND")
    if case["status"] != "OPEN":
        fail("ERR_INVALID_STATE", "only an OPEN case may move into investigation")
    case["status"] = "INVESTIGATING"
    touch(case)
    return ok(dump(case))


@bp.post("/fraud-cases/<case_id>/substantiate")
def substantiate_case(case_id):
    caller = authenticate(("FraudAnalyst",))
    case = find(store.cases, case_id, "ERR_FRAUD_CASE_NOT_FOUND")
    member = store.members[case["member_id"]]
    program = store.programs[member["program_id"]]

    # Rung 8
    if case["status"] != "INVESTIGATING":
        fail("ERR_INVALID_STATE", "only an INVESTIGATING case may be substantiated")
    # Rung 11
    if caller.user_id == case["opened_by_user_id"]:
        fail("ERR_SEGREGATION_OF_DUTIES", "the opener of a case may not adjudicate it")
    # Rung 13
    if program["revenue_recognition_state"] == "LOCKED":
        fail("ERR_PERIOD_LOCKED", "the accounting period is locked")

    # Hop 1 -- clawback basis over the 90-day lookback
    cutoff = today() - timedelta(days=calc.CLAWBACK_LOOKBACK_DAYS)
    basis = 0
    for txn in store.transactions.values():
        if txn["member_id"] != member["id"] or txn["txn_type"] not in calc.EARN_TYPES:
            continue
        activity = pdate(txn["activity_date"])
        if cutoff <= activity <= today():
            basis += txn["total_miles"]

    clawback = calc.clawback_for(case["case_type"], member["mile_balance"], basis)

    case["status"] = "SUBSTANTIATED"
    case["adjudicated_by_user_id"] = caller.user_id
    case["clawback_miles"] = clawback
    case["freeze_applied"] = True
    touch(case)

    # Hop 2 -- apply the outcome
    if clawback > 0:
        insert_transaction(member, program, "ADJUSTMENT", -clawback,
                           "%04d-%02d-%02d" % (today().year, today().month, today().day),
                           base_miles=clawback)
        member["mile_balance"] -= clawback

    if case["case_type"] == "ACCOUNT_TAKEOVER":
        member["security_state"] = "CLOSED"
    elif member["security_state"] != "CLOSED":
        member["security_state"] = "FROZEN"
    touch(member)

    # Hops 3 and 4 -- cancel held bookings and re-posture their windows
    cancel_held_bookings(member)

    # Hop 5
    if clawback > 0:
        program_add_outstanding(program, -clawback)

    return ok(dump(case))


@bp.post("/fraud-cases/<case_id>/dismiss")
def dismiss_case(case_id):
    caller = authenticate(("FraudAnalyst",))
    case = find(store.cases, case_id, "ERR_FRAUD_CASE_NOT_FOUND")
    member = store.members[case["member_id"]]
    data = body()
    v.opt_str(data, "note", allow_empty=True)

    # Rung 8
    if case["status"] != "INVESTIGATING":
        fail("ERR_INVALID_STATE", "only an INVESTIGATING case may be dismissed")
    # Rung 11
    if caller.user_id == case["opened_by_user_id"]:
        fail("ERR_SEGREGATION_OF_DUTIES", "the opener of a case may not adjudicate it")

    case["status"] = "DISMISSED"
    case["adjudicated_by_user_id"] = caller.user_id
    touch(case)

    others = [c for c in store.cases.values()
              if c["member_id"] == member["id"] and c["id"] != case["id"]
              and c["status"] in LIVE_CASE_STATUSES]
    if not others and member["security_state"] in ("WATCH", "FROZEN"):
        member["security_state"] = "NORMAL"
        member["risk_score"] = 0
        touch(member)

    return ok(dump(case))
