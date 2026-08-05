"""In-office scheduling and delivery, plus patient-logged home practice."""

from datetime import timedelta

from flask import Blueprint, request

import calc
import cascades
import config
import lookup
import serialize
from auth import authenticate, require_owner
from envelope import created, ok, paginate, pagination
from errors import ApiError
from store import base_row, db, now, now_iso, ordered, parse_date, parse_instant, touch
from validate import filter_enum, json_body, require_order

bp = Blueprint("sessions", __name__)
P = config.API_PREFIX

_OCCUPYING = ("SCHEDULED", "CHECKED_IN", "COMPLETED")


@bp.post(P + "/therapy-plans/<id>/sessions")
def schedule_session(id):
    authenticate([config.ROLE_FRONT_DESK, config.ROLE_OPTOMETRIST, config.ROLE_VISION_THERAPIST])
    b = json_body()
    therapist_id = b.str_req("therapist_id")
    room_id = b.str_req("room_id")
    start_raw = b.instant_req("scheduled_start_at")
    end_raw = b.instant_req("scheduled_end_at")
    require_order(start_raw, end_raw, "scheduled_end_at must be strictly after scheduled_start_at.")
    b.enum_shape_req("procedure_code")
    expected_version = b.int_req("expected_authorization_version")
    procedure_code = b.enum_req("procedure_code", config.PROCEDURE_CODES)

    plan = lookup.plan_or_404(id)                                          # rung 8
    therapist = lookup.therapist_or_404(therapist_id)                      # rung 11
    lookup.room_or_404(room_id)
    lookup.gate_for_plan(plan)                                             # rung 12

    auth_row = db.authorizations.get(plan.get("authorization_id"))
    if auth_row is not None:
        if expected_version != auth_row["version"]:                        # rung 13
            raise ApiError("ERR_STALE_VERSION")
        if auth_row["status"] not in ("ACTIVE", "EXHAUSTED"):              # rung 14
            raise ApiError("ERR_INVALID_STATE", "The authorization pool is not open.")
    if plan["status"] != "ACTIVE":                                         # rung 15
        raise ApiError("ERR_PLAN_NOT_ACTIVE")

    start = parse_instant(start_raw)
    end = parse_instant(end_raw)
    expires = parse_instant(therapist.get("credential_expires_at"))
    if expires is None or expires <= start:                                # rung 16
        raise ApiError("ERR_CREDENTIAL_EXPIRED")

    window_start = parse_date(auth_row["window_start_date"])               # rung 19
    window_end = parse_date(auth_row["window_end_date"])
    if not (window_start <= start.date() <= window_end):
        raise ApiError("ERR_SESSION_OUTSIDE_AUTH_WINDOW")

    buffer_delta = timedelta(minutes=config.ROOM_TURNOVER_BUFFER_MINUTES)
    for other in db.sessions.values():                                     # rung 20
        if other.get("room_id") != room_id or other["schedule_status"] not in _OCCUPYING:
            continue
        o_start = parse_instant(other.get("scheduled_start_at"))
        o_end = parse_instant(other.get("scheduled_end_at"))
        if o_start is None or o_end is None:
            continue
        if start < o_end + buffer_delta and o_start < end + buffer_delta:
            raise ApiError("ERR_ROOM_CONFLICT")

    for other in db.sessions.values():                                     # rung 21
        if other.get("therapist_id") != therapist_id or other["schedule_status"] not in _OCCUPYING:
            continue
        o_start = parse_instant(other.get("scheduled_start_at"))
        o_end = parse_instant(other.get("scheduled_end_at"))
        if o_start is None or o_end is None:
            continue
        if start < o_end and o_start < end:
            raise ApiError("ERR_THERAPIST_CONFLICT")

    requested = calc.interval_minutes(start_raw, end_raw)                  # rung 22
    existing = calc.therapist_scheduled_minutes(therapist_id, start.date())
    if existing + requested > config.THERAPIST_MAX_DAILY_MINUTES:
        raise ApiError("ERR_THERAPIST_DAILY_CAP_EXCEEDED")

    if auth_row["visits_remaining"] < 1:                                   # rung 23
        raise ApiError("ERR_AUTH_VISITS_EXHAUSTED")

    row = base_row()
    row.update({
        "plan_id": plan["id"],
        "patient_id": plan["patient_id"],
        "therapist_id": therapist_id,
        "room_id": room_id,
        "authorization_id": auth_row["id"],
        "supervising_optometrist_id": None,
        "modality": "IN_OFFICE",
        "scheduled_start_at": start_raw,
        "scheduled_end_at": end_raw,
        "performed_at": None,
        "timed_minutes": None,
        "procedure_code": procedure_code,
        "billable_units": 0,
        "charge_amount": 0.0,
        "weighted_minutes": 0.0,
        "schedule_status": "SCHEDULED",
        "billing_status": "PENDING",
        "activities_mastered_delta": 0,
        "cancel_reason": None,
        "attested_at": None,
        "attestation_statement": None,
        "activity_notes": None,
    })
    db.sessions[row["id"]] = row
    cascades.consume_visit_unit(auth_row)
    return created(serialize.session(row))


@bp.post(P + "/therapy-plans/<id>/home-sessions")
def log_home_session(id):
    caller = authenticate([config.ROLE_PATIENT])
    plan_peek = db.plans.get(id)
    if plan_peek is not None:                                              # rung 2 ownership
        require_owner(caller, plan_peek["patient_id"])
    b = json_body()
    performed_at = b.instant_req("performed_at")
    timed_minutes = b.int_req("timed_minutes", non_negative=True)
    activity_notes = b.str_opt("activity_notes")

    plan = lookup.plan_or_404(id)                                          # rung 8
    lookup.gate_for_plan(plan)                                             # rung 12
    if plan["status"] != "ACTIVE":                                         # rung 15
        raise ApiError("ERR_PLAN_NOT_ACTIVE")

    row = base_row()
    row.update({
        "plan_id": plan["id"],
        "patient_id": plan["patient_id"],
        "therapist_id": None,
        "room_id": None,
        "authorization_id": None,
        "supervising_optometrist_id": None,
        "modality": "HOME",
        "scheduled_start_at": None,
        "scheduled_end_at": None,
        "performed_at": performed_at,
        "timed_minutes": timed_minutes,
        "procedure_code": "HOME_PRACTICE",
        "billable_units": 0,
        "charge_amount": 0.0,
        "weighted_minutes": 0.0,
        "schedule_status": "LOGGED",
        "billing_status": "NON_BILLABLE",
        "activities_mastered_delta": 0,
        "cancel_reason": None,
        "attested_at": None,
        "attestation_statement": None,
        "activity_notes": activity_notes,
    })
    row["weighted_minutes"] = calc.weighted_minutes(row)
    db.sessions[row["id"]] = row
    return created(serialize.session(row))


@bp.get(P + "/sessions/<id>")
def get_session(id):
    caller = authenticate(config.READ_ROLES_WITH_PATIENT)
    row = db.sessions.get(id)
    if row is not None:
        require_owner(caller, row["patient_id"])
    return ok(serialize.session(lookup.session_or_404(id)))


@bp.get(P + "/sessions")
def list_sessions():
    caller = authenticate(config.READ_ROLES_WITH_PATIENT)
    limit, offset = pagination(request.args)
    modality = filter_enum(request.args, "modality", config.MODALITIES)
    schedule_status = filter_enum(request.args, "schedule_status", config.SCHEDULE_STATUSES)
    billing_status = filter_enum(request.args, "billing_status", config.BILLING_STATUSES)
    plan_id = request.args.get("plan_id")
    patient_id = request.args.get("patient_id")
    therapist_id = request.args.get("therapist_id")
    room_id = request.args.get("room_id")
    authorization_id = request.args.get("authorization_id")
    supervising = request.args.get("supervising_optometrist_id")
    if caller.is_patient:
        patient_id = caller.user_id

    def match(row):
        if plan_id and row["plan_id"] != plan_id:
            return False
        if patient_id and row["patient_id"] != patient_id:
            return False
        if therapist_id and row["therapist_id"] != therapist_id:
            return False
        if room_id and row["room_id"] != room_id:
            return False
        if authorization_id and row["authorization_id"] != authorization_id:
            return False
        if supervising and row["supervising_optometrist_id"] != supervising:
            return False
        if modality and row["modality"] != modality:
            return False
        if schedule_status and row["schedule_status"] != schedule_status:
            return False
        if billing_status and row["billing_status"] != billing_status:
            return False
        return True

    return paginate(ordered(db.sessions, match), limit, offset, serialize.session)


@bp.post(P + "/sessions/<id>/check-in")
def check_in(id):
    authenticate([config.ROLE_FRONT_DESK, config.ROLE_OPTOMETRIST,
                  config.ROLE_VISION_THERAPIST, config.ROLE_THERAPY_ASSISTANT])
    json_body()
    session = lookup.session_or_404(id)                                    # rung 9
    lookup.gate_for_patient_id(session["patient_id"])                      # rung 12
    if session["modality"] != "IN_OFFICE" or session["schedule_status"] != "SCHEDULED":  # rung 14
        raise ApiError("ERR_INVALID_STATE", "Only a SCHEDULED in-office session may be checked in.")
    plan = db.plans.get(session["plan_id"])
    if plan is None or plan["status"] != "ACTIVE":                         # rung 15
        raise ApiError("ERR_PLAN_NOT_ACTIVE")

    session["schedule_status"] = "CHECKED_IN"
    touch(session)
    return ok(serialize.session(session))


@bp.post(P + "/sessions/<id>/complete")
def complete_session(id):
    authenticate([config.ROLE_OPTOMETRIST, config.ROLE_VISION_THERAPIST,
                  config.ROLE_THERAPY_ASSISTANT])
    b = json_body()
    performed_raw = b.instant_req("performed_at")
    timed_minutes = b.int_req("timed_minutes", non_negative=True)
    supervising_id = b.str_opt("supervising_optometrist_id")
    mastered_delta = b.int_opt("activities_mastered_delta", 0)

    session = lookup.session_or_404(id)                                    # rung 9
    supervisor = None
    if supervising_id:
        supervisor = lookup.therapist_or_404(supervising_id)               # rung 11
    lookup.gate_for_patient_id(session["patient_id"])                      # rung 12
    if session["schedule_status"] != "CHECKED_IN":                         # rung 14
        raise ApiError("ERR_INVALID_STATE", "Only a CHECKED_IN session may be completed.")

    performed = parse_instant(performed_raw)
    therapist = db.therapists.get(session.get("therapist_id"))
    expires = parse_instant(therapist.get("credential_expires_at")) if therapist else None
    if expires is None or expires <= performed:                            # rung 16
        raise ApiError("ERR_CREDENTIAL_EXPIRED")

    if therapist["credential"] == "VISION_THERAPY_ASSISTANT":              # rung 18
        if supervisor is None or supervisor["credential"] != "OPTOMETRIST":
            raise ApiError("ERR_SUPERVISION_REQUIRED")
        sup_expires = parse_instant(supervisor.get("credential_expires_at"))
        if sup_expires is None or sup_expires <= performed:
            raise ApiError("ERR_SUPERVISION_REQUIRED")

    session["schedule_status"] = "COMPLETED"
    session["performed_at"] = performed_raw
    session["timed_minutes"] = timed_minutes
    session["supervising_optometrist_id"] = supervising_id
    session["activities_mastered_delta"] = mastered_delta
    units = calc.session_billable_units(session["procedure_code"], timed_minutes)
    session["billable_units"] = units
    session["charge_amount"] = calc.charge_amount(units, session["procedure_code"])
    session["weighted_minutes"] = calc.weighted_minutes(session)
    session["billing_status"] = "BILLABLE" if units >= 1 else "NON_BILLABLE"
    touch(session)

    plan = db.plans.get(session["plan_id"])
    if plan is not None:
        calc.recompute_cumulative_minutes(plan)
        touch(plan)
        phase = cascades.in_progress_phase(plan["id"])
        if phase is not None and mastered_delta:
            phase["activities_mastered_count"] += mastered_delta
            touch(phase)
    return ok(serialize.session(session))


@bp.post(P + "/sessions/<id>/cancel")
def cancel_session_route(id):
    authenticate([config.ROLE_FRONT_DESK, config.ROLE_OPTOMETRIST, config.ROLE_VISION_THERAPIST])
    b = json_body()
    b.enum_shape_req("cancel_reason")                                      # rung 3
    reason = b.enum_req("cancel_reason", config.CANCEL_REASONS)            # rung 4
    session = lookup.session_or_404(id)                                    # rung 9
    lookup.gate_for_patient_id(session["patient_id"])                      # rung 12
    if session["schedule_status"] not in ("SCHEDULED", "CHECKED_IN"):      # rung 14
        raise ApiError("ERR_INVALID_STATE",
                       "Only a SCHEDULED or CHECKED_IN session may be cancelled.")

    cascades.cancel_session(session, reason)
    return ok(serialize.session(session))


@bp.post(P + "/sessions/<id>/no-show")
def no_show(id):
    authenticate([config.ROLE_FRONT_DESK])
    json_body()
    session = lookup.session_or_404(id)                                    # rung 9
    lookup.gate_for_patient_id(session["patient_id"])                      # rung 12
    if session["modality"] != "IN_OFFICE" or session["schedule_status"] != "SCHEDULED":  # rung 14
        raise ApiError("ERR_INVALID_STATE", "Only a SCHEDULED in-office session may be no-showed.")
    start = parse_instant(session.get("scheduled_start_at"))
    if start is None or now() < start:
        raise ApiError("ERR_INVALID_STATE",
                       "A no-show may only be recorded once the clock reaches the start instant.")

    session["schedule_status"] = "NO_SHOW"
    session["billing_status"] = "NON_BILLABLE"
    touch(session)
    return ok(serialize.session(session))


@bp.post(P + "/sessions/<id>/attest")
def attest_session(id):
    caller = authenticate([config.ROLE_PATIENT])
    peek = db.sessions.get(id)
    if peek is not None:                                                   # rung 2 ownership
        require_owner(caller, peek["patient_id"])
    b = json_body()
    statement = b.str_req("attestation_statement")
    session = lookup.session_or_404(id)                                    # rung 9
    lookup.gate_for_patient_id(session["patient_id"])                      # rung 12
    if session["modality"] != "HOME" or session["schedule_status"] != "LOGGED":  # rung 14
        raise ApiError("ERR_INVALID_STATE", "Only a LOGGED home session may be attested.")

    session["schedule_status"] = "ATTESTED"
    session["attested_at"] = now_iso()
    session["attestation_statement"] = statement
    session["weighted_minutes"] = calc.weighted_minutes(session)
    touch(session)

    plan = db.plans.get(session["plan_id"])
    if plan is not None:
        calc.recompute_cumulative_minutes(plan)
        calc.refresh_home_compliance(plan)
        touch(plan)
    return ok(serialize.session(session))
