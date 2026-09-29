"""The application funnel, touchpoint ingest and source-of-hire attribution."""

from flask import Blueprint

import db
import response
import validation as V
from errors import ApiError
from middleware import require
from services import calc, channel_svc, serialize

bp = Blueprint("applications", __name__)

READ_ROLES = ("BrandProgramLead", "ComplianceReviewer", "MediaBuyer", "RecruitingOps")
TOUCH_TYPES = ("IMPRESSION", "CLICK", "ORGANIC_VISIT", "EVENT_SCAN",
               "EMAIL_CLICK", "REFERRAL")


def _propagate(touchpoints):
    """Hops 2-5: flight and channel counters, pacing, then the throttle."""
    flight_ids, channel_ids = [], []
    for touch in touchpoints:
        if touch["media_flight_id"] and touch["media_flight_id"] not in flight_ids:
            flight_ids.append(touch["media_flight_id"])
        if touch["channel_id"] not in channel_ids:
            channel_ids.append(touch["channel_id"])
    for flight_id in flight_ids:
        flight = db.flights.get(flight_id)
        if flight is not None:
            db.touch(flight)
    channels = [db.channels[cid] for cid in channel_ids if cid in db.channels]
    channels.sort(key=lambda c: c["created_at"])
    for channel in channels:
        channel_svc.recompute_pacing(channel)
        db.touch(channel)
    for channel in channels:
        channel_svc.apply_throttle(channel)


@bp.route("/applications", methods=["POST"])
@require("Anonymous", "Candidate")
def create_application():
    data = V.body()
    job_posting_id = V.field(data, "job_posting_id", "string", required=True)
    candidate_email = V.field(data, "candidate_email", "email", required=True,
                              max_len=200)
    posting = calc.must_get(db.postings, job_posting_id, "ERR_POSTING_NOT_FOUND")
    row = {
        "id": db.new_id(),
        "job_posting_id": posting["id"],
        "candidate_email": candidate_email,
        "status": "STARTED",
        "submitted_at": None,
        "screened_at": None,
        "decided_at": None,
        "attributed_credit_bp_total": 0,
        "eligible_touch_count": 0,
        "attribution_model_applied": None,
    }
    stamp = db.wall_now()
    row.update({"created_at": stamp, "updated_at": stamp, "version": 1})
    db.applications[row["id"]] = row
    return response.ok(serialize.application(row), 201)


@bp.route("/applications/<application_id>/submit", methods=["POST"])
@require("Anonymous", "Candidate")
def submit_application(application_id):
    app = calc.must_get(db.applications, application_id, "ERR_APPLICATION_NOT_FOUND")
    if app["status"] != "STARTED":
        raise ApiError("ERR_APPLICATION_NOT_STARTED", "The application is not STARTED.")
    posting = db.postings[app["job_posting_id"]]
    if posting["compliance_status"] != "CLEARED":
        raise ApiError("ERR_POSTING_COMPLIANCE_NOT_CLEARED",
                       "The posting is not compliance CLEARED.")
    if posting["content_status"] != "PUBLISHED":
        raise ApiError("ERR_POSTING_NOT_PUBLISHED", "The posting is not PUBLISHED.")
    app["status"] = "SUBMITTED"
    app["submitted_at"] = db.clock()
    db.touch(app)
    db.touch(posting)
    return response.ok(serialize.application(app))


@bp.route("/applications/<application_id>/screen", methods=["POST"])
@require("RecruitingOps")
def screen_application(application_id):
    app = calc.must_get(db.applications, application_id, "ERR_APPLICATION_NOT_FOUND")
    if app["status"] != "SUBMITTED":
        raise ApiError("ERR_APPLICATION_NOT_SUBMITTED",
                       "The application is not SUBMITTED.")
    app["status"] = "SCREENED"
    app["screened_at"] = db.clock()
    db.touch(app)
    return response.ok(serialize.application(app))


@bp.route("/applications/<application_id>/decide", methods=["POST"])
@require("RecruitingOps")
def decide_application(application_id):
    data = V.body()
    outcome = V.field(data, "outcome", "enum", required=True,
                      values=("QUALIFIED", "DISQUALIFIED"))
    V.field(data, "reason", "string", nullable=True, min_len=0, max_len=500)
    app = calc.must_get(db.applications, application_id, "ERR_APPLICATION_NOT_FOUND")
    if outcome == "QUALIFIED":
        if app["status"] != "SCREENED":
            raise ApiError("ERR_APPLICATION_NOT_SCREENED",
                           "The application is not SCREENED.")
    elif app["status"] not in ("SCREENED", "QUALIFIED"):
        raise ApiError("ERR_APPLICATION_NOT_DECIDABLE",
                       "The application cannot be decided from this status.")
    posting = db.postings[app["job_posting_id"]]
    program = calc.program_of_posting(posting)

    if outcome == "QUALIFIED":
        model = program["attribution_model"] if program else "LINEAR"
        credits, selected = calc.attribution_credit(app, model)
        if not selected:
            raise ApiError("ERR_NO_ELIGIBLE_TOUCHPOINT",
                           "No touchpoint falls inside the attribution window.")
        for touch in selected:
            touch["credit_bp"] = credits[touch["id"]]
        app["status"] = "QUALIFIED"
        app["decided_at"] = db.clock()
        app["eligible_touch_count"] = len(selected)
        app["attribution_model_applied"] = model
        app["attributed_credit_bp_total"] = 10000
        if program is not None:
            program["last_attribution_recompute_at"] = db.clock()
            db.touch(program)
        _propagate(selected)
        db.touch(app)
        db.touch(posting)
        return response.ok(serialize.application(app))

    if app["status"] == "QUALIFIED":
        affected = [t for t in db.touchpoints.values()
                    if t["application_id"] == app["id"] and t["credit_bp"]]
        affected.sort(key=lambda t: (t["occurred_at"], t["created_at"]))
        for touch in db.touchpoints.values():
            if touch["application_id"] == app["id"]:
                touch["credit_bp"] = 0
        app["status"] = "DISQUALIFIED"
        app["decided_at"] = db.clock()
        app["attributed_credit_bp_total"] = 0
        app["attribution_model_applied"] = None
        _propagate(affected)
        db.touch(app)
        db.touch(posting)
        return response.ok(serialize.application(app))

    app["status"] = "DISQUALIFIED"
    app["decided_at"] = db.clock()
    db.touch(app)
    return response.ok(serialize.application(app))


@bp.route("/applications/<application_id>", methods=["GET"])
@require(*READ_ROLES)
def get_application(application_id):
    app = calc.must_get(db.applications, application_id, "ERR_APPLICATION_NOT_FOUND")
    return response.ok(serialize.application(app))


@bp.route("/applications", methods=["GET"])
@require(*READ_ROLES)
def list_applications():
    limit, offset = V.pagination()
    rows = calc.by_created(db.applications.values())
    for name in ("job_posting_id", "status", "candidate_email"):
        value = V.qs(name)
        if value:
            rows = [r for r in rows if r[name] == value]
    page, meta = V.window(rows, limit, offset)
    return response.ok_list([serialize.application(r) for r in page], meta)


# --------------------------------------------------------------- touchpoints
@bp.route("/touchpoints", methods=["POST"])
@require("RecruitingOps", "MediaBuyer")
def create_touchpoint():
    data = V.body()
    application_id = V.field(data, "application_id", "string", required=True)
    channel_id = V.field(data, "channel_id", "string", required=True)
    media_flight_id = V.field(data, "media_flight_id", "string", nullable=True)
    touch_type = V.field(data, "touch_type", "enum", required=True, values=TOUCH_TYPES)
    occurred_at = V.field(data, "occurred_at", "datetime", required=True)
    media_cost_cents = V.field(data, "media_cost_cents", "integer",
                               default=0, min_value=0)
    app = calc.must_get(db.applications, application_id, "ERR_APPLICATION_NOT_FOUND")
    channel = calc.must_get(db.channels, channel_id, "ERR_CHANNEL_NOT_FOUND")
    flight = None
    if media_flight_id is not None:
        flight = calc.must_get(db.flights, media_flight_id, "ERR_FLIGHT_NOT_FOUND")
    row = {
        "id": db.new_id(),
        "application_id": app["id"],
        "channel_id": channel["id"],
        "media_flight_id": flight["id"] if flight else None,
        "touch_type": touch_type,
        "occurred_at": occurred_at,
        "media_cost_cents": media_cost_cents,
        "credit_bp": 0,
        "created_at": db.wall_now(),
    }
    db.touchpoints[row["id"]] = row
    return response.ok(serialize.touchpoint(row), 201)


@bp.route("/touchpoints/<touchpoint_id>", methods=["GET"])
@require(*READ_ROLES)
def get_touchpoint(touchpoint_id):
    row = calc.must_get(db.touchpoints, touchpoint_id, "ERR_RECORD_NOT_FOUND")
    return response.ok(serialize.touchpoint(row))


@bp.route("/touchpoints", methods=["GET"])
@require(*READ_ROLES)
def list_touchpoints():
    limit, offset = V.pagination()
    rows = sorted(db.touchpoints.values(),
                  key=lambda r: (r["occurred_at"], r["created_at"]))
    for name in ("application_id", "channel_id", "media_flight_id", "touch_type"):
        value = V.qs(name)
        if value:
            rows = [r for r in rows if r[name] == value]
    page, meta = V.window(rows, limit, offset)
    return response.ok_list([serialize.touchpoint(r) for r in page], meta)
