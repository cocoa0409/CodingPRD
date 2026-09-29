"""Chasing the prescriber: opening, chasing, escalating and answering."""

from flask import Blueprint

import calc
import clock
import db
import engine
import enums
import middleware
import response
import store
import validators
from errors import ApiError

bp = Blueprint("auths", __name__)


@bp.post("/refill-authorizations")
def create_request():
    middleware.authenticate(("PharmacyOperations",))
    body = validators.json_body()
    prescription_id = validators.string(body, "prescription_id")
    requested_refills = validators.integer(
        body, "requested_refills", minimum=1, maximum=12
    )

    prescription = middleware.lookup("prescription", prescription_id)

    if prescription["status"] not in ("ACTIVE", "PENDING_AUTHORIZATION"):
        raise ApiError("ERR_INVALID_PRESCRIPTION_STATE")
    for existing in engine.auth_requests_of_prescription(prescription_id):
        if existing["status"] in ("SENT", "NO_RESPONSE", "ESCALATED"):
            raise ApiError("ERR_DUPLICATE_AUTH_REQUEST")

    request_row = store.create(
        db.refill_authorizations,
        {
            "prescription_id": prescription_id,
            "prescriber_npi": prescription["prescriber_npi"],
            "requested_refills": requested_refills,
            "status": "SENT",
            "chase_round": 0,
            "escalation_level": 0,
            "first_sent_at": clock.now_iso(),
            "last_sent_at": clock.now_iso(),
            "next_chase_due_at": clock.hours_from_now_iso(enums.CHASE_WINDOW_HOURS),
            "no_response_recorded_at": None,
            "approved_refills": None,
            "denial_reason": None,
        },
    )
    return response.object_response(store.serialize(request_row), 201)


@bp.post("/refill-authorizations/<request_id>/chase")
def chase(request_id):
    middleware.authenticate(("PharmacyOperations",))
    request_row = middleware.lookup("refill_authorization", request_id)

    if request_row["status"] not in ("SENT", "NO_RESPONSE"):
        raise ApiError("ERR_INVALID_AUTH_STATE")

    if request_row["status"] == "SENT":
        due_at = store.ts(request_row["next_chase_due_at"])
        if due_at is not None and clock.now() < due_at:
            raise ApiError("ERR_CHASE_TOO_EARLY")
        if request_row["chase_round"] >= enums.CHASE_ROUND_LIMIT:
            raise ApiError("ERR_CHASE_LIMIT_REACHED")
        request_row["status"] = "NO_RESPONSE"
        request_row["chase_round"] += 1
        request_row["no_response_recorded_at"] = clock.now_iso()
    else:
        request_row["status"] = "SENT"
        request_row["last_sent_at"] = clock.now_iso()
        request_row["next_chase_due_at"] = clock.hours_from_now_iso(enums.CHASE_WINDOW_HOURS)
    store.touch(request_row)

    store.commit()
    return response.object_response(store.serialize(request_row))


@bp.post("/refill-authorizations/<request_id>/escalate")
def escalate(request_id):
    middleware.authenticate(("PharmacyOperations",))
    request_row = middleware.lookup("refill_authorization", request_id)

    if request_row["status"] != "NO_RESPONSE":
        raise ApiError("ERR_INVALID_AUTH_STATE")
    if request_row["chase_round"] < enums.CHASE_ROUND_LIMIT:
        raise ApiError("ERR_ESCALATION_PREMATURE")

    request_row["status"] = "ESCALATED"
    request_row["escalation_level"] = 1
    store.touch(request_row)

    today = clock.today()
    for line in engine.lines_of_prescription(request_row["prescription_id"]):
        if line["line_status"] != "HELD_AUTH":
            continue
        cycle = db.fill_cycles[line["cycle_id"]]
        if today < store.d(cycle["cycle_start_date"]):
            continue
        line["line_status"] = "EXCLUDED_HELD"
        line["hold_reason"] = "AUTH_ESCALATED"
        store.touch(line)
        _resolve_cycle(cycle)

    store.commit()
    return response.object_response(store.serialize(request_row))


@bp.post("/refill-authorizations/<request_id>/respond")
def respond(request_id):
    middleware.authenticate(("Prescriber",))
    body = validators.json_body()
    decision = validators.enum(body, "decision", enums.AUTH_DECISIONS)
    approved_refills = validators.integer(
        body, "approved_refills", required=False, default=None
    )
    denial_reason = validators.string(body, "denial_reason", required=False, default=None)

    request_row = middleware.lookup("refill_authorization", request_id)

    if request_row["status"] not in ("SENT", "ESCALATED"):
        raise ApiError("ERR_INVALID_AUTH_STATE")

    if decision == "APPROVE":
        if (
            approved_refills is None
            or approved_refills < 1
            or approved_refills > 12
            or approved_refills > request_row["requested_refills"]
        ):
            raise ApiError("ERR_INVALID_APPROVED_DAYS")
    elif denial_reason is None:
        raise ApiError("ERR_INVALID_APPROVED_DAYS")

    prescription = db.prescriptions[request_row["prescription_id"]]
    patient = db.patients[prescription["patient_id"]]
    plan = engine.plan_of(patient)
    held_lines = [
        line
        for line in engine.lines_of_prescription(prescription["id"])
        if line["line_status"] == "HELD_AUTH"
    ]

    if decision == "APPROVE":
        request_row["status"] = "APPROVED"
        request_row["approved_refills"] = approved_refills
        store.touch(request_row)

        prescription["status"] = "ACTIVE"
        prescription["refills_authorized"] += approved_refills
        prescription["refills_remaining"] += approved_refills
        store.touch(prescription)

        for line in held_lines:
            line["line_status"] = "ADJUDICATED"
            line["hold_reason"] = None
            line["copay_cents"] = calc.line_copay_cents(
                plan, prescription, line["days_supply_filled"]
            )
            store.touch(line)
            engine.stamp_dispense(prescription, line)
    else:
        request_row["status"] = "DENIED"
        request_row["denial_reason"] = denial_reason
        store.touch(request_row)

        prescription["status"] = "DISCONTINUED"
        store.touch(prescription)

        for line in held_lines:
            line["line_status"] = "EXCLUDED_HELD"
            line["hold_reason"] = "AUTH_DENIED"
            store.touch(line)

    seen = set()
    for line in held_lines:
        if line["cycle_id"] in seen:
            continue
        seen.add(line["cycle_id"])
        _resolve_cycle(db.fill_cycles[line["cycle_id"]])

    store.commit()
    return response.object_response(store.serialize(request_row))


def _resolve_cycle(cycle):
    engine.recompute_total_copay(cycle)
    engine.clear_cycle_if_resolved(cycle)
    store.touch(cycle)
