"""CrewCall endpoints: publish/confirm/complete/cancel lifecycle."""

from __future__ import annotations

from flask import Blueprint

import db
from errors import (
    raise_err,
    ERR_INVALID_STATE,
    ERR_RESOURCE_NOT_FOUND,
    ERR_CREW_CALL_LATE,
    ERR_CREW_HEADCOUNT_UNMET,
    ERR_TOO_EARLY,
)
from middleware import require_roles
from response import success_object, success_list
from services import calculations as calc
from services.domain import (
    check_declared,
    check_terminal,
    check_transition_owner,
    minus_hours,
    parse_to,
)
from util import (
    get_json_body,
    paginate,
    parse_iso8601,
    parse_pagination,
    serialize,
    serialize_list,
    sort_by_created_at,
)

bp = Blueprint("crew_calls", __name__)

CALL_STATES = {"DRAFT", "PUBLISHED", "CONFIRMED", "COMPLETED", "CANCELLED"}
CALL_TERMINAL = {"COMPLETED", "CANCELLED"}
CALL_TO_OWNERS = {
    "PUBLISHED": {"ProductionManager"},
    "CONFIRMED": {"ProductionManager"},
    "COMPLETED": {"ProductionManager"},
    "CANCELLED": {"ProductionManager"},
}
CALL_DECLARED = {
    "DRAFT": {"PUBLISHED", "CANCELLED"},
    "PUBLISHED": {"CONFIRMED", "CANCELLED"},
    "CONFIRMED": {"COMPLETED", "CANCELLED"},
}


def get_call_or_404(call_id: str) -> dict:
    call = db.crew_calls.get(call_id)
    if call is None:
        raise_err(ERR_RESOURCE_NOT_FOUND, "CrewCall id does not exist")
    return call


@bp.route("/crew-calls/<call_id>", methods=["GET"])
@require_roles("Any")
def get_call(call_id: str, _user_id: str, _role: str):
    return success_object(serialize(get_call_or_404(call_id)))


@bp.route("/crew-calls/<call_id>/assignments", methods=["GET"])
@require_roles("Any")
def list_call_assignments(call_id: str, _user_id: str, _role: str):
    get_call_or_404(call_id)
    limit, offset = parse_pagination()
    items = [a for a in db.crew_assignments.values() if a["crew_call_id"] == call_id]
    items = sort_by_created_at(items)
    page, total = paginate(items, limit, offset)
    return success_list(serialize_list(page), limit, offset, total)


@bp.route("/crew-calls/<call_id>/transition", methods=["POST"])
@require_roles("ProductionManager")
def transition_call(call_id: str, _user_id: str, _role: str):
    body = get_json_body()
    to = parse_to(body, CALL_STATES)
    check_transition_owner(to, CALL_TO_OWNERS, _role)
    call = get_call_or_404(call_id)
    check_terminal(call, CALL_TERMINAL, to, CALL_DECLARED)
    check_declared(call, to, CALL_DECLARED)

    production = db.productions.get(call["production_id"])
    venue = db.venues.get(production["venue_id"])
    clock = db.clock_dt()

    if to == "PUBLISHED":
        deadline = minus_hours(
            parse_iso8601(call["call_start"], "call_start"),
            venue["crew_call_publish_lead_hours"],
        )
        if clock > deadline:
            raise_err(ERR_CREW_CALL_LATE, "Publish is past the contractual lead window")
        call["status"] = "PUBLISHED"
        db.touch(call)
        calc.refresh_posture(production)
        return success_object(serialize(call))

    if to == "CONFIRMED":
        confirmed = sum(
            1
            for a in db.crew_assignments.values()
            if a["crew_call_id"] == call["id"] and a["status"] == "CONFIRMED"
        )
        if confirmed < call["required_headcount"]:
            raise_err(ERR_CREW_HEADCOUNT_UNMET, "Confirmed assignments below required_headcount")
        call["status"] = "CONFIRMED"
        db.touch(call)
        calc.refresh_posture(production)
        return success_object(serialize(call))

    if to == "COMPLETED":
        assignments = [a for a in db.crew_assignments.values() if a["crew_call_id"] == call["id"]]
        for a in assignments:
            if a["status"] not in ("WORKED", "NO_SHOW", "CANCELLED"):
                raise_err(
                    ERR_INVALID_STATE,
                    "Every assignment must be WORKED, NO_SHOW, or CANCELLED to complete",
                )
        if clock < parse_iso8601(call["call_end"], "call_end"):
            raise_err(ERR_TOO_EARLY, "Logical clock has not reached call_end")
        total = 0
        for a in assignments:
            if a["status"] != "WORKED":
                continue
            technician = db.technicians.get(a["technician_id"])
            charge = calc.compute_labor_charge(technician, a["worked_hours"], venue)
            a["labor_charge_cents"] = charge
            a["status"] = "RECONCILED"
            db.touch(a)
            total += charge
        call["labor_cost_cents"] = total
        call["status"] = "COMPLETED"
        db.touch(call)
        calc.refresh_posture(production)
        return success_object(serialize(call))

    # to == "CANCELLED"
    for a in db.crew_assignments.values():
        if a["crew_call_id"] == call["id"] and a["status"] in ("ASSIGNED", "CONFIRMED", "WORKED"):
            a["status"] = "CANCELLED"
            db.touch(a)
    call["status"] = "CANCELLED"
    db.touch(call)
    calc.refresh_posture(production)
    return success_object(serialize(call))
