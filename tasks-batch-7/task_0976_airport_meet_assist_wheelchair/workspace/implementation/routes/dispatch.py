"""Dispatch and assignment lifecycle."""
import uuid
from datetime import timedelta

from flask import Blueprint

import db
from errors import (bad_request, invalid_state, posture_restricted,
                    segregation_of_duties, stale_version,
                    tsa_clearance_required, temporal_conflict)
from middleware import require_roles
from response import success_object
from routes.util import (get_or_404, json_body, require_enum, require_fields,
                         serialize_assignment)
from services import cascades, pricing, selectors

bp = Blueprint("dispatch", __name__)

ALL_ROLES = ("PlatformAdmin", "OpsManager", "Dispatcher", "Agent",
             "Confirmer", "BillingClerk")


@bp.post("/maa/legs/<lid>/dispatch")
def dispatch_leg(lid):
    user_id, _ = require_roles("Dispatcher")
    leg = get_or_404(db.legs, lid, "ServiceLeg")
    request = db.assist_requests[leg["assist_request_id"]]
    body = json_body()
    expected = body.get("expected_assist_request_version")
    if expected is None:
        raise bad_request("expected_assist_request_version is required")
    if not isinstance(expected, int) or isinstance(expected, bool):
        raise bad_request("expected_assist_request_version must be an integer")
    # OCC (priority 4) before state checks (priority 5)
    if expected != request["version"]:
        raise stale_version("expected_assist_request_version does not match current version")

    if leg["status"] != "PLANNED":
        raise invalid_state("Only PLANNED legs may be dispatched")
    if request["request_status"] not in {"SUBMITTED", "ASSIGNED"}:
        raise invalid_state("Parent request must be SUBMITTED or ASSIGNED")
    segment = db.segments[leg["segment_id"]]
    airport = db.airports[segment["airport_id"]]
    if airport["posture"] == "LOCKDOWN":
        raise posture_restricted("Airport is in LOCKDOWN")

    # TSA precondition: at least one candidate agent with tsa_cleared_until > now
    if leg.get("requires_tsa_escort") and not selectors.any_agent_with_tsa(airport["id"]):
        raise tsa_clearance_required("No candidate agent holds a valid TSA clearance")

    agent = selectors.select_agent(leg, airport["id"])

    chair = None
    if leg.get("requires_wheelchair"):
        chair = selectors.select_wheelchair(leg, airport["id"])

    now = db.now()
    asg = db.common_fields()
    asg.update({
        "assist_request_id": request["id"],
        "service_leg_id": leg["id"],
        "agent_id": agent["id"],
        "wheelchair_asset_id": chair["id"] if chair else None,
        "status": "DISPATCHED",
        "assigned_by_user_id": user_id,
        "completed_by_user_id": None,
        "umnr_second_signoff_user_id": None,
        "scheduled_completion_utc": leg["scheduled_pickup_utc"] + timedelta(
            minutes=selectors.estimate_transfer_minutes(leg["leg_kind"])),
        "tracking_token": "trk_" + uuid.uuid4().hex,
    })
    db.assignments[asg["id"]] = asg

    agent["active_assignment_count"] = agent.get("active_assignment_count", 0) + 1
    db.touch(agent)

    if chair is not None:
        chair["status"] = "CHECKED_OUT"
        chair["usage_count"] = chair.get("usage_count", 0) + 1
        db.touch(chair)

    leg["status"] = "DISPATCHED"
    db.touch(leg)

    cascades._maybe_advance_to_assigned(request["id"])
    db.touch(request)  # dispatch bumps parent AssistRequest.version by 1
    return success_object(serialize_assignment(asg), status=201)


@bp.get("/maa/assignments/<aid>")
def get_assignment(aid):
    require_roles(*ALL_ROLES)
    asg = get_or_404(db.assignments, aid, "Assignment")
    return success_object(serialize_assignment(asg))


@bp.get("/maa/assignments/<aid>/incidents")
def list_assignment_incidents(aid):
    from routes.util import list_response, serialize_incident
    require_roles(*ALL_ROLES)
    asg = get_or_404(db.assignments, aid, "Assignment")
    items = [i for i in db.incidents.values() if i["assignment_id"] == asg["id"]]
    return list_response(items, serialize_incident)


@bp.get("/maa/assignments/<aid>/tracking")
def list_assignment_tracking(aid):
    from routes.util import list_response, serialize_tracking_event
    require_roles(*ALL_ROLES)
    asg = get_or_404(db.assignments, aid, "Assignment")
    items = [t for t in db.tracking_events.values() if t["assignment_id"] == asg["id"]]
    return list_response(items, serialize_tracking_event)


# ---------------------------------------------------------------------------
# Assignment lifecycle events
# ---------------------------------------------------------------------------

@bp.post("/maa/assignments/<aid>/events")
def assignment_event(aid):
    user_id, role = require_roles("Agent", "Confirmer", "Dispatcher")
    asg = get_or_404(db.assignments, aid, "Assignment")
    body = json_body()
    require_fields(body, ["event_type"])
    event_type = require_enum(
        body["event_type"],
        {"ARRIVE_PICKUP", "DEPART_PICKUP", "ARRIVE_GATE", "HANDOFF",
         "COMPLETE", "MARK_NO_SHOW", "CANCEL_ASSIGN"},
        "event_type")

    leg = db.legs[asg["service_leg_id"]]
    request = db.assist_requests[asg["assist_request_id"]]
    segment = db.segments[leg["segment_id"]]
    airport = db.airports[segment["airport_id"]]
    now = db.now()

    # Role gating per event
    agent_events = {"ARRIVE_PICKUP", "DEPART_PICKUP", "ARRIVE_GATE", "HANDOFF"}
    if event_type in agent_events and role != "Agent":
        from errors import unauthorized
        raise unauthorized(f"{event_type} requires Agent role")
    if event_type == "COMPLETE" and role != "Confirmer":
        from errors import unauthorized
        raise unauthorized("COMPLETE requires Confirmer role")
    if event_type in {"MARK_NO_SHOW", "CANCEL_ASSIGN"} and role != "Dispatcher":
        from errors import unauthorized
        raise unauthorized(f"{event_type} requires Dispatcher role")

    # Agent-identity ownership for field events
    if event_type in agent_events and asg["agent_id"] != user_id:
        from errors import unauthorized
        raise unauthorized("Agent may only act on their own assignment")

    if event_type == "ARRIVE_PICKUP":
        if asg["status"] != "DISPATCHED":
            raise invalid_state("Assignment must be DISPATCHED")
        if airport["posture"] == "LOCKDOWN":
            raise posture_restricted("Airport is in LOCKDOWN")
        if leg.get("requires_tsa_escort"):
            agent = db.agents.get(asg["agent_id"])
            if agent is None or agent["tsa_cleared_until"] is None or agent["tsa_cleared_until"] <= now:
                raise tsa_clearance_required("Agent TSA clearance expired")
        asg["status"] = "AT_PICKUP"
        db.touch(asg)
        leg["status"] = "AT_PICKUP"
        leg["actual_pickup_utc"] = now
        db.touch(leg)
        cascades._maybe_advance_to_in_service(request["id"])
        db.touch(request)

    elif event_type == "DEPART_PICKUP":
        if asg["status"] != "AT_PICKUP":
            raise invalid_state("Assignment must be AT_PICKUP")
        if airport["posture"] == "LOCKDOWN":
            raise posture_restricted("Airport is in LOCKDOWN")
        asg["status"] = "IN_TRANSIT"
        db.touch(asg)
        leg["status"] = "IN_TRANSIT"
        db.touch(leg)
        db.touch(request)

    elif event_type == "ARRIVE_GATE":
        if asg["status"] != "IN_TRANSIT":
            raise invalid_state("Assignment must be IN_TRANSIT")
        if airport["posture"] == "LOCKDOWN":
            raise posture_restricted("Airport is in LOCKDOWN")
        asg["status"] = "AT_GATE"
        db.touch(asg)
        leg["status"] = "AT_GATE"
        db.touch(leg)
        db.touch(request)

    elif event_type == "HANDOFF":
        if asg["status"] != "AT_GATE":
            raise invalid_state("Assignment must be AT_GATE")
        if airport["posture"] == "LOCKDOWN":
            raise posture_restricted("Airport is in LOCKDOWN")
        if leg.get("requires_ummr_agent"):
            second = body.get("umnr_second_signoff_user_id")
            if not second:
                raise segregation_of_duties(
                    "umnr_second_signoff_user_id is required for UMNR handoff")
            if second == asg["assigned_by_user_id"] or second == user_id:
                raise segregation_of_duties(
                    "umnr_second_signoff_user_id must differ from dispatcher and acting agent")
            asg["umnr_second_signoff_user_id"] = second
            request["sofia_signoff_by"] = user_id
        asg["status"] = "HANDED_OFF"
        db.touch(asg)
        leg["status"] = "HANDED_OFF"
        db.touch(leg)
        db.touch(request)

    elif event_type == "COMPLETE":
        if asg["status"] != "HANDED_OFF":
            raise invalid_state("Assignment must be HANDED_OFF to complete")
        if user_id == asg["assigned_by_user_id"]:
            raise segregation_of_duties("Confirmer must differ from dispatcher")
        cascades.complete_assignment(asg, user_id)

    elif event_type == "MARK_NO_SHOW":
        if asg["status"] != "DISPATCHED":
            raise invalid_state("Assignment must be DISPATCHED")
        if not (now > leg["scheduled_pickup_utc"] + timedelta(minutes=30)):
            raise invalid_state("Too early to mark NO_SHOW")
        asg["status"] = "NO_SHOW"
        db.touch(asg)
        cascades._release_chair_no_maint(asg.get("wheelchair_asset_id"))
        agent = db.agents.get(asg["agent_id"])
        if agent is not None and agent.get("active_assignment_count", 0) > 0:
            agent["active_assignment_count"] -= 1
            db.touch(agent)
        # Parent failure bubble: if every other leg is terminal -> FAILED
        legs = [l for l in db.legs.values() if l["assist_request_id"] == request["id"]]
        others_terminal = all(
            l["status"] in {"COMPLETED", "NO_SHOW", "CANCELLED", "FAILED"}
            for l in legs if l["id"] != leg["id"])
        if others_terminal:
            leg["status"] = "NO_SHOW"
            db.touch(leg)
            if request["request_status"] not in {"COMPLETED", "CANCELLED", "FAILED"}:
                request["request_status"] = "FAILED"
                prov = cascades._open_provisional_invoice(request["id"])
                if prov is not None:
                    cascades._void_invoice(prov)
                if request["billing_status"] == "PROVISIONAL":
                    request["billing_status"] = "UNBILLED"
        db.touch(request)

    elif event_type == "CANCEL_ASSIGN":
        if asg["status"] != "DISPATCHED":
            raise invalid_state("Assignment must be DISPATCHED")
        cascades.cancel_assignment_direct(asg)
        cascades._bubble_request_failure(request["id"])
        db.touch(request)

    return success_object(serialize_assignment(asg))
