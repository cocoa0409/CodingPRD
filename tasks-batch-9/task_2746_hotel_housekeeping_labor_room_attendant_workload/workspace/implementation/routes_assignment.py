"""Room assignments, the eight creation gates, the cleaning windows and the
inspection / re-clean loop -- PRD 3.4, 3.5 and 3.6.
"""

from flask import Blueprint, request

import derive
from auth import HOUSEKEEPING_DIRECTOR, ROOM_ATTENDANT, SUPERVISOR, authenticate, resolve_acting_attendant
from envelope import created, filtered, ok, paginate
from errors import ApiError
from numeric import to_frac, trunc_toward_zero
from serialize import assignment_out, inspection_out
from store import STORE, base_record, touch
from timeutil import date_minus_days, minutes_between
from validate import read_body, vdatetime, venum, vint, vstr

bp = Blueprint("assignment", __name__)


def _require_owner(actor, roster):
    if actor.role == ROOM_ATTENDANT and roster["attendant_id"] != actor.user_id:
        raise ApiError(
            "ERR_NOT_ASSIGNMENT_OWNER",
            "Roster %s does not belong to the acting attendant." % roster["id"],
        )


def _new_assignment_row(store, roster, room, room_type, service_type,
                        reclean_generation=0, supersedes_assignment_id=None):
    row = base_record(store)
    row.update({
        "roster_id": roster["id"],
        "room_id": room["id"],
        "supersedes_assignment_id": supersedes_assignment_id,
        "service_type": service_type,
        "credits": derive.assignment_credit_value(
            room, room_type, service_type, reclean_generation
        ),
        "reclean_generation": reclean_generation,
        "status": "ASSIGNED",
        "started_at": None,
        "completed_at": None,
        "actual_minutes": None,
        "square_feet_snapshot": room_type["square_feet"],
        "linen_sets_debited": 0,
        "roster_version_after": None,
    })
    store.assignments[row["id"]] = row
    return row


@bp.post("/housekeeping/room-assignments")
def create_assignment():
    authenticate((HOUSEKEEPING_DIRECTOR, SUPERVISOR))
    body = read_body()
    roster_id = vstr(body, "roster_id", 1, None)
    room_id = vstr(body, "room_id", 1, None)
    service_type = venum(body, "service_type", derive.SERVICE_TYPES)
    expected_roster_version = vint(body, "expected_roster_version", 0, None)

    roster = derive.get_roster(STORE, roster_id)
    room = derive.get_room(STORE, room_id)

    day = derive.forecast_day_of_roster(STORE, roster)
    # Rung 8: scope coherence outranks every state and capacity rule.
    if room["property_id"] != day["property_id"]:
        raise ApiError(
            "ERR_PROPERTY_SCOPE_MISMATCH",
            "Room %s belongs to another property than the roster." % room["id"],
        )

    # Rung 9: optimistic concurrency sits above the state preconditions.
    if expected_roster_version != roster["version"]:
        raise ApiError(
            "ERR_STALE_ROSTER_VERSION",
            "expected_roster_version %d does not match the current version %d."
            % (expected_roster_version, roster["version"]),
        )

    # Rung 10.  Assignments may be created while the roster is still PLANNED.
    if roster["status"] == "CLOSED":
        raise ApiError("ERR_ROSTER_ALREADY_CLOSED", "Roster is already closed.")

    # Rung 12: at most one non-terminal assignment per roster, room and service type.
    for other in derive.assignments_of_roster(STORE, roster["id"]):
        if (
            other["room_id"] == room["id"]
            and other["service_type"] == service_type
            and other["status"] in derive.NON_TERMINAL_ASSIGNMENT_STATUSES
        ):
            raise ApiError(
                "ERR_ASSIGNMENT_DUPLICATE",
                "A non-terminal %s assignment already exists for this roster and room."
                % service_type,
            )

    prop = STORE.properties[day["property_id"]]
    attendant = derive.attendant_of_roster(STORE, roster)
    room_type = STORE.room_types[room["room_type_id"]]
    incoming_credits = derive.assignment_credit_value(room, room_type, service_type, 0)
    incoming_sqft = int(room_type["square_feet"])

    prospective_credits = to_frac(roster["assigned_credits"]) + to_frac(incoming_credits)
    prospective_sqft = int(roster["assigned_square_feet"]) + incoming_sqft

    # Gate 1 -- the statutory square-footage ordinance.
    sqft_cap = derive.effective_sqft_cap(prop)
    if sqft_cap is not None and prospective_sqft > sqft_cap:
        raise ApiError(
            "ERR_ORDINANCE_SQFT_EXCEEDED",
            "Assigned square feet would reach %d against a ceiling of %d."
            % (prospective_sqft, sqft_cap),
        )

    # Gate 2 -- the contractual credit ceiling.
    credit_cap = derive.effective_credit_cap(prop, attendant)
    if prospective_credits > to_frac(credit_cap):
        waived = (
            roster["waiver_state"] == "GRANTED"
            and roster["waiver_requested_credits"] is not None
            and prospective_credits <= to_frac(roster["waiver_requested_credits"])
        )
        if not waived:
            raise ApiError(
                "ERR_CREDIT_CAP_EXCEEDED",
                "Assigned credits would exceed the effective credit cap of %s."
                % credit_cap,
            )

    # Gate 3 -- the injury-prevention freeze.
    if roster["compliance_state"] == "BREACH_BLOCKED":
        raise ApiError(
            "ERR_ROSTER_WORKLOAD_BREACH",
            "Roster is BREACH_BLOCKED and accepts no further work.",
        )

    # Gate 4 -- restricted-duty eligibility.
    if attendant["restricted_duty"] and service_type == "DEEP_CLEAN":
        raise ApiError(
            "ERR_RESTRICTED_DUTY_INELIGIBLE",
            "A restricted-duty attendant may not be given a DEEP_CLEAN room.",
        )

    # Gate 5 -- the linen shortage block.
    if service_type == "DEEP_CLEAN" and derive.property_has_linen_shortage(
        STORE, prop["id"]
    ):
        raise ApiError(
            "ERR_LINEN_SHORTAGE_BLOCK",
            "Deep cleaning is deferred while linen is short at this property.",
        )

    # Gate 6 -- opt-out respected.
    if room["service_program"] == "OPT_OUT" and service_type in ("CHECKOUT", "STAYOVER"):
        raise ApiError(
            "ERR_SERVICE_OPTED_OUT",
            "The guest in room %s has opted out of service." % room["room_number"],
        )

    # Gate 7 -- the every-other-day cadence.
    if room["service_program"] == "EVERY_OTHER_DAY" and service_type == "STAYOVER":
        last = room["last_serviced_business_date"]
        if last is not None and last > date_minus_days(day["business_date"], 2):
            raise ApiError(
                "ERR_SERVICE_NOT_DUE",
                "Alternating-day service is not yet due for room %s."
                % room["room_number"],
            )

    # Gate 8 -- occupancy coherence.  LINEN_REFRESH carries no requirement.
    required_occupancy = derive.OCCUPANCY_REQUIRED_FOR_SERVICE.get(service_type)
    if required_occupancy is not None and room["occupancy_state"] != required_occupancy:
        raise ApiError(
            "ERR_OCCUPANCY_MISMATCH",
            "%s requires an occupancy_state of %s." % (service_type, required_occupancy),
        )

    row = _new_assignment_row(STORE, roster, room, room_type, service_type)
    derive.cascade_roster(STORE, roster)
    row["roster_version_after"] = roster["version"]
    return created(assignment_out(STORE, row))


@bp.get("/housekeeping/room-assignments/<aid>")
def read_assignment(aid):
    authenticate(None)
    row = derive.get_assignment(STORE, aid)
    return ok(assignment_out(STORE, row))


@bp.get("/housekeeping/room-assignments")
def list_assignments():
    authenticate(None)
    rows = filtered(
        list(STORE.assignments.values()),
        request.args,
        {
            "roster_id": ("roster_id", None),
            "room_id": ("room_id", None),
            "supersedes_assignment_id": ("supersedes_assignment_id", None),
            "status": ("status", None),
            "service_type": ("service_type", None),
        },
    )
    return paginate(rows, request.args, lambda r: assignment_out(STORE, r))


STARTABLE_ROOM_CONDITIONS = ("DIRTY", "RECLEAN_REQUIRED", "CLEAN", "INSPECTED_PASS")


@bp.post("/housekeeping/room-assignments/<aid>/start")
def start_assignment(aid):
    actor = authenticate((SUPERVISOR, ROOM_ATTENDANT))
    body = read_body()
    started_at = vdatetime(body, "started_at", required=False, default=None)

    assignment = derive.get_assignment(STORE, aid)
    roster = derive.get_roster(STORE, assignment["roster_id"])
    _require_owner(actor, roster)

    if assignment["status"] != "ASSIGNED":
        raise ApiError("ERR_ASSIGNMENT_NOT_ASSIGNED", "Assignment is not ASSIGNED.")
    if roster["status"] == "CLOSED":
        raise ApiError("ERR_ROSTER_ALREADY_CLOSED", "Roster is already closed.")
    if roster["status"] != "CLOCKED_IN":
        raise ApiError("ERR_ROSTER_NOT_CLOCKED_IN", "Roster is not CLOCKED_IN.")

    room = STORE.rooms[assignment["room_id"]]
    for other in derive.assignments_of_room(STORE, room["id"]):
        if other["id"] != assignment["id"] and other["status"] == "IN_PROGRESS":
            raise ApiError(
                "ERR_ROOM_ALREADY_IN_SERVICE",
                "Room %s is already being cleaned." % room["room_number"],
            )
    if room["cleanliness_status"] not in STARTABLE_ROOM_CONDITIONS:
        raise ApiError(
            "ERR_ROOM_ALREADY_IN_SERVICE",
            "Room %s is in %s and cannot receive a start."
            % (room["room_number"], room["cleanliness_status"]),
        )

    if roster["compliance_state"] == "BREACH_BLOCKED":
        raise ApiError(
            "ERR_ROSTER_WORKLOAD_BREACH",
            "Roster is BREACH_BLOCKED and accepts no further work.",
        )

    if started_at is None:
        started_at = STORE.now()
    assignment["started_at"] = started_at
    assignment["status"] = "IN_PROGRESS"
    touch(STORE, assignment)

    # The room-condition machine is cyclic: DIRTY -> IN_SERVICE for a planned clean,
    # RECLEAN_REQUIRED -> IN_SERVICE for a system-generated re-clean.
    room["cleanliness_status"] = "IN_SERVICE"
    touch(STORE, room)
    return ok(assignment_out(STORE, assignment))


@bp.post("/housekeeping/room-assignments/<aid>/complete")
def complete_assignment(aid):
    actor = authenticate((SUPERVISOR, ROOM_ATTENDANT))
    body = read_body()
    completed_at = vdatetime(body, "completed_at", required=False, default=None)

    assignment = derive.get_assignment(STORE, aid)
    roster = derive.get_roster(STORE, assignment["roster_id"])
    _require_owner(actor, roster)

    if assignment["status"] != "IN_PROGRESS":
        raise ApiError(
            "ERR_ASSIGNMENT_NOT_IN_PROGRESS", "Assignment is not IN_PROGRESS."
        )
    if roster["status"] == "CLOSED":
        raise ApiError("ERR_ROSTER_ALREADY_CLOSED", "Roster is already closed.")
    if roster["status"] != "CLOCKED_IN":
        raise ApiError("ERR_ROSTER_NOT_CLOCKED_IN", "Roster is not CLOCKED_IN.")
    if roster["compliance_state"] == "BREACH_BLOCKED":
        raise ApiError(
            "ERR_ROSTER_WORKLOAD_BREACH",
            "Roster is BREACH_BLOCKED and accepts no further work.",
        )

    if completed_at is None:
        completed_at = STORE.now()
    started_at = assignment["started_at"]
    if started_at is None or completed_at <= started_at:
        raise ApiError(
            "ERR_INVALID_TIME_WINDOW", "completed_at must be strictly after started_at."
        )

    prop = derive.property_of_roster(STORE, roster)
    if derive.room_window_overlap(STORE, assignment, started_at, completed_at):
        raise ApiError(
            "ERR_ROOM_WINDOW_OVERLAP",
            "The cleaning window overlaps another completed window on this room.",
        )
    if derive.rest_buffer_violation(
        STORE, assignment, started_at, completed_at, prop["rest_buffer_minutes"]
    ):
        raise ApiError(
            "ERR_REST_BUFFER_VIOLATION",
            "The window is not separated from the attendant's other windows by %d minutes."
            % prop["rest_buffer_minutes"],
        )

    room = STORE.rooms[assignment["room_id"]]
    room_type = STORE.room_types[room["room_type_id"]]
    day = derive.forecast_day_of_roster(STORE, roster)

    # The linen debit is validated BEFORE anything is written, because insufficient
    # stock refuses the entire completion.
    linen_item = derive.sheet_set_item(STORE, room["property_id"])
    debit_sets = 0
    if linen_item is not None and assignment["service_type"] != "STAYOVER":
        debit_sets = int(room_type["linen_sets_per_room"])
        if linen_item["on_hand_clean"] - debit_sets < 0:
            raise ApiError(
                "ERR_LINEN_STOCK_INSUFFICIENT",
                "The clean shelf holds %d sets and the debit asks for %d."
                % (linen_item["on_hand_clean"], debit_sets),
            )

    assignment["completed_at"] = completed_at
    assignment["actual_minutes"] = trunc_toward_zero(
        minutes_between(started_at, completed_at)
    )
    assignment["status"] = "COMPLETED"

    room["cleanliness_status"] = "CLEAN"
    room["last_serviced_business_date"] = day["business_date"]
    if assignment["service_type"] == "DEEP_CLEAN":
        room["last_deep_cleaned_business_date"] = day["business_date"]
    touch(STORE, room)

    assignment["linen_sets_debited"] = debit_sets
    if linen_item is not None and debit_sets > 0:
        linen_item["on_hand_clean"] = linen_item["on_hand_clean"] - debit_sets
        linen_item["soiled_queue"] = linen_item["soiled_queue"] + debit_sets
        derive.recompute_linen(STORE, linen_item, bump=True)

    derive.cascade_roster(STORE, roster)
    assignment["roster_version_after"] = roster["version"]
    touch(STORE, assignment)
    return ok(assignment_out(STORE, assignment))


@bp.post("/housekeeping/room-assignments/<aid>/cancel")
def cancel_assignment(aid):
    authenticate((HOUSEKEEPING_DIRECTOR, SUPERVISOR))
    assignment = derive.get_assignment(STORE, aid)
    roster = derive.get_roster(STORE, assignment["roster_id"])

    if roster["status"] == "CLOSED":
        raise ApiError("ERR_ROSTER_ALREADY_CLOSED", "Roster is already closed.")
    if assignment["status"] != "ASSIGNED":
        raise ApiError(
            "ERR_ASSIGNMENT_TERMINAL",
            "Only an assignment still in ASSIGNED may be cancelled.",
        )

    assignment["status"] = "CANCELLED"
    # Cancelling sheds the credits and square feet, which is how a roster escapes
    # BREACH_BLOCKED without a waiver.
    derive.cascade_roster(STORE, roster)
    assignment["roster_version_after"] = roster["version"]
    touch(STORE, assignment)
    return ok(assignment_out(STORE, assignment))


# ---------------------------------------------------------------------------
# Inspections and the re-clean loop (PRD 3.6)
# ---------------------------------------------------------------------------

POINT_FIELDS = (
    "bathroom_points",
    "linen_points",
    "dust_points",
    "amenity_points",
    "floor_points",
)

MAX_RECLEAN_GENERATION = 2


@bp.post("/housekeeping/inspections")
def create_inspection():
    actor = authenticate((SUPERVISOR,))
    body = read_body()
    assignment_id = vstr(body, "assignment_id", 1, None)
    points = {}
    for field in POINT_FIELDS:
        points[field] = vint(body, field, 0, 10)

    assignment = derive.get_assignment(STORE, assignment_id)
    # Rung 6: an X-User-ID that must resolve to an Attendant row is checked here.
    inspector = resolve_acting_attendant(STORE, actor)
    roster = derive.get_roster(STORE, assignment["roster_id"])

    if assignment["status"] != "COMPLETED":
        raise ApiError("ERR_ASSIGNMENT_NOT_COMPLETED", "Assignment is not COMPLETED.")
    if roster["status"] == "CLOSED":
        raise ApiError("ERR_ROSTER_ALREADY_CLOSED", "Roster is already closed.")
    if roster["status"] != "CLOCKED_IN":
        raise ApiError("ERR_ROSTER_NOT_CLOCKED_IN", "Roster is not CLOCKED_IN.")

    # Rung 13: nobody inspects their own work.
    if actor.user_id == roster["attendant_id"]:
        raise ApiError(
            "ERR_SEGREGATION_OF_DUTIES",
            "An attendant may not inspect work performed on their own roster.",
        )

    # Rung 14: inspector qualification.
    if not inspector["can_inspect"] or inspector["status"] != "ACTIVE":
        raise ApiError(
            "ERR_NOT_INSPECTION_QUALIFIED",
            "The acting attendant is not qualified to inspect.",
        )

    prop = derive.property_of_roster(STORE, roster)
    score_pct, critical_fail, result = derive.inspection_score(
        points, prop["reclean_threshold_score"]
    )

    row = base_record(STORE, with_version=False)
    row.update({
        "assignment_id": assignment["id"],
        "inspector_attendant_id": inspector["id"],
        "score_pct": score_pct,
        "critical_fail": critical_fail,
        "result": result,
        "generated_reclean_assignment_id": None,
    })
    for field in POINT_FIELDS:
        row[field] = points[field]
    STORE.inspections[row["id"]] = row

    room = STORE.rooms[assignment["room_id"]]
    room_type = STORE.room_types[room["room_type_id"]]

    if result == "PASS":
        assignment["status"] = "INSPECTED_PASS"
        touch(STORE, assignment)
        room["cleanliness_status"] = "INSPECTED_PASS"
        touch(STORE, room)
        derive.cascade_roster(STORE, roster)
        return created(inspection_out(STORE, row))

    # FAIL -- a chain of five effects.
    assignment["status"] = "RECLEAN_REQUIRED"
    touch(STORE, assignment)

    reclean = None
    if assignment["reclean_generation"] < MAX_RECLEAN_GENERATION:
        # The system-generated re-clean is exempt from the pre-create ordinance gates
        # of PRD 3.4, so a quality failure is never silently dropped.
        reclean = _new_assignment_row(
            STORE,
            roster,
            room,
            room_type,
            assignment["service_type"],
            reclean_generation=assignment["reclean_generation"] + 1,
            supersedes_assignment_id=assignment["id"],
        )
        row["generated_reclean_assignment_id"] = reclean["id"]
        room["cleanliness_status"] = "RECLEAN_REQUIRED"
    else:
        # Two failed re-cleans mean the room comes off the floor.
        room["cleanliness_status"] = "OUT_OF_ORDER"
    touch(STORE, room)

    # The failure marks the attendant, which raises the sampling obligation before
    # the roster is recomputed.
    attendant = derive.attendant_of_roster(STORE, roster)
    attendant["quality_probation"] = True
    attendant["lifetime_fail_count"] = attendant["lifetime_fail_count"] + 1
    touch(STORE, attendant)

    derive.cascade_roster(STORE, roster)
    if reclean is not None:
        reclean["roster_version_after"] = roster["version"]
    return created(inspection_out(STORE, row))


@bp.get("/housekeeping/inspections/<iid>")
def read_inspection(iid):
    authenticate(None)
    row = derive.get_inspection(STORE, iid)
    return ok(inspection_out(STORE, row))


@bp.get("/housekeeping/inspections")
def list_inspections():
    authenticate(None)
    rows = filtered(
        list(STORE.inspections.values()),
        request.args,
        {
            "assignment_id": ("assignment_id", None),
            "inspector_attendant_id": ("inspector_attendant_id", None),
            "generated_reclean_assignment_id": ("generated_reclean_assignment_id", None),
            "result": ("result", None),
        },
    )
    return paginate(rows, request.args, lambda r: inspection_out(STORE, r))
