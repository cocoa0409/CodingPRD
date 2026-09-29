"""Floor programming: proposals, decisions, outcomes and reimbursement."""
from flask import Blueprint, g

import calc
import derive
import responses
import services
import store
import validators as V
from auth import endpoint
from constants import API_PREFIX, LINE_CATEGORIES, PROGRAM_CATEGORIES
from errors import ApiError
from store import DB

DIRECTOR = ["ResidenceDirector"]
RA_OR_DIRECTOR = ["ResidentAssistant", "ResidenceDirector"]
bp = Blueprint("programs", __name__)


@bp.route("%s/program-events" % API_PREFIX, methods=["POST"])
@endpoint(["ResidentAssistant"])
def create_event():
    body = V.body()
    floor_id = V.s_id(body, "floor_id")
    title = V.s_str(body, "title")
    category = V.s_enum(body, "category", PROGRAM_CATEGORIES)
    scheduled_for = V.s_dt(body, "scheduled_for")
    amount = V.s_int(body, "requested_amount_cents", 0, 500000)
    ra = services.acting_ra()
    floor = store.get("floors", floor_id)
    if floor is None:
        raise ApiError("ERR_FLOOR_NOT_FOUND")
    services.ra_active_gate(ra)
    if ra.get("assigned_floor_id") != floor_id:
        raise ApiError("ERR_FLOOR_MISMATCH")
    row = store.insert("events", "ProgramEvent", {
        "floor_id": floor_id,
        "organizer_ra_id": ra["id"],
        "title": title,
        "category": category,
        "scheduled_for": store.fmt_iso(scheduled_for),
        "requested_amount_cents": amount,
        "status": "PROPOSED",
        "encumbered_amount_cents": 0,
        "attendance_count": None,
        "receipt_lines": [],
        "reimbursed_amount_cents": None,
        "decision_reason": None,
    })
    return responses.obj(row, 201)


@bp.route("%s/program-events/<event_id>/decision" % API_PREFIX, methods=["POST"])
@endpoint(DIRECTOR)
def decide_event(event_id):
    event = V.must_get("ProgramEvent", event_id)
    body = V.body()
    decision = V.s_enum(body, "decision", ("APPROVE", "DENY"))
    reason = V.s_str(body, "reason", required=False)
    if event["status"] != "PROPOSED":
        raise ApiError("ERR_PROGRAM_STATE_INVALID")
    floor = DB["floors"].get(event["floor_id"])
    if decision == "DENY":
        event["status"] = "DENIED"
        event["decision_reason"] = reason
        return responses.obj(event)
    if floor is None:
        raise ApiError("ERR_FLOOR_NOT_FOUND")
    if floor.get("programming_frozen"):
        raise ApiError("ERR_BUILDING_NOT_OPEN")
    if floor["programming_budget_cents"] <= 0:
        raise ApiError("ERR_PROGRAM_BUDGET_NOT_ALLOCATED")
    if event["requested_amount_cents"] > derive.floor_available_cents(floor):
        raise ApiError("ERR_FLOOR_BUDGET_EXCEEDED")
    event["status"] = "APPROVED"
    event["decision_reason"] = reason
    event["encumbered_amount_cents"] = event["requested_amount_cents"]
    return responses.obj(event)


@bp.route("%s/program-events/<event_id>/outcome" % API_PREFIX, methods=["POST"])
@endpoint(RA_OR_DIRECTOR)
def event_outcome(event_id):
    event = V.must_get("ProgramEvent", event_id)
    body = V.body()
    action = V.s_enum(body, "action", ("HOLD", "CANCEL"))
    attendance = V.s_int(body, "attendance_count", 0, required=(action == "HOLD"))
    if action == "HOLD":
        if event["status"] != "APPROVED":
            raise ApiError("ERR_PROGRAM_STATE_INVALID")
        if store.now() < store.parse_iso(event["scheduled_for"]):
            raise ApiError("ERR_PROGRAM_STATE_INVALID")
        event["status"] = "HELD"
        event["attendance_count"] = attendance
    else:
        if event["status"] not in ("APPROVED", "HELD"):
            raise ApiError("ERR_PROGRAM_STATE_INVALID")
        event["status"] = "CANCELLED"
        event["encumbered_amount_cents"] = 0
    return responses.obj(event)


@bp.route("%s/program-events/<event_id>/reimbursement" % API_PREFIX, methods=["POST"])
@endpoint(DIRECTOR)
def reimburse_event(event_id):
    event = V.must_get("ProgramEvent", event_id)
    body = V.body()
    raw_lines = V.s_list(body, "receipt_lines", allow_empty=False)
    lines = []
    for item in raw_lines:
        if not isinstance(item, dict):
            raise ApiError("ERR_INVALID_REQUEST", "receipt_lines entries must be objects.")
        category = V.s_enum(item, "line_category", LINE_CATEGORIES)
        amount = V.s_int(item, "amount_cents", 0)
        lines.append({"line_category": category, "amount_cents": amount})
    if event["status"] != "HELD":
        raise ApiError("ERR_PROGRAM_NOT_HELD")
    floor = DB["floors"].get(event["floor_id"])
    if floor is None:
        raise ApiError("ERR_FLOOR_NOT_FOUND")
    amount = calc.reimbursement_amount(lines)
    overrun = max(0, amount - event["requested_amount_cents"])
    if overrun > derive.floor_available_cents(floor):
        raise ApiError("ERR_FLOOR_BUDGET_EXCEEDED")
    event["receipt_lines"] = lines
    event["reimbursed_amount_cents"] = amount
    event["encumbered_amount_cents"] = 0
    event["status"] = "REIMBURSED"
    return responses.obj(event)
