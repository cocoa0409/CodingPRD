"""Logical clock, venues, numbering series and the meeting lifecycle."""
from datetime import timedelta

from flask import Blueprint, g

import calc
import domain
from core import (ALL_ROLES, ROLE_CITY_CLERK, ROLE_PRESIDING, STAFF_ROLES,
                  ApiError, authorize, body_dict, db, fetch, fk, invalid,
                  iso_ts, listing, new_record, now_dt, ok, opt_enum, opt_int,
                  parse_datetime, q, req_enum, req_int, req_str, touch)

bp = Blueprint("meetings", __name__)

MEETING_STATES = ("SCHEDULED", "NOTICED", "IN_SESSION", "ADJOURNED", "CANCELLED")
OCCUPYING_STATES = ("SCHEDULED", "NOTICED", "IN_SESSION")


# ------------------------------------------------------------------ clock
@bp.route("/clerk/_clock/set_current_utc", methods=["POST"])
def set_clock():
    authorize(STAFF_ROLES)
    body = body_dict()
    if "to_iso8601" not in body or body["to_iso8601"] is None:
        raise invalid("Field 'to_iso8601' is required.")
    db.clock = parse_datetime(body["to_iso8601"])
    return ok({"current_utc": iso_ts(db.clock)})


# ------------------------------------------------------------------ venues
@bp.route("/clerk/venues", methods=["POST"])
def create_venue():
    authorize((ROLE_CITY_CLERK,))
    body = body_dict()
    name = req_str(body, "name")
    address = req_str(body, "address")
    capacity = req_int(body, "capacity", minimum=1)
    buffer_minutes = opt_int(body, "teardown_buffer_minutes", default=30,
                             minimum=0, maximum=240)
    status = opt_enum(body, "status", ("AVAILABLE", "CLOSED"), default="AVAILABLE")
    venue = new_record()
    venue.update({
        "name": name,
        "address": address,
        "capacity": capacity,
        "teardown_buffer_minutes": buffer_minutes,
        "status": status,
    })
    db.venues[venue["id"]] = venue
    return ok(venue, 201)


@bp.route("/clerk/venues/<venue_id>", methods=["GET"])
def get_venue(venue_id):
    authorize(STAFF_ROLES)
    return ok(fetch(db.venues, venue_id, "ERR_VENUE_NOT_FOUND"))


@bp.route("/clerk/venues/<venue_id>", methods=["PUT"])
def update_venue(venue_id):
    authorize((ROLE_CITY_CLERK,))
    venue = fetch(db.venues, venue_id, "ERR_VENUE_NOT_FOUND")
    body = body_dict()
    capacity = opt_int(body, "capacity", minimum=1)
    buffer_minutes = opt_int(body, "teardown_buffer_minutes", minimum=0, maximum=240)
    status = opt_enum(body, "status", ("AVAILABLE", "CLOSED"))
    if capacity is not None:
        venue["capacity"] = capacity
    if buffer_minutes is not None:
        venue["teardown_buffer_minutes"] = buffer_minutes
    if status is not None:
        venue["status"] = status
    touch(venue)
    return ok(venue)


# ----------------------------------------------------------- number series
@bp.route("/clerk/number-series", methods=["POST"])
def create_series():
    authorize((ROLE_CITY_CLERK,))
    body = body_dict()
    series_year = req_int(body, "series_year", minimum=1)
    instrument_class = req_enum(body, "instrument_class", ("ORDINANCE", "RESOLUTION"))
    prefix = req_str(body, "prefix")
    next_sequence = opt_int(body, "next_sequence", default=1, minimum=1,
                            maximum=calc.MAX_SEQUENCE)
    for existing in db.number_series.values():
        if (existing["series_year"] == series_year
                and existing["instrument_class"] == instrument_class):
            raise ApiError("ERR_DUPLICATE_NUMBER_SERIES", 422)
    series = new_record()
    series.update({
        "series_year": series_year,
        "instrument_class": instrument_class,
        "prefix": prefix,
        "next_sequence": next_sequence,
        "minted_count": 0,
        "status": "OPEN",
    })
    db.number_series[series["id"]] = series
    return ok(series, 201)


@bp.route("/clerk/number-series/<series_id>", methods=["GET"])
def get_series(series_id):
    authorize(STAFF_ROLES)
    return ok(fetch(db.number_series, series_id, "ERR_NUMBER_SERIES_NOT_FOUND"))


@bp.route("/clerk/number-series/<series_id>/close", methods=["POST"])
def close_series(series_id):
    authorize((ROLE_CITY_CLERK,))
    series = fetch(db.number_series, series_id, "ERR_NUMBER_SERIES_NOT_FOUND")
    if series["status"] != "OPEN":
        raise ApiError("ERR_NUMBER_SERIES_CLOSED", 409)
    series["status"] = "CLOSED"
    touch(series)
    return ok(series)


# ---------------------------------------------------------------- meetings
def _occupation(meeting, venue, start=None, end=None):
    """[start, end + teardown_buffer) -- the buffer trails every occupation."""
    start = meeting["scheduled_start"] if start is None else start
    end = meeting["scheduled_end"] if end is None else end
    return start, end + timedelta(minutes=venue["teardown_buffer_minutes"])


def _venue_conflict(venue, start, end, exclude_id=None):
    new_start, new_end = _occupation(None, venue, start, end)
    for other in db.meetings.values():
        if other["id"] == exclude_id:
            continue
        if other["venue_id"] != venue["id"]:
            continue
        if other["status"] not in OCCUPYING_STATES:
            continue
        other_start, other_end = _occupation(other, venue)
        if new_start < other_end and other_start < new_end:
            return True
    return False


@bp.route("/clerk/meetings", methods=["POST"])
def create_meeting():
    authorize((ROLE_CITY_CLERK,))
    body = body_dict()
    venue = fk(body, "venue_id", db.venues, "ERR_VENUE_NOT_FOUND")
    body_type = req_enum(body, "body_type",
                         ("COUNCIL", "PLANNING_COMMISSION", "BOARD_OF_ADJUSTMENT"))
    meeting_type = req_enum(body, "meeting_type",
                            ("REGULAR", "SPECIAL", "EMERGENCY", "WORKSHOP"))
    if venue is None:
        raise invalid("Field 'venue_id' is required.")
    start = _req_dt(body, "scheduled_start")
    end = _req_dt(body, "scheduled_end")
    if end <= start:
        raise invalid("scheduled_end must be strictly after scheduled_start.")
    quorum = req_int(body, "quorum_required", minimum=1)
    if _venue_conflict(venue, start, end):
        raise ApiError("ERR_VENUE_WINDOW_CONFLICT", 409)
    if venue["status"] == "CLOSED":
        raise ApiError("ERR_VENUE_CLOSED", 409)
    meeting = new_record()
    meeting.update({
        "body_type": body_type,
        "meeting_type": meeting_type,
        "venue_id": venue["id"],
        "scheduled_start": start,
        "scheduled_end": end,
        "quorum_required": quorum,
        "present_member_count": 0,
        "status": "SCHEDULED",
        "notice_posted_at": None,
        "required_notice_hours": None,
        "notice_compliant": False,
        "adjourned_at": None,
        "cancelled_reason": None,
    })
    db.meetings[meeting["id"]] = meeting
    return ok(meeting, 201)


def _req_dt(body, key):
    if key not in body or body[key] is None:
        raise invalid("Field '%s' is required." % key)
    return parse_datetime(body[key])


@bp.route("/clerk/meetings/<meeting_id>", methods=["GET"])
def get_meeting(meeting_id):
    authorize(STAFF_ROLES)
    return ok(fetch(db.meetings, meeting_id, "ERR_MEETING_NOT_FOUND"))


@bp.route("/clerk/meetings", methods=["GET"])
def list_meetings():
    authorize(STAFF_ROLES)
    return listing(list(db.meetings.values()),
                   {"venue_id": q("venue_id"), "status": q("status")})


@bp.route("/clerk/meetings/<meeting_id>/reschedule", methods=["POST"])
def reschedule_meeting(meeting_id):
    authorize((ROLE_CITY_CLERK,))
    meeting = fetch(db.meetings, meeting_id, "ERR_MEETING_NOT_FOUND")
    body = body_dict()
    start = _req_dt(body, "scheduled_start")
    end = _req_dt(body, "scheduled_end")
    if end <= start:
        raise invalid("scheduled_end must be strictly after scheduled_start.")
    if meeting["status"] not in ("SCHEDULED", "NOTICED"):
        raise ApiError("ERR_INVALID_MEETING_STATE", 409)
    packet = domain.posted_packet_of(meeting["id"])
    probe = dict(meeting)
    probe["scheduled_start"] = start
    if packet is not None:
        hours, deadline = calc.meeting_notice_requirement(
            probe, packet["contains_public_hearing"], packet["late_addendum"])
        if deadline <= now_dt():
            raise ApiError("ERR_NOTICE_DEADLINE_MISSED", 409)
    venue = db.venues.get(meeting["venue_id"])
    if venue is not None and _venue_conflict(venue, start, end,
                                             exclude_id=meeting["id"]):
        raise ApiError("ERR_VENUE_WINDOW_CONFLICT", 409)
    meeting["scheduled_start"] = start
    meeting["scheduled_end"] = end
    if packet is not None:
        domain.recompute_packet_notice(packet, meeting)
        packet["notice_compliant"] = calc.agenda_notice_compliance(
            packet["posted_at"], packet["notice_deadline_at"])
        touch(packet)
    domain.mirror_meeting_notice(meeting)
    touch(meeting)
    return ok(meeting)


@bp.route("/clerk/meetings/<meeting_id>/convene", methods=["POST"])
def convene_meeting(meeting_id):
    authorize((ROLE_PRESIDING,))
    meeting = fetch(db.meetings, meeting_id, "ERR_MEETING_NOT_FOUND")
    body = body_dict()
    present = req_int(body, "present_member_count", minimum=0)
    if meeting["status"] != "NOTICED":
        raise ApiError("ERR_INVALID_MEETING_STATE", 409)
    if not meeting["notice_compliant"]:
        raise ApiError("ERR_NOTICE_DEADLINE_MISSED", 409)
    if present < meeting["quorum_required"]:
        raise ApiError("ERR_QUORUM_NOT_MET", 409)
    meeting["status"] = "IN_SESSION"
    meeting["present_member_count"] = present
    touch(meeting)
    return ok(meeting)


@bp.route("/clerk/meetings/<meeting_id>/adjourn", methods=["POST"])
def adjourn_meeting(meeting_id):
    authorize((ROLE_PRESIDING,))
    meeting = fetch(db.meetings, meeting_id, "ERR_MEETING_NOT_FOUND")
    if meeting["status"] != "IN_SESSION":
        raise ApiError("ERR_INVALID_MEETING_STATE", 409)
    meeting["status"] = "ADJOURNED"
    meeting["adjourned_at"] = now_dt()
    touch(meeting)
    minutes = new_record()
    minutes.update({
        "meeting_id": meeting["id"],
        "status": "DRAFT",
        "revision_number": 1,
        "text_body": "",
        "pending_correction_text": None,
        "correction_count": 0,
        "approved_on": None,
    })
    db.minutes[minutes["id"]] = minutes
    for motion in domain.motions_of(meeting["id"]):
        if motion["status"] == "SECONDED":
            motion["status"] = "WITHDRAWN"
            touch(motion)
    return ok(meeting)


@bp.route("/clerk/meetings/<meeting_id>/cancel", methods=["POST"])
def cancel_meeting(meeting_id):
    authorize((ROLE_CITY_CLERK,))
    meeting = fetch(db.meetings, meeting_id, "ERR_MEETING_NOT_FOUND")
    body = body_dict()
    reason = req_str(body, "cancelled_reason")
    if meeting["status"] not in ("SCHEDULED", "NOTICED"):
        raise ApiError("ERR_INVALID_MEETING_STATE", 409)
    for packet in domain.packets_of(meeting["id"]):
        if packet["status"] in ("DRAFT", "POSTED"):
            packet["status"] = "WITHDRAWN"
            touch(packet)
    domain.void_meeting_agenda_notices(meeting["id"])
    meeting["status"] = "CANCELLED"
    meeting["cancelled_reason"] = reason
    meeting["notice_posted_at"] = None
    meeting["required_notice_hours"] = None
    meeting["notice_compliant"] = False
    touch(meeting)
    domain.new_notice("CANCELLATION", meeting=meeting)
    return ok(meeting)
