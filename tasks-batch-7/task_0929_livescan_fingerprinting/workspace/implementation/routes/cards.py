from flask import Blueprint, g, request

import cardsvc
import constants as C
import derive
import serializers
import validation as V
from envelope import object_response, paginate
from errors import ApiError
from lookups import (agency_of_appointment, body_row, check_billing_freeze, check_segregation,
                     freeze_for_site, optional_body_row, path_row, position_of_card,
                     require_appointment_state, require_card_state)
from store import db

bp = Blueprint("cards", __name__)


def _freeze_for_card(card):
    appointment = db.appointments[card["appointment_id"]]
    site = db.sites.get(card["site_id"])
    check_billing_freeze(agency_of_appointment(appointment), freeze_for_site(site))


def _check_device_ready(device, site):
    """Rungs 19 and 20."""
    if derive.device_status(device) != "CALIBRATED":
        raise ApiError("ERR_DEVICE_CALIBRATION_EXPIRED", "the device calibration has lapsed")
    if site["site_kind"] != "MOBILE_EVENT":
        return
    now = db.now()
    for assignment in db.device_assignments.values():
        if assignment["device_id"] != device["id"] or assignment["site_id"] != site["id"]:
            continue
        if derive.assignment_status(assignment) not in ("SCHEDULED", "ACTIVE"):
            continue
        if assignment["window_start"] <= now < assignment["window_end"]:
            return
    raise ApiError(
        "ERR_DEVICE_ASSIGNMENT_CONFLICT",
        "no roster entry binds this device to this mobile event now",
    )


@bp.post("/livescan/cards")
def open_card():
    data = V.body()
    appointment = (
        body_row("appointments", data["appointment_id"]) if data.get("appointment_id") else None
    )
    device = body_row("devices", data["device_id"]) if data.get("device_id") else None
    reprint_of = optional_body_row("submissions", data, "reprint_of_submission_id")
    if appointment is None:
        V.bad_request("appointment_id is required")
    if device is None:
        V.bad_request("device_id is required")

    site = db.sites[appointment["site_id"]]
    check_billing_freeze(agency_of_appointment(appointment), freeze_for_site(site))
    require_appointment_state(appointment, ("CHECKED_IN",))
    _check_device_ready(device, site)

    card = cardsvc.open_card(
        appointment,
        device,
        site,
        g.user_id,
        reprint_of_submission_id=reprint_of["id"] if reprint_of else None,
    )
    appointment["status"] = "IN_CAPTURE"
    db.touch(appointment)
    device["capture_count"] += 1
    db.touch(device)
    return object_response(serializers.card(card), 201)


@bp.get("/livescan/cards/<id>")
def read_card(id):
    return object_response(serializers.card(path_row("cards", id)))


@bp.get("/livescan/cards")
def list_cards():
    rows = list(db.cards.values())
    for field in (
        "appointment_id",
        "device_id",
        "site_id",
        "status",
        "superseded_by_card_id",
        "reprint_of_submission_id",
    ):
        value = request.args.get(field)
        if value is not None:
            rows = [r for r in rows if r[field] == value]
    return paginate(rows, serializers.card)


@bp.get("/livescan/cards/<id>/positions")
def list_positions(id):
    card = path_row("cards", id)
    rows = [p for p in db.positions.values() if p["card_id"] == card["id"]]
    status = request.args.get("status")
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return paginate(rows, serializers.position)


@bp.post("/livescan/cards/<id>/positions/<position_code>/attempts")
def record_attempt(id, position_code):
    card = path_row("cards", id)
    position = position_of_card(card, position_code)
    data = V.body()
    score = V.req_int(data, "score", minimum=0, maximum=100)

    _freeze_for_card(card)
    require_card_state(card, ("OPEN", "CAPTURING"))

    device = db.devices[card["device_id"]]
    site = db.sites[card["site_id"]]
    _check_device_ready(device, site)

    if position["status"] in ("PASSED", "EXCEPTION_CODED"):
        raise ApiError("ERR_POSITION_ALREADY_CLOSED", "position is %s" % position["status"])
    if position["attempt_count"] >= C.POSITION_ATTEMPT_CEILING:
        raise ApiError("ERR_POSITION_ATTEMPT_CEILING_REACHED", "three attempts already recorded")

    now = db.now()
    position["attempt_count"] += 1
    if position["best_score"] is None or score > position["best_score"]:
        position["best_score"] = score
    if score >= C.POSITION_PASS_THRESHOLD:
        position["status"] = "PASSED"
        position["closed_at"] = now
    elif position["attempt_count"] >= C.POSITION_ATTEMPT_CEILING:
        position["status"] = "CEILING_REACHED"
    else:
        position["status"] = "FAILED_RETRYABLE"
    db.touch(position)

    if card["status"] == "OPEN":
        card["status"] = "CAPTURING"
    if card["first_capture_at"] is None:
        card["first_capture_at"] = now
    card["last_capture_at"] = now
    derive.recompute_card_aggregates(card)
    db.touch(card)

    return object_response(serializers.position(position), 201)


@bp.post("/livescan/cards/<id>/positions/<position_code>/exception")
def close_position(id, position_code):
    card = path_row("cards", id)
    position = position_of_card(card, position_code)
    data = V.body()
    exception_code = V.req_string(data, "exception_code")
    V.enum_value("exception_code", exception_code, C.EXCEPTION_CODES)

    _freeze_for_card(card)
    require_card_state(card, ("OPEN", "CAPTURING"))

    if position["status"] in ("PASSED", "EXCEPTION_CODED"):
        raise ApiError("ERR_POSITION_ALREADY_CLOSED", "position is %s" % position["status"])
    if card["positions_exception_count"] + 1 > C.EXCEPTION_POSITION_HARD_MAX:
        raise ApiError("ERR_EXCEPTION_LIMIT_EXCEEDED", "the hard exception ceiling is four")

    now = db.now()
    position["status"] = "EXCEPTION_CODED"
    position["exception_code"] = exception_code
    position["closed_at"] = now
    db.touch(position)

    if card["status"] == "OPEN":
        card["status"] = "CAPTURING"
    card["last_capture_at"] = now
    derive.recompute_card_aggregates(card)
    db.touch(card)

    return object_response(serializers.position(position))


@bp.post("/livescan/cards/<id>/exception-override")
def exception_override(id):
    card = path_row("cards", id)
    data = V.body()
    V.req_string(data, "justification")

    _freeze_for_card(card)
    require_card_state(card, ("CAPTURING",))
    check_segregation(card["captured_by_user_id"])

    card["exception_override_by_user_id"] = g.user_id
    derive.recompute_card_aggregates(card)
    db.touch(card)
    return object_response(serializers.card(card))


@bp.post("/livescan/cards/<id>/finalize")
def finalize_card(id):
    card = path_row("cards", id)
    _freeze_for_card(card)
    require_card_state(card, ("CAPTURING",))

    derive.recompute_card_aggregates(card)
    if (
        card["positions_exception_count"] > C.EXCEPTION_POSITION_MAX
        and card["exception_override_by_user_id"] is None
    ):
        raise ApiError("ERR_EXCEPTION_LIMIT_EXCEEDED", "a supervisor override is required")

    positions = derive.card_positions(card)
    if not all(p["status"] in ("PASSED", "EXCEPTION_CODED") for p in positions):
        raise ApiError("ERR_CARD_NOT_SUBMITTABLE", "every position must be closed")
    if card["mean_quality_score"] < C.CARD_MEAN_QUALITY_MIN:
        raise ApiError("ERR_CARD_NOT_SUBMITTABLE", "mean_quality_score is below 65")

    card["status"] = "READY_FOR_SUBMISSION"
    db.touch(card)
    return object_response(serializers.card(card))
