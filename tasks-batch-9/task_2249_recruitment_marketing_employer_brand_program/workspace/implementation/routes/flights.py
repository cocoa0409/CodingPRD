"""Paid media flights: pricing, funding, delivery and pacing."""

from flask import Blueprint

import db
import response
import validation as V
from errors import ApiError
from middleware import require
from services import budget, calc, channel_svc, serialize

bp = Blueprint("flights", __name__)

READ_ROLES = ("BrandProgramLead", "PersonaResearcher", "ComplianceReviewer",
              "MediaBuyer", "CommunityManager", "RecruitingOps")
BLOCKING_STATES = ("RESERVED", "ACTIVE", "PAUSED_PACING", "SUSPENDED_CONTENT")


def _overlaps(a_start, a_end, b_start, b_end):
    """Half-open [start, end) intersection."""
    return a_start < b_end and b_start < a_end


@bp.route("/media-flights", methods=["POST"])
@require("MediaBuyer")
def create_flight():
    data = V.body()
    channel_id = V.field(data, "channel_id", "string", required=True)
    job_family_id = V.field(data, "job_family_id", "string", required=True)
    job_posting_id = V.field(data, "job_posting_id", "string", required=True)
    start_date = V.field(data, "start_date", "date", required=True)
    end_date = V.field(data, "end_date", "date", required=True)
    daily_cap_cents = V.field(data, "daily_cap_cents", "integer", required=True,
                              min_value=1)
    expected = V.field(data, "expected_program_version", "integer", required=True)

    channel = calc.must_get(db.channels, channel_id, "ERR_CHANNEL_NOT_FOUND")
    family = calc.must_get(db.job_families, job_family_id, "ERR_JOB_FAMILY_NOT_FOUND")
    posting = calc.must_get(db.postings, job_posting_id, "ERR_POSTING_NOT_FOUND")
    program = calc.program_of_family(family)
    if expected != program["version"]:
        raise ApiError("ERR_STALE_PROGRAM_VERSION",
                       "expected_program_version does not match the program version.")
    if channel["channel_type"] not in calc.PAYABLE_TYPES:
        raise ApiError("ERR_CHANNEL_NOT_PAYABLE",
                       "This channel type cannot carry paid media.")
    days = calc.flight_days(start_date, end_date)
    if days < channel["min_flight_days"]:
        raise ApiError("ERR_FLIGHT_TOO_SHORT",
                       "flight_days must be at least %d." % channel["min_flight_days"])
    start_day, end_day = db.parse_day(start_date), db.parse_day(end_date)
    capacity_used = 0
    for other in db.flights.values():
        if other["channel_id"] != channel["id"] or other["state"] not in BLOCKING_STATES:
            continue
        if not _overlaps(start_day, end_day,
                         db.parse_day(other["start_date"]), db.parse_day(other["end_date"])):
            continue
        if other["job_family_id"] == family["id"]:
            raise ApiError("ERR_FLIGHT_WINDOW_OVERLAP",
                           "Another flight on this channel and family overlaps the window.")
        capacity_used += other["daily_cap_cents"]
    if daily_cap_cents + capacity_used > channel["daily_capacity_cents"]:
        raise ApiError("ERR_CHANNEL_DAILY_CAPACITY_EXCEEDED",
                       "The channel's daily capacity would be exceeded.")

    pricing = calc.flight_pricing(channel, days, daily_cap_cents)
    row = {
        "id": db.new_id(),
        "channel_id": channel["id"],
        "job_family_id": family["id"],
        "job_posting_id": posting["id"],
        "start_date": start_date,
        "end_date": end_date,
        "daily_cap_cents": daily_cap_cents,
        "reserved_cents": pricing["total_cost_cents"],
        "spent_cents": 0,
        "state": "RESERVED",
        "release_reason": None,
        "activated_at": None,
    }
    row.update(pricing)
    budget.reserve(program, family, pricing["total_cost_cents"], "MEDIA_FLIGHT",
                   row["id"], "FLIGHT_RESERVATION", channel)
    stamp = db.wall_now()
    row.update({"created_at": stamp, "updated_at": stamp, "version": 1})
    db.flights[row["id"]] = row
    db.touch(program)
    return response.ok(serialize.flight(row), 201)


@bp.route("/media-flights/<flight_id>/activate", methods=["POST"])
@require("MediaBuyer")
def activate_flight(flight_id):
    flight = calc.must_get(db.flights, flight_id, "ERR_FLIGHT_NOT_FOUND")
    if flight["state"] != "RESERVED":
        raise ApiError("ERR_FLIGHT_NOT_RESERVED", "The flight is not RESERVED.")
    posting = db.postings[flight["job_posting_id"]]
    if posting["compliance_status"] != "CLEARED":
        raise ApiError("ERR_POSTING_COMPLIANCE_NOT_CLEARED",
                       "The posting is not compliance CLEARED.")
    program = calc.program_of_family(db.job_families[flight["job_family_id"]])
    if calc.brand_health_score(program) < 55.0:
        raise ApiError("ERR_BRAND_HEALTH_GATE",
                       "The program's brand_health_score is below 55.00.")
    if posting["content_status"] != "PUBLISHED":
        raise ApiError("ERR_POSTING_NOT_PUBLISHED", "The posting is not PUBLISHED.")
    flight["state"] = "ACTIVE"
    flight["activated_at"] = db.clock()
    channel = db.channels[flight["channel_id"]]
    channel_svc.enter_active(channel)
    channel_svc.recompute_pacing(channel)
    db.touch(flight)
    db.touch(channel)
    return response.ok(serialize.flight(flight))


@bp.route("/media-flights/<flight_id>/resume", methods=["POST"])
@require("MediaBuyer")
def resume_flight(flight_id):
    flight = calc.must_get(db.flights, flight_id, "ERR_FLIGHT_NOT_FOUND")
    if flight["state"] not in ("PAUSED_PACING", "SUSPENDED_CONTENT"):
        raise ApiError("ERR_FLIGHT_NOT_RESUMABLE", "The flight is not resumable.")
    channel = db.channels[flight["channel_id"]]
    posting = db.postings[flight["job_posting_id"]]
    if posting["compliance_status"] != "CLEARED":
        raise ApiError("ERR_POSTING_COMPLIANCE_NOT_CLEARED",
                       "The posting is not compliance CLEARED.")
    if posting["content_status"] != "PUBLISHED":
        raise ApiError("ERR_POSTING_NOT_PUBLISHED", "The posting is not PUBLISHED.")
    if channel["pacing_status"] == "THROTTLED":
        raise ApiError("ERR_CHANNEL_THROTTLED", "The channel is THROTTLED.")
    family = db.job_families[flight["job_family_id"]]
    program = calc.program_of_family(family)
    budget.reserve(program, family, flight["total_cost_cents"], "MEDIA_FLIGHT",
                   flight["id"], "FLIGHT_RESERVATION", channel)
    flight["reserved_cents"] = flight["total_cost_cents"]
    flight["release_reason"] = None
    flight["state"] = "ACTIVE"
    channel_svc.enter_active(channel)
    channel_svc.recompute_pacing(channel)
    db.touch(flight)
    db.touch(channel)
    db.touch(program)
    return response.ok(serialize.flight(flight))


@bp.route("/media-flights/<flight_id>/spend", methods=["POST"])
@require("MediaBuyer")
def record_spend(flight_id):
    data = V.body()
    amount_cents = V.field(data, "amount_cents", "integer", required=True, min_value=1)
    spent_on = V.field(data, "spent_on", "date", required=True)
    flight = calc.must_get(db.flights, flight_id, "ERR_FLIGHT_NOT_FOUND")
    if flight["state"] not in ("ACTIVE", "PAUSED_PACING"):
        raise ApiError("ERR_FLIGHT_ALREADY_TERMINAL", "The flight is terminal.")
    if flight["spent_cents"] + amount_cents > flight["total_cost_cents"]:
        raise ApiError("ERR_SPEND_EXCEEDS_RESERVATION",
                       "Recorded spend would exceed total_cost_cents.")
    flight["spent_cents"] += amount_cents
    flight["last_spent_on"] = spent_on
    channel = db.channels[flight["channel_id"]]
    channel_svc.recompute_pacing(channel)
    channel_svc.apply_throttle(channel)
    db.touch(flight)
    db.touch(channel)
    return response.ok(serialize.flight(flight))


@bp.route("/media-flights/<flight_id>/complete", methods=["POST"])
@require("MediaBuyer")
def complete_flight(flight_id):
    flight = calc.must_get(db.flights, flight_id, "ERR_FLIGHT_NOT_FOUND")
    if flight["state"] not in ("ACTIVE", "PAUSED_PACING"):
        raise ApiError("ERR_FLIGHT_NOT_COMPLETABLE", "The flight is not completable.")
    if db.clock() < db.day_midnight(flight["end_date"]):
        raise ApiError("ERR_FLIGHT_WINDOW_OPEN", "The flight window is still open.")
    _terminate(flight, "COMPLETED", "COMPLETED", "FLIGHT_COMPLETED")
    return response.ok(serialize.flight(flight))


@bp.route("/media-flights/<flight_id>/cancel", methods=["POST"])
@require("MediaBuyer")
def cancel_flight(flight_id):
    data = V.body()
    V.field(data, "reason", "string", nullable=True, min_len=0, max_len=500)
    flight = calc.must_get(db.flights, flight_id, "ERR_FLIGHT_NOT_FOUND")
    if flight["state"] not in BLOCKING_STATES:
        raise ApiError("ERR_FLIGHT_ALREADY_TERMINAL", "The flight is already terminal.")
    _terminate(flight, "CANCELLED", "CANCELLED", "FLIGHT_CANCELLED")
    return response.ok(serialize.flight(flight))


def _terminate(flight, new_state, release_reason, ledger_reason):
    was_active = flight["state"] == "ACTIVE"
    flight["state"] = new_state
    flight["release_reason"] = release_reason
    flight["reserved_cents"] = 0
    program = calc.program_of_family(db.job_families[flight["job_family_id"]])
    budget.release(program, flight["id"], ledger_reason)
    channel = db.channels[flight["channel_id"]]
    if was_active:
        channel_svc.resolve_idle(channel)
    db.touch(flight)
    db.touch(channel)
    db.touch(program)


@bp.route("/media-flights/<flight_id>", methods=["GET"])
@require(*READ_ROLES)
def get_flight(flight_id):
    flight = calc.must_get(db.flights, flight_id, "ERR_FLIGHT_NOT_FOUND")
    return response.ok(serialize.flight(flight))


@bp.route("/media-flights", methods=["GET"])
@require(*READ_ROLES)
def list_flights():
    limit, offset = V.pagination()
    rows = sorted(db.flights.values(), key=lambda r: (r["start_date"], r["created_at"]))
    for name, key in (("channel_id", "channel_id"),
                      ("job_family_id", "job_family_id"),
                      ("job_posting_id", "job_posting_id"),
                      ("state", "state")):
        value = V.qs(name)
        if value:
            rows = [r for r in rows if r[key] == value]
    page, meta = V.window(rows, limit, offset)
    return response.ok_list([serialize.flight(r) for r in page], meta)
