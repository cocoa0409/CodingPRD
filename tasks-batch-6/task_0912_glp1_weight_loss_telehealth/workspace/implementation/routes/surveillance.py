"""Side-effect check-ins (PRD 3.8) and the coaching entitlement (PRD 3.10)."""

from flask import Blueprint

import calculations as calc
import envelope
import errors
import serializers
import services
import validation as v
from auth import ANY_ROLE, guard, require_owner
from errors import ApiError
from store import new_record, ordered, parse_iso, store, touch

bp = Blueprint("surveillance", __name__)


# --- check-ins -------------------------------------------------------------
@bp.post("/check-ins")
def create_check_in():
    guard(["Patient"])
    body = v.body()

    patient_id = v.string_field(body, "patient_id", required=True)
    prescription_id = v.string_field(body, "prescription_id", required=True)
    nausea_score = v.int_field(body, "nausea_score", required=True, minimum=0, maximum=3)
    vomiting_score = v.int_field(body, "vomiting_score", required=True, minimum=0,
                                 maximum=3)
    dehydration_flag = v.bool_field(body, "dehydration_flag", required=False,
                                    default=False)

    services.get_patient(patient_id)
    services.get_prescription(prescription_id)

    check_in = new_record(store.check_ins, {
        "patient_id": patient_id,
        "prescription_id": prescription_id,
        "triaged_by_provider_id": None,
        "nausea_score": nausea_score,
        "vomiting_score": vomiting_score,
        "dehydration_flag": dehydration_flag,
        "severity_score": calc.severity_score(nausea_score, vomiting_score,
                                              dehydration_flag),
        "status": "SUBMITTED",
        "submitted_at": store.now_iso(),
        "triaged_at": None,
        "resolved_at": None,
    })
    return envelope.success(serializers.dump("check_in", check_in), 201)


@bp.get("/check-ins/<check_in_id>")
def read_check_in(check_in_id):
    guard(ANY_ROLE)
    check_in = services.get_check_in(check_in_id)
    return envelope.success(serializers.dump("check_in", check_in), 200)


@bp.get("/check-ins")
def list_check_ins():
    guard(ANY_ROLE)
    limit, offset = v.pagination()
    filters = v.query_filters("patient_id", "prescription_id",
                              "triaged_by_provider_id", "status")
    records = v.apply_filters(ordered(list(store.check_ins.values())), filters)
    page, total = v.paginate(records, limit, offset)
    return envelope.collection(serializers.dump_many("check_in", page),
                               limit, offset, total)


@bp.post("/check-ins/<check_in_id>/triage")
def triage_check_in(check_in_id):
    user_id, _role = guard(["Provider"])
    check_in = services.get_check_in(check_in_id)

    if check_in["status"] != "SUBMITTED":
        raise ApiError(errors.ERR_INVALID_STATE)

    score = check_in["severity_score"]
    check_in["triaged_at"] = store.now_iso()
    check_in["triaged_by_provider_id"] = user_id
    check_in["status"] = ("ESCALATED" if score >= calc.CHECK_IN_ESCALATION_SCORE
                          else "CLEARED")
    touch(check_in)

    prescription = services.get_prescription(check_in["prescription_id"])
    services.recompute_severity_indices(prescription)

    if score >= calc.CHECK_IN_HOLD_SCORE:
        services.apply_clinical_hold(prescription)

    return envelope.success(serializers.dump("check_in", check_in), 200)


@bp.post("/check-ins/<check_in_id>/resolve")
def resolve_check_in(check_in_id):
    guard(["Provider"])
    check_in = services.get_check_in(check_in_id)

    if check_in["status"] != "ESCALATED":
        raise ApiError(errors.ERR_INVALID_STATE)

    check_in["status"] = "RESOLVED"
    check_in["resolved_at"] = store.now_iso()
    touch(check_in)

    prescription = services.get_prescription(check_in["prescription_id"])
    if not services.has_open_escalation(prescription["id"]):
        services.apply_hold_release(prescription)

    return envelope.success(serializers.dump("check_in", check_in), 200)


# --- coaching sessions -----------------------------------------------------
@bp.post("/coaching-sessions")
def create_coaching_session():
    guard(["Patient"])
    body = v.body()

    subscription_id = v.string_field(body, "subscription_id", required=True)
    coach_provider_id = v.string_field(body, "coach_provider_id", required=True)
    start_raw = v.datetime_field(body, "scheduled_start_at", required=True)
    end_raw = v.datetime_field(body, "scheduled_end_at", required=True)
    start_dt, end_dt = v.interval(start_raw, end_raw)

    subscription = services.get_subscription(subscription_id)
    coach = services.get_provider(coach_provider_id)

    # Gate 1: the subscription must be active.
    if subscription["status"] != "ACTIVE":
        raise ApiError(errors.ERR_SUBSCRIPTION_NOT_ACTIVE)

    # Gate 2: the practitioner must be an active coach.
    if coach["provider_type"] != "COACH" or coach["status"] != "ACTIVE":
        raise ApiError(errors.ERR_PROVIDER_NOT_ELIGIBLE)

    # Gate 3a: plain half-open overlap against the coach's other sessions.
    if services.coach_conflicts(coach_provider_id, start_dt, end_dt):
        raise ApiError(errors.ERR_COACH_SLOT_CONFLICT)

    # Gate 3b: the start instant must land inside one OPEN or INVOICED cycle.
    billing_cycle_id = None
    for cycle in services.cycles_of(subscription_id):
        if cycle["status"] not in ("OPEN", "INVOICED"):
            continue
        period_start = parse_iso(cycle["period_start_at"])
        period_end = parse_iso(cycle["period_end_at"])
        if period_start <= start_dt < period_end:
            billing_cycle_id = cycle["id"]
            break
    if billing_cycle_id is None:
        raise ApiError(errors.ERR_INVALID_STATE)

    # Gate 4: entitlement, under the reservation-inclusive reading.
    if calc.credits_available(subscription) < 1:
        raise ApiError(errors.ERR_COACHING_CREDITS_EXHAUSTED)

    session = new_record(store.coaching_sessions, {
        "subscription_id": subscription_id,
        "coach_provider_id": coach_provider_id,
        "billing_cycle_id": billing_cycle_id,
        "scheduled_start_at": start_raw,
        "scheduled_end_at": end_raw,
        "status": "SCHEDULED",
        "completed_at": None,
    })

    subscription["coaching_credits_available"] -= 1
    subscription["coaching_credits_reserved"] += 1
    touch(subscription)

    return envelope.success(serializers.dump("coaching_session", session), 201)


@bp.get("/coaching-sessions/<coaching_session_id>")
def read_coaching_session(coaching_session_id):
    guard(ANY_ROLE)
    session = services.get_coaching_session(coaching_session_id)
    return envelope.success(serializers.dump("coaching_session", session), 200)


@bp.get("/coaching-sessions")
def list_coaching_sessions():
    guard(ANY_ROLE)
    limit, offset = v.pagination()
    filters = v.query_filters("subscription_id", "coach_provider_id",
                              "billing_cycle_id", "status")
    records = v.apply_filters(ordered(list(store.coaching_sessions.values())), filters)
    page, total = v.paginate(records, limit, offset)
    return envelope.collection(serializers.dump_many("coaching_session", page),
                               limit, offset, total)


@bp.post("/coaching-sessions/<coaching_session_id>/complete")
def complete_coaching_session(coaching_session_id):
    user_id, _role = guard(["Coach"])
    session = services.get_coaching_session(coaching_session_id)
    require_owner(session["coach_provider_id"] == user_id)

    if session["status"] != "SCHEDULED":
        raise ApiError(errors.ERR_INVALID_STATE)

    subscription = services.get_subscription(session["subscription_id"])
    if subscription["status"] != "ACTIVE":
        raise ApiError(errors.ERR_SUBSCRIPTION_NOT_ACTIVE)

    session["status"] = "COMPLETED"
    session["completed_at"] = store.now_iso()
    touch(session)

    subscription["coaching_credits_reserved"] -= 1
    subscription["coaching_credits_consumed"] += 1
    touch(subscription)

    return envelope.success(serializers.dump("coaching_session", session), 200)


@bp.post("/coaching-sessions/<coaching_session_id>/cancel")
def cancel_coaching_session(coaching_session_id):
    guard(["Patient", "Coach"])
    session = services.get_coaching_session(coaching_session_id)

    if session["status"] != "SCHEDULED":
        raise ApiError(errors.ERR_INVALID_STATE)

    session["status"] = "CANCELLED"
    touch(session)

    subscription = services.get_subscription(session["subscription_id"])
    subscription["coaching_credits_reserved"] -= 1
    subscription["coaching_credits_available"] += 1
    touch(subscription)

    return envelope.success(serializers.dump("coaching_session", session), 200)
