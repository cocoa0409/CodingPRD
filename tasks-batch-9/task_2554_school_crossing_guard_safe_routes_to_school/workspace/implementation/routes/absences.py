"""Absence intake, the substitute-offer ladder and the cost of coverage
(PRD 3.6)."""
from datetime import timedelta
from decimal import Decimal

from flask import Blueprint

import calc
import domain
import validate as v
from auth import require
from db import base_entity, db, now, touch
from errors import fail
from response import list_response, object_response
from timeutil import combine, fmt_date, fmt_dt, parse_date, parse_dt, parse_hhmm

bp = Blueprint("absences", __name__)

REASONS = ("ILLNESS", "FAMILY", "WEATHER", "TRAINING", "UNEXCUSED")
RESPONSES = ("ACCEPT", "DECLINE")
READ_ROLES = ("ProgramAdmin", "CrossingSupervisor", "CrossingGuard")
RESCINDABLE = ("DISPATCH_PENDING", "OFFER_OUT", "UNCOVERED_GAP")
SECONDS_PER_HOUR = Decimal("3600")


@bp.post("/srts/absence-reports")
def file_absence():
    user_id, role = require("CrossingGuard", "CrossingSupervisor")
    body = v.body()
    assignment_id = v.req_str(body, "post_assignment_id")
    absence_date = v.req_date(body, "absence_date")
    reason = v.req_enum(body, "reason", REASONS)
    note = v.opt_str(body, "note")
    assignment = domain.get_assignment(assignment_id)

    if assignment["status"] not in domain.LIVE_ASSIGNMENT_STATUSES:
        fail("ERR_ASSIGNMENT_NOT_ACTIVE",
             "An absence can only be filed against a SCHEDULED or ACTIVE assignment.")

    start = parse_date(assignment["start_date"])
    end = parse_date(assignment["end_date"])
    if absence_date < start or absence_date > end:
        fail("ERR_ABSENCE_OUTSIDE_ASSIGNMENT",
             "absence_date must fall inside the assignment's closed window.")

    school = domain.school_of_assignment(assignment)
    date_text = fmt_date(absence_date)
    if date_text in school["no_school_dates"]:
        fail("ERR_ABSENCE_ON_NON_SCHOOL_DAY",
             "There is nothing to cover on a day with no school.")

    for other in domain.absences_of_assignment(assignment):
        if other["absence_date"] != date_text:
            continue
        if other["status"] in ("COVERED", "RESCINDED"):
            continue
        fail("ERR_ABSENCE_DUPLICATE",
             "A live absence report already exists for this duty day.")

    if role == "CrossingGuard" and user_id != assignment["guard_id"]:
        fail("ERR_UNAUTHORIZED",
             "A CrossingGuard may only file absences against their own assignment.")

    shift = assignment["shift"]
    created = now()
    shift_start = _pinned_shift_start(school, shift, absence_date, date_text)
    notice_hours = (Decimal((shift_start - created).total_seconds())
                    / SECONDS_PER_HOUR)

    absence = base_entity()
    absence.update({
        "post_assignment_id": assignment["id"],
        "guard_id": assignment["guard_id"],
        "absence_date": date_text,
        "shift": shift,
        "reason": reason,
        "note": note,
        "status": "DISPATCH_PENDING",
        "shift_start_utc": fmt_dt(shift_start),
        "notice_hours": float(notice_hours),
        "urgency_tier": calc.urgency_tier(notice_hours),
        "dispatch_attempt_count": 0,
        "dispatch_offers": [],
        "current_offer_guard_id": None,
        "current_offer_expires_at": None,
        "excluded_guard_ids": [],
        "substitute_guard_id": None,
        "substitute_cost_cents": None,
        "rescind_reason": None,
    })
    db.absences[absence["id"]] = absence

    domain.propagate_from_assignment(assignment)

    guard = db.guards.get(assignment["guard_id"])
    if guard is not None:
        domain.refresh_reliability_and_touch(guard)
        domain.apply_reliability_breach(guard)
    return object_response(absence, 201)


def _pinned_shift_start(school, shift, absence_date, date_text):
    """shift_start_utc is pinned at creation and never recomputed (PRD 3.6)."""
    if shift in ("AM", "BOTH"):
        clock_time = parse_hhmm(school["am_window_start_utc"])
        moment = combine(absence_date, clock_time)
    else:
        clock_time = parse_hhmm(school["pm_window_start_utc"])
        moment = combine(absence_date, clock_time)
        if date_text in school["early_dismissal_dates"]:
            moment = moment + timedelta(
                minutes=int(school["early_dismissal_pm_offset_minutes"]))
    return moment


@bp.get("/srts/absence-reports/<absence_id>")
def read_absence(absence_id):
    require(*READ_ROLES)
    absence = domain.get_absence(absence_id)
    return object_response(absence)


@bp.get("/srts/absence-reports")
def list_absences():
    require(*READ_ROLES)
    limit, offset = v.pagination()
    assignment_id = v.query_filter("post_assignment_id")
    guard_id = v.query_filter("guard_id")
    status = v.query_filter("status")
    records = list(db.absences.values())
    if assignment_id is not None:
        records = [a for a in records if a["post_assignment_id"] == assignment_id]
    if guard_id is not None:
        records = [a for a in records if a["guard_id"] == guard_id]
    if status is not None:
        records = [a for a in records if a["status"] == status]
    return list_response(records, limit, offset)


def _open_offer(absence):
    for offer in reversed(absence["dispatch_offers"]):
        if offer["offer_status"] == "OPEN":
            return offer
    return None


@bp.post("/srts/absence-reports/<absence_id>/dispatch")
def dispatch_absence(absence_id):
    require("CrossingSupervisor")
    absence = domain.get_absence(absence_id)

    status = absence["status"]
    lapsed = False
    if status in ("DISPATCH_PENDING", "UNCOVERED_GAP"):
        pass
    elif status == "OFFER_OUT":
        expires_at = parse_dt(absence["current_offer_expires_at"])
        if expires_at is None or now() <= expires_at:
            fail("ERR_ABSENCE_NOT_DISPATCHABLE",
                 "The standing offer on this report has not lapsed yet.")
        lapsed = True
    else:
        fail("ERR_ABSENCE_NOT_DISPATCHABLE",
             "This report is not in a dispatchable state.")

    if lapsed:
        offer = _open_offer(absence)
        if offer is not None:
            offer["offer_status"] = "EXPIRED"
            if offer["offered_guard_id"] not in absence["excluded_guard_ids"]:
                absence["excluded_guard_ids"].append(offer["offered_guard_id"])
        absence["current_offer_guard_id"] = None
        absence["current_offer_expires_at"] = None

    candidate = _select_substitute(absence)
    if candidate is None:
        absence["status"] = "UNCOVERED_GAP"
        touch(absence)
        return object_response(absence)

    moment = now()
    expires_at = fmt_dt(moment + timedelta(minutes=calc.OFFER_TTL_MINUTES))
    absence["dispatch_offers"].append({
        "attempt_number": absence["dispatch_attempt_count"] + 1,
        "offered_guard_id": candidate["id"],
        "offered_at": fmt_dt(moment),
        "offer_expires_at": expires_at,
        "offer_status": "OPEN",
    })
    absence["dispatch_attempt_count"] += 1
    absence["current_offer_guard_id"] = candidate["id"]
    absence["current_offer_expires_at"] = expires_at
    absence["status"] = "OFFER_OUT"
    touch(absence)
    return object_response(absence)


def _select_substitute(absence):
    """Eligibility filter then the three ranking keys of PRD 3.6."""
    assignment = domain.assignment_of_absence(absence)
    post = domain.post_of_assignment(assignment)
    required_shift = post["required_shift"]
    zone_code = post["zone_code"]
    absence_date = parse_date(absence["absence_date"])

    eligible = []
    for guard in db.guards.values():
        if guard["certification_status"] != "CERTIFIED":
            continue
        expires_on = parse_date(guard["certification_expires_on"])
        if expires_on is None or expires_on < absence_date:
            continue
        if guard["duty_status"] not in ("UNASSIGNED", "ASSIGNED"):
            continue
        if not guard["equipment_complete"]:
            continue
        if not guard["substitute_pool_optin"]:
            continue
        if guard["id"] == absence["guard_id"]:
            continue
        if guard["id"] in absence["excluded_guard_ids"]:
            continue
        if domain.guard_busy_on(guard, absence_date, required_shift):
            continue
        eligible.append(guard)

    if not eligible:
        return None

    def rank(guard):
        score = calc.dec(guard["reliability_score_season_to_date"])
        zone_match = 0 if guard["home_zone_code"] == zone_code else 1
        return (-score, zone_match, guard["created_at"], guard["_seq"])

    eligible.sort(key=rank)
    return eligible[0]


@bp.post("/srts/absence-reports/<absence_id>/offer-response")
def answer_offer(absence_id):
    user_id, _role = require("CrossingGuard")
    body = v.body()
    response = v.req_enum(body, "response", RESPONSES)
    absence = domain.get_absence(absence_id)

    if absence["status"] != "OFFER_OUT":
        fail("ERR_NO_OPEN_OFFER", "This report carries no open substitute offer.")
    if user_id != absence["current_offer_guard_id"]:
        fail("ERR_NOT_OFFER_RECIPIENT",
             "Only the current offer recipient may answer it.")
    expires_at = parse_dt(absence["current_offer_expires_at"])
    if expires_at is None or now() > expires_at:
        fail("ERR_OFFER_EXPIRED", "The offer has lapsed.")

    offer = _open_offer(absence)
    if response == "DECLINE":
        if offer is not None:
            offer["offer_status"] = "DECLINED"
        if user_id not in absence["excluded_guard_ids"]:
            absence["excluded_guard_ids"].append(user_id)
        absence["current_offer_guard_id"] = None
        absence["current_offer_expires_at"] = None
        absence["status"] = "DISPATCH_PENDING"
        touch(absence)
        return object_response(absence)

    if offer is not None:
        offer["offer_status"] = "ACCEPTED"
    absence["substitute_guard_id"] = user_id
    absence["status"] = "COVERED"
    absence["substitute_cost_cents"] = calc.substitute_cost_cents(
        absence["shift"], absence["urgency_tier"], absence["dispatch_attempt_count"])
    absence["current_offer_guard_id"] = None
    absence["current_offer_expires_at"] = None
    touch(absence)

    assignment = domain.assignment_of_absence(absence)
    if assignment is not None:
        domain.propagate_from_assignment(assignment)
    guard = db.guards.get(absence["guard_id"])
    if guard is not None:
        domain.refresh_reliability_and_touch(guard)
    return object_response(absence)


@bp.post("/srts/absence-reports/<absence_id>/rescind")
def rescind_absence(absence_id):
    require("CrossingGuard", "CrossingSupervisor")
    body = v.body()
    rescind_reason = v.req_str(body, "rescind_reason")
    absence = domain.get_absence(absence_id)

    if absence["status"] not in RESCINDABLE:
        fail("ERR_ABSENCE_NOT_RESCINDABLE",
             "A COVERED or RESCINDED report cannot be withdrawn.")

    offer = _open_offer(absence)
    if offer is not None:
        offer["offer_status"] = "EXPIRED"
    absence["current_offer_guard_id"] = None
    absence["current_offer_expires_at"] = None
    absence["status"] = "RESCINDED"
    absence["rescind_reason"] = rescind_reason
    touch(absence)

    assignment = domain.assignment_of_absence(absence)
    if assignment is not None:
        domain.propagate_from_assignment(assignment)
    guard = db.guards.get(absence["guard_id"])
    if guard is not None:
        domain.refresh_reliability_and_touch(guard)
    return object_response(absence)
