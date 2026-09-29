"""AlertEvent endpoints (PRD 3.5).

An alert carries two independent state dimensions — relay_state and
accessibility_state — that never constrain each other.
"""

from flask import Blueprint, request

import clock
import serializers
from auth import ANY_ROLE, check_station_ownership, guard
from envelope import object_response
from errors import ApiError
from routes.helpers import collection_response, filter_equals
from services import calculations as calc
from store import base_row, db, mark_created, touch
from validators import (
    CAPTION_INTERACTIONS,
    EVENT_CODE_RE,
    FIPS_RE,
    get_alert,
    get_station,
    json_body,
    req_array,
    req_enum,
    req_datetime,
    req_int,
    req_number,
    req_string,
)

bp = Blueprint("alerts", __name__)


@bp.post("/alert-events")
@guard("StationEngineer")
def create_alert():
    body = json_body(request)
    station_id = req_string(body, "station_id")
    event_code = req_string(body, "event_code", pattern=EVENT_CODE_RE)
    originator_sequence = req_string(body, "originator_sequence")
    fips_codes = req_array(body, "fips_codes", non_empty=True, member_pattern=FIPS_RE)
    received_at = req_datetime(body, "received_at")

    station = get_station(station_id)
    check_station_ownership(station)

    # rung 10 — clock-relative window
    if received_at > clock.now():
        raise ApiError("ERR_ALERT_RECEIVED_IN_FUTURE")

    # duplicate avoidance runs first, against the rows that already exist
    suppression = calc.duplicate_suppression_window(
        station_id, event_code, originator_sequence, fips_codes, received_at
    )

    alert = base_row()
    alert.update({
        "station_id": station_id,
        "event_code": event_code,
        "originator_sequence": originator_sequence,
        "fips_codes": list(fips_codes),
        "received_at": received_at,
        "relay_state": "RECEIVED",
        "accessibility_state": "ACCESSIBILITY_UNVERIFIED",
        "matched_relay_rule_id": None,
        "relay_class_applied": "NONE",
        "forward_delay_seconds_applied": 0,
        "suppression_reference_alert_id": suppression["suppression_reference_alert_id"],
        "suppression_source": suppression["suppression_source"],
        "visual_crawl_seconds": None,
        "audio_loudness_lufs": None,
        "caption_interaction": None,
        "accessibility_deficiency_points": None,
    })

    if suppression["relay_state"] == "SUPPRESSED_DUPLICATE":
        # suppressed: the selector is skipped entirely
        alert["relay_state"] = "SUPPRESSED_DUPLICATE"
    else:
        plan = db.state_plans.get(station["state_plan_id"])
        selection = calc.relay_rule_selection(station, plan, event_code, fips_codes)
        alert["relay_state"] = selection["relay_state"]
        alert["matched_relay_rule_id"] = selection["matched_relay_rule_id"]
        alert["relay_class_applied"] = selection["relay_class_applied"]
        alert["forward_delay_seconds_applied"] = selection["forward_delay_seconds_applied"]

    db.alerts[alert["id"]] = alert
    mark_created(alert)
    return object_response(serializers.alert_event(alert), 201)


@bp.get("/alert-events/<alert_id>")
@guard(*ANY_ROLE)
def read_alert(alert_id):
    alert = get_alert(alert_id)
    return object_response(serializers.alert_event(alert))


@bp.get("/alert-events")
@guard(*ANY_ROLE)
def list_alerts():
    rows = list(db.alerts.values())
    rows = filter_equals(rows, request, (
        ("station_id", "station_id"),
        ("matched_relay_rule_id", "matched_relay_rule_id"),
        ("suppression_reference_alert_id", "suppression_reference_alert_id"),
        ("relay_state", "relay_state"),
        ("accessibility_state", "accessibility_state"),
        ("event_code", "event_code"),
        ("originator_sequence", "originator_sequence"),
    ))
    return collection_response(rows, request, serializers.alert_event)


@bp.post("/alert-events/<alert_id>/confirm-relay")
@guard("StationEngineer")
def confirm_relay(alert_id):
    alert = get_alert(alert_id)
    station = db.stations.get(alert["station_id"])
    if station is not None:
        check_station_ownership(station)

    if alert["relay_state"] != "RELAY_PENDING":
        raise ApiError("ERR_ALERT_NOT_RELAY_PENDING")

    # touches only the forwarding dimension
    alert["relay_state"] = "RELAYED"
    touch(alert)
    return object_response(serializers.alert_event(alert))


@bp.post("/alert-events/<alert_id>/verify-accessibility")
@guard("StationEngineer")
def verify_accessibility(alert_id):
    body = json_body(request)
    visual_crawl_seconds = req_int(body, "visual_crawl_seconds", minimum=0, maximum=600)
    audio_loudness_lufs = req_number(body, "audio_loudness_lufs", minimum=-60.0, maximum=0.0)
    caption_interaction = req_enum(body, "caption_interaction", CAPTION_INTERACTIONS)

    alert = get_alert(alert_id)
    station = db.stations.get(alert["station_id"])
    if station is not None:
        check_station_ownership(station)

    if alert["accessibility_state"] != "ACCESSIBILITY_UNVERIFIED":
        raise ApiError("ERR_ACCESSIBILITY_ALREADY_VERIFIED")

    points, state = calc.accessibility_pass_evaluation(
        visual_crawl_seconds, audio_loudness_lufs, caption_interaction
    )
    alert["visual_crawl_seconds"] = visual_crawl_seconds
    alert["audio_loudness_lufs"] = audio_loudness_lufs
    alert["caption_interaction"] = caption_interaction
    alert["accessibility_deficiency_points"] = points
    # touches only the accessibility dimension
    alert["accessibility_state"] = state
    touch(alert)
    return object_response(serializers.alert_event(alert))
