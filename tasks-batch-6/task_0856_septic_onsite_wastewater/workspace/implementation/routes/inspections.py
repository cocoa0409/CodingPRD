"""Field inspections: the contractor calendar, verdicts and the four-eyes rule."""
from flask import Blueprint

import calc
import derive
import lookup
import response
import serialize
import store
import validate as v
from auth import authenticate
from errors import ApiError
from store import ordered, touch
from util import now

bp = Blueprint("inspections", __name__)

INSPECTION_TYPES = ("COVER", "FINAL", "COMPLAINT")
INSPECTION_READ_ROLES = ["Applicant", "DesignProfessional", "Installer",
                         "EnvironmentalHealthSpecialist", "HealthOfficer",
                         "RecordsClerk"]
RESULTS = ("PASS", "FAIL")
RESULTABLE_PERMIT_STATES = ("UNDER_CONSTRUCTION", "COVER_PASSED")


def _calendar_conflict(contractor_id, start, end, exclude_id=None):
    for existing in ordered(store.inspections.values()):
        if existing["contractor_id"] != contractor_id:
            continue
        if existing["status"] != "SCHEDULED":
            continue
        if exclude_id is not None and existing["id"] == exclude_id:
            continue
        if calc.contractor_slot_conflict(start, end, existing["scheduled_start"],
                                         existing["scheduled_end"]):
            return True
    return False


@bp.post("/inspections")
def schedule_inspection():
    actor = authenticate(["EnvironmentalHealthSpecialist"])
    body = v.body()
    permit = lookup.construction_permit(v.req_fk(body, "construction_permit_id"))
    inspection_type = v.req_enum(body, "inspection_type", INSPECTION_TYPES)
    scheduled_start = v.req_dt(body, "scheduled_start")
    scheduled_end = v.req_dt(body, "scheduled_end")
    if scheduled_end <= scheduled_start:
        raise v.bad("scheduled_end must be strictly after scheduled_start.")

    # A voided permit authorises nothing; an expired one is caught by the
    # construction-window rule below, which is what PRD 3.6 states explicitly.
    if permit["status"] == "VOIDED":
        raise ApiError("ERR_INVALID_STATE")

    if _calendar_conflict(permit["contractor_id"], scheduled_start, scheduled_end):
        raise ApiError("ERR_CONTRACTOR_SCHEDULE_CONFLICT")

    clock = now()
    if clock < permit["valid_from"] or clock > permit["valid_until"]:
        raise ApiError("ERR_PERMIT_NOT_IN_WINDOW")

    inspection = store.new_record()
    inspection.update({
        "construction_permit_id": permit["id"],
        "contractor_id": permit["contractor_id"],
        "inspection_type": inspection_type,
        "inspector_user_id": actor.user_id,
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
        "status": "SCHEDULED",
        "result_recorded_at": None,
        "deficiency_codes": [],
        "reinspection_round": 0,
    })
    store.inspections[inspection["id"]] = inspection

    if permit["status"] == "ISSUED":
        permit["status"] = "UNDER_CONSTRUCTION"
        touch(permit)

    return response.ok(serialize.inspection(inspection), 201)


@bp.get("/inspections/<inspection_id>")
def read_inspection(inspection_id):
    authenticate(INSPECTION_READ_ROLES)
    inspection = lookup.inspection(inspection_id)
    return response.ok(serialize.inspection(inspection))


@bp.get("/inspections")
def list_inspections():
    authenticate(INSPECTION_READ_ROLES)
    limit, offset = v.pagination()
    rows = ordered(store.inspections.values())
    for field in ("construction_permit_id", "contractor_id", "status",
                  "inspection_type"):
        value = v.q(field)
        if value is not None:
            rows = [r for r in rows if r[field] == value]
    page, total = v.paginate(rows, limit, offset)
    return response.ok_list(serialize.many("inspection", page),
                            limit, offset, total)


@bp.post("/inspections/<inspection_id>/result")
def record_result(inspection_id):
    actor = authenticate(["EnvironmentalHealthSpecialist"])
    inspection = lookup.inspection(inspection_id)
    body = v.body()
    result = v.req_enum(body, "result", RESULTS)
    deficiency_codes = []
    if result == "FAIL":
        deficiency_codes = v.req_str_array(body, "deficiency_codes",
                                           non_empty=True)

    permit = store.construction_permits[inspection["construction_permit_id"]]
    design = store.system_designs.get(permit["system_design_id"])

    # Check 8 -- segregation of duties, ahead of every state check.
    if (result == "PASS" and inspection["inspection_type"] == "COVER"
            and design is not None
            and design["review_ehs_user_id"] is not None
            and design["review_ehs_user_id"] == actor.user_id):
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    if inspection["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE")
    if permit["status"] not in RESULTABLE_PERMIT_STATES:
        raise ApiError("ERR_INVALID_STATE")

    if result == "PASS":
        contractor = store.contractors.get(permit["contractor_id"])
        effective = None
        if contractor is not None:
            effective = calc.contractor_effective_status(
                contractor["status"], contractor["license_expires_on"], now())
        if effective != "ACTIVE":
            raise ApiError("ERR_CONTRACTOR_NOT_ACTIVE")

        kind = inspection["inspection_type"]
        if kind == "COVER" and permit["status"] != "UNDER_CONSTRUCTION":
            raise ApiError("ERR_INSPECTION_SEQUENCE")
        if kind == "FINAL" and permit["status"] != "COVER_PASSED":
            raise ApiError("ERR_INSPECTION_SEQUENCE")

        clock = now()
        inspection["status"] = "PASSED"
        inspection["result_recorded_at"] = clock
        touch(inspection)
        if kind == "COVER":
            permit["status"] = "COVER_PASSED"
            permit["cover_inspection_passed_at"] = clock
            touch(permit)
        elif kind == "FINAL":
            permit["status"] = "COMPLETED"
            touch(permit)
    else:
        inspection["status"] = "FAILED"
        inspection["result_recorded_at"] = now()
        inspection["deficiency_codes"] = deficiency_codes
        touch(inspection)

    return response.ok(serialize.inspection(inspection))


@bp.post("/inspections/<inspection_id>/reschedule")
def reschedule_inspection(inspection_id):
    authenticate(["EnvironmentalHealthSpecialist"])
    inspection = lookup.inspection(inspection_id)
    body = v.body()
    scheduled_start = v.req_dt(body, "scheduled_start")
    scheduled_end = v.req_dt(body, "scheduled_end")
    if scheduled_end <= scheduled_start:
        raise v.bad("scheduled_end must be strictly after scheduled_start.")

    if inspection["status"] != "FAILED":
        raise ApiError("ERR_INVALID_STATE")
    permit = store.construction_permits[inspection["construction_permit_id"]]
    if permit["status"] not in RESULTABLE_PERMIT_STATES:
        raise ApiError("ERR_INVALID_STATE")

    if _calendar_conflict(inspection["contractor_id"], scheduled_start,
                          scheduled_end, exclude_id=inspection["id"]):
        raise ApiError("ERR_CONTRACTOR_SCHEDULE_CONFLICT")

    inspection["scheduled_start"] = scheduled_start
    inspection["scheduled_end"] = scheduled_end
    inspection["status"] = "SCHEDULED"
    inspection["reinspection_round"] += 1
    inspection["result_recorded_at"] = None
    inspection["deficiency_codes"] = []
    touch(inspection)
    return response.ok(serialize.inspection(inspection))
