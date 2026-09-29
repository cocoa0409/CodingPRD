"""Violation remedies: cure, dispute and dispute decision (PRD §3.7)."""

from flask import Blueprint

import lookup
from auth import (
    ROLE_BRAND_CHANNEL_MANAGER, ROLE_RESELLER, STAFF_AND_RESELLER, authenticate, require_owner,
)
from calc import latest_non_rescinded_notice
from cascade import rescind_latest_notice, strip_assessed_points
from envelope import ok, ok_list
from errors import fail
from store import days, dt_of, fmt, now_dt, serialize, touch
from validate import body, req_hash, req_int, req_str, req_enum

bp = Blueprint("violations", __name__)

DISPUTE_ROUND_CAP = 2
REJECTED_DISPUTE_EXTENSION_DAYS = 5
DISPUTE_DECISIONS = ["REJECT", "SUSTAIN"]


@bp.post("/violations/<violation_id>/cure-submission")
def cure_submission(violation_id):
    ctx = authenticate([ROLE_RESELLER])
    b = body()
    req_str(b, "cure_evidence_url", 1, None)
    req_int(b, "corrected_price_cents", 0, None)
    req_hash(b, "evidence_hash")
    violation = lookup.violation(violation_id)
    require_owner(ctx, violation, reseller_field="reseller_id")
    if violation["status"] != "NOTICED":
        fail("ERR_INVALID_STATE", "Only a NOTICED violation may be cured.")
    deadline = dt_of(violation, "cure_deadline_at")
    if deadline is None or now_dt() > deadline:
        fail("ERR_CURE_WINDOW_EXPIRED", "The cure window has closed.")

    violation["status"] = "CURED"
    violation["resolution_reason"] = "CURE_ACCEPTED"
    touch(violation)

    notice = latest_non_rescinded_notice(violation["id"])
    if notice is not None and notice["status"] in ("ISSUED", "ACKNOWLEDGED"):
        notice["status"] = "SATISFIED"
        notice["closed_reason"] = "VIOLATION_CURED"
        touch(notice)
    return ok(serialize(violation))


@bp.post("/violations/<violation_id>/dispute")
def dispute(violation_id):
    ctx = authenticate([ROLE_RESELLER])
    b = body()
    dispute_reason = req_str(b, "dispute_reason", 1, None)
    violation = lookup.violation(violation_id)
    require_owner(ctx, violation, reseller_field="reseller_id")
    if violation["status"] != "NOTICED":
        fail("ERR_INVALID_STATE", "Only a NOTICED violation may be disputed.")
    if violation["dispute_rounds"] >= DISPUTE_ROUND_CAP:
        fail("ERR_DISPUTE_ROUNDS_EXHAUSTED", "The right to dispute has been exhausted.")

    violation["status"] = "DISPUTED"
    violation["dispute_reason"] = dispute_reason
    touch(violation)
    return ok(serialize(violation))


@bp.post("/violations/<violation_id>/dispute-decision")
def dispute_decision(violation_id):
    authenticate([ROLE_BRAND_CHANNEL_MANAGER])
    b = body()
    decision = req_enum(b, "decision", DISPUTE_DECISIONS)
    req_str(b, "decision_reason", 1, None)
    violation = lookup.violation(violation_id)
    if violation["status"] != "DISPUTED":
        fail("ERR_INVALID_STATE", "Only a DISPUTED violation may receive a dispute decision.")

    if decision == "REJECT":
        violation["status"] = "NOTICED"
        violation["dispute_rounds"] = violation["dispute_rounds"] + 1
        deadline = dt_of(violation, "cure_deadline_at")
        if deadline is not None:
            violation["cure_deadline_at"] = fmt(deadline + days(REJECTED_DISPUTE_EXTENSION_DAYS))
        violation["resolution_reason"] = None
        touch(violation)
    else:
        violation["status"] = "VOIDED"
        violation["resolution_reason"] = "DISPUTE_SUSTAINED"
        strip_assessed_points(violation)
        rescind_latest_notice(violation, "DISPUTE_SUSTAINED")
        touch(violation)
    return ok(serialize(violation))


@bp.get("/violations/<violation_id>")
def read_violation(violation_id):
    ctx = authenticate(STAFF_AND_RESELLER)
    row = lookup.violation(violation_id)
    require_owner(ctx, row, reseller_field="reseller_id")
    return ok(serialize(row))


@bp.get("/violations")
def list_violations():
    authenticate(STAFF_AND_RESELLER)
    rows = lookup.filtered("violations", {
        "observation_id": "observation_id",
        "reseller_id": "reseller_id",
        "cited_policy_id": "cited_policy_id",
        "status": "status",
    })
    return ok_list(rows)
