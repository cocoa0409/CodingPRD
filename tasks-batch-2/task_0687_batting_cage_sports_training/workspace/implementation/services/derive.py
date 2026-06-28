"""Derived-field computation and cascade recompute helpers.

These functions compute the server-maintained derived fields described in PRD
2.7 / 3.3 / 3.6 / 2.6 and the corresponding SCAFFOLD calculations:
  - lane_maint_status
  - facility_posture / open_incident_count
  - machine_status
  - member.waiver_ok
  - program enrolled_count / status

They mutate the stored dicts in place and bump version/updated_at when a value
actually changes (PRD 2.7: every mutation incl. cascades refreshes updated_at
and bumps version).
"""
from datetime import timezone

from clock import clock
from constants import CLOSE_THRESHOLD, DEGRADE_AT, OOS_AT
from db import db, iso_ts


def touch(entity):
    """Refresh updated_at and bump version on a mutated resource (PRD 2.7).

    Waivers are immutable and have no updated_at/version, so they are never
    passed here.
    """
    entity["updated_at"] = iso_ts(clock.now())
    entity["version"] = entity.get("version", 0) + 1


# ---------------------------------------------------------------------------
# Lane maint_status (PRD 3.3 / calc lane_maint_status)
# ---------------------------------------------------------------------------
def compute_lane_maint_status(lane_id):
    open_windows = [
        w for w in db.maintenance.values()
        if w["lane_id"] == lane_id and w["status"] == "OPEN"
    ]
    if any(w["severity"] == "CRITICAL" for w in open_windows):
        return "CLOSED"
    if any(w["severity"] == "ROUTINE" for w in open_windows):
        return "UNDER_MAINTENANCE"
    return "AVAILABLE"


def recompute_lane(lane):
    """Recompute lane.maint_status; bump version if it changed."""
    new_status = compute_lane_maint_status(lane["id"])
    if lane["maint_status"] != new_status:
        lane["maint_status"] = new_status
        touch(lane)
    return lane


# ---------------------------------------------------------------------------
# Facility posture (PRD 3.3 / calc facility_posture)
# ---------------------------------------------------------------------------
def compute_open_incident_count(facility_id):
    return sum(
        1 for lane in db.lanes.values()
        if lane["facility_id"] == facility_id and lane["maint_status"] == "CLOSED"
    )


def compute_posture(open_incident_count):
    if open_incident_count >= CLOSE_THRESHOLD:
        return "CLOSED"
    if open_incident_count >= 1:
        return "RESTRICTED"
    return "OPEN"


def recompute_facility(facility):
    """Recompute open_incident_count + posture; bump version if changed."""
    count = compute_open_incident_count(facility["id"])
    posture = compute_posture(count)
    if facility["open_incident_count"] != count or facility["posture"] != posture:
        facility["open_incident_count"] = count
        facility["posture"] = posture
        touch(facility)
    return facility


# ---------------------------------------------------------------------------
# Machine status (PRD 3.6 / calc machine_status)
# ---------------------------------------------------------------------------
def compute_machine_status(pitch_count):
    if pitch_count >= OOS_AT:
        return "OUT_OF_SERVICE"
    if pitch_count >= DEGRADE_AT:
        return "DEGRADED"
    return "OPERATIONAL"


def recompute_machine(machine):
    new_status = compute_machine_status(machine["pitch_count"])
    if machine["status"] != new_status:
        machine["status"] = new_status
        touch(machine)
    return machine


def machine_on_lane(lane_id):
    for m in db.machines.values():
        if m["lane_id"] == lane_id:
            return m
    return None


# ---------------------------------------------------------------------------
# Member waiver_ok (PRD 3.2 / calc waiver_validity)
# ---------------------------------------------------------------------------
def compute_waiver_ok(member_id):
    signed = [
        w for w in db.waivers.values()
        if w["member_id"] == member_id and w["status"] == "SIGNED"
    ]
    if not signed:
        return False
    # latest by greatest signed_at, tie-break greatest created_at, no id tie-break.
    latest = max(signed, key=lambda w: (w["signed_at"], w["created_at"]))
    return clock.now() < _parse_stored(latest["expires_at"])


def recompute_member_waiver(member):
    new_ok = compute_waiver_ok(member["id"])
    if member["waiver_ok"] != new_ok:
        member["waiver_ok"] = new_ok
        touch(member)
    return member


def _parse_stored(iso_str):
    from clock import parse_iso
    return parse_iso(iso_str)


# ---------------------------------------------------------------------------
# Program enrolled_count / status (PRD 3.8 / calc program_enrollment_ledger)
# ---------------------------------------------------------------------------
def compute_enrolled_count(program_id):
    return sum(
        1 for e in db.enrollments.values()
        if e["program_id"] == program_id and e["status"] == "ENROLLED"
    )


def recompute_program(program):
    """Recompute enrolled_count; derive OPEN/FULL (CLOSED is sticky / explicit).

    PRD 3.8: status is FULL when enrolled_count == capacity, CLOSED when a
    manager has explicitly closed it, OPEN otherwise. CLOSED is set only by the
    close endpoint and is not overridden here.
    """
    count = compute_enrolled_count(program["id"])
    changed = False
    if program["enrolled_count"] != count:
        program["enrolled_count"] = count
        changed = True
    if program["status"] != "CLOSED":
        new_status = "FULL" if count == program["capacity"] else "OPEN"
        if program["status"] != new_status:
            program["status"] = new_status
            changed = True
    if changed:
        touch(program)
    return program
