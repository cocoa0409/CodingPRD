"""Program element and permit endpoints."""

from datetime import timedelta

from flask import Blueprint

import cascades
import derive
import serializers
from auth import (ALL_DMC_ROLES, ROLE_OPS_COORDINATOR, ROLE_PERMIT_OFFICER,
                  ROLE_PROGRAM_DIRECTOR, endpoint)
from common import (apply_filters, element_or_404, permit_or_404, program_or_404,
                    respond_list, supplier_or_404, venue_or_404)
from envelope import created, ok
from errors import fail
from store import clock_now, day_end, db, new_row, touch, whole_days_between
from validation import (body, opt_bool, opt_enum, opt_int, opt_str, ref_id, req_dt,
                        req_enum, req_int, req_str, strictly_after)

bp = Blueprint("elements", __name__)

ELEMENT_TYPES = ("ACTIVITY", "DINE_AROUND", "OFF_PREMISE_EVENT", "TRANSFER_BLOCK")
ELEMENT_STATUSES = ("PLANNED", "PERMIT_BLOCKED", "READY", "DELIVERED",
                    "WEATHER_SWITCHED", "CANCELLED")
PERMIT_TYPES = ("STREET_CLOSURE", "SPECIAL_VENUE", "OFF_PREMISE_ALCOHOL")
PERMIT_STATUSES = ("DRAFT", "SUBMITTED", "CONDITIONS_REQUESTED", "APPROVED", "DENIED")
PERMIT_DECISIONS = ("APPROVED", "DENIED", "CONDITIONS_REQUESTED")

_NO_ID = object()


# --------------------------------------------------------------------------
# shared graph and geometry checks
# --------------------------------------------------------------------------

def _check_acyclic(candidate_id, predecessor_id):
    seen = set()
    current = predecessor_id
    while current is not None:
        if current == candidate_id or current in seen:
            fail("ERR_ELEMENT_DEPENDENCY_CYCLE",
                 "The production timeline would contain a cycle.")
        seen.add(current)
        row = db.elements.get(current)
        if row is None:
            return
        current = row["predecessor_element_id"]


def _check_weather_alternative(program_id, alternative_id, predecessor_id):
    if alternative_id is None:
        return
    referenced = db.elements.get(alternative_id)
    if referenced is None:
        return
    if referenced["program_id"] != program_id:
        fail("ERR_INVALID_WEATHER_ALTERNATIVE",
             "The weather alternative must reference an element of the same programme.")
    if not referenced["is_weather_dependent"]:
        fail("ERR_INVALID_WEATHER_ALTERNATIVE",
             "The referenced element is not weather dependent.")
    if predecessor_id is not None and alternative_id == predecessor_id:
        fail("ERR_INVALID_WEATHER_ALTERNATIVE",
             "The weather alternative may not be the element's own predecessor.")
    if referenced["alternative_for_element_id"] is not None:
        fail("ERR_INVALID_WEATHER_ALTERNATIVE",
             "A rain plan for a rain plan is not permitted.")


def _check_venue_geometry(candidate_id, venue, starts_at, ends_at):
    buffer_delta = timedelta(minutes=int(venue["turnover_buffer_minutes"]))
    for incumbent in derive.elements_of_venue(venue["id"]):
        if incumbent["id"] == candidate_id:
            continue
        if incumbent["status"] not in derive.VENUE_OCCUPYING_STATUSES:
            continue
        if starts_at < incumbent["ends_at"] + buffer_delta \
                and incumbent["starts_at"] < ends_at:
            fail("ERR_VENUE_TURNOVER_CONFLICT",
                 "The venue occupation conflicts with an existing booking.")


def _check_venue_capacity(venue, element_type, planned_headcount):
    if venue["status"] != "ACTIVE":
        fail("ERR_VENUE_CAPACITY_EXCEEDED", "The venue is not ACTIVE.")
    if element_type == "DINE_AROUND":
        if planned_headcount > int(venue["capacity_seated"]):
            fail("ERR_VENUE_CAPACITY_EXCEEDED",
                 "planned_headcount exceeds the venue's seated capacity.")
    elif element_type in ("ACTIVITY", "OFF_PREMISE_EVENT"):
        if planned_headcount > int(venue["capacity_reception"]):
            fail("ERR_VENUE_CAPACITY_EXCEEDED",
                 "planned_headcount exceeds the venue's reception capacity.")


# --------------------------------------------------------------------------
# program elements
# --------------------------------------------------------------------------

@bp.post("/dmc/program-elements")
@endpoint((ROLE_PROGRAM_DIRECTOR,))
def create_element():
    data = body()

    program = None
    program_ref = ref_id(data, "program_id")
    if program_ref is not None:
        program = program_or_404(program_ref)
    supplier_ref = ref_id(data, "supplier_id")
    if supplier_ref is not None:
        supplier_or_404(supplier_ref)
    venue = None
    venue_ref = ref_id(data, "venue_id")
    if venue_ref is not None:
        venue = venue_or_404(venue_ref)
    predecessor_ref = ref_id(data, "predecessor_element_id")
    if predecessor_ref is not None:
        element_or_404(predecessor_ref)
    alternative_ref = ref_id(data, "alternative_for_element_id")
    if alternative_ref is not None:
        element_or_404(alternative_ref)

    program_id = req_str(data, "program_id", min_len=1)
    supplier_id = req_str(data, "supplier_id", min_len=1)
    element_type = req_enum(data, "element_type", ELEMENT_TYPES)
    title = req_str(data, "title", min_len=1)
    starts_at = req_dt(data, "starts_at")
    ends_at = req_dt(data, "ends_at")
    strictly_after(ends_at, starts_at, "ends_at", "starts_at")
    planned_headcount = req_int(data, "planned_headcount", minimum=0)
    guaranteed_headcount = req_int(data, "guaranteed_headcount", minimum=0)
    per_person_cost_cents = req_int(data, "per_person_cost_cents", minimum=0)
    expected_program_version = req_int(data, "expected_program_version")
    venue_id = venue_ref
    predecessor_element_id = predecessor_ref
    alternative_for_element_id = alternative_ref
    is_weather_dependent = opt_bool(data, "is_weather_dependent", default=False)
    if is_weather_dependent is None:
        is_weather_dependent = False

    if expected_program_version != program["version"]:
        fail("ERR_STALE_PROGRAM_VERSION",
             "expected_program_version does not match the programme's current version.")
    if program["execution_status"] != "DRAFT":
        fail("ERR_PROGRAM_DESIGN_LOCKED", "The programme's element set is frozen.")
    if starts_at < program["arrival_date"] or ends_at > day_end(program["departure_date"]):
        fail("ERR_ELEMENT_OUTSIDE_PROGRAM_WINDOW",
             "The element does not sit inside the programme window.")
    if venue is not None:
        _check_venue_geometry(None, venue, starts_at, ends_at)
    _check_acyclic(_NO_ID, predecessor_element_id)
    _check_weather_alternative(program_id, alternative_for_element_id,
                               predecessor_element_id)
    if venue is not None:
        _check_venue_capacity(venue, element_type, planned_headcount)

    row = new_row(
        program_id=program_id,
        supplier_id=supplier_id,
        venue_id=venue_id,
        predecessor_element_id=predecessor_element_id,
        alternative_for_element_id=alternative_for_element_id,
        element_type=element_type,
        title=title,
        starts_at=starts_at,
        ends_at=ends_at,
        planned_headcount=planned_headcount,
        guaranteed_headcount=guaranteed_headcount,
        per_person_cost_cents=per_person_cost_cents,
        is_weather_dependent=is_weather_dependent,
        actual_headcount=None,
        status="PLANNED",
        delivered_at=None,
        cancellation_penalty_cents=0,
    )
    db.elements[row["id"]] = row
    touch(program)
    return created(serializers.element(row))


@bp.get("/dmc/program-elements/<element_id>")
@endpoint(ALL_DMC_ROLES)
def read_element(element_id):
    return ok(serializers.element(element_or_404(element_id)))


@bp.get("/dmc/program-elements")
@endpoint(ALL_DMC_ROLES)
def list_elements():
    rows = apply_filters(list(db.elements.values()), [
        ("program_id", "program_id", None),
        ("supplier_id", "supplier_id", None),
        ("venue_id", "venue_id", None),
        ("predecessor_element_id", "predecessor_element_id", None),
        ("alternative_for_element_id", "alternative_for_element_id", None),
        ("status", "status", ELEMENT_STATUSES),
    ])
    return respond_list(rows, serializers.element)


@bp.patch("/dmc/program-elements/<element_id>")
@endpoint((ROLE_PROGRAM_DIRECTOR,))
def patch_element(element_id):
    element = element_or_404(element_id)
    data = body()

    predecessor_ref = ref_id(data, "predecessor_element_id")
    if predecessor_ref is not None:
        element_or_404(predecessor_ref)
    alternative_ref = ref_id(data, "alternative_for_element_id")
    if alternative_ref is not None:
        element_or_404(alternative_ref)

    title = None
    if "title" in data:
        title = req_str(data, "title", min_len=1)
    planned_headcount = None
    if "planned_headcount" in data:
        planned_headcount = req_int(data, "planned_headcount", minimum=0)
    is_weather_dependent = None
    if "is_weather_dependent" in data:
        is_weather_dependent = opt_bool(data, "is_weather_dependent",
                                        default=element["is_weather_dependent"])

    predecessor_element_id = element["predecessor_element_id"]
    if "predecessor_element_id" in data:
        predecessor_element_id = predecessor_ref
    alternative_for_element_id = element["alternative_for_element_id"]
    if "alternative_for_element_id" in data:
        alternative_for_element_id = alternative_ref

    program = db.programs.get(element["program_id"])
    if program is None or program["execution_status"] != "DRAFT":
        fail("ERR_PROGRAM_DESIGN_LOCKED", "The programme's element set is frozen.")

    _check_acyclic(element["id"], predecessor_element_id)
    _check_weather_alternative(element["program_id"], alternative_for_element_id,
                               predecessor_element_id)

    if title is not None:
        element["title"] = title
    if planned_headcount is not None:
        element["planned_headcount"] = planned_headcount
    if is_weather_dependent is not None:
        element["is_weather_dependent"] = is_weather_dependent
    element["predecessor_element_id"] = predecessor_element_id
    element["alternative_for_element_id"] = alternative_for_element_id
    touch(element)
    return ok(serializers.element(element))


@bp.post("/dmc/program-elements/<element_id>/mark-ready")
@endpoint((ROLE_OPS_COORDINATOR,))
def mark_element_ready(element_id):
    element = element_or_404(element_id)
    if element["status"] != "PLANNED":
        fail("ERR_INVALID_STATE_TRANSITION", "mark-ready requires status PLANNED.")
    program = db.programs.get(element["program_id"])
    if program is None or program["execution_status"] not in ("CONFIRMED", "IN_EXECUTION"):
        fail("ERR_PROGRAM_NOT_CONFIRMED",
             "The programme must be CONFIRMED or IN_EXECUTION.")
    if derive.element_has_blocking_permit(element_id):
        fail("ERR_PERMIT_NOT_APPROVED", "A permit of this element is still outstanding.")
    venue = db.venues.get(element["venue_id"]) if element["venue_id"] else None
    if venue is not None and venue["requires_special_venue_permit"]:
        if not derive.element_has_approved_special_venue_permit(element_id):
            fail("ERR_PERMIT_NOT_APPROVED",
                 "The venue requires an APPROVED SPECIAL_VENUE permit.")
    if derive.active_contract_for(element["program_id"], element["supplier_id"]) is None:
        fail("ERR_NO_ACTIVE_SUPPLIER_CONTRACT",
             "No ACTIVE supplier contract covers this element.")
    predecessor_id = element["predecessor_element_id"]
    if predecessor_id is not None:
        predecessor = db.elements.get(predecessor_id)
        if predecessor is None or predecessor["status"] != "DELIVERED":
            fail("ERR_PREDECESSOR_NOT_DELIVERED",
                 "The production-timeline predecessor has not been delivered.")

    element["status"] = "READY"
    touch(element)
    return ok(serializers.element(element))


@bp.post("/dmc/program-elements/<element_id>/deliver")
@endpoint((ROLE_OPS_COORDINATOR,))
def deliver_element(element_id):
    element = element_or_404(element_id)
    data = body()
    actual_headcount = req_int(data, "actual_headcount", minimum=0)
    if element["status"] != "READY":
        fail("ERR_INVALID_STATE_TRANSITION", "deliver requires status READY.")
    program = db.programs.get(element["program_id"])
    if program is None or program["execution_status"] != "IN_EXECUTION":
        fail("ERR_PROGRAM_NOT_IN_EXECUTION", "The programme is not IN_EXECUTION.")
    if clock_now() < element["starts_at"]:
        fail("ERR_ELEMENT_NOT_STARTED", "The element has not started yet.")

    element["status"] = "DELIVERED"
    element["actual_headcount"] = actual_headcount
    element["delivered_at"] = clock_now()
    touch(element)
    cascades.settle_staffing_on_delivery(element, program)
    cascades.bubble_program_completed(program)
    return ok(serializers.element(element))


@bp.post("/dmc/program-elements/<element_id>/weather-switch")
@endpoint((ROLE_OPS_COORDINATOR,))
def weather_switch_element(element_id):
    element = element_or_404(element_id)
    if element["status"] != "READY":
        fail("ERR_INVALID_STATE_TRANSITION", "weather-switch requires status READY.")
    if not element["is_weather_dependent"]:
        fail("ERR_ELEMENT_NOT_WEATHER_DEPENDENT",
             "The element is not weather dependent.")
    program = db.programs.get(element["program_id"])
    if program is None or program["execution_status"] != "IN_EXECUTION":
        fail("ERR_PROGRAM_NOT_IN_EXECUTION", "The programme is not IN_EXECUTION.")

    candidates = [e for e in derive.all_elements()
                  if e["alternative_for_element_id"] == element_id
                  and e["status"] == "PLANNED"]
    if not candidates:
        fail("ERR_NO_WEATHER_ALTERNATIVE", "No rain plan is available.")
    candidates.sort(key=lambda e: (e["starts_at"], e["created_at"], e["_seq"]))
    alternative = candidates[0]
    if derive.element_has_blocking_permit(alternative["id"]):
        fail("ERR_PERMIT_NOT_APPROVED",
             "The selected rain plan has an outstanding permit.")

    element["status"] = "WEATHER_SWITCHED"
    touch(element)
    alternative["status"] = "READY"
    touch(alternative)
    cascades.release_assignments_of_element(element, program)
    cascades.bubble_program_completed(program)
    return ok(serializers.element(element))


@bp.post("/dmc/program-elements/<element_id>/cancel")
@endpoint((ROLE_PROGRAM_DIRECTOR,))
def cancel_element(element_id):
    element = element_or_404(element_id)
    body()
    if element["status"] not in ("PLANNED", "PERMIT_BLOCKED", "READY"):
        fail("ERR_INVALID_STATE_TRANSITION", "The element can no longer be cancelled.")
    program = db.programs.get(element["program_id"])
    if program is not None and program["settlement_status"] != "NOT_STARTED":
        fail("ERR_PROGRAM_ALREADY_RECONCILING",
             "The settlement dimension has already left NOT_STARTED.")

    cascades.cancel_element(element, program)
    return ok(serializers.element(element))


# --------------------------------------------------------------------------
# permits
# --------------------------------------------------------------------------

@bp.post("/dmc/permits")
@endpoint((ROLE_PERMIT_OFFICER,))
def create_permit():
    data = body()
    element_ref = ref_id(data, "element_id")
    if element_ref is not None:
        element_or_404(element_ref)
    row = new_row(
        element_id=req_str(data, "element_id", min_len=1),
        permit_type=req_enum(data, "permit_type", PERMIT_TYPES),
        authority_name=req_str(data, "authority_name", min_len=1),
        lead_time_days_required=req_int(data, "lead_time_days_required", minimum=0),
        status="DRAFT",
        submitted_at=None,
        decision_at=None,
        conditions_note=None,
        resubmission_count=0,
    )
    db.permits[row["id"]] = row
    return created(serializers.permit(row))


@bp.get("/dmc/permits/<permit_id>")
@endpoint(ALL_DMC_ROLES)
def read_permit(permit_id):
    return ok(serializers.permit(permit_or_404(permit_id)))


@bp.get("/dmc/permits")
@endpoint(ALL_DMC_ROLES)
def list_permits():
    rows = apply_filters(list(db.permits.values()), [
        ("element_id", "element_id", None),
        ("status", "status", PERMIT_STATUSES),
    ])
    return respond_list(rows, serializers.permit)


@bp.post("/dmc/permits/<permit_id>/submit")
@endpoint((ROLE_PERMIT_OFFICER,))
def submit_permit(permit_id):
    permit = permit_or_404(permit_id)
    if permit["status"] not in ("DRAFT", "CONDITIONS_REQUESTED"):
        fail("ERR_INVALID_STATE_TRANSITION",
             "submit requires status DRAFT or CONDITIONS_REQUESTED.")
    element = db.elements.get(permit["element_id"])
    if element is None or element["status"] not in ("PLANNED", "PERMIT_BLOCKED"):
        fail("ERR_INVALID_STATE_TRANSITION",
             "The authorised element must be PLANNED or PERMIT_BLOCKED.")
    if whole_days_between(clock_now(), element["starts_at"]) \
            < int(permit["lead_time_days_required"]):
        fail("ERR_PERMIT_LEAD_TIME_INSUFFICIENT",
             "The submission does not meet the required lead time.")

    resubmission = permit["status"] == "CONDITIONS_REQUESTED"
    permit["status"] = "SUBMITTED"
    permit["submitted_at"] = clock_now()
    if resubmission:
        permit["resubmission_count"] = int(permit["resubmission_count"]) + 1
    touch(permit)
    return ok(serializers.permit(permit))


@bp.post("/dmc/permits/<permit_id>/record-decision")
@endpoint((ROLE_PERMIT_OFFICER,))
def record_permit_decision(permit_id):
    permit = permit_or_404(permit_id)
    data = body()
    decision = req_enum(data, "decision", PERMIT_DECISIONS)
    conditions_note = None
    if decision == "CONDITIONS_REQUESTED":
        conditions_note = req_str(data, "conditions_note", min_len=1)
    if permit["status"] != "SUBMITTED":
        fail("ERR_INVALID_STATE_TRANSITION", "record-decision requires status SUBMITTED.")

    element = db.elements.get(permit["element_id"])
    program = db.programs.get(element["program_id"]) if element else None

    permit["status"] = decision
    permit["decision_at"] = clock_now()
    if conditions_note is not None:
        permit["conditions_note"] = conditions_note
    touch(permit)

    if decision == "APPROVED":
        if element is not None and element["status"] == "PERMIT_BLOCKED" \
                and not derive.element_has_blocking_permit(element["id"]):
            element["status"] = "PLANNED"
            touch(element)
    elif decision == "DENIED":
        if element is not None:
            cascades.block_element(element, program)

    return ok(serializers.permit(permit))
