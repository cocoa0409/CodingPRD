"""Server-initiated transitions, compensations and version bookkeeping (PRD 2.9).

A mutating request snapshots every existing record's observable rendering before
the handler runs.  After the handler (and after the posture-edge cascade), any
record whose rendering changed — including changes that only touch derived
fields — has its ``updated_at`` refreshed and its ``version`` incremented by
exactly 1.  Records created during the request stay at version 1.
"""
import json

import clock
import config
import derive
from db import db

_state = {"snapshot": None, "postures": None, "forced": set(), "active": False}


def _fingerprint(record):
    data = derive.render(record)
    data.pop("version", None)
    data.pop("updated_at", None)
    return json.dumps(data, sort_keys=True, default=str)


def begin_request():
    snapshot = {}
    for record in db.all_records():
        if "version" not in record:
            continue
        snapshot[record["id"]] = _fingerprint(record)
    postures = {}
    for unit in db.units.values():
        postures[unit["id"]] = derive.unit_posture(unit)
    _state["snapshot"] = snapshot
    _state["postures"] = postures
    _state["forced"] = set()
    _state["active"] = True


def force_bump(record):
    """Record an explicit version increment even when nothing observable moved."""
    if _state["active"]:
        _state["forced"].add(record["id"])


def finalize():
    if not _state["active"]:
        return
    apply_posture_edges()
    stamp = clock.now()
    snapshot = _state["snapshot"] or {}
    forced = _state["forced"]
    for record in list(db.all_records()):
        if "version" not in record:
            continue
        previous = snapshot.get(record["id"])
        if previous is None:
            continue
        if record["id"] in forced or _fingerprint(record) != previous:
            record["version"] += 1
            record["updated_at"] = stamp
    _state["snapshot"] = None
    _state["postures"] = None
    _state["forced"] = set()
    _state["active"] = False


def abort_request():
    _state["snapshot"] = None
    _state["postures"] = None
    _state["forced"] = set()
    _state["active"] = False


# --- posture edge cascade -------------------------------------------------

def apply_posture_edges():
    """Block / unblock queued packages as a unit crosses the storage lock."""
    previous = _state["postures"] or {}
    for unit in list(db.units.values()):
        before = previous.get(unit["id"])
        if before is None:
            continue
        after = derive.unit_posture(unit)
        if before != "STORAGE_LOCKED" and after == "STORAGE_LOCKED":
            block_unit_packages(unit)
        elif before == "STORAGE_LOCKED" and after != "STORAGE_LOCKED":
            release_unit_packages(unit)


def block_unit_packages(unit):
    for package in derive.packages_of_unit(unit["id"]):
        if package["status"] == "QUEUED":
            package["status"] = "BLOCKED"
            package["blocked_reason"] = config.BLOCK_REASON_UNIT


def release_unit_packages(unit):
    for package in derive.packages_of_unit(unit["id"]):
        if (package["status"] == "BLOCKED"
                and package.get("blocked_reason") == config.BLOCK_REASON_UNIT):
            package["status"] = "QUEUED"
            package["blocked_reason"] = None


# --- capture target reconciliation ---------------------------------------

def reconcile_admission_capture(admission):
    """PRD 3.6 / 3.7: the ADMITTED <-> CAPTURE_TARGET_MET pair and its taper cascade."""
    if admission is None:
        return
    index = derive.admission_capture(admission)["capture_adequacy_index"]
    if admission["clinical_state"] == "ADMITTED" and index >= derive.ONE:
        admission["clinical_state"] = "CAPTURE_TARGET_MET"
        for plan in derive.taper_plans_of_admission(admission["id"]):
            if plan["status"] in ("ACTIVE", "HELD"):
                plan["status"] = "COMPLETED"
    elif admission["clinical_state"] == "CAPTURE_TARGET_MET" and index < derive.ONE:
        admission["clinical_state"] = "ADMITTED"
        for plan in derive.taper_plans_of_admission(admission["id"]):
            if plan["status"] == "COMPLETED" and plan["current_step"] < plan["total_steps"]:
                plan["status"] = "ACTIVE"


def reconcile_admission_for_study(study):
    reconcile_admission_capture(db.admissions.get(study["admission_id"]))


def reconcile_admission_for_marking(marking):
    study = db.studies.get(marking["study_id"])
    if study is not None:
        reconcile_admission_for_study(study)
