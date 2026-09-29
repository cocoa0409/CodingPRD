"""Technical advance packets: open, submit, return, approve."""

from flask import Blueprint, g

from db import db, new_row, public, public_list, touch
from errors import fail
from middleware import endpoint, require_artist_scope
from response import paginate, respond_array, respond_object
from services import calc
from validators import (
    body,
    body_fk,
    load,
    opt_int,
    pagination,
    query_enum,
    req_int,
    req_string,
    stored_instant,
)

bp = Blueprint("advance_packets", __name__)

PACKET_STATUSES = ("DRAFT", "SUBMITTED", "RETURNED", "APPROVED")
READ_ROLES = ["TalentBuyer", "ArtistRep", "BusinessAffairs", "ProductionManager"]
ACTIVE_CONTRACT_STATES = ("PENDING_RIDER", "RIDER_SETTLED")


def _stage_day_channels(packet, booking):
    """Sum input_channel_count of SUBMITTED|APPROVED packets on the same stage-day."""
    day = stored_instant(booking["slot_start_utc"]).date()
    total = 0
    for other in db.advance_packets.values():
        if other["id"] == packet["id"]:
            continue
        if other["status"] not in ("SUBMITTED", "APPROVED"):
            continue
        sibling = db.bookings.get(other["booking_id"])
        if sibling is None or sibling["stage_id"] != booking["stage_id"]:
            continue
        if stored_instant(sibling["slot_start_utc"]).date() != day:
            continue
        total += other["input_channel_count"]
    return total + packet["input_channel_count"]


@bp.post("/advance-packets")
@endpoint(["ArtistRep", "ProductionManager"])
def create_packet():
    payload = body()
    req_string(payload, "booking_id", 1)
    stage_plot_ref = req_string(payload, "stage_plot_ref", 1, 120)
    input_channel_count = req_int(payload, "input_channel_count", 1, 96)
    monitor_mix_count = req_int(payload, "monitor_mix_count", 0, 24)
    travel_party_size = req_int(payload, "travel_party_size", 1, 60)
    load_in_offset_minutes = opt_int(payload, "load_in_offset_minutes", 30, 30, 480)

    booking = body_fk(payload, "booking_id", "bookings")
    require_artist_scope(booking["artist_id"])

    row = new_row(
        booking_id=booking["id"],
        stage_plot_ref=stage_plot_ref,
        input_channel_count=input_channel_count,
        monitor_mix_count=monitor_mix_count,
        travel_party_size=travel_party_size,
        load_in_offset_minutes=load_in_offset_minutes,
        status="DRAFT",
        submission_count=0,
        submitted_by_user_id=None,
        approved_by_user_id=None,
        return_reason=None,
        channel_overage=0,
    )
    db.advance_packets[row["id"]] = row
    return respond_object(public(row), 201)


@bp.get("/advance-packets/<packet_id>")
@endpoint(READ_ROLES)
def get_packet(packet_id):
    packet = load("advance_packets", packet_id)
    booking = db.bookings.get(packet["booking_id"])
    if booking is not None:
        require_artist_scope(booking["artist_id"])
    return respond_object(public(packet))


@bp.get("/bookings/<booking_id>/advance-packets")
@endpoint(READ_ROLES)
def list_booking_packets(booking_id):
    status = query_enum("status", PACKET_STATUSES)
    limit, offset = pagination()
    booking = load("bookings", booking_id)
    require_artist_scope(booking["artist_id"])

    rows = calc.booking_advance_packets(booking["id"])
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    rows = calc.sorted_rows(rows, [])
    window, meta = paginate(rows, limit, offset)
    return respond_array(public_list(window), pagination=meta)


@bp.post("/advance-packets/<packet_id>/submit")
@endpoint(["ArtistRep", "ProductionManager"])
def submit_packet(packet_id):
    packet = load("advance_packets", packet_id)
    booking = db.bookings.get(packet["booking_id"])
    if booking is not None:
        require_artist_scope(booking["artist_id"])

    if packet["status"] not in ("DRAFT", "RETURNED"):
        fail("ERR_INVALID_ADVANCE_STATE", "only a draft or returned packet may be submitted")
    if booking is None or booking["contract_status"] not in ACTIVE_CONTRACT_STATES:
        fail("ERR_INVALID_BOOKING_STATE", "the booking no longer accepts an advance")
    if packet["submission_count"] >= calc.MAX_ADVANCE_SUBMISSIONS:
        fail("ERR_ADVANCE_SUBMISSIONS_EXHAUSTED", "the submission cap is reached")

    total = _stage_day_channels(packet, booking)
    if total > calc.STAGE_CHANNEL_HARD_MAX:
        fail("ERR_STAGE_CHANNEL_CAP_EXCEEDED", "the stage-day channel maximum is exceeded")

    packet["status"] = "SUBMITTED"
    packet["submission_count"] = packet["submission_count"] + 1
    packet["submitted_by_user_id"] = g.user_id
    packet["channel_overage"] = max(0, total - calc.STAGE_CHANNEL_ADVISORY)
    touch(packet)
    return respond_object(public(packet))


@bp.post("/advance-packets/<packet_id>/return")
@endpoint(["ProductionManager"])
def return_packet(packet_id):
    payload = body()
    return_reason = req_string(payload, "return_reason", 1, None)

    packet = load("advance_packets", packet_id)
    if packet["status"] != "SUBMITTED":
        fail("ERR_INVALID_ADVANCE_STATE", "only a submitted packet may be returned")
    if packet["submitted_by_user_id"] == g.user_id:
        fail("ERR_SEGREGATION_OF_DUTIES", "the submitter may not return their own packet")

    packet["status"] = "RETURNED"
    packet["return_reason"] = return_reason
    touch(packet)
    return respond_object(public(packet))


@bp.post("/advance-packets/<packet_id>/approve")
@endpoint(["ProductionManager"])
def approve_packet(packet_id):
    packet = load("advance_packets", packet_id)
    booking = db.bookings.get(packet["booking_id"])

    if packet["status"] != "SUBMITTED":
        fail("ERR_INVALID_ADVANCE_STATE", "only a submitted packet may be approved")
    if booking is None or booking["contract_status"] not in ACTIVE_CONTRACT_STATES:
        fail("ERR_INVALID_BOOKING_STATE", "the booking no longer accepts an advance")
    if packet["submitted_by_user_id"] == g.user_id:
        fail("ERR_SEGREGATION_OF_DUTIES", "the submitter may not approve their own packet")

    slot_start = stored_instant(booking["slot_start_utc"])
    midnight = slot_start.replace(hour=0, minute=0, second=0, microsecond=0)
    load_in_minutes = (slot_start - midnight).total_seconds() / 60.0
    if packet["load_in_offset_minutes"] > load_in_minutes:
        fail(
            "ERR_INVALID_ADVANCE_STATE",
            "the load-in would begin before midnight of the show date",
        )

    packet["status"] = "APPROVED"
    packet["approved_by_user_id"] = g.user_id
    touch(packet)
    return respond_object(public(packet))
