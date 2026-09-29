"""Compliance runs (PRD §3.9). Four ordered phases; disposal always spans two runs."""
from flask import Blueprint

import calculations as calc
from constants import ROLE_COMPLIANCE_OFFICER, ROLE_PRIVACY_ENGINEER
from db import db, now, touch
from helpers import bump_service, resolve_body_fk
from middleware import authenticate, body
from response import ok

bp = Blueprint("compliance_runs", __name__)


def _service_records(service_id):
    rows = [r for r in db.child_data_records.values() if r["service_id"] == service_id]
    rows.sort(key=lambda r: (r["collected_at"], r["created_at"], r["_seq"]))
    return rows


@bp.post("/compliance-runs")
@authenticate(ROLE_COMPLIANCE_OFFICER, ROLE_PRIVACY_ENGINEER)
def create_run():
    data = body()
    service = resolve_body_fk("service", data, "service_id")

    # The run's sequence number is the newly advanced value.
    service["compliance_run_sequence"] += 1
    run_sequence = service["compliance_run_sequence"]
    current = now()

    # phase 1 — expire stale consents
    expired_consent_count = 0
    for consent in db.consent_requests.values():
        if consent["service_id"] != service["id"]:
            continue
        if consent["status"] not in ("NOTICE_DELIVERED", "PENDING_VERIFICATION"):
            continue
        deadline = consent["verification_deadline_at"]
        if deadline is not None and current >= deadline:
            consent["status"] = "EXPIRED"
            touch(consent)
            expired_consent_count += 1

    records = _service_records(service["id"])

    # phase 2 — schedule due records (still held, so no counter change)
    scheduled_count = 0
    for record in records:
        if record["status"] != "COLLECTED":
            continue
        if current >= record["disposal_due_at"]:
            record["status"] = "SCHEDULED_FOR_DISPOSAL"
            record["scheduled_run_sequence"] = run_sequence
            touch(record)
            scheduled_count += 1

    # phase 3 — destroy only what an EARLIER run scheduled
    disposed_count = 0
    for record in records:
        if record["status"] != "SCHEDULED_FOR_DISPOSAL":
            continue
        scheduled_at = record["scheduled_run_sequence"]
        if scheduled_at is not None and scheduled_at < run_sequence:
            record["status"] = "DISPOSED"
            record["disposed_at"] = current
            touch(record)
            disposed_count += 1

    # phase 4 — counters and posture are derived, so they refresh implicitly
    bump_service(service)

    return ok(
        {
            "service_id": service["id"],
            "run_sequence": run_sequence,
            "expired_consent_count": expired_consent_count,
            "scheduled_count": scheduled_count,
            "disposed_count": disposed_count,
            "live_child_data_element_count_after": calc.live_child_data_element_count(
                service["id"]
            ),
            "compliance_posture_after": calc.compliance_posture(service),
        }
    )
