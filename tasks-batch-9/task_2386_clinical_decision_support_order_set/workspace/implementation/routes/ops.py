"""Operational capabilities: the expiration sweep, deterministic firing ingest and
the logical clock (PRD §3.7, §3.9)."""
from datetime import timedelta

from flask import Blueprint

import const
import validate
from common import base_record, touch
from db import db
from errors import ApiError
from middleware import authenticate, get_alert
from response import created, ok
from services import domain, sweep

bp = Blueprint("ops", __name__)


# ------------------------------------------------------------------ expiration sweep
@bp.post("/cds/_ops/run-expiration-sweep")
def run_expiration_sweep():
    authenticate((const.SYSTEM_ADMIN, "CommitteeChair"))
    data = validate.body()
    dry_run = validate.boolean(data, "dry_run", default=False)

    if dry_run:
        snapshot = db.snapshot()
        try:
            result = sweep.run_sweep()
        finally:
            db.restore(snapshot)
    else:
        result = sweep.run_sweep()

    return ok(result)


# ------------------------------------------------------------------ firing ingest
@bp.post("/_events/alert-firings")
def ingest_alert_firings():
    authenticate((const.SYSTEM_ADMIN,))
    data = validate.body()

    alert = None
    if isinstance(data.get("alert_id"), str):
        alert = get_alert(data["alert_id"])

    alert_id = validate.string(data, "alert_id", required=True)
    fired_at_start = validate.instant(data, "fired_at_start", required=True)
    interval_seconds = validate.integer(data, "interval_seconds", required=True, minimum=0)
    fire_count = validate.integer(data, "fire_count", required=True, minimum=0)
    override_count = validate.integer(data, "override_count", required=True, minimum=0)
    distinct_clinician_count = validate.integer(
        data, "distinct_clinician_count", required=True, minimum=0
    )
    override_reason_code = validate.string(data, "override_reason_code")

    if alert is None:
        alert = get_alert(alert_id)

    if override_count > fire_count:
        raise ApiError("ERR_INVALID_REQUEST", "override_count may not exceed fire_count")

    if alert["override_reason_required"] and override_count > 0:
        declared = alert["override_reason_codes"] or []
        if not override_reason_code or override_reason_code not in declared:
            raise ApiError(
                "ERR_OVERRIDE_REASON_REQUIRED",
                "An overridden firing must carry a declared override_reason_code",
            )

    distinct = distinct_clinician_count if distinct_clinician_count > 0 else 1
    first_fired_at = None
    last_fired_at = None

    for index in range(fire_count):
        fired_at = fired_at_start + timedelta(seconds=interval_seconds * index)
        accepted = index >= override_count
        # PRD §2.4: an OverrideEvent firing record is an append-only observation
        # carrying only `id` and `created_at` — no `updated_at`, no `version`.
        event = base_record(with_version=False)
        event.update({
            "alert_id": alert["id"],
            "firing_clinician_ref": "SYN-%03d" % ((index % distinct) + 1),
            "fired_at": fired_at,
            "accepted": accepted,
            "override_reason_code": None if accepted else override_reason_code,
            "severity_tier_snapshot": alert["severity_tier"],
            "ingest_batch_seq": index,
        })
        db.override_events[event["id"]] = event
        if first_fired_at is None:
            first_fired_at = fired_at
        last_fired_at = fired_at

    alert["lifetime_fire_count"] += fire_count
    domain.recompute_override_ledger(alert)
    domain.recompute_alert_ledger(alert)
    touch(alert)

    return created({
        "alert_id": alert["id"],
        "created_event_count": fire_count,
        "first_fired_at": first_fired_at,
        "last_fired_at": last_fired_at,
        "override_event_count": override_count,
        "distinct_clinician_count": distinct_clinician_count,
    })


# ------------------------------------------------------------------ logical clock
@bp.post("/_clock/set_current_utc")
def set_current_utc():
    authenticate((const.SYSTEM_ADMIN,))
    data = validate.body()
    target = validate.instant(data, "to_iso8601", required=True)
    db.clock = target
    return ok({"current_utc": target})
