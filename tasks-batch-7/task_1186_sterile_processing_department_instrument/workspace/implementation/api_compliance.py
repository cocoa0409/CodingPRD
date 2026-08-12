"""Compliance summary and the test-driving logical clock."""
from flask import Blueprint

import domain
import store
from common import (
    ANY, CLOCK, auth, get_body, logical_now, ok, req_datetime, rhu,
)

bp = Blueprint("compliance", __name__)


@bp.get("/spd/compliance/summary")
def compliance_summary():
    auth(ANY)
    now = logical_now()
    case_start = now - domain.CASE_WINDOW

    iuss_count_7d = domain.iuss_count_7d()
    completed_cases_30d = sum(
        1 for c in store.OR_CASES.values()
        if c["status"] == "COMPLETED" and c["completed_at"] is not None
        and c["completed_at"] > case_start and c["completed_at"] <= now)
    # The scheduled denominator counts every case whose scheduled_start_at is
    # within the trailing 720h look-back, regardless of status — including
    # cases scheduled later than the current instant (the schedule book).
    scheduled_cases_30d = sum(
        1 for c in store.OR_CASES.values()
        if c["scheduled_start_at"] > case_start)
    rate_per_completed = rhu(
        domain.D(iuss_count_7d) / max(completed_cases_30d, 1), 4)
    rate_per_scheduled = rhu(
        domain.D(iuss_count_7d) / max(scheduled_cases_30d, 1), 4)
    loads_recalled_30d = sum(
        1 for l in store.STERILIZATION_LOADS.values()
        if l["status"] == "RECALLED" and l["recalled_at"] is not None
        and l["recalled_at"] > case_start and l["recalled_at"] <= now)
    trays_quarantined_count = sum(
        1 for t in store.TRAYS.values() if t["status"] == "QUARANTINED")

    return ok({
        "iuss_count_7d": iuss_count_7d,
        "completed_cases_30d": completed_cases_30d,
        "scheduled_cases_30d": scheduled_cases_30d,
        "iuss_rate_per_completed": float(rate_per_completed),
        "iuss_rate_per_scheduled": float(rate_per_scheduled),
        "loads_recalled_30d": loads_recalled_30d,
        "trays_quarantined_count": trays_quarantined_count,
    })


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    auth(("FacilityAdmin",))
    body = get_body()
    instant = req_datetime(body, "to_iso8601")
    CLOCK.set(instant)
    return ok({"current_utc": CLOCK.now()})
