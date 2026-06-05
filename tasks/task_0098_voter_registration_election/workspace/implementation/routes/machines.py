"""VotingMachine + MachineFailure endpoints (PRD §3.6, §3.9, §2.8)."""

from flask import Blueprint, g, request

import db
from errors import (
    APIError, invalid_request, not_found, invalid_state, stale_version,
)
import errors as E
from middleware import require_roles
from response import ok_object, ok_array
from services import serialize
from services.common import get_json_body, require_fields, paginate

bp = Blueprint("machines", __name__)

MACHINE_ROLES = {"PRIMARY", "BACKUP"}
# Machine lifecycle targets driven via /transition.
MACHINE_TARGETS = {"OPERATIONAL", "REPLACED", "RETIRED"}


@bp.route("/voting-machines", methods=["POST"])
def create_machine():
    require_roles("ElectionAdmin")
    body = get_json_body()
    require_fields(body, "precinct_id", "serial", "capacity")
    precinct = db.precincts.get(body["precinct_id"])
    if precinct is None:
        raise not_found("Precinct not found.")
    if not isinstance(body["serial"], str) or not body["serial"].strip():
        raise invalid_request("serial must be a non-empty string.")
    role = body.get("role", "PRIMARY")
    if role is None:
        role = "PRIMARY"
    if role not in MACHINE_ROLES:
        raise invalid_request("role out of range.")
    cap = body["capacity"]
    if isinstance(cap, bool) or not isinstance(cap, int):
        raise invalid_request("capacity must be an integer.")
    if cap < 1:
        raise invalid_request("capacity must be >= 1.")

    row = {
        "precinct_id": body["precinct_id"],
        "serial": body["serial"],
        "role": role,
        "status": "OPERATIONAL",
        "backup_for_machine_id": None,
        "capacity": cap,
    }
    db.stamp_create_full(row)
    db.machines[row["id"]] = row
    return ok_object(serialize.machine_view(row), 201)


@bp.route("/voting-machines/<mid>", methods=["GET"])
def get_machine(mid):
    require_roles("ElectionAdmin", "PollWorker")
    m = db.machines.get(mid)
    if m is None:
        raise not_found("Voting machine not found.")
    return ok_object(serialize.machine_view(m))


@bp.route("/voting-machines", methods=["GET"])
def list_machines():
    require_roles("ElectionAdmin", "PollWorker")
    precinct_id = request.args.get("precinct_id")
    backup_for = request.args.get("backup_for_machine_id")
    status = request.args.get("status")
    role = request.args.get("role")
    rows = list(db.machines.values())
    if precinct_id is not None:
        rows = [r for r in rows if r["precinct_id"] == precinct_id]
    if backup_for is not None:
        rows = [r for r in rows if r.get("backup_for_machine_id") == backup_for]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if role is not None:
        rows = [r for r in rows if r["role"] == role]
    page, limit, offset, total, has_more = paginate(rows)
    return ok_array([serialize.machine_view(r) for r in page],
                    limit=limit, offset=offset, total_count=total, has_more=has_more)


@bp.route("/voting-machines/<mid>/transition", methods=["POST"])
def transition_machine(mid):
    require_roles("PollWorker", "ElectionAdmin")
    m = db.machines.get(mid)
    if m is None:
        raise not_found("Voting machine not found.")
    body = get_json_body()
    require_fields(body, "target_status")
    target = body["target_status"]
    if target not in MACHINE_TARGETS:
        raise invalid_request("Unknown target_status.")

    cur = m["status"]

    if target == "OPERATIONAL":
        # Repair: FAILED -> OPERATIONAL.
        if cur != "FAILED":
            raise invalid_state("Machine is not FAILED.")
        # Compensating: release a backup currently covering this machine.
        for other in db.machines.values():
            if other.get("backup_for_machine_id") == mid:
                other["backup_for_machine_id"] = None
                db.stamp_update(other)
        m["status"] = "OPERATIONAL"
        db.stamp_update(m)
        return ok_object(serialize.machine_view(m))

    if target == "REPLACED":
        if cur != "FAILED":
            raise invalid_state("Machine is not FAILED.")
        m["status"] = "REPLACED"
        db.stamp_update(m)
        return ok_object(serialize.machine_view(m))

    if target == "RETIRED":
        if cur not in ("OPERATIONAL", "FAILED", "REPLACED"):
            raise invalid_state("Machine cannot be retired from its current state.")
        # Retire guard: not the active backup of a still-FAILED machine.
        if m.get("backup_for_machine_id"):
            covered = db.machines.get(m["backup_for_machine_id"])
            if covered is not None and covered["status"] == "FAILED":
                raise APIError(E.ERR_BACKUP_IN_USE,
                               "Machine is the active backup of a FAILED machine.", 409)
        m["status"] = "RETIRED"
        db.stamp_update(m)
        return ok_object(serialize.machine_view(m))

    raise invalid_request("Unsupported target_status.")


def _select_backup(failed):
    """Backup selector (PRD §3.9). Returns the chosen backup or None."""
    candidates = [
        x for x in db.machines.values()
        if x["precinct_id"] == failed["precinct_id"]
        and x["role"] == "BACKUP"
        and x["status"] == "OPERATIONAL"
        and x.get("backup_for_machine_id") is None
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda x: (
        -x["capacity"],                 # highest throughput first
        x.get("created_at", ""),        # oldest
        x.get("id", ""),
    ))
    return candidates[0]


@bp.route("/machine-failures", methods=["POST"])
def report_failure():
    require_roles("PollWorker")
    body = get_json_body()
    require_fields(body, "machine_id", "expected_machine_version")
    machine = db.machines.get(body["machine_id"])
    if machine is None:
        raise not_found("Voting machine not found.")
    ev = body["expected_machine_version"]
    if isinstance(ev, bool) or not isinstance(ev, int):
        raise invalid_request("expected_machine_version must be an integer.")

    # State (priority 4): OPERATIONAL + PRIMARY.
    if machine["status"] != "OPERATIONAL" or machine["role"] != "PRIMARY":
        raise invalid_state("Machine is not an OPERATIONAL PRIMARY.")

    # OCC (priority 19).
    if ev != machine["version"]:
        raise stale_version("Machine version is stale.")

    backup = _select_backup(machine)

    failure = {
        "machine_id": machine["id"],
        "reported_at": db.current_utc_iso(),
        "backup_machine_id": backup["id"] if backup else None,
        "resolution": "BACKUP_ACTIVATED" if backup else "NO_BACKUP_AVAILABLE",
    }
    db.stamp_create_light(failure)
    db.machine_failures[failure["id"]] = failure

    machine["status"] = "FAILED"
    db.stamp_update(machine)
    if backup is not None:
        backup["backup_for_machine_id"] = machine["id"]
        db.stamp_update(backup)

    return ok_object(serialize.failure_view(failure), 201)


@bp.route("/machine-failures/<fid>", methods=["GET"])
def get_failure(fid):
    require_roles("ElectionAdmin", "PollWorker")
    f = db.machine_failures.get(fid)
    if f is None:
        raise not_found("Machine failure not found.")
    return ok_object(serialize.failure_view(f))


@bp.route("/machine-failures", methods=["GET"])
def list_failures():
    require_roles("ElectionAdmin", "PollWorker")
    machine_id = request.args.get("machine_id")
    backup_machine_id = request.args.get("backup_machine_id")
    rows = list(db.machine_failures.values())
    if machine_id is not None:
        rows = [r for r in rows if r["machine_id"] == machine_id]
    if backup_machine_id is not None:
        rows = [r for r in rows if r.get("backup_machine_id") == backup_machine_id]
    page, limit, offset, total, has_more = paginate(rows)
    return ok_array([serialize.failure_view(r) for r in page],
                    limit=limit, offset=offset, total_count=total, has_more=has_more)
