"""OutageTicket endpoints (PRD 3.6): duplicate linking, SLA, replacement cascade."""
from datetime import timedelta

from flask import Blueprint

from db import new_record, store, touch
from domain import (
    REPLACEMENT_STOP_MINUTES, SLA_HOURS, compute_ticket_priority,
    escalate_priority, estimate_labor_cents, evaluate_auto_suspension,
    program_of_ticket, require_active, ser_ticket,
)
from errors import raise_error
from middleware import ALL_ROLES, get_caller, locked, require_roles
from response import success_object
from util import CLOCK
from validate import get_body, opt_bool, req_enum, req_str
from routes.common import list_endpoint, require_record

bp = Blueprint("tickets", __name__)

PM = ["ProgramManager"]
FS = ["FieldSupervisor"]
CR = ["CitizenReporter"]
RESOLUTION_CODES = ["LIGHT_OUT_FIXED", "FIXTURE_REPLACED", "NO_FAULT_FOUND"]
DUPLICATE_CANDIDATE_STATES = ("OPEN", "TRIAGED", "DISPATCHED", "RESOLVED", "REOPENED")
REPAIR_ELIGIBLE_POLE_STATES = ("SCHEDULED", "CONVERTED", "REWORK", "VERIFIED", "UNDER_REPAIR")


@bp.route("/streetlights/outage-tickets", methods=["POST"])
@locked
def create_ticket():
    caller = get_caller()
    body = get_body()
    pole_id = req_str(body, "pole_id")
    description = req_str(body, "description")
    hazard_flag = opt_bool(body, "hazard_flag", default=False)
    require_roles(caller, CR)
    pole = store.poles.get(pole_id)
    if pole is None:
        raise_error("ERR_POLE_NOT_FOUND", f"pole not found: {pole_id}")
    require_active(program_of_ticket({"pole_id": pole_id}))
    if pole["status"] == "EXEMPT":
        raise_error("ERR_POLE_EXEMPT", "reports against an EXEMPT pole are refused")
    # ticket_duplicate_selector: earliest-created non-terminal candidate.
    candidates = [t for t in store.tickets.values()
                  if t["pole_id"] == pole_id and t["status"] in DUPLICATE_CANDIDATE_STATES]
    candidates.sort(key=lambda t: t["_seq"])
    duplicate_of = candidates[0]["id"] if candidates else None
    rec = new_record("tickets", {
        "pole_id": pole_id,
        "reporter_user_id": caller.user_id,
        "description": description,
        "hazard_flag": hazard_flag,
        "duplicate_of_ticket_id": duplicate_of,
        "priority": None,
        "sla_hours": None,
        "sla_breached": None,
        "assigned_crew_id": None,
        "reported_at": CLOCK.now_iso(),
        "resolved_at": None,
        "resolution_code": None,
        "reopen_count": 0,
        "status": "DUPLICATE" if duplicate_of else "OPEN",
    })
    rec["_reported_dt"] = CLOCK.now()
    return success_object(ser_ticket(rec), status=201)


@bp.route("/streetlights/outage-tickets", methods=["GET"])
@locked
def list_tickets():
    return list_endpoint("tickets", ser_ticket,
                         ["pole_id", "duplicate_of_ticket_id", "assigned_crew_id",
                          "status", "priority"])


@bp.route("/streetlights/outage-tickets/<tid>", methods=["GET"])
@locked
def get_ticket(tid):
    caller = get_caller()
    require_roles(caller, ALL_ROLES)
    rec = require_record("tickets", tid, "ERR_TICKET_NOT_FOUND")
    return success_object(ser_ticket(rec))


@bp.route("/streetlights/outage-tickets/<tid>/triage", methods=["POST"])
@locked
def triage_ticket(tid):
    caller = get_caller()
    require_roles(caller, PM)
    ticket = require_record("tickets", tid, "ERR_TICKET_NOT_FOUND")
    require_active(program_of_ticket(ticket))
    if ticket["status"] not in ("OPEN", "REOPENED"):
        raise_error("ERR_TICKET_NOT_OPEN", "triage requires status OPEN or REOPENED")
    if ticket["status"] == "OPEN":
        pole = store.poles[ticket["pole_id"]]
        district = store.districts[pole["district_id"]]
        ticket["priority"] = compute_ticket_priority(ticket, pole, district)
    # From REOPENED the escalated priority is retained and re-asserted.
    ticket["sla_hours"] = SLA_HOURS[ticket["priority"]]
    ticket["status"] = "TRIAGED"
    touch(ticket)
    return success_object(ser_ticket(ticket))


@bp.route("/streetlights/outage-tickets/<tid>/dispatch", methods=["POST"])
@locked
def dispatch_ticket(tid):
    caller = get_caller()
    body = get_body()
    crew_id = req_str(body, "crew_id")
    require_roles(caller, PM)
    ticket = require_record("tickets", tid, "ERR_TICKET_NOT_FOUND")
    crew = store.crews.get(crew_id)
    if crew is None:
        raise_error("ERR_CREW_NOT_FOUND", f"crew not found: {crew_id}")
    require_active(program_of_ticket(ticket))
    if ticket["status"] != "TRIAGED":
        raise_error("ERR_TICKET_NOT_TRIAGED", "dispatch requires a TRIAGED ticket")
    ticket["assigned_crew_id"] = crew_id
    ticket["status"] = "DISPATCHED"
    touch(ticket)
    return success_object(ser_ticket(ticket))


def _cascade_fixture_replaced(ticket, crew):
    """PRD 3.6 replacement cascade: pole -> UNDER_REPAIR (pre_repair_status
    recorded, retained across repeat episodes), replacement work order under
    the resolving crew, the pole's PENDING stop -> BLOCKED, auto-suspension."""
    pole = store.poles.get(ticket["pole_id"])
    if pole is None or pole["status"] not in REPAIR_ELIGIBLE_POLE_STATES:
        return
    if pole["status"] != "UNDER_REPAIR":
        pole["pre_repair_status"] = pole["status"]
        pole["status"] = "UNDER_REPAIR"
        touch(pole)
        for s in store.stops.values():
            if s["pole_id"] == pole["id"] and s["status"] == "PENDING":
                s["status"] = "BLOCKED"
                touch(s)
                route = store.routes.get(s["route_id"])
                if route is not None:
                    evaluate_auto_suspension(route)
    new_record("work_orders", {
        "route_id": None,
        "stop_id": None,
        "pole_id": pole["id"],
        "crew_id": crew["id"],
        "ticket_id": ticket["id"],
        "is_replacement": True,
        "stop_minutes": REPLACEMENT_STOP_MINUTES,
        "new_fixture_wattage": None,
        "new_cct_kelvin": None,
        "shielding": None,
        "estimated_labor_cost_cents": estimate_labor_cents(crew, REPLACEMENT_STOP_MINUTES),
        "est_reconciled": False,
        "cumulative_week_minutes_before": None,
        "overtime_minutes": None,
        "labor_cost_cents": None,
        "performed_by_user_id": None,
        "qc_by_user_id": None,
        "completed_at": None,
        "_completed_dt": None,
        "execution_status": "PENDING",
        "qc_status": "NONE",
    })


@bp.route("/streetlights/outage-tickets/<tid>/resolve", methods=["POST"])
@locked
def resolve_ticket(tid):
    caller = get_caller()
    body = get_body()
    resolution_code = req_enum(body, "resolution_code", RESOLUTION_CODES)
    require_roles(caller, FS)
    ticket = require_record("tickets", tid, "ERR_TICKET_NOT_FOUND")
    # Stage 5 ownership: resolving FieldSupervisor is the assigned crew.
    if caller.user_id != ticket["assigned_crew_id"]:
        raise_error("ERR_FORBIDDEN", "only the assigned crew may resolve this ticket")
    require_active(program_of_ticket(ticket))
    if ticket["status"] != "DISPATCHED":
        raise_error("ERR_TICKET_NOT_DISPATCHED", "resolve requires a DISPATCHED ticket")
    resolved_dt = CLOCK.now()
    reported_dt = ticket.get("_reported_dt")
    elapsed_hours = (resolved_dt - reported_dt).total_seconds() / 3600.0
    ticket["sla_breached"] = elapsed_hours > ticket["sla_hours"]
    ticket["resolved_at"] = CLOCK.now_iso()
    ticket["_resolved_dt"] = resolved_dt
    ticket["resolution_code"] = resolution_code
    ticket["status"] = "RESOLVED"
    touch(ticket)
    if resolution_code == "FIXTURE_REPLACED":
        crew = store.crews[ticket["assigned_crew_id"]]
        _cascade_fixture_replaced(ticket, crew)
    return success_object(ser_ticket(ticket))


@bp.route("/streetlights/outage-tickets/<tid>/verify", methods=["POST"])
@locked
def verify_ticket(tid):
    caller = get_caller()
    require_roles(caller, CR)
    ticket = require_record("tickets", tid, "ERR_TICKET_NOT_FOUND")
    if caller.user_id != ticket["reporter_user_id"]:
        raise_error("ERR_FORBIDDEN", "only the reporter may verify this ticket")
    require_active(program_of_ticket(ticket))
    if ticket["status"] != "RESOLVED":
        raise_error("ERR_TICKET_NOT_RESOLVED", "verify requires a RESOLVED ticket")
    ticket["status"] = "VERIFIED"
    touch(ticket)
    return success_object(ser_ticket(ticket))


@bp.route("/streetlights/outage-tickets/<tid>/reopen", methods=["POST"])
@locked
def reopen_ticket(tid):
    caller = get_caller()
    require_roles(caller, CR)
    ticket = require_record("tickets", tid, "ERR_TICKET_NOT_FOUND")
    if caller.user_id != ticket["reporter_user_id"]:
        raise_error("ERR_FORBIDDEN", "only the reporter may reopen this ticket")
    require_active(program_of_ticket(ticket))
    if ticket["status"] != "RESOLVED":
        raise_error("ERR_TICKET_NOT_RESOLVED", "reopen requires a RESOLVED ticket")
    # Within resolved_at + 72h, inclusive of exactly 72 hours.
    if CLOCK.now() > ticket["_resolved_dt"] + timedelta(hours=72):
        raise_error("ERR_REOPEN_WINDOW_EXPIRED", "reopen window (72h) has expired")
    ticket["reopen_count"] += 1
    ticket["priority"] = escalate_priority(ticket["priority"])
    ticket["sla_hours"] = SLA_HOURS[ticket["priority"]]
    # The SLA clock deliberately does not reset: reported_at is unchanged.
    ticket["status"] = "REOPENED"
    touch(ticket)
    return success_object(ser_ticket(ticket))
