"""Paid stays, the posting fork, corrections and elite benefit obligations."""

from flask import Blueprint, request

import db
import middleware
import support
import validate
from errors import ApiError
from middleware import ADMIN, AGENT, AUDITOR, MEMBER, OWNER
from services import calc, derive

bp = Blueprint("stays", __name__)


def _plan_of(stay):
    return db.store.rate_plans.get(stay["rate_plan_id"]) or {}


# ---------------------------------------------------------------------------
# capture
# ---------------------------------------------------------------------------

@bp.route("/loyalty/stays", methods=["POST"])
def create_stay():
    caller = middleware.require(ADMIN, OWNER)
    payload = validate.body()
    hotel_id = validate.fk(payload, "hotel_id")
    middleware.own_hotel(caller, hotel_id)
    hotel = validate.get_hotel(hotel_id)
    plan = validate.get_rate_plan(validate.fk(payload, "rate_plan_id"))
    member = validate.get_member(validate.fk(payload, "member_id"))

    checkin = validate.req_date(payload, "checkin_date")
    checkout = validate.req_date(payload, "checkout_date")
    room_revenue = validate.req_int(payload, "room_revenue_cents")
    incidental = validate.opt_int(payload, "incidental_revenue_cents", 0)

    validate.range_stay(checkin, checkout)
    validate.int_min("room_revenue_cents", room_revenue, 0)
    validate.int_min("incidental_revenue_cents", incidental, 0)

    if plan["hotel_id"] != hotel_id:
        raise ApiError("ERR_RATE_PLAN_HOTEL_MISMATCH")
    if hotel["status"] != "ACTIVE":
        raise ApiError("ERR_HOTEL_NOT_ACTIVE",
                       "A paid stay may only be captured at an ACTIVE property.")

    record = {}
    db.stamp_full(record)
    record.update({
        "member_id": member["id"],
        "hotel_id": hotel_id,
        "rate_plan_id": plan["id"],
        "checkin_date": db.date_str(checkin),
        "checkout_date": db.date_str(checkout),
        "nights": db.nights_between(checkin, checkout),
        "room_revenue_cents": room_revenue,
        "incidental_revenue_cents": incidental,
        "tier_at_checkin": member["elite_tier"],
        "status": "PENDING_POSTING",
        "base_points_awarded": 0,
        "bonus_points_awarded": 0,
        "program_fee_assessed_cents": 0,
        "bonus_multiplier_applied": 0.00,
        "dispute_reason": None,
        "void_reason": None,
    })
    support.tail(record)
    db.store.stays[record["id"]] = record
    return support.created(record)


@bp.route("/loyalty/stays/<stay_id>", methods=["GET"])
def get_stay(stay_id):
    caller = middleware.require(ADMIN, AUDITOR, OWNER, MEMBER, AGENT)
    stay = validate.get_stay(stay_id)
    middleware.own_hotel(caller, stay["hotel_id"])
    middleware.own_member(caller, stay["member_id"])
    return support.one(stay)


@bp.route("/loyalty/stays", methods=["GET"])
def list_stays():
    caller = middleware.require(ADMIN, AUDITOR, OWNER, MEMBER, AGENT)
    middleware.scope_filter(caller, request.args)
    extra = None
    if caller.is_owner:
        extra = lambda r: r["hotel_id"] == caller.user_id
    elif caller.is_member:
        extra = lambda r: r["member_id"] == caller.user_id
    return support.listing(db.store.stays.values(),
                           ("member_id", "hotel_id", "rate_plan_id", "status"), extra)


# ---------------------------------------------------------------------------
# posting fork
# ---------------------------------------------------------------------------

@bp.route("/loyalty/stays/<stay_id>/post", methods=["POST"])
def post_stay(stay_id):
    caller = middleware.require(ADMIN, OWNER)
    stay = validate.get_stay(stay_id)
    middleware.own_hotel(caller, stay["hotel_id"])
    hotel = db.store.hotels.get(stay["hotel_id"])
    plan = _plan_of(stay)
    member = db.store.members.get(stay["member_id"])

    if stay["status"] != "PENDING_POSTING":
        raise ApiError("ERR_STAY_INVALID_STATE",
                       "Only a stay awaiting posting may be posted.")
    if hotel is None or hotel["status"] not in ("ACTIVE", "FEE_DELINQUENT"):
        raise ApiError("ERR_HOTEL_NOT_ACTIVE",
                       "The property must be ACTIVE or FEE_DELINQUENT to post a stay.")
    if db.clock_date() < db.parse_date(stay["checkout_date"]):
        raise ApiError("ERR_STAY_NOT_COMPLETED")

    qualifying = bool(plan.get("is_qualifying")) and stay["room_revenue_cents"] > 0

    if qualifying:
        base = calc.stay_base_points(stay["room_revenue_cents"], plan)
        bonus, multiplier = calc.elite_bonus_points(base, stay["tier_at_checkin"])
        stay["status"] = "POSTED_QUALIFYING"
        stay["base_points_awarded"] = base
        stay["bonus_points_awarded"] = bonus
        stay["bonus_multiplier_applied"] = calc.as_float(multiplier)
        stay["program_fee_assessed_cents"] = calc.program_fee_assessment(
            stay["room_revenue_cents"], plan, hotel)
        db.touch(stay)

        derive.add_entry(stay["member_id"], "EARN_BASE", base, source_stay_id=stay["id"])
        if bonus > 0:
            derive.add_entry(stay["member_id"], "EARN_BONUS", bonus,
                             source_stay_id=stay["id"])
        if member is not None:
            derive.recompute_member(member)
        derive.recompute_hotel(hotel)
        derive.evaluate_delinquency(hotel)
        derive.synthesize_obligations(stay, hotel)
        derive.recompute_fund()
    else:
        stay["status"] = "POSTED_NON_QUALIFYING"
        stay["base_points_awarded"] = 0
        stay["bonus_points_awarded"] = 0
        stay["bonus_multiplier_applied"] = 0.00
        stay["program_fee_assessed_cents"] = 0
        db.touch(stay)
        derive.recompute_hotel(hotel)

    return support.one(stay)


@bp.route("/loyalty/stays/<stay_id>/dispute", methods=["POST"])
def dispute_stay(stay_id):
    caller = middleware.require(MEMBER, AGENT, ADMIN)
    stay = validate.get_stay(stay_id)
    middleware.own_member(caller, stay["member_id"])
    payload = validate.body()
    reason = validate.req_str(payload, "dispute_reason", 1)
    if stay["status"] not in ("POSTED_QUALIFYING", "POSTED_NON_QUALIFYING"):
        raise ApiError("ERR_STAY_INVALID_STATE",
                       "Only a posted stay may be disputed.")
    stay["status"] = "DISPUTED"
    stay["dispute_reason"] = reason
    db.touch(stay)
    member = db.store.members.get(stay["member_id"])
    if member is not None:
        derive.recompute_member(member)
    return support.one(stay)


@bp.route("/loyalty/stays/<stay_id>/adjust", methods=["POST"])
def adjust_stay(stay_id):
    middleware.require(ADMIN)
    stay = validate.get_stay(stay_id)
    payload = validate.body()
    revised = validate.opt_int(payload, "room_revenue_cents")
    if revised is not None:
        validate.int_min("room_revenue_cents", revised, 0)
    hotel = db.store.hotels.get(stay["hotel_id"])
    if hotel is None or hotel["status"] == "TERMINATED":
        raise ApiError("ERR_HOTEL_NOT_ACTIVE",
                       "A terminated property cannot have its stays adjusted.")
    if stay["status"] != "DISPUTED":
        raise ApiError("ERR_STAY_INVALID_STATE",
                       "Only a disputed stay may be adjusted.")

    plan = _plan_of(stay)
    member = db.store.members.get(stay["member_id"])
    if revised is not None:
        stay["room_revenue_cents"] = revised

    old_base = stay["base_points_awarded"]
    old_bonus = stay["bonus_points_awarded"]
    new_base = calc.stay_base_points(stay["room_revenue_cents"], plan)
    tier_now = member["elite_tier"] if member is not None else "BASE"
    new_bonus, multiplier = calc.elite_bonus_points(new_base, tier_now)
    if new_base == 0:
        multiplier = calc.dec("0.00")

    stay["status"] = "ADJUSTED"
    stay["base_points_awarded"] = new_base
    stay["bonus_points_awarded"] = new_bonus
    stay["bonus_multiplier_applied"] = calc.as_float(multiplier)
    stay["program_fee_assessed_cents"] = calc.program_fee_assessment(
        stay["room_revenue_cents"], plan, hotel)
    db.touch(stay)

    if new_base - old_base != 0:
        derive.add_entry(stay["member_id"], "EARN_BASE", new_base - old_base,
                         source_stay_id=stay["id"])
    if new_bonus - old_bonus != 0:
        derive.add_entry(stay["member_id"], "EARN_BONUS", new_bonus - old_bonus,
                         source_stay_id=stay["id"])

    if member is not None:
        derive.recompute_member(member)
    derive.recompute_hotel(hotel)
    derive.evaluate_delinquency(hotel)
    derive.recompute_fund()
    return support.one(stay)


@bp.route("/loyalty/stays/<stay_id>/void", methods=["POST"])
def void_stay(stay_id):
    middleware.require(ADMIN)
    stay = validate.get_stay(stay_id)
    payload = validate.body()
    reason = validate.req_str(payload, "void_reason", 1)
    if stay["status"] == "VOID":
        raise ApiError("ERR_STAY_INVALID_STATE", "The stay is already void.")

    member = db.store.members.get(stay["member_id"])
    hotel = db.store.hotels.get(stay["hotel_id"])

    # hop one
    stay["status"] = "VOID"
    stay["void_reason"] = reason
    db.touch(stay)

    # hop two - every entry this stay produced is reversed
    derive.reverse_entries(derive.entries_for_stay(stay["id"]))

    # hop three - the member's derived figures and tier are re-derived
    if member is not None:
        derive.recompute_member(member)
        # hop four - a tier fall waives obligations the new tier no longer earns
        touched = derive.waive_obligations_no_longer_entitled(member)
    else:
        touched = set()

    # and independently: this stay's own live obligations cannot outlive it
    for delivery in derive.deliveries_for_stay(stay["id"]):
        if delivery["status"] in ("OBLIGATED", "ESCALATED"):
            delivery["status"] = "WAIVED"
            db.touch(delivery)
    touched.add(stay["hotel_id"])

    for hotel_id in touched:
        other = db.store.hotels.get(hotel_id)
        if other is not None:
            derive.recompute_hotel(other)
    derive.recompute_fund()
    return support.one(stay)


# ---------------------------------------------------------------------------
# elite benefit obligations
# ---------------------------------------------------------------------------

def _delivery_stay(delivery):
    return db.store.stays.get(delivery["stay_id"]) or {}


@bp.route("/loyalty/elite-benefit-deliveries/<delivery_id>", methods=["GET"])
def get_delivery(delivery_id):
    caller = middleware.require(ADMIN, AUDITOR, OWNER, MEMBER, AGENT)
    delivery = validate.get_delivery(delivery_id)
    stay = _delivery_stay(delivery)
    middleware.own_hotel(caller, stay.get("hotel_id"))
    middleware.own_member(caller, stay.get("member_id"))
    return support.one(delivery)


@bp.route("/loyalty/elite-benefit-deliveries", methods=["GET"])
def list_deliveries():
    caller = middleware.require(ADMIN, AUDITOR, OWNER, MEMBER, AGENT)
    extra = None
    if caller.is_owner:
        extra = lambda d: _delivery_stay(d).get("hotel_id") == caller.user_id
    elif caller.is_member:
        extra = lambda d: _delivery_stay(d).get("member_id") == caller.user_id
    return support.listing(db.store.deliveries.values(),
                           ("stay_id", "status", "benefit_type"), extra)


@bp.route("/loyalty/elite-benefit-deliveries/<delivery_id>/deliver", methods=["POST"])
def deliver_benefit(delivery_id):
    caller = middleware.require(ADMIN, OWNER)
    delivery = validate.get_delivery(delivery_id)
    stay = _delivery_stay(delivery)
    middleware.own_hotel(caller, stay.get("hotel_id"))
    hotel = db.store.hotels.get(stay.get("hotel_id"))

    if stay.get("status") != "POSTED_QUALIFYING":
        raise ApiError("ERR_STAY_INVALID_STATE",
                       "The originating stay is no longer in POSTED_QUALIFYING.")
    if delivery["status"] != "OBLIGATED":
        raise ApiError("ERR_DELIVERY_INVALID_STATE",
                       "Only an OBLIGATED benefit may be recorded as delivered.")

    delivery["status"] = "DELIVERED"
    delivery["cost_recovery_cents"] = calc.benefit_cost_recovery(
        delivery["benefit_type"], hotel or {}, stay)
    db.touch(delivery)
    if hotel is not None:
        derive.recompute_hotel(hotel)
    return support.one(delivery)


@bp.route("/loyalty/elite-benefit-deliveries/<delivery_id>/deny", methods=["POST"])
def deny_benefit(delivery_id):
    caller = middleware.require(ADMIN, OWNER)
    delivery = validate.get_delivery(delivery_id)
    stay = _delivery_stay(delivery)
    middleware.own_hotel(caller, stay.get("hotel_id"))
    payload = validate.body()
    reason = validate.req_str(payload, "denial_reason", 1)
    hotel = db.store.hotels.get(stay.get("hotel_id"))

    if stay.get("status") != "POSTED_QUALIFYING":
        raise ApiError("ERR_STAY_INVALID_STATE",
                       "The originating stay is no longer in POSTED_QUALIFYING.")
    if delivery["status"] != "OBLIGATED":
        raise ApiError("ERR_DELIVERY_INVALID_STATE",
                       "Only an OBLIGATED benefit may be denied.")
    if hotel is not None and hotel["benefit_denial_count"] >= calc.BENEFIT_DENIAL_LIMIT:
        raise ApiError("ERR_BENEFIT_DENIAL_LIMIT_EXCEEDED")

    delivery["status"] = "DENIED"
    delivery["denial_reason"] = reason
    delivery["cost_recovery_cents"] = 0
    db.touch(delivery)
    if hotel is not None:
        derive.recompute_hotel(hotel)
    return support.one(delivery)
