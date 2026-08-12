"""Test-driving / ops endpoints: logical clock, daily sweep, backlog summary."""
from datetime import timedelta

from flask import Blueprint

import db
import response
from middleware import ALL_ROLES, authn, authz, get_body
from services.core import backlog_summary
from util import iso_z, req_dt, touch

bp = Blueprint("ops", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    body = get_body()
    target = req_dt(body, "to_iso8601")
    _, role = authn()
    authz(role, ["ComplianceAdmin"])
    db.set_now(target)
    return response.success({"current_utc": iso_z(db.now())}, status=200)


@bp.route("/ops/jobs/daily-compliance-sweep", methods=["POST"])
def daily_sweep():
    _, role = authn()
    authz(role, ["ComplianceAdmin"])
    now = db.now()

    alerts_closed = 0
    for alert in db.alerts.values():
        if alert["status"] not in {"NEW", "UNDER_TRIAGE"}:
            continue
        scenario = db.scenarios.get(alert["scenario_id"])
        stale_days = scenario["stale_alert_days"] if scenario else 30
        if now - alert["created_at"] > timedelta(days=stale_days):
            alert["status"] = "AUTO_CLOSED"
            alert["closure_reason"] = "STALE_EXPIRY"
            touch(alert)
            alerts_closed += 1

    reviews_overdue = 0
    for review in db.reviews.values():
        if review["status"] == "SCHEDULED" and review["due_at"] < now:
            review["status"] = "OVERDUE"
            touch(review)
            reviews_overdue += 1

    shares_expired = 0
    for share in db.shares.values():
        if (share["status"] == "SENT" and share["sent_at"] is not None
                and share["sent_at"] + timedelta(days=30) < now):
            share["status"] = "EXPIRED"
            touch(share)
            shares_expired += 1

    return response.success({
        "alerts_auto_closed": alerts_closed,
        "reviews_marked_overdue": reviews_overdue,
        "shares_expired": shares_expired,
    }, status=200)


@bp.route("/backlog/summary", methods=["GET"])
def backlog():
    _, role = authn()
    authz(role, ALL_ROLES)
    return response.success(backlog_summary(), status=200)
