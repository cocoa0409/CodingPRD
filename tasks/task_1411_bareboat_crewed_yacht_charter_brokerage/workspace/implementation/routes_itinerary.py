"""Routes: itinerary legs and port permits (PRD §3.6)."""

from flask import Blueprint, g, request

from httpkit import (api_err, as_date, as_enum, as_str, body_json, get_or_404,
                     req_field, require_roles, respond_object,
                     respond_paginated, sort_created)
from serializers import ser_leg, ser_permit
from services import legs_of, permits_of, reevaluate_leg
from store import db, mutate, new_record

bp = Blueprint("itinerary", __name__)

LEG_EDITABLE_AGREEMENT_STATES = ("PENDING_SIGNATURES", "SIGNED", "IN_PREP")


def _agreement_of_leg(leg):
    return db["charter_agreements"][leg["charter_agreement_id"]]


def _central_agent_or_403(agr):
    if g.user_id != agr["central_agent_id"]:
        raise api_err(
            "ERR_FORBIDDEN", "Caller is not the agreement's central agent"
        )


@bp.route("/charter-agreements/<aid>/itinerary-legs", methods=["POST"])
def create_leg(aid):
    require_roles("CentralAgent")
    agr = get_or_404("charter_agreements", aid, "CharterAgreement")
    _central_agent_or_403(agr)
    if agr["status"] not in LEG_EDITABLE_AGREEMENT_STATES:
        raise api_err(
            "ERR_INVALID_STATE",
            "Legs may be appended only in PENDING_SIGNATURES, SIGNED or IN_PREP",
        )
    body = body_json()
    port_name = as_str(req_field(body, "port_name"), "port_name")
    arrival = as_date(req_field(body, "arrival_date"), "arrival_date")
    departure = as_date(req_field(body, "departure_date"), "departure_date")
    if not (
        agr["start_date"] <= arrival <= departure <= agr["end_date"]
    ):
        raise api_err(
            "ERR_LEG_OUTSIDE_CHARTER_WINDOW",
            "Leg dates must satisfy start_date <= arrival <= departure <= end_date",
        )
    leg = new_record()
    leg.update({
        "charter_agreement_id": agr["id"],
        "seq_no": len(legs_of(agr["id"])) + 1,
        "port_name": port_name,
        "arrival_date": arrival,
        "departure_date": departure,
        "status": "PLANNED",
    })
    db["itinerary_legs"][leg["id"]] = leg
    return respond_object(ser_leg(leg), 201)


@bp.route("/charter-agreements/<aid>/itinerary-legs", methods=["GET"])
def list_legs(aid):
    agr = get_or_404("charter_agreements", aid, "CharterAgreement")
    items = legs_of(agr["id"])  # seq_no order
    return respond_paginated([ser_leg(l) for l in items])


@bp.route("/itinerary-legs/<lid>", methods=["GET"])
def get_leg(lid):
    leg = get_or_404("itinerary_legs", lid, "ItineraryLeg")
    return respond_object(ser_leg(leg))


@bp.route("/itinerary-legs/<lid>/permits", methods=["POST"])
def create_permit(lid):
    require_roles("CentralAgent")
    leg = get_or_404("itinerary_legs", lid, "ItineraryLeg")
    agr = _agreement_of_leg(leg)
    _central_agent_or_403(agr)
    body = body_json()
    ref = as_str(req_field(body, "port_authority_ref"), "port_authority_ref")
    valid_from = as_date(req_field(body, "valid_from"), "valid_from")
    valid_until = as_date(req_field(body, "valid_until"), "valid_until")
    if valid_from > valid_until:
        raise api_err(
            "ERR_INVALID_REQUEST", "valid_from must be on or before valid_until"
        )
    p = new_record()
    p.update({
        "itinerary_leg_id": leg["id"],
        "port_authority_ref": ref,
        "valid_from": valid_from,
        "valid_until": valid_until,
        "status": "REQUESTED",
    })
    db["port_permits"][p["id"]] = p
    # A fresh REQUESTED permit flips a PERMITTED leg back to PLANNED
    reevaluate_leg(leg)
    return respond_object(ser_permit(p), 201)


@bp.route("/itinerary-legs/<lid>/permits", methods=["GET"])
def list_permits(lid):
    leg = get_or_404("itinerary_legs", lid, "ItineraryLeg")
    items = permits_of(leg["id"])
    v = request.args.get("status")
    if v is not None:
        items = [p for p in items if p["status"] == v]
    return respond_paginated([ser_permit(p) for p in sort_created(items)])


@bp.route("/port-permits/<pid>/decide", methods=["POST"])
def decide_permit(pid):
    require_roles("PlatformAdmin")
    p = get_or_404("port_permits", pid, "PortPermit")
    if p["status"] != "REQUESTED":
        raise api_err("ERR_INVALID_STATE", "PortPermit is not REQUESTED")
    body = body_json()
    outcome = as_enum(req_field(body, "outcome"), ("GRANTED", "DENIED"), "outcome")
    if outcome == "GRANTED":
        leg = db["itinerary_legs"][p["itinerary_leg_id"]]
        if not (
            p["valid_from"] <= leg["arrival_date"]
            and p["valid_until"] >= leg["departure_date"]
        ):
            raise api_err(
                "ERR_PERMIT_WINDOW_INSUFFICIENT",
                "Permit window must contain the leg's arrival/departure (closed)",
            )
    p["status"] = outcome
    mutate(p)
    reevaluate_leg(db["itinerary_legs"][p["itinerary_leg_id"]])
    return respond_object(ser_permit(p))


@bp.route("/port-permits/<pid>/resubmit", methods=["POST"])
def resubmit_permit(pid):
    require_roles("CentralAgent")
    p = get_or_404("port_permits", pid, "PortPermit")
    leg = db["itinerary_legs"][p["itinerary_leg_id"]]
    agr = _agreement_of_leg(leg)
    _central_agent_or_403(agr)
    if p["status"] != "DENIED":
        raise api_err("ERR_INVALID_STATE", "PortPermit is not DENIED")
    body = body_json()
    valid_from = as_date(req_field(body, "valid_from"), "valid_from")
    valid_until = as_date(req_field(body, "valid_until"), "valid_until")
    if valid_from > valid_until:
        raise api_err(
            "ERR_INVALID_REQUEST", "valid_from must be on or before valid_until"
        )
    p["valid_from"] = valid_from
    p["valid_until"] = valid_until
    p["status"] = "REQUESTED"
    mutate(p)
    reevaluate_leg(leg)
    return respond_object(ser_permit(p))
