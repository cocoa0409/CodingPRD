"""PRD 3.8 -- community engagement sessions and host exclusive occupancy."""

from flask import Blueprint

import calc
import envelope
import lookup
import serialize
import store
import validate
from auth import ROLE_JURISDICTION_DELEGATE, guard, require_owned_jurisdiction
from errors import fail

bp = Blueprint("sessions", __name__)

MODALITIES = ("IN_PERSON", "VIRTUAL", "HYBRID")
STRATEGY_TYPES = ("PROTECT", "ACCOMMODATE", "RETREAT", "AVOID")
SCHEDULABLE_CYCLE_STATES = ("DRAFT", "ENGAGEMENT", "REVISION")
OCCUPYING_STATUSES = ("SCHEDULED", "COMPLETED")


@bp.post("/resilience/plan-cycles/<plan_cycle_id>/engagement-sessions")
@guard(ROLE_JURISDICTION_DELEGATE)
def schedule_session(plan_cycle_id):
    cycle = lookup.need("plan_cycle", plan_cycle_id)
    body = validate.json_body()
    host = lookup.need_ref("jurisdiction", body, "host_jurisdiction_id")
    if host is None:
        validate.bad("host_jurisdiction_id", "is required.")
    require_owned_jurisdiction(host["id"], roles=(ROLE_JURISDICTION_DELEGATE,))

    modality = validate.enum_field(body, "modality", MODALITIES, required=True)
    window_start = validate.datetime_field(body, "window_start", required=True)
    window_end = validate.datetime_field(body, "window_end", required=True)
    validate.require_window(window_start, window_end)

    if host["status"] != "ACTIVE":
        fail("ERR_JURISDICTION_NOT_ACTIVE", "The host jurisdiction is not ACTIVE.")
    if cycle["status"] not in SCHEDULABLE_CYCLE_STATES:
        fail(
            "ERR_PLAN_CYCLE_STATE_INVALID",
            "Sessions may only be scheduled while the cycle is DRAFT, ENGAGEMENT or REVISION.",
        )

    for other in store.ordered(store.sessions):
        if other["host_jurisdiction_id"] != host["id"]:
            continue
        if other["status"] not in OCCUPYING_STATUSES:
            continue
        if calc.sessions_conflict(
            window_start, window_end, other["window_start"], other["window_end"]
        ):
            fail(
                "ERR_SESSION_WINDOW_CONFLICT",
                "The host already occupies an overlapping window, including its 24h buffer.",
            )

    record = store.insert(store.sessions, {
        "plan_cycle_id": cycle["id"],
        "host_jurisdiction_id": host["id"],
        "modality": modality,
        "window_start": window_start,
        "window_end": window_end,
        "status": "SCHEDULED",
        "attendee_count": None,
        "disadvantaged_attendee_count": None,
        "equity_reach_bps": None,
        "preferred_strategy_type": None,
    })
    return envelope.created(serialize.session(record))


@bp.get("/resilience/engagement-sessions")
@guard()
def list_sessions():
    rows = envelope.match(
        store.ordered(store.sessions),
        plan_cycle_id=envelope.str_filter("plan_cycle_id"),
        host_jurisdiction_id=envelope.str_filter("host_jurisdiction_id"),
        modality=envelope.str_filter("modality"),
        status=envelope.str_filter("status"),
    )
    return envelope.listing(rows, serialize.session)


@bp.get("/resilience/engagement-sessions/<session_id>")
@guard()
def get_session(session_id):
    row = lookup.need("session", session_id)
    return envelope.ok(serialize.session(row))


@bp.post("/resilience/engagement-sessions/<session_id>/complete")
@guard(ROLE_JURISDICTION_DELEGATE)
def complete_session(session_id):
    session = lookup.need("session", session_id)
    require_owned_jurisdiction(
        session["host_jurisdiction_id"], roles=(ROLE_JURISDICTION_DELEGATE,)
    )
    body = validate.json_body()
    attendees = validate.int_field(body, "attendee_count", required=True, minimum=0)
    disadvantaged = validate.int_field(
        body, "disadvantaged_attendee_count", required=True, minimum=0
    )
    preferred = validate.enum_field(
        body, "preferred_strategy_type", STRATEGY_TYPES, required=True
    )

    if session["status"] != "SCHEDULED":
        fail("ERR_SESSION_NOT_SCHEDULED", "The session is not SCHEDULED.")
    if disadvantaged > attendees:
        fail(
            "ERR_ATTENDANCE_MISMATCH",
            "disadvantaged_attendee_count may not exceed attendee_count.",
        )

    session["attendee_count"] = attendees
    session["disadvantaged_attendee_count"] = disadvantaged
    session["preferred_strategy_type"] = preferred
    session["equity_reach_bps"] = calc.equity_reach_bps(disadvantaged, attendees)
    session["status"] = "COMPLETED"
    store.touch(session)
    return envelope.ok(serialize.session(session))
