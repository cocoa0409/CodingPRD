"""Visits, adverse events, and compensation payments (PRD §3.5, §3.6, §3.7)."""
from flask import Blueprint

import calc
import clock
import db
import domain
from errors import err
from middleware import require
from response import object_response, array_plain
from serialize import serialize
from util import parse_dt
from validate import get_json, require_fields, check_int, check_string, check_enum, check_action

bp = Blueprint("visits", __name__)

SEVERITIES = {"MILD", "MODERATE", "SEVERE", "LIFE_THREATENING"}
REVIEW_ACTIONS = {"TRIAGE", "ADJUDICATE"}
RELATIONS = {"RELATED", "UNRELATED"}


def _get_enrollment_or_404(enrollment_id):
    e = db.enrollments.get(enrollment_id)
    if e is None:
        err("ERR_NOT_FOUND", "Enrollment not found")
    return e


# --- Visit -----------------------------------------------------------------

@bp.route("/enrollments/<enrollment_id>/visits", methods=["POST"])
@require("CoordinatorStaff")
def schedule_visit(enrollment_id, caller_id=None, caller_role=None):
    e = _get_enrollment_or_404(enrollment_id)
    body = get_json()
    require_fields(body, "sequence_index", "scheduled_at", "draw_window_minutes")
    seq = check_int(body, "sequence_index", minimum=1)
    scheduled_raw = check_string(body, "scheduled_at")
    scheduled_at = parse_dt(scheduled_raw)
    if scheduled_at is None:
        err("ERR_INVALID_REQUEST", "scheduled_at must be an ISO 8601 datetime")
    window = check_int(body, "draw_window_minutes", minimum=0)

    siblings = domain.enrollment_visits(enrollment_id)

    # Duplicate sequence_index (priority 20).
    if any(v["sequence_index"] == seq for v in siblings):
        err("ERR_DUPLICATE_VISIT_INDEX", "sequence_index already exists for this enrollment")

    # Window overlap (priority 18): |Δ minutes| must be >= w_a + w_b.
    for v in siblings:
        delta_min = abs((scheduled_at - v["scheduled_at"]).total_seconds()) / 60.0
        if delta_min < (window + v["draw_window_minutes"]):
            err("ERR_VISIT_WINDOW_OVERLAP", "Visit draw window overlaps a sibling visit")

    rec = domain.make_base()
    rec.update({
        "enrollment_id": enrollment_id,
        "sequence_index": seq,
        "scheduled_at": scheduled_at,
        "draw_window_minutes": window,
        "drawn_at": None,
        "draw_in_window": False,
        "draw_deviation_minutes": None,
        "status": "SCHEDULED",
        "payable_amount_cents": 0,
    })
    db.visits[rec["id"]] = rec
    return object_response(serialize("Visit", rec), 201)


@bp.route("/enrollments/<enrollment_id>/visits", methods=["GET"])
@require("CoordinatorStaff", "Sponsor", "SafetyOfficer")
def list_visits(enrollment_id, caller_id=None, caller_role=None):
    _get_enrollment_or_404(enrollment_id)
    items = domain.sorted_by_created(domain.enrollment_visits(enrollment_id))
    return array_plain([serialize("Visit", v) for v in items])


@bp.route("/visits/<visit_id>/complete", methods=["POST"])
@require("CoordinatorStaff")
def complete_visit(visit_id, caller_id=None, caller_role=None):
    v = db.visits.get(visit_id)
    if v is None:
        err("ERR_NOT_FOUND", "Visit not found")
    e = db.enrollments[v["enrollment_id"]]

    body = get_json()
    require_fields(body, "drawn_at")
    drawn_raw = check_string(body, "drawn_at")
    drawn_at = parse_dt(drawn_raw)
    if drawn_at is None:
        err("ERR_INVALID_REQUEST", "drawn_at must be an ISO 8601 datetime")

    # State (priority 8): visit must be SCHEDULED.
    if v["status"] != "SCHEDULED":
        err("ERR_INVALID_STATE", "Visit is not in SCHEDULED state")
    # Parent enrollment must be ACTIVE.
    if e["enrollment_status"] != "ACTIVE":
        err("ERR_INVALID_STATE", "Parent enrollment is not ACTIVE")
    # Hold gate (priority 12).
    if e["safety_status"] == "HOLD":
        err("ERR_ENROLLMENT_ON_HOLD", "Enrollment is on a safety hold")

    # Half-open window check (priority 17 / calc draw_window_check):
    # [scheduled_at - w, scheduled_at + w).
    from datetime import timedelta
    w = timedelta(minutes=v["draw_window_minutes"])
    lower = v["scheduled_at"] - w
    upper = v["scheduled_at"] + w
    in_window = (drawn_at >= lower) and (drawn_at < upper)
    if not in_window:
        err("ERR_DRAW_OUT_OF_WINDOW", "drawn_at falls outside the half-open draw window")

    deviation = int(abs((drawn_at - v["scheduled_at"]).total_seconds()) // 60)

    v["drawn_at"] = drawn_at
    v["draw_in_window"] = True
    v["draw_deviation_minutes"] = deviation
    v["status"] = "COMPLETED"
    v["payable_amount_cents"] = calc.visit_compensation(deviation, v["sequence_index"])
    domain.touch(v)

    # Cascade: parent enrollment completed_visits_count (derived, recomputed).
    e["completed_visits_count"] = sum(
        1 for x in domain.enrollment_visits(e["id"]) if x["status"] == "COMPLETED"
    )
    domain.touch(e)

    return object_response(serialize("Visit", v), 200)


# --- AdverseEvent ----------------------------------------------------------

@bp.route("/enrollments/<enrollment_id>/adverse-events", methods=["POST"])
@require("Investigator")
def report_adverse_event(enrollment_id, caller_id=None, caller_role=None):
    _get_enrollment_or_404(enrollment_id)
    body = get_json()
    require_fields(body, "severity", "occurred_at")
    severity = check_enum(body, "severity", SEVERITIES)
    occurred_raw = check_string(body, "occurred_at")
    occurred_at = parse_dt(occurred_raw)
    if occurred_at is None:
        err("ERR_INVALID_REQUEST", "occurred_at must be an ISO 8601 datetime")

    is_serious = False
    if body.get("is_serious") is not None:
        if not isinstance(body["is_serious"], bool):
            err("ERR_INVALID_REQUEST", "is_serious must be a boolean")
        is_serious = body["is_serious"]

    rec = domain.make_base()
    rec.update({
        "enrollment_id": enrollment_id,
        "reporter_user_id": caller_id,
        "severity": severity,
        "is_serious": is_serious,
        "occurred_at": occurred_at,
        "report_status": "REPORTED",
        "adjudicator_user_id": None,
    })
    db.adverse_events[rec["id"]] = rec
    return object_response(serialize("AdverseEvent", rec), 201)


@bp.route("/enrollments/<enrollment_id>/adverse-events", methods=["GET"])
@require("CoordinatorStaff", "Sponsor", "SafetyOfficer", "Investigator")
def list_adverse_events(enrollment_id, caller_id=None, caller_role=None):
    _get_enrollment_or_404(enrollment_id)
    items = domain.sorted_by_created(domain.enrollment_adverse_events(enrollment_id))
    return array_plain([serialize("AdverseEvent", ae) for ae in items])


@bp.route("/adverse-events/<event_id>/review", methods=["POST"])
@require("SafetyOfficer")
def review_adverse_event(event_id, caller_id=None, caller_role=None):
    ae = db.adverse_events.get(event_id)
    if ae is None:
        err("ERR_NOT_FOUND", "Adverse event not found")
    e = db.enrollments[ae["enrollment_id"]]
    t = db.trials[e["trial_id"]]

    body = get_json()
    require_fields(body, "action")
    # Action discriminator (priority 6): TRIAGE or ADJUDICATE; ADJUDICATE must
    # carry a valid relation.
    action = check_action(body, "action", REVIEW_ACTIONS)
    relation = body.get("relation")
    if action == "ADJUDICATE":
        if relation not in RELATIONS:
            err("ERR_INVALID_ACTION", "ADJUDICATE requires relation RELATED or UNRELATED")

    if action == "TRIAGE":
        # State (priority 8): must be REPORTED.
        if ae["report_status"] != "REPORTED":
            err("ERR_INVALID_STATE", "Adverse event is not in REPORTED state")
        # Segregation of duties (priority 10).
        if caller_id == ae["reporter_user_id"]:
            err("ERR_SEGREGATION_OF_DUTIES", "A SafetyOfficer may not review their own report")

        ae["report_status"] = "UNDER_REVIEW"
        domain.touch(ae)
        # Cascade: CLEAR -> FLAGGED.
        if e["safety_status"] == "CLEAR":
            e["safety_status"] = "FLAGGED"
            domain.touch(e)
        return object_response(serialize("AdverseEvent", ae), 200)

    # ADJUDICATE
    if ae["report_status"] != "UNDER_REVIEW":
        err("ERR_INVALID_STATE", "Adverse event is not in UNDER_REVIEW state")
    if caller_id == ae["reporter_user_id"]:
        err("ERR_SEGREGATION_OF_DUTIES", "A SafetyOfficer may not review their own report")

    ae["adjudicator_user_id"] = caller_id
    if relation == "RELATED":
        ae["report_status"] = "ADJUDICATED_RELATED"
        domain.touch(ae)
        # Cascade: severe/life-threatening -> FLAGGED -> HOLD -> freeze trial.
        if ae["severity"] in ("SEVERE", "LIFE_THREATENING") and e["safety_status"] == "FLAGGED":
            e["safety_status"] = "HOLD"
            domain.touch(e)
            domain.recompute_active_safety_holds(t)
            domain.recompute_trial_posture(t)
            domain.touch(t)
    else:  # UNRELATED
        ae["report_status"] = "ADJUDICATED_UNRELATED"
        domain.touch(ae)
        # Cascade: if no other AE keeps it flagged, FLAGGED -> CLEAR.
        if e["safety_status"] == "FLAGGED":
            others_open = any(
                o["id"] != ae["id"] and o["report_status"] in ("REPORTED", "UNDER_REVIEW")
                for o in domain.enrollment_adverse_events(e["id"])
            )
            if not others_open:
                e["safety_status"] = "CLEAR"
                domain.touch(e)

    return object_response(serialize("AdverseEvent", ae), 200)


# --- CompensationPayment ---------------------------------------------------

@bp.route("/enrollments/<enrollment_id>/payments", methods=["POST"])
@require("Sponsor")
def create_payment(enrollment_id, caller_id=None, caller_role=None):
    e = _get_enrollment_or_404(enrollment_id)

    # Gather COMPLETED, previously-unpaid visits, ordered by sequence_index ASC.
    paid_visit_ids = set()
    for p in domain.enrollment_payments(enrollment_id):
        if p["status"] in ("PENDING", "PAID"):
            paid_visit_ids.update(p["visit_ids"])

    candidates = [
        v for v in domain.enrollment_visits(enrollment_id)
        if v["status"] == "COMPLETED" and v["id"] not in paid_visit_ids
    ]
    candidates.sort(key=lambda v: v["sequence_index"])

    if not candidates:
        err("ERR_NO_PAYABLE_VISITS", "No COMPLETED previously-unpaid visit to sweep")

    gross = sum(v["payable_amount_cents"] for v in candidates)
    amount = calc.compensation_sweep(gross, e["enrollment_status"])
    visit_ids = [v["id"] for v in candidates]

    rec = domain.make_base()
    rec.update({
        "enrollment_id": enrollment_id,
        "amount_cents": amount,
        "gross_cents": gross,
        "visit_ids": visit_ids,
        "status": "PENDING",
    })
    db.payments[rec["id"]] = rec
    return object_response(serialize("CompensationPayment", rec), 201)


@bp.route("/enrollments/<enrollment_id>/payments", methods=["GET"])
@require("Sponsor", "CoordinatorStaff")
def list_payments(enrollment_id, caller_id=None, caller_role=None):
    _get_enrollment_or_404(enrollment_id)
    items = domain.sorted_by_created(domain.enrollment_payments(enrollment_id))
    return array_plain([serialize("CompensationPayment", p) for p in items])


@bp.route("/payments/<payment_id>/pay", methods=["POST"])
@require("Sponsor")
def pay_payment(payment_id, caller_id=None, caller_role=None):
    p = db.payments.get(payment_id)
    if p is None:
        err("ERR_NOT_FOUND", "Payment not found")
    if p["status"] != "PENDING":
        err("ERR_PAYMENT_NOT_PENDING", "Payment is not PENDING")
    p["status"] = "PAID"
    domain.touch(p)
    return object_response(serialize("CompensationPayment", p), 200)
