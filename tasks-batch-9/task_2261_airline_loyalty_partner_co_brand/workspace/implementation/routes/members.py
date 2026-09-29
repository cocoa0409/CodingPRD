"""Member accounts, elite status governance and the mile ledger
(PRD 3.4 and 3.6)."""

from datetime import timedelta

from flask import Blueprint

import calc
import validators as v
from db import store
from errors import fail
from middleware import authenticate, body, page_params, qfilter
from response import created, ok, ok_list
from services.core import (at_midnight, base_row, dump, dump_all, find, finish_row,
                           fk, insert_transaction, member_scope, now, ordered,
                           paginate, pdate, program_add_outstanding, touch)

bp = Blueprint("members", __name__)

MEMBER_READ_ROLES = ("ProgramAdmin", "FraudAnalyst", "RevenueAccountant", "Member")
LEDGER_READ_ROLES = ("ProgramAdmin", "RevenueAccountant", "FraudAnalyst", "Member")
HOME_REGIONS = ("AMER", "EMEA", "APAC")
MATCH_TIERS = ("SILVER", "GOLD", "PLATINUM")
DEBIT_TYPES = ("REDEEM", "EXPIRY", "ADJUSTMENT")


# --------------------------------------------------------------------------
# /member-accounts
# --------------------------------------------------------------------------


@bp.post("/member-accounts")
def create_member():
    authenticate(("ProgramAdmin",))
    data = body()
    program = fk(store.programs, data, "program_id", "ERR_PROGRAM_NOT_FOUND", required=True)
    ref = v.req_str(data, "external_member_ref")
    region = v.req_enum(data, "home_region", HOME_REGIONS)
    cycle_year = v.opt_int(data, "cycle_year", 2026)
    rollover_in = v.opt_int(data, "rollover_carried_in", 0, minimum=0)

    row = base_row()
    row["program_id"] = program["id"]
    row["external_member_ref"] = ref
    row["home_region"] = region
    row["cycle_year"] = cycle_year
    row["rollover_carried_in"] = rollover_in
    row["elite_tier"] = "BASE"
    row["security_state"] = "NORMAL"
    row["status_match_state"] = "NONE"
    row["status_match_tier"] = None
    row["status_match_expires_at"] = None
    row["qualification_state"] = "ACCUMULATING"
    row["qualifying_miles_ytd"] = 0
    row["qualifying_segments_ytd"] = 0
    row["qualifying_spend_cents_ytd"] = 0
    row["rollover_carried_out"] = 0
    row["awarded_tier_at_close"] = None
    row["mile_balance"] = 0
    row["lifetime_miles"] = 0
    row["risk_score"] = 0
    finish_row(row)
    store.members[row["id"]] = row
    return created(dump(row))


@bp.get("/member-accounts")
def list_members():
    caller = authenticate(MEMBER_READ_ROLES)
    limit, offset = page_params()
    rows = ordered(store.members)
    program_id = qfilter("program_id")
    if program_id is not None:
        rows = [r for r in rows if r["program_id"] == program_id]
    tier = qfilter("elite_tier")
    if tier is not None:
        rows = [r for r in rows if r["elite_tier"] == tier]
    security = qfilter("security_state")
    if security is not None:
        rows = [r for r in rows if r["security_state"] == security]
    if caller.is_member:
        rows = [r for r in rows if r["id"] == caller.user_id]
    page, total = paginate(rows, limit, offset)
    return ok_list(dump_all(page), limit, offset, total)


@bp.get("/member-accounts/<member_id>")
def read_member(member_id):
    caller = authenticate(MEMBER_READ_ROLES)
    member_scope(caller, member_id)
    member = find(store.members, member_id, "ERR_MEMBER_NOT_FOUND")
    return ok(dump(member))


@bp.post("/member-accounts/<member_id>/status-match")
def grant_status_match(member_id):
    authenticate(("ProgramAdmin",))
    member = find(store.members, member_id, "ERR_MEMBER_NOT_FOUND")
    data = body()
    matched = v.req_enum(data, "matched_tier", MATCH_TIERS)
    trial_days = v.req_int(data, "trial_days", minimum=0)

    # Rung 8 -- state precondition and the strictly-higher-tier precondition
    if member["status_match_state"] != "NONE":
        fail("ERR_INVALID_STATE", "a status match has already been granted")
    if calc.TIER_RANK[matched] <= calc.TIER_RANK[member["elite_tier"]]:
        fail("ERR_INVALID_STATE",
             "matched_tier must be strictly higher than the member's current tier")
    # Rung 12
    if member["security_state"] != "NORMAL":
        fail("ERR_MEMBER_FROZEN", "the member account is not in NORMAL security state")

    member["status_match_state"] = "TRIAL"
    member["status_match_tier"] = matched
    member["elite_tier"] = matched
    member["status_match_expires_at"] = now() + timedelta(days=trial_days)
    touch(member)
    return ok(dump(member))


@bp.post("/member-accounts/<member_id>/status-match/resolve")
def resolve_status_match(member_id):
    authenticate(("ProgramAdmin",))
    member = find(store.members, member_id, "ERR_MEMBER_NOT_FOUND")
    data = body()
    outcome = v.req_enum(data, "outcome", ("CONFIRM", "LAPSE"))
    if member["status_match_state"] != "TRIAL":
        fail("ERR_INVALID_STATE", "only a TRIAL status match may be resolved")
    if outcome == "CONFIRM":
        member["status_match_state"] = "CONFIRMED"
        member["elite_tier"] = member["status_match_tier"]
    else:
        member["status_match_state"] = "LAPSED"
        member["elite_tier"] = member["awarded_tier_at_close"] or "BASE"
    touch(member)
    return ok(dump(member))


@bp.post("/member-accounts/<member_id>/qualification-cycle/close")
def close_cycle(member_id):
    authenticate(("ProgramAdmin",))
    member = find(store.members, member_id, "ERR_MEMBER_NOT_FOUND")
    if member["qualification_state"] not in ("ACCUMULATING", "RESTATED"):
        fail("ERR_INVALID_STATE", "the qualification cycle is already closed")

    awarded, rollover_out = calc.qualify(
        member["qualifying_miles_ytd"], member["rollover_carried_in"],
        member["qualifying_segments_ytd"], member["qualifying_spend_cents_ytd"])

    member["qualification_state"] = "CLOSED"
    member["awarded_tier_at_close"] = awarded
    member["rollover_carried_out"] = rollover_out
    tier = awarded
    if (member["status_match_state"] in ("TRIAL", "CONFIRMED")
            and member["status_match_tier"] is not None
            and calc.TIER_RANK[member["status_match_tier"]] > calc.TIER_RANK[awarded]):
        tier = member["status_match_tier"]
    member["elite_tier"] = tier
    touch(member)
    return ok(dump(member))


@bp.post("/member-accounts/<member_id>/qualification-cycle/restate")
def restate_cycle(member_id):
    authenticate(("ProgramAdmin",))
    member = find(store.members, member_id, "ERR_MEMBER_NOT_FOUND")
    data = body()
    v.req_str(data, "reason")
    if member["qualification_state"] != "CLOSED":
        fail("ERR_INVALID_STATE", "only a CLOSED qualification cycle may be restated")

    member["qualification_state"] = "RESTATED"
    member["awarded_tier_at_close"] = None
    member["rollover_carried_out"] = 0
    tier = "BASE"
    if (member["status_match_state"] in ("TRIAL", "CONFIRMED")
            and member["status_match_tier"] is not None):
        tier = member["status_match_tier"]
    member["elite_tier"] = tier
    touch(member)
    return ok(dump(member))


# --------------------------------------------------------------------------
# /mile-transactions
# --------------------------------------------------------------------------


@bp.post("/mile-transactions")
def create_transaction():
    authenticate(("ProgramAdmin", "RevenueAccountant"))
    data = body()

    # Rung 6 -- foreign keys in declaration order
    member = fk(store.members, data, "member_id", "ERR_MEMBER_NOT_FOUND", required=True)
    campaign = fk(store.campaigns, data, "promotion_id", "ERR_PROMOTION_NOT_FOUND")
    booking = fk(store.bookings, data, "award_booking_id", "ERR_BOOKING_NOT_FOUND")
    reverses = fk(store.transactions, data, "reverses_transaction_id",
                  "ERR_TRANSACTION_NOT_FOUND")

    # Rung 7
    txn_type = v.req_enum(data, "txn_type", calc.TXN_TYPES)
    base_miles = v.opt_int(data, "base_miles", 0, minimum=0)
    spend = v.opt_int(data, "qualifying_spend_cents", 0, minimum=0)
    segments = v.opt_int(data, "segments", 0, minimum=0)
    activity_text = v.req_str(data, "activity_date")
    activity = v.parse_date(activity_text, "activity_date")

    # Rung 8
    if campaign is not None and campaign["status"] != "LIVE":
        fail("ERR_INVALID_STATE", "only a LIVE campaign may be applied to an earn row")
    # Rung 12
    if member["security_state"] != "NORMAL":
        fail("ERR_MEMBER_FROZEN", "the member account is not in NORMAL security state")
    # Rung 13
    program = store.programs[member["program_id"]]
    if program["revenue_recognition_state"] == "LOCKED":
        fail("ERR_PERIOD_LOCKED", "the accounting period is locked")
    # Rung 23
    if campaign is not None:
        if calc.CHANNEL_FOR_TXN.get(txn_type) != campaign["earn_channel"]:
            fail("ERR_PROMOTION_CHANNEL_MISMATCH",
                 "the campaign's earn_channel does not match this txn_type")
        stamp = at_midnight(activity)
        if not (campaign["window_start"] <= stamp < campaign["window_end"]):
            fail("ERR_PROMOTION_CHANNEL_MISMATCH",
                 "activity_date falls outside the campaign window")
    # Rung 27
    if campaign is not None and campaign["program_id"] != member["program_id"]:
        fail("ERR_CROSS_PROGRAM_REFERENCE",
             "the member and the campaign belong to different programmes")

    if txn_type in calc.EARN_TYPES:
        computed = calc.earn_credit(txn_type, base_miles, spend, segments,
                                    member["elite_tier"], campaign)
        total = computed["total_miles"]
        row = insert_transaction(
            member, program, txn_type, total, activity_text,
            award_booking_id=booking["id"] if booking else None,
            reverses_transaction_id=reverses["id"] if reverses else None,
            promotion_id=campaign["id"] if campaign else None,
            base_miles=base_miles, qualifying_spend_cents=spend, segments=segments,
            tier_bonus_miles=computed["tier_bonus_miles"],
            promo_multiplier_bps=computed["promo_multiplier_bps"],
            stacking_mode_applied=computed["stacking_mode_applied"],
            bonus_miles=computed["bonus_miles"],
            qualifying_miles_credited=computed["qualifying_miles_credited"])

        member["qualifying_miles_ytd"] += computed["qualifying_miles_credited"]
        if txn_type == "FLIGHT_EARN":
            member["qualifying_segments_ytd"] += segments
        elif txn_type == "CARD_SPEND_EARN":
            member["qualifying_spend_cents_ytd"] += spend
        member["mile_balance"] += total
        member["lifetime_miles"] += total
        touch(member)
        program_add_outstanding(program, total)
        if campaign is not None and computed["bonus_miles"]:
            campaign["accrued_bonus_miles"] += computed["bonus_miles"]
            touch(campaign)
        return created(dump(row))

    # Non-earning rows bypass the seven steps entirely.
    if txn_type in DEBIT_TYPES:
        # Rung 31
        if member["mile_balance"] < base_miles:
            fail("ERR_INSUFFICIENT_MILES", "the member's mile balance is too low")
        total = -base_miles
    else:  # REVERSAL
        total = base_miles

    row = insert_transaction(
        member, program, txn_type, total, activity_text,
        award_booking_id=booking["id"] if booking else None,
        reverses_transaction_id=reverses["id"] if reverses else None,
        promotion_id=campaign["id"] if campaign else None,
        base_miles=base_miles, qualifying_spend_cents=spend, segments=segments)

    member["mile_balance"] += total
    touch(member)
    program_add_outstanding(program, total)
    return created(dump(row))


@bp.get("/mile-transactions")
def list_transactions():
    caller = authenticate(LEDGER_READ_ROLES)
    limit, offset = page_params()
    rows = ordered(store.transactions)
    member_id = qfilter("member_id")
    if member_id is not None:
        member_scope(caller, member_id)
        rows = [r for r in rows if r["member_id"] == member_id]
    promotion_id = qfilter("promotion_id")
    if promotion_id is not None:
        rows = [r for r in rows if r["promotion_id"] == promotion_id]
    booking_id = qfilter("award_booking_id")
    if booking_id is not None:
        rows = [r for r in rows if r["award_booking_id"] == booking_id]
    reverses = qfilter("reverses_transaction_id")
    if reverses is not None:
        rows = [r for r in rows if r["reverses_transaction_id"] == reverses]
    txn_type = qfilter("txn_type")
    if txn_type is not None:
        rows = [r for r in rows if r["txn_type"] == txn_type]
    if caller.is_member:
        rows = [r for r in rows if r["member_id"] == caller.user_id]
    page, total = paginate(rows, limit, offset)
    return ok_list(dump_all(page), limit, offset, total)


@bp.get("/mile-transactions/<transaction_id>")
def read_transaction(transaction_id):
    caller = authenticate(LEDGER_READ_ROLES)
    row = find(store.transactions, transaction_id, "ERR_TRANSACTION_NOT_FOUND")
    member_scope(caller, row["member_id"])
    return ok(dump(row))
