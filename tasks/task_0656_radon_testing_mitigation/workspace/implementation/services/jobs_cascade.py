"""Cross-entity cascades around MitigationJob clearing (PRD §3.5, §3.6, §3.7).

Kept in its own module to avoid an import cycle between the radon-test route and
the warranty/retest-schedule logic.
"""

from db import store, new_id, format_iso8601_millis
from services.domain import (
    _common_create_fields,
    touch,
    now_clock,
    add_days,
    recompute_property_derived,
)


def _arm_retest_schedule(warranty):
    """Warranty issuance arms a RetestSchedule (PRD §3.7). interval_days from the
    job's retest_interval_days; next_due_utc = warranty.started_at_utc + interval_days."""
    job = store.mitigation_jobs.get(warranty["mitigation_job_id"])
    interval_days = job["retest_interval_days"]
    started_dt = warranty["_started_dt"]
    next_due = add_days(started_dt, interval_days)

    sched = _common_create_fields()
    sched.update(
        {
            "warranty_id": warranty["id"],
            "property_id": warranty["property_id"],
            "interval_days": interval_days,
            "next_due_utc": format_iso8601_millis(next_due),
            "_next_due_dt": next_due,
            "last_fired_utc": None,
            "_last_fired_dt": None,
            "fired_count": 0,
            "status": "ARMED",
        }
    )
    store.retest_schedules[sched["id"]] = sched
    return sched


def _issue_warranty(job, prop):
    """Issue a Warranty snapshotting the job's after-care terms (PRD §3.5)."""
    ts = now_clock()
    warranty = _common_create_fields()
    warranty.update(
        {
            "mitigation_job_id": job["id"],
            "property_id": prop["id"],
            "covered_system_price_cents": job["quote_total_cents"],
            "term_days": job["warranty_term_days"],
            "started_at_utc": format_iso8601_millis(ts),
            "_started_dt": ts,
            "guarantee_ceiling_pci_l": job["warranty_guarantee_ceiling_pci_l"],
            "refund_method": job["warranty_refund_method"],
            "refund_paid_cents": 0,
            "coverage_status": "ACTIVE",
            "claim_status": "NONE",
        }
    )
    store.warranties[warranty["id"]] = warranty
    _arm_retest_schedule(warranty)
    return warranty


def _close_job_permit(job):
    """When a job reaches CLEARED its ISSUED permit is auto-closed (PRD §3.5)."""
    pid = job.get("permit_id")
    if not pid:
        return
    permit = store.permits.get(pid)
    if permit is not None and permit["status"] == "ISSUED":
        permit["status"] = "CLOSED"
        touch(permit)


def _resolve_claim_if_any(job):
    """If a warranty on this job has claim_status CLAIM_OPEN and the job is now
    CLEARED with retest_passed true, advance claim_status -> CLAIM_RESOLVED
    (coverage untouched) (PRD §3.6)."""
    for w in store.warranties.values():
        if w["mitigation_job_id"] != job["id"]:
            continue
        if w["claim_status"] == "CLAIM_OPEN":
            w["claim_status"] = "CLAIM_RESOLVED"
            touch(w)


def clear_job_from_retest(job, prop):
    """RETEST_PENDING -> CLEARED system transition (PRD §3.5).

    Balance is assumed already verified by the caller. Sets retest_passed, closes
    the permit, resolves an open claim, issues a fresh Warranty + RetestSchedule
    (only the first clear; a clearing that resolves a claim reuses the warranty),
    and flips property posture to CLEARED.
    """
    job["status"] = "CLEARED"
    job["retest_passed"] = True
    touch(job)

    _close_job_permit(job)

    # Does this job already have a warranty (rework following a claim)? If so, the
    # clear resolves the claim and does NOT issue a second warranty.
    existing = [w for w in store.warranties.values() if w["mitigation_job_id"] == job["id"]]
    if existing:
        _resolve_claim_if_any(job)
    else:
        _issue_warranty(job, prop)

    recompute_property_derived(prop)


def job_to_rework_from_retest(job, prop):
    """RETEST_PENDING -> REWORK system transition (PRD §3.5). Property posture
    remains MITIGATING."""
    job["status"] = "REWORK"
    touch(job)
    recompute_property_derived(prop)
