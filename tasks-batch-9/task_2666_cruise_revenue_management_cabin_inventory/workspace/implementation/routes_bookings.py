"""Bookings: the fare buildup, the money dimension, cancellation and settlement."""

from flask import Blueprint

import calcs
import cascade
import shape
import store
from auth import actor, require_booking_owner
from envelope import created, list_response, object_response
from errors import ApiError

bp = Blueprint("bookings", __name__)

READ_ROLES = ("RevenueManager", "ReservationAgent", "GroupSalesAgent", "Guest")
LIST_ROLES = ("RevenueManager", "ReservationAgent", "GroupSalesAgent")
LEDGER_ROLES = ("RevenueManager", "ReservationAgent", "Guest")
SELLING_STATUSES = ("OPEN_FOR_SALE", "SALES_SUSPENDED")
PAYMENT_KINDS = ("DEPOSIT", "FINAL_PAYMENT", "PARTIAL", "UPGRADE_CHARGE", "REFUND")
CANCELLABLE = ("WAITLISTED", "OPTION", "CONFIRMED")


def _audience_matches(promotion, guest, group_block_id):
    audience = promotion["audience"]
    if audience == "GENERAL":
        return True
    if audience == "REPEAT_GUEST":
        return guest["loyalty_tier"] != "NONE"
    if audience == "GROUP":
        return group_block_id is not None
    return False


def _promo_window_current(promotion, now):
    starts_on = store.parse_iso(promotion["starts_on"])
    ends_on = store.parse_iso(promotion["ends_on"])
    return (starts_on is not None and ends_on is not None
            and starts_on <= now <= ends_on)


@bp.post("/bookings")
def create_booking():
    user_id, _role = actor("ReservationAgent")
    data = shape.body()

    sailing_id = shape.req_str(data, "sailing_id")
    cabin_category_id = shape.req_str(data, "cabin_category_id")
    guest_id = shape.req_str(data, "guest_id")
    occupancy_adults = shape.req_int(data, "occupancy_adults", allowed=(1, 2))
    third_berth_guests = shape.opt_int(data, "third_berth_guests", 0, allowed=(0, 1))
    fourth_berth_guests = shape.opt_int(data, "fourth_berth_guests", 0, allowed=(0, 1))
    group_block_id = shape.opt_ref(data, "group_block_id")
    promotion_id = shape.opt_ref(data, "promotion_id")
    allow_waitlist = shape.opt_bool(data, "allow_waitlist", False)

    # Tier 6, in the declared field order.
    sailing = cascade.sailing_or_404(sailing_id)
    category = cascade.category_or_404(cabin_category_id)
    guest = cascade.guest_or_404(guest_id)
    block = cascade.block_or_404(group_block_id) if group_block_id else None
    promotion = cascade.promotion_or_404(promotion_id) if promotion_id else None

    # Tier 11: only a selling voyage takes new business.
    if sailing["status"] not in SELLING_STATUSES:
        raise ApiError("ERR_SAILING_NOT_OPEN")

    # Tier 12: the party must fit the cabin.
    guest_count = occupancy_adults + third_berth_guests + fourth_berth_guests
    if guest_count > category["max_occupancy"] or occupancy_adults > category["lower_berths"]:
        raise ApiError("ERR_MAX_OCCUPANCY_EXCEEDED")

    # Tier 13: berths fill in order.
    if fourth_berth_guests == 1 and third_berth_guests == 0:
        raise ApiError("ERR_BERTH_SEQUENCE_INVALID")

    # Tier 15: pin the fare window at the sale instant.
    now = store.now_dt()
    booked_days_to_sail = store.days_to_sail(
        store.parse_iso(sailing["embark_date"]), now)
    rule = cascade.rule_for_window(sailing_id, cabin_category_id, booked_days_to_sail)
    if rule is None:
        raise ApiError("ERR_NO_FARE_RULE_FOR_WINDOW")

    # Tier 17: audience, then block coherence, then category presence.
    if promotion is not None and not _audience_matches(promotion, guest, group_block_id):
        raise ApiError("ERR_PROMO_AUDIENCE_MISMATCH")
    if block is not None and (block["sailing_id"] != sailing_id
                             or block["cabin_category_id"] != cabin_category_id):
        raise ApiError("ERR_GROUP_BLOCK_MISMATCH")
    inv = cascade.inventory_for(sailing_id, cabin_category_id)
    if inv is None:
        raise ApiError("ERR_CATEGORY_NOT_ON_SAILING")

    # Tier 18: a FROZEN sailing sells only onto the waitlist.
    waitlisted = False
    if sailing["inventory_posture"] == "FROZEN":
        if not allow_waitlist:
            raise ApiError("ERR_POSTURE_FROZEN")
        if block is None:
            waitlisted = True

    # Tier 19: capacity, on the fence for a group pickup and on the allotment otherwise.
    if block is not None:
        if block["cabins_held"] - block["picked_up_cabins"] < 1:
            raise ApiError("ERR_GROUP_BLOCK_EXHAUSTED")
    elif not waitlisted and inv["available_cabins"] < 1:
        if not allow_waitlist:
            raise ApiError("ERR_CATEGORY_SOLD_OUT")
        waitlisted = True

    # Tier 20: the quoted campaign must be live and unexhausted.
    if promotion is not None:
        if promotion["status"] != "ACTIVE" or not _promo_window_current(promotion, now):
            raise ApiError("ERR_PROMOTION_NOT_ACTIVE")
        if promotion["redemption_count"] >= promotion["max_redemptions"]:
            raise ApiError("ERR_PROMO_EXHAUSTED")

    money = calcs.fare_buildup(
        rule, occupancy_adults, third_berth_guests, fourth_berth_guests,
        promotion["discount_pct"] if promotion is not None else 0,
        guest["repeat_guest_offer_pct"],
    )

    embark = store.parse_iso(sailing["embark_date"])
    final_due = store.add_days(embark, -sailing["final_payment_days_before"])
    deposit_due = store.add_days(now, sailing["deposit_due_days_after_booking"])
    deposit_cents = money["deposit_due_cents"]
    if booked_days_to_sail <= sailing["final_payment_days_before"]:
        payment_terms = "FULL_AT_BOOKING"
        deposit_cents = money["net_ticket_cents"]
        deposit_due = now
        final_due = now
    else:
        payment_terms = "STANDARD"

    row = store.stamp_new({})
    row.update({
        "sailing_id": sailing["id"],
        "cabin_category_id": category["id"],
        "assigned_cabin_category_id": category["id"],
        "guest_id": guest["id"],
        "group_block_id": block["id"] if block is not None else None,
        "promotion_id": promotion["id"] if promotion is not None else None,
        "fare_rule_id": rule["id"],
        "pinned_fare_rule_version": rule["version"],
        "occupancy_adults": occupancy_adults,
        "third_berth_guests": third_berth_guests,
        "fourth_berth_guests": fourth_berth_guests,
        "guest_count": guest_count,
        "allow_waitlist": allow_waitlist,
        "booking_status": "WAITLISTED" if waitlisted else "OPTION",
        "payment_status": "AWAITING_DEPOSIT",
        "booked_days_to_sail": booked_days_to_sail,
        "lower_berth_subtotal_cents": money["lower_berth_subtotal_cents"],
        "berth_discount_pct": money["berth_discount_pct"],
        "third_berth_net_cents": money["third_berth_net_cents"],
        "fourth_berth_net_cents": money["fourth_berth_net_cents"],
        "gross_ticket_cents": money["gross_ticket_cents"],
        "promo_discount_cents": money["promo_discount_cents"],
        "loyalty_discount_cents": money["loyalty_discount_cents"],
        "net_ticket_cents": money["net_ticket_cents"],
        "upgrade_charge_cents": 0,
        "itinerary_compensation_obc_cents": 0,
        "itinerary_refund_cents": 0,
        "amount_paid_cents": 0,
        "balance_due_cents": money["net_ticket_cents"],
        "deposit_due_cents": deposit_cents,
        "deposit_due_date": store.iso(deposit_due),
        "final_payment_due_date": store.iso(final_due),
        "payment_terms": payment_terms,
        "provisional_penalty_cents": None,
        "cancellation_penalty_cents": None,
        "refund_cents": None,
        "cancelled_at": None,
        "cancel_reason": None,
        "settled_at": None,
        "delinquent_since": None,
        "projected_onboard_gross_cents": 0,
        "projected_onboard_net_cents": 0,
        "created_by_user_id": user_id,
    })
    cascade.recompute_onboard(row, sailing)
    store.bookings[row["id"]] = row

    # A pinned fare is never unpinned, so this audit counter only ever rises.
    rule["bookings_pinned_count"] = rule["bookings_pinned_count"] + 1
    store.touch(rule)
    if promotion is not None:
        cascade.redeem_promotion(promotion)
    cascade.recompute_guest(guest, bump=True)
    cascade.recompute_inventory(inv, bump=True)
    cascade.recompute_sailing(sailing, bump=True)
    return created(row)


@bp.get("/bookings/<booking_id>")
def read_booking(booking_id):
    user_id, role = actor(*READ_ROLES)
    booking = cascade.booking_or_404(booking_id)
    # Tier 7: a Guest sees only their own booking.
    require_booking_owner(role, user_id, booking)
    return object_response(booking)


@bp.get("/bookings")
def list_bookings():
    actor(*LIST_ROLES)
    limit, offset = shape.pagination()
    filters = {
        "sailing_id": shape.filter_str("sailing_id"),
        "cabin_category_id": shape.filter_str("cabin_category_id"),
        "assigned_cabin_category_id": shape.filter_str("assigned_cabin_category_id"),
        "guest_id": shape.filter_str("guest_id"),
        "group_block_id": shape.filter_str("group_block_id"),
        "promotion_id": shape.filter_str("promotion_id"),
        "fare_rule_id": shape.filter_str("fare_rule_id"),
        "booking_status": shape.filter_str("booking_status"),
        "payment_status": shape.filter_str("payment_status"),
    }

    rows = []
    for row in store.bookings.values():
        keep = True
        for field, wanted in filters.items():
            if wanted is not None and row.get(field) != wanted:
                keep = False
                break
        if keep:
            rows.append(row)
    rows.sort(key=lambda r: r["created_at"])
    return list_response(rows, limit, offset)


@bp.post("/bookings/<booking_id>/confirm")
def confirm_booking(booking_id):
    actor("ReservationAgent")
    shape.body()
    booking = cascade.booking_or_404(booking_id)

    # Tier 10: the inventory dimension must sit in OPTION.
    if booking["booking_status"] != "OPTION":
        raise ApiError("ERR_BOOKING_NOT_IN_OPTION")

    # Tier 11: sailing, then the group block, then the deposit.
    sailing = store.sailings.get(booking["sailing_id"])
    if sailing is None or sailing["status"] != "OPEN_FOR_SALE":
        raise ApiError("ERR_SAILING_NOT_OPEN")
    block_id = booking.get("group_block_id")
    if block_id:
        block = store.group_blocks.get(block_id)
        if block is None or block["status"] != "DEFINITE":
            raise ApiError("ERR_GROUP_BLOCK_NOT_DEFINITE")
    if booking["payment_status"] not in ("DEPOSIT_PAID", "PAID_IN_FULL"):
        raise ApiError("ERR_DEPOSIT_NOT_PAID")

    booking["booking_status"] = "CONFIRMED"
    store.touch(booking)
    cascade.recompute_sailing(sailing, bump=True)
    return object_response(booking)


@bp.post("/bookings/<booking_id>/payments")
def post_payment(booking_id):
    actor("ReservationAgent")
    data = shape.body()
    kind = shape.req_enum(data, "kind", PAYMENT_KINDS)
    amount = shape.req_int(data, "amount_cents", minimum=1)
    booking = cascade.booking_or_404(booking_id)

    # Tier 10: a dead booking takes no money at all.
    if booking["booking_status"] in ("CANCELLED", "SAILED"):
        raise ApiError("ERR_BOOKING_NOT_ACTIVE")

    status = booking["payment_status"]
    active = booking["booking_status"] in ("OPTION", "CONFIRMED")
    if kind == "DEPOSIT":
        allowed = active and status in ("AWAITING_DEPOSIT", "DELINQUENT")
    elif kind in ("FINAL_PAYMENT", "PARTIAL"):
        allowed = active and status in ("DEPOSIT_PAID", "DELINQUENT")
    else:
        # UPGRADE_CHARGE and REFUND are server-created only.
        allowed = False
    if not allowed:
        raise ApiError("ERR_PAYMENT_STATE_INVALID")

    now = store.now_dt()
    balance = booking["balance_due_cents"]

    # Tier 16: the final-payment deadline, with the grace window on the cure path.
    if kind == "FINAL_PAYMENT":
        if status == "DELINQUENT":
            since = store.parse_iso(booking["delinquent_since"])
            if since is not None and now >= store.add_days(
                    since, calcs.DELINQUENCY_GRACE_DAYS):
                raise ApiError("ERR_FINAL_PAYMENT_OVERDUE")
        else:
            due = store.parse_iso(booking["final_payment_due_date"])
            if due is not None and now > due:
                raise ApiError("ERR_FINAL_PAYMENT_OVERDUE")

    # Tier 20: money gates, last.
    if kind == "DEPOSIT":
        if amount < booking["deposit_due_cents"]:
            raise ApiError("ERR_DEPOSIT_BELOW_MINIMUM")
        if amount > balance:
            raise ApiError("ERR_PAYMENT_EXCEEDS_BALANCE")
    elif kind == "FINAL_PAYMENT":
        if amount > balance:
            raise ApiError("ERR_PAYMENT_EXCEEDS_BALANCE")
        if amount < balance:
            raise ApiError("ERR_FINAL_PAYMENT_SHORT")
    else:
        if amount >= balance:
            raise ApiError("ERR_PAYMENT_EXCEEDS_BALANCE")

    if kind == "DEPOSIT":
        target = (booking["net_ticket_cents"] + booking["upgrade_charge_cents"]
                  - booking["itinerary_refund_cents"])
        resulting = "DEPOSIT_PAID" if booking["amount_paid_cents"] + amount < target \
            else "PAID_IN_FULL"
        booking["delinquent_since"] = None
    elif kind == "FINAL_PAYMENT":
        resulting = "PAID_IN_FULL"
        booking["delinquent_since"] = None
    else:
        resulting = "DEPOSIT_PAID"

    event = cascade.append_payment_event(booking, kind, amount, resulting)
    booking["payment_status"] = resulting
    cascade.recompute_booking_money(booking)
    store.touch(booking)

    sailing = store.sailings.get(booking["sailing_id"])
    if sailing is not None:
        cascade.recompute_sailing(sailing, bump=True)
    return created(event)


@bp.get("/bookings/<booking_id>/payment-events")
def list_payment_events(booking_id):
    user_id, role = actor(*LEDGER_ROLES)
    booking = cascade.booking_or_404(booking_id)
    require_booking_owner(role, user_id, booking)
    limit, offset = shape.pagination()
    kind = shape.filter_str("kind")

    rows = [e for e in cascade.events_of(booking["id"])
            if kind is None or e["kind"] == kind]
    rows.sort(key=lambda e: (e["posted_at"], e["created_at"]))
    return list_response(rows, limit, offset)


@bp.post("/bookings/<booking_id>/cancel")
def cancel_booking_endpoint(booking_id):
    user_id, role = actor("ReservationAgent", "Guest")
    data = shape.body()
    reason = shape.req_str(data, "reason")
    booking = cascade.booking_or_404(booking_id)

    # Tier 7 before any state check, so nothing leaks about another guest's booking.
    require_booking_owner(role, user_id, booking)

    # Tier 10.
    if booking["booking_status"] not in CANCELLABLE:
        raise ApiError("ERR_BOOKING_NOT_ACTIVE")

    sailing = store.sailings.get(booking["sailing_id"])
    # The PROVISIONAL evaluation is a disclosure quote: no money moves here.
    if booking["booking_status"] == "WAITLISTED":
        provisional = 0
    else:
        provisional = calcs.penalty_cents(
            booking["net_ticket_cents"], booking["upgrade_charge_cents"],
            store.days_to_sail(store.parse_iso(sailing["embark_date"]), store.now_dt())
            if sailing is not None else 0)

    cascade.cancel_booking(booking, sailing, reason, provisional_cents=provisional,
                           final_cents=None, assess_payment=True)
    if sailing is not None:
        # The freed cabin is NOT offered to the waitlist here; it waits for a sweep.
        cascade.recompute_inventories_of(sailing["id"], bump=True)
        cascade.recompute_sailing(sailing, bump=True)
    return object_response(booking)


@bp.post("/bookings/<booking_id>/settle-cancellation")
def settle_cancellation(booking_id):
    actor("RevenueManager")
    shape.body()
    booking = cascade.booking_or_404(booking_id)

    # Tier 10: only a cancelled booking carrying an assessed penalty settles.
    if booking["payment_status"] != "PENALTY_ASSESSED" \
            or booking["booking_status"] != "CANCELLED":
        raise ApiError("ERR_BOOKING_NOT_AWAITING_SETTLEMENT")

    sailing = store.sailings.get(booking["sailing_id"])
    days = store.days_to_sail(
        store.parse_iso(sailing["embark_date"]), store.now_dt()) if sailing else 0
    # The FINAL evaluation runs at the settlement instant and is the one that pays.
    final = 0 if booking["cancel_reason"] == "INVENTORY_CLOSED" else calcs.penalty_cents(
        booking["net_ticket_cents"], booking["upgrade_charge_cents"], days)
    booking["cancellation_penalty_cents"] = final

    refund = max(0, booking["amount_paid_cents"] - final)
    booking["refund_cents"] = refund
    if refund > 0:
        cascade.append_payment_event(
            booking, "REFUND", refund, "REFUNDED", note="CANCELLATION_SETTLEMENT")
    booking["payment_status"] = "REFUNDED"
    booking["settled_at"] = store.now_iso()
    cascade.recompute_booking_money(booking)
    store.touch(booking)
    return object_response(booking)


@bp.post("/bookings/<booking_id>/assign-guarantee")
def assign_guarantee(booking_id):
    actor("ReservationAgent")
    data = shape.body()
    target_id = shape.req_str(data, "assigned_cabin_category_id")
    booking = cascade.booking_or_404(booking_id)

    # Tier 6: the named category must resolve.
    target = cascade.category_or_404(target_id)

    # Tier 10.
    if booking["booking_status"] not in ("OPTION", "CONFIRMED"):
        raise ApiError("ERR_BOOKING_NOT_ACTIVE")

    sailing_id = booking["sailing_id"]
    source_category = store.cabin_categories.get(booking["assigned_cabin_category_id"])
    target_inv = cascade.inventory_for(sailing_id, target_id)
    sold_guarantee = bool(store.cabin_categories.get(
        booking["cabin_category_id"], {}).get("is_guarantee"))

    # Tier 19: the named allotment must have room (only once it exists at all).
    if target_inv is not None and sold_guarantee and not target["is_guarantee"]:
        if target_inv["available_cabins"] < 1:
            raise ApiError("ERR_TARGET_CATEGORY_UNAVAILABLE")

    # Tier 20: a guarantee booking may only resolve onto a named category here.
    if not sold_guarantee or target["is_guarantee"] or target_inv is None:
        raise ApiError("ERR_NOT_GUARANTEE_BOOKING")

    sailing = store.sailings.get(sailing_id)
    # The guarantee fare is honoured: net_ticket_cents does not move.
    booking["assigned_cabin_category_id"] = target["id"]
    cascade.recompute_onboard(booking, sailing)
    store.touch(booking)

    source_inv = None
    if source_category is not None:
        source_inv = cascade.inventory_for(sailing_id, source_category["id"])
    if source_inv is not None:
        cascade.recompute_inventory(source_inv, bump=True)
    cascade.recompute_inventory(target_inv, bump=True)
    if sailing is not None:
        cascade.recompute_sailing(sailing, bump=True)
    return object_response(booking)
