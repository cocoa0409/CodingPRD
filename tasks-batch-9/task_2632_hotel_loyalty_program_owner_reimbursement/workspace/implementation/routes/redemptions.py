"""Award bookings and the owner reimbursement chain."""

import re

from flask import Blueprint, request

import db
import middleware
import support
import validate
from errors import ApiError
from middleware import ADMIN, AGENT, AUDITOR, MEMBER, OWNER
from services import calc, derive

bp = Blueprint("redemptions", __name__)

PERIOD_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")

LIVE_FULFILMENT = ("HELD", "CONFIRMED", "STAYED")


# ---------------------------------------------------------------------------
# price window resolution
# ---------------------------------------------------------------------------

def _select_pricing(hotel_id, checkin):
    candidates = []
    for row in db.store.pricing_rows.values():
        if row["hotel_id"] != hotel_id:
            continue
        start = db.parse_date(row["window_start_date"])
        end = db.parse_date(row["window_end_date"])
        if start <= checkin <= end:
            candidates.append(row)
    if not candidates:
        raise ApiError("ERR_NO_REDEMPTION_PRICING")
    candidates.sort(key=lambda r: (0 if r["season"] == "PEAK" else 1,
                                   r["created_at"], r["_seq"]))
    return candidates[0]


def _occupied_nights(hotel_id, exclude_id=None):
    """A map from calendar date to the number of live award bookings on it."""
    counts = {}
    for other in db.store.redemptions.values():
        if other["hotel_id"] != hotel_id or other["id"] == exclude_id:
            continue
        if other["fulfillment_status"] not in LIVE_FULFILMENT:
            continue
        for day in db.date_range_half_open(db.parse_date(other["checkin_date"]),
                                           db.parse_date(other["checkout_date"])):
            counts[day] = counts.get(day, 0) + 1
    return counts


# ---------------------------------------------------------------------------
# booking
# ---------------------------------------------------------------------------

@bp.route("/loyalty/redemptions", methods=["POST"])
def create_redemption():
    caller = middleware.require(ADMIN, AGENT, MEMBER)
    payload = validate.body()
    member_id = validate.fk(payload, "member_id")
    middleware.own_member(caller, member_id)
    hotel = validate.get_hotel(validate.fk(payload, "hotel_id"))
    member = validate.get_member(member_id)

    checkin = validate.req_date(payload, "checkin_date")
    checkout = validate.req_date(payload, "checkout_date")
    expected_version = validate.req_int(payload, "expected_hotel_version")
    validate.range_stay(checkin, checkout)

    nights = db.nights_between(checkin, checkout)
    row = _select_pricing(hotel["id"], checkin)
    season = row["season"]
    points_charged = calc.redemption_points_price(
        row["points_per_night"], nights, season, member["elite_tier"],
        hotel["market_tier"])

    if expected_version != hotel["version"]:
        raise ApiError("ERR_STALE_HOTEL_VERSION")
    if hotel["status"] not in ("ACTIVE", "FEE_DELINQUENT"):
        raise ApiError("ERR_HOTEL_NOT_ACTIVE",
                       "The property must be ACTIVE or FEE_DELINQUENT to take award bookings.")
    if season == "PEAK" and hotel["status"] == "FEE_DELINQUENT":
        raise ApiError("ERR_PEAK_INVENTORY_WITHHELD")

    stay_nights = list(db.date_range_half_open(checkin, checkout))

    for window in db.store.blackout_windows.values():
        if window["hotel_id"] != hotel["id"] or window["status"] != "ACTIVE":
            continue
        if window["scope"] == "STANDARD_ONLY" and season != "STANDARD":
            continue
        start = db.parse_date(window["start_date"])
        end = db.parse_date(window["end_date"])
        if any(start <= day <= end for day in stay_nights):
            raise ApiError("ERR_BLACKOUT_DATE_UNAVAILABLE")

    for other in db.store.redemptions.values():
        if other["member_id"] != member_id:
            continue
        if other["fulfillment_status"] not in LIVE_FULFILMENT:
            continue
        if (checkin < db.parse_date(other["checkout_date"])
                and db.parse_date(other["checkin_date"]) < checkout):
            raise ApiError("ERR_MEMBER_REDEMPTION_OVERLAP")

    allotment = row["award_allotment_per_night"]
    occupied = _occupied_nights(hotel["id"])
    for day in stay_nights:
        if occupied.get(day, 0) + 1 > allotment:
            raise ApiError("ERR_AWARD_INVENTORY_UNAVAILABLE")

    if calc.tier_rank(member["elite_tier"]) < calc.tier_rank(row["min_tier_required"]):
        raise ApiError("ERR_TIER_BELOW_INVENTORY_MINIMUM")
    if member["point_balance"] < points_charged:
        raise ApiError("ERR_INSUFFICIENT_POINTS")
    if season == "PEAK" and derive.fund_is_impaired():
        raise ApiError("ERR_FUND_IMPAIRED_PEAK_BLOCKED")

    record = {}
    db.stamp_full(record)
    record.update({
        "member_id": member_id,
        "hotel_id": hotel["id"],
        "batch_id": None,
        "checkin_date": db.date_str(checkin),
        "checkout_date": db.date_str(checkout),
        "nights": nights,
        "season": season,
        "points_per_night_applied": row["points_per_night"],
        "award_allotment_applied": allotment,
        "points_charged": points_charged,
        "cash_copay_cents": row["cash_copay_cents"] * nights,
        "fulfillment_status": "HELD",
        "reimbursement_status": "NOT_DUE",
        "estimated_reimbursement_cents": 0,
        "settled_reimbursement_cents": 0,
        "cancel_reason": None,
    })
    support.tail(record)
    db.store.redemptions[record["id"]] = record

    derive.add_entry(member_id, "REDEEM", -points_charged,
                     source_redemption_id=record["id"])
    derive.recompute_member(member)
    db.touch(hotel)
    derive.recompute_fund()
    return support.created(record)


@bp.route("/loyalty/redemptions/<redemption_id>", methods=["GET"])
def get_redemption(redemption_id):
    caller = middleware.require(ADMIN, AUDITOR, OWNER, MEMBER, AGENT)
    booking = validate.get_redemption(redemption_id)
    middleware.own_hotel(caller, booking["hotel_id"])
    middleware.own_member(caller, booking["member_id"])
    return support.one(booking)


@bp.route("/loyalty/redemptions", methods=["GET"])
def list_redemptions():
    caller = middleware.require(ADMIN, AUDITOR, OWNER, MEMBER, AGENT)
    middleware.scope_filter(caller, request.args)
    extra = None
    if caller.is_owner:
        extra = lambda r: r["hotel_id"] == caller.user_id
    elif caller.is_member:
        extra = lambda r: r["member_id"] == caller.user_id
    return support.listing(
        db.store.redemptions.values(),
        ("member_id", "hotel_id", "batch_id", "fulfillment_status",
         "reimbursement_status"),
        extra)


# ---------------------------------------------------------------------------
# the fulfilment dimension
# ---------------------------------------------------------------------------

@bp.route("/loyalty/redemptions/<redemption_id>/confirm", methods=["POST"])
def confirm_redemption(redemption_id):
    caller = middleware.require(ADMIN, AGENT, MEMBER)
    booking = validate.get_redemption(redemption_id)
    middleware.own_member(caller, booking["member_id"])
    hotel = db.store.hotels.get(booking["hotel_id"])
    if booking["fulfillment_status"] != "HELD":
        raise ApiError("ERR_REDEMPTION_INVALID_STATE",
                       "Only a held award booking may be confirmed.")
    if hotel is None or hotel["status"] not in ("ACTIVE", "FEE_DELINQUENT"):
        raise ApiError("ERR_HOTEL_NOT_ACTIVE",
                       "The property must be ACTIVE or FEE_DELINQUENT to confirm a booking.")
    booking["fulfillment_status"] = "CONFIRMED"
    db.touch(booking)
    return support.one(booking)


@bp.route("/loyalty/redemptions/<redemption_id>/complete-stay", methods=["POST"])
def complete_redemption(redemption_id):
    caller = middleware.require(ADMIN, OWNER)
    booking = validate.get_redemption(redemption_id)
    middleware.own_hotel(caller, booking["hotel_id"])
    hotel = db.store.hotels.get(booking["hotel_id"])
    if booking["fulfillment_status"] != "CONFIRMED":
        raise ApiError("ERR_REDEMPTION_INVALID_STATE",
                       "Only a confirmed award booking may be completed.")
    if db.clock_date() < db.parse_date(booking["checkout_date"]):
        raise ApiError("ERR_REDEMPTION_NOT_ELAPSED")

    booking["fulfillment_status"] = "STAYED"
    booking["reimbursement_status"] = "ACCRUED"
    booking["estimated_reimbursement_cents"] = calc.owner_reimbursement(
        hotel["trailing_12m_occupancy_pct"], hotel["trailing_12m_adr_cents"],
        booking["nights"])
    db.touch(booking)
    derive.recompute_hotel(hotel)
    return support.one(booking)


@bp.route("/loyalty/redemptions/<redemption_id>/no-show", methods=["POST"])
def no_show_redemption(redemption_id):
    caller = middleware.require(ADMIN, OWNER)
    booking = validate.get_redemption(redemption_id)
    middleware.own_hotel(caller, booking["hotel_id"])
    if booking["fulfillment_status"] != "CONFIRMED":
        raise ApiError("ERR_REDEMPTION_INVALID_STATE",
                       "Only a confirmed award booking may be marked a no-show.")
    if db.clock_date() < db.parse_date(booking["checkin_date"]):
        raise ApiError("ERR_REDEMPTION_NOT_ARRIVED")
    booking["fulfillment_status"] = "NO_SHOW"
    db.touch(booking)
    return support.one(booking)


@bp.route("/loyalty/redemptions/<redemption_id>/cancel", methods=["POST"])
def cancel_redemption(redemption_id):
    caller = middleware.require(ADMIN, AGENT, MEMBER)
    booking = validate.get_redemption(redemption_id)
    middleware.own_member(caller, booking["member_id"])
    payload = validate.body()
    reason = validate.req_str(payload, "cancel_reason", 1)
    if booking["fulfillment_status"] not in ("HELD", "CONFIRMED"):
        raise ApiError("ERR_REDEMPTION_INVALID_STATE",
                       "Only a held or confirmed award booking may be cancelled.")

    booking["fulfillment_status"] = "CANCELLED"
    booking["cancel_reason"] = reason
    db.touch(booking)

    redeems = [e for e in derive.entries_for_redemption(booking["id"])
               if e["entry_type"] == "REDEEM"]
    derive.reverse_entries(redeems)
    member = db.store.members.get(booking["member_id"])
    if member is not None:
        derive.recompute_member(member)
    derive.recompute_fund()
    return support.one(booking)


# ---------------------------------------------------------------------------
# reimbursement batches
# ---------------------------------------------------------------------------

def _batch_items(batch):
    return db.ordered([r for r in db.store.redemptions.values()
                       if r.get("batch_id") == batch["id"]])


@bp.route("/loyalty/reimbursement-batches", methods=["POST"])
def create_batch():
    caller = middleware.require(ADMIN, OWNER)
    payload = validate.body()
    hotel_id = validate.fk(payload, "hotel_id")
    middleware.own_hotel(caller, hotel_id)
    hotel = validate.get_hotel(hotel_id)
    period = validate.req_str(payload, "period_month", 7, 7)
    if not PERIOD_RE.match(period):
        raise ApiError("ERR_INVALID_REQUEST",
                       "Field 'period_month' must be a calendar month in YYYY-MM form.")
    if hotel["status"] in ("ONBOARDING", "TERMINATED"):
        raise ApiError("ERR_HOTEL_NOT_ACTIVE",
                       "A batch may only be opened for a property in the programme.")
    for other in db.store.batches.values():
        if other["hotel_id"] != hotel_id or other["period_month"] != period:
            continue
        if other["status"] in ("OPEN", "RELEASED", "APPROVED"):
            raise ApiError("ERR_DUPLICATE_BATCH_PERIOD")

    record = {}
    db.stamp_full(record)
    record.update({
        "hotel_id": hotel_id,
        "period_month": period,
        "status": "OPEN",
        "item_count": 0,
        "gross_reimbursement_cents": 0,
        "fee_offset_base_cents": 0,
        "delinquency_surcharge_cents": 0,
        "total_fee_offset_cents": 0,
        "net_payable_cents": 0,
        "occupancy_pct_at_release": 0.0,
        "adr_cents_at_release": 0,
        "released_by_user_id": None,
        "approved_by_user_id": None,
        "rejection_reason": None,
    })
    support.tail(record)
    db.store.batches[record["id"]] = record
    return support.created(record)


@bp.route("/loyalty/reimbursement-batches/<batch_id>", methods=["GET"])
def get_batch(batch_id):
    caller = middleware.require(ADMIN, AUDITOR, OWNER)
    batch = validate.get_batch(batch_id)
    middleware.own_hotel(caller, batch["hotel_id"])
    return support.one(batch)


@bp.route("/loyalty/reimbursement-batches", methods=["GET"])
def list_batches():
    caller = middleware.require(ADMIN, AUDITOR, OWNER)
    middleware.scope_filter(caller, request.args, member_key=None)
    extra = None
    if caller.is_owner:
        extra = lambda r: r["hotel_id"] == caller.user_id
    return support.listing(db.store.batches.values(),
                           ("hotel_id", "period_month", "status"), extra)


@bp.route("/loyalty/reimbursement-batches/<batch_id>/release", methods=["POST"])
def release_batch(batch_id):
    caller = middleware.require(ADMIN)
    batch = validate.get_batch(batch_id)
    hotel = db.store.hotels.get(batch["hotel_id"])
    if batch["status"] != "OPEN":
        raise ApiError("ERR_BATCH_INVALID_STATE", "Only an OPEN batch may be released.")
    if hotel is None or hotel["status"] == "TERMINATED":
        raise ApiError("ERR_HOTEL_NOT_ACTIVE",
                       "A terminated property cannot have a batch released.")

    items = []
    for booking in db.store.redemptions.values():
        if booking["hotel_id"] != batch["hotel_id"]:
            continue
        if booking["fulfillment_status"] != "STAYED":
            continue
        if booking["reimbursement_status"] != "ACCRUED":
            continue
        if db.month_key_of(booking["checkout_date"]) != batch["period_month"]:
            continue
        items.append(booking)
    if not items:
        raise ApiError("ERR_BATCH_NO_ELIGIBLE_ITEMS")
    items = db.ordered(items)

    occupancy = hotel["trailing_12m_occupancy_pct"]
    adr = hotel["trailing_12m_adr_cents"]
    gross = 0
    for booking in items:
        booking["reimbursement_status"] = "BATCHED"
        booking["batch_id"] = batch["id"]
        booking["settled_reimbursement_cents"] = calc.owner_reimbursement(
            occupancy, adr, booking["nights"])
        gross += booking["settled_reimbursement_cents"]
        db.touch(booking)

    offset_base = hotel["fee_ledger_balance_cents"]
    surcharge, total_offset, net = calc.batch_net_payable(gross, offset_base)

    batch["status"] = "RELEASED"
    batch["occupancy_pct_at_release"] = occupancy
    batch["adr_cents_at_release"] = adr
    batch["item_count"] = len(items)
    batch["gross_reimbursement_cents"] = gross
    batch["fee_offset_base_cents"] = offset_base
    batch["delinquency_surcharge_cents"] = surcharge
    batch["total_fee_offset_cents"] = total_offset
    batch["net_payable_cents"] = net
    batch["released_by_user_id"] = caller.user_id
    db.touch(batch)
    derive.recompute_hotel(hotel)
    return support.one(batch)


@bp.route("/loyalty/reimbursement-batches/<batch_id>/approve", methods=["POST"])
def approve_batch(batch_id):
    caller = middleware.require(ADMIN)
    batch = validate.get_batch(batch_id)
    if batch["released_by_user_id"] is not None \
            and caller.user_id == batch["released_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    if batch["status"] != "RELEASED":
        raise ApiError("ERR_BATCH_INVALID_STATE",
                       "Only a released batch may be approved.")
    batch["status"] = "APPROVED"
    batch["approved_by_user_id"] = caller.user_id
    db.touch(batch)
    return support.one(batch)


@bp.route("/loyalty/reimbursement-batches/<batch_id>/reject", methods=["POST"])
def reject_batch(batch_id):
    caller = middleware.require(ADMIN)
    batch = validate.get_batch(batch_id)
    if batch["released_by_user_id"] is not None \
            and caller.user_id == batch["released_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    payload = validate.body()
    reason = validate.req_str(payload, "rejection_reason", 1)
    if batch["status"] != "RELEASED":
        raise ApiError("ERR_BATCH_INVALID_STATE",
                       "Only a released batch may be rejected.")

    for booking in _batch_items(batch):
        if booking["reimbursement_status"] != "BATCHED":
            continue
        booking["reimbursement_status"] = "ACCRUED"
        booking["batch_id"] = None
        booking["settled_reimbursement_cents"] = 0
        db.touch(booking)

    batch["status"] = "REJECTED"
    batch["rejection_reason"] = reason
    batch["item_count"] = 0
    batch["gross_reimbursement_cents"] = 0
    batch["fee_offset_base_cents"] = 0
    batch["delinquency_surcharge_cents"] = 0
    batch["total_fee_offset_cents"] = 0
    batch["net_payable_cents"] = 0
    db.touch(batch)
    hotel = db.store.hotels.get(batch["hotel_id"])
    if hotel is not None:
        derive.recompute_hotel(hotel)
    return support.one(batch)


@bp.route("/loyalty/reimbursement-batches/<batch_id>/pay", methods=["POST"])
def pay_batch(batch_id):
    caller = middleware.require(ADMIN)
    batch = validate.get_batch(batch_id)
    if caller.user_id in (batch["released_by_user_id"], batch["approved_by_user_id"]):
        raise ApiError("ERR_PAYER_CONFLICT")
    if batch["status"] != "APPROVED":
        raise ApiError("ERR_BATCH_INVALID_STATE", "Only an approved batch may be paid.")
    if derive.fund_cash() < batch["net_payable_cents"]:
        raise ApiError("ERR_FUND_INSUFFICIENT_CASH")

    # hop one - the batch is disbursed
    batch["status"] = "PAID"
    db.touch(batch)

    # hop two - the attached bookings are settled and programme cash moves
    for booking in _batch_items(batch):
        if booking["reimbursement_status"] != "BATCHED":
            continue
        booking["reimbursement_status"] = "PAID"
        db.touch(booking)

    hotel = db.store.hotels.get(batch["hotel_id"])
    if hotel is not None:
        derive.recompute_hotel(hotel)
        # hop three - a cleared fee ledger restores a delinquent property
        derive.evaluate_delinquency_cure(hotel)
    derive.recompute_fund()
    return support.one(batch)
