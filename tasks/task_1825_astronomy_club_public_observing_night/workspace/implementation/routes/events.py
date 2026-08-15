"""Routes: observing events, operator assignments, group bookings, readings, reports."""
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import Blueprint, request

import domain as D
from helpers import (ApiError, actor, as_decimal, as_enum, as_int, as_str, body,
                     field, fk, list_response, parse_dt, sorted_items, success)
from store import DB
import views

events_bp = Blueprint("events", __name__)

ALL_ROLES = ("ClubOfficer", "Member", "EventCoordinator", "EquipmentChair")
READ_ROLES_EVENTS = ALL_ROLES
READ_ROLES_STAFF = ("ClubOfficer", "Member", "EventCoordinator")


def _get_or_404(table, rid):
    ent = table.get(rid)
    if ent is None:
        raise ApiError(404, "ERR_NOT_FOUND", "Resource not found: %s" % rid)
    return ent


def _within_daylight(ws, we):
    """Fixed daylight table: every UTC date's civil daylight is [06:00Z, 20:00Z)."""
    if ws.date() != we.date():
        return False
    d = ws.date()
    start = datetime(d.year, d.month, d.day, 6, 0, tzinfo=timezone.utc)
    end = datetime(d.year, d.month, d.day, 20, 0, tzinfo=timezone.utc)
    return ws >= start and we <= end


# ----- observing events -----

@events_bp.post("/club/observing-events")
def create_event():
    actor(["EventCoordinator"])
    data = body()
    title = as_str(field(data, "title"), "title")
    kind = as_enum(field(data, "event_kind"), "event_kind", D.EVENT_KINDS)
    ws = parse_dt(field(data, "window_start"), "window_start")
    we = parse_dt(field(data, "window_end"), "window_end")
    moon = as_int(field(data, "moon_illumination_pct"), "moon_illumination_pct")
    if moon < 0 or moon > 100:
        raise ApiError(400, "ERR_INVALID_REQUEST",
                       "moon_illumination_pct must be between 0 and 100")
    min_ops = as_int(field(data, "min_operators"), "min_operators")
    if min_ops < 1:
        raise ApiError(400, "ERR_INVALID_REQUEST", "min_operators must be >= 1")
    if not (ws < we):
        raise ApiError(422, "ERR_INVALID_WINDOW",
                       "window_start must be strictly before window_end")
    e = D.mint(DB)
    e.update({
        "title": title,
        "event_kind": kind,
        "window_start": ws,
        "window_end": we,
        "status": "DRAFT",
        "moon_illumination_pct": moon,
        "weather_cancellation_pct": 0,
        "min_operators": min_ops,
        "confirmed_operator_count": 0,
        "cancellation_reason": None,
    })
    DB.events[e["id"]] = e
    return success(views.event_view(DB, e), 201)


@events_bp.get("/club/observing-events/<event_id>")
def get_event(event_id):
    actor(READ_ROLES_EVENTS)
    return success(views.event_view(DB, _get_or_404(DB.events, event_id)), 200)


@events_bp.get("/club/observing-events")
def list_events():
    actor(READ_ROLES_EVENTS)
    items = sorted_items(DB.events)
    status = request.args.get("status")
    kind = request.args.get("event_kind")
    if status is not None:
        items = [e for e in items if e["status"] == status]
    if kind is not None:
        items = [e for e in items if e["event_kind"] == kind]
    return list_response(items, lambda e: views.event_view(DB, e))


@events_bp.post("/club/observing-events/<event_id>/schedule")
def schedule_event(event_id):
    actor(["EventCoordinator"])
    e = _get_or_404(DB.events, event_id)
    if e["status"] != "DRAFT":
        raise ApiError(409, "ERR_INVALID_STATE", "Only a DRAFT event may be scheduled")
    if e["event_kind"] == "PUBLIC_NIGHT" and \
            e["moon_illumination_pct"] > D.MOON_ILLUMINATION_LIMIT:
        raise ApiError(422, "ERR_MOON_TOO_BRIGHT",
                       "PUBLIC_NIGHT requires moon_illumination_pct <= 40")
    if e["event_kind"] == "SOLAR_SESSION" and \
            not _within_daylight(e["window_start"], e["window_end"]):
        raise ApiError(422, "ERR_NOT_DAYLIGHT_WINDOW",
                       "SOLAR_SESSION window must lie within 06:00Z-20:00Z of one UTC date")
    e["status"] = "SCHEDULED"
    D.stamp(DB, e)
    return success(views.event_view(DB, e), 200)


@events_bp.post("/club/observing-events/<event_id>/unschedule")
def unschedule_event(event_id):
    actor(["EventCoordinator"])
    e = _get_or_404(DB.events, event_id)
    if e["status"] != "SCHEDULED":
        raise ApiError(409, "ERR_INVALID_STATE",
                       "Only a SCHEDULED event may be unscheduled")
    e["status"] = "DRAFT"
    D.stamp(DB, e)
    return success(views.event_view(DB, e), 200)


@events_bp.post("/club/observing-events/<event_id>/weather-check")
def weather_check(event_id):
    actor(["EventCoordinator"])
    e = _get_or_404(DB.events, event_id)
    data = body()
    pct = as_int(field(data, "weather_cancellation_pct"), "weather_cancellation_pct")
    if pct < 0 or pct > 100:
        raise ApiError(400, "ERR_INVALID_REQUEST",
                       "weather_cancellation_pct must be between 0 and 100")
    e["weather_cancellation_pct"] = pct
    D.stamp(DB, e)
    if pct >= D.WEATHER_CANCEL_THRESHOLD and e["status"] == "CONFIRMED":
        D.event_cancel_cascade(DB, e, "WEATHER")
    return success(views.event_view(DB, e), 200)


@events_bp.post("/club/observing-events/<event_id>/confirm")
def confirm_event(event_id):
    actor(["EventCoordinator"])
    e = _get_or_404(DB.events, event_id)
    data = body()
    expected = as_int(field(data, "expected_event_version"), "expected_event_version")
    if e["status"] != "SCHEDULED":
        raise ApiError(409, "ERR_INVALID_STATE", "Only a SCHEDULED event may be confirmed")
    if expected != e["version"]:
        raise ApiError(412, "ERR_STALE_VERSION",
                       "expected_event_version does not match the event's version")
    # Business gates in PRD order: coverage -> weather -> solar safety.
    e["confirmed_operator_count"] = sum(
        1 for a in DB.assignments.values()
        if a["event_id"] == e["id"] and a["status"] == "CONFIRMED")
    if e["confirmed_operator_count"] < e["min_operators"]:
        raise ApiError(422, "ERR_INSUFFICIENT_OPERATORS",
                       "confirmed_operator_count is below min_operators")
    if e["weather_cancellation_pct"] >= D.WEATHER_CANCEL_THRESHOLD:
        raise ApiError(422, "ERR_WEATHER_RISK",
                       "Latest weather_cancellation_pct is at or above 70")
    if e["event_kind"] == "SOLAR_SESSION":
        ok = any(a["status"] == "CONFIRMED" and
                 D.has_active_cert(DB, a["member_id"], "SOLAR_SCOPE")
                 for a in DB.assignments.values() if a["event_id"] == e["id"])
        if not ok:
            raise ApiError(422, "ERR_NO_SOLAR_CERTIFIED_OPERATOR",
                           "No CONFIRMED operator holds an ACTIVE SOLAR_SCOPE certification")
    e["status"] = "CONFIRMED"
    D.stamp(DB, e)
    return success(views.event_view(DB, e), 200)


@events_bp.post("/club/observing-events/<event_id>/cancel")
def cancel_event(event_id):
    actor(["EventCoordinator"])
    e = _get_or_404(DB.events, event_id)
    data = body()
    reason = as_enum(field(data, "cancellation_reason"), "cancellation_reason",
                     D.CANCEL_REASONS)
    if e["status"] not in ("SCHEDULED", "CONFIRMED"):
        raise ApiError(409, "ERR_INVALID_STATE",
                       "Only a SCHEDULED or CONFIRMED event may be cancelled")
    D.event_cancel_cascade(DB, e, reason)
    return success(views.event_view(DB, e), 200)


@events_bp.post("/club/observing-events/<event_id>/complete")
def complete_event(event_id):
    actor(["EventCoordinator"])
    e = _get_or_404(DB.events, event_id)
    if e["status"] != "CONFIRMED":
        raise ApiError(409, "ERR_INVALID_STATE", "Only a CONFIRMED event may be completed")
    if DB.clock < e["window_end"]:
        raise ApiError(409, "ERR_INVALID_STATE",
                       "Event window has not closed yet")
    e["status"] = "COMPLETED"
    D.stamp(DB, e)
    for b in DB.bookings.values():
        if b["event_id"] == e["id"] and b["status"] == "CONFIRMED":
            b["status"] = "COMPLETED"
            D.stamp(DB, b)
    return success(views.event_view(DB, e), 200)


# ----- event operator assignments -----

@events_bp.post("/club/event-operator-assignments")
def create_assignment():
    actor(["EventCoordinator"])
    data = body()
    ev = fk(data, "event_id", DB.events)
    member = fk(data, "member_id", DB.members)
    tele = fk(data, "telescope_id", DB.telescopes)
    as_str(field(data, "event_id"), "event_id")
    as_str(field(data, "member_id"), "member_id")
    as_str(field(data, "telescope_id"), "telescope_id")
    a = D.mint(DB)
    a.update({
        "event_id": ev["id"],
        "member_id": member["id"],
        "telescope_id": tele["id"],
        "status": "INVITED",
        "invited_at": DB.clock,
    })
    DB.assignments[a["id"]] = a
    return success(views.assignment_view(DB, a), 201)


@events_bp.get("/club/event-operator-assignments/<assignment_id>")
def get_assignment(assignment_id):
    actor(READ_ROLES_STAFF)
    return success(views.assignment_view(DB, _get_or_404(DB.assignments, assignment_id)), 200)


@events_bp.get("/club/event-operator-assignments")
def list_assignments():
    actor(READ_ROLES_STAFF)
    items = sorted_items(DB.assignments)
    event_id = request.args.get("event_id")
    member_id = request.args.get("member_id")
    telescope_id = request.args.get("telescope_id")
    status = request.args.get("status")
    if event_id is not None:
        items = [a for a in items if a["event_id"] == event_id]
    if member_id is not None:
        items = [a for a in items if a["member_id"] == member_id]
    if telescope_id is not None:
        items = [a for a in items if a["telescope_id"] == telescope_id]
    if status is not None:
        items = [a for a in items if a["status"] == status]
    return list_response(items, lambda a: views.assignment_view(DB, a))


def _owned_assignment(assignment_id):
    uid, _ = actor(["Member"])
    a = _get_or_404(DB.assignments, assignment_id)
    if a["member_id"] != uid:
        raise ApiError(403, "ERR_FORBIDDEN",
                       "Only the invited Member may respond to this assignment")
    return a


@events_bp.post("/club/event-operator-assignments/<assignment_id>/accept")
def accept_assignment(assignment_id):
    a = _owned_assignment(assignment_id)
    if a["status"] != "INVITED":
        raise ApiError(409, "ERR_INVALID_STATE", "Only an INVITED assignment may be accepted")
    member = DB.members[a["member_id"]]
    # PRD 3.7 order: standing -> certification -> overlap.
    if member["status"] != "ACTIVE":
        raise ApiError(422, "ERR_MEMBER_NOT_IN_GOOD_STANDING", "Member is not ACTIVE")
    tele = DB.telescopes[a["telescope_id"]]
    if not D.has_active_cert(DB, member["id"], tele["equipment_class"]):
        raise ApiError(422, "ERR_CERTIFICATION_REQUIRED",
                       "Member lacks an ACTIVE certification for the telescope's class")
    host = DB.events[a["event_id"]]
    for other in DB.assignments.values():
        if other["id"] == a["id"] or other["member_id"] != member["id"]:
            continue
        if other["status"] != "CONFIRMED":
            continue
        oe = DB.events[other["event_id"]]
        # Closed-interval semantics: a touch at window_end == window_start counts.
        if oe["window_start"] <= host["window_end"] and \
                host["window_start"] <= oe["window_end"]:
            raise ApiError(409, "ERR_OPERATOR_OVERLAP",
                           "Member already holds a CONFIRMED assignment at an overlapping window")
    a["status"] = "CONFIRMED"
    D.stamp(DB, a)
    D.recompute_coverage(DB, host)
    return success(views.assignment_view(DB, a), 200)


@events_bp.post("/club/event-operator-assignments/<assignment_id>/decline")
def decline_assignment(assignment_id):
    a = _owned_assignment(assignment_id)
    if a["status"] != "INVITED":
        raise ApiError(409, "ERR_INVALID_STATE", "Only an INVITED assignment may be declined")
    a["status"] = "DECLINED"
    D.stamp(DB, a)
    return success(views.assignment_view(DB, a), 200)


@events_bp.post("/club/event-operator-assignments/<assignment_id>/withdraw")
def withdraw_assignment(assignment_id):
    a = _owned_assignment(assignment_id)
    if a["status"] != "CONFIRMED":
        raise ApiError(409, "ERR_INVALID_STATE",
                       "Only a CONFIRMED assignment may be withdrawn")
    a["status"] = "WITHDRAWN"
    D.stamp(DB, a)
    D.recompute_coverage(DB, DB.events[a["event_id"]])
    return success(views.assignment_view(DB, a), 200)


@events_bp.post("/club/event-operator-assignments/<assignment_id>/mark-no-show")
def mark_assignment_no_show(assignment_id):
    actor(["EventCoordinator"])
    a = _get_or_404(DB.assignments, assignment_id)
    if a["status"] != "CONFIRMED":
        raise ApiError(409, "ERR_INVALID_STATE",
                       "Only a CONFIRMED assignment may be marked NO_SHOW")
    host = DB.events[a["event_id"]]
    if host["status"] != "COMPLETED":
        raise ApiError(409, "ERR_INVALID_STATE", "Host event is not COMPLETED")
    a["status"] = "NO_SHOW"
    D.stamp(DB, a)
    DB.no_show_marks.append({
        "member_id": a["member_id"],
        "marked_at": DB.clock,
        "entity_created_at": a["created_at"],
        "seq": DB.next_seq(),
    })
    member = DB.members[a["member_id"]]
    member["no_show_strikes"] = D.compute_strikes(DB, member["id"])
    D.stamp(DB, member)
    D.recompute_coverage(DB, host)
    return success(views.assignment_view(DB, a), 200)


# ----- group visit bookings -----

@events_bp.post("/club/group-visit-bookings")
def create_booking():
    uid, _ = actor(["Member"])
    data = body()
    ev = fk(data, "event_id", DB.events)
    contact = fk(data, "contact_member_id", DB.members)
    if isinstance(data.get("contact_member_id"), str) and data["contact_member_id"] != uid:
        raise ApiError(403, "ERR_FORBIDDEN",
                       "A Member may only book visits with itself as contact")
    as_str(field(data, "event_id"), "event_id")
    group_name = as_str(field(data, "group_name"), "group_name")
    party_size = as_int(field(data, "party_size"), "party_size")
    if party_size < 1:
        raise ApiError(400, "ERR_INVALID_REQUEST", "party_size must be >= 1")
    as_str(field(data, "contact_member_id"), "contact_member_id")
    if ev["event_kind"] != "PUBLIC_NIGHT":
        raise ApiError(400, "ERR_INVALID_REQUEST",
                       "Group visits attach only to PUBLIC_NIGHT events")
    if contact["status"] != "ACTIVE":
        raise ApiError(422, "ERR_MEMBER_NOT_IN_GOOD_STANDING",
                       "Contact member is not ACTIVE")
    if D.compute_strikes(DB, contact["id"]) >= D.STRIKE_THROTTLE_LIMIT:
        raise ApiError(422, "ERR_NO_SHOW_THROTTLED",
                       "Contact member has too many no-show strikes")
    b = D.mint(DB)
    b.update({
        "event_id": ev["id"],
        "group_name": group_name,
        "party_size": party_size,
        "contact_member_id": contact["id"],
        "deposit_cents": D.deposit_for_party(party_size),
        "status": "PENDING",
        "_deposit_refund_note": None,
    })
    DB.bookings[b["id"]] = b
    return success(views.booking_view(DB, b), 201)


@events_bp.get("/club/group-visit-bookings/<booking_id>")
def get_booking(booking_id):
    actor(READ_ROLES_STAFF)
    return success(views.booking_view(DB, _get_or_404(DB.bookings, booking_id)), 200)


@events_bp.get("/club/group-visit-bookings")
def list_bookings():
    actor(READ_ROLES_STAFF)
    items = sorted_items(DB.bookings)
    event_id = request.args.get("event_id")
    contact_id = request.args.get("contact_member_id")
    status = request.args.get("status")
    if event_id is not None:
        items = [b for b in items if b["event_id"] == event_id]
    if contact_id is not None:
        items = [b for b in items if b["contact_member_id"] == contact_id]
    if status is not None:
        items = [b for b in items if b["status"] == status]
    return list_response(items, lambda b: views.booking_view(DB, b))


@events_bp.post("/club/group-visit-bookings/<booking_id>/confirm")
def confirm_booking(booking_id):
    actor(["EventCoordinator"])
    b = _get_or_404(DB.bookings, booking_id)
    if b["status"] != "PENDING":
        raise ApiError(409, "ERR_INVALID_STATE", "Only a PENDING booking may be confirmed")
    host = DB.events[b["event_id"]]
    if host["status"] not in ("SCHEDULED", "CONFIRMED"):
        raise ApiError(409, "ERR_INVALID_STATE",
                       "Host event is not SCHEDULED or CONFIRMED")
    confirmed_size = sum(o["party_size"] for o in DB.bookings.values()
                         if o["event_id"] == b["event_id"] and o["status"] == "CONFIRMED")
    if confirmed_size + b["party_size"] > D.GROUP_CAPACITY_PER_EVENT:
        raise ApiError(422, "ERR_EVENT_GROUP_CAPACITY",
                       "Aggregate CONFIRMED party size would exceed 60")
    b["status"] = "CONFIRMED"
    D.stamp(DB, b)
    return success(views.booking_view(DB, b), 200)


@events_bp.post("/club/group-visit-bookings/<booking_id>/cancel")
def cancel_booking(booking_id):
    uid, role = actor(["Member", "EventCoordinator"])
    b = _get_or_404(DB.bookings, booking_id)
    if role == "Member" and b["contact_member_id"] != uid:
        raise ApiError(403, "ERR_FORBIDDEN",
                       "Only the contact Member or an EventCoordinator may cancel")
    if b["status"] not in ("PENDING", "CONFIRMED"):
        raise ApiError(409, "ERR_INVALID_STATE",
                       "Only a PENDING or CONFIRMED booking may be cancelled")
    b["status"] = "CANCELLED"
    D.stamp(DB, b)
    return success(views.booking_view(DB, b), 200)


@events_bp.post("/club/group-visit-bookings/<booking_id>/mark-no-show")
def mark_booking_no_show(booking_id):
    actor(["EventCoordinator"])
    b = _get_or_404(DB.bookings, booking_id)
    if b["status"] != "CONFIRMED":
        raise ApiError(409, "ERR_INVALID_STATE",
                       "Only a CONFIRMED booking may be marked NO_SHOW")
    host = DB.events[b["event_id"]]
    if host["status"] != "COMPLETED":
        raise ApiError(409, "ERR_INVALID_STATE", "Host event is not COMPLETED")
    b["status"] = "NO_SHOW"
    D.stamp(DB, b)
    DB.no_show_marks.append({
        "member_id": b["contact_member_id"],
        "marked_at": DB.clock,
        "entity_created_at": b["created_at"],
        "seq": DB.next_seq(),
    })
    member = DB.members[b["contact_member_id"]]
    member["no_show_strikes"] = D.compute_strikes(DB, member["id"])
    D.stamp(DB, member)
    return success(views.booking_view(DB, b), 200)


# ----- sky quality readings -----

@events_bp.post("/club/sky-quality-readings")
def create_reading():
    uid, _ = actor(["Member"])
    data = body()
    taker = fk(data, "taken_by_member_id", DB.members)
    ev = fk(data, "event_id", DB.events)
    if isinstance(data.get("taken_by_member_id"), str) and \
            data["taken_by_member_id"] != uid:
        raise ApiError(403, "ERR_FORBIDDEN",
                       "A Member may only record readings it took")
    as_str(field(data, "taken_by_member_id"), "taken_by_member_id")
    as_str(field(data, "event_id"), "event_id")
    sqm = as_decimal(field(data, "sqm_value"), "sqm_value")
    if sqm < Decimal("10.00") or sqm > Decimal("22.99"):
        raise ApiError(400, "ERR_INVALID_REQUEST",
                       "sqm_value must be between 10.00 and 22.99")
    sqm = sqm.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    r = {
        "id": D.new_id(),
        "created_at": DB.clock,
        "_seq": DB.next_seq(),
        "taken_by_member_id": taker["id"],
        "event_id": ev["id"],
        "sqm_value": sqm,
        "taken_at": DB.clock,
    }
    DB.readings[r["id"]] = r
    # Provisional recompute of every OPEN report whose window covers taken_at.
    for rep in DB.reports.values():
        if rep["status"] == "OPEN" and rep["period_start"] <= r["taken_at"] < rep["period_end"]:
            D.report_recompute(DB, rep)
            D.stamp(DB, rep)
    return success(views.reading_view(DB, r), 201)


@events_bp.get("/club/sky-quality-readings/<reading_id>")
def get_reading(reading_id):
    actor(READ_ROLES_STAFF)
    return success(views.reading_view(DB, _get_or_404(DB.readings, reading_id)), 200)


@events_bp.get("/club/sky-quality-readings")
def list_readings():
    actor(READ_ROLES_STAFF)
    items = sorted_items(DB.readings)
    event_id = request.args.get("event_id")
    taker = request.args.get("taken_by_member_id")
    if event_id is not None:
        items = [r for r in items if r["event_id"] == event_id]
    if taker is not None:
        items = [r for r in items if r["taken_by_member_id"] == taker]
    return list_response(items, lambda r: views.reading_view(DB, r))


# ----- dark sky reports -----

@events_bp.post("/club/dark-sky-reports")
def create_report():
    actor(["ClubOfficer"])
    data = body()
    ps = parse_dt(field(data, "period_start"), "period_start")
    pe = parse_dt(field(data, "period_end"), "period_end")
    if not (ps < pe):
        raise ApiError(422, "ERR_INVALID_WINDOW",
                       "period_start must be strictly before period_end")
    rep = D.mint(DB)
    rep.update({
        "period_start": ps,
        "period_end": pe,
        "status": "OPEN",
        "reading_count": 0,
        "median_sqm": None,
        "advocacy_grade": None,
    })
    DB.reports[rep["id"]] = rep
    D.report_recompute(DB, rep)  # provisional sweep at open
    return success(views.report_view(DB, rep), 201)


@events_bp.get("/club/dark-sky-reports/<report_id>")
def get_report(report_id):
    actor(READ_ROLES_STAFF)
    return success(views.report_view(DB, _get_or_404(DB.reports, report_id)), 200)


@events_bp.get("/club/dark-sky-reports")
def list_reports():
    actor(READ_ROLES_STAFF)
    items = sorted_items(DB.reports)
    status = request.args.get("status")
    if status is not None:
        items = [r for r in items if r["status"] == status]
    return list_response(items, lambda r: views.report_view(DB, r))


@events_bp.post("/club/dark-sky-reports/<report_id>/finalize")
def finalize_report(report_id):
    actor(["ClubOfficer"])
    rep = _get_or_404(DB.reports, report_id)
    if rep["status"] != "OPEN":
        raise ApiError(409, "ERR_INVALID_STATE", "Only an OPEN report may be finalized")
    if rep["reading_count"] < D.MIN_READINGS_PER_REPORT:
        raise ApiError(422, "ERR_INSUFFICIENT_READINGS",
                       "Report has fewer than 3 swept readings")
    # Final variant: freeze median and grade at finalize-time values.
    D.report_recompute(DB, rep)
    rep["status"] = "FINALIZED"
    D.stamp(DB, rep)
    return success(views.report_view(DB, rep), 200)
