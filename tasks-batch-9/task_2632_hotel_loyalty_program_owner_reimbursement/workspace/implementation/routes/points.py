"""Point-sale partners, point purchases, the programme fund and the clock."""

from flask import Blueprint, request

import db
import middleware
import response
import support
import validate
from errors import ApiError
from middleware import ADMIN, AGENT, AUDITOR, MEMBER, OWNER
from services import calc, derive

bp = Blueprint("points", __name__)


# ---------------------------------------------------------------------------
# partners
# ---------------------------------------------------------------------------

@bp.route("/loyalty/partners", methods=["POST"])
def create_partner():
    middleware.require(ADMIN)
    payload = validate.body()
    name = validate.req_str(payload, "name", 1, 200)
    partner_type = validate.req_enum(payload, "partner_type", calc.PARTNER_TYPES)
    unit_price = validate.req_int(payload, "points_cost_per_1000_cents")
    monthly_cap = validate.req_int(payload, "monthly_cap_points")
    validate.int_min("points_cost_per_1000_cents", unit_price, 1)
    validate.int_min("monthly_cap_points", monthly_cap, 1000)

    record = {}
    db.stamp_full(record)
    record.update({
        "name": name,
        "partner_type": partner_type,
        "points_cost_per_1000_cents": unit_price,
        "monthly_cap_points": monthly_cap,
        "purchased_points_mtd": 0,
    })
    support.tail(record)
    db.store.partners[record["id"]] = record
    return support.created(record)


@bp.route("/loyalty/partners/<partner_id>", methods=["GET"])
def get_partner(partner_id):
    middleware.require(ADMIN, AUDITOR)
    return support.one(validate.get_partner(partner_id))


@bp.route("/loyalty/partners", methods=["GET"])
def list_partners():
    middleware.require(ADMIN, AUDITOR)
    return support.listing(db.store.partners.values(), ("partner_type",))


# ---------------------------------------------------------------------------
# point purchases
# ---------------------------------------------------------------------------

@bp.route("/loyalty/point-purchases", methods=["POST"])
def create_purchase():
    caller = middleware.require(ADMIN, AGENT, MEMBER)
    payload = validate.body()
    member_id = validate.fk(payload, "member_id")
    middleware.own_member(caller, member_id)
    member = validate.get_member(member_id)
    partner_id = validate.opt_fk(payload, "partner_id")
    partner = validate.get_partner(partner_id) if partner_id is not None else None

    channel = validate.req_enum(payload, "channel", calc.PURCHASE_CHANNELS)
    quantity = validate.req_int(payload, "points_quantity")
    validate.multiple_of("points_quantity", quantity, calc.POINT_QUANTITY_STEP,
                         calc.POINT_QUANTITY_STEP)

    if channel == "PARTNER_SALE":
        if partner is None:
            raise ApiError("ERR_PARTNER_CHANNEL_MISMATCH",
                           "A partner sale must name the buying partner.")
    elif partner is not None:
        raise ApiError("ERR_PARTNER_CHANNEL_MISMATCH",
                       "Only a partner sale may name a partner.")

    discount, cash_due, bonus = calc.point_purchase_pricing(quantity, channel, partner)

    if partner is not None:
        consumed = derive.partner_month_consumption(partner["id"])
        if consumed + quantity > partner["monthly_cap_points"]:
            raise ApiError("ERR_PARTNER_MONTHLY_CAP_EXCEEDED")
    if derive.member_purchase_consumption(member_id) + quantity \
            > calc.MEMBER_ANNUAL_PURCHASE_CAP_POINTS:
        raise ApiError("ERR_PURCHASE_CAP_EXCEEDED")

    record = {}
    db.stamp_full(record)
    record.update({
        "member_id": member_id,
        "partner_id": partner["id"] if partner is not None else None,
        "channel": channel,
        "points_quantity": quantity,
        "volume_discount_pct": calc.as_float(discount),
        "cash_due_cents": cash_due,
        "bonus_points": bonus,
        "status": "PENDING",
        "refund_reason": None,
    })
    support.tail(record)
    db.store.purchases[record["id"]] = record

    # The pending purchase already consumes both caps, so the two counters that
    # hold them are re-derived on this request (PRD 3.8).
    derive.recompute_member(member)
    if partner is not None:
        derive.recompute_partner(partner)
    return support.created(record)


@bp.route("/loyalty/point-purchases/<purchase_id>", methods=["GET"])
def get_purchase(purchase_id):
    caller = middleware.require(ADMIN, AUDITOR, AGENT, MEMBER)
    purchase = validate.get_purchase(purchase_id)
    middleware.own_member(caller, purchase["member_id"])
    return support.one(purchase)


@bp.route("/loyalty/point-purchases", methods=["GET"])
def list_purchases():
    caller = middleware.require(ADMIN, AUDITOR, AGENT, MEMBER)
    middleware.scope_filter(caller, request.args, hotel_key=None)
    extra = None
    if caller.is_member:
        extra = lambda r: r["member_id"] == caller.user_id
    return support.listing(db.store.purchases.values(),
                           ("member_id", "partner_id", "channel", "status"), extra)


@bp.route("/loyalty/point-purchases/<purchase_id>/settle", methods=["POST"])
def settle_purchase(purchase_id):
    middleware.require(ADMIN)
    purchase = validate.get_purchase(purchase_id)
    if purchase["status"] != "PENDING":
        raise ApiError("ERR_PURCHASE_INVALID_STATE",
                       "Only a pending purchase may be settled.")

    purchase["status"] = "SETTLED"
    db.touch(purchase)

    entry_type = "PARTNER_SALE" if purchase["channel"] == "PARTNER_SALE" else "PURCHASE"
    derive.add_entry(purchase["member_id"], entry_type, purchase["points_quantity"],
                     source_purchase_id=purchase["id"])
    if purchase["bonus_points"] > 0:
        derive.add_entry(purchase["member_id"], "EARN_BONUS", purchase["bonus_points"],
                         source_purchase_id=purchase["id"])

    member = db.store.members.get(purchase["member_id"])
    if member is not None:
        derive.recompute_member(member)
    if purchase["partner_id"] is not None:
        partner = db.store.partners.get(purchase["partner_id"])
        if partner is not None:
            derive.recompute_partner(partner)
    derive.recompute_fund()
    return support.one(purchase)


@bp.route("/loyalty/point-purchases/<purchase_id>/refund", methods=["POST"])
def refund_purchase(purchase_id):
    middleware.require(ADMIN, AGENT)
    purchase = validate.get_purchase(purchase_id)
    payload = validate.body()
    reason = validate.req_str(payload, "refund_reason", 1)
    if purchase["status"] != "SETTLED":
        raise ApiError("ERR_PURCHASE_INVALID_STATE",
                       "Only a settled purchase may be refunded.")

    purchase["status"] = "REFUNDED"
    purchase["refund_reason"] = reason
    db.touch(purchase)

    derive.reverse_entries(derive.entries_for_purchase(purchase["id"]))

    member = db.store.members.get(purchase["member_id"])
    if member is not None:
        derive.recompute_member(member)
    if purchase["partner_id"] is not None:
        partner = db.store.partners.get(purchase["partner_id"])
        if partner is not None:
            derive.recompute_partner(partner)
    derive.recompute_fund()
    return support.one(purchase)


# ---------------------------------------------------------------------------
# programme fund
# ---------------------------------------------------------------------------

@bp.route("/loyalty/program-fund", methods=["GET"])
def read_fund():
    middleware.require(ADMIN, AUDITOR)
    return support.one(derive.fund())


@bp.route("/loyalty/program-fund/revalue", methods=["POST"])
def revalue_fund():
    middleware.require(ADMIN, AUDITOR)
    return support.one(derive.revalue_fund(True))


@bp.route("/loyalty/program-fund/breakage-rate", methods=["POST"])
def set_breakage_rate():
    middleware.require(ADMIN)
    payload = validate.body()
    rate = validate.req_num(payload, "breakage_rate_pct")
    validate.dec_between("breakage_rate_pct", rate, calc.dec(0),
                         calc.MAX_BREAKAGE_RATE_PCT, 4)
    record = derive.fund()
    record["breakage_rate_pct"] = calc.as_float(rate)
    return support.one(derive.revalue_fund(False))


# ---------------------------------------------------------------------------
# logical clock (test support)
# ---------------------------------------------------------------------------

@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    middleware.require(ADMIN, AUDITOR, OWNER, MEMBER, AGENT)
    payload = validate.body()
    raw = validate.req_str(payload, "current_utc", 1)
    parsed = db.parse_utc(raw)
    if parsed is None:
        raise ApiError("ERR_INVALID_REQUEST",
                       "Field 'current_utc' must be an ISO 8601 UTC instant.")
    db.set_clock(parsed)
    return response.empty_response()
