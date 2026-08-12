"""AssistRequests and ServiceLegs."""
import uuid
from datetime import timedelta

from flask import Blueprint, request as _req

import db
from errors import (already_in_service, bad_request, invalid_state, no_legs,
                    payment_method_required, posture_restricted,
                    referential_integrity, stale_version)
from middleware import require_roles
from response import success_object
from routes.util import (get_or_404, json_body, list_response, require_enum,
                         require_fields, serialize_assist_request,
                         serialize_invoice, serialize_leg)
from services import cascades, pricing

bp = Blueprint("requests", __name__)

ALL_ROLES = ("PlatformAdmin", "OpsManager", "Dispatcher", "Agent",
             "Confirmer", "Requester", "BillingClerk")
LIST_ROLES = ("PlatformAdmin", "OpsManager", "Dispatcher", "BillingClerk")


@bp.post("/maa/assist-requests")
def create_assist_request():
    require_roles("Requester")
    body = json_body()
    require_fields(body, ["passenger_id", "bill_to", "service_tier"])
    passenger = db.passengers.get(body["passenger_id"])
    if passenger is None:
        raise bad_request("passenger_id does not resolve")
    bill_to = require_enum(body["bill_to"], {"AIRLINE", "PRIVATE"}, "bill_to")
    tier = require_enum(body["service_tier"], {"STANDARD", "PRIORITY", "CONCIERGE"}, "service_tier")
    companion_count = body.get("companion_count", 0)
    if not isinstance(companion_count, int) or isinstance(companion_count, bool) or companion_count < 0:
        raise bad_request("companion_count must be a non-negative integer")
    umnr_handoff = body.get("umnr_handoff_required", False)
    if not isinstance(umnr_handoff, bool):
        raise bad_request("umnr_handoff_required must be a boolean")
    request = db.common_fields()
    request.update({
        "passenger_id": passenger["id"],
        "bill_to": bill_to,
        "service_tier": tier,
        "request_status": "DRAFT",
        "billing_status": "UNBILLED",
        "provisional_charge_cents": None,
        "final_charge_cents": None,
        "companion_count": companion_count,
        "umnr_handoff_required": umnr_handoff,
        "sofia_signoff_by": None,
        "_last_change_epoch": {},
    })
    db.assist_requests[request["id"]] = request
    return success_object(serialize_assist_request(request), status=201)


@bp.get("/maa/assist-requests/<rid>")
def get_assist_request(rid):
    require_roles(*ALL_ROLES)
    request = get_or_404(db.assist_requests, rid, "AssistRequest")
    return success_object(serialize_assist_request(request))


@bp.get("/maa/assist-requests")
def list_assist_requests():
    require_roles(*LIST_ROLES)
    items = list(db.assist_requests.values())
    passenger_id = _req.args.get("passenger_id")
    request_status = _req.args.get("request_status")
    billing_status = _req.args.get("billing_status")
    if passenger_id:
        items = [r for r in items if r["passenger_id"] == passenger_id]
    if request_status:
        items = [r for r in items if r["request_status"] == request_status]
    if billing_status:
        items = [r for r in items if r["billing_status"] == billing_status]
    return list_response(items, serialize_assist_request)


# ---------------------------------------------------------------------------
# Legs
# ---------------------------------------------------------------------------

@bp.post("/maa/assist-requests/<rid>/legs")
def create_leg(rid):
    require_roles("Requester")
    request = get_or_404(db.assist_requests, rid, "AssistRequest")
    body = json_body()
    require_fields(body, ["segment_id", "leg_kind", "pickup_zone"])
    if request["request_status"] != "DRAFT":
        raise invalid_state("Legs may only be added while the request is DRAFT")
    segment = db.segments.get(body["segment_id"])
    if segment is None:
        raise referential_integrity("segment_id does not resolve")
    leg_kind = require_enum(
        body["leg_kind"],
        {"MEET_ARRIVAL", "DEPARTURE_ESCORT", "CONNECTION_TRANSFER"},
        "leg_kind")
    pickup_zone = body["pickup_zone"]
    if not isinstance(pickup_zone, str) or not pickup_zone.strip():
        raise bad_request("pickup_zone must be a non-empty string")
    onward_leg_id = body.get("onward_leg_id")
    if onward_leg_id is not None:
        if leg_kind != "CONNECTION_TRANSFER":
            raise referential_integrity("onward_leg_id is only meaningful for CONNECTION_TRANSFER")
        onward = db.legs.get(onward_leg_id)
        if onward is None or onward["assist_request_id"] != request["id"]:
            raise referential_integrity("onward_leg_id must reference a leg of the same request")
        onward_seg = db.segments.get(onward["segment_id"])
        if onward_seg is None or onward_seg["airport_id"] != segment["airport_id"]:
            raise referential_integrity("onward leg must not cross airport boundary")

    passenger = db.passengers[request["passenger_id"]]
    terminal = db.terminals.get(segment["terminal_id"])
    airport = db.airports[segment["airport_id"]]

    scheduled_pickup = segment["scheduled_utc"] + timedelta(minutes=airport["meet_buffer_minutes"])

    requires_wheelchair = passenger["mobility_code"] in {"WCHS", "WCHC"}
    requires_wchc_chair = passenger["mobility_code"] == "WCHC"
    requires_ummr = passenger["passenger_class"] == "UMNR"
    requires_senior = passenger["passenger_class"] == "SENIOR"
    is_international = bool(segment.get("international", False))
    requires_tsa = bool(terminal and terminal.get("requires_secure_escort")) or (
        is_international and leg_kind != "MEET_ARRIVAL")

    leg = db.common_fields()
    leg.update({
        "assist_request_id": request["id"],
        "segment_id": segment["id"],
        "leg_kind": leg_kind,
        "onward_leg_id": onward_leg_id,
        "pickup_zone": pickup_zone,
        "status": "PLANNED",
        "scheduled_pickup_utc": scheduled_pickup,
        "actual_pickup_utc": None,
        "completed_utc": None,
        "requires_wheelchair": requires_wheelchair,
        "requires_tsa_escort": requires_tsa,
        "requires_ummr_agent": requires_ummr,
        "requires_senior_agent": requires_senior,
        "requires_wchc_chair": requires_wchc_chair,
        "provisional_leg_cents": None,
        "final_leg_cents": None,
    })
    db.legs[leg["id"]] = leg
    return success_object(serialize_leg(leg), status=201)


@bp.get("/maa/assist-requests/<rid>/legs")
def list_request_legs(rid):
    require_roles(*ALL_ROLES)
    request = get_or_404(db.assist_requests, rid, "AssistRequest")
    items = [l for l in db.legs.values() if l["assist_request_id"] == request["id"]]
    return list_response(items, serialize_leg)


@bp.get("/maa/legs/<lid>")
def get_leg(lid):
    require_roles(*ALL_ROLES)
    leg = get_or_404(db.legs, lid, "ServiceLeg")
    return success_object(serialize_leg(leg))


@bp.get("/maa/legs/<lid>/onward-legs")
def list_onward_legs(lid):
    require_roles(*ALL_ROLES)
    leg = get_or_404(db.legs, lid, "ServiceLeg")
    items = [l for l in db.legs.values() if l.get("onward_leg_id") == leg["id"]]
    return list_response(items, serialize_leg)


@bp.get("/maa/assist-requests/<rid>/assignments")
def list_request_assignments(rid):
    from routes.util import serialize_assignment
    require_roles(*ALL_ROLES)
    request = get_or_404(db.assist_requests, rid, "AssistRequest")
    items = [a for a in db.assignments.values() if a["assist_request_id"] == request["id"]]
    return list_response(items, serialize_assignment)


@bp.get("/maa/legs/<lid>/assignments")
def list_leg_assignments(lid):
    from routes.util import serialize_assignment
    require_roles(*ALL_ROLES)
    leg = get_or_404(db.legs, lid, "ServiceLeg")
    items = [a for a in db.assignments.values() if a["service_leg_id"] == leg["id"]]
    return list_response(items, serialize_assignment)


@bp.get("/maa/assist-requests/<rid>/incidents")
def list_request_incidents(rid):
    from routes.util import serialize_incident
    require_roles(*ALL_ROLES)
    request = get_or_404(db.assist_requests, rid, "AssistRequest")
    items = [i for i in db.incidents.values() if i["assist_request_id"] == request["id"]]
    return list_response(items, serialize_incident)


@bp.get("/maa/assist-requests/<rid>/invoices")
def list_request_invoices(rid):
    require_roles("PlatformAdmin", "OpsManager", "BillingClerk", "Requester")
    request = get_or_404(db.assist_requests, rid, "AssistRequest")
    items = [i for i in db.invoices.values() if i["assist_request_id"] == request["id"]]
    return list_response(items, serialize_invoice)


# ---------------------------------------------------------------------------
# AssistRequest lifecycle events (SUBMIT, CANCEL) — OCC guarded
# ---------------------------------------------------------------------------

@bp.post("/maa/assist-requests/<rid>/events")
def assist_request_event(rid):
    user_id, _ = require_roles("Requester")
    request = get_or_404(db.assist_requests, rid, "AssistRequest")
    body = json_body()
    require_fields(body, ["event_type"])
    event_type = require_enum(body["event_type"], {"SUBMIT", "CANCEL"}, "event_type")

    expected = body.get("expected_assist_request_version")
    if expected is None:
        raise bad_request("expected_assist_request_version is required")
    if not isinstance(expected, int) or isinstance(expected, bool):
        raise bad_request("expected_assist_request_version must be an integer")
    if expected != request["version"]:
        raise stale_version("expected_assist_request_version does not match current version")

    if event_type == "SUBMIT":
        if request["request_status"] != "DRAFT":
            raise invalid_state("Only DRAFT requests may be submitted")
        legs = [l for l in db.legs.values() if l["assist_request_id"] == request["id"]]
        if not legs:
            raise no_legs("SUBMIT requires at least one ServiceLeg")
        passenger = db.passengers[request["passenger_id"]]
        if request["bill_to"] == "PRIVATE" and not passenger.get("private_card_token"):
            raise payment_method_required("bill_to=PRIVATE requires private_card_token")
        if request["bill_to"] == "AIRLINE" and not passenger.get("airline_pnr"):
            raise payment_method_required("bill_to=AIRLINE requires airline_pnr")
        for leg in legs:
            seg = db.segments[leg["segment_id"]]
            airport = db.airports[seg["airport_id"]]
            if airport["posture"] == "LOCKDOWN":
                raise posture_restricted("Segment airport is in LOCKDOWN")

        # Compute per-leg provisional charges
        for leg in legs:
            seg = db.segments[leg["segment_id"]]
            airport = db.airports[seg["airport_id"]]
            leg["provisional_leg_cents"] = pricing.provisional_leg_charge(leg, request, airport)
            db.touch(leg)
        request["provisional_charge_cents"] = pricing.request_provisional_total(request["id"])
        request["request_status"] = "SUBMITTED"
        request["billing_status"] = "PROVISIONAL"
        # Snapshot the current ops_epoch per airport for stale detection
        snapshot = {}
        for leg in legs:
            seg = db.segments[leg["segment_id"]]
            airport = db.airports[seg["airport_id"]]
            snapshot[airport["id"]] = airport.get("ops_epoch", 0)
        request["_last_change_epoch"] = snapshot
        db.touch(request)

        inv = db.common_fields()
        inv.update({
            "assist_request_id": request["id"],
            "invoice_kind": "PROVISIONAL",
            "amount_cents": request["provisional_charge_cents"],
            "status": "OPEN",
            "bill_to": request["bill_to"],
            "supersedes_invoice_id": None,
            "writeoff_baseline_cents": None,
            "created_by_user_id": user_id,
        })
        db.invoices[inv["id"]] = inv
        return success_object(serialize_assist_request(request))

    # CANCEL
    if request["request_status"] == "DRAFT":
        request["request_status"] = "CANCELLED"
        db.touch(request)
        return success_object(serialize_assist_request(request))
    # In-flight guard (PRD §3.10): attempting to cancel with an assignment in
    # AT_PICKUP / IN_TRANSIT / AT_GATE is rejected with ERR_ALREADY_IN_SERVICE.
    for asg in db.assignments.values():
        if (asg["assist_request_id"] == request["id"]
                and asg["status"] in {"AT_PICKUP", "IN_TRANSIT", "AT_GATE"}):
            raise already_in_service("An assignment is already in service")
    if request["request_status"] != "SUBMITTED":
        raise invalid_state("Only DRAFT or SUBMITTED requests may be cancelled")
    # Cancel DISPATCHED assignments + PLANNED/DISPATCHED legs
    for asg in list(db.assignments.values()):
        if asg["assist_request_id"] == request["id"] and asg["status"] == "DISPATCHED":
            cascades.cancel_assignment_direct(asg)
    for leg in list(db.legs.values()):
        if leg["assist_request_id"] == request["id"] and leg["status"] in {"PLANNED", "DISPATCHED"}:
            leg["status"] = "CANCELLED"
            db.touch(leg)
    prov = None
    for inv in db.invoices.values():
        if (inv["assist_request_id"] == request["id"]
                and inv["invoice_kind"] == "PROVISIONAL" and inv["status"] == "OPEN"):
            prov = inv
            break
    if prov is not None:
        prov["status"] = "VOID"
        db.touch(prov)
    request["billing_status"] = "UNBILLED"
    request["request_status"] = "CANCELLED"
    db.touch(request)
    return success_object(serialize_assist_request(request))
