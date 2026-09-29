"""Recovery operations: booking, cross-clamp and cancellation."""

from datetime import timedelta

from flask import Blueprint, request

from constants import OPERATION_STATUSES, THORACIC_TYPES
from db import base_record, clock_now, db, lock, ordered
from errors import ApiError
from middleware import authenticate
from response import ok, paginated
from services.calculations import floor_minutes
from services.domain import (
    operations_of_case,
    organs_of_case,
    refresh_organ_counters,
    refresh_team_ledger,
    set_allocation_status,
    touch,
)
from validation import Body, json_body, page, pagination

bp = Blueprint("recovery", __name__)


def resolve_case(case_id):
    record = db.donor_cases.get(case_id)
    if record is None:
        raise ApiError("ERR_DONOR_CASE_NOT_FOUND")
    return record


def resolve_operation(operation_id):
    record = db.recovery_operations.get(operation_id)
    if record is None:
        raise ApiError("ERR_OPERATION_NOT_FOUND")
    return record


def specialty_covers(specialty, organ_types):
    for organ_type in organ_types:
        if specialty == "MULTIORGAN":
            continue
        if specialty == "THORACIC" and organ_type in THORACIC_TYPES:
            continue
        if specialty == "ABDOMINAL" and organ_type not in THORACIC_TYPES:
            continue
        return False
    return True


@bp.post("/opo/donor-cases/<case_id>/recovery-operations")
def book_recovery_operation(case_id):
    authenticate("RecoveryLogistics")
    with lock:
        case = resolve_case(case_id)
        raw = json_body()
        if not isinstance(raw, dict):
            raise ApiError("ERR_INVALID_REQUEST", "The request body must be a JSON object.")

        supplied_team = raw.get("recovery_team_id")
        if supplied_team is not None:
            if not isinstance(supplied_team, str) or supplied_team not in db.recovery_teams:
                raise ApiError("ERR_TEAM_NOT_FOUND")

        body = Body(raw)
        team_id = body.string("recovery_team_id", required=True)
        or_start_at = body.instant("or_start_at", required=True)
        or_end_at = body.instant("or_end_at", required=True)

        if case["case_posture"] == "FROZEN":
            raise ApiError("ERR_CASE_FROZEN")
        if or_end_at <= or_start_at:
            raise ApiError("ERR_INVALID_TIME_WINDOW")

        team = db.recovery_teams[team_id]
        accepted = [o for o in organs_of_case(case_id) if o["status"] == "ACCEPTED"]
        accepted_types = [o["organ_type"] for o in accepted]
        if not specialty_covers(team["specialty"], accepted_types):
            raise ApiError("ERR_TEAM_SPECIALTY_MISMATCH")
        if not accepted:
            raise ApiError("ERR_NO_ACCEPTED_ORGANS")

        buffer_minutes = timedelta(minutes=team["turnaround_buffer_minutes"])
        for other in db.recovery_operations.values():
            if other["recovery_team_id"] != team_id:
                continue
            if other["status"] not in ("SCHEDULED", "COMPLETED"):
                continue
            if (
                or_start_at < other["or_end_at"] + buffer_minutes
                and other["or_start_at"] < or_end_at + buffer_minutes
            ):
                raise ApiError("ERR_TEAM_WINDOW_CONFLICT")

        record = base_record()
        record.update(
            {
                "donor_case_id": case_id,
                "recovery_team_id": team_id,
                "or_start_at": or_start_at,
                "or_end_at": or_end_at,
                "or_minutes": floor_minutes(or_end_at, or_start_at),
                "status": "SCHEDULED",
                "cross_clamp_at": None,
                "organ_types_covered": accepted_types,
                "cancelled_reason": None,
            }
        )
        db.recovery_operations[record["id"]] = record
        refresh_team_ledger(team)
        return ok(record, 201)


@bp.get("/opo/recovery-operations/<operation_id>")
def read_recovery_operation(operation_id):
    authenticate("OpoAdmin", "RecoveryLogistics", "MedicalDirector", "DonorCoordinator")
    with lock:
        return ok(resolve_operation(operation_id))


@bp.get("/opo/recovery-operations")
def list_recovery_operations():
    authenticate("OpoAdmin", "RecoveryLogistics", "MedicalDirector")
    with lock:
        limit, offset = pagination()
        case_id = request.args.get("donor_case_id")
        team_id = request.args.get("recovery_team_id")
        status = request.args.get("status")
        rows = list(db.recovery_operations.values())
        if case_id is not None:
            rows = [r for r in rows if r["donor_case_id"] == case_id]
        if team_id is not None:
            rows = [r for r in rows if r["recovery_team_id"] == team_id]
        if status is not None:
            rows = [r for r in rows if r["status"] == status and status in OPERATION_STATUSES]
        rows = ordered(rows)
        return paginated(page(rows, limit, offset), limit, offset, len(rows))


@bp.post("/opo/recovery-operations/<operation_id>/cross-clamp")
def record_cross_clamp(operation_id):
    authenticate("RecoveryLogistics")
    with lock:
        operation = resolve_operation(operation_id)
        Body()
        if operation["status"] != "SCHEDULED":
            raise ApiError("ERR_OPERATION_NOT_SCHEDULED")

        case = db.donor_cases.get(operation["donor_case_id"])
        if case is not None and case["case_posture"] == "FROZEN":
            raise ApiError("ERR_CASE_FROZEN")

        accepted = [o for o in organs_of_case(operation["donor_case_id"]) if o["status"] == "ACCEPTED"]
        if not accepted:
            raise ApiError("ERR_NO_ACCEPTED_ORGANS")

        cross_clamp_at = clock_now()
        operation["status"] = "COMPLETED"
        operation["cross_clamp_at"] = cross_clamp_at
        touch(operation)

        team = db.recovery_teams.get(operation["recovery_team_id"])
        if team is not None:
            refresh_team_ledger(team)

        for organ in accepted:
            organ["status"] = "RECOVERED"
            organ["cross_clamp_at"] = cross_clamp_at
            touch(organ)

        if case is not None:
            refresh_organ_counters(case)
            if case["allocation_status"] == "ALLOCATED":
                set_allocation_status(case, "RECOVERED")
        return ok(operation)


@bp.post("/opo/recovery-operations/<operation_id>/cancel")
def cancel_recovery_operation(operation_id):
    authenticate("RecoveryLogistics")
    with lock:
        operation = resolve_operation(operation_id)
        Body()
        if operation["status"] != "SCHEDULED":
            raise ApiError("ERR_OPERATION_NOT_SCHEDULED")

        operation["status"] = "CANCELLED"
        operation["cancelled_reason"] = "LOGISTICS_WITHDRAWN"
        touch(operation)
        team = db.recovery_teams.get(operation["recovery_team_id"])
        if team is not None:
            refresh_team_ledger(team)
        return ok(operation)


# `operations_of_case` participates in the cascade helpers; re-exported for clarity.
__all__ = ["bp", "operations_of_case"]
