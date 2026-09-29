"""Program design, staffing and delivery day."""
from datetime import timedelta

from flask import Blueprint

from db import store, base_row, touch, clock_now, clock_date, by_created_at
from errors import ApiError, invalid
from middleware import authorize
from response import object_response, created_response, list_response, pagination, paginate
from validation import body, req_str, req_enum, req_int, req_bool, req_instant
from services import constants as C
from services import derive, serialize, cascade
from services.lookup import get_booking, get_element, get_facilitator, get_program_block, apply_filters

bp = Blueprint("blocks", __name__)
PREFIX = "/challenge-course"

READ_ROLES = ["ProgramDirector", "SafetyOfficer", "Facilitator", "GroupCoordinator"]
BUFFER = timedelta(minutes=C.FACILITATOR_BUFFER_MINUTES)


# ------------------------------------------------------------------ program blocks

@bp.post(PREFIX + "/program-blocks")
def create_program_block():
    authorize(["ProgramDirector"])
    payload = body()

    booking_id = req_str(payload, "booking_id")
    sequence_index = req_int(payload, "sequence_index", minimum=1)
    phase = req_enum(payload, "phase", C.PHASES)
    element_id = req_str(payload, "element_id", required=False, default=None)
    planned_start_at = req_instant(payload, "planned_start_at")
    planned_end_at = req_instant(payload, "planned_end_at")

    if planned_start_at >= planned_end_at:
        raise invalid("planned_start_at must be strictly earlier than planned_end_at.")

    booking = get_booking(booking_id)
    element = get_element(element_id) if element_id else None

    # Step 26 — phase and element type belong to the same family.
    allowed_types = C.PHASE_ELEMENT_TYPES[phase]
    if allowed_types is None:
        if element is not None:
            raise ApiError("ERR_ELEMENT_PHASE_MISMATCH")
    else:
        if element is None or element["element_type"] not in allowed_types:
            raise ApiError("ERR_ELEMENT_PHASE_MISMATCH")

    # Step 27 — the element sits on the booking's course.
    if element is not None and element["course_id"] != booking["course_id"]:
        raise ApiError("ERR_ELEMENT_COURSE_MISMATCH")

    siblings = derive.blocks_of_booking(booking["id"])

    # Step 28 — sequencing, in the PRD's stated order.
    for existing in siblings:
        if existing["sequence_index"] == sequence_index:
            raise ApiError("ERR_DUPLICATE_BLOCK_SEQUENCE")

    if sequence_index == 1 and phase != "ICEBREAKER":
        raise ApiError("ERR_SEQUENCING_VIOLATION")

    if phase == "HIGH_ELEMENT":
        prerequisite = any(
            b["sequence_index"] < sequence_index
            and b["phase"] in ("GROUND_INITIATIVE", "LOW_ELEMENT")
            for b in siblings
        )
        if not prerequisite:
            raise ApiError("ERR_SEQUENCE_PREREQUISITE_MISSING")

    highest = max([b["sequence_index"] for b in siblings], default=0)
    if sequence_index != highest + 1:
        raise ApiError("ERR_SEQUENCE_GAP")

    # Step 32 — elements are single-occupancy; the interval is half-open, so
    # adjacency is permitted.
    if element is not None:
        for other in derive.blocks_of_element(element["id"]):
            if other["status"] not in C.ACTIVE_BLOCK_STATUSES:
                continue
            if planned_start_at < other["planned_end_at"] and other["planned_start_at"] < planned_end_at:
                raise ApiError("ERR_ELEMENT_SCHEDULE_CONFLICT")

    # Step 34 — both instants fall on the booking's program date.
    program_date = booking["program_date"]
    if planned_start_at.date() != program_date or planned_end_at.date() != program_date:
        raise ApiError("ERR_PROGRAM_DATE_IN_PAST")

    row = base_row()
    row.update({
        "booking_id": booking["id"],
        "element_id": element["id"] if element is not None else None,
        "sequence_index": sequence_index,
        "phase": phase,
        "planned_start_at": planned_start_at,
        "planned_end_at": planned_end_at,
        "status": "SCHEDULED",
        "actual_head_count": 0,
        "debrief_completed": False,
        "started_at": None,
        "completed_at": None,
    })
    store.program_blocks[row["id"]] = row
    return created_response(serialize.program_block(row))


@bp.get(PREFIX + "/program-blocks/<program_block_id>")
def read_program_block(program_block_id):
    authorize(READ_ROLES)
    row = get_program_block(program_block_id)
    return object_response(serialize.program_block(row))


@bp.get(PREFIX + "/program-blocks")
def list_program_blocks():
    authorize(READ_ROLES)
    limit, offset = pagination()
    rows = by_created_at(list(store.program_blocks.values()))
    rows = apply_filters(rows, {
        "booking_id": ("str", "booking_id"),
        "element_id": ("str", "element_id"),
        "phase": ("str", "phase"),
        "status": ("str", "status"),
    })
    window, total = paginate(rows, limit, offset)
    return list_response([serialize.program_block(r) for r in window], limit, offset, total)


# --------------------------------------------------------------- block assignments

@bp.post(PREFIX + "/program-blocks/<program_block_id>/block-assignments")
def create_block_assignment(program_block_id):
    authorize(["ProgramDirector"])
    payload = body()

    facilitator_id = req_str(payload, "facilitator_id")
    assignment_role = req_enum(payload, "assignment_role", C.ASSIGNMENT_ROLES,
                               required=False, default=None)

    block = get_program_block(program_block_id)
    facilitator = get_facilitator(facilitator_id)

    # Step 22 — certification currency.
    if facilitator["cert_status"] != "ACTIVE":
        raise ApiError("ERR_FACILITATOR_CERT_INACTIVE")

    # Step 23 — certification level against the rigged element's demand.
    required_level = derive.required_cert_level_for_block(block)
    if (C.CERT_LEVEL_ORDINAL[facilitator["certification_level"]]
            < C.CERT_LEVEL_ORDINAL[required_level]):
        raise ApiError("ERR_CERT_LEVEL_INSUFFICIENT")

    # Step 24 — the facilitator belongs to the course being staffed.
    booking = store.bookings.get(block["booking_id"])
    course_id = booking["course_id"] if booking is not None else None
    if course_id is not None and facilitator["course_id"] != course_id:
        raise ApiError("ERR_FACILITATOR_COURSE_MISMATCH")

    # Step 33 — a twenty-minute turnaround buffer separates consecutive blocks.
    for assignment in derive.assignments_of_facilitator(facilitator["id"]):
        if assignment["program_block_id"] == block["id"]:
            # Another assignment on this very block is not a turnaround.
            continue
        other = store.program_blocks.get(assignment["program_block_id"])
        if other is None:
            continue
        if (block["planned_start_at"] < other["planned_end_at"] + BUFFER
                and other["planned_start_at"] < block["planned_end_at"] + BUFFER):
            raise ApiError("ERR_FACILITATOR_SCHEDULE_CONFLICT")

    row = base_row(common_fields=False)
    row.update({
        "program_block_id": block["id"],
        "facilitator_id": facilitator["id"],
        "assignment_role": assignment_role,
        # Frozen at assignment time and never refreshed.
        "rescue_current_at_assignment": derive.rescue_current(facilitator),
    })
    store.block_assignments[row["id"]] = row
    return created_response(serialize.block_assignment(row))


@bp.get(PREFIX + "/program-blocks/<program_block_id>/block-assignments")
def list_assignments_of_block(program_block_id):
    authorize(["ProgramDirector", "SafetyOfficer", "Facilitator"])
    limit, offset = pagination()
    block = get_program_block(program_block_id)
    rows = derive.assignments_of_block(block["id"])
    window, total = paginate(rows, limit, offset)
    return list_response([serialize.block_assignment(r) for r in window], limit, offset, total)


# ------------------------------------------------------------------- delivery day

@bp.post(PREFIX + "/program-blocks/<program_block_id>/start")
def start_block(program_block_id):
    authorize(["Facilitator"])
    body()

    block = get_program_block(program_block_id)

    # ---- Step 9: state preconditions, in the order the PRD lists them.
    if block["status"] not in ("SCHEDULED", "SUSPENDED"):
        raise ApiError("ERR_BLOCK_NOT_SCHEDULED")

    booking = store.bookings.get(block["booking_id"])
    if booking is None or booking["status"] != "CONFIRMED":
        raise ApiError("ERR_BOOKING_NOT_CONFIRMED")

    element = store.elements.get(block["element_id"]) if block["element_id"] else None
    if element is not None:
        if element["status"] == "RETIRED":
            raise ApiError("ERR_ELEMENT_RETIRED")
        if element["status"] != "SERVICEABLE":
            raise ApiError("ERR_ELEMENT_NOT_SERVICEABLE")

    course = store.courses.get(booking["course_id"])
    high = block["phase"] == "HIGH_ELEMENT"

    # ---- Step 11: course posture.
    if course is not None:
        if course["posture"] == "CLOSED":
            raise ApiError("ERR_COURSE_CLOSED")
        if high and course["posture"] != "OPEN":
            raise ApiError("ERR_COURSE_RESTRICTED_HIGH_ELEMENT")

    # ---- Step 12: the daily pre-use inspection.
    if element is not None and not derive.daily_inspection_satisfied(element["id"]):
        raise ApiError("ERR_DAILY_INSPECTION_MISSING")

    # ---- Step 13: professional inspection currency.
    if element is not None:
        due = element["next_professional_inspection_due_on"]
        if due is not None and due < clock_date():
            raise ApiError("ERR_INSPECTION_OVERDUE")

    # ---- Step 14: belay readiness.
    if element is not None and element["required_belay_set_count"] > 0:
        if not derive.belay_ready(element):
            raise ApiError("ERR_BELAY_NOT_READY")

    assignments = derive.assignments_of_block(block["id"])

    # ---- Step 15: a rescue-current, actively certified person on high work.
    if high:
        ready = False
        for assignment in assignments:
            if not assignment["rescue_current_at_assignment"]:
                continue
            person = store.facilitators.get(assignment["facilitator_id"])
            if person is not None and person["cert_status"] == "ACTIVE":
                ready = True
                break
        if not ready:
            raise ApiError("ERR_RESCUE_READINESS_UNMET")

    # ---- Step 16: emergency-medical access for high work.
    if high and course is not None and course["ems_response_minutes"] > C.EMS_MAX_MINUTES:
        raise ApiError("ERR_EMS_ACCESS_UNSUITABLE")

    # ---- Step 19: participant screening completeness.
    people = derive.participants_of_booking(booking["id"])
    statuses = [derive.screening_status(p, booking) for p in people]
    eligible = [p for p, s in zip(people, statuses) if s == "ELIGIBLE"]
    if not eligible or any(s in ("BLOCKED", "CONDITIONAL") for s in statuses):
        raise ApiError("ERR_PARTICIPANT_SCREENING_INCOMPLETE")

    # ---- Step 20: weight band on the rigged element, inclusive.
    if element is not None:
        low = element["min_participant_weight_kg"]
        high_limit = element["max_participant_weight_kg"]
        for person in eligible:
            if person["weight_kg"] < low or person["weight_kg"] > high_limit:
                raise ApiError("ERR_WEIGHT_LIMIT_EXCEEDED")

    # ---- Step 21: supervision count and certification capacity.
    active_heads = derive.active_head_count(booking)
    if (derive.assigned_facilitator_count(block["id"]) < derive.required_facilitator_count(block)
            or derive.block_supervision_capacity(block["id"]) < active_heads):
        raise ApiError("ERR_SUPERVISION_RATIO_UNMET")

    # ---- Step 22: every assigned facilitator holds active certification.
    for assignment in assignments:
        person = store.facilitators.get(assignment["facilitator_id"])
        if person is None or person["cert_status"] != "ACTIVE":
            raise ApiError("ERR_FACILITATOR_CERT_INACTIVE")

    # ---- Step 35: the program runs in order.
    for other in derive.blocks_of_booking(booking["id"]):
        if other["sequence_index"] >= block["sequence_index"]:
            continue
        if other["status"] not in C.TERMINAL_BLOCK_STATUSES:
            raise ApiError("ERR_BLOCK_SEQUENCE_NOT_READY")

    block["status"] = "IN_PROGRESS"
    block["started_at"] = clock_now()
    # The frozen eligible roster INCLUDING chaperones: anybody who goes on the
    # element wears the hardware.
    block["actual_head_count"] = len(eligible)
    touch(block)

    return object_response(serialize.program_block(block))


@bp.post(PREFIX + "/program-blocks/<program_block_id>/complete")
def complete_block(program_block_id):
    authorize(["Facilitator"])
    payload = body()
    debrief_completed = req_bool(payload, "debrief_completed", required=False, default=False)

    block = get_program_block(program_block_id)

    # Step 9.
    if block["status"] != "IN_PROGRESS":
        raise ApiError("ERR_BLOCK_NOT_IN_PROGRESS")

    # Step 30 — the debrief phase must record that the debrief happened.
    if block["phase"] == "DEBRIEF" and not debrief_completed:
        raise ApiError("ERR_DEBRIEF_NOT_RECORDED")

    block["status"] = "COMPLETED"
    block["completed_at"] = clock_now()
    block["debrief_completed"] = debrief_completed
    touch(block)

    cycles = block["actual_head_count"]
    element = store.elements.get(block["element_id"]) if block["element_id"] else None
    if element is not None:
        was_ready = derive.belay_ready(element)

        element["cumulative_cycle_count"] = element["cumulative_cycle_count"] + cycles
        derive.recompute_element_forecast(element)
        touch(element)

        for item in derive.equipment_of_element(element["id"]):
            if item["status"] != "IN_SERVICE":
                continue
            item["usage_cycles"] = item["usage_cycles"] + cycles
            if item["first_use_on"] is None:
                item["first_use_on"] = clock_date()
            derive.recompute_equipment_forecast(item)
            if item["usage_cycles"] >= item["max_cycles"]:
                item["status"] = "RETIRED"
            touch(item)

        cascade.propagate_belay_loss(element, was_ready)

    booking = store.bookings.get(block["booking_id"])
    if booking is not None:
        cascade.maybe_deliver(booking)

    return object_response(serialize.program_block(block))
