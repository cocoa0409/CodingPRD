"""Booking through delivery: the session lifecycle (PRD §3.6)."""

from flask import Blueprint, request

from core import numbers as N
from core import timeutil as T
from core.constants import (
    ACTIVITY_TYPES,
    BASE_RATE_CENTS_PER_MINUTE,
    CANCELLATION_REASON_INPUT_MEMBERS,
    CREW_RELEASE_REASON_CASCADE,
    HORSE_MAX_MOUNTED_MINUTES_PER_DAY,
    HORSE_MAX_MOUNTED_MINUTES_PER_WEEK,
    HORSE_MAX_SESSIONS_PER_DAY,
    LATE_CANCELLATION_FEE_PCT,
    LATE_CANCELLATION_WINDOW_HOURS,
    NO_SHOW_FEE_PCT,
    SESSION_MAX_DURATION_MINUTES,
    SESSION_MIN_DURATION_MINUTES,
)
from core.envelope import list_response, object_response
from core.errors import fail
from core.ladder import (
    Field, caller_id, caller_role, endpoint, pagination, paginate, query_enum,
    validate_body,
)
from core.lookups import horse_or_404, resource_or_404, rider_or_404, session_or_404
from core.store import all_rows, clock, db, new_row, touch
from domain import booking, derive, funding, gates, policy, serialize, workload

bp = Blueprint("sessions", __name__)

SCHEDULE_STATUSES = ["CREW_PENDING", "CONFIRMED", "COMPLETED", "CANCELLED", "NO_SHOW"]
BILLING_STATUSES = ["UNBILLED", "CHARGED", "FUNDED", "REVERSED"]
ELIGIBILITY_VARIANTS = ["current_declared", "at_assessment",
                        "at_booking_instant", "at_ride_instant"]


@bp.post("/sessions")
@endpoint(["Instructor", "ProgramAdmin"])
def create_session():
    payload = validate_body([
        Field("rider_id", "string", required=True),
        Field("horse_id", "string", required=True),
        Field("instructor_id", "string", required=True),
        Field("activity_type", "enum", required=True, members=ACTIVITY_TYPES),
        Field("scheduled_start", "instant", required=True),
        Field("duration_minutes", "int", required=True,
              minimum=SESSION_MIN_DURATION_MINUTES,
              maximum=SESSION_MAX_DURATION_MINUTES),
        Field("supervising_instructor_id", "string"),
    ])

    # rung 13 - body foreign keys, in the declared field order.
    rider = rider_or_404(payload["rider_id"])
    horse = horse_or_404(payload["horse_id"])
    instructor = resource_or_404("instructors", payload["instructor_id"])
    supervisor = None
    if payload.get("supervising_instructor_id"):
        supervisor = resource_or_404("instructors",
                                     payload["supervising_instructor_id"])

    start = T.echoed(payload["scheduled_start"])
    end = T.derived(T.plus_minutes(start.dt, payload["duration_minutes"]))
    session_date = T.day_of(start.dt)
    instructors = [instructor] + ([supervisor] if supervisor else [])

    gates.gate_incident_hold(rider=rider, horse=horse, instructors=instructors)  # 14
    gates.gate_finalized_period_for_session(session_date)                        # 15
    gates.gate_horse_hold(horse)                                                 # 16
    gates.gate_instructor_certification(instructors, ("CURRENT",))               # 17
    gates.gate_medical_release(rider)                                            # 18

    booking.rider_state_checks(rider, payload["activity_type"])                  # 20-24
    booking.supervision_pairing(instructor, supervisor)                          # 25
    effective = supervisor if supervisor is not None else instructor
    booking.instructor_tier_check(rider, payload["activity_type"], effective)    # 26
    booking.load_check(rider, horse)                                             # 27

    if workload.horse_overlap(horse["id"], start.dt, end.dt) is not None:        # 28
        fail("ERR_HORSE_SCHEDULE_CONFLICT", "The horse is already booked then.")
    if workload.horse_rest_violation(horse["id"], start.dt, end.dt) is not None:  # 29
        fail("ERR_HORSE_REST_INTERVAL", "The horse needs a longer rest interval.")
    _capacity_checks(horse, session_date, payload["duration_minutes"])           # 30-31
    named = [instructor["id"]] + ([supervisor["id"]] if supervisor else [])
    if workload.instructor_overlap(named, start.dt, end.dt) is not None:         # 32
        fail("ERR_INSTRUCTOR_SCHEDULE_CONFLICT",
             "The instructor is already teaching then.")

    row = new_row("sessions")
    row.update({
        "rider_id": rider["id"],
        "horse_id": horse["id"],
        "instructor_id": instructor["id"],
        "supervising_instructor_id": supervisor["id"] if supervisor else None,
        "activity_type": payload["activity_type"],
        "scheduled_start": start,
        "duration_minutes": payload["duration_minutes"],
        "scheduled_end": end,
        "mounted_minutes": None,
        "schedule_status": "CREW_PENDING",
        "billing_status": "UNBILLED",
        "cancellation_reason": None,
    })
    return object_response(serialize.session(row), 201)


def _capacity_checks(horse, session_date, duration_minutes):
    day = workload.day_window(session_date)
    week = workload.week_window(session_date)
    count_after = workload.session_count_in_window(horse["id"], day, "committed") + 1
    day_after = workload.minutes_in_window(horse["id"], day, "committed") + duration_minutes
    week_after = workload.minutes_in_window(horse["id"], week, "committed") + duration_minutes
    if count_after > HORSE_MAX_SESSIONS_PER_DAY \
            or day_after > HORSE_MAX_MOUNTED_MINUTES_PER_DAY:
        fail("ERR_HORSE_DAILY_LIMIT_EXCEEDED", "The horse's daily ceiling is exceeded.")
    if week_after > HORSE_MAX_MOUNTED_MINUTES_PER_WEEK:
        fail("ERR_HORSE_WEEKLY_MINUTES_EXCEEDED",
             "The horse's weekly minute ceiling is exceeded.")


@bp.get("/sessions/<session_id>")
@endpoint(["Instructor", "ProgramAdmin", "VolunteerCoordinator", "BillingClerk",
           "IntakeCoordinator"])
def read_session(session_id):
    return object_response(serialize.session(session_or_404(session_id)))


@bp.get("/sessions")
@endpoint(["Instructor", "ProgramAdmin", "VolunteerCoordinator", "BillingClerk"])
def list_sessions():
    limit, offset = pagination()
    schedule_status = query_enum("schedule_status", SCHEDULE_STATUSES)
    billing_status = query_enum("billing_status", BILLING_STATUSES)
    rider_id = request.args.get("rider_id")
    horse_id = request.args.get("horse_id")
    instructor_id = request.args.get("instructor_id")
    supervising_id = request.args.get("supervising_instructor_id")
    raw_date = request.args.get("on_date")
    on_date = None
    if raw_date is not None:
        on_date = T.parse_date(raw_date)
        if on_date is None:
            fail("ERR_VALIDATION", "on_date must be a YYYY-MM-DD date.")

    rows = all_rows("sessions")
    if rider_id is not None:
        rows = [r for r in rows if r["rider_id"] == rider_id]
    if horse_id is not None:
        rows = [r for r in rows if r["horse_id"] == horse_id]
    if instructor_id is not None:
        rows = [r for r in rows if r["instructor_id"] == instructor_id]
    if supervising_id is not None:
        rows = [r for r in rows if r.get("supervising_instructor_id") == supervising_id]
    if schedule_status is not None:
        rows = [r for r in rows if r["schedule_status"] == schedule_status]
    if billing_status is not None:
        rows = [r for r in rows if r["billing_status"] == billing_status]
    if on_date is not None:
        rows = [r for r in rows if T.day_of(r["scheduled_start"].dt) == on_date]
    page = paginate(rows, limit, offset)
    return list_response([serialize.session(r) for r in page],
                         limit, offset, len(rows))


@bp.get("/sessions/<session_id>/eligibility")
@endpoint(["Instructor", "ProgramAdmin"])
def session_eligibility(session_id):
    variant = request.args.get("variant")
    if variant is None:
        variant = "current_declared"
    elif variant not in ELIGIBILITY_VARIANTS:
        fail("ERR_VALIDATION", "Unsupported variant %r." % variant)
    session = session_or_404(session_id)
    rider = db["riders"].get(session["rider_id"])
    horse = db["horses"].get(session["horse_id"])

    weight_variant = "at_assessment" if variant == "at_assessment" else "current_declared"
    instant = session["scheduled_start"].dt if variant == "at_ride_instant" \
        else clock.now()

    effective = policy.effective_instructor(session)
    release = derive.latest_release(rider["id"])
    result = policy.evaluate_precaution(rider, session["activity_type"])
    blocking = booking.eligibility_walk(session, weight_variant, instant)
    return object_response({
        "session_id": session["id"],
        "variant": variant,
        "admissible": blocking is None,
        # Adjudication of friction 3 (§3.6): blocking_gate carries the ERROR
        # IDENTIFIER of the first check that would refuse the write.  The rival
        # reading ("the name of the gate itself") has no declared vocabulary for
        # the non-gate rungs this read also reports on (rider not active, crew
        # incomplete, tier insufficient), so the error-id reading is the one that
        # keeps every declared refusal reason observable through this field.
        "blocking_gate": blocking,
        "precaution_tier": result.tier,
        "required_instructor_tier": policy.required_instructor_tier(
            rider, session["activity_type"]),
        "instructor_certification_status": derive.certification_status(
            effective, instant) if effective else None,
        "release_status": derive.release_status(release, instant) if release else None,
        "effective_load_lb": policy.effective_load_lb(rider, horse, weight_variant),
        "horse_max_load_lb": horse["max_load_lb"],
        "crew_satisfied": derive.crew_satisfied(session),
        "required_sidewalker_count": rider["required_sidewalker_count"],
        "requires_leader": rider["requires_leader"],
        "sidewalker_hold_type": rider["sidewalker_hold_type"],
        "quoted_fee_cents": (session["duration_minutes"]
                             * BASE_RATE_CENTS_PER_MINUTE[session["activity_type"]]),
    })


@bp.post("/sessions/<session_id>/confirm")
@endpoint(["Instructor", "ProgramAdmin"])
def confirm_session(session_id):
    session = session_or_404(session_id)
    rider = db["riders"].get(session["rider_id"])
    horse = db["horses"].get(session["horse_id"])
    instructors = policy.session_instructors(session)

    gates.gate_incident_hold(rider=rider, horse=horse, instructors=instructors)  # 14
    gates.gate_horse_hold(horse)                                                 # 16
    gates.gate_instructor_certification(instructors, ("CURRENT",))               # 17
    gates.gate_medical_release(rider)                                            # 18
    if session["schedule_status"] != "CREW_PENDING":                             # 19
        fail("ERR_INVALID_STATE", "Only a CREW_PENDING session may be confirmed.")
    booking.rider_state_checks(rider, session["activity_type"])                  # 20-24
    booking.instructor_tier_check(rider, session["activity_type"],               # 26
                                  policy.effective_instructor(session))
    if not derive.crew_satisfied(session):                                       # 40
        fail("ERR_CREW_INCOMPLETE", "The crew requirement is not satisfied.")

    session["schedule_status"] = "CONFIRMED"
    touch(session)
    return object_response(serialize.session(session))


@bp.post("/sessions/<session_id>/complete")
@endpoint(["Instructor", "ProgramAdmin"])
def complete_session(session_id):
    existing = db["sessions"].get(session_id)
    if existing is not None and caller_role() == "Instructor" \
            and caller_id() != existing["instructor_id"]:
        fail("ERR_UNAUTHORIZED",                                                 # rung 4
             "Only the session's own instructor may complete it.")
    payload = validate_body([
        Field("mounted_minutes", "int", required=True, minimum=0),
        Field("preferred_grant_id", "string"),
    ])
    session = session_or_404(session_id)
    if payload["mounted_minutes"] > session["duration_minutes"]:                 # rung 7
        fail("ERR_VALIDATION", "mounted_minutes exceeds the booked duration.")

    rider = db["riders"].get(session["rider_id"])
    horse = db["horses"].get(session["horse_id"])
    instructors = policy.session_instructors(session)
    preferred_grant = None
    if payload.get("preferred_grant_id"):
        preferred_grant = resource_or_404("grants", payload["preferred_grant_id"])  # 13

    session_date = T.day_of(session["scheduled_start"].dt)
    gates.gate_incident_hold(rider=rider, horse=horse, instructors=instructors)  # 14
    gates.gate_finalized_period_for_session(session_date)                        # 15
    gates.gate_horse_hold(horse)                                                 # 16
    gates.gate_instructor_certification(instructors, ("CURRENT", "GRACE"))       # 17
    gates.gate_medical_release(rider)                                            # 18
    if session["schedule_status"] != "CONFIRMED":                                # 19
        fail("ERR_INVALID_STATE", "Only a CONFIRMED session may be completed.")

    if preferred_grant is not None:                                              # 41
        # Adjudication of friction 5 (§3.8): a PASSING preferred_grant_id is a
        # caller assertion that is validated and then DISCARDED - the step-1
        # candidate ranking (period_end ASC, remaining ASC, created_at ASC) is
        # left untouched.  Promoting the named grant would make that declared
        # ranking false in one branch; discarding keeps the declared ordering
        # true in every branch, so more declared behaviour stays reachable.
        if not funding.grant_is_eligible(preferred_grant, rider, session_date):
            fail("ERR_GRANT_RESTRICTION_VIOLATION",
                 "The preferred grant fails the eligibility filter.")

    gross = (payload["mounted_minutes"]
             * BASE_RATE_CENTS_PER_MINUTE[session["activity_type"]])
    session["mounted_minutes"] = payload["mounted_minutes"]
    session["schedule_status"] = "COMPLETED"
    try:
        funding.create_charge(session, rider, "SESSION_FEE", gross, session_date)  # 42
    except Exception:
        session["mounted_minutes"] = None
        session["schedule_status"] = "CONFIRMED"
        raise
    touch(session)
    return object_response(serialize.session(session))


@bp.post("/sessions/<session_id>/cancel")
@endpoint(["Instructor", "ProgramAdmin", "IntakeCoordinator"])
def cancel_session(session_id):
    payload = validate_body([
        Field("cancellation_reason", "enum", required=True,
              members=CANCELLATION_REASON_INPUT_MEMBERS),
    ])
    session = session_or_404(session_id)
    if session["schedule_status"] not in ("CREW_PENDING", "CONFIRMED"):          # 19
        fail("ERR_INVALID_STATE", "Only a live session may be cancelled.")

    supplied = payload["cancellation_reason"]
    if supplied == "RIDER_REQUEST":
        hours_notice = ((session["scheduled_start"].dt - clock.now()).total_seconds()
                        / 3600.0)
        derived_reason = ("EARLY_RIDER" if hours_notice >= LATE_CANCELLATION_WINDOW_HOURS
                          else "LATE_RIDER")
    else:
        derived_reason = supplied

    session["schedule_status"] = "CANCELLED"
    session["cancellation_reason"] = derived_reason
    release_crew(session)
    if derived_reason == "LATE_RIDER":
        rider = db["riders"].get(session["rider_id"])
        quoted = (session["duration_minutes"]
                  * BASE_RATE_CENTS_PER_MINUTE[session["activity_type"]])
        gross = N.cents(N.dec(quoted) * N.dec(LATE_CANCELLATION_FEE_PCT))
        funding.create_charge(session, rider, "LATE_CANCELLATION_FEE", gross,
                              T.day_of(session["scheduled_start"].dt))
    touch(session)
    return object_response(serialize.session(session))


@bp.post("/sessions/<session_id>/no-show")
@endpoint(["Instructor", "ProgramAdmin"])
def no_show_session(session_id):
    session = session_or_404(session_id)
    if session["schedule_status"] != "CONFIRMED" \
            or clock.now() < session["scheduled_start"].dt:                      # 19
        fail("ERR_INVALID_STATE",
             "A no-show requires a CONFIRMED session at or after scheduled_start.")
    session["schedule_status"] = "NO_SHOW"
    session["cancellation_reason"] = "NO_SHOW"
    release_crew(session)
    rider = db["riders"].get(session["rider_id"])
    quoted = (session["duration_minutes"]
              * BASE_RATE_CENTS_PER_MINUTE[session["activity_type"]])
    gross = N.cents(N.dec(quoted) * N.dec(NO_SHOW_FEE_PCT))
    funding.create_charge(session, rider, "NO_SHOW_FEE", gross,
                          T.day_of(session["scheduled_start"].dt))
    touch(session)
    return object_response(serialize.session(session))


def release_crew(session):
    for assignment in derive.session_assignments(session["id"]):
        if assignment["status"] != "ASSIGNED":
            continue
        assignment["status"] = "RELEASED"
        assignment["release_reason"] = CREW_RELEASE_REASON_CASCADE
        touch(assignment)
