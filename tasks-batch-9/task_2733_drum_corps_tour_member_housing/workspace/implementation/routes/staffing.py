from flask import Blueprint

import find
import serialize
import validators as v
from auth import acting_user_id, endpoint
from envelope import object_response, paginate
from errors import ApiError
from store import db, new_record, sorted_records, touch

bp = Blueprint("staffing", __name__)

DUTIES = ("DRIVE", "COOK", "CHAPERONE", "TRAINER")
DUTY_ROLE = {
    "DRIVE": "DRIVER",
    "COOK": "COOK",
    "CHAPERONE": "CHAPERONE",
    "TRAINER": "ATHLETIC_TRAINER",
}
OPEN_STATUSES = ("PROPOSED", "ACCEPTED", "APPROVED")
READ_ROLES = ["CorpsDirector", "TourManager", "VolunteerScreener", "Volunteer"]
LIST_ROLES = ["CorpsDirector", "TourManager", "VolunteerScreener"]


@bp.route("/staff-assignments", methods=["POST"])
@endpoint(["TourManager"])
def create_staff_assignment():
    body = v.get_body()
    volunteer_id = v.req_str(body, "volunteer_id")
    stop_id = v.req_str(body, "tour_stop_id")
    duty = v.req_enum(body, "duty", DUTIES)
    start_raw, shift_start = v.req_instant(body, "shift_start_at")
    end_raw, shift_end = v.req_instant(body, "shift_end_at")
    # Rung 4 -- shift_end_at must be later than shift_start_at.
    v.date_range(shift_end > shift_start, "shift_end_at must be later than shift_start_at.")
    # Rung 8 -- volunteer then stop, in declaration order.
    volunteer = find.volunteer(volunteer_id)
    stop = find.stop(stop_id)
    # Rung 20 -- the parent stop must be PLANNED or CONFIRMED.
    if stop["status"] not in ("PLANNED", "CONFIRMED"):
        raise ApiError("ERR_INVALID_STOP_STATE",
                       "The parent stop must be PLANNED or CONFIRMED.")
    # Rung 29 -- the duty must correspond exactly to the volunteer's role_type.
    if DUTY_ROLE[duty] != volunteer["role_type"]:
        raise ApiError("ERR_DUTY_ROLE_MISMATCH",
                       "The duty does not correspond to the volunteer's role type.")
    # Rung 42 -- the shift must sit inside the stop's window.
    if shift_start < stop["_arrive_at"] or shift_end > stop["_depart_at"]:
        raise ApiError("ERR_SHIFT_OUTSIDE_STOP_WINDOW",
                       "The shift falls outside the stop's window.")
    # Rung 43 -- one volunteer may not hold two overlapping open shifts.
    for other in db.staff.values():
        if other["volunteer_id"] != volunteer_id:
            continue
        if other["status"] not in OPEN_STATUSES:
            continue
        if other["_shift_start_at"] < shift_end and other["_shift_end_at"] > shift_start:
            raise ApiError("ERR_VOLUNTEER_SHIFT_OVERLAP",
                           "This volunteer already holds an overlapping open shift.")

    record = new_record()
    record.update({
        "volunteer_id": volunteer_id,
        "tour_stop_id": stop_id,
        "duty": duty,
        "shift_start_at": start_raw,
        "shift_end_at": end_raw,
        "_shift_start_at": shift_start,
        "_shift_end_at": shift_end,
        "status": "PROPOSED",
        "approved_by_user_id": None,
        "released_reason": None,
    })
    db.staff[record["id"]] = record
    return object_response(serialize.staff(record), 201)


@bp.route("/staff-assignments/<staff_assignment_id>", methods=["GET"])
@endpoint(READ_ROLES)
def get_staff_assignment(staff_assignment_id):
    return object_response(serialize.staff(find.staff(staff_assignment_id)))


@bp.route("/staff-assignments", methods=["GET"])
@endpoint(LIST_ROLES)
def list_staff_assignments():
    volunteer_id = v.arg_str("volunteer_id")
    stop_id = v.arg_str("tour_stop_id")
    duty = v.arg_str("duty")
    status = v.arg_str("status")
    records = []
    for record in sorted_records(db.staff):
        if volunteer_id is not None and record["volunteer_id"] != volunteer_id:
            continue
        if stop_id is not None and record["tour_stop_id"] != stop_id:
            continue
        if duty is not None and record["duty"] != duty:
            continue
        if status is not None and record["status"] != status:
            continue
        records.append(record)
    return paginate(records, serialize.staff)


@bp.route("/staff-assignments/<staff_assignment_id>/accept", methods=["POST"])
@endpoint(["Volunteer"])
def accept_staff_assignment(staff_assignment_id):
    shift = find.staff(staff_assignment_id)
    # Rung 9 -- a volunteer may accept only their own shift.
    if acting_user_id() != shift["volunteer_id"]:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", "This shift belongs to another volunteer.")
    if shift["status"] != "PROPOSED":
        raise ApiError("ERR_INVALID_STAFF_ASSIGNMENT_STATE",
                       "Only a PROPOSED shift may be accepted.")
    shift["status"] = "ACCEPTED"
    touch(shift)
    return object_response(serialize.staff(shift))


@bp.route("/staff-assignments/<staff_assignment_id>/approve", methods=["POST"])
@endpoint(["TourManager"])
def approve_staff_assignment(staff_assignment_id):
    shift = find.staff(staff_assignment_id)
    if shift["status"] != "ACCEPTED":
        raise ApiError("ERR_INVALID_STAFF_ASSIGNMENT_STATE",
                       "Only an ACCEPTED shift may be approved.")
    volunteer = db.volunteers.get(shift["volunteer_id"])
    # Rung 36 -- the screening gate is evaluated ahead of the duties gate.
    if volunteer is None or volunteer["screening_status"] != "CLEARED":
        raise ApiError("ERR_SCREENING_NOT_CLEARED",
                       "The volunteer's background screening is not CLEARED.")
    # Rung 37 -- the screener may never bless their own subject.
    if acting_user_id() == volunteer["screened_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "The approving user may not be the screening user.")
    shift["status"] = "APPROVED"
    shift["approved_by_user_id"] = acting_user_id()
    touch(shift)
    return object_response(serialize.staff(shift))
