"""Inspection scheduling, execution, assessments and the completion cascade."""

import datetime

from flask import Blueprint

import auth
import calc
import envelope
import flows
import lclock
import lookups
import serialize
import store
import valid
from errors import ApiError

bp = Blueprint("inspections", __name__)
P = "/vector-control"

KINDS = ("INITIAL", "REINSPECTION")
RESULTS = ("VIOLATION_FOUND", "NO_VIOLATION", "COMPLIANT", "NON_COMPLIANT", "NO_ACCESS")
INITIAL_RESULTS = ("VIOLATION_FOUND", "NO_VIOLATION", "NO_ACCESS")
REINSPECTION_RESULTS = ("COMPLIANT", "NON_COMPLIANT", "NO_ACCESS")
BUSY = ("SCHEDULED", "IN_PROGRESS")


def refresh_assignment_count(officer_id):
    officer = store.officers.get(officer_id)
    if officer is None:
        return None
    officer["active_assignment_count"] = sum(
        1
        for i in store.inspections.values()
        if i["officer_id"] == officer_id and i["status"] in BUSY
    )
    store.touch(officer)
    return officer


def assessment_for(inspection_id):
    for assessment in store.assessments.values():
        if assessment["inspection_id"] == inspection_id:
            return assessment
    return None


@bp.post(P + "/inspections")
def create_inspection():
    caller = auth.guard("Supervisor")
    data = valid.body()
    # step 3: body foreign keys, in the order the endpoint lists them
    raw_officer_id = data.get("officer_id")
    if isinstance(raw_officer_id, str) and raw_officer_id:
        lookups.officer(raw_officer_id)
    raw_complaint_id = data.get("complaint_id")
    if isinstance(raw_complaint_id, str) and raw_complaint_id:
        lookups.complaint(raw_complaint_id)
    raw_order_id = data.get("abatement_order_id")
    if isinstance(raw_order_id, str) and raw_order_id:
        lookups.order(raw_order_id)

    # step 5: request shape
    kind = valid.req_enum(data, "kind", KINDS)
    officer_id = valid.req_id(data, "officer_id")
    scheduled_start = valid.req_dt(data, "scheduled_start")
    scheduled_end = valid.req_dt(data, "scheduled_end")
    if scheduled_end <= scheduled_start:
        valid.bad("scheduled_end must be strictly after scheduled_start.")
    minutes = (scheduled_end - scheduled_start).total_seconds() / 60.0
    if minutes < calc.INSPECTION_MIN_DURATION_MINUTES or minutes > calc.INSPECTION_MAX_DURATION_MINUTES:
        valid.bad("The visit window must run between 30 and 240 minutes inclusive.")
    complaint = None
    order = None
    if kind == "INITIAL":
        complaint_id = valid.req_id(data, "complaint_id")
        complaint = lookups.complaint(complaint_id)
    else:
        order_id = valid.req_id(data, "abatement_order_id")
        order = lookups.order(order_id)
    officer = lookups.officer(officer_id)

    # step 8: related-entity state
    if kind == "INITIAL":
        if complaint["status"] != "TRIAGED":
            raise ApiError("ERR_COMPLAINT_NOT_TRIAGED")
        property_id = complaint["property_id"]
    else:
        if order["status"] != "SERVED":
            raise ApiError("ERR_ORDER_NOT_SERVED")
        property_id = order["property_id"]

    # step 9: segregation of duties on re-inspections
    if kind == "REINSPECTION":
        origin = store.inspections.get(order["inspection_id"])
        if origin is not None and origin["officer_id"] == officer_id:
            raise ApiError("ERR_REINSPECTION_SAME_OFFICER")

    # step 11: officer availability (closed comparison, 30-minute travel buffer)
    buffer = datetime.timedelta(minutes=calc.OFFICER_TRAVEL_BUFFER_MINUTES)
    for other in store.inspections.values():
        if other["officer_id"] != officer_id or other["status"] not in BUSY:
            continue
        if scheduled_start <= other["scheduled_end"] + buffer and \
                other["scheduled_start"] <= scheduled_end + buffer:
            raise ApiError("ERR_OFFICER_SCHEDULE_CONFLICT")

    # step 12: site availability (half-open, no buffer) then the re-inspection window
    for other in store.inspections.values():
        if other["property_id"] != property_id or other["status"] not in BUSY:
            continue
        if scheduled_start < other["scheduled_end"] and other["scheduled_start"] < scheduled_end:
            raise ApiError("ERR_PROPERTY_INSPECTION_OVERLAP")
    if kind == "REINSPECTION":
        deadline = order["compliance_deadline"]
        if deadline is not None and scheduled_start < deadline:
            raise ApiError("ERR_REINSPECTION_TOO_EARLY")

    inspection = store.stamp_new(
        {
            "complaint_id": complaint["id"] if complaint is not None else None,
            "abatement_order_id": order["id"] if order is not None else None,
            "property_id": property_id,
            "officer_id": officer_id,
            "kind": kind,
            "scheduled_start": scheduled_start,
            "scheduled_end": scheduled_end,
            "status": "SCHEDULED",
            "result": None,
            "notes": None,
            "started_at": None,
            "completed_at": None,
        }
    )
    store.inspections[inspection["id"]] = inspection
    refresh_assignment_count(officer_id)
    if kind == "INITIAL":
        complaint["status"] = "INSPECTION_SCHEDULED"
        store.touch(complaint)
    else:
        order["status"] = "REINSPECTION_SCHEDULED"
        store.touch(order)
    return envelope.obj(serialize.inspection(inspection), 201)


@bp.get(P + "/inspections/<inspection_id>")
def read_inspection(inspection_id):
    auth.guard("ProgramAdmin", "Supervisor", "Inspector", "IntakeClerk")
    inspection = lookups.inspection(inspection_id)
    return envelope.obj(serialize.inspection(inspection))


@bp.get(P + "/inspections")
def list_inspections():
    auth.guard("ProgramAdmin", "Supervisor", "Inspector", "IntakeClerk")
    limit, offset = valid.pagination()
    filters = {
        "complaint_id": valid.query_str("complaint_id"),
        "abatement_order_id": valid.query_str("abatement_order_id"),
        "property_id": valid.query_str("property_id"),
        "officer_id": valid.query_str("officer_id"),
        "status": valid.query_str("status"),
        "kind": valid.query_str("kind"),
    }

    def keep(i):
        for field, expected in filters.items():
            if expected is not None and i[field] != expected:
                return False
        return True

    rows = store.ordered(store.inspections, keep)
    return lookups.page(rows, limit, offset, serialize.inspection)


@bp.post(P + "/inspections/<inspection_id>/start")
def start_inspection(inspection_id):
    caller = auth.guard("Inspector")
    inspection = lookups.inspection(inspection_id)
    auth.require_officer(caller, inspection["officer_id"])
    if inspection["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE", "Only a SCHEDULED visit may be started.")
    officer = store.officers.get(inspection["officer_id"])
    if officer is None or officer["certification_expires_at"] <= lclock.now():
        raise ApiError("ERR_CERTIFICATION_EXPIRED")
    inspection["started_at"] = lclock.now()
    inspection["status"] = "IN_PROGRESS"
    store.touch(inspection)
    refresh_assignment_count(inspection["officer_id"])
    return envelope.obj(serialize.inspection(inspection))


@bp.post(P + "/inspections/<inspection_id>/assessments")
def create_assessment(inspection_id):
    caller = auth.guard("Inspector")
    inspection = lookups.inspection(inspection_id)
    auth.require_officer(caller, inspection["officer_id"])
    data = valid.body()
    harborage = valid.req_int(data, "harborage_score", minimum=0, maximum=10)
    attractant = valid.req_int(data, "attractant_score", minimum=0, maximum=10)
    sanitation = valid.req_int(data, "sanitation_score", minimum=0, maximum=10)
    burrow_count = valid.req_int(data, "burrow_count", minimum=0)
    evidence_photo_count = valid.opt_int(data, "evidence_photo_count", 0, minimum=0)
    recommended_actions = valid.opt_str_array(data, "recommended_actions", [])
    if inspection["status"] != "IN_PROGRESS":
        raise ApiError("ERR_INVALID_STATE", "Only an IN_PROGRESS visit may record an assessment.")
    if assessment_for(inspection["id"]) is not None:
        raise ApiError("ERR_ASSESSMENT_ALREADY_EXISTS")

    index, tier = calc.assessment_infestation_index(
        harborage, attractant, sanitation, burrow_count
    )
    assessment = store.stamp_new(
        {
            "inspection_id": inspection["id"],
            "harborage_score": harborage,
            "attractant_score": attractant,
            "sanitation_score": sanitation,
            "burrow_count": burrow_count,
            "evidence_photo_count": evidence_photo_count,
            "recommended_actions": recommended_actions,
            "infestation_index": index,
            "infestation_tier": tier,
        },
        versioned=False,
    )
    store.assessments[assessment["id"]] = assessment
    # PROVISIONAL variant of property_chronic_score; chronic_flag is NOT touched.
    prop = store.properties.get(inspection["property_id"])
    if prop is not None:
        prop["provisional_chronic_score"] = calc.chronic_score_provisional(index)
        store.touch(prop)
    return envelope.obj(serialize.assessment(assessment), 201)


@bp.get(P + "/inspections/<inspection_id>/assessments")
def list_assessments(inspection_id):
    auth.guard("ProgramAdmin", "Supervisor", "Inspector")
    inspection = lookups.inspection(inspection_id)
    limit, offset = valid.pagination()
    rows = store.ordered(
        store.assessments, lambda a: a["inspection_id"] == inspection["id"]
    )
    return lookups.page(rows, limit, offset, serialize.assessment)


@bp.post(P + "/inspections/<inspection_id>/complete")
def complete_inspection(inspection_id):
    caller = auth.guard("Inspector")
    inspection = lookups.inspection(inspection_id)
    auth.require_officer(caller, inspection["officer_id"])
    data = valid.body()
    result = valid.req_enum(data, "result", RESULTS)
    notes = valid.opt_str(data, "notes")
    if inspection["status"] != "IN_PROGRESS":
        raise ApiError("ERR_INVALID_STATE", "Only an IN_PROGRESS visit may be completed.")
    kind = inspection["kind"]
    allowed = INITIAL_RESULTS if kind == "INITIAL" else REINSPECTION_RESULTS
    if result not in allowed:
        raise ApiError("ERR_RESULT_KIND_MISMATCH")
    if result == "VIOLATION_FOUND" and assessment_for(inspection["id"]) is None:
        raise ApiError("ERR_ASSESSMENT_REQUIRED")

    now = lclock.now()
    inspection["completed_at"] = now
    inspection["result"] = result
    inspection["notes"] = notes
    inspection["status"] = "COMPLETED"
    store.touch(inspection)
    refresh_assignment_count(inspection["officer_id"])
    prop = store.properties.get(inspection["property_id"])
    if prop is not None:
        prop["last_inspection_at"] = now
        store.touch(prop)

    if kind == "INITIAL":
        complaint = store.complaints.get(inspection["complaint_id"])
        if result == "VIOLATION_FOUND":
            if complaint is not None and complaint["status"] == "INSPECTION_SCHEDULED":
                complaint["status"] = "INSPECTED"
                store.touch(complaint)
            if prop is not None:
                flows.recompute_chronic_reviewed(prop)
        elif result == "NO_VIOLATION":
            if complaint is not None and complaint["status"] == "INSPECTION_SCHEDULED":
                flows.close_complaint(complaint, "CLOSED_NO_VIOLATION", "NO_VIOLATION")
        elif result == "NO_ACCESS":
            if complaint is not None and complaint["status"] == "INSPECTION_SCHEDULED":
                complaint["status"] = "TRIAGED"
                store.touch(complaint)
    else:
        order = store.orders.get(inspection["abatement_order_id"])
        if order is not None and order["status"] == "REINSPECTION_SCHEDULED":
            if result == "COMPLIANT":
                flows.order_reaches_terminal(order, "COMPLIED")
            elif result == "NON_COMPLIANT":
                order["status"] = "ESCALATED"
                order["escalation_level"] = min(
                    calc.ESCALATION_MAX_LEVEL, order["escalation_level"] + 1
                )
                store.bump(order)
            elif result == "NO_ACCESS":
                order["status"] = "SERVED"
                store.touch(order)
    return envelope.obj(serialize.inspection(inspection))
