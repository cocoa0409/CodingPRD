"""Surgical case drafting, block holds, confirmation, recovery and cancellation."""
from datetime import timedelta

from flask import Blueprint

from db import clock_dt, clock_str, db, new_record, ordered, touch
from errors import ApiError
from middleware import actor_id, authorize
from routes.helpers import ALL_ROLES, scope_check, send, send_list
from services.domain import (ANESTHESIA_LEVELS, CANCELLATION_REASONS,
                             CLEARANCE_STATUSES, DRILL_COMPLIANCE_FLOOR,
                             PROCEDURE_CATEGORIES, RECOVERY_MINUTES_BY_LEVEL,
                             REFERRAL_CATEGORIES, SCHEDULING_STATUSES,
                             VOIDABLE_EVALUATION_STATUSES, evaluations_of_case,
                             get_block, get_case, get_practice, open_permit,
                             path_row, referenced_row, reservations_of_case)
from services.inventory import release_reservation
from services.practice import (recompute_consignment, refresh_permit_ratio,
                               touch_practice)
from services.scheduling import (duration_minutes, intervals_overlap,
                                 monitor_double_booked, permit_rank_sufficient,
                                 privilege_admits, recompute_block,
                                 recovery_capacity_exceeded,
                                 room_turnover_conflict, staffing_unmet,
                                 touch_block)
from timeutil import parse_date
from validation import (q_enum, q_string, read_body, v_enum, v_id, v_instant,
                        v_int, v_string)

bp = Blueprint("cases", __name__)


def _referral_status(procedure_category, referring_npi):
    if procedure_category in REFERRAL_CATEGORIES and referring_npi:
        return "PENDING"
    return "NOT_REQUIRED"


def _closes_cycle(case_id, predecessor_id):
    """Walk outward from the proposed predecessor; a hit on case_id is a cycle."""
    seen = set()
    cursor = predecessor_id
    while cursor:
        if cursor == case_id:
            return True
        if cursor in seen:
            return False
        seen.add(cursor)
        row = get_case(cursor)
        if row is None:
            return False
        cursor = row.get("prerequisite_case_id")
    return False


@bp.post("/surgical-cases")
def create_case():
    authorize("SchedulingCoordinator")
    body = read_body(
        required=("practice_id", "patient_id", "primary_surgeon_id",
                  "planned_anesthesia_level", "procedure_category",
                  "planned_start", "planned_end", "total_charge_cents"),
        optional=("monitor_staff_id", "block_id", "prerequisite_case_id",
                  "referring_provider_npi"),
    )
    practice_id = v_id(body, "practice_id")
    patient_id = v_id(body, "patient_id")
    primary_surgeon_id = v_id(body, "primary_surgeon_id")
    level = v_enum(body, "planned_anesthesia_level", ANESTHESIA_LEVELS)
    category = v_enum(body, "procedure_category", PROCEDURE_CATEGORIES)
    planned_start = v_instant(body, "planned_start")
    planned_end = v_instant(body, "planned_end")
    total_charge_cents = v_int(body, "total_charge_cents", minimum=0)
    monitor_staff_id = v_id(body, "monitor_staff_id", default=None)
    block_id = v_id(body, "block_id", default=None)
    prerequisite_case_id = v_id(body, "prerequisite_case_id", default=None)
    referring_provider_npi = v_string(body, "referring_provider_npi", min_len=1,
                                      max_len=32, default=None)
    if parse_date(planned_end) <= parse_date(planned_start):
        raise ApiError("ERR_INVALID_FIELD_VALUE",
                       "Field 'planned_end' must be strictly later than 'planned_start'.")

    practice = referenced_row(db.practices, practice_id)
    patient = referenced_row(db.patients, patient_id)
    surgeon = referenced_row(db.staff, primary_surgeon_id)
    monitor = referenced_row(db.staff, monitor_staff_id) if monitor_staff_id else None
    block = referenced_row(db.blocks, block_id) if block_id else None
    predecessor = (referenced_row(db.cases, prerequisite_case_id)
                   if prerequisite_case_id else None)

    scope_check(patient["practice_id"], practice_id)
    scope_check(surgeon["practice_id"], practice_id)
    if monitor is not None:
        scope_check(monitor["practice_id"], practice_id)
    if block is not None:
        scope_check(block["practice_id"], practice_id)

    if surgeon["role_type"] != "SURGEON":
        raise ApiError("ERR_INVALID_FIELD_VALUE",
                       "Field 'primary_surgeon_id' must reference a staff member whose role_type is SURGEON.")

    case = new_record({
        "practice_id": practice_id,
        "patient_id": patient_id,
        "primary_surgeon_id": primary_surgeon_id,
        "monitor_staff_id": monitor_staff_id,
        "block_id": block_id,
        "prerequisite_case_id": prerequisite_case_id,
        "procedure_category": category,
        "planned_anesthesia_level": level,
        "planned_start": planned_start,
        "planned_end": planned_end,
        "total_charge_cents": total_charge_cents,
        "referring_provider_npi": referring_provider_npi,
        "duration_minutes": duration_minutes(planned_start, planned_end),
        "scheduling_status": "DRAFT",
        "clearance_status": "NOT_EVALUATED",
        "referral_coordination_status": _referral_status(category, referring_provider_npi),
        "recovery_minutes_required": RECOVERY_MINUTES_BY_LEVEL[level],
        "recovery_started_at": None,
        "cancellation_reason": None,
    })
    if predecessor is not None and _closes_cycle(case["id"], prerequisite_case_id):
        raise ApiError("ERR_PREREQUISITE_CYCLE")
    db.cases[case["id"]] = case
    return send(case, 201)


@bp.get("/surgical-cases/<case_id>")
def read_case(case_id):
    authorize(*ALL_ROLES)
    return send(path_row(db.cases, case_id))


@bp.get("/surgical-cases")
def list_cases():
    authorize(*ALL_ROLES)
    practice_id = q_string("practice_id")
    patient_id = q_string("patient_id")
    surgeon_id = q_string("primary_surgeon_id")
    monitor_id = q_string("monitor_staff_id")
    block_id = q_string("block_id")
    prerequisite_case_id = q_string("prerequisite_case_id")
    scheduling_status = q_enum("scheduling_status", SCHEDULING_STATUSES)
    clearance_status = q_enum("clearance_status", CLEARANCE_STATUSES)
    rows = []
    for case in db.cases.values():
        if practice_id is not None and case["practice_id"] != practice_id:
            continue
        if patient_id is not None and case["patient_id"] != patient_id:
            continue
        if surgeon_id is not None and case["primary_surgeon_id"] != surgeon_id:
            continue
        if monitor_id is not None and case.get("monitor_staff_id") != monitor_id:
            continue
        if block_id is not None and case.get("block_id") != block_id:
            continue
        if prerequisite_case_id is not None and case.get("prerequisite_case_id") != prerequisite_case_id:
            continue
        if scheduling_status is not None and case["scheduling_status"] != scheduling_status:
            continue
        if clearance_status is not None and case["clearance_status"] != clearance_status:
            continue
        rows.append(case)
    return send_list(ordered(rows))


@bp.post("/surgical-cases/<case_id>/hold-block")
def hold_block(case_id):
    authorize("SchedulingCoordinator")
    case = path_row(db.cases, case_id)
    body = read_body(required=("block_id",))
    block_id = v_id(body, "block_id")
    block = referenced_row(db.blocks, block_id)
    practice = get_practice(case["practice_id"])

    if case["scheduling_status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    if not privilege_admits(practice["sedation_privilege_state"],
                            case["planned_anesthesia_level"]):
        raise ApiError("ERR_SEDATION_PRIVILEGE_UNAVAILABLE")
    scope_check(block["practice_id"], case["practice_id"])
    if block["status"] == "RELEASED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    if not (parse_date(block["block_start"]) <= parse_date(case["planned_start"])
            and parse_date(case["planned_end"]) <= parse_date(block["block_end"])):
        raise ApiError("ERR_CASE_OUTSIDE_BLOCK_WINDOW")
    if block["surgeon_id"] != case["primary_surgeon_id"]:
        raise ApiError("ERR_BLOCK_SURGEON_MISMATCH")
    if room_turnover_conflict(case, block, practice):
        raise ApiError("ERR_ROOM_TURNOVER_CONFLICT")
    recompute_block(block)
    if int(case["duration_minutes"]) > int(block["open_minutes"]):
        raise ApiError("ERR_BLOCK_CAPACITY_EXCEEDED")

    case["block_id"] = block["id"]
    case["scheduling_status"] = "BLOCK_HELD"
    touch(case)
    touch_block(block)
    return send(case)


@bp.post("/surgical-cases/<case_id>/confirm")
def confirm_case(case_id):
    authorize("SchedulingCoordinator")
    case = path_row(db.cases, case_id)
    body = read_body(required=("expected_block_version",))
    expected_block_version = v_int(body, "expected_block_version", minimum=0)
    practice = get_practice(case["practice_id"])
    block = get_block(case.get("block_id")) if case.get("block_id") else None
    level = case["planned_anesthesia_level"]

    if block is not None and int(block["version"]) != expected_block_version:
        raise ApiError("ERR_STALE_BLOCK_VERSION")
    if case["scheduling_status"] != "BLOCK_HELD":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    if case["clearance_status"] != "CLEARED":
        raise ApiError("ERR_CASE_NOT_CLEARED")
    if not privilege_admits(practice["sedation_privilege_state"], level):
        raise ApiError("ERR_SEDATION_PRIVILEGE_UNAVAILABLE")
    if not permit_rank_sufficient(case["practice_id"], level):
        raise ApiError("ERR_PERMIT_LEVEL_INSUFFICIENT")
    if level != "LOCAL_ONLY":
        permit = open_permit(case["practice_id"])
        if permit is not None:
            if refresh_permit_ratio(permit) < DRILL_COMPLIANCE_FLOOR:
                raise ApiError("ERR_DRILL_COMPLIANCE_LAPSED")
    if staffing_unmet(case, practice):
        raise ApiError("ERR_STAFFING_RATIO_UNMET")
    predecessor_id = case.get("prerequisite_case_id")
    if predecessor_id:
        predecessor = get_case(predecessor_id)
        if predecessor is None or predecessor["scheduling_status"] != "COMPLETED":
            raise ApiError("ERR_PREREQUISITE_CASE_INCOMPLETE")
    if case["referral_coordination_status"] == "PENDING":
        raise ApiError("ERR_REFERRAL_ACKNOWLEDGEMENT_REQUIRED")
    if monitor_double_booked(case):
        raise ApiError("ERR_MONITOR_DOUBLE_BOOKED")
    if recovery_capacity_exceeded(case, practice):
        raise ApiError("ERR_RECOVERY_CAPACITY_EXCEEDED")

    case["scheduling_status"] = "CONFIRMED"
    touch(case)
    if block is not None:
        touch_block(block)
    return send(case)


@bp.post("/surgical-cases/<case_id>/cancel")
def cancel_case(case_id):
    authorize("SchedulingCoordinator")
    case = path_row(db.cases, case_id)
    body = read_body(required=("cancellation_reason",))
    reason = v_enum(body, "cancellation_reason", CANCELLATION_REASONS)

    origin = case["scheduling_status"]
    if origin not in ("DRAFT", "BLOCK_HELD", "CONFIRMED"):
        raise ApiError("ERR_INVALID_STATE_TRANSITION")

    case["scheduling_status"] = "CANCELLED"
    case["cancellation_reason"] = reason
    touch(case)

    if origin in ("BLOCK_HELD", "CONFIRMED"):
        block = get_block(case.get("block_id")) if case.get("block_id") else None
        if block is not None:
            touch_block(block)
        released_any = False
        for reservation in reservations_of_case(case["id"]):
            if reservation["status"] != "HELD":
                continue
            release_reservation(reservation)
            released_any = True
        practice = get_practice(case["practice_id"])
        if practice is not None and released_any:
            recompute_consignment(practice)
            touch_practice(practice)

    for evaluation in evaluations_of_case(case["id"]):
        if evaluation["status"] in VOIDABLE_EVALUATION_STATUSES:
            evaluation["status"] = "VOIDED"
            touch(evaluation)
    return send(case)


@bp.post("/surgical-cases/<case_id>/start-recovery")
def start_recovery(case_id):
    authorize("Surgeon")
    case = path_row(db.cases, case_id)
    if actor_id() != case["primary_surgeon_id"]:
        raise ApiError("ERR_ACTOR_NOT_ASSIGNED")
    if case["scheduling_status"] != "CONFIRMED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    if clock_dt() < parse_date(case["planned_start"]):
        raise ApiError("ERR_INVALID_STATE_TRANSITION")

    case["recovery_started_at"] = clock_str()
    case["scheduling_status"] = "IN_RECOVERY"
    touch(case)
    return send(case)


@bp.post("/surgical-cases/<case_id>/complete")
def complete_case(case_id):
    authorize("Surgeon")
    case = path_row(db.cases, case_id)
    if actor_id() != case["primary_surgeon_id"]:
        raise ApiError("ERR_ACTOR_NOT_ASSIGNED")
    if case["scheduling_status"] != "IN_RECOVERY":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    started = parse_date(case.get("recovery_started_at"))
    minutes = int(case.get("recovery_minutes_required") or 0)
    if started is None or clock_dt() < started + timedelta(minutes=minutes):
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    for reservation in reservations_of_case(case["id"]):
        if reservation["status"] == "HELD":
            raise ApiError("ERR_INVALID_STATE_TRANSITION")

    case["scheduling_status"] = "COMPLETED"
    touch(case)
    block = get_block(case.get("block_id")) if case.get("block_id") else None
    if block is not None:
        recompute_block(block)
    return send(case)


@bp.post("/surgical-cases/<case_id>/referral-coordination")
def referral_coordination(case_id):
    authorize("SchedulingCoordinator")
    case = path_row(db.cases, case_id)
    body = read_body(required=("acknowledged_by_npi",))
    v_string(body, "acknowledged_by_npi", min_len=1, max_len=32)

    if case["referral_coordination_status"] != "PENDING":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    case["referral_coordination_status"] = "ACKNOWLEDGED"
    touch(case)
    return send(case)


@bp.post("/surgical-cases/<case_id>/prerequisite")
def repoint_prerequisite(case_id):
    authorize("SchedulingCoordinator")
    case = path_row(db.cases, case_id)
    body = read_body(required=("prerequisite_case_id",))
    predecessor_id = v_id(body, "prerequisite_case_id")
    predecessor = referenced_row(db.cases, predecessor_id)
    scope_check(predecessor["practice_id"], case["practice_id"])

    if case["scheduling_status"] not in ("DRAFT", "BLOCK_HELD"):
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    if _closes_cycle(case["id"], predecessor_id):
        raise ApiError("ERR_PREREQUISITE_CYCLE")

    case["prerequisite_case_id"] = predecessor_id
    touch(case)
    return send(case)
