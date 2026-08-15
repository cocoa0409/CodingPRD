"""InspectionEvent endpoints."""

from datetime import timedelta

from flask import Blueprint, request

from db import store
from middleware import (
    require_roles, ALL_ROLES,
    ROLE_CONTRACTOR_ADMIN, ROLE_TECHNICIAN,
)
from response import success_object, list_response
from util import get_body, check_unknown_fields, req_str, req_datetime
from errors import (
    invalid_state, invalid_date_range, cross_reference_mismatch,
    technician_not_assigned, technician_capacity, license_not_valid,
    system_out_of_service, posture_blocked, event_not_yet_due,
)
from services.core import (
    base_record, public, touch,
    get_plan, get_event, ref_system, ref_technician,
    contractor_of_plan, property_of_plan, property_of_event,
    require_contractor_active, require_property_active,
)
from services import calc

bp = Blueprint("events", __name__)

TERMINAL_EVENT_STATES = {"COMPLETED", "CANCELLED", "NO_ACCESS"}


def _gates_for_plan(plan):
    prop = property_of_plan(plan)
    con = contractor_of_plan(plan)
    require_contractor_active(con)
    require_property_active(prop)
    return prop, con


@bp.route("/fire-compliance/inspection-plans/<pid>/events", methods=["POST"])
def create_event(pid):
    require_roles([ROLE_CONTRACTOR_ADMIN])
    plan = get_plan(pid)
    body = get_body()
    check_unknown_fields(body, {"system_id", "lead_technician_id", "scheduled_start", "scheduled_end"})
    system_id = req_str(body, "system_id")
    lead_technician_id = req_str(body, "lead_technician_id")
    scheduled_start = req_datetime(body, "scheduled_start")
    scheduled_end = req_datetime(body, "scheduled_end")
    # body FK existence (priority 4)
    sys = ref_system(system_id)
    tech = ref_technician(lead_technician_id)
    # parent gates (6)
    prop, con = _gates_for_plan(plan)
    if plan["plan_posture"] in ("FULFILLED", "LAPSED"):
        raise invalid_state("Plan is terminal; no new events")
    if sys["status"] != "IN_SERVICE":
        raise invalid_state("ProtectedSystem is DECOMMISSIONED; scheduling halted")
    if tech["status"] != "ACTIVE":
        raise invalid_state("Technician is INACTIVE; may not be newly assigned")
    # date range (10): end strictly after start
    if not scheduled_end > scheduled_start:
        raise invalid_date_range("scheduled_end must be strictly after scheduled_start")
    # technician aggregate capacity (12): at most 3 overlapping SCHEDULED /
    # IN_PROGRESS engagements, closed-closed interval intersection
    overlapping = 0
    for ev in store.events.values():
        if ev["lead_technician_id"] != tech["id"]:
            continue
        if ev["status"] not in ("SCHEDULED", "IN_PROGRESS"):
            continue
        if scheduled_start <= ev["scheduled_end"] and ev["scheduled_start"] <= scheduled_end:
            overlapping += 1
    if overlapping >= calc.TECH_CAPACITY_MAX:
        raise technician_capacity("Lead technician already leads 3 overlapping engagements")
    # cross-aggregate integrity (15): system must belong to the plan's property
    if sys["property_id"] != plan["property_id"]:
        raise cross_reference_mismatch("system_id does not belong to the plan's property")

    rec = base_record()
    rec.update({
        "plan_id": plan["id"],
        "system_id": sys["id"],
        "lead_technician_id": tech["id"],
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
        "completed_at": None,
        "report_due_date": None,
        "status": "SCHEDULED",
        "_on_time": False,
    })
    store.events[rec["id"]] = rec
    return success_object(public(rec), status=201)


@bp.route("/fire-compliance/inspection-plans/<pid>/events", methods=["GET"])
def list_events_of_plan(pid):
    require_roles(ALL_ROLES)
    plan = get_plan(pid)
    status = request.args.get("status")
    rows = [e for e in store.events.values() if e["plan_id"] == plan["id"]]
    if status is not None:
        rows = [e for e in rows if e["status"] == status]
    return list_response(rows, request.args, public)


@bp.route("/fire-compliance/inspection-events/<eid>", methods=["GET"])
def fetch_event(eid):
    require_roles(ALL_ROLES)
    return success_object(public(get_event(eid)))


@bp.route("/fire-compliance/inspection-events", methods=["GET"])
def list_events_cross():
    require_roles(ALL_ROLES)
    lead = request.args.get("lead_technician_id")
    system_id = request.args.get("system_id")
    status = request.args.get("status")
    rows = list(store.events.values())
    if lead is not None:
        rows = [e for e in rows if e["lead_technician_id"] == lead]
    if system_id is not None:
        rows = [e for e in rows if e["system_id"] == system_id]
    if status is not None:
        rows = [e for e in rows if e["status"] == status]
    return list_response(rows, request.args, public)


def _require_lead(ev, user_id):
    if ev["lead_technician_id"] != user_id:
        raise technician_not_assigned("Acting technician is not the event's lead")


@bp.route("/fire-compliance/inspection-events/<eid>/start", methods=["POST"])
def start_event(eid):
    _, user_id = require_roles([ROLE_TECHNICIAN])
    ev = get_event(eid)
    # transition legality (5)
    if ev["status"] != "SCHEDULED":
        raise invalid_state("Event is not SCHEDULED")
    # acting technician must be the assigned lead
    _require_lead(ev, user_id)
    # parent gates (6): contractor ACTIVE and posture != SUSPENDED
    con = contractor_of_plan(store.plans.get(ev["plan_id"]))
    require_contractor_active(con)
    if con is not None and con["posture"] == "SUSPENDED":
        raise posture_blocked("Contractor is SUSPENDED")
    # license validity (7): ACTIVE license of the mapped class, expires strictly
    # after the event's scheduled date
    sys = store.systems.get(ev["system_id"])
    required_class = calc.LICENSE_CLASS_FOR_CATEGORY[sys["system_category"]]
    scheduled_date = ev["scheduled_start"].date()
    if not calc.technician_has_valid_license(ev["lead_technician_id"], required_class, scheduled_date):
        raise license_not_valid("Lead technician lacks an ACTIVE license of the required class valid past the scheduled date")
    # impairment gate (8): system must not be OUT_OF_SERVICE
    if sys["impairment_status"] == "OUT_OF_SERVICE":
        raise system_out_of_service("System is OUT_OF_SERVICE")

    ev["status"] = "IN_PROGRESS"
    touch(ev)
    plan = store.plans.get(ev["plan_id"])
    if plan is not None:
        calc.derive_plan_posture(plan)
    if con is not None:
        calc.recompute_contractor(con)
    return success_object(public(ev))


@bp.route("/fire-compliance/inspection-events/<eid>/complete", methods=["POST"])
def complete_event(eid):
    _, user_id = require_roles([ROLE_TECHNICIAN])
    ev = get_event(eid)
    if ev["status"] != "IN_PROGRESS":
        raise invalid_state("Event is not IN_PROGRESS")
    _require_lead(ev, user_id)
    con = contractor_of_plan(store.plans.get(ev["plan_id"]))
    require_contractor_active(con)

    now = store.now()
    completed_date = now.date()
    ev["completed_at"] = now
    ev["report_due_date"] = completed_date + timedelta(days=calc.MARSHAL_REPORT_WINDOW_DAYS)
    # on-time snapshot for the audited-score bonus: completion on/before the
    # latest covered-device due date (due dates as of now, pre-recompute)
    covered = calc.covered_devices_of_event(ev)
    if covered:
        latest_due = max(d["next_due_date"] for d in covered)
        ev["_on_time"] = completed_date <= latest_due
    else:
        ev["_on_time"] = False
    ev["status"] = "COMPLETED"
    touch(ev)
    # every covered device: next_due recomputes from the completion date
    for dev in covered:
        new_due = calc.device_next_due_from_base(completed_date, dev["frequency_code"])
        if dev["next_due_date"] != new_due:
            dev["next_due_date"] = new_due
            touch(dev)
    # every OPEN deficiency recorded on this event receives its correction
    # deadline measured from the completion date
    for d in store.deficiencies.values():
        if d["event_id"] == ev["id"] and d["status"] == "OPEN" and d["correction_deadline"] is None:
            d["correction_deadline"] = completed_date + timedelta(
                days=calc.correction_window_days(d["classification"]))
            touch(d)
    # parent plan: events_completed += 1; posture re-evaluates (may FULFILL)
    plan = store.plans.get(ev["plan_id"])
    if plan is not None:
        from services.core import set_fields
        set_fields(plan, events_completed=sum(
            1 for e in store.events.values()
            if e["plan_id"] == plan["id"] and e["status"] == "COMPLETED"))
        calc.derive_plan_posture(plan)
    # auto-create the 1:1 DRAFT marshal report
    report = base_record()
    report.update({
        "event_id": ev["id"],
        "portal_submission_id": None,
        "submitted_at": None,
        "is_late": False,
        "revision_of_id": None,
        "status": "DRAFT",
    })
    store.reports[report["id"]] = report
    if con is not None:
        calc.recompute_contractor(con)
    return success_object(public(ev))


@bp.route("/fire-compliance/inspection-events/<eid>/cancel", methods=["POST"])
def cancel_event(eid):
    require_roles([ROLE_CONTRACTOR_ADMIN])
    ev = get_event(eid)
    if ev["status"] != "SCHEDULED":
        raise invalid_state("Event is not SCHEDULED")
    prop, con = _gates_for_plan(store.plans.get(ev["plan_id"]))

    ev["status"] = "CANCELLED"
    touch(ev)
    plan = store.plans.get(ev["plan_id"])
    if plan is not None:
        calc.recompute_plan_totals(plan)
        calc.derive_plan_posture(plan)
    if con is not None:
        calc.recompute_contractor(con)
    return success_object(public(ev))


@bp.route("/fire-compliance/inspection-events/<eid>/mark-no-access", methods=["POST"])
def mark_no_access(eid):
    _, user_id = require_roles([ROLE_TECHNICIAN])
    ev = get_event(eid)
    if ev["status"] != "SCHEDULED":
        raise invalid_state("Event is not SCHEDULED")
    _require_lead(ev, user_id)
    con = contractor_of_plan(store.plans.get(ev["plan_id"]))
    require_contractor_active(con)
    if store.now() < ev["scheduled_start"]:
        raise event_not_yet_due("Current time is before the event's scheduled start")

    # covered devices keep their old next_due_date: a missed inspection does
    # NOT roll the due date forward
    ev["status"] = "NO_ACCESS"
    touch(ev)
    plan = store.plans.get(ev["plan_id"])
    if plan is not None:
        calc.derive_plan_posture(plan)
    if con is not None:
        calc.recompute_contractor(con)
    return success_object(public(ev))
