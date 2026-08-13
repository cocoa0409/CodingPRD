"""SubmissionBatch routes: create, stage, seal, unseal, transmit, acknowledge, reconcile."""
import math
import re
from datetime import timezone

from flask import Blueprint, request

from db import store, new_id, now_iso
from middleware import get_auth, require_role, get_body, req_string, apply_pagination
from response import success_object, success_list
from errors import not_found, invalid_request, invalid_state, ApiError, stale_version
from services.core import (
    touch, recompute_program_posture, get_scorecard, recompute_scorecard,
    recompute_cycle_tallies,
)

bp = Blueprint("batches", __name__)

LATE_FLAT_CENTS = 500000
LATE_PER_DAY_CENTS = 100000
ACK_CODE_RE = re.compile(r"^E5[0-9]{2}_")


def batch_view(b):
    return {
        "id": b["id"],
        "created_at": b["created_at"],
        "updated_at": b["updated_at"],
        "version": b["version"],
        "cycle_id": b["cycle_id"],
        "status": b["status"],
        "encounter_count": b["encounter_count"],
        "total_paid_cents": b["total_paid_cents"],
        "sealed_encounter_count": b["sealed_encounter_count"],
        "sealed_total_paid_cents": b["sealed_total_paid_cents"],
        "sealed_by_user_id": b["sealed_by_user_id"],
        "transmitted_by_user_id": b["transmitted_by_user_id"],
        "transmitted_at": b["transmitted_at"],
        "late": b["late"],
    }


def _recompute_batch_counters(b):
    staged = [e for e in store.encounters.values() if e.get("batch_id") == b["id"]]
    b["encounter_count"] = len(staged)
    b["total_paid_cents"] = sum(e["paid_amount_cents"] for e in staged)


@bp.route("/programs/batches", methods=["POST"])
def create_batch():
    _, role = get_auth()
    require_role(role, {"McoEncounterOps"})
    body = get_body()
    cycle_id = req_string(body, "cycle_id")
    cycle = store.cycles.get(cycle_id)
    if cycle is None:
        raise not_found("cycle not found")
    if cycle["status"] != "OPEN":
        raise ApiError("ERR_CYCLE_CLOSED", "Batch create against a CLOSED cycle", 409)
    bid = new_id()
    b = {
        "id": bid,
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "version": 1,
        "cycle_id": cycle_id,
        "status": "DRAFT",
        "encounter_count": 0,
        "total_paid_cents": 0,
        "sealed_encounter_count": None,
        "sealed_total_paid_cents": None,
        "sealed_by_user_id": None,
        "transmitted_by_user_id": None,
        "transmitted_at": None,
        "late": False,
    }
    store.batches[bid] = b
    return success_object(batch_view(b), 201)


@bp.route("/programs/batches/<bid>", methods=["GET"])
def get_batch(bid):
    get_auth()
    b = store.batches.get(bid)
    if b is None:
        raise not_found()
    return success_object(batch_view(b))


@bp.route("/programs/batches", methods=["GET"])
def list_batches():
    get_auth()
    cycle_id = request.args.get("cycle_id")
    status = request.args.get("status")
    items = list(store.batches.values())
    if cycle_id is not None:
        items = [b for b in items if b["cycle_id"] == cycle_id]
    if status is not None:
        items = [b for b in items if b["status"] == status]
    page, limit, offset, total = apply_pagination(items)
    return success_list([batch_view(b) for b in page], limit, offset, total)


@bp.route("/programs/batches/<bid>/encounters", methods=["POST"])
def stage_encounter(bid):
    _, role = get_auth()
    require_role(role, {"McoEncounterOps"})
    body = get_body()
    encounter_id = req_string(body, "encounter_id")
    expected_batch_version = body.get("expected_batch_version")
    if expected_batch_version is None or isinstance(expected_batch_version, bool) or not isinstance(expected_batch_version, int):
        raise invalid_request("expected_batch_version is required and must be an integer")
    b = store.batches.get(bid)
    if b is None:
        raise not_found("batch not found")
    e = store.encounters.get(encounter_id)
    if e is None:
        raise not_found("encounter not found")
    # state preconditions
    if b["status"] != "DRAFT":
        raise ApiError("ERR_BATCH_SEALED", "Add-encounter attempted on a batch not in DRAFT", 409)
    if e["status"] != "VALIDATED" or e.get("batch_id") is not None:
        raise ApiError("ERR_ENCOUNTER_NOT_STAGEABLE",
                       "Encounter not VALIDATED or already staged", 409)
    # OCC
    if expected_batch_version != b["version"]:
        raise stale_version()
    # provider quality hold
    sc = get_scorecard(e["provider_id"], e["attributed_cycle_id"])
    if sc is not None and sc["tier"] == "RED" and sc["status"] != "ACKNOWLEDGED":
        raise ApiError("ERR_PROVIDER_QUALITY_HOLD",
                       "Provider's scorecard for the encounter's cycle is RED and remediation not acknowledged",
                       409)
    # cycle alignment
    if e["attributed_cycle_id"] != b["cycle_id"]:
        raise ApiError("ERR_CYCLE_MISMATCH",
                       "Encounter attributed_cycle_id differs from batch.cycle_id", 409)
    e["batch_id"] = b["id"]
    e["status"] = "STAGED"
    touch(e)
    _recompute_batch_counters(b)
    touch(b)
    return success_object(batch_view(b))


@bp.route("/programs/batches/<bid>/seal", methods=["POST"])
def seal_batch(bid):
    user_id, role = get_auth()
    require_role(role, {"McoEncounterOps"})
    get_body(required=False)
    b = store.batches.get(bid)
    if b is None:
        raise not_found()
    if b["status"] != "DRAFT":
        raise invalid_state("Batch is not DRAFT")
    _recompute_batch_counters(b)
    if b["encounter_count"] < 1:
        raise ApiError("ERR_EMPTY_BATCH", "Seal attempted with zero staged encounters", 409)
    b["sealed_encounter_count"] = b["encounter_count"]
    b["sealed_total_paid_cents"] = b["total_paid_cents"]
    b["sealed_by_user_id"] = user_id
    b["status"] = "SEALED"
    touch(b)
    return success_object(batch_view(b))


@bp.route("/programs/batches/<bid>/unseal", methods=["POST"])
def unseal_batch(bid):
    _, role = get_auth()
    require_role(role, {"McoEncounterOps"})
    get_body(required=False)
    b = store.batches.get(bid)
    if b is None:
        raise not_found()
    if b["status"] != "SEALED":
        raise invalid_state("Batch is not SEALED")
    b["sealed_encounter_count"] = None
    b["sealed_total_paid_cents"] = None
    b["sealed_by_user_id"] = None
    b["status"] = "DRAFT"
    touch(b)
    return success_object(batch_view(b))


@bp.route("/programs/batches/<bid>/transmit", methods=["POST"])
def transmit_batch(bid):
    user_id, role = get_auth()
    require_role(role, {"McoCompliance"})
    get_body(required=False)
    b = store.batches.get(bid)
    if b is None:
        raise not_found()
    if b["status"] != "SEALED":
        raise invalid_state("Batch is not SEALED")
    cycle = store.cycles.get(b["cycle_id"])
    if cycle is None:
        raise not_found("cycle not found")
    if cycle["status"] != "OPEN":
        raise ApiError("ERR_CYCLE_CLOSED", "Transmit against a CLOSED cycle", 409)
    program = store.programs.get(cycle["program_id"])
    if program is not None and program["posture"] == "RESTRICTED":
        raise ApiError("ERR_PROGRAM_RESTRICTED", "Program posture RESTRICTED blocks batch transmit", 409)
    if user_id == b["sealed_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "Transmitter X-User-ID equals sealed_by_user_id", 403)
    # transmit
    now = store.clock
    b["transmitted_at"] = store.clock_raw
    b["transmitted_by_user_id"] = user_id
    late = now > cycle["_effective_deadline_at"]
    b["late"] = late
    b["status"] = "TRANSMITTED"
    touch(b)
    for e in store.encounters.values():
        if e.get("batch_id") == b["id"] and e["status"] == "STAGED":
            e["status"] = "SUBMITTED"
            touch(e)
    # late penalty cascade
    if late and program is not None:
        delta_seconds = (now - cycle["_effective_deadline_at"]).total_seconds()
        days_late = math.floor(delta_seconds / 86400)
        amount = LATE_FLAT_CENTS + LATE_PER_DAY_CENTS * days_late
        pid = new_id()
        penalty = {
            "id": pid,
            "created_at": now_iso(),
            "updated_at": now_iso(),
            "version": 1,
            "program_id": program["id"],
            "cycle_id": cycle["id"],
            "audit_id": None,
            "reason": "LATE_SUBMISSION",
            "amount_cents": amount,
            "reduced_amount_cents": None,
            "status": "ASSESSED",
        }
        store.penalties[pid] = penalty
        recompute_program_posture(program)
    return success_object(batch_view(b))


@bp.route("/programs/batches/<bid>/acknowledge", methods=["POST"])
def acknowledge_batch(bid):
    _, role = get_auth()
    require_role(role, {"StateAgency"})
    body = get_body()
    outcomes = body.get("outcomes")
    if not isinstance(outcomes, list):
        raise invalid_request("outcomes must be an array")
    for o in outcomes:
        if not isinstance(o, dict):
            raise invalid_request("Each outcome must be an object")
        if "encounter_id" not in o or not isinstance(o["encounter_id"], str):
            raise invalid_request("outcome missing encounter_id")
        if o.get("outcome") not in ("ACCEPTED", "DENIED"):
            raise invalid_request("outcome must be ACCEPTED or DENIED")
    b = store.batches.get(bid)
    if b is None:
        raise not_found()
    if b["status"] != "TRANSMITTED":
        raise invalid_state("Batch is not TRANSMITTED")
    # completeness: outcomes cover each SUBMITTED encounter exactly once, no extras
    submitted = {e["id"]: e for e in store.encounters.values()
                 if e.get("batch_id") == bid and e["status"] == "SUBMITTED"}
    outcome_ids = [o["encounter_id"] for o in outcomes]
    if len(set(outcome_ids)) != len(outcome_ids):
        raise ApiError("ERR_ACK_INCOMPLETE", "Duplicate outcome for an encounter", 422)
    if set(outcome_ids) != set(submitted.keys()):
        raise ApiError("ERR_ACK_INCOMPLETE",
                       "Acknowledge outcomes do not cover each SUBMITTED encounter exactly once", 422)
    for o in outcomes:
        if o["outcome"] == "DENIED":
            code = o.get("edit_code")
            if not isinstance(code, str) or not ACK_CODE_RE.match(code):
                raise ApiError("ERR_ACK_INCOMPLETE",
                               "DENIED outcome missing well-formed E5xx edit_code", 422)

    accepted = [o for o in outcomes if o["outcome"] == "ACCEPTED"]
    denied = [o for o in outcomes if o["outcome"] == "DENIED"]

    cycle = store.cycles.get(b["cycle_id"])

    if not denied:
        # all accepted -> ACKNOWLEDGED
        for o in accepted:
            e = submitted[o["encounter_id"]]
            e["status"] = "ACKNOWLEDGED"
            touch(e)
        b["status"] = "ACKNOWLEDGED"
        touch(b)
        if cycle is not None:
            recompute_cycle_tallies(cycle)
        return success_object(batch_view(b))

    if not accepted:
        # all denied -> REJECTED_BATCH then immediately back to DRAFT; denial side effects do NOT fire
        b["status"] = "REJECTED_BATCH"
        # immediate system transition back to DRAFT
        for e in submitted.values():
            e["status"] = "VALIDATED"
            e["batch_id"] = None
            touch(e)
        b["status"] = "DRAFT"
        b["sealed_encounter_count"] = None
        b["sealed_total_paid_cents"] = None
        b["sealed_by_user_id"] = None
        _recompute_batch_counters(b)
        touch(b)
        return success_object(batch_view(b))

    # mixed -> PARTIAL
    for o in accepted:
        e = submitted[o["encounter_id"]]
        e["status"] = "ACKNOWLEDGED"
        touch(e)
    for o in denied:
        e = submitted[o["encounter_id"]]
        e["status"] = "DENIED"
        touch(e)
        # finding: tier BUSINESS, severity FATAL, origin STATE_ACK, run_seq 0
        fid = new_id()
        store.findings[fid] = {
            "id": fid,
            "created_at": now_iso(),
            "encounter_id": e["id"],
            "run_seq": 0,
            "edit_code": o["edit_code"],
            "tier": "BUSINESS",
            "severity": "FATAL",
            "origin": "STATE_ACK",
            "field_path": "encounter",
            "message": f"State acknowledgment denial: {o['edit_code']}",
        }
        # scorecard cascade: fatal += 1, run_count unchanged
        sc = None
        from services.core import ensure_scorecard
        sc = ensure_scorecard(e["provider_id"], e["attributed_cycle_id"])
        sc["fatal_finding_count"] += 1
        recompute_scorecard(sc)
    b["status"] = "PARTIAL"
    touch(b)
    if cycle is not None:
        recompute_cycle_tallies(cycle)
    return success_object(batch_view(b))


@bp.route("/programs/batches/<bid>/reconcile", methods=["POST"])
def reconcile_batch(bid):
    _, role = get_auth()
    require_role(role, {"McoEncounterOps"})
    get_body(required=False)
    b = store.batches.get(bid)
    if b is None:
        raise not_found()
    if b["status"] == "ACKNOWLEDGED":
        b["status"] = "RECONCILED"
        touch(b)
        return success_object(batch_view(b))
    if b["status"] == "PARTIAL":
        # zero remaining DENIED encounters with batch_id == this batch
        for e in store.encounters.values():
            if e.get("batch_id") == bid and e["status"] == "DENIED":
                raise ApiError("ERR_BATCH_HAS_UNRESOLVED_DENIALS",
                               "PARTIAL batch reconcile attempted while DENIED encounters remain in the batch",
                               409)
        b["status"] = "RECONCILED"
        touch(b)
        return success_object(batch_view(b))
    raise invalid_state("Batch is not ACKNOWLEDGED or PARTIAL")
