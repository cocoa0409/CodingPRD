"""Test-driving and batch surface: the logical clock and the nightly sweep."""

from flask import Blueprint

from db import db, sorted_records, touch
from middleware import require
from response import ok
from services import policy as policy_svc
from util import iso_ms, parse_date, parse_instant
from validate import body, req_instant

bp = Blueprint("ops", __name__)


@bp.post("/_clock/set_current_utc")
def set_clock():
    require("PlanAdmin")
    data = body()
    moment = req_instant(data, "to_iso8601")
    db.clock = moment
    return ok({"current_utc": iso_ms(db.clock)})


@bp.post("/sweeps/expiration")
def sweep_expiration():
    require("PlanAdmin")
    body()

    today = db.today()
    now = db.now()

    activated = 0
    expired_policies = 0
    expired_offers = 0
    withdrawn_applications = 0

    # Job 1 — future-dated binds become effective.  The territory's exposure
    # does NOT move: a BOUND policy was already counted.
    for policy in sorted_records(db.policies):
        if policy["coverage_status"] != "BOUND":
            continue
        effective = parse_date(policy["effective_date"])
        if effective is not None and effective <= today:
            policy["coverage_status"] = "IN_FORCE"
            touch(policy)
            activated += 1

    # Job 2 — terms run out.  Exposure is released, but the full term was
    # earned so there is no refund and no commission return.
    for policy in sorted_records(db.policies):
        if policy["coverage_status"] != "IN_FORCE":
            continue
        expiration = parse_date(policy["expiration_date"])
        if expiration is not None and expiration <= today:
            policy_svc.terminate(policy, "EXPIRED", None, None, with_refund=False)
            expired_policies += 1

    # Job 3 — lapsed take-out offers; strictly after the deadline instant.
    for offer in sorted_records(db.takeout_offers):
        if offer["status"] != "OUTSTANDING":
            continue
        deadline = parse_instant(offer["election_deadline_at"])
        if deadline is not None and now > deadline:
            offer["status"] = "EXPIRED"
            touch(offer)
            expired_offers += 1
            policy = db.policies.get(offer["policy_id"])
            if policy is not None and policy["depopulation_status"] == "OFFER_OUTSTANDING":
                policy["depopulation_status"] = "NOT_OFFERED"
                touch(policy)

    # Job 4 — bind windows that lapsed; strictly after the deadline instant.
    for application in sorted_records(db.applications):
        if application["status"] != "APPROVED_TO_BIND":
            continue
        deadline = parse_instant(application["bind_deadline_at"])
        if deadline is not None and now > deadline:
            application["status"] = "WITHDRAWN"
            application["eligibility_hold_reason"] = "BIND_WINDOW_LAPSED"
            touch(application)
            withdrawn_applications += 1

    return ok({
        "activated_policy_count": activated,
        "expired_policy_count": expired_policies,
        "expired_offer_count": expired_offers,
        "withdrawn_application_count": withdrawn_applications,
    })
