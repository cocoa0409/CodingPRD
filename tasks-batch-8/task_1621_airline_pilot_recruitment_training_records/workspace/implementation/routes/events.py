"""Training events and checkrides: scheduling rule stack, billing, phase
advancement, segregation of duties, and the checkride outcome cascades."""

from flask import Blueprint, request

from db import store
from errors import ApiError
from middleware import require_roles
from services import (
    CHECKRIDE_FEE_CENTS, INSTRUCTOR_BUFFER, MILESTONE_PASS_SCORE, PHASE_NEXT,
    PHASE_ORDER, TIER_BY_PHASE, bump, enrollment_equipment, event_rate_card_cents,
    find_qualification, get_checkride, get_enrollment, get_event, get_instructor,
    get_slot, has_valid_first_medical, insert_ledger, new_id, recompute_class,
    ser_checkride, ser_training_event, stamp_new, touch,
)
from util import (
    get_body, is_int, pagination_params, req_str, req_ts, sort_rows,
    success_list, success_object,
)

bp = Blueprint("events", __name__)

EVENT_READ_ROLES = ("Recruiter", "CrewScheduler", "TrainingCoordinator", "CheckAirman", "SystemAdmin")
EVENT_PHASES = ("GROUND_SCHOOL", "SIMULATOR", "CHECKRIDE", "IOE")
EVENT_TYPES = ("SESSION", "MILESTONE")
RIDE_TYPES = ("ORAL", "PRACTICAL", "LINE_CHECK")


# ---- Training events ------------------------------------------------------------

@bp.post("/training-events")
def create_event():
    require_roles("TrainingCoordinator", "SystemAdmin")
    body = get_body()
    enrollment_id = req_str(body, "enrollment_id")
    instructor_id = req_str(body, "instructor_id")
    simulator_slot_id = body.get("simulator_slot_id")
    if simulator_slot_id is not None and not isinstance(simulator_slot_id, str):
        raise ApiError("ERR_INVALID_REQUEST", "simulator_slot_id must be a string")
    phase = body.get("phase")
    event_type = body.get("event_type")
    scheduled_start = req_ts(body, "scheduled_start")
    scheduled_end = req_ts(body, "scheduled_end")

    # (3) existence, in §2.8 reference order.
    enrollment = get_enrollment(enrollment_id)
    instructor = get_instructor(instructor_id)
    slot = get_slot(simulator_slot_id) if simulator_slot_id is not None else None

    # (4) state: the referenced slot must be AVAILABLE.
    if slot is not None and slot["status"] != "AVAILABLE":
        raise ApiError("ERR_SLOT_NOT_AVAILABLE", "Simulator slot is not AVAILABLE")

    # (6)+(7) medical and currency gates, IOE phase only, in that order.
    if phase == "IOE":
        equipment = enrollment_equipment(enrollment)
        qual = find_qualification(enrollment["applicant_id"], equipment["id"]) if equipment else None
        if qual is not None:
            if qual["operating_state"] == "GROUNDED":
                raise ApiError("ERR_MEDICAL_GROUNDED",
                               "Applicant qualification is GROUNDED for this equipment")
            if qual["currency_state"] in ("LAPSED", "EXPIRED"):
                raise ApiError("ERR_CURRENCY_LAPSED",
                               "Applicant qualification currency is %s" % qual["currency_state"])

    # (10) instructor tier must cover the phase.
    if phase in TIER_BY_PHASE and instructor["instructor_type"] not in TIER_BY_PHASE[phase]:
        raise ApiError("ERR_INSTRUCTOR_NOT_QUALIFIED",
                       "Instructor tier %s does not cover phase %s"
                       % (instructor["instructor_type"], phase))

    # (11) simulator containment + half-open overlap (SIMULATOR phase with slot).
    if phase == "SIMULATOR" and slot is not None:
        if not (slot["start_at"] <= scheduled_start and scheduled_end <= slot["end_at"]):
            raise ApiError("ERR_SLOT_TEMPORAL_OVERLAP",
                           "Simulator event must be fully contained in the slot window")
        for other in store.training_events.values():
            if (other["simulator_slot_id"] == slot["id"] and other["status"] == "SCHEDULED"
                    and scheduled_start < other["scheduled_end"]
                    and other["scheduled_start"] < scheduled_end):
                raise ApiError("ERR_SLOT_TEMPORAL_OVERLAP",
                               "Simulator event overlaps another SCHEDULED event in the slot")

    # (12) instructor separation buffer: >= 30 minutes end-to-start either way.
    for other in store.training_events.values():
        if other["instructor_id"] == instructor["id"] and other["status"] != "CANCELLED":
            if not (other["scheduled_end"] + INSTRUCTOR_BUFFER <= scheduled_start
                    or scheduled_end + INSTRUCTOR_BUFFER <= other["scheduled_start"]):
                raise ApiError("ERR_INSTRUCTOR_BUFFER_VIOLATION",
                               "Events of one instructor need a >= 30 minute separation")

    # (13) scheduling window against the logical clock.
    if scheduled_start < store.now():
        raise ApiError("ERR_FUTURE_ACTIVITY_DATE", "scheduled_start is in the past")

    # (14) instructor aggregate daily capacity (UTC calendar day of the start).
    same_day = sum(
        1 for other in store.training_events.values()
        if other["instructor_id"] == instructor["id"] and other["status"] != "CANCELLED"
        and other["scheduled_start"].date() == scheduled_start.date())
    if same_day >= instructor["daily_max_sessions"]:
        raise ApiError("ERR_INSTRUCTOR_DAILY_LIMIT",
                       "Instructor daily_max_sessions reached for that UTC day")

    # (16) constraint band: enums, temporal sanity, slot discipline, phase discipline.
    if phase not in EVENT_PHASES:
        raise ApiError("ERR_INVALID_REQUEST", "phase must be one of %s" % ", ".join(EVENT_PHASES))
    if event_type not in EVENT_TYPES:
        raise ApiError("ERR_INVALID_REQUEST", "event_type must be one of SESSION, MILESTONE")
    if not scheduled_end > scheduled_start:
        raise ApiError("ERR_INVALID_REQUEST", "scheduled_end must be strictly after scheduled_start")
    if phase == "SIMULATOR" and simulator_slot_id is None:
        raise ApiError("ERR_INVALID_REQUEST", "simulator_slot_id is required when phase is SIMULATOR")
    if phase != "SIMULATOR" and simulator_slot_id is not None:
        raise ApiError("ERR_INVALID_REQUEST", "simulator_slot_id is forbidden unless phase is SIMULATOR")
    if enrollment["status"] == "IN_PROGRESS":
        if phase != enrollment["current_phase"]:
            raise ApiError("ERR_PHASE_PREREQUISITE_NOT_MET",
                           "Event phase must equal the enrollment's current phase")
    elif enrollment["status"] == "REMEDIATION":
        if PHASE_ORDER[phase] > PHASE_ORDER.get(enrollment["current_phase"], len(PHASE_ORDER)):
            raise ApiError("ERR_PHASE_PREREQUISITE_NOT_MET",
                           "In remediation the event may target the current or an earlier phase")
    else:
        raise ApiError("ERR_PHASE_PREREQUISITE_NOT_MET",
                       "Events may be scheduled only for IN_PROGRESS or REMEDIATION enrollments")

    event = stamp_new({
        "enrollment_id": enrollment_id,
        "instructor_id": instructor_id,
        "simulator_slot_id": simulator_slot_id,
        "phase": phase,
        "event_type": event_type,
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
        "status": "SCHEDULED",
        "score": None,
        "billed_amount_cents": 0,
    })
    store.training_events[event["id"]] = event
    return success_object(ser_training_event(event), 201)


@bp.get("/training-events")
def list_events():
    require_roles(*EVENT_READ_ROLES)
    limit, offset = pagination_params()
    rows = list(store.training_events.values())
    enrollment_id = request.args.get("enrollment_id")
    instructor_id = request.args.get("instructor_id")
    simulator_slot_id = request.args.get("simulator_slot_id")
    status = request.args.get("status")
    if enrollment_id is not None:
        rows = [e for e in rows if e["enrollment_id"] == enrollment_id]
    if instructor_id is not None:
        rows = [e for e in rows if e["instructor_id"] == instructor_id]
    if simulator_slot_id is not None:
        rows = [e for e in rows if e["simulator_slot_id"] == simulator_slot_id]
    if status is not None:
        rows = [e for e in rows if e["status"] == status]
    rows = sort_rows(rows)
    total = len(rows)
    return success_list([ser_training_event(e) for e in rows[offset:offset + limit]], limit, offset, total)


@bp.get("/training-events/<eid>")
def read_event(eid):
    require_roles(*EVENT_READ_ROLES)
    return success_object(ser_training_event(get_event(eid)))


def _check_airman_owns_event(event, user_id, role):
    if role == "CheckAirman" and event["instructor_id"] != user_id:
        raise ApiError("ERR_FORBIDDEN_ROLE",
                       "CheckAirman may resolve only events they personally instruct")


def _event_resolvable(eid, action):
    user_id, role = require_roles("TrainingCoordinator", "CheckAirman", "SystemAdmin")
    event = get_event(eid)
    _check_airman_owns_event(event, user_id, role)
    if event["status"] != "SCHEDULED":
        raise ApiError("ERR_TRAINING_EVENT_INVALID_STATE",
                       "%s requires status SCHEDULED, found %s" % (action, event["status"]))
    if store.now() < event["scheduled_start"]:
        raise ApiError("ERR_TRAINING_EVENT_INVALID_STATE",
                       "%s is not allowed before scheduled_start" % action)
    return event


def _bill_event(event):
    enrollment = store.enrollments.get(event["enrollment_id"])
    event["billed_amount_cents"] = event_rate_card_cents(event)
    if enrollment is not None:
        insert_ledger(enrollment["applicant_id"], enrollment["id"], event["phase"],
                      event["billed_amount_cents"], event["id"])


def _advance_phase(enrollment):
    nxt = PHASE_NEXT.get(enrollment["current_phase"])
    if nxt is not None:
        enrollment["current_phase"] = nxt
        bump(enrollment)


@bp.post("/training-events/<eid>/complete")
def complete_event(eid):
    event = _event_resolvable(eid, "complete")
    body = get_body()
    score = body.get("score")
    if not is_int(score) or score < 0 or score > 100:
        raise ApiError("ERR_INVALID_REQUEST", "score is required and must be an integer in 0..100")
    # IOE milestone gate: cumulative COMPLETED IOE SESSION hours must reach the
    # fleet's ioe_hours_required.
    if event["event_type"] == "MILESTONE" and event["phase"] == "IOE":
        enrollment = store.enrollments.get(event["enrollment_id"])
        equipment = enrollment_equipment(enrollment) if enrollment else None
        required = equipment["ioe_hours_required"] if equipment else 0
        from services import event_duration_hours
        hours = sum(
            event_duration_hours(other)
            for other in store.training_events.values()
            if other["enrollment_id"] == event["enrollment_id"]
            and other["phase"] == "IOE" and other["event_type"] == "SESSION"
            and other["status"] == "COMPLETED")
        if hours < required:
            raise ApiError("ERR_PHASE_PREREQUISITE_NOT_MET",
                           "IOE milestone requires %s completed IOE session hours" % required)
    event["status"] = "COMPLETED"
    event["score"] = score
    bump(event)
    _bill_event(event)
    if event["event_type"] == "MILESTONE" and score >= MILESTONE_PASS_SCORE:
        enrollment = store.enrollments.get(event["enrollment_id"])
        if enrollment is not None:
            _advance_phase(enrollment)
    return success_object(ser_training_event(event))


@bp.post("/training-events/<eid>/fail")
def fail_event(eid):
    event = _event_resolvable(eid, "fail")
    body = get_body()
    score = body.get("score")
    if score is not None and (not is_int(score) or score < 0 or score > 100):
        raise ApiError("ERR_INVALID_REQUEST", "score must be an integer in 0..100")
    event["status"] = "FAILED"
    event["score"] = score
    bump(event)
    _bill_event(event)  # FAILED sessions are billed in full; no phase advancement
    return success_object(ser_training_event(event))


@bp.post("/training-events/<eid>/cancel")
def cancel_event(eid):
    require_roles("TrainingCoordinator", "SystemAdmin")
    event = get_event(eid)
    if event["status"] != "SCHEDULED":
        raise ApiError("ERR_TRAINING_EVENT_INVALID_STATE",
                       "cancel requires status SCHEDULED, found %s" % event["status"])
    event["status"] = "CANCELLED"  # no ledger entry; billed_amount_cents stays 0
    bump(event)
    return success_object(ser_training_event(event))


# ---- Checkrides ------------------------------------------------------------------

def _airman_conflict(check_airman_id, enrollment_id):
    """Segregation of duties: the airman must not have instructed any
    non-CANCELLED training event of the same enrollment."""
    return any(
        ev["enrollment_id"] == enrollment_id and ev["status"] != "CANCELLED"
        and ev["instructor_id"] == check_airman_id
        for ev in store.training_events.values())


@bp.post("/checkrides")
def create_checkride():
    require_roles("TrainingCoordinator", "SystemAdmin")
    body = get_body()
    enrollment_id = req_str(body, "enrollment_id")
    check_airman_id = req_str(body, "check_airman_id")
    ride_type = body.get("ride_type")
    scheduled_at = req_ts(body, "scheduled_at")
    # (3) existence
    enrollment = get_enrollment(enrollment_id)
    airman = get_instructor(check_airman_id)
    # (4) enrollment state guard: IN_PROGRESS with current_phase CHECKRIDE.
    if not (enrollment["status"] == "IN_PROGRESS" and enrollment["current_phase"] == "CHECKRIDE"):
        raise ApiError("ERR_ENROLLMENT_INVALID_STATE",
                       "checkride scheduling requires an IN_PROGRESS enrollment in phase CHECKRIDE")
    # (5) segregation of duties at scheduling time.
    if _airman_conflict(check_airman_id, enrollment_id):
        raise ApiError("ERR_CHECK_AIRMAN_CONFLICT",
                       "Check airman previously instructed this enrollment")
    # (10) the named airman must be tier CHECK_AIRMAN.
    if airman["instructor_type"] != "CHECK_AIRMAN":
        raise ApiError("ERR_INSTRUCTOR_NOT_QUALIFIED",
                       "check_airman_id must reference a CHECK_AIRMAN instructor")
    # (13) scheduling window.
    if scheduled_at < store.now():
        raise ApiError("ERR_FUTURE_ACTIVITY_DATE", "scheduled_at is in the past")
    # (16) constraint band.
    if ride_type not in RIDE_TYPES:
        raise ApiError("ERR_INVALID_REQUEST", "ride_type must be one of %s" % ", ".join(RIDE_TYPES))
    attempt_number = 1 + sum(
        1 for c in store.checkrides.values()
        if c["enrollment_id"] == enrollment_id and c["status"] != "CANCELLED")
    checkride = stamp_new({
        "enrollment_id": enrollment_id,
        "check_airman_id": check_airman_id,
        "ride_type": ride_type,
        "status": "SCHEDULED",
        "scheduled_at": scheduled_at,
        "completed_at": None,
        "attempt_number": attempt_number,
    })
    store.checkrides[checkride["id"]] = checkride
    return success_object(ser_checkride(checkride), 201)


@bp.get("/checkrides")
def list_checkrides():
    require_roles(*EVENT_READ_ROLES)
    limit, offset = pagination_params()
    rows = list(store.checkrides.values())
    enrollment_id = request.args.get("enrollment_id")
    check_airman_id = request.args.get("check_airman_id")
    status = request.args.get("status")
    if enrollment_id is not None:
        rows = [c for c in rows if c["enrollment_id"] == enrollment_id]
    if check_airman_id is not None:
        rows = [c for c in rows if c["check_airman_id"] == check_airman_id]
    if status is not None:
        rows = [c for c in rows if c["status"] == status]
    rows = sort_rows(rows)
    total = len(rows)
    return success_list([ser_checkride(c) for c in rows[offset:offset + limit]], limit, offset, total)


@bp.get("/checkrides/<cid>")
def read_checkride(cid):
    require_roles(*EVENT_READ_ROLES)
    return success_object(ser_checkride(get_checkride(cid)))


@bp.post("/checkrides/<cid>/record-outcome")
def record_outcome(cid):
    user_id, role = require_roles("CheckAirman", "SystemAdmin")
    checkride = get_checkride(cid)
    # (2) identity: the acting CheckAirman must be the ride's assigned airman.
    if role == "CheckAirman" and checkride["check_airman_id"] != user_id:
        raise ApiError("ERR_FORBIDDEN_ROLE",
                       "A check airman may record outcomes only on rides assigned to them")
    # (4) state guards.
    if checkride["status"] != "SCHEDULED":
        raise ApiError("ERR_CHECKRIDE_INVALID_STATE",
                       "record-outcome requires status SCHEDULED, found %s" % checkride["status"])
    enrollment = get_enrollment(checkride["enrollment_id"])
    if enrollment["status"] not in ("IN_PROGRESS", "REMEDIATION"):
        raise ApiError("ERR_ENROLLMENT_INVALID_STATE",
                       "record-outcome requires enrollment IN_PROGRESS or REMEDIATION")
    # (5) segregation of duties, re-checked.
    if _airman_conflict(checkride["check_airman_id"], enrollment["id"]):
        raise ApiError("ERR_CHECK_AIRMAN_CONFLICT",
                       "Check airman previously instructed this enrollment")
    # (6) medical gate against the class equipment's qualification, if one exists.
    equipment = enrollment_equipment(enrollment)
    qual = find_qualification(enrollment["applicant_id"], equipment["id"]) if equipment else None
    if qual is not None and qual["operating_state"] == "GROUNDED":
        raise ApiError("ERR_MEDICAL_GROUNDED",
                       "Applicant qualification is GROUNDED for this equipment")
    # (16) constraint band: outcome value.
    outcome = get_body().get("outcome")
    if outcome not in ("PASS", "FAIL"):
        raise ApiError("ERR_INVALID_REQUEST", "outcome must be one of PASS, FAIL")

    now = store.now()
    checkride["completed_at"] = now
    bump(checkride)

    if outcome == "PASS":
        checkride["status"] = "COMPLETED_PASS"
        # Phase advance CHECKRIDE -> IOE (cascade: no enrollment version bump is
        # listed for this transition, unlike the event-milestone advance).
        if enrollment["current_phase"] == "CHECKRIDE":
            enrollment["current_phase"] = "IOE"
            touch(enrollment)
        # Qualification upsert for (applicant, class equipment).
        if equipment is not None:
            if qual is None:
                qual = stamp_new({
                    "applicant_id": enrollment["applicant_id"],
                    "equipment_id": equipment["id"],
                    "currency_state": "QUALIFIED",
                    "operating_state": "ACTIVE",
                    "qualified_at": now,
                    "landings_90d": 0,
                    "landings_expiring_7d": 0,
                    "lapsed_since": None,
                    "last_evaluated_at": None,
                    "_requalifying_since": None,
                })
                store.qualifications[qual["id"]] = qual
            else:
                # Existing row: only operating_state is refreshed here.
                new_operating = "ACTIVE" if has_valid_first_medical(enrollment["applicant_id"]) else "GROUNDED"
                if qual["operating_state"] != new_operating:
                    qual["operating_state"] = new_operating
                touch(qual)
        insert_ledger(enrollment["applicant_id"], enrollment["id"], "CHECKRIDE",
                      CHECKRIDE_FEE_CENTS, checkride["id"])
    else:
        checkride["status"] = "COMPLETED_FAIL"
        insert_ledger(enrollment["applicant_id"], enrollment["id"], "CHECKRIDE",
                      CHECKRIDE_FEE_CENTS, checkride["id"])
        # Cascade link 1: IN_PROGRESS -> REMEDIATION (no-op when already there).
        enrollment["failed_attempts"] = sum(
            1 for c in store.checkrides.values()
            if c["enrollment_id"] == enrollment["id"] and c["status"] == "COMPLETED_FAIL")
        if enrollment["status"] == "IN_PROGRESS":
            enrollment["status"] = "REMEDIATION"
            enrollment["entered_remediation_at"] = now
            touch(enrollment)
            # Link 2: RETRAINING surcharge, caused by entering remediation.
            from services import retraining_charge_cents
            insert_ledger(enrollment["applicant_id"], enrollment["id"], "RETRAINING",
                          retraining_charge_cents(), checkride["id"])
            # Link 3 (balance recompute) happens inside insert_ledger.
        else:
            touch(enrollment)
    return success_object(ser_checkride(checkride))


@bp.post("/checkrides/<cid>/cancel")
def cancel_checkride(cid):
    require_roles("TrainingCoordinator", "SystemAdmin")
    checkride = get_checkride(cid)
    if checkride["status"] != "SCHEDULED":
        raise ApiError("ERR_CHECKRIDE_INVALID_STATE",
                       "cancel requires status SCHEDULED, found %s" % checkride["status"])
    checkride["status"] = "CANCELLED"
    bump(checkride)
    return success_object(ser_checkride(checkride))
