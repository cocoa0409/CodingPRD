"""Booking endpoints: create/price, confirm, cancel, and nested surveys."""
from datetime import timedelta

from flask import Blueprint

from db import DB, fmt_ts, new_id, now
from errors import ApiError
from middleware import ALL_ROLES, auth
from response import ok, ok_list
from services import (
    ceil_div,
    chaperone_divisor,
    lookup,
    refresh_full_open,
    school_total,
    seats_available,
    ser_booking,
    ser_survey,
    sort_items,
    stamp,
    time_tier_refund,
    touch,
    unit_price_for,
)
from util import (
    body,
    pagination_args,
    req_bool,
    req_enum,
    req_field,
    req_int,
    req_str,
)

bp = Blueprint("bookings", __name__)

BOOKING_KINDS = ("GENERAL", "MEMBER", "SCHOOL")
SCHOOL_ONLY_FIELDS = ("student_count", "chaperone_count", "grade_level", "curriculum_standard")
BOOKING_ROLES = ["MuseumAdmin", "FrontDeskStaff", "Member"]


def _paginate(items, serializer):
    limit, offset = pagination_args()
    total = len(items)
    page = items[offset : offset + limit]
    return ok_list([serializer(x) for x in page], total, limit, offset)


def _check_member_ownership(role, user_id, booking):
    if role == "Member" and booking["member_id"] != user_id:
        raise ApiError(
            "ERR_FORBIDDEN", 403, "Members may act only on their own bookings"
        )


@bp.post("/bookings")
def create_booking():
    user_id, role = auth(BOOKING_ROLES)
    data = body()
    # Tier 2 (authorization): member-creation restriction (PRD 2.1).
    if role == "Member" and (
        data.get("booking_kind") != "MEMBER" or data.get("member_id") != user_id
    ):
        raise ApiError(
            "ERR_FORBIDDEN",
            403,
            "Members may create only MEMBER bookings naming themselves",
        )
    # Tier 3 (existence): body FKs slot_id, member_id.
    raw_slot = data.get("slot_id")
    slot = lookup("slots", raw_slot) if raw_slot is not None else None
    raw_member = data.get("member_id")
    member = lookup("members", raw_member) if raw_member is not None else None
    # Tier 4 (request shape): kind discipline and field sets.
    booking_kind = req_enum(data, "booking_kind", BOOKING_KINDS)
    visitor_name = req_str(data, "visitor_name")
    if slot is None:
        raise ApiError("ERR_INVALID_REQUEST", 400, "Missing required field: slot_id")
    student_count = None
    chaperone_count = None
    grade_level = None
    curriculum_standard = None
    if booking_kind in ("GENERAL", "MEMBER"):
        party_size = req_int(data, "party_size", minimum=1)
        for field in SCHOOL_ONLY_FIELDS:
            if data.get(field) is not None:
                raise ApiError(
                    "ERR_INVALID_REQUEST",
                    400,
                    f"{field} is not allowed on {booking_kind} bookings",
                )
        if booking_kind == "MEMBER":
            if raw_member is None:
                raise ApiError(
                    "ERR_INVALID_REQUEST",
                    400,
                    "member_id is required for MEMBER bookings",
                )
        elif raw_member is not None:
            raise ApiError(
                "ERR_INVALID_REQUEST",
                400,
                "member_id must be absent for GENERAL bookings",
            )
    else:  # SCHOOL
        if data.get("party_size") is not None:
            raise ApiError(
                "ERR_INVALID_REQUEST",
                400,
                "party_size must be absent for SCHOOL bookings",
            )
        if raw_member is not None:
            raise ApiError(
                "ERR_INVALID_REQUEST",
                400,
                "member_id must be absent for SCHOOL bookings",
            )
        student_count = req_int(data, "student_count", minimum=1)
        chaperone_count = req_int(data, "chaperone_count", minimum=0)
        grade_level = req_str(data, "grade_level")
        curriculum_standard = req_str(data, "curriculum_standard")
        party_size = student_count + chaperone_count
    member_id = raw_member if booking_kind == "MEMBER" else None
    # Tier 5 (lifecycle state): the slot must be OPEN (FULL fails too).
    if slot["status"] != "OPEN":
        raise ApiError(
            "ERR_SLOT_NOT_OPEN", 409, "Bookings can be created only on OPEN slots"
        )
    route = lookup("routes", slot["route_id"])
    # Tier 7 (collection safety): HIGH_VALUE party cap, then chaperone ratio.
    hv_rooms = [
        DB["rooms"][rid]
        for rid in route["room_ids"]
        if DB["rooms"][rid]["collection_tier"] == "HIGH_VALUE"
    ]
    if hv_rooms:
        cap = min(r["safety_max_party"] for r in hv_rooms)
        if party_size > cap:
            raise ApiError(
                "ERR_SAFETY_PARTY_TOO_LARGE",
                422,
                "Party exceeds the safety_max_party of a HIGH_VALUE room",
            )
    if booking_kind == "SCHOOL":
        required = ceil_div(student_count, chaperone_divisor(route))
        if chaperone_count < required:
            raise ApiError(
                "ERR_CHAPERONE_RATIO_VIOLATION",
                422,
                "chaperone_count is below the required ratio",
            )
    # Tier 9 (cross-entity): curriculum alignment with the PUBLISHED script.
    if booking_kind == "SCHOOL":
        published = DB["scripts"].get(route["published_script_id"] or "")
        if published is None or curriculum_standard not in published[
            "curriculum_standards"
        ]:
            raise ApiError(
                "ERR_CURRICULUM_NOT_ALIGNED",
                422,
                "curriculum_standard is not covered by the route's published script",
            )
    # Tier 11 (capacity and fiscal): seats first, then member standing.
    if party_size > seats_available(slot):
        raise ApiError(
            "ERR_CAPACITY_EXCEEDED", 409, "party_size exceeds seats_available"
        )
    if booking_kind == "MEMBER" and member["status"] != "ACTIVE":
        raise ApiError(
            "ERR_MEMBER_NOT_ACTIVE", 422, "Member is not ACTIVE"
        )
    # Pricing, frozen at creation (PRD 3.6, calculation booking_total_price_cents).
    if booking_kind == "GENERAL":
        unit = unit_price_for(route)
        total = party_size * unit
    elif booking_kind == "MEMBER":
        unit = unit_price_for(route)
        total = (party_size - 1) * unit
    else:
        total = school_total(route, student_count, chaperone_count)
        unit = total  # school pricing is a group rate carried on the unit field
    hold_dt = min(now() + timedelta(hours=48), slot["_start_dt"])
    rec = {
        "id": new_id(),
        "slot_id": slot["id"],
        "member_id": member_id,
        "booking_kind": booking_kind,
        "visitor_name": visitor_name,
        "party_size": party_size,
        "student_count": student_count,
        "chaperone_count": chaperone_count,
        "grade_level": grade_level,
        "curriculum_standard": curriculum_standard,
        "unit_price_cents": unit,
        "total_price_cents": total,
        "refund_cents": 0,
        "_hold_dt": hold_dt,
        "status": "RESERVED",
    }
    stamp(rec)
    DB["bookings"][rec["id"]] = rec
    refresh_full_open(slot)
    return ok(ser_booking(rec), 201)


@bp.get("/bookings/<bid>")
def get_booking(bid):
    user_id, role = auth(BOOKING_ROLES)
    booking = lookup("bookings", bid)
    _check_member_ownership(role, user_id, booking)
    return ok(ser_booking(booking))


@bp.post("/bookings/<bid>/confirm")
def confirm_booking(bid):
    user_id, role = auth(BOOKING_ROLES)
    booking = lookup("bookings", bid)
    _check_member_ownership(role, user_id, booking)
    data = body()
    paid_cents = req_int(data, "paid_cents", minimum=0)
    if booking["status"] != "RESERVED":
        raise ApiError(
            "ERR_INVALID_STATE", 409, "Only a RESERVED booking can be confirmed"
        )
    slot = lookup("slots", booking["slot_id"])
    if slot["status"] not in ("OPEN", "FULL"):
        raise ApiError(
            "ERR_INVALID_STATE",
            409,
            "The booking's slot is not OPEN or FULL",
        )
    if now() >= slot["_start_dt"]:
        raise ApiError(
            "ERR_CONFIRM_WINDOW_CLOSED",
            422,
            "Confirmation is closed at or after the slot start",
        )
    if paid_cents != booking["total_price_cents"]:
        raise ApiError(
            "ERR_PAYMENT_MISMATCH",
            422,
            "paid_cents must equal total_price_cents",
        )
    booking["status"] = "CONFIRMED"
    touch(booking)
    refresh_full_open(slot)
    return ok(ser_booking(booking))


@bp.post("/bookings/<bid>/cancel")
def cancel_booking(bid):
    user_id, role = auth(BOOKING_ROLES)
    booking = lookup("bookings", bid)
    _check_member_ownership(role, user_id, booking)
    if booking["status"] not in ("RESERVED", "CONFIRMED"):
        raise ApiError(
            "ERR_INVALID_STATE",
            409,
            "Only a RESERVED or CONFIRMED booking can be cancelled",
        )
    slot = lookup("slots", booking["slot_id"])
    if booking["status"] == "CONFIRMED":
        booking["refund_cents"] = time_tier_refund(booking, slot)
    else:
        booking["refund_cents"] = 0
    booking["status"] = "CANCELLED"
    touch(booking)
    refresh_full_open(slot)
    return ok(ser_booking(booking))


@bp.post("/bookings/<bid>/surveys")
def create_survey(bid):
    user_id, role = auth(["Member", "FrontDeskStaff"])
    booking = lookup("bookings", bid)
    _check_member_ownership(role, user_id, booking)
    data = body()
    overall = req_int(data, "overall_rating", minimum=1, maximum=5)
    clarity = req_int(data, "interpretation_clarity", minimum=1, maximum=5)
    recommend = req_bool(data, "would_recommend")
    comment = data.get("comment")
    if comment is not None and not isinstance(comment, str):
        raise ApiError("ERR_INVALID_REQUEST", 400, "comment must be a string")
    slot = lookup("slots", booking["slot_id"])
    if booking["status"] != "CONFIRMED" or slot["status"] != "COMPLETED":
        raise ApiError(
            "ERR_INVALID_STATE",
            409,
            "Surveys require a CONFIRMED booking on a COMPLETED slot",
        )
    if slot["_completed_dt"] is not None and now() > slot["_completed_dt"] + timedelta(
        days=14
    ):
        raise ApiError(
            "ERR_SURVEY_WINDOW_CLOSED",
            422,
            "The 14-day survey window has closed",
        )
    if any(s["booking_id"] == bid for s in DB["surveys"].values()):
        raise ApiError(
            "ERR_DUPLICATE_SURVEY", 409, "A survey already exists for this booking"
        )
    rec = {
        "id": new_id(),
        "booking_id": booking["id"],
        "slot_id": booking["slot_id"],
        "overall_rating": overall,
        "interpretation_clarity": clarity,
        "would_recommend": recommend,
        "comment": comment,
        "status": "SUBMITTED",
        "created_at": fmt_ts(now()),
    }
    DB["surveys"][rec["id"]] = rec
    return ok(ser_survey(rec), 201)


@bp.get("/bookings/<bid>/surveys")
def list_booking_surveys(bid):
    user_id, role = auth(ALL_ROLES)
    booking = lookup("bookings", bid)
    _check_member_ownership(role, user_id, booking)
    items = sort_items(
        [s for s in DB["surveys"].values() if s["booking_id"] == booking["id"]]
    )
    return _paginate(items, ser_survey)
