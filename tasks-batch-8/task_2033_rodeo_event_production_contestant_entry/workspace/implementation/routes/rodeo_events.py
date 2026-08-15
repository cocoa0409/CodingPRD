"""RodeoEvent endpoints: create, list, get, draw execution (PRD 3.1, 3.5)."""
from flask import Blueprint, request

from db import DB, new_id
from errors import ApiError
from middleware import ALL_ROLES, auth
from response import ok, ok_list
from services import (
    EVENT_CODES,
    ROUGH_STOCK_CODES,
    commit_draw,
    fk_or_404,
    get_or_404,
    plan_draw,
    rodeo_of_event,
    ser,
    sorted_created,
    stamp,
)
from util import (
    as_enum,
    as_int,
    as_int_range,
    as_str,
    body,
    pagination_args,
    required,
)

bp = Blueprint("rodeo_events", __name__, url_prefix="/api")


@bp.post("/rodeo-events")
def create_rodeo_event():
    auth(["CommitteeAdmin"])
    data = body()
    # Body FK existence (priority 4) precedes field shape (priority 5).
    rodeo_id = data.get("rodeo_id")
    if rodeo_id is not None:
        get_or_404("rodeos", rodeo_id)
    as_str(required(data, "rodeo_id"), "rodeo_id")
    event_code = as_enum(required(data, "event_code"), "event_code", EVENT_CODES)
    go_rounds = as_int_range(required(data, "go_rounds"), "go_rounds", 1, 3)
    entry_fee_cents = as_int_range(
        required(data, "entry_fee_cents"), "entry_fee_cents", 1000, None
    )
    added_money_cents = as_int_range(
        required(data, "added_money_cents"), "added_money_cents", 0, None
    )
    per_performance_slots = as_int_range(
        required(data, "per_performance_slots"), "per_performance_slots", 1, None
    )
    payout_places = as_int_range(
        required(data, "payout_places"), "payout_places", 1, 4
    )
    rec = {
        "id": new_id(),
        "rodeo_id": rodeo_id,
        "event_code": event_code,
        "discipline": "ROUGH_STOCK" if event_code in ROUGH_STOCK_CODES else "TIMED",
        "go_rounds": go_rounds,
        "entry_fee_cents": entry_fee_cents,
        "added_money_cents": added_money_cents,
        "per_performance_slots": per_performance_slots,
        "payout_places": payout_places,
        "drawn_rounds": [],
    }
    stamp(rec)
    DB["rodeo_events"][rec["id"]] = rec
    return ok(ser(rec), status=201)


@bp.get("/rodeo-events")
def list_rodeo_events():
    auth(ALL_ROLES)
    rodeo_id = request.args.get("rodeo_id")
    event_id = request.args.get("rodeo_event_id")
    items = DB["rodeo_events"].values()
    if rodeo_id is not None:
        items = [e for e in items if e["rodeo_id"] == rodeo_id]
    if event_id is not None:
        items = [e for e in items if e["id"] == event_id]
    items = sorted_created(items)
    limit, offset = pagination_args()
    return ok_list(
        [ser(e) for e in items[offset : offset + limit]], len(items), limit, offset
    )


@bp.get("/rodeo-events/<event_id>")
def get_rodeo_event(event_id):
    auth(ALL_ROLES)
    return ok(ser(get_or_404("rodeo_events", event_id)))


@bp.post("/rodeo-events/<event_id>/draws")
def execute_draw(event_id):
    auth(["CommitteeAdmin"])
    event = get_or_404("rodeo_events", event_id)
    data = body()
    # Field shape (priority 5).
    go_round_number = as_int(required(data, "go_round_number"), "go_round_number")
    expected = data.get("expected_rodeo_event_version")
    if expected is not None:
        as_int(expected, "expected_rodeo_event_version")
    # Rodeo posture gate (priority 7).
    rodeo = rodeo_of_event(event)
    if rodeo["posture"] not in ("DRAW_LOCKED", "IN_PROGRESS"):
        raise ApiError(
            "ERR_RODEO_NOT_OPEN",
            409,
            "Draws require the rodeo to be DRAW_LOCKED or IN_PROGRESS",
        )
    # Draw integrity (priority 19): range and predecessor ordering.
    if go_round_number < 1 or go_round_number > event["go_rounds"]:
        raise ApiError("ERR_GO_ROUND_INVALID", 422, "go_round_number out of range")
    if go_round_number > 1 and (go_round_number - 1) not in event["drawn_rounds"]:
        raise ApiError(
            "ERR_GO_ROUND_INVALID",
            422,
            f"Go-round {go_round_number - 1} must be drawn first",
        )
    # Re-draw blocked once VERIFIED results exist for this go-round (19.5).
    assignments = DB["draw_assignments"]
    for r in DB["run_results"].values():
        if r["rodeo_event_id"] == event_id and r["status"] == "VERIFIED":
            assignment = assignments[r["draw_assignment_id"]]
            if assignment["go_round_number"] == go_round_number:
                raise ApiError(
                    "ERR_RESULTS_EXIST",
                    409,
                    "Go-round already has verified results",
                )
    # Plan the whole draw (atomic): raises ERR_INSUFFICIENT_STOCK (20) if the
    # eligible rough-stock pool cannot cover every assigned entry.
    plan = plan_draw(rodeo, event, go_round_number)
    # Optimistic concurrency is always evaluated last (priority 25).
    if expected is not None and expected != event["version"]:
        raise ApiError(
            "ERR_STALE_VERSION",
            412,
            "expected_rodeo_event_version does not match the event version",
        )
    assigned_count, waitlisted_count = commit_draw(rodeo, event, go_round_number, plan)
    return ok(
        {
            "assigned_count": assigned_count,
            "waitlisted_count": waitlisted_count,
            "go_round_number": go_round_number,
        }
    )
