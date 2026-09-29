"""The two inspection regimes: annual professional cycles and daily pre-use logs."""
from flask import Blueprint, g

from db import store, base_row, touch, clock_now, by_created_at
from errors import ApiError, invalid
from middleware import authorize
from response import object_response, created_response, list_response, pagination, paginate
from validation import body, req_str, req_enum, req_date, add_months
from services import constants as C
from services import derive, serialize, cascade
from services.lookup import get_element, get_facilitator, get_inspection, get_operational_log, apply_filters

bp = Blueprint("inspections", __name__)
PREFIX = "/challenge-course"


# --------------------------------------------------------- professional inspections

@bp.post(PREFIX + "/professional-inspections")
def create_inspection():
    authorize(["ProgramDirector", "ProfessionalInspector"])
    payload = body()

    element_id = req_str(payload, "element_id")
    inspector_id = req_str(payload, "inspector_id")
    performed_on = req_date(payload, "performed_on")
    findings_note = req_str(payload, "findings_note", required=False, default="", allow_empty=True)

    element = get_element(element_id)
    inspector = get_facilitator(inspector_id)

    # Step 25 — the named inspector must genuinely be independent.
    if (inspector["staff_type"] != "CONTRACT_INSPECTOR"
            or inspector["is_operator_employee"]
            or inspector["cert_status"] != "ACTIVE"):
        raise ApiError("ERR_INSPECTOR_NOT_INDEPENDENT")

    row = base_row()
    row.update({
        "element_id": element["id"],
        "inspector_id": inspector["id"],
        "performed_on": performed_on,
        "findings_note": findings_note,
        "outcome": "NONE",
        "status": "DRAFT",
        "disposition_note": "",
        "disposed_on": None,
    })
    store.professional_inspections[row["id"]] = row
    return created_response(serialize.professional_inspection(row))


@bp.get(PREFIX + "/professional-inspections/<inspection_id>")
def read_inspection(inspection_id):
    authorize(["ProgramDirector", "SafetyOfficer", "ProfessionalInspector"])
    row = get_inspection(inspection_id)
    return object_response(serialize.professional_inspection(row))


@bp.get(PREFIX + "/professional-inspections")
def list_inspections():
    authorize(["ProgramDirector", "SafetyOfficer", "ProfessionalInspector"])
    limit, offset = pagination()
    rows = by_created_at(list(store.professional_inspections.values()))
    rows = apply_filters(rows, {
        "element_id": ("str", "element_id"),
        "inspector_id": ("str", "inspector_id"),
        "status": ("str", "status"),
        "outcome": ("str", "outcome"),
    })
    window, total = paginate(rows, limit, offset)
    return list_response([serialize.professional_inspection(r) for r in window],
                         limit, offset, total)


@bp.post(PREFIX + "/professional-inspections/<inspection_id>/file")
def file_inspection(inspection_id):
    authorize(["ProfessionalInspector"])
    payload = body()
    outcome = req_enum(payload, "outcome", C.FILE_OUTCOMES)

    inspection = get_inspection(inspection_id)

    # Step 7 — only the inspector who owns the record may file it.
    if inspection["inspector_id"] != g.user_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")

    # Step 9 — the record must be in DRAFT.
    if inspection["status"] != "DRAFT":
        raise ApiError("ERR_INSPECTION_NOT_DRAFT")

    if outcome in ("CONDITIONAL", "FAIL") and not (inspection["findings_note"] or "").strip():
        raise invalid("A non-empty findings_note is required for a %s filing." % outcome)

    inspection["outcome"] = outcome
    inspection["status"] = "FILED_" + outcome
    touch(inspection)

    element = store.elements.get(inspection["element_id"])
    course = store.courses.get(element["course_id"]) if element else None

    if outcome == "CONDITIONAL" and element is not None:
        if element["status"] in ("SERVICEABLE", "RESTRICTED"):
            cascade.element_to_restricted(element, restricting_log_id=None)
            if course is not None:
                derive.recompute_posture(course, bump_version=True)
    elif outcome == "FAIL" and element is not None:
        if element["status"] in ("SERVICEABLE", "RESTRICTED"):
            cascade.element_to_out_of_service(element)
            if course is not None:
                derive.recompute_posture(course, bump_version=True)

    return object_response(serialize.professional_inspection(inspection))


@bp.post(PREFIX + "/professional-inspections/<inspection_id>/dispose")
def dispose_inspection(inspection_id):
    authorize(["SafetyOfficer"])
    payload = body()
    disposition_note = req_str(payload, "disposition_note")

    inspection = get_inspection(inspection_id)

    # Step 9 — the record must sit in one of the three filed states.
    if inspection["status"] not in ("FILED_PASS", "FILED_CONDITIONAL", "FILED_FAIL"):
        raise ApiError("ERR_INSPECTION_NOT_FILED")

    # Step 10 — the filing inspector may not accept their own filing.
    if inspection["inspector_id"] == g.user_id:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    outcome = inspection["outcome"]
    inspection["status"] = "DISPOSED"
    inspection["disposition_note"] = disposition_note
    inspection["disposed_on"] = clock_now()
    touch(inspection)

    element = store.elements.get(inspection["element_id"])
    if element is not None:
        if outcome == "PASS":
            if element["next_professional_inspection_due_on"] is not None:
                element["next_professional_inspection_due_on"] = add_months(
                    element["next_professional_inspection_due_on"], C.INSPECTION_PASS_MONTHS
                )
            element["consecutive_conditional_count"] = 0
        elif outcome == "CONDITIONAL":
            if element["next_professional_inspection_due_on"] is not None:
                element["next_professional_inspection_due_on"] = add_months(
                    element["next_professional_inspection_due_on"],
                    C.INSPECTION_CONDITIONAL_MONTHS
                )
            element["consecutive_conditional_count"] = element["consecutive_conditional_count"] + 1
        touch(element)

        course = store.courses.get(element["course_id"])
        if course is not None:
            derive.recompute_posture(course, bump_version=True)

    return object_response(serialize.professional_inspection(inspection))


# ------------------------------------------------------------- operational logs

@bp.post(PREFIX + "/operational-logs")
def create_operational_log():
    authorize(["Facilitator", "SafetyOfficer"])
    payload = body()

    element_id = req_str(payload, "element_id")
    facilitator_id = req_str(payload, "facilitator_id")
    log_date = req_date(payload, "log_date")
    result = req_enum(payload, "result", C.LOG_RESULTS)
    defect_note = req_str(payload, "defect_note", required=False, default="", allow_empty=True)

    if result != "CLEAR" and not (defect_note or "").strip():
        raise invalid("A non-empty defect_note is required for a %s result." % result)

    element = get_element(element_id)
    facilitator = get_facilitator(facilitator_id)

    # Step 7 — the log must be filed under the acting user's own identifier.
    if facilitator["id"] != g.user_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")

    # Step 24 — the facilitator must belong to the element's course.
    if facilitator["course_id"] != element["course_id"]:
        raise ApiError("ERR_FACILITATOR_COURSE_MISMATCH")

    row = base_row(common_fields=False)
    row.update({
        "element_id": element["id"],
        "facilitator_id": facilitator["id"],
        "log_date": log_date,
        "result": result,
        "defect_note": defect_note,
        "caused_restriction": False,
    })
    store.operational_logs[row["id"]] = row

    if result == "DEFECT_MAJOR" and element["status"] == "SERVICEABLE":
        # Cascade A in full.
        row["caused_restriction"] = True
        cascade.element_to_restricted(element, restricting_log_id=row["id"])
        course = store.courses.get(element["course_id"])
        if course is not None:
            derive.recompute_posture(course, bump_version=True)

    return created_response(serialize.operational_log(row))


@bp.get(PREFIX + "/operational-logs/<log_id>")
def read_operational_log(log_id):
    authorize(["ProgramDirector", "SafetyOfficer", "Facilitator", "ProfessionalInspector"])
    row = get_operational_log(log_id)
    return object_response(serialize.operational_log(row))


@bp.get(PREFIX + "/operational-logs")
def list_operational_logs():
    authorize(["ProgramDirector", "SafetyOfficer", "Facilitator"])
    limit, offset = pagination()
    rows = by_created_at(list(store.operational_logs.values()))
    rows = apply_filters(rows, {
        "element_id": ("str", "element_id"),
        "facilitator_id": ("str", "facilitator_id"),
        "log_date": ("date", "log_date"),
        "result": ("str", "result"),
    })
    window, total = paginate(rows, limit, offset)
    return list_response([serialize.operational_log(r) for r in window], limit, offset, total)
