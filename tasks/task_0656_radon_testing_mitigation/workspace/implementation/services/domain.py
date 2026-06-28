"""Domain helpers: entity construction, system-field management, derived-field
reconciliation (Property posture, latest_result, open_test_count), and cross-entity
cascades. PRD §2.4, §2.6 and the §3 workflows.
"""

import datetime

from db import store, new_id, format_iso8601_millis
from services import calc

# Terminal states (SCAFFOLD §1.2).
RADON_TEST_TERMINAL = {"RESULT_READY", "VOIDED"}
JOB_TERMINAL = {"CLEARED", "CANCELLED"}


def now_clock():
    """Current logical-clock instant (aware UTC datetime)."""
    return store.clock_current_utc


def _common_create_fields():
    """id, created_at, updated_at, version for resources with common_fields=true
    (PRD §2.4). version begins at 1 and increments by one on every mutation."""
    ts = now_clock()
    return {
        "id": new_id(),
        "created_at": format_iso8601_millis(ts),
        "updated_at": format_iso8601_millis(ts),
        "version": 1,
        "_seq": store.next_seq(),  # internal stable ordering key
        "_created_dt": ts,  # internal aware dt (for arithmetic / tie-breaks)
    }


def touch(entity):
    """Mark a resource mutated: advance updated_at and increment version
    (PRD §2.4, §2.6). Uses the logical clock for the timestamp."""
    entity["updated_at"] = format_iso8601_millis(now_clock())
    entity["version"] = entity.get("version", 1) + 1


def add_days(dt, days):
    return dt + datetime.timedelta(days=int(days))


# ---------------------------------------------------------------------------
# Serialization — strip internal (underscore-prefixed) fields on output.
# ---------------------------------------------------------------------------
def public(entity):
    return {k: v for k, v in entity.items() if not k.startswith("_")}


# ---------------------------------------------------------------------------
# Property derived-field reconciliation (PRD §2.6, §3.1).
# ---------------------------------------------------------------------------
def _property_tests(property_id):
    return [t for t in store.radon_tests.values() if t["property_id"] == property_id]


def _property_jobs(property_id):
    return [j for j in store.mitigation_jobs.values() if j["property_id"] == property_id]


def recompute_property_derived(prop):
    """Recompute open_test_count, latest_result_pci_l, and the compound posture
    for a property, then mark it mutated. Called whenever a child test or job
    changes state (PRD §2.6).
    """
    pid = prop["id"]
    tests = _property_tests(pid)

    # open_test_count: tests not in a terminal state.
    prop["open_test_count"] = sum(
        1 for t in tests if t["status"] not in RADON_TEST_TERMINAL
    )

    # latest_result_pci_l: result of the most recent RESULT_READY test by created_at desc.
    ready = [t for t in tests if t["status"] == "RESULT_READY"]
    if ready:
        # Most recent by created_at desc; tie-break by creation seq desc.
        ready.sort(key=lambda t: (t["_created_dt"], t["_seq"]), reverse=True)
        prop["latest_result_pci_l"] = ready[0]["result_pci_l"]
    else:
        prop["latest_result_pci_l"] = None

    _recompute_posture(prop)
    touch(prop)


def _recompute_posture(prop):
    """Derive the compound posture from child tests/jobs (PRD §3.1).

    Order of resolution:
      - CLEARED   : a MitigationJob CLEARED with retest_passed true.
      - MITIGATING: a MitigationJob in {SCHEDULED, INSTALLED, RETEST_PENDING, REWORK}.
      - MITIGATION_REQUIRED: latest_result >= 4.0 and no clearing-eligible job.
      - TESTING   : open_test_count > 0.
      - CLEARED (from TESTING): latest_result < 4.0 with no non-terminal job.
      - OPEN      : nothing else.
    """
    pid = prop["id"]
    jobs = _property_jobs(pid)
    latest = prop.get("latest_result_pci_l")

    cleared_job = any(
        j["status"] == "CLEARED" and j.get("retest_passed") for j in jobs
    )
    if cleared_job:
        prop["posture"] = "CLEARED"
        return

    mitigating_job = any(
        j["status"] in {"SCHEDULED", "INSTALLED", "RETEST_PENDING", "REWORK"}
        for j in jobs
    )
    if mitigating_job:
        prop["posture"] = "MITIGATING"
        return

    non_terminal_job = any(j["status"] not in JOB_TERMINAL for j in jobs)

    if latest is not None and latest >= 4.0:
        # Action-recommended latest result, no clearing-eligible job yet.
        prop["posture"] = "MITIGATION_REQUIRED"
        return

    if prop.get("open_test_count", 0) > 0:
        prop["posture"] = "TESTING"
        return

    if latest is not None and latest < 4.0 and not non_terminal_job:
        # Initial clean read with no open jobs => directly CLEARED.
        prop["posture"] = "CLEARED"
        return

    prop["posture"] = "OPEN"


# ---------------------------------------------------------------------------
# Payment ledger recomputation (SCAFFOLD payment_ledger_balance, PRD §3.5).
# ---------------------------------------------------------------------------
def _job_payments(job_id):
    """All PaymentRecords for a job, ordered by recorded_at_utc ASC, tie-break
    created_at ASC (PRD §3.5)."""
    rows = [p for p in store.payment_records.values() if p["mitigation_job_id"] == job_id]
    rows.sort(key=lambda p: (p["_recorded_dt"], p["_created_dt"], p["_seq"]))
    return rows


def recompute_job_payments(job):
    """deposit_paid_cents = sum of DEPOSIT amounts; balance_paid_cents = sum of
    BALANCE amounts. Gating totals count only positive deposit/balance rows
    (PRD §3.5). Marks the job mutated."""
    rows = _job_payments(job["id"])
    job["deposit_paid_cents"] = sum(p["amount_cents"] for p in rows if p["kind"] == "DEPOSIT")
    job["balance_paid_cents"] = sum(p["amount_cents"] for p in rows if p["kind"] == "BALANCE")
    touch(job)


def append_payment(job, kind, amount_cents):
    """Append an append-only PaymentRecord ledger entry. PaymentRecord carries
    only id + created_at (PRD §2.4); recorded_at_utc stamped from the logical
    clock (PRD §3.5)."""
    ts = now_clock()
    record = {
        "id": new_id(),
        "created_at": format_iso8601_millis(ts),
        "mitigation_job_id": job["id"],
        "kind": kind,
        "amount_cents": amount_cents,
        "recorded_at_utc": format_iso8601_millis(ts),
        "_created_dt": ts,
        "_recorded_dt": ts,
        "_seq": store.next_seq(),
    }
    store.payment_records[record["id"]] = record
    return record
