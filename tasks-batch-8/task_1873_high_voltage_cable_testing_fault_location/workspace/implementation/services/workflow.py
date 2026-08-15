"""Cross-entity workflow helpers: mutations, cascades and derived state."""
from decimal import Decimal

import db
import util

OPEN_ASSIGNMENT_STATES = ("RESERVED", "CONFIRMED", "ACTIVE")
TERMINAL_SERIES_STATES = ("ACCEPTED", "INVALID")
TERMINAL_JOB_STATES = ("COMPLETED", "ABORTED")
OPEN_SPLICE_STATES = ("PLANNED", "SPLICING", "CURING", "COMPLETED")


def touch(rec):
    """Every mutation refreshes updated_at (logical clock) and bumps version."""
    rec["updated_at"] = db.now()
    rec["version"] += 1


def job_of_fault(fault):
    return db.jobs.get(fault["test_job_id"])


def circuit_of_job(job):
    return db.circuits.get(job["circuit_id"])


def circuit_of_fault(fault):
    job = job_of_fault(fault)
    return circuit_of_job(job) if job else None


def faults_of_circuit(circuit_id):
    out = []
    for f in db.faults.values():
        job = job_of_fault(f)
        if job and job["circuit_id"] == circuit_id:
            out.append(f)
    return out


# ------------------------------------------------------------------ circuit derived fields
def refresh_replacement(circuit):
    band = circuit["current_health_band"]
    circuit["replacement_recommended"] = bool(
        band == "CRITICAL" or (band == "POOR" and circuit["unresolved_fault_count"] >= 2)
    )


def recompute_resolved_24m(circuit):
    cutoff = util.minus_months(db.now(), 24)
    count = 0
    for f in faults_of_circuit(circuit["id"]):
        if (
            f["status"] == "CLOSED_VERIFIED"
            and f["closed_at"] is not None
            and f["closed_at"] >= cutoff
        ):
            count += 1
    circuit["resolved_fault_count_24m"] = count


def fault_opened(circuit):
    """A fault record appears (auto on FAIL or manual on MONITOR)."""
    circuit["unresolved_fault_count"] += 1
    refresh_replacement(circuit)
    touch(circuit)


def fault_closed(fault):
    """CLOSED_VERIFIED closure cascade (PRD 3.7)."""
    fault["status"] = "CLOSED_VERIFIED"
    fault["closed_at"] = db.now()
    touch(fault)
    circuit = circuit_of_fault(fault)
    circuit["unresolved_fault_count"] -= 1
    circuit["splice_count"] += 1
    recompute_resolved_24m(circuit)
    refresh_replacement(circuit)
    touch(circuit)
    job = job_of_fault(fault)
    if job:
        maybe_auto_evaluate(job)


def fault_reopened(fault):
    fault["status"] = "REOPENED"
    fault["closed_at"] = None
    touch(fault)
    circuit = circuit_of_fault(fault)
    circuit["unresolved_fault_count"] += 1
    recompute_resolved_24m(circuit)
    refresh_replacement(circuit)
    touch(circuit)


# ------------------------------------------------------------------ job auto evaluation
def maybe_auto_evaluate(job):
    if job["status"] != "IN_PROGRESS":
        return
    slist = [s for s in db.series.values() if s["test_job_id"] == job["id"]]
    if not slist:
        return
    if any(s["status"] not in TERMINAL_SERIES_STATES for s in slist):
        return
    flist = [f for f in db.faults.values() if f["test_job_id"] == job["id"]]
    if any(f["status"] != "CLOSED_VERIFIED" for f in flist):
        return
    job["status"] = "EVALUATION"
    touch(job)
    circuit = circuit_of_job(job)
    if circuit and circuit["status"] == "UNDER_TEST":
        circuit["status"] = "TEST_COMPLETE"
        touch(circuit)


# ------------------------------------------------------------------ mobile units
def settle_unit(unit):
    """Recompute committed_hours over open assignments and derive ASSIGNED/AVAILABLE."""
    total = Decimal("0")
    open_found = False
    for a in db.assignments.values():
        if a["mobile_unit_id"] == unit["id"] and a["status"] in OPEN_ASSIGNMENT_STATES:
            total += a["duration_hours"]
            open_found = True
    unit["committed_hours"] = util.rhu(total, 1)
    if not open_found and unit["status"] == "ASSIGNED":
        unit["status"] = "AVAILABLE"
    touch(unit)


def release_assignment(a):
    a["status"] = "RELEASED"
    touch(a)
    unit = db.units.get(a["mobile_unit_id"])
    if unit:
        settle_unit(unit)


def cancel_assignment(a):
    a["status"] = "CANCELLED"
    touch(a)
    unit = db.units.get(a["mobile_unit_id"])
    if unit:
        settle_unit(unit)
