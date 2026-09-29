"""Portal bookings, change management, cancellation and no-shows (PRD §3.4, §3.5)."""

from flask import Blueprint

import calc
import serializers as ser
import validators as V
from auth import authenticate
from envelope import created, ok, ok_list, paginate
from errors import fail
from store import (
    STORE,
    base_record,
    clock_at_or_after_date,
    clock_before_date,
    date_shift,
    days_between,
    parse_iso_date,
    sort_created,
    touch,
)

bp = Blueprint("reservations", __name__, url_prefix="/housing")

RESERVATION_STATUSES = ("CONFIRMED", "WAITLISTED", "CANCELLED", "NO_SHOW")
TRANSMISSION_STATUSES = ("NOT_TRANSMITTED", "TRANSMITTED", "CHANGE_PENDING")
READ_ROLES = [
    "BureauCoordinator",
    "BureauController",
    "EventOrganizer",
    "HotelManager",
    "Attendee",
]
TERMINAL_RESERVATION_STATUSES = ("CANCELLED", "NO_SHOW")


def _check_stay_window(event, check_in, check_out):
    """§3.4 — the widened housing window: one day either side."""
    low = date_shift(event["event_start_date"], -1)
    high = date_shift(event["event_end_date"], 1)
    if parse_iso_date(check_in) < low or parse_iso_date(check_out) > high:
        fail("ERR_INVALID_STAY_WINDOW", "the stay falls outside the widened housing window")


@bp.post("/reservations")
def create_reservation():
    principal = authenticate(["Attendee", "BureauCoordinator"])
    body = V.json_body()

    sub_block_id = V.field_str(body, "sub_block_id")
    attendee_id = V.field_str(body, "attendee_id")
    check_in_date = V.field_date(body, "check_in_date")
    check_out_date = V.field_date(body, "check_out_date")
    occupants = V.field_int(body, "occupants", required=False, minimum=1, maximum=4, default=1)
    if parse_iso_date(check_out_date) <= parse_iso_date(check_in_date):
        fail("ERR_INVALID_REQUEST", "check_out_date must be strictly later than check_in_date")

    # step 4 — body identifiers left-to-right
    sub_block = V.get_sub_block(sub_block_id)
    attendee = V.get_attendee(attendee_id)

    # step 6 — a delegate may only book for themselves
    if principal.role == "Attendee" and attendee["id"] != principal.user_id:
        fail("ERR_NOT_RESOURCE_OWNER", "a delegate may only book their own stay")

    # step 8 — own-state: the parent block, then the sub-block
    block = calc.block_of_sub_block(sub_block)
    if block is None or block["status"] != "OPEN":
        fail("ERR_BLOCK_NOT_OPEN", "the parent housing block is not OPEN")
    if sub_block["approval_status"] != "APPROVED":
        fail("ERR_INVALID_SUB_BLOCK_STATE", "the sub-block is not APPROVED")

    # step 11 — logical-clock cutoff gate
    if not clock_before_date(block["cutoff_date"]):
        fail("ERR_CUTOFF_PASSED", "the block cutoff date has been reached")

    # step 13 — housing-risk hold
    if attendee["housing_risk_flag"]:
        fail("ERR_ATTENDEE_HOUSING_RISK_HOLD", "the delegate is under a housing-risk hold")

    # step 15 — eligibility
    event = calc.event_of_block(block)
    if attendee["event_id"] != block["event_id"]:
        fail("ERR_SUB_BLOCK_ELIGIBILITY_MISMATCH", "the delegate belongs to another event")
    if sub_block["segment"] != "GENERAL":
        if attendee["attendee_type"] != sub_block["segment"]:
            fail(
                "ERR_SUB_BLOCK_ELIGIBILITY_MISMATCH",
                "the delegate type does not match the sub-block segment",
            )
        if sub_block["eligibility_code"] not in attendee["eligibility_codes"]:
            fail(
                "ERR_SUB_BLOCK_ELIGIBILITY_MISMATCH",
                "the delegate does not carry the sub-block eligibility code",
            )

    # step 16 — stay window
    _check_stay_window(event, check_in_date, check_out_date)

    # step 17 — buffered same-attendee overlap
    if calc.attendee_stay_collides(attendee["id"], check_in_date, check_out_date):
        fail("ERR_ATTENDEE_STAY_OVERLAP", "the delegate already holds an overlapping stay")

    # step 18 — night-capacity admission
    if not calc.admits_stay(sub_block, check_in_date, check_out_date):
        fail("ERR_SUB_BLOCK_NIGHT_CAPACITY_EXCEEDED", "a night of the stay is at allotment capacity")

    hotel = STORE.hotels.get(block["hotel_id"])
    record = base_record()
    record.update(
        {
            "sub_block_id": sub_block["id"],
            "attendee_id": attendee["id"],
            "check_in_date": check_in_date,
            "check_out_date": check_out_date,
            "occupants": occupants,
            "intake_seq": STORE.next_intake_seq(),
            "room_nights": days_between(check_in_date, check_out_date),
            # Commercial terms are snapshotted and frozen at intake.
            "quoted_nightly_rate_cents": block["negotiated_nightly_rate_cents"],
            "room_tax_pct_snapshot": hotel["room_tax_pct"] if hotel else 0,
            "reservation_status": "CONFIRMED",
            "transmission_status": "NOT_TRANSMITTED",
            "eligibility_review_required": False,
            "no_show_billed_cents": 0,
            "total_room_charge_cents": 0,
        }
    )
    record["total_room_charge_cents"] = calc.reservation_total_charge(record)
    STORE.reservations[record["id"]] = record

    calc.recompute_sub_block(sub_block)
    calc.recompute_event(event)
    return created(ser.reservation_out(record))


@bp.get("/reservations/<reservation_id>")
def read_reservation(reservation_id):
    authenticate(READ_ROLES)
    reservation = V.get_reservation(reservation_id)
    return ok(ser.reservation_out(reservation))


@bp.get("/reservations")
def list_reservations():
    authenticate(READ_ROLES)
    sub_block_id = V.str_arg("sub_block_id")
    attendee_id = V.str_arg("attendee_id")
    reservation_status = V.enum_arg("reservation_status", RESERVATION_STATUSES)
    transmission_status = V.enum_arg("transmission_status", TRANSMISSION_STATUSES)
    limit, offset = V.pagination_args()

    items = list(STORE.reservations.values())
    if sub_block_id is not None:
        items = [r for r in items if r["sub_block_id"] == sub_block_id]
    if attendee_id is not None:
        items = [r for r in items if r["attendee_id"] == attendee_id]
    if reservation_status is not None:
        items = [r for r in items if r["reservation_status"] == reservation_status]
    if transmission_status is not None:
        items = [r for r in items if r["transmission_status"] == transmission_status]
    items = sort_created(items)
    page, pagination = paginate(items, limit, offset)
    return ok_list([ser.reservation_out(r) for r in page], pagination)


@bp.patch("/reservations/<reservation_id>")
def change_reservation(reservation_id):
    principal = authenticate(["Attendee", "BureauCoordinator"])
    body = V.json_body()

    new_check_in = V.field_date(body, "check_in_date", required=False)
    new_check_out = V.field_date(body, "check_out_date", required=False)
    new_occupants = V.field_int(body, "occupants", required=False, minimum=1, maximum=4)

    reservation = V.get_reservation(reservation_id)

    check_in = new_check_in if new_check_in is not None else reservation["check_in_date"]
    check_out = new_check_out if new_check_out is not None else reservation["check_out_date"]
    if parse_iso_date(check_out) <= parse_iso_date(check_in):
        fail("ERR_INVALID_REQUEST", "check_out_date must be strictly later than check_in_date")

    # step 6 — a delegate may only change their own stay
    if principal.role == "Attendee" and reservation["attendee_id"] != principal.user_id:
        fail("ERR_NOT_RESOURCE_OWNER", "a delegate may only change their own stay")

    sub_block = STORE.sub_blocks.get(reservation["sub_block_id"])
    block = calc.block_of_sub_block(sub_block) if sub_block else None

    # step 8 — own-state
    if reservation["reservation_status"] in TERMINAL_RESERVATION_STATUSES:
        fail("ERR_RESERVATION_NOT_MODIFIABLE", "the reservation has reached a terminal status")
    if block is None or block["status"] == "CLOSED":
        fail("ERR_RESERVATION_NOT_MODIFIABLE", "the parent housing block is CLOSED")

    # step 11 — cutoff
    if not clock_before_date(block["cutoff_date"]):
        fail("ERR_CUTOFF_PASSED", "the block cutoff date has been reached")

    # step 13 — housing-risk hold
    attendee = STORE.attendees.get(reservation["attendee_id"])
    if attendee is not None and attendee["housing_risk_flag"]:
        fail("ERR_ATTENDEE_HOUSING_RISK_HOLD", "the delegate is under a housing-risk hold")

    event = calc.event_of_block(block)
    # step 16 — stay window
    _check_stay_window(event, check_in, check_out)
    # step 17 — buffered overlap, excluding the reservation being changed
    if calc.attendee_stay_collides(
        reservation["attendee_id"], check_in, check_out, reservation["id"]
    ):
        fail("ERR_ATTENDEE_STAY_OVERLAP", "the delegate already holds an overlapping stay")
    # step 18 — night capacity, excluding the reservation being changed
    if not calc.admits_stay(sub_block, check_in, check_out, reservation["id"]):
        fail("ERR_SUB_BLOCK_NIGHT_CAPACITY_EXCEEDED", "a night of the stay is at allotment capacity")

    reservation["check_in_date"] = check_in
    reservation["check_out_date"] = check_out
    if new_occupants is not None:
        reservation["occupants"] = new_occupants
    reservation["room_nights"] = days_between(check_in, check_out)
    # Re-priced at the ORIGINAL snapshotted rate and tax, never at current terms.
    reservation["total_room_charge_cents"] = calc.reservation_total_charge(reservation)
    if reservation["transmission_status"] == "TRANSMITTED":
        reservation["transmission_status"] = "CHANGE_PENDING"
    touch(reservation)

    calc.recompute_sub_block(sub_block)
    calc.recompute_event(event)
    return ok(ser.reservation_out(reservation))


@bp.post("/reservations/<reservation_id>/cancel")
def cancel_reservation(reservation_id):
    principal = authenticate(["Attendee", "BureauCoordinator"])
    V.json_body()
    reservation = V.get_reservation(reservation_id)

    # step 6
    if principal.role == "Attendee" and reservation["attendee_id"] != principal.user_id:
        fail("ERR_NOT_RESOURCE_OWNER", "a delegate may only cancel their own stay")

    sub_block = STORE.sub_blocks.get(reservation["sub_block_id"])
    block = calc.block_of_sub_block(sub_block) if sub_block else None

    # step 8
    if reservation["reservation_status"] != "CONFIRMED":
        fail("ERR_RESERVATION_NOT_MODIFIABLE", "only a CONFIRMED reservation may be cancelled")
    if block is None or block["status"] not in ("OPEN", "CUTOFF_PASSED"):
        fail("ERR_RESERVATION_NOT_MODIFIABLE", "the parent block must be OPEN or CUTOFF_PASSED")

    reservation["reservation_status"] = "CANCELLED"
    if reservation["transmission_status"] == "TRANSMITTED":
        reservation["transmission_status"] = "CHANGE_PENDING"
    touch(reservation)

    event = calc.event_of_block(block)
    calc.recompute_sub_block(sub_block)
    calc.recompute_event(event)

    # Cancellation is the only waitlist-promotion trigger, and it promotes at most one.
    promoted = calc.promote_one_waitlisted(sub_block)
    if promoted is not None:
        calc.recompute_sub_block(sub_block)
        calc.recompute_event(event)

    return ok(ser.reservation_out(reservation))


@bp.post("/reservations/<reservation_id>/no-show")
def no_show_reservation(reservation_id):
    principal = authenticate(["HotelManager"])
    V.json_body()
    reservation = V.get_reservation(reservation_id)

    sub_block = STORE.sub_blocks.get(reservation["sub_block_id"])
    block = calc.block_of_sub_block(sub_block) if sub_block else None

    # step 6 — only the owning property reports a no-show
    if block is None or block["hotel_id"] != principal.user_id:
        fail("ERR_NOT_RESOURCE_OWNER", "the acting hotel does not own this block")

    # step 8 — the other three conditions all report as not-modifiable
    if reservation["reservation_status"] != "CONFIRMED":
        fail("ERR_RESERVATION_NOT_MODIFIABLE", "only a CONFIRMED reservation may be no-showed")
    if block["status"] != "CUTOFF_PASSED":
        fail("ERR_RESERVATION_NOT_MODIFIABLE", "the parent block must be CUTOFF_PASSED")
    if not clock_at_or_after_date(reservation["check_in_date"]):
        fail("ERR_RESERVATION_NOT_MODIFIABLE", "the arrival date has not been reached")

    reservation["reservation_status"] = "NO_SHOW"
    reservation["no_show_billed_cents"] = calc.no_show_billing(reservation)
    touch(reservation)

    attendee = STORE.attendees.get(reservation["attendee_id"])
    if attendee is not None:
        attendee["no_show_strikes"] += 1
        touch(attendee)

    calc.recompute_sub_block(sub_block)
    calc.recompute_event_of_block(block)
    # No waitlist promotion runs on a no-show: the room was physically held.
    return ok(ser.reservation_out(reservation))
