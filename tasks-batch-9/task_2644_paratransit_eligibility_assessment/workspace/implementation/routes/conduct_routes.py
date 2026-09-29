"""PRD 3.9 — trip conduct ingestion, no-show points and suspension due process."""

from flask import Blueprint

import conduct
import lookups
import owners
import serializers
import shapes
from auth import actor_id, require
from envelope import created, ok
from errors import ApiError
from store import base_record, date_of, db, now, plus_days, today, touch

bp = Blueprint("conduct_routes", __name__)

SUSPENSION_RESPONSE_WINDOW_DAYS = 14


def _new_proceeding(applicant_id, origin, proposed_by_user_id, grounds_note, review_window_end_date, points):
    rec = base_record()
    rec.update(
        {
            "applicant_id": applicant_id,
            "status": "PROPOSED",
            "origin": origin,
            "proposed_by_user_id": proposed_by_user_id,
            "grounds_note": grounds_note,
            "review_window_end_date": review_window_end_date,
            "points_at_proposal": points,
            "notice_sent_at": None,
            "response_deadline_date": None,
            "rider_response_at": None,
            "rider_response_note": None,
            "decided_by_user_id": None,
            "decision": None,
            "duration_days": 0,
            "suspension_start_date": None,
            "suspension_end_date": None,
            "days_served": 0,
            "days_forgiven": 0,
        }
    )
    db.proceedings[rec["id"]] = rec
    return rec


# ---------------------------------------------------------------------------
# POST /trip-events
# ---------------------------------------------------------------------------

@bp.post("/trip-events")
@require(("ConductOfficer", "AccessibilityOfficeAdmin"))
def ingest_trip_event():
    payload = shapes.body()
    applicant = None
    if payload.get("applicant_id") is not None:
        applicant = lookups.applicant(payload["applicant_id"])
    if applicant is None:
        shapes.req_str(payload, "applicant_id")
    trip_date = shapes.req_iso_date(payload, "trip_date")
    event_type = shapes.req_enum(payload, "event_type", shapes.TRIP_EVENT_TYPES)

    # PRD 3.9: history may be backfilled but the future may not be anticipated.
    if trip_date > today():
        raise ApiError("ERR_TRIP_DATE_FUTURE")

    rec = base_record()
    rec.update(
        {
            "applicant_id": applicant["id"],
            "trip_date": trip_date,
            "event_type": event_type,
            "recorded_at": now(),
            "excused": False,
            "excuse_reason": None,
            "points_assessed": conduct.POINTS[event_type],
        }
    )
    db.trip_events[rec["id"]] = rec
    touch(applicant)

    # PRD 3.9: the auto-proposal cascade, gated on all three thresholds and on
    # no live proceeding already existing for that rider.
    block = conduct.compute_conduct(applicant["id"])
    if conduct.thresholds_met(block) and not conduct.has_live_proceeding(applicant["id"]):
        _new_proceeding(
            applicant["id"],
            "AUTO_THRESHOLD",
            None,
            None,
            today(),
            block["no_show_points_event_basis"],
        )
    return created(serializers.trip_event(rec))


# ---------------------------------------------------------------------------
# POST /trip-events/{id}/excuse
# ---------------------------------------------------------------------------

@bp.post("/trip-events/<trip_event_id>/excuse")
@require(("ConductOfficer", "AccessibilityOfficeAdmin"))
def excuse_trip_event(trip_event_id):
    rec = lookups.trip_event(trip_event_id)
    payload = shapes.body()
    reason = shapes.req_str(payload, "excuse_reason")

    rec["excused"] = True
    rec["excuse_reason"] = reason
    rec["points_assessed"] = 0
    touch(rec)
    applicant = db.applicants.get(rec["applicant_id"])
    if applicant is not None:
        touch(applicant)
    return ok(serializers.trip_event(rec))


# ---------------------------------------------------------------------------
# POST /applicants/{id}/suspension-proceedings
# ---------------------------------------------------------------------------

@bp.post("/applicants/<applicant_id>/suspension-proceedings")
@require(("ConductOfficer",))
def propose_suspension(applicant_id):
    applicant = lookups.applicant(applicant_id)
    payload = shapes.body()
    expected_version = shapes.req_int(payload, "expected_applicant_version")
    review_window_end_date = shapes.req_iso_date(payload, "review_window_end_date")
    grounds_note = shapes.opt_str(payload, "grounds_note", None)

    if expected_version != applicant["version"]:
        raise ApiError("ERR_STALE_APPLICANT_VERSION")

    # PRD 3.9: a newer review supersedes every still-PROPOSED proceeding.
    for other in conduct.proceedings_of(applicant["id"]):
        if other["status"] == "PROPOSED":
            other["status"] = "VOID"
            touch(other)

    block = conduct.compute_conduct(applicant["id"])
    rec = _new_proceeding(
        applicant["id"],
        "MANUAL",
        actor_id(),
        grounds_note,
        review_window_end_date,
        block["no_show_points_event_basis"],
    )
    touch(applicant)
    return created(serializers.proceeding(rec))


# ---------------------------------------------------------------------------
# POST /suspension-proceedings/{id}/send-notice
# ---------------------------------------------------------------------------

@bp.post("/suspension-proceedings/<proceeding_id>/send-notice")
@require(("ConductOfficer",))
def send_notice(proceeding_id):
    rec = lookups.proceeding(proceeding_id)
    shapes.body()

    if rec["status"] != "PROPOSED":
        raise ApiError("ERR_PROCEEDING_STATE_INVALID")

    instant = now()
    rec["notice_sent_at"] = instant
    rec["response_deadline_date"] = plus_days(date_of(instant), SUSPENSION_RESPONSE_WINDOW_DAYS)
    rec["status"] = "NOTICE_SENT"
    touch(rec)
    return ok(serializers.proceeding(rec))


# ---------------------------------------------------------------------------
# POST /suspension-proceedings/{id}/respond
# ---------------------------------------------------------------------------

@bp.post("/suspension-proceedings/<proceeding_id>/respond")
@require(("Applicant",), ownership=owners.proceeding_path)
def respond_to_notice(proceeding_id):
    rec = lookups.proceeding(proceeding_id)
    payload = shapes.body()
    note = shapes.req_str(payload, "rider_response_note")

    if rec["status"] != "NOTICE_SENT":
        raise ApiError("ERR_PROCEEDING_STATE_INVALID")
    if rec["response_deadline_date"] is not None and today() > rec["response_deadline_date"]:
        raise ApiError("ERR_RESPONSE_WINDOW_CLOSED")

    rec["rider_response_at"] = now()
    rec["rider_response_note"] = note
    rec["status"] = "RIDER_RESPONDED"
    touch(rec)
    return ok(serializers.proceeding(rec))


# ---------------------------------------------------------------------------
# POST /suspension-proceedings/{id}/decide
# ---------------------------------------------------------------------------

@bp.post("/suspension-proceedings/<proceeding_id>/decide")
@require(("ConductOfficer",), identity_required=True)
def decide_proceeding(proceeding_id):
    rec = lookups.proceeding(proceeding_id)
    payload = shapes.body()
    decision = shapes.req_enum(payload, "decision", shapes.SUSPENSION_DECISIONS)
    start_date = shapes.opt_iso_date(payload, "suspension_start_date", None)
    if decision == "UPHELD" and start_date is None:
        shapes.bad("suspension_start_date is required when the decision is UPHELD.")
    if decision == "RESCINDED" and start_date is not None:
        shapes.bad("suspension_start_date must be null when the decision is RESCINDED.")

    if rec["status"] not in ("RIDER_RESPONDED", "RESPONSE_LAPSED"):
        raise ApiError("ERR_PROCEEDING_STATE_INVALID")
    if actor_id() == rec["proposed_by_user_id"]:
        raise ApiError("ERR_DECIDER_NOT_INDEPENDENT")
    if rec["notice_sent_at"] is None or rec["status"] not in ("RIDER_RESPONDED", "RESPONSE_LAPSED"):
        raise ApiError("ERR_DUE_PROCESS_INCOMPLETE")

    applicant = db.applicants.get(rec["applicant_id"])

    if decision == "UPHELD":
        block = conduct.compute_conduct(rec["applicant_id"])
        if not conduct.thresholds_met(block):
            raise ApiError("ERR_SUSPENSION_UNSUPPORTED")
        if start_date < today():
            raise ApiError("ERR_SUSPENSION_START_IN_PAST")

        prior = conduct.prior_upheld_count(rec["applicant_id"])
        duration = conduct.ladder_duration(prior)
        rec["decision"] = "UPHELD"
        rec["decided_by_user_id"] = actor_id()
        rec["duration_days"] = duration
        rec["suspension_start_date"] = start_date
        rec["suspension_end_date"] = plus_days(start_date, duration - 1)
        rec["days_served"] = 0
        rec["days_forgiven"] = duration
        rec["status"] = "UPHELD_PENDING"
    else:
        rec["decision"] = "RESCINDED"
        rec["decided_by_user_id"] = actor_id()
        rec["duration_days"] = 0
        rec["suspension_start_date"] = None
        rec["suspension_end_date"] = None
        rec["days_served"] = 0
        rec["days_forgiven"] = 0
        rec["status"] = "RESCINDED"

    touch(rec)
    if applicant is not None:
        touch(applicant)
    return ok(serializers.proceeding(rec))


# ---------------------------------------------------------------------------
# POST /suspension-proceedings/{id}/rescind
# ---------------------------------------------------------------------------

@bp.post("/suspension-proceedings/<proceeding_id>/rescind")
@require(("ConductOfficer", "AccessibilityOfficeAdmin"))
def rescind_proceeding(proceeding_id):
    rec = lookups.proceeding(proceeding_id)
    shapes.body()

    if rec["status"] not in ("UPHELD_PENDING", "ACTIVE"):
        raise ApiError("ERR_PROCEEDING_STATE_INVALID")

    # PRD 3.9: a suspension already running freezes days_served at the inclusive
    # count from suspension_start_date through today; one not yet started
    # forgives the whole term.
    served = conduct.days_served_now(rec)
    rec["days_served"] = served
    rec["days_forgiven"] = rec["duration_days"] - served
    rec["status"] = "VOID"
    touch(rec)
    applicant = db.applicants.get(rec["applicant_id"])
    if applicant is not None:
        touch(applicant)
    return ok(serializers.proceeding(rec))
