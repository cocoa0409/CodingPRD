"""Operational sweep and the test-only logical clock."""

from flask import Blueprint

import calc
import services
from core import body, caller, db, fmt_ts, now, ok, req_datetime, sort_rows, touch

bp = Blueprint("ops", __name__)


@bp.post("/ops-run")
def ops_run():
    caller("PortalAdmin")
    datasets_recomputed = 0
    currency_transitions = 0
    staleness_alerts = 0
    triage_breached = 0
    correction_breached = 0

    participating = [
        d
        for d in sort_rows(db.datasets.values())
        if d["publication_status"] in calc.PUBLISHED_STATES
    ]

    # Step one: re-derive days_overdue and currency_status.
    for dataset in participating:
        before, after = services.recompute_currency(dataset)
        datasets_recomputed += 1
        if before != after:
            currency_transitions += 1

    # Step two: staleness alerting for datasets entering or remaining STALE/BREACHED.
    for dataset in participating:
        if dataset["currency_status"] in ("STALE", "BREACHED"):
            services.emit_staleness_alert(dataset)
            staleness_alerts += 1

    # Step three: engagement then AS_OBSERVED prioritisation.
    for dataset in participating:
        services.recompute_engagement(dataset)
        services.recompute_priority(dataset, "AS_OBSERVED")

    # Step four: SLA breach latching, in ascending created_at order.
    for issue in sort_rows(db.issues.values()):
        if issue["status"] == "SUBMITTED":
            if (
                issue["triage_due_at"] is not None
                and now() > issue["triage_due_at"]
                and not issue["triage_breached"]
            ):
                issue["triage_breached"] = True
                triage_breached += 1
                touch(issue)
        elif issue["status"] == "ACCEPTED":
            if (
                issue["correction_due_at"] is not None
                and now() > issue["correction_due_at"]
                and not issue["correction_breached"]
            ):
                issue["correction_breached"] = True
                correction_breached += 1
                touch(issue)

    # Step five: departmental posture, in ascending created_at order.
    departments_recomputed = 0
    postures_changed = 0
    for department in sort_rows(db.departments.values()):
        changed = services.recompute_department(department)
        departments_recomputed += 1
        if changed:
            postures_changed += 1

    return ok(
        {
            "datasets_recomputed": datasets_recomputed,
            "currency_transitions": currency_transitions,
            "staleness_alerts_emitted": staleness_alerts,
            "issues_triage_breached": triage_breached,
            "issues_correction_breached": correction_breached,
            "departments_recomputed": departments_recomputed,
            "postures_changed": postures_changed,
        }
    )


@bp.post("/_clock/set_current_utc")
def set_clock():
    caller("PortalAdmin")
    data = body()
    moment = req_datetime(data, "to_iso8601")
    db.logical_now = moment
    return ok({"current_utc": fmt_ts(db.logical_now)})
