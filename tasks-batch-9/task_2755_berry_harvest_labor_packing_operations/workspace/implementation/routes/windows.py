"""Harvest windows: planning, confirmation, opening, closing, resumption and
cancellation (PRD §3.3)."""

from flask import Blueprint

import config
import db
import response
import util
import validation as V
from errors import fail
from routes.helpers import CS, FSO, HM, PC, PO, filter_args
from services import calc

bp = Blueprint("windows", __name__)

READERS = (HM, CS, PC, PO, FSO)

WINDOW_FIELDS = [
    V.Field("block_id", "string"),
    V.Field("crew_id", "string"),
    V.Field("start_at", "instant"),
    V.Field("end_at", "instant"),
    V.Field("forecast_brix", "number", minimum=0, maximum=30),
    V.Field("planned_volume_lbs", "number", exclusive_min=0),
    V.Field("piece_rate_cents_per_clamshell", "int", minimum=1, maximum=500),
    V.Field("clamshell_net_weight_lbs", "number", exclusive_min=0, maximum=5),
]

CANCEL_FIELDS = [V.Field("cancel_reason_code", "string")]


@bp.route("/harvest-windows", methods=["POST"])
def create_window():
    V.authenticate((HM,))
    body = V.read_body()
    V.validate_body(WINDOW_FIELDS, body)

    start = V.tolerant("instant", body.get("start_at"))
    end = V.tolerant("instant", body.get("end_at"))
    if start is not None and end is not None:
        if end <= start:
            fail("ERR_INVALID_DATE_RANGE", "end_at must be strictly after start_at.")
        if start.date() != end.date():
            fail(
                "ERR_INVALID_DATE_RANGE",
                "A harvest window is a single shift: start_at and end_at must share "
                "one calendar date.",
            )
    parsed = V.parse_temporal(WINDOW_FIELDS, body)
    start = parsed["start_at"]
    end = parsed["end_at"]

    block = V.get_block(body["block_id"])
    crew = V.get_crew(body["crew_id"])
    if crew["status"] == "RELEASED":
        fail("ERR_CREW_MISMATCH", "A RELEASED crew cannot be assigned a new window.")
    if calc.has_reentry_conflict(block["id"], start, end):
        fail("ERR_BLOCK_REENTRY_CONFLICT")

    rec = db.new_record()
    rec["block_id"] = block["id"]
    rec["crew_id"] = crew["id"]
    rec["start_at"] = body["start_at"]
    rec["end_at"] = body["end_at"]
    rec["forecast_brix"] = util.q1(body["forecast_brix"])
    rec["planned_volume_lbs"] = util.q2(body["planned_volume_lbs"])
    rec["piece_rate_cents_per_clamshell"] = int(body["piece_rate_cents_per_clamshell"])
    rec["clamshell_net_weight_lbs"] = util.q2(body["clamshell_net_weight_lbs"])
    rec["window_hours"] = util.hours_between(start, end)
    rec["effective_pick_rate_lbs_per_hour"] = None
    rec["required_picker_count"] = None
    rec["status"] = "PLANNED"
    rec["suspended_reason_code"] = None
    rec["cancel_reason_code"] = None
    rec["harvested_clamshells"] = 0
    rec["packed_lbs"] = util.q2(0)
    rec["_start_at"] = start
    rec["_end_at"] = end
    db.harvest_windows[rec["id"]] = rec
    return response.object_response(rec, 201)


@bp.route("/harvest-windows/<harvest_window_id>", methods=["GET"])
def read_window(harvest_window_id):
    V.authenticate(READERS)
    return response.object_response(V.get_window(harvest_window_id))


@bp.route("/harvest-windows", methods=["GET"])
def list_windows():
    V.authenticate(READERS)
    rows = filter_args(
        db.all_of(db.harvest_windows),
        {"block_id": "block_id", "crew_id": "crew_id", "status": "status"},
    )
    return response.paginate(rows)


@bp.route("/harvest-windows/<harvest_window_id>/confirm", methods=["POST"])
def confirm_window(harvest_window_id):
    V.authenticate((HM,))
    window = V.get_window(harvest_window_id)
    if window["status"] != "PLANNED":
        fail("ERR_INVALID_WINDOW_STATE", "Only a PLANNED window may be confirmed.")
    block = db.blocks[window["block_id"]]
    if block["food_safety_posture"] == "QUARANTINED":
        fail("ERR_BLOCK_QUARANTINED")
    if calc.has_reentry_conflict(
        block["id"], window["_start_at"], window["_end_at"], window["id"]
    ):
        fail("ERR_BLOCK_REENTRY_CONFLICT")
    rate, required = calc.staffing_estimate(window, block)
    if required > config.CREW_CAP:
        fail(
            "ERR_INSUFFICIENT_PICKERS",
            "The window would need more than the crew cap of 60 pickers.",
        )
    if util.dec(window["forecast_brix"]) < config.BRIX_MIN[block["variety"]]:
        fail("ERR_BRIX_BELOW_MINIMUM")

    window["effective_pick_rate_lbs_per_hour"] = rate
    window["required_picker_count"] = required
    window["status"] = "CONFIRMED"
    db.touch(window)
    return response.object_response(window)


@bp.route("/harvest-windows/<harvest_window_id>/open", methods=["POST"])
def open_window(harvest_window_id):
    V.authenticate((HM,))
    window = V.get_window(harvest_window_id)
    if window["status"] != "CONFIRMED":
        fail("ERR_INVALID_WINDOW_STATE", "Only a CONFIRMED window may be opened.")
    block = db.blocks[window["block_id"]]
    if block["food_safety_posture"] == "QUARANTINED":
        fail("ERR_BLOCK_QUARANTINED")
    if block["food_safety_posture"] != "CLEARED":
        fail("ERR_BLOCK_NOT_CLEARED")
    crew = db.crews[window["crew_id"]]
    if crew["status"] not in ("CERTIFIED", "ACTIVE"):
        fail(
            "ERR_INVALID_CREW_STATE",
            "The assigned crew must be CERTIFIED or ACTIVE to pick.",
        )
    if db.clock_instant() >= window["_end_at"]:
        fail(
            "ERR_TEMPORAL_ORDER_VIOLATION",
            "A window whose end has passed cannot be opened.",
        )
    required = window["required_picker_count"] or 0
    if int(crew["picker_count"]) < int(required):
        fail("ERR_INSUFFICIENT_PICKERS")

    window["status"] = "OPEN"
    db.touch(window)
    if crew["status"] == "CERTIFIED":
        crew["status"] = "ACTIVE"
        db.touch(crew)
    return response.object_response(window)


@bp.route("/harvest-windows/<harvest_window_id>/close", methods=["POST"])
def close_window(harvest_window_id):
    V.authenticate((HM,))
    window = V.get_window(harvest_window_id)
    if window["status"] != "OPEN":
        fail("ERR_INVALID_WINDOW_STATE", "Only an OPEN window may be closed.")
    for session in db.sessions_of_window(window["id"]):
        if session["status"] == "OPEN":
            fail("ERR_INVALID_WINDOW_STATE", "A pick session of the window is still OPEN.")
    for lot in db.lots_of_window(window["id"]):
        if lot["cold_chain_status"] == "COOLING":
            fail("ERR_INVALID_WINDOW_STATE", "A lot of the window is still COOLING.")
    calc.recompute_window_packed(window)
    calc.recompute_window_harvested(window)
    window["status"] = "CLOSED"
    db.touch(window)
    return response.object_response(window)


@bp.route("/harvest-windows/<harvest_window_id>/resume", methods=["POST"])
def resume_window(harvest_window_id):
    V.authenticate((HM,))
    window = V.get_window(harvest_window_id)
    if window["status"] != "SUSPENDED":
        fail("ERR_INVALID_WINDOW_STATE", "Only a SUSPENDED window may be resumed.")
    block = db.blocks[window["block_id"]]
    if block["food_safety_posture"] == "QUARANTINED":
        fail("ERR_BLOCK_QUARANTINED")
    if block["food_safety_posture"] != "CLEARED":
        fail("ERR_BLOCK_NOT_CLEARED")
    if db.clock_instant() >= window["_end_at"]:
        fail(
            "ERR_TEMPORAL_ORDER_VIOLATION",
            "A window whose end has passed cannot be resumed.",
        )
    calc.apply_staffing_estimate(window, block)
    window["suspended_reason_code"] = None
    window["status"] = "CONFIRMED"
    db.touch(window)
    return response.object_response(window)


@bp.route("/harvest-windows/<harvest_window_id>/cancel", methods=["POST"])
def cancel_window(harvest_window_id):
    V.authenticate((HM,))
    window = V.get_window(harvest_window_id)
    body = V.read_body()
    V.check_shape(CANCEL_FIELDS, body)
    if window["status"] not in ("PLANNED", "CONFIRMED", "SUSPENDED"):
        fail(
            "ERR_INVALID_WINDOW_STATE",
            "Cancellation is admitted only from PLANNED, CONFIRMED or SUSPENDED.",
        )
    if window["status"] != "PLANNED":
        for session in db.sessions_of_window(window["id"]):
            if session["status"] in ("OPEN", "TALLIED", "DISPUTED", "APPROVED"):
                fail(
                    "ERR_INVALID_WINDOW_STATE",
                    "The window still holds live or accrued pick sessions.",
                )
    window["cancel_reason_code"] = body["cancel_reason_code"]
    window["status"] = "CANCELLED"
    db.touch(window)
    return response.object_response(window)
