"""CasePosting endpoints."""

from decimal import Decimal

from flask import Blueprint, request as freq

from db import db
from errors import (
    ApiError,
    ERR_BLOCK_NOT_ACTIVE,
    ERR_BLOCK_NOT_FOUND,
    ERR_BLOCK_SERVICE_MISMATCH,
    ERR_CASE_DOES_NOT_FIT,
    ERR_CASE_NOT_BUMPED,
    ERR_CASE_NOT_FOUND,
    ERR_CASE_NOT_IN_PROGRESS,
    ERR_CASE_NOT_SCHEDULABLE,
    ERR_CASE_NOT_SCHEDULED,
    ERR_EMERGENT_WINDOW_BLOCKED,
    ERR_INVALID_REQUEST,
    ERR_INVALID_TIME_RANGE,
    ERR_NO_ANESTHESIA_COVERAGE,
    ERR_NOT_RESOURCE_OWNER,
    ERR_ROOM_NOT_FOUND,
    ERR_SURGEON_DOUBLE_BOOKED,
    ERR_SURGEON_NOT_FOUND,
)
from middleware import get_auth, require_roles, get_json_body
from response import success_object, paginate
from serializers import case_json, first_case_of_room_day
from services import (
    BENCHMARK,
    new_common,
    touch,
    turnover_for,
    scheduled_cases_of_block,
    pack_positions,
    recompute_block_metrics,
    repack_block,
    anesthesia_covers,
    surgeon_double_booked,
    recompute_surgeon_scorecard,
    bump_case,
)
from util import is_int, parse_date, round_half_up_int

bp = Blueprint("cases", __name__)

CASE_STATUSES = {"POSTED", "SCHEDULED", "BUMPED", "IN_PROGRESS", "COMPLETED", "CANCELLED"}
PROCEDURE_CLASSES = {"MINOR", "STANDARD", "COMPLEX"}
PRIORITIES = {"ELECTIVE", "ADD_ON", "EMERGENT"}


@bp.route("/cases", methods=["POST"])
def create_case():
    auth = require_roles("Surgeon")
    body = get_json_body()
    surgeon_id = body.get("surgeon_id")
    # ownership (priority 3): posting a case requires surgeon_id == X-User-ID
    if isinstance(surgeon_id, str) and surgeon_id != auth.user_id:
        raise ApiError(
            ERR_NOT_RESOURCE_OWNER, 403, "a surgeon may only post their own cases"
        )
    # existence (priority 4): body FK surgeon
    if isinstance(surgeon_id, str) and surgeon_id not in db.surgeons:
        raise ApiError(ERR_SURGEON_NOT_FOUND, 404, "surgeon not found")
    # shape (priority 5)
    if not isinstance(surgeon_id, str) or not surgeon_id:
        raise ApiError(ERR_INVALID_REQUEST, 400, "surgeon_id is required")
    procedure_class = body.get("procedure_class")
    if procedure_class not in PROCEDURE_CLASSES:
        raise ApiError(ERR_INVALID_REQUEST, 400, "invalid procedure_class")
    priority = body.get("priority")
    if priority not in PRIORITIES:
        raise ApiError(ERR_INVALID_REQUEST, 400, "invalid priority")
    patient_ref = body.get("patient_ref")
    if patient_ref is not None and not isinstance(patient_ref, str):
        raise ApiError(ERR_INVALID_REQUEST, 400, "patient_ref must be a string")

    surgeon = db.surgeons[surgeon_id]
    benchmark = BENCHMARK[procedure_class]
    predicted = round_half_up_int(
        Decimal(benchmark) * Decimal(str(surgeon["duration_bias_factor"]))
    )
    rec = new_common()
    rec.update(
        {
            "surgeon_id": surgeon_id,
            "block_id": None,
            "or_id": None,
            "date": None,
            "patient_ref": patient_ref,
            "procedure_class": procedure_class,
            "priority": priority,
            "benchmark_duration_minutes": benchmark,
            "predicted_duration_minutes": predicted,
            "turnover_minutes": None,
            "scheduled_start_minute": None,
            "scheduled_end_minute": None,
            "actual_start_minute": None,
            "actual_end_minute": None,
            "first_case_delay_minutes": None,
            "status": "POSTED",
        }
    )
    db.cases[rec["id"]] = rec
    return success_object(case_json(rec), 201)


@bp.route("/cases", methods=["GET"])
def list_cases():
    get_auth()
    items = list(db.cases.values())
    surgeon_id = freq.args.get("surgeon_id")
    if surgeon_id is not None:
        items = [c for c in items if c["surgeon_id"] == surgeon_id]
    block_id = freq.args.get("block_id")
    if block_id is not None:
        items = [c for c in items if c.get("block_id") == block_id]
    or_id = freq.args.get("or_id")
    if or_id is not None:
        items = [c for c in items if c.get("or_id") == or_id]
    dt = freq.args.get("date")
    if dt is not None:
        items = [c for c in items if c.get("date") == dt]
    st = freq.args.get("status")
    if st is not None:
        if st not in CASE_STATUSES:
            raise ApiError(ERR_INVALID_REQUEST, 400, "invalid status filter")
        items = [c for c in items if c["status"] == st]
    pr = freq.args.get("priority")
    if pr is not None:
        if pr not in PRIORITIES:
            raise ApiError(ERR_INVALID_REQUEST, 400, "invalid priority filter")
        items = [c for c in items if c["priority"] == pr]
    out = [case_json(c) for c in items]
    out.sort(key=lambda r: (r["created_at"],))
    return paginate(out)


@bp.route("/cases/<caseId>", methods=["GET"])
def get_case(caseId):
    get_auth()
    rec = db.cases.get(caseId)
    if rec is None:
        raise ApiError(ERR_CASE_NOT_FOUND, 404, "case not found")
    return success_object(case_json(rec))


# ---------------------------------------------------------------------------
# scheduling
# ---------------------------------------------------------------------------

def _check_alignment(block, case):
    surgeon = db.surgeons[case["surgeon_id"]]
    if block.get("surgeon_id") is not None:
        if block["surgeon_id"] != case["surgeon_id"]:
            raise ApiError(
                ERR_BLOCK_SERVICE_MISMATCH,
                409,
                "case surgeon does not match the block's surgeon",
            )
    else:
        if surgeon["service_line_id"] != block["service_line_id"]:
            raise ApiError(
                ERR_BLOCK_SERVICE_MISMATCH,
                409,
                "case surgeon's service line differs from the block's",
            )


def _schedule_into_block(case, block):
    """Shared logic for schedule (POSTED) and reschedule (BUMPED) block path.

    Validation order per PRD §3.4: anesthesia -> block state -> fit ->
    double-booking -> alignment.
    """
    room = db.rooms[block["or_id"]]
    turnover = turnover_for(case["procedure_class"], room)

    # packed position: new case appended after the last SCHEDULED case's
    # actual end (bumped cases leave gaps; the sequence is not repacked here)
    existing = scheduled_cases_of_block(block["id"])
    if existing:
        last_end = existing[-1]["scheduled_end_minute"]
        start = last_end + turnover
    else:
        start = block["start_minute"]
    end = start + case["predicted_duration_minutes"]

    # anesthesia: coverage must span [start, end + turnover)
    if not anesthesia_covers(block["or_id"], block["date"], start, end + turnover):
        raise ApiError(
            ERR_NO_ANESTHESIA_COVERAGE,
            409,
            "no ACTIVE anesthesia coverage spans the case including its turnover gap",
        )
    # state: block must be ACTIVE
    if block["status"] != "ACTIVE":
        raise ApiError(
            ERR_BLOCK_NOT_ACTIVE, 409, "block scheduling requires block status ACTIVE"
        )
    # fit
    if end > block["end_minute"]:
        raise ApiError(
            ERR_CASE_DOES_NOT_FIT, 409, "packed end exceeds the block end_minute"
        )
    # surgeon padded double-booking across all rooms on the date
    if surgeon_double_booked(
        case["surgeon_id"], block["date"], start, end + turnover,
        exclude_case_id=case["id"],
    ):
        raise ApiError(
            ERR_SURGEON_DOUBLE_BOOKED,
            409,
            "surgeon has another SCHEDULED case whose padded interval intersects",
        )
    # alignment
    _check_alignment(block, case)

    # commit
    case["block_id"] = block["id"]
    case["or_id"] = block["or_id"]
    case["date"] = block["date"]
    case["turnover_minutes"] = turnover
    case["scheduled_start_minute"] = start
    case["scheduled_end_minute"] = end
    case["status"] = "SCHEDULED"
    case["_sched_seq"] = db.next_sched_seq()
    touch(case)
    recompute_block_metrics(block)
    touch(block)


def _schedule_emergent(case, or_id, date, desired_start):
    room = db.rooms[or_id]
    turnover = turnover_for(case["procedure_class"], room)
    start = desired_start
    end = start + case["predicted_duration_minutes"]

    # anesthesia first among business checks
    if not anesthesia_covers(or_id, date, start, end + turnover):
        raise ApiError(
            ERR_NO_ANESTHESIA_COVERAGE,
            409,
            "no ACTIVE anesthesia coverage spans the case including its turnover gap",
        )
    # surgeon padded double-booking
    if surgeon_double_booked(
        case["surgeon_id"], date, start, end + turnover, exclude_case_id=case["id"]
    ):
        raise ApiError(
            ERR_SURGEON_DOUBLE_BOOKED,
            409,
            "surgeon has another SCHEDULED case whose padded interval intersects",
        )
    # emergent window resolution: at most one bump frees the window
    intersecting = []
    for c in db.cases.values():
        if c["id"] == case["id"]:
            continue
        if c.get("or_id") != or_id or c.get("date") != date:
            continue
        if c["status"] not in ("SCHEDULED", "IN_PROGRESS"):
            continue
        if start < c["scheduled_end_minute"] and c["scheduled_start_minute"] < end:
            intersecting.append(c)
    victim = None
    if intersecting:
        if len(intersecting) > 1:
            raise ApiError(
                ERR_EMERGENT_WINDOW_BLOCKED,
                409,
                "multiple cases intersect the emergent window",
            )
        cand = intersecting[0]
        if cand["status"] == "IN_PROGRESS" or cand["priority"] == "EMERGENT":
            raise ApiError(
                ERR_EMERGENT_WINDOW_BLOCKED,
                409,
                "emergent window cannot be freed by a single bump",
            )
        victim = cand

    # commit (atomic: all checks passed)
    if victim is not None:
        old_block_id = victim.get("block_id")
        bump_case(victim)
        if old_block_id and old_block_id in db.blocks:
            vblock = db.blocks[old_block_id]
            recompute_block_metrics(vblock)
            touch(vblock)
    case["block_id"] = None
    case["or_id"] = or_id
    case["date"] = date
    case["turnover_minutes"] = turnover
    case["scheduled_start_minute"] = start
    case["scheduled_end_minute"] = end
    case["status"] = "SCHEDULED"
    case["_sched_seq"] = db.next_sched_seq()
    touch(case)


@bp.route("/cases/<caseId>/schedule", methods=["POST"])
def schedule_case(caseId):
    auth = require_roles("Surgeon")
    case = db.cases.get(caseId)
    if case is None:
        raise ApiError(ERR_CASE_NOT_FOUND, 404, "case not found")
    if case["surgeon_id"] != auth.user_id:
        raise ApiError(
            ERR_NOT_RESOURCE_OWNER, 403, "a surgeon may only schedule their own cases"
        )
    body = get_json_body()
    block_id = body.get("block_id")
    or_id = body.get("or_id")
    date = body.get("date")
    desired = body.get("desired_start_minute")

    is_block_path = case["priority"] in ("ELECTIVE", "ADD_ON")
    # body FK existence in declared order (block_id, or_id) — priority 4,
    # before request-shape checks (priority 5)
    if isinstance(block_id, str) and block_id and block_id not in db.blocks:
        raise ApiError(ERR_BLOCK_NOT_FOUND, 404, "block not found")
    if isinstance(or_id, str) and or_id and or_id not in db.rooms:
        raise ApiError(ERR_ROOM_NOT_FOUND, 404, "operating room not found")

    # shape: payload combination must match the priority's scheduling mode
    if is_block_path:
        if not isinstance(block_id, str) or not block_id:
            raise ApiError(
                ERR_INVALID_REQUEST,
                400,
                "ELECTIVE/ADD_ON scheduling requires block_id",
            )
    else:
        if not isinstance(or_id, str) or not or_id:
            raise ApiError(
                ERR_INVALID_REQUEST,
                400,
                "EMERGENT scheduling requires or_id, date, desired_start_minute",
            )
        try:
            parse_date(date)
        except (ValueError, TypeError):
            raise ApiError(ERR_INVALID_REQUEST, 400, "date must be YYYY-MM-DD")
        if not is_int(desired) or not (0 <= desired <= 1440):
            raise ApiError(
                ERR_INVALID_REQUEST,
                400,
                "desired_start_minute must be an integer in [0,1440]",
            )

    # state: case must be POSTED
    if case["status"] != "POSTED":
        raise ApiError(
            ERR_CASE_NOT_SCHEDULABLE, 409, "schedule requires case status POSTED"
        )

    if is_block_path:
        _schedule_into_block(case, db.blocks[block_id])
    else:
        _schedule_emergent(case, or_id, date, desired)
    return success_object(case_json(case))


@bp.route("/cases/<caseId>/reschedule", methods=["POST"])
def reschedule_case(caseId):
    auth = require_roles("Surgeon")
    case = db.cases.get(caseId)
    if case is None:
        raise ApiError(ERR_CASE_NOT_FOUND, 404, "case not found")
    if case["surgeon_id"] != auth.user_id:
        raise ApiError(
            ERR_NOT_RESOURCE_OWNER, 403, "a surgeon may only reschedule their own cases"
        )
    body = get_json_body()
    block_id = body.get("block_id")
    if isinstance(block_id, str) and block_id not in db.blocks:
        raise ApiError(ERR_BLOCK_NOT_FOUND, 404, "block not found")
    if not isinstance(block_id, str) or not block_id:
        raise ApiError(ERR_INVALID_REQUEST, 400, "block_id is required")
    if case["status"] != "BUMPED":
        raise ApiError(
            ERR_CASE_NOT_BUMPED, 409, "reschedule requires case status BUMPED"
        )
    _schedule_into_block(case, db.blocks[block_id])
    return success_object(case_json(case))


@bp.route("/cases/<caseId>/start", methods=["POST"])
def start_case(caseId):
    require_roles("CirculatorNurse")
    case = db.cases.get(caseId)
    if case is None:
        raise ApiError(ERR_CASE_NOT_FOUND, 404, "case not found")
    body = get_json_body()
    actual_start = body.get("actual_start_minute")
    if not is_int(actual_start) or not (0 <= actual_start <= 1440):
        raise ApiError(
            ERR_INVALID_REQUEST,
            400,
            "actual_start_minute is required and must be an integer in [0,1440]",
        )
    if case["status"] != "SCHEDULED":
        raise ApiError(
            ERR_CASE_NOT_SCHEDULED, 409, "start requires case status SCHEDULED"
        )
    case["actual_start_minute"] = actual_start
    case["status"] = "IN_PROGRESS"
    # first-case-of-room-day delay
    first = first_case_of_room_day(case["or_id"], case["date"])
    is_first = first is not None and first["id"] == case["id"]
    if is_first and case["first_case_delay_minutes"] is None:
        case["first_case_delay_minutes"] = max(
            0, actual_start - case["scheduled_start_minute"]
        )
    touch(case)
    if is_first:
        surgeon = db.surgeons.get(case["surgeon_id"])
        if surgeon is not None:
            recompute_surgeon_scorecard(surgeon)
            touch(surgeon)
    return success_object(case_json(case))


@bp.route("/cases/<caseId>/complete", methods=["POST"])
def complete_case(caseId):
    require_roles("CirculatorNurse")
    case = db.cases.get(caseId)
    if case is None:
        raise ApiError(ERR_CASE_NOT_FOUND, 404, "case not found")
    body = get_json_body()
    actual_end = body.get("actual_end_minute")
    if not is_int(actual_end) or not (0 <= actual_end <= 1440):
        raise ApiError(
            ERR_INVALID_REQUEST,
            400,
            "actual_end_minute is required and must be an integer in [0,1440]",
        )
    if case["status"] != "IN_PROGRESS":
        raise ApiError(
            ERR_CASE_NOT_IN_PROGRESS, 409, "complete requires case status IN_PROGRESS"
        )
    if actual_end <= case["actual_start_minute"]:
        raise ApiError(
            ERR_INVALID_TIME_RANGE,
            400,
            "actual_end_minute must be strictly after actual_start_minute",
        )
    case["actual_end_minute"] = actual_end
    case["status"] = "COMPLETED"
    touch(case)
    surgeon = db.surgeons.get(case["surgeon_id"])
    if surgeon is not None:
        recompute_surgeon_scorecard(surgeon)
        touch(surgeon)
    return success_object(case_json(case))


@bp.route("/cases/<caseId>/cancel", methods=["POST"])
def cancel_case(caseId):
    auth = require_roles("Surgeon")
    case = db.cases.get(caseId)
    if case is None:
        raise ApiError(ERR_CASE_NOT_FOUND, 404, "case not found")
    if case["surgeon_id"] != auth.user_id:
        raise ApiError(
            ERR_NOT_RESOURCE_OWNER, 403, "a surgeon may only cancel their own cases"
        )
    if case["status"] not in ("POSTED", "SCHEDULED", "BUMPED"):
        raise ApiError(
            ERR_CASE_NOT_SCHEDULABLE,
            409,
            "cancel requires case status POSTED, SCHEDULED, or BUMPED",
        )
    if case["status"] == "SCHEDULED":
        block_id = case.get("block_id")
        case["status"] = "CANCELLED"
        touch(case)
        if block_id and block_id in db.blocks:
            block = db.blocks[block_id]
            repack_block(block)
            recompute_block_metrics(block)
            touch(block)
    else:
        case["status"] = "CANCELLED"
        touch(case)
    return success_object(case_json(case))
