"""Promotion campaigns, award seat inventory, award bookings and partner
airlines (PRD 3.4, 3.5)."""

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
                           paginate, pdate, program_add_outstanding, recompute_window,
                           release_seats, today, touch)

bp = Blueprint("awards", __name__)

CAMPAIGN_READ_ROLES = ("ProgramAdmin", "PartnerManager", "RevenueAccountant", "Member")
BOOKING_READ_ROLES = ("ProgramAdmin", "RevenueAccountant", "FraudAnalyst", "Member")
EARN_CHANNELS = ("FLIGHT", "CARD_SPEND", "PARTNER")
STACKING_MODES = ("EXCLUSIVE", "ADDITIVE", "MULTIPLICATIVE")
CAPACITY_STATES = ("OPEN", "CONSTRAINED", "CLOSED")


# --------------------------------------------------------------------------
# /promotion-campaigns
# --------------------------------------------------------------------------


@bp.post("/promotion-campaigns")
def create_campaign():
    authenticate(("ProgramAdmin",))
    data = body()
    program = fk(store.programs, data, "program_id", "ERR_PROGRAM_NOT_FOUND", required=True)
    code = v.req_str(data, "code")
    channel = v.req_enum(data, "earn_channel", EARN_CHANNELS)
    multiplier = v.req_int(data, "multiplier_bps",
                           minimum=calc.MIN_PROMO_MULTIPLIER_BPS,
                           maximum=calc.MAX_PROMO_MULTIPLIER_BPS)
    stacking = v.req_enum(data, "stacking_mode", STACKING_MODES)
    cap = v.opt_int(data, "bonus_cap_miles", None, minimum=0)
    window_start = v.req_dt(data, "window_start")
    window_end = v.req_dt(data, "window_end")

    # Rung 14
    if not window_start < window_end:
        fail("ERR_INVALID_INTERVAL", "window_start must be strictly before window_end")
    # Rung 15
    if window_start < now():
        fail("ERR_WINDOW_IN_PAST", "the campaign window may not open in the past")
    # Rung 19 -- half-open windows, so exact adjacency is allowed
    for other in store.campaigns.values():
        if (other["program_id"] != program["id"]
                or other["earn_channel"] != channel
                or other["status"] not in ("SCHEDULED", "LIVE")):
            continue
        if window_start < other["window_end"] and other["window_start"] < window_end:
            fail("ERR_PROMOTION_WINDOW_OVERLAP",
                 "the window overlaps a live or scheduled campaign on the same channel")

    row = base_row()
    row["program_id"] = program["id"]
    row["code"] = code
    row["earn_channel"] = channel
    row["multiplier_bps"] = multiplier
    row["stacking_mode"] = stacking
    row["bonus_cap_miles"] = cap
    row["accrued_bonus_miles"] = 0
    row["window_start"] = window_start
    row["window_end"] = window_end
    row["status"] = "SCHEDULED"
    row["cancellation_reason"] = None
    finish_row(row)
    store.campaigns[row["id"]] = row
    return created(dump(row))


@bp.get("/promotion-campaigns")
def list_campaigns():
    authenticate(CAMPAIGN_READ_ROLES)
    limit, offset = page_params()
    rows = ordered(store.campaigns)
    program_id = qfilter("program_id")
    if program_id is not None:
        rows = [r for r in rows if r["program_id"] == program_id]
    channel = qfilter("earn_channel")
    if channel is not None:
        rows = [r for r in rows if r["earn_channel"] == channel]
    status = qfilter("status")
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, total = paginate(rows, limit, offset)
    return ok_list(dump_all(page), limit, offset, total)


@bp.get("/promotion-campaigns/<campaign_id>")
def read_campaign(campaign_id):
    authenticate(CAMPAIGN_READ_ROLES)
    row = find(store.campaigns, campaign_id, "ERR_PROMOTION_NOT_FOUND")
    return ok(dump(row))


@bp.post("/promotion-campaigns/<campaign_id>/cancel")
def cancel_campaign(campaign_id):
    authenticate(("ProgramAdmin",))
    campaign = find(store.campaigns, campaign_id, "ERR_PROMOTION_NOT_FOUND")
    data = body()
    reason = v.req_str(data, "reason")
    if campaign["status"] not in ("SCHEDULED", "LIVE"):
        fail("ERR_INVALID_STATE", "only a SCHEDULED or LIVE campaign may be cancelled")
    campaign["status"] = "CANCELLED"
    campaign["cancellation_reason"] = reason
    touch(campaign)
    return ok(dump(campaign))


# --------------------------------------------------------------------------
# /award-inventory-windows
# --------------------------------------------------------------------------


@bp.post("/award-inventory-windows")
def create_window():
    authenticate(("ProgramAdmin",))
    data = body()
    program = fk(store.programs, data, "program_id", "ERR_PROGRAM_NOT_FOUND", required=True)
    route = v.req_str(data, "route_code")
    cabin = v.req_enum(data, "cabin", calc.CABINS)
    start_text = v.req_str(data, "window_start_date")
    start = v.parse_date(start_text, "window_start_date")
    end_text = v.req_str(data, "window_end_date")
    end = v.parse_date(end_text, "window_end_date")
    seats = v.req_int(data, "authorized_seats", minimum=0)
    share = v.opt_int(data, "saver_seat_share_bps", None, minimum=0, maximum=10000)

    # Rung 14
    if start > end:
        fail("ERR_INVALID_INTERVAL",
             "window_start_date must not be after window_end_date")
    # Rung 15
    if at_midnight(start) < now():
        fail("ERR_WINDOW_IN_PAST", "the window may not open in the past")
    # Rung 20 -- at least two clear days between closed intervals
    for other in store.windows.values():
        if (other["program_id"] != program["id"]
                or other["route_code"] != route
                or other["cabin"] != cabin):
            continue
        other_start = pdate(other["window_start_date"])
        other_end = pdate(other["window_end_date"])
        clear = (start - other_end).days >= 3 or (other_start - end).days >= 3
        if not clear:
            fail("ERR_AWARD_WINDOW_BUFFER_VIOLATION",
                 "the window must leave at least two clear days from every other "
                 "window on the same route and cabin")

    row = base_row()
    row["program_id"] = program["id"]
    row["route_code"] = route
    row["cabin"] = cabin
    row["window_start_date"] = start_text
    row["window_end_date"] = end_text
    row["authorized_seats"] = seats
    row["saver_seat_share_bps"] = (share if share is not None
                                   else program["saver_share_default_bps"])
    row["seats_held"] = 0
    row["seats_confirmed"] = 0
    row["saver_seats_consumed"] = 0
    row["load_factor_bps"] = 0
    row["capacity_control_state"] = "OPEN"
    row["demand_multiplier_bps"] = 9000
    finish_row(row)
    store.windows[row["id"]] = row
    return created(dump(row))


@bp.get("/award-inventory-windows")
def list_windows():
    authenticate(CAMPAIGN_READ_ROLES)
    limit, offset = page_params()
    rows = ordered(store.windows)
    program_id = qfilter("program_id")
    if program_id is not None:
        rows = [r for r in rows if r["program_id"] == program_id]
    route = qfilter("route_code")
    if route is not None:
        rows = [r for r in rows if r["route_code"] == route]
    cabin = qfilter("cabin")
    if cabin is not None:
        rows = [r for r in rows if r["cabin"] == cabin]
    state = qfilter("capacity_control_state")
    if state is not None:
        rows = [r for r in rows if r["capacity_control_state"] == state]
    page, total = paginate(rows, limit, offset)
    return ok_list(dump_all(page), limit, offset, total)


@bp.get("/award-inventory-windows/<window_id>")
def read_window(window_id):
    authenticate(CAMPAIGN_READ_ROLES)
    row = find(store.windows, window_id, "ERR_AWARD_WINDOW_NOT_FOUND")
    return ok(dump(row))


@bp.patch("/award-inventory-windows/<window_id>/capacity-control")
def pin_capacity(window_id):
    authenticate(("ProgramAdmin",))
    window = find(store.windows, window_id, "ERR_AWARD_WINDOW_NOT_FOUND")
    data = body()
    target = v.req_enum(data, "capacity_control_state", CAPACITY_STATES)
    current = window["capacity_control_state"]

    if target == "CLOSED":
        if current == "CLOSED":
            fail("ERR_INVALID_STATE", "the window is already CLOSED")
    elif target == "OPEN":
        if current != "CLOSED":
            fail("ERR_INVALID_STATE", "only a CLOSED window may be reopened")
        if window["load_factor_bps"] >= calc.CAPACITY_CONSTRAINED_BPS:
            fail("ERR_INVALID_STATE",
                 "the load factor must be below 7500 basis points to reopen")
    else:
        fail("ERR_INVALID_STATE", "capacity_control_state may not be pinned to CONSTRAINED")

    window["capacity_control_state"] = target
    touch(window)
    return ok(dump(window))


# --------------------------------------------------------------------------
# /award-bookings
# --------------------------------------------------------------------------


@bp.post("/award-bookings")
def create_booking():
    caller = authenticate(("Member", "ProgramAdmin"))
    data = body()

    # Rung 3
    if caller.is_member:
        member_scope(caller, data.get("member_id"))

    # Rung 6
    member = fk(store.members, data, "member_id", "ERR_MEMBER_NOT_FOUND", required=True)
    window = fk(store.windows, data, "window_id", "ERR_AWARD_WINDOW_NOT_FOUND",
                required=True)
    partner = fk(store.partners, data, "partner_airline_id", "ERR_PARTNER_NOT_FOUND")

    # Rung 7 -- `seats` bounds are owned by rung 26, so only its type is checked here
    travel_text = v.req_str(data, "travel_date")
    travel = v.parse_date(travel_text, "travel_date")
    seats = v.req_int(data, "seats")
    fare_class = v.req_enum(data, "fare_class", calc.FARE_CLASSES)
    expected = v.req_int(data, "expected_window_version")

    # Rung 9
    if expected != window["version"]:
        fail("ERR_STALE_VERSION", "expected_window_version does not match the window")
    # Rung 12
    if member["security_state"] != "NORMAL":
        fail("ERR_MEMBER_FROZEN", "the member account is not in NORMAL security state")
    # Rung 18
    if travel < pdate(window["window_start_date"]) or travel > pdate(window["window_end_date"]):
        fail("ERR_TRAVEL_DATE_OUT_OF_WINDOW",
             "travel_date falls outside the window's date interval")
    # Rung 24
    if partner is not None and partner["reciprocity_mode"] == "SUSPENDED":
        fail("ERR_RECIPROCITY_SUSPENDED", "the partner airline's reciprocity is suspended")
    # Rung 25
    if window["capacity_control_state"] == "CLOSED":
        fail("ERR_AWARD_WINDOW_CLOSED", "the award window is closed")
    # Rung 26
    if seats < 1 or seats > calc.MAX_SEATS_PER_BOOKING:
        fail("ERR_SEAT_COUNT_INVALID", "seats must be between 1 and 9 inclusive")
    # Rung 27
    if window["program_id"] != member["program_id"] or (
            partner is not None and partner["program_id"] != member["program_id"]):
        fail("ERR_CROSS_PROGRAM_REFERENCE",
             "the member, window and partner airline must share one programme")
    # Rung 28
    if window["seats_held"] + window["seats_confirmed"] + seats > window["authorized_seats"]:
        fail("ERR_AWARD_SEATS_UNAVAILABLE", "the window has no raw capacity left")
    # Rung 29
    if fare_class == "SAVER":
        allotment = calc.saver_allotment(window["authorized_seats"],
                                         window["saver_seat_share_bps"])
        if window["saver_seats_consumed"] + seats > allotment:
            fail("ERR_SAVER_ALLOTMENT_EXHAUSTED", "the saver allotment is exhausted")

    priced = calc.price_award_booking(window, fare_class, partner,
                                      member["elite_tier"], seats)

    row = base_row()
    row["member_id"] = member["id"]
    row["window_id"] = window["id"]
    row["partner_airline_id"] = partner["id"] if partner else None
    row["travel_date"] = travel_text
    row["seats"] = seats
    row["fare_class"] = fare_class
    row["chart_miles_per_seat"] = priced["chart_miles_per_seat"]
    row["demand_multiplier_bps_applied"] = priced["demand_multiplier_bps_applied"]
    row["partner_uplift_bps_applied"] = priced["partner_uplift_bps_applied"]
    row["surcharge_band"] = priced["surcharge_band"]
    row["elite_discount_bps_applied"] = priced["elite_discount_bps_applied"]
    row["quoted_miles"] = priced["quoted_miles"]
    row["cash_surcharge_cents"] = priced["cash_surcharge_cents"]
    row["partner_settlement_cents"] = priced["partner_settlement_cents"]
    row["partner_settled"] = False
    row["hold_expires_at"] = now() + timedelta(hours=calc.HOLD_HOURS)
    row["status"] = "HELD"
    finish_row(row)
    store.bookings[row["id"]] = row

    window["seats_held"] += seats
    if fare_class == "SAVER":
        window["saver_seats_consumed"] += seats
    recompute_window(window)
    touch(window)

    return created(dump(row))


@bp.get("/award-bookings")
def list_bookings():
    caller = authenticate(BOOKING_READ_ROLES)
    limit, offset = page_params()
    rows = ordered(store.bookings)
    member_id = qfilter("member_id")
    if member_id is not None:
        member_scope(caller, member_id)
        rows = [r for r in rows if r["member_id"] == member_id]
    window_id = qfilter("window_id")
    if window_id is not None:
        rows = [r for r in rows if r["window_id"] == window_id]
    partner_id = qfilter("partner_airline_id")
    if partner_id is not None:
        rows = [r for r in rows if r["partner_airline_id"] == partner_id]
    status = qfilter("status")
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if caller.is_member:
        rows = [r for r in rows if r["member_id"] == caller.user_id]
    page, total = paginate(rows, limit, offset)
    return ok_list(dump_all(page), limit, offset, total)


@bp.get("/award-bookings/<booking_id>")
def read_booking(booking_id):
    caller = authenticate(BOOKING_READ_ROLES)
    booking = find(store.bookings, booking_id, "ERR_BOOKING_NOT_FOUND")
    member_scope(caller, booking["member_id"])
    return ok(dump(booking))


@bp.post("/award-bookings/<booking_id>/ticket")
def ticket_booking(booking_id):
    caller = authenticate(("Member", "ProgramAdmin"))
    booking = find(store.bookings, booking_id, "ERR_BOOKING_NOT_FOUND")
    member_scope(caller, booking["member_id"])
    member = store.members[booking["member_id"]]
    program = store.programs[member["program_id"]]

    # Rung 8
    if booking["status"] != "HELD":
        fail("ERR_INVALID_STATE", "only a HELD booking may be ticketed")
    # Rung 12
    if member["security_state"] != "NORMAL":
        fail("ERR_MEMBER_FROZEN", "the member account is not in NORMAL security state")
    # Rung 13
    if program["revenue_recognition_state"] == "LOCKED":
        fail("ERR_PERIOD_LOCKED", "the accounting period is locked")
    # Rung 30
    if not booking["hold_expires_at"] > now():
        fail("ERR_HOLD_EXPIRED", "the hold has expired")
    # Rung 31
    quoted = booking["quoted_miles"]
    if member["mile_balance"] < quoted:
        fail("ERR_INSUFFICIENT_MILES", "the member's mile balance is too low")

    booking["status"] = "TICKETED"
    touch(booking)

    insert_transaction(member, program, "REDEEM", -quoted,
                       "%04d-%02d-%02d" % (today().year, today().month, today().day),
                       award_booking_id=booking["id"], base_miles=quoted)

    member["mile_balance"] -= quoted
    touch(member)
    program_add_outstanding(program, -quoted)

    window = store.windows[booking["window_id"]]
    window["seats_held"] -= booking["seats"]
    window["seats_confirmed"] += booking["seats"]
    recompute_window(window)
    touch(window)

    return ok(dump(booking))


@bp.post("/award-bookings/<booking_id>/cancel")
def cancel_booking(booking_id):
    caller = authenticate(("Member", "ProgramAdmin"))
    booking = find(store.bookings, booking_id, "ERR_BOOKING_NOT_FOUND")
    member_scope(caller, booking["member_id"])
    if booking["status"] != "HELD":
        fail("ERR_INVALID_STATE", "only a HELD booking may be cancelled")
    booking["status"] = "CANCELLED"
    touch(booking)
    release_seats(booking)
    return ok(dump(booking))


@bp.post("/award-bookings/<booking_id>/refund")
def refund_booking(booking_id):
    authenticate(("ProgramAdmin",))
    booking = find(store.bookings, booking_id, "ERR_BOOKING_NOT_FOUND")
    member = store.members[booking["member_id"]]
    program = store.programs[member["program_id"]]

    if booking["status"] != "TICKETED" or booking["partner_settled"]:
        fail("ERR_INVALID_STATE",
             "only a TICKETED booking that has not been settled may be refunded")
    if program["revenue_recognition_state"] == "LOCKED":
        fail("ERR_PERIOD_LOCKED", "the accounting period is locked")

    quoted = booking["quoted_miles"]
    redeem_row = None
    for txn in ordered(store.transactions):
        if txn["award_booking_id"] == booking["id"] and txn["txn_type"] == "REDEEM":
            redeem_row = txn

    booking["status"] = "REFUNDED"
    touch(booking)

    insert_transaction(member, program, "REVERSAL", quoted,
                       "%04d-%02d-%02d" % (today().year, today().month, today().day),
                       award_booking_id=booking["id"],
                       reverses_transaction_id=redeem_row["id"] if redeem_row else None,
                       base_miles=quoted)

    member["mile_balance"] += quoted
    touch(member)
    program_add_outstanding(program, quoted)

    window = store.windows[booking["window_id"]]
    window["seats_confirmed"] -= booking["seats"]
    if booking["fare_class"] == "SAVER":
        window["saver_seats_consumed"] -= booking["seats"]
    recompute_window(window)
    touch(window)

    return ok(dump(booking))


# --------------------------------------------------------------------------
# /partner-airlines
# --------------------------------------------------------------------------


@bp.post("/partner-airlines")
def create_partner():
    authenticate(("ProgramAdmin", "PartnerManager"))
    data = body()
    program = fk(store.programs, data, "program_id", "ERR_PROGRAM_NOT_FOUND", required=True)
    iata = v.req_str(data, "iata_code")
    rate = v.req_int(data, "settlement_rate_centicents_per_mile", minimum=1)
    reciprocity = v.opt_enum(data, "reciprocity_mode", calc.RECIPROCITY_MODES, "FULL")
    pricing = v.opt_enum(data, "award_pricing_mode", calc.AWARD_PRICING_MODES, "FIXED_CHART")

    row = base_row()
    row["program_id"] = program["id"]
    row["iata_code"] = iata
    row["settlement_rate_centicents_per_mile"] = rate
    row["reciprocity_mode"] = reciprocity
    row["award_pricing_mode"] = pricing
    row["net_settlement_balance_cents"] = 0
    row["settled_booking_count"] = 0
    row["last_settlement_run_at"] = None
    finish_row(row)
    store.partners[row["id"]] = row
    return created(dump(row))


@bp.get("/partner-airlines")
def list_partners():
    authenticate(CAMPAIGN_READ_ROLES)
    limit, offset = page_params()
    rows = ordered(store.partners)
    program_id = qfilter("program_id")
    if program_id is not None:
        rows = [r for r in rows if r["program_id"] == program_id]
    reciprocity = qfilter("reciprocity_mode")
    if reciprocity is not None:
        rows = [r for r in rows if r["reciprocity_mode"] == reciprocity]
    page, total = paginate(rows, limit, offset)
    return ok_list(dump_all(page), limit, offset, total)


@bp.get("/partner-airlines/<airline_id>")
def read_partner(airline_id):
    authenticate(CAMPAIGN_READ_ROLES)
    row = find(store.partners, airline_id, "ERR_PARTNER_NOT_FOUND")
    return ok(dump(row))


@bp.post("/partner-airlines/<airline_id>/settlement-runs")
def settlement_run(airline_id):
    authenticate(("RevenueAccountant",))
    partner = find(store.partners, airline_id, "ERR_PARTNER_NOT_FOUND")

    # Rung 24
    if partner["reciprocity_mode"] == "SUSPENDED":
        fail("ERR_RECIPROCITY_SUSPENDED", "the partner airline's reciprocity is suspended")

    factor = calc.RECIPROCITY_FACTOR_BPS[partner["reciprocity_mode"]]
    limit_date = today()
    for booking in ordered(store.bookings):
        if (booking["partner_airline_id"] != partner["id"]
                or booking["status"] != "TICKETED"
                or booking["partner_settled"]
                or pdate(booking["travel_date"]) > limit_date):
            continue
        amount = calc.rhu(booking["partner_settlement_cents"] * factor, 10000)
        partner["net_settlement_balance_cents"] += amount
        partner["settled_booking_count"] += 1
        booking["partner_settled"] = True
        touch(booking)

    partner["last_settlement_run_at"] = now()
    touch(partner)
    return ok(dump(partner))
