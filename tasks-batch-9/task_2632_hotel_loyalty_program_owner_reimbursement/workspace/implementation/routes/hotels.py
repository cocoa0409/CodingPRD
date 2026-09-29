"""Properties, rate plans, award pricing windows and blackout windows."""

import re

from flask import Blueprint, request

import db
import middleware
import response
import support
import validate
from errors import ApiError
from middleware import ADMIN, AGENT, AUDITOR, MEMBER, OWNER
from services import calc, derive

bp = Blueprint("hotels", __name__)

BRAND_CODE_RE = re.compile(r"^[A-Z]{3}$")


# ---------------------------------------------------------------------------
# properties
# ---------------------------------------------------------------------------

@bp.route("/loyalty/hotels", methods=["POST"])
def create_hotel():
    middleware.require(ADMIN)
    payload = validate.body()
    name = validate.req_str(payload, "name", 1, 120)
    brand_code = validate.req_str(payload, "brand_code", 3, 3)
    if not BRAND_CODE_RE.match(brand_code):
        raise ApiError("ERR_INVALID_REQUEST",
                       "Field 'brand_code' must be exactly three uppercase letters.")
    market_tier = validate.req_enum(payload, "market_tier", calc.MARKET_TIERS)
    program_fee_pct = validate.req_num(payload, "program_fee_pct")
    rooms_count = validate.req_int(payload, "rooms_count")
    occupancy = validate.req_num(payload, "trailing_12m_occupancy_pct")
    adr = validate.req_int(payload, "trailing_12m_adr_cents")

    validate.dec_between("program_fee_pct", program_fee_pct, calc.dec(0), calc.dec("0.20"), 4)
    validate.int_min("rooms_count", rooms_count, 1)
    validate.dec_between("trailing_12m_occupancy_pct", occupancy, calc.dec(0), calc.dec(1), 4)
    validate.int_min("trailing_12m_adr_cents", adr, 0)

    record = {}
    db.stamp_full(record)
    record.update({
        "name": name,
        "brand_code": brand_code,
        "market_tier": market_tier,
        "program_fee_pct": calc.as_float(program_fee_pct),
        "rooms_count": rooms_count,
        "trailing_12m_occupancy_pct": calc.as_float(occupancy),
        "trailing_12m_adr_cents": adr,
        "status": "ONBOARDING",
        "fee_ledger_balance_cents": 0,
        "reimbursement_owed_cents": 0,
        "benefit_recovery_owed_cents": 0,
        "benefit_denial_count": 0,
        "blackout_days_used_current_year": 0,
        "termination_reason": None,
    })
    support.tail(record)
    db.store.hotels[record["id"]] = record
    return support.created(record)


@bp.route("/loyalty/hotels", methods=["GET"])
def list_hotels():
    middleware.require(ADMIN, AUDITOR)
    return support.listing(db.store.hotels.values(), ("status", "market_tier"))


@bp.route("/loyalty/hotels/<hotel_id>", methods=["GET"])
def get_hotel(hotel_id):
    caller = middleware.require(ADMIN, AUDITOR, OWNER, AGENT)
    middleware.own_hotel(caller, hotel_id)
    return support.one(validate.get_hotel(hotel_id))


@bp.route("/loyalty/hotels/<hotel_id>/activate", methods=["POST"])
def activate_hotel(hotel_id):
    middleware.require(ADMIN)
    hotel = validate.get_hotel(hotel_id)
    if hotel["status"] != "ONBOARDING":
        raise ApiError("ERR_HOTEL_NOT_ACTIVE",
                       "Only a property in ONBOARDING may be activated.")
    has_plan = any(p["hotel_id"] == hotel_id for p in db.store.rate_plans.values())
    if not has_plan:
        raise ApiError("ERR_HOTEL_ONBOARDING_INCOMPLETE")
    hotel["status"] = "ACTIVE"
    db.touch(hotel)
    return support.one(hotel)


@bp.route("/loyalty/hotels/<hotel_id>/performance-refresh", methods=["POST"])
def refresh_performance(hotel_id):
    caller = middleware.require(ADMIN, OWNER)
    middleware.own_hotel(caller, hotel_id)
    hotel = validate.get_hotel(hotel_id)
    payload = validate.body()
    occupancy = validate.req_num(payload, "trailing_12m_occupancy_pct")
    adr = validate.req_int(payload, "trailing_12m_adr_cents")
    validate.dec_between("trailing_12m_occupancy_pct", occupancy, calc.dec(0), calc.dec(1), 4)
    validate.int_min("trailing_12m_adr_cents", adr, 0)
    if hotel["status"] == "TERMINATED":
        raise ApiError("ERR_HOTEL_NOT_ACTIVE",
                       "A terminated property cannot restate its performance figures.")
    hotel["trailing_12m_occupancy_pct"] = calc.as_float(occupancy)
    hotel["trailing_12m_adr_cents"] = adr
    db.touch(hotel)
    return support.one(hotel)


@bp.route("/loyalty/hotels/<hotel_id>/terminate", methods=["POST"])
def terminate_hotel(hotel_id):
    middleware.require(ADMIN)
    hotel = validate.get_hotel(hotel_id)
    payload = validate.body()
    reason = validate.req_str(payload, "termination_reason", 1)
    if hotel["status"] not in ("ACTIVE", "FEE_DELINQUENT"):
        raise ApiError("ERR_HOTEL_NOT_ACTIVE",
                       "Only an active or fee-delinquent property may be terminated.")

    # hop 1 - the property closes
    hotel["status"] = "TERMINATED"
    hotel["termination_reason"] = reason

    # hop 2 - accrued reimbursement is written off
    for redemption in db.ordered(list(db.store.redemptions.values())):
        if redemption["hotel_id"] != hotel_id:
            continue
        if redemption["reimbursement_status"] == "ACCRUED":
            redemption["reimbursement_status"] = "VOIDED"
            db.touch(redemption)

    # hop 3 - unsettled batches are rejected and their items voided
    for batch in db.ordered(list(db.store.batches.values())):
        if batch["hotel_id"] != hotel_id:
            continue
        if batch["status"] not in ("OPEN", "RELEASED"):
            continue
        batch["status"] = "REJECTED"
        batch["rejection_reason"] = "HOTEL_TERMINATED"
        db.touch(batch)
        for redemption in db.ordered(list(db.store.redemptions.values())):
            if redemption.get("batch_id") != batch["id"]:
                continue
            if redemption["reimbursement_status"] == "BATCHED":
                redemption["reimbursement_status"] = "VOIDED"
                redemption["batch_id"] = None
                db.touch(redemption)

    # hop 4 - outstanding elite benefit obligations are waived
    for delivery in db.ordered(list(db.store.deliveries.values())):
        if delivery["status"] != "OBLIGATED":
            continue
        stay = db.store.stays.get(delivery["stay_id"])
        if stay is None or stay["hotel_id"] != hotel_id:
            continue
        delivery["status"] = "WAIVED"
        db.touch(delivery)

    # hop 5 - live award bookings are cancelled and their points returned
    members = {}
    for redemption in db.ordered(list(db.store.redemptions.values())):
        if redemption["hotel_id"] != hotel_id:
            continue
        if redemption["fulfillment_status"] not in ("HELD", "CONFIRMED"):
            continue
        redemption["fulfillment_status"] = "CANCELLED"
        db.touch(redemption)
        redeem_entries = [e for e in derive.entries_for_redemption(redemption["id"])
                          if e["entry_type"] == "REDEEM"]
        for entry in redeem_entries:
            derive.add_entry(redemption["member_id"], "REVERSAL", -entry["points"],
                             source_redemption_id=redemption["id"],
                             reversal_of_entry_id=entry["id"])
        member = db.store.members.get(redemption["member_id"])
        if member is not None:
            members[member["id"]] = member

    for member in db.ordered(list(members.values())):
        derive.recompute_member(member)

    derive.recompute_hotel(hotel)
    derive.recompute_fund()
    db.touch(hotel)
    return support.one(hotel)


# ---------------------------------------------------------------------------
# rate plans
# ---------------------------------------------------------------------------

@bp.route("/loyalty/hotels/<hotel_id>/rate-plans", methods=["POST"])
def create_rate_plan(hotel_id):
    caller = middleware.require(ADMIN, OWNER)
    middleware.own_hotel(caller, hotel_id)
    hotel = validate.get_hotel(hotel_id)
    payload = validate.body()
    rate_code = validate.req_str(payload, "rate_code", 1, 16)
    rate_category = validate.req_enum(payload, "rate_category", calc.RATE_CATEGORIES)
    if hotel["status"] == "TERMINATED":
        raise ApiError("ERR_HOTEL_NOT_ACTIVE",
                       "A terminated property cannot publish rate plans.")
    for plan in db.store.rate_plans.values():
        if plan["hotel_id"] == hotel_id and plan["rate_code"] == rate_code:
            raise ApiError("ERR_DUPLICATE_RATE_CODE")

    record = {}
    db.stamp_light(record)
    record.update({"hotel_id": hotel_id, "rate_code": rate_code,
                   "rate_category": rate_category})
    record.update(calc.rate_plan_derivation(rate_category))
    support.tail(record, ("created_at",))
    db.store.rate_plans[record["id"]] = record
    return support.created(record)


@bp.route("/loyalty/rate-plans/<rate_plan_id>", methods=["GET"])
def get_rate_plan(rate_plan_id):
    caller = middleware.require(ADMIN, AUDITOR, OWNER)
    plan = validate.get_rate_plan(rate_plan_id)
    middleware.own_hotel(caller, plan["hotel_id"])
    return support.one(plan)


@bp.route("/loyalty/rate-plans", methods=["GET"])
def list_rate_plans():
    caller = middleware.require(ADMIN, AUDITOR, OWNER)
    middleware.scope_filter(caller, request.args, member_key=None)
    extra = None
    if caller.is_owner:
        extra = lambda r: r["hotel_id"] == caller.user_id
    return support.listing(db.store.rate_plans.values(),
                           ("hotel_id", "rate_category"), extra)


# ---------------------------------------------------------------------------
# award pricing windows
# ---------------------------------------------------------------------------

@bp.route("/loyalty/hotels/<hotel_id>/redemption-pricing", methods=["POST"])
def create_pricing(hotel_id):
    middleware.require(ADMIN)
    validate.get_hotel(hotel_id)
    payload = validate.body()
    season = validate.req_enum(payload, "season", calc.SEASONS)
    start = validate.req_date(payload, "window_start_date")
    end = validate.req_date(payload, "window_end_date")
    points_per_night = validate.req_int(payload, "points_per_night")
    cash_copay = validate.req_int(payload, "cash_copay_cents")
    min_tier = validate.req_enum(payload, "min_tier_required", calc.TIERS)
    allotment = validate.req_int(payload, "award_allotment_per_night")
    validate.range_inclusive(start, end)

    for row in db.store.pricing_rows.values():
        if row["hotel_id"] != hotel_id or row["season"] != season:
            continue
        other_start = db.parse_date(row["window_start_date"])
        other_end = db.parse_date(row["window_end_date"])
        if start <= other_end and other_start <= end:
            raise ApiError("ERR_PRICING_WINDOW_OVERLAP")

    record = {}
    db.stamp_light(record)
    record.update({
        "hotel_id": hotel_id,
        "season": season,
        "window_start_date": db.date_str(start),
        "window_end_date": db.date_str(end),
        "points_per_night": points_per_night,
        "cash_copay_cents": cash_copay,
        "min_tier_required": min_tier,
        "award_allotment_per_night": allotment,
    })
    support.tail(record, ("created_at",))
    db.store.pricing_rows[record["id"]] = record
    return support.created(record)


@bp.route("/loyalty/redemption-pricing/<pricing_id>", methods=["GET"])
def get_pricing(pricing_id):
    caller = middleware.require(ADMIN, AUDITOR, OWNER, MEMBER, AGENT)
    row = validate.get_pricing(pricing_id)
    middleware.own_hotel(caller, row["hotel_id"])
    return support.one(row)


@bp.route("/loyalty/redemption-pricing", methods=["GET"])
def list_pricing():
    caller = middleware.require(ADMIN, AUDITOR, OWNER, MEMBER, AGENT)
    middleware.scope_filter(caller, request.args, member_key=None)
    extra = None
    if caller.is_owner:
        extra = lambda r: r["hotel_id"] == caller.user_id
    return support.listing(db.store.pricing_rows.values(), ("hotel_id", "season"), extra)


# ---------------------------------------------------------------------------
# blackout windows
# ---------------------------------------------------------------------------

@bp.route("/loyalty/hotels/<hotel_id>/blackout-windows", methods=["POST"])
def create_blackout(hotel_id):
    caller = middleware.require(ADMIN, OWNER)
    middleware.own_hotel(caller, hotel_id)
    hotel = validate.get_hotel(hotel_id)
    payload = validate.body()
    start = validate.req_date(payload, "start_date")
    end = validate.req_date(payload, "end_date")
    scope = validate.req_enum(payload, "scope", calc.BLACKOUT_SCOPES)
    validate.range_inclusive(start, end)
    if hotel["status"] != "ACTIVE":
        raise ApiError("ERR_HOTEL_NOT_ACTIVE",
                       "Only an ACTIVE property may draft a blackout window.")

    record = {}
    db.stamp_full(record)
    record.update({
        "hotel_id": hotel_id,
        "start_date": db.date_str(start),
        "end_date": db.date_str(end),
        "scope": scope,
        "status": "DRAFT",
        "day_count": db.day_span(start, end),
        "revoke_reason": None,
    })
    support.tail(record)
    db.store.blackout_windows[record["id"]] = record
    return support.created(record)


@bp.route("/loyalty/blackout-windows/<window_id>/activate", methods=["POST"])
def activate_blackout(window_id):
    middleware.require(ADMIN)
    window = validate.get_window(window_id)
    if window["status"] != "DRAFT":
        raise ApiError("ERR_BLACKOUT_WINDOW_INVALID_STATE",
                       "Only a DRAFT window may be activated.")
    hotel = db.store.hotels.get(window["hotel_id"])
    start = db.parse_date(window["start_date"])
    end = db.parse_date(window["end_date"])

    for other in db.store.blackout_windows.values():
        if other["id"] == window_id or other["hotel_id"] != window["hotel_id"]:
            continue
        if other["status"] != "ACTIVE":
            continue
        pair = sorted([window, other],
                      key=lambda w: (w["start_date"], w["created_at"], w["_seq"]))
        earlier_end = db.parse_date(pair[0]["end_date"])
        later_start = db.parse_date(pair[1]["start_date"])
        gap_days = (later_start - earlier_end).days - 1
        if gap_days < calc.BLACKOUT_BUFFER_DAYS:
            raise ApiError("ERR_BLACKOUT_WINDOW_BUFFER_CONFLICT")

    used = hotel["blackout_days_used_current_year"] if hotel is not None else 0
    if used + window["day_count"] > calc.BLACKOUT_ANNUAL_CAP_DAYS:
        raise ApiError("ERR_BLACKOUT_ANNUAL_CAP_EXCEEDED")

    window["status"] = "ACTIVE"
    db.touch(window)
    if hotel is not None:
        derive.recompute_hotel(hotel)
    return support.one(window)


@bp.route("/loyalty/blackout-windows/<window_id>/revoke", methods=["POST"])
def revoke_blackout(window_id):
    middleware.require(ADMIN)
    window = validate.get_window(window_id)
    payload = validate.body()
    reason = validate.req_str(payload, "revoke_reason", 1)
    if window["status"] != "ACTIVE":
        raise ApiError("ERR_BLACKOUT_WINDOW_INVALID_STATE",
                       "Only an ACTIVE window may be revoked.")
    window["status"] = "REVOKED"
    window["revoke_reason"] = reason
    db.touch(window)
    hotel = db.store.hotels.get(window["hotel_id"])
    if hotel is not None:
        derive.recompute_hotel(hotel)
    return support.one(window)


@bp.route("/loyalty/blackout-windows/<window_id>", methods=["GET"])
def get_blackout(window_id):
    caller = middleware.require(ADMIN, AUDITOR, OWNER, MEMBER, AGENT)
    window = validate.get_window(window_id)
    middleware.own_hotel(caller, window["hotel_id"])
    return support.one(window)


@bp.route("/loyalty/blackout-windows", methods=["GET"])
def list_blackouts():
    caller = middleware.require(ADMIN, AUDITOR, OWNER, MEMBER, AGENT)
    middleware.scope_filter(caller, request.args, member_key=None)
    extra = None
    if caller.is_owner:
        extra = lambda r: r["hotel_id"] == caller.user_id
    return support.listing(db.store.blackout_windows.values(),
                           ("hotel_id", "status"), extra)
