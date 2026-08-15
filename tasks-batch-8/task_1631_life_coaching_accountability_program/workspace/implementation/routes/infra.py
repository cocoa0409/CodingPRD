"""Test-driving infrastructure: logical clock and payment simulation
(SCAFFOLD §1.5; PRD §2.5, §3.3).
"""
from datetime import timedelta

from flask import Blueprint

import engine
from auth import authenticate, require_role, body, get_str
from db import store
from envelope import success
from errors import (ApiError, ERR_INVALID_REQUEST, ERR_INVALID_STATE,
                    ERR_COACH_NOT_CREDENTIALED, ERR_COACH_CAPACITY_FULL,
                    not_found)
from serializers import enrollment as ser_enrollment, touch
from timeutil import parse_datetime, fmt_dt

bp = Blueprint("infra", __name__)


@bp.post("/_clock/set_current_utc")
def set_clock():
    role, uid = authenticate()
    require_role(role, uid, ("PlatformAdmin",))
    b = body()
    target = parse_datetime(b.get("to_iso8601"))
    if target is None:
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "to_iso8601 must be a valid ISO 8601 datetime")
    store.clock = target
    engine.sweep_date_advance_transitions()
    return success({"current_utc": fmt_dt(store.clock)}), 200


@bp.post("/_payments/simulate")
def simulate_payment():
    """outcome=FAILED leaves all state untouched. outcome=SUCCEEDED pays the
    next due installment — or, when settling a delinquency, every LATE
    installment at once. On a PENDING_PAYMENT enrollment, paying installment
    sequence_no=1 fires activation (credential + capacity gates, PRD §3.3)."""
    role, uid = authenticate()
    require_role(role, uid, ("PlatformAdmin", "PracticeManager"))
    b = body()
    eid = b.get("enrollment_id")
    e = store.enrollments.get(eid) if isinstance(eid, str) else None
    if e is None:
        raise not_found("enrollment_id does not reference an existing enrollment")
    outcome = b.get("outcome")
    if outcome not in ("SUCCEEDED", "FAILED"):
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "outcome must be one of SUCCEEDED, FAILED")
    if outcome == "FAILED":
        return success(ser_enrollment(e)), 200

    installments = sorted(
        (i for i in store.installments.values() if i["enrollment_id"] == e["id"]),
        key=lambda i: i["sequence_no"])

    if e["lifecycle_status"] == "PENDING_PAYMENT":
        # Activation path (priority 6 credential gate, priority 13 capacity).
        coach = store.coaches.get(e["coach_id"])
        if (coach is None or coach["credential_status"] != "VERIFIED"
                or coach["ethics_status"] != "ACTIVE"):
            raise ApiError(ERR_COACH_NOT_CREDENTIALED, 422,
                           "Coach is not delivery-eligible (credential VERIFIED and ethics ACTIVE required)")
        active_count = sum(1 for x in store.enrollments.values()
                           if x["coach_id"] == e["coach_id"]
                           and x["lifecycle_status"] == "ACTIVE")
        if active_count >= coach["max_concurrent_clients"]:
            raise ApiError(ERR_COACH_CAPACITY_FULL, 422,
                           "Coach has reached max_concurrent_clients")
        first = installments[0]
        first["installment_status"] = "PAID"
        e["lifecycle_status"] = "ACTIVE"
        e["activated_at"] = store.clock
        # due_on resolves only at activation: first due on the activation date,
        # each later installment 30 days after its predecessor (PRD §3.3).
        activation_date = store.clock.date()
        for inst in installments:
            inst["due_on"] = activation_date + timedelta(days=(inst["sequence_no"] - 1) * 30)
        touch(e)
    elif e["payment_status"] == "DELINQUENT":
        # Settling a delinquency pays every LATE installment at once.
        for inst in installments:
            if inst["installment_status"] == "LATE":
                inst["installment_status"] = "PAID"
        e["payment_status"] = "CURRENT"
        touch(e)
    elif e["payment_status"] == "DEFAULTED":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "A DEFAULTED enrollment cannot be settled")
    else:
        # Pay the next due (lowest sequence_no) PENDING installment.
        nxt = next((i for i in installments if i["installment_status"] == "PENDING"),
                   None)
        if nxt is not None:
            nxt["installment_status"] = "PAID"
            touch(e)
    return success(ser_enrollment(e)), 200
