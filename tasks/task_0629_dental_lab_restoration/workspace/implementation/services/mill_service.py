"""MillJob and MillMachine state machines (scaffold §1.2, PRD §3.4)."""
from datetime import timedelta

import db
import errors
import lookups
from errors import err


def create_mill_job(unit, machine, start_at, duration_minutes):
    """POST /mill-jobs (PRD §3.4). Capability + double-booking checks."""
    material = db.materials[db.restorations[unit["restoration_id"]]["material_id"]]

    # ERR_MACHINE_CAPABILITY_MISMATCH (priority 9).
    if machine["capability"] != material["fabrication_process"]:
        raise err(errors.ERR_MACHINE_CAPABILITY_MISMATCH,
                  "Machine capability does not match material fabrication process.")

    end_at = start_at + timedelta(minutes=duration_minutes)

    # ERR_MACHINE_DOUBLE_BOOKED (priority 12): half-open [start, end) intersection
    # with any non-CANCELLED job on the same machine. Touch end-to-end is fine.
    for j in lookups.machine_mill_jobs(machine["id"]):
        if j["status"] == "CANCELLED":
            continue
        if start_at < j["end_at"] and j["start_at"] < end_at:
            raise err(errors.ERR_MACHINE_DOUBLE_BOOKED,
                      "Mill job interval intersects an existing job on the machine.")

    job = db.stamp_create({
        "id": db.new_id(),
        "fabrication_unit_id": unit["id"],
        "mill_machine_id": machine["id"],
        "start_at": start_at,
        "duration_minutes": duration_minutes,
        "end_at": end_at,
        "status": "SCHEDULED",
    })
    db.mill_jobs[job["id"]] = job
    return job


def start_job(job, expected_machine_version):
    """POST /mill-jobs/{id}/start — SCHEDULED -> RUNNING; unit QUEUED -> MILLING (PRD §3.4).

    OCC on MillMachine.version. Validation order: state then OCC then business.
    """
    if job["status"] != "SCHEDULED":
        raise err(errors.ERR_INVALID_STATE, "Mill job is not SCHEDULED.")

    machine = db.mill_machines[job["mill_machine_id"]]

    # OCC (priority 7) — checked before the AVAILABLE business-safety precondition.
    if expected_machine_version != machine["version"]:
        raise err(errors.ERR_STALE_MACHINE_VERSION, "expected_machine_version is stale.")

    # Precondition: machine status AVAILABLE.
    if machine["status"] != "AVAILABLE":
        raise err(errors.ERR_INVALID_STATE, "Mill machine is not AVAILABLE.")

    job["status"] = "RUNNING"
    db.touch(job)

    unit = db.fabrication_units[job["fabrication_unit_id"]]
    unit["status"] = "MILLING"
    db.touch(unit)

    db.touch(machine)  # bump MillMachine.version
    return job


def complete_job(job):
    """POST /mill-jobs/{id}/complete — RUNNING -> DONE; unit MILLING -> MILLED (PRD §3.4)."""
    if job["status"] != "RUNNING":
        raise err(errors.ERR_INVALID_STATE, "Mill job is not RUNNING.")

    job["status"] = "DONE"
    db.touch(job)

    unit = db.fabrication_units[job["fabrication_unit_id"]]
    unit["status"] = "MILLED"
    db.touch(unit)
    return job


def cancel_job(job):
    """POST /mill-jobs/{id}/cancel — SCHEDULED -> CANCELLED; free interval (PRD §3.4)."""
    if job["status"] != "SCHEDULED":
        raise err(errors.ERR_INVALID_STATE, "Mill job is not SCHEDULED.")

    job["status"] = "CANCELLED"
    db.touch(job)
    return job


def machine_maintenance(machine):
    """POST /mill-machines/{id}/maintenance — AVAILABLE -> MAINTENANCE (PRD §3.4)."""
    if machine["status"] != "AVAILABLE":
        raise err(errors.ERR_INVALID_STATE, "Machine is not AVAILABLE.")

    # Precondition: no mill job on this machine is currently RUNNING.
    for j in lookups.machine_mill_jobs(machine["id"]):
        if j["status"] == "RUNNING":
            raise err(errors.ERR_INVALID_STATE, "Machine has a RUNNING job.")

    machine["status"] = "MAINTENANCE"
    db.touch(machine)
    return machine


def machine_release(machine):
    """POST /mill-machines/{id}/release — MAINTENANCE -> AVAILABLE (PRD §3.4)."""
    if machine["status"] != "MAINTENANCE":
        raise err(errors.ERR_INVALID_STATE, "Machine is not in MAINTENANCE.")

    machine["status"] = "AVAILABLE"
    db.touch(machine)
    return machine
