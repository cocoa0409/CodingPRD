"""Cross-entity helpers for encounter completion / void cascades."""

from db import db
from services.common import touch


def issued_clearance_for(encounter_id):
    """Return the ISSUED clearance for an encounter, or None."""
    for cl in db.clearances.values():
        if cl["encounter_id"] == encounter_id and cl["status"] == "ISSUED":
            return cl
    return None


def any_clearance_for(encounter_id):
    """Return the most recently created clearance for an encounter, or None."""
    found = None
    for cl in db.clearances.values():
        if cl["encounter_id"] == encounter_id:
            if found is None or cl["_seq_create"] > found["_seq_create"]:
                found = cl
    return found


def hire_status_from_determination(determination):
    if determination == "FIT":
        return "CLEARED"
    if determination == "FIT_WITH_RESTRICTIONS":
        return "CLEARED"
    if determination == "NOT_FIT":
        return "DISQUALIFIED"
    return None


def apply_clearance_to_worker(worker, clearance):
    """Cascade hire_status from a clearance determination, recording provenance so
    a later rescission can revert it."""
    new_status = hire_status_from_determination(clearance["determination"])
    if new_status is None:
        return
    worker["hire_status"] = new_status
    worker["_hire_status_source_clearance_id"] = clearance["id"]
    touch(worker)


def revert_worker_if_set_from(worker, clearance_id):
    """Revert hire_status to CANDIDATE iff it was set from this clearance."""
    if worker is None:
        return
    if worker.get("_hire_status_source_clearance_id") == clearance_id:
        worker["hire_status"] = "CANDIDATE"
        worker["_hire_status_source_clearance_id"] = None
        touch(worker)
