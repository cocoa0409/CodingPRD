"""StormEvent endpoints (PRD §3.1, §3.9)."""

from flask import Blueprint

import serializers
from clock import clock
from db import base_row, db, touch
from errors import api_error
from middleware import authenticate
from response import object_response
from routes.common import get_storm_event
from services import aggregates, calculations
from services import posture as posture_service
from services.constants import SWATH_CONFIDENCE, TARGETING_SCORE_FLOOR, TERMINAL_REPAIR_STATUSES
from validation import json_body, req_enum, req_instant_string, req_int, req_state_code, req_string

bp = Blueprint("storm_events", __name__)

READ_ROLES = ("CatastropheDirector", "CrewCoordinator", "ShopEstimator", "IntakeAdvisor")


@bp.post("/hail-ops/storm-events")
def create_storm_event():
    authenticate(("CatastropheDirector",))
    body = json_body()
    name = req_string(body, "name")
    region_state_code = req_state_code(body, "region_state_code")
    max_hail_size_mm = req_int(body, "max_hail_size_mm", minimum=1)
    swath_area_km2 = req_int(body, "swath_area_km2", minimum=1)
    swath_confidence = req_enum(body, "swath_confidence", SWATH_CONFIDENCE)
    vehicle_population_estimate = req_int(body, "vehicle_population_estimate", minimum=0)
    competitor_shop_count = req_int(body, "competitor_shop_count", minimum=0)
    first_hail_at = req_instant_string(body, "first_hail_at")

    row = base_row()
    row.update({
        "name": name,
        "region_state_code": region_state_code,
        "max_hail_size_mm": max_hail_size_mm,
        "swath_area_km2": swath_area_km2,
        "swath_confidence": swath_confidence,
        "vehicle_population_estimate": vehicle_population_estimate,
        "competitor_shop_count": competitor_shop_count,
        "first_hail_at": first_hail_at,
        "status": "EVALUATING",
        "demobilized_at": None,
    })
    # The score is computed at registration and never recomputed afterwards.
    row["targeting_score"] = calculations.storm_targeting_score(row)
    db.storm_events[row["id"]] = row
    return object_response(serializers.storm_event(row), 201)


@bp.get("/hail-ops/storm-events/<identifier>")
def read_storm_event(identifier):
    authenticate(READ_ROLES)
    event = get_storm_event(identifier)
    return object_response(serializers.storm_event(event))


@bp.post("/hail-ops/storm-events/<identifier>/decision")
def decide_storm_event(identifier):
    authenticate(("CatastropheDirector",))
    body = json_body()
    decision = req_enum(body, "decision", ("TARGET", "DECLINE"))
    event = get_storm_event(identifier)

    if event["status"] != "EVALUATING":
        raise api_error(
            "ERR_INVALID_STORM_EVENT_STATE",
            "A decision may only be recorded while the event is EVALUATING.",
        )
    if decision == "TARGET" and event["targeting_score"] < TARGETING_SCORE_FLOOR:
        raise api_error(
            "ERR_TARGETING_SCORE_BELOW_FLOOR",
            "targeting_score %s is below the floor of %d."
            % (event["targeting_score"], TARGETING_SCORE_FLOOR),
        )

    event["status"] = "TARGETED" if decision == "TARGET" else "DECLINED"
    touch(event)
    return object_response(serializers.storm_event(event))


@bp.post("/hail-ops/storm-events/<identifier>/activate")
def activate_storm_event(identifier):
    authenticate(("CatastropheDirector",))
    event = get_storm_event(identifier)
    posture_service.recompute_for_event(event["id"])

    if event["status"] != "TARGETED":
        raise api_error(
            "ERR_INVALID_STORM_EVENT_STATE", "Activation requires the event to be TARGETED."
        )
    facilities = aggregates.facilities_of_event(event["id"])
    if not any(f["status"] == "COMMISSIONED" for f in facilities):
        raise api_error(
            "ERR_NO_COMMISSIONED_FACILITY",
            "Activation requires at least one COMMISSIONED facility on the event.",
        )

    event["status"] = "ACTIVE"
    touch(event)
    return object_response(serializers.storm_event(event))


@bp.post("/hail-ops/storm-events/<identifier>/demobilize")
def demobilize_storm_event(identifier):
    authenticate(("CatastropheDirector",))
    event = get_storm_event(identifier)
    posture_service.recompute_for_event(event["id"])

    if event["status"] != "ACTIVE":
        raise api_error(
            "ERR_INVALID_STORM_EVENT_STATE", "Demobilization requires the event to be ACTIVE."
        )
    for vehicle in aggregates.vehicles_of_event(event["id"]):
        if vehicle["repair_status"] not in TERMINAL_REPAIR_STATUSES:
            raise api_error(
                "ERR_EVENT_CLOSEOUT_BLOCKED",
                "Every vehicle of the event must be RELEASED or TOWED_OUT.",
            )

    event["status"] = "DEMOBILIZING"
    event["demobilized_at"] = clock.instant()
    touch(event)

    # CASCADE hop 1 — facilities of the event
    demobilized = []
    for facility in aggregates.facilities_of_event(event["id"]):
        if facility["status"] in ("SETUP", "COMMISSIONED", "SUSPENDED"):
            facility["status"] = "DEMOBILIZED"
            facility["posture"] = "FROZEN"
            touch(facility)
            demobilized.append(facility)

    # CASCADE hop 2 — crew deployments of those facilities
    # CASCADE hop 3 — housing occupancy and technician deployment_state are pure
    # aggregates over effective_end_date, so ending the deployment recomputes them.
    end_date = clock.date_str()
    for facility in demobilized:
        for deployment in aggregates.deployments_of_facility(facility["id"]):
            if deployment["status"] in ("CONFIRMED", "ON_SITE"):
                deployment["status"] = "ENDED"
                deployment["actual_end_date"] = end_date
                touch(deployment)

    return object_response(serializers.storm_event(event))


@bp.post("/hail-ops/storm-events/<identifier>/close")
def close_storm_event(identifier):
    authenticate(("CatastropheDirector",))
    event = get_storm_event(identifier)
    posture_service.recompute_for_event(event["id"])

    if event["status"] != "DEMOBILIZING":
        raise api_error(
            "ERR_INVALID_STORM_EVENT_STATE", "Closeout requires the event to be DEMOBILIZING."
        )
    for facility in aggregates.facilities_of_event(event["id"]):
        if facility["status"] != "DEMOBILIZED":
            raise api_error(
                "ERR_EVENT_CLOSEOUT_BLOCKED",
                "Every facility of the event must be DEMOBILIZED before closeout.",
            )
    for vehicle in aggregates.vehicles_of_event(event["id"]):
        if vehicle["billing_status"] in ("AUTHORIZED", "BILLED"):
            raise api_error(
                "ERR_EVENT_CLOSEOUT_BLOCKED",
                "No vehicle of the event may still be AUTHORIZED or BILLED.",
            )

    event["status"] = "CLOSED"
    touch(event)

    # Every ACTIVE rate agreement of the event is superseded; each carrier's
    # active_rate_agreement_count is a live aggregate and follows automatically.
    for agreement in aggregates.rate_agreements_of_event(event["id"]):
        if agreement["status"] == "ACTIVE":
            agreement["status"] = "SUPERSEDED"
            touch(agreement)

    return object_response(serializers.storm_event(event))
