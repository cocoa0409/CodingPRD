"""Participant intake + lifecycle, emergency contacts, waitlist entries,
call schedules, satisfaction surveys."""
from datetime import timedelta

from flask import Blueprint, request

from auth import endpoint, get_body
from db import store, now, new_entity, touch
from envelope import ok, ok_list
from errors import (raise_err, ERR_NOT_FOUND, ERR_INVALID_REQUEST,
                    ERR_INVALID_STATE, ERR_INTAKE_PAUSED,
                    ERR_PARTICIPANT_NOT_ENROLLED, ERR_EMERGENCY_CONTACT_REQUIRED,
                    ERR_NO_24H_CONTACT, ERR_CAPACITY_REACHED, ERR_OFFER_NOT_OPEN,
                    ERR_REAPPLICATION_TOO_SOON, ERR_DUPLICATE_SCHEDULE,
                    ERR_SURVEY_PERIOD_DUPLICATE)
from validate import (Field, validate_payload, parse_pagination, sort_items,
                      parse_bool_filter)
import calc
import cascade
import serialize
import timeutil
from timeutil import parse_hm

bp = Blueprint("participants", __name__)

IW = ["IntakeWorker"]
PC = ["ProgramCoordinator"]
IW_PC = ["IntakeWorker", "ProgramCoordinator"]
READ_P = ["ProgramCoordinator", "IntakeWorker", "QualityReviewer"]
ALL = ["ProgramCoordinator", "IntakeWorker", "QualityReviewer",
       "VolunteerCaller", "ExternalResponder"]

REFERRAL_SOURCES = {"SELF", "FAMILY", "APS_REFERRAL", "HOSPITAL_DISCHARGE",
                    "OTHER_PROVIDER"}
AGE_BANDS = {"AGE_65_74", "AGE_75_84", "AGE_85_PLUS"}
MOBILITY = {"NONE", "LIMITED", "SEVERE"}
WEEKDAYS = {"MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"}

INTAKE_SPEC = [
    Field("full_name", "str", required=True, allow_empty_str=False),
    Field("date_of_birth", "date", required=True),
    Field("phone", "str", required=True, allow_empty_str=False),
    Field("address", "str", required=True),
    Field("referral_source", "enum", required=True, enum=REFERRAL_SOURCES),
    Field("age_band", "enum", required=True, enum=AGE_BANDS),
    Field("lives_alone", "bool", required=True),
    Field("mobility", "enum", required=True, enum=MOBILITY),
    Field("cognitive_concern", "bool", required=True),
    Field("chronic_conditions_count", "int", required=True, minv=0, maxv=10),
    Field("recent_hospitalization", "bool", required=True),
    Field("recent_bereavement", "bool", required=True),
    Field("primary_language", "str", default="en"),
]


def get_participant_or_404(pid):
    p = store.participants.get(pid)
    if not p:
        raise_err(ERR_NOT_FOUND, "Participant not found")
    return p


def require_program():
    g = calc.sole_program()
    if not g:
        raise_err(ERR_NOT_FOUND, "Program not found")
    return g


@bp.route("/api/participants", methods=["POST"])
@endpoint(IW)
def create_participant(uid, role):
    data = validate_payload(get_body(), INTAKE_SPEC)
    g = require_program()
    if g["intake_posture"] != "OPEN":
        raise_err(ERR_INTAKE_PAUSED, "Program intake is paused")
    p = new_entity()
    p.update({
        "full_name": data["full_name"],
        "date_of_birth": data["date_of_birth"],
        "phone": data["phone"],
        "address": data["address"],
        "primary_language": data.get("primary_language", "en"),
        "referral_source": data["referral_source"],
        "age_band": data["age_band"],
        "lives_alone": data["lives_alone"],
        "mobility": data["mobility"],
        "cognitive_concern": data["cognitive_concern"],
        "chronic_conditions_count": data["chronic_conditions_count"],
        "recent_hospitalization": data["recent_hospitalization"],
        "recent_bereavement": data["recent_bereavement"],
        "acuity_score": None,
        "acuity_tier": None,
        "rolling_acuity_score": None,
        "rolling_acuity_tier": None,
        "status": "APPLICANT",
        "consecutive_no_answer_count": 0,
        "open_escalation_id": None,
        "coverage_deficient": False,
        "enrolled_at": None,
        "last_status_change_at": None,
    })
    store.participants[p["id"]] = p
    return ok(serialize.participant(p), 201)


@bp.route("/api/participants", methods=["GET"])
@endpoint(ALL)
def list_participants(uid, role):
    limit, offset = parse_pagination(request.args)
    items = list(store.participants.values())
    if "status" in request.args:
        items = [p for p in items if p["status"] == request.args["status"]]
    if "acuity_tier" in request.args:
        items = [p for p in items if p["acuity_tier"] == request.args["acuity_tier"]]
    cov = parse_bool_filter(request.args, "coverage_deficient")
    if cov is not None:
        items = [p for p in items if p["coverage_deficient"] == cov]
    items = sort_items(items)
    total = len(items)
    return ok_list([serialize.participant(p) for p in items[offset:offset + limit]],
                   total, limit, offset)


@bp.route("/api/participants/<pid>", methods=["GET"])
@endpoint(ALL)
def get_participant(pid, uid, role):
    return ok(serialize.participant(get_participant_or_404(pid)))


@bp.route("/api/participants/<pid>", methods=["PATCH"])
@endpoint(IW)
def patch_participant(pid, uid, role):
    p = get_participant_or_404(pid)
    data = validate_payload(get_body(), INTAKE_SPEC, partial=True)
    if p["status"] not in ("APPLICANT", "UNDER_REVIEW"):
        raise_err(ERR_INVALID_STATE, "Intake fields editable only while APPLICANT or UNDER_REVIEW")
    for key, val in data.items():
        p[key] = val
    touch(p)
    return ok(serialize.participant(p))


@bp.route("/api/participants/<pid>/submit-review", methods=["POST"])
@endpoint(IW)
def submit_review(pid, uid, role):
    p = get_participant_or_404(pid)
    if p["status"] not in ("APPLICANT", "UNDER_REVIEW"):
        raise_err(ERR_INVALID_STATE, "Participant is not APPLICANT")
    score, tier = calc.compute_intake_acuity(p)
    p["acuity_score"] = score
    p["acuity_tier"] = tier
    p["status"] = "UNDER_REVIEW"
    p["last_status_change_at"] = now()
    touch(p)
    return ok(serialize.participant(p))


@bp.route("/api/participants/<pid>/approve", methods=["POST"])
@endpoint(IW)
def approve(pid, uid, role):
    p = get_participant_or_404(pid)
    if p["status"] != "UNDER_REVIEW":
        raise_err(ERR_INVALID_STATE, "Participant is not UNDER_REVIEW")
    g = require_program()
    if g["intake_posture"] != "OPEN":
        raise_err(ERR_INTAKE_PAUSED, "Program intake is paused")
    actives = [c for c in store.contacts.values()
               if c["participant_id"] == p["id"] and c["status"] == "ACTIVE"]
    if not any(c["contact_rank"] == "PRIMARY" for c in actives):
        raise_err(ERR_EMERGENCY_CONTACT_REQUIRED,
                  "An ACTIVE PRIMARY emergency contact is required")
    if calc.effective_tier(p) in ("HIGH", "CRITICAL"):
        if not any(c["accepts_24h"] for c in actives):
            raise_err(ERR_NO_24H_CONTACT,
                      "An ACTIVE accepts_24h contact is required for HIGH/CRITICAL")
    if calc.admit_ok(g, p["acuity_tier"]):
        p["status"] = "ENROLLED"
        p["enrolled_at"] = now()
        p["last_status_change_at"] = now()
        touch(p)
        touch(g)  # occupied_slots moved -> program version bump
    else:
        p["status"] = "WAITLISTED"
        p["last_status_change_at"] = now()
        touch(p)
        e = new_entity()
        e.update({
            "participant_id": p["id"],
            "status": "WAITING",
            "waitlist_entered_at": now(),
            "offered_at": None,
            "offer_expires_at": None,
            "declines_count": 0,
            "expires_count": 0,
            "priority_score_at_offer": None,
            "removal_reason": None,
        })
        store.waitlist[e["id"]] = e
    return ok(serialize.participant(p))


@bp.route("/api/participants/<pid>/deny", methods=["POST"])
@endpoint(IW)
def deny(pid, uid, role):
    p = get_participant_or_404(pid)
    validate_payload(get_body(), [Field("reason", "str", required=True)])
    if p["status"] != "UNDER_REVIEW":
        raise_err(ERR_INVALID_STATE, "Participant is not UNDER_REVIEW")
    p["status"] = "DENIED"
    p["last_status_change_at"] = now()
    touch(p)
    return ok(serialize.participant(p))


@bp.route("/api/participants/<pid>/suspend", methods=["POST"])
@endpoint(PC)
def suspend(pid, uid, role):
    p = get_participant_or_404(pid)
    validate_payload(get_body(), [Field("reason", "str", required=True)])
    if p["status"] != "ENROLLED":
        raise_err(ERR_INVALID_STATE, "Participant is not ENROLLED")
    p["status"] = "SUSPENDED"
    p["last_status_change_at"] = now()
    touch(p)
    for a in list(store.assignments.values()):
        if a["participant_id"] == p["id"] and a["status"] == "SCHEDULED":
            cascade.cancel_assignment(a, "PARTICIPANT_SUSPEND")
    calc.recompute_coverage(p)
    return ok(serialize.participant(p))


@bp.route("/api/participants/<pid>/resume", methods=["POST"])
@endpoint(PC)
def resume(pid, uid, role):
    p = get_participant_or_404(pid)
    if p["status"] != "SUSPENDED":
        raise_err(ERR_INVALID_STATE, "Participant is not SUSPENDED")
    g = require_program()
    p["status"] = "ENROLLED"
    p["last_status_change_at"] = now()
    touch(p)
    cascade.regenerate_assignments(p, g)
    calc.recompute_coverage(p)
    return ok(serialize.participant(p))


@bp.route("/api/participants/<pid>/disenroll", methods=["POST"])
@endpoint(PC)
def disenroll(pid, uid, role):
    p = get_participant_or_404(pid)
    validate_payload(get_body(), [Field("reason", "str", required=True)])
    if p["status"] not in ("ENROLLED", "SUSPENDED", "WELFARE_HOLD"):
        raise_err(ERR_INVALID_STATE, "Participant cannot be disenrolled from this state")
    g = require_program()
    p["status"] = "DISENROLLED"
    p["last_status_change_at"] = now()
    touch(p)
    touch(g)  # occupied_slots decremented -> program version bump
    for a in list(store.assignments.values()):
        if a["participant_id"] == p["id"] and a["status"] == "SCHEDULED":
            cascade.cancel_assignment(a, "MANUAL")
    return ok(serialize.participant(p))


@bp.route("/api/participants/<pid>/reapply", methods=["POST"])
@endpoint(IW)
def reapply(pid, uid, role):
    p = get_participant_or_404(pid)
    if p["status"] not in ("DENIED", "DISENROLLED", "EXITED"):
        raise_err(ERR_INVALID_STATE, "Participant cannot re-apply from this state")
    g = require_program()
    earliest = p["last_status_change_at"] + timedelta(days=g["reapply_cooling_days"])
    if now() < earliest:
        raise_err(ERR_REAPPLICATION_TOO_SOON, "Cooling-off period has not elapsed")
    p["status"] = "APPLICANT"
    p["acuity_score"] = None
    p["acuity_tier"] = None
    p["rolling_acuity_score"] = None
    p["rolling_acuity_tier"] = None
    p["consecutive_no_answer_count"] = 0
    p["last_status_change_at"] = now()
    touch(p)
    return ok(serialize.participant(p))


# ---------------- emergency contacts ----------------

CONTACT_SPEC = [
    Field("full_name", "str", required=True, allow_empty_str=False),
    Field("phone", "str", required=True, allow_empty_str=False),
    Field("relationship", "str", required=True),
    Field("contact_rank", "enum", required=True, enum={"PRIMARY", "SECONDARY"}),
    Field("accepts_24h", "bool", default=False),
]


@bp.route("/api/participants/<pid>/emergency-contacts", methods=["GET"])
@endpoint(READ_P)
def list_contacts(pid, uid, role):
    p = get_participant_or_404(pid)
    limit, offset = parse_pagination(request.args)
    items = [c for c in store.contacts.values() if c["participant_id"] == p["id"]]
    if "status" in request.args:
        items = [c for c in items if c["status"] == request.args["status"]]
    items = sort_items(items)
    total = len(items)
    return ok_list([serialize.contact(c) for c in items[offset:offset + limit]],
                   total, limit, offset)


@bp.route("/api/participants/<pid>/emergency-contacts", methods=["POST"])
@endpoint(IW_PC)
def create_contact(pid, uid, role):
    p = get_participant_or_404(pid)
    data = validate_payload(get_body(), CONTACT_SPEC)
    c = new_entity()
    c.update({
        "participant_id": p["id"],
        "full_name": data["full_name"],
        "phone": data["phone"],
        "relationship": data["relationship"],
        "contact_rank": data["contact_rank"],
        "accepts_24h": data.get("accepts_24h", False),
        "status": "ACTIVE",
    })
    store.contacts[c["id"]] = c
    return ok(serialize.contact(c), 201)


def get_contact_or_404(cid):
    c = store.contacts.get(cid)
    if not c:
        raise_err(ERR_NOT_FOUND, "Emergency contact not found")
    return c


@bp.route("/api/emergency-contacts/<cid>/deactivate", methods=["POST"])
@endpoint(IW_PC)
def deactivate_contact(cid, uid, role):
    c = get_contact_or_404(cid)
    if c["status"] == "REMOVED":
        raise_err(ERR_INVALID_STATE, "Contact already REMOVED")
    c["status"] = "REMOVED"
    touch(c)
    return ok(serialize.contact(c))


@bp.route("/api/emergency-contacts/<cid>/reactivate", methods=["POST"])
@endpoint(IW_PC)
def reactivate_contact(cid, uid, role):
    c = get_contact_or_404(cid)
    if c["status"] not in ("UNREACHABLE", "REMOVED"):
        raise_err(ERR_INVALID_STATE, "Contact is not UNREACHABLE or REMOVED")
    c["status"] = "ACTIVE"
    touch(c)
    return ok(serialize.contact(c))


# ---------------- waitlist entries ----------------

@bp.route("/api/participants/<pid>/waitlist-entries", methods=["GET"])
@endpoint(READ_P)
def list_waitlist(pid, uid, role):
    p = get_participant_or_404(pid)
    limit, offset = parse_pagination(request.args)
    items = [e for e in store.waitlist.values() if e["participant_id"] == p["id"]]
    items = sort_items(items)
    total = len(items)
    return ok_list([serialize.waitlist_entry(e) for e in items[offset:offset + limit]],
                   total, limit, offset)


def get_entry_or_404(wid):
    e = store.waitlist.get(wid)
    if not e:
        raise_err(ERR_NOT_FOUND, "Waitlist entry not found")
    return e


@bp.route("/api/waitlist-entries/<wid>", methods=["GET"])
@endpoint(READ_P)
def get_entry(wid, uid, role):
    return ok(serialize.waitlist_entry(get_entry_or_404(wid)))


@bp.route("/api/waitlist-entries/<wid>/accept", methods=["POST"])
@endpoint(IW)
def accept_entry(wid, uid, role):
    e = get_entry_or_404(wid)
    if e["status"] != "OFFERED":
        raise_err(ERR_OFFER_NOT_OPEN, "Waitlist entry is not OFFERED")
    if e["offer_expires_at"] is not None and now() > e["offer_expires_at"]:
        raise_err(ERR_OFFER_NOT_OPEN, "Offer has expired")
    g = require_program()
    p = get_participant_or_404(e["participant_id"])
    if not calc.admit_ok(g, p["acuity_tier"]):
        raise_err(ERR_CAPACITY_REACHED, "Free capacity exhausted")
    e["status"] = "ACCEPTED"
    touch(e)
    p["status"] = "ENROLLED"
    p["enrolled_at"] = now()
    p["last_status_change_at"] = now()
    touch(p)
    touch(g)
    return ok(serialize.waitlist_entry(e))


@bp.route("/api/waitlist-entries/<wid>/decline", methods=["POST"])
@endpoint(IW)
def decline_entry(wid, uid, role):
    e = get_entry_or_404(wid)
    if e["status"] != "OFFERED":
        raise_err(ERR_OFFER_NOT_OPEN, "Waitlist entry is not OFFERED")
    e["declines_count"] += 1
    e["offered_at"] = None
    e["offer_expires_at"] = None
    if e["declines_count"] >= 2:
        e["status"] = "REMOVED"
        e["removal_reason"] = "MAX_DECLINES"
        touch(e)
        cascade.exit_waitlist_participant(e)
    else:
        e["status"] = "WAITING"
        touch(e)
    return ok(serialize.waitlist_entry(e))


@bp.route("/api/waitlist-entries/<wid>/withdraw", methods=["POST"])
@endpoint(IW)
def withdraw_entry(wid, uid, role):
    e = get_entry_or_404(wid)
    if e["status"] not in ("WAITING", "OFFERED"):
        raise_err(ERR_OFFER_NOT_OPEN, "Waitlist entry is not WAITING or OFFERED")
    e["status"] = "REMOVED"
    e["removal_reason"] = "WITHDRAWN"
    touch(e)
    cascade.exit_waitlist_participant(e)
    return ok(serialize.waitlist_entry(e))


# ---------------- call schedules ----------------

SCHEDULE_SPEC = [
    Field("weekday", "enum", required=True, enum=WEEKDAYS),
    Field("window_start", "hm", required=True),
    Field("window_end", "hm", required=True),
]


@bp.route("/api/participants/<pid>/call-schedules", methods=["GET"])
@endpoint(READ_P)
def list_schedules(pid, uid, role):
    p = get_participant_or_404(pid)
    limit, offset = parse_pagination(request.args)
    items = [s for s in store.schedules.values() if s["participant_id"] == p["id"]]
    if "status" in request.args:
        items = [s for s in items if s["status"] == request.args["status"]]
    items = sort_items(items)
    total = len(items)
    return ok_list([serialize.schedule(s) for s in items[offset:offset + limit]],
                   total, limit, offset)


@bp.route("/api/participants/<pid>/call-schedules", methods=["POST"])
@endpoint(PC)
def create_schedule(pid, uid, role):
    p = get_participant_or_404(pid)
    data = validate_payload(get_body(), SCHEDULE_SPEC)
    ws, we = parse_hm(data["window_start"]), parse_hm(data["window_end"])
    if ws >= we:
        raise_err(ERR_INVALID_REQUEST, "window_start must be before window_end")
    if not (15 <= we - ws <= 120):
        raise_err(ERR_INVALID_REQUEST, "Schedule window must be 15..120 minutes")
    if p["status"] != "ENROLLED":
        raise_err(ERR_PARTICIPANT_NOT_ENROLLED, "Participant is not ENROLLED")
    for s in store.schedules.values():
        if (s["participant_id"] == p["id"] and s["weekday"] == data["weekday"]
                and s["status"] in ("ACTIVE", "PAUSED")):
            raise_err(ERR_DUPLICATE_SCHEDULE,
                      "An ACTIVE or PAUSED schedule already exists for that weekday")
    s = new_entity()
    s.update({
        "participant_id": p["id"],
        "weekday": data["weekday"],
        "window_start": data["window_start"],
        "window_end": data["window_end"],
        "status": "ACTIVE",
    })
    store.schedules[s["id"]] = s
    calc.recompute_coverage(p)
    return ok(serialize.schedule(s), 201)


def get_schedule_or_404(sid):
    s = store.schedules.get(sid)
    if not s:
        raise_err(ERR_NOT_FOUND, "Call schedule not found")
    return s


@bp.route("/api/call-schedules/<sid>/pause", methods=["POST"])
@endpoint(PC)
def pause_schedule(sid, uid, role):
    s = get_schedule_or_404(sid)
    if s["status"] != "ACTIVE":
        raise_err(ERR_INVALID_STATE, "Schedule is not ACTIVE")
    s["status"] = "PAUSED"
    touch(s)
    calc.recompute_coverage(store.participants[s["participant_id"]])
    return ok(serialize.schedule(s))


@bp.route("/api/call-schedules/<sid>/resume", methods=["POST"])
@endpoint(PC)
def resume_schedule(sid, uid, role):
    s = get_schedule_or_404(sid)
    if s["status"] != "PAUSED":
        raise_err(ERR_INVALID_STATE, "Schedule is not PAUSED")
    s["status"] = "ACTIVE"
    touch(s)
    calc.recompute_coverage(store.participants[s["participant_id"]])
    return ok(serialize.schedule(s))


@bp.route("/api/call-schedules/<sid>/archive", methods=["POST"])
@endpoint(PC)
def archive_schedule(sid, uid, role):
    s = get_schedule_or_404(sid)
    if s["status"] not in ("ACTIVE", "PAUSED"):
        raise_err(ERR_INVALID_STATE, "Schedule cannot be archived from this state")
    s["status"] = "ARCHIVED"
    touch(s)
    calc.recompute_coverage(store.participants[s["participant_id"]])
    return ok(serialize.schedule(s))


# ---------------- satisfaction surveys ----------------

@bp.route("/api/participants/<pid>/satisfaction-surveys", methods=["GET"])
@endpoint(READ_P)
def list_surveys(pid, uid, role):
    p = get_participant_or_404(pid)
    limit, offset = parse_pagination(request.args)
    items = [s for s in store.surveys.values() if s["participant_id"] == p["id"]]
    if "period_month" in request.args:
        items = [s for s in items if s["period_month"] == request.args["period_month"]]
    items = sort_items(items)
    total = len(items)
    return ok_list([serialize.survey(s) for s in items[offset:offset + limit]],
                   total, limit, offset)


@bp.route("/api/participants/<pid>/satisfaction-surveys", methods=["POST"])
@endpoint(IW)
def issue_survey(pid, uid, role):
    p = get_participant_or_404(pid)
    data = validate_payload(get_body(),
                            [Field("period_month", "month", required=True)])
    if p["status"] != "ENROLLED":
        raise_err(ERR_PARTICIPANT_NOT_ENROLLED, "Participant is not ENROLLED")
    for s in store.surveys.values():
        if (s["participant_id"] == p["id"]
                and s["period_month"] == data["period_month"]):
            raise_err(ERR_SURVEY_PERIOD_DUPLICATE,
                      "A survey already exists for this participant and period")
    s = new_entity()
    s.update({
        "participant_id": p["id"],
        "period_month": data["period_month"],
        "issued_at": now(),
        "status": "ISSUED",
        "items": None,
        "survey_mean": None,
    })
    store.surveys[s["id"]] = s
    return ok(serialize.survey(s), 201)


def get_survey_or_404(sid):
    s = store.surveys.get(sid)
    if not s:
        raise_err(ERR_NOT_FOUND, "Satisfaction survey not found")
    return s


@bp.route("/api/satisfaction-surveys/<sid>", methods=["GET"])
@endpoint(READ_P)
def get_survey(sid, uid, role):
    return ok(serialize.survey(get_survey_or_404(sid)))


@bp.route("/api/satisfaction-surveys/<sid>/return", methods=["POST"])
@endpoint(IW)
def return_survey(sid, uid, role):
    s = get_survey_or_404(sid)
    data = validate_payload(get_body(), [Field("items", "items5", required=True)])
    if s["status"] != "ISSUED":
        raise_err(ERR_INVALID_STATE, "Survey is not ISSUED")
    s["items"] = data["items"]
    s["survey_mean"] = calc.survey_mean(data["items"])
    s["status"] = "SCORED"
    touch(s)
    return ok(serialize.survey(s))
