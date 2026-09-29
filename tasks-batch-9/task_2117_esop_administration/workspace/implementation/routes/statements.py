"""Participant statement endpoints and the logical-clock capability."""

from flask import Blueprint

import responses
import services
import validation as v
from auth import ALL_ROLES, PLAN_ADMINISTRATOR, READ_ROLES, endpoint
from clock import CLOCK, parse_iso8601
from db import DB, serialize, sorted_rows, touch
from errors import fail

bp = Blueprint("statements", __name__)

DELIVERY_CHANNELS = ("EMAIL", "POSTAL", "PORTAL")


@bp.get("/participant-statements/<statement_id>")
@endpoint(READ_ROLES)
def read_statement(statement_id):
    return responses.ok(serialize(services.get_statement(statement_id)))


@bp.get("/participant-statements")
@endpoint(READ_ROLES)
def list_statements():
    limit, offset = v.pagination()
    participant_id = v.query_str("participant_id")
    allocation_run_id = v.query_str("allocation_run_id")
    plan_year = v.query_int("plan_year")
    delivery_status = v.query_str("delivery_status")
    rows = sorted_rows(DB.participant_statements)
    if participant_id is not None:
        rows = [r for r in rows if r["participant_id"] == participant_id]
    if allocation_run_id is not None:
        rows = [r for r in rows if r["allocation_run_id"] == allocation_run_id]
    if plan_year is not None:
        rows = [] if plan_year is v.MISSING else [r for r in rows if r["plan_year"] == plan_year]
    if delivery_status is not None:
        rows = [r for r in rows if r["delivery_status"] == delivery_status]
    return services.paged(rows, limit, offset)


@bp.post("/participant-statements/<statement_id>/deliver")
@endpoint([PLAN_ADMINISTRATOR])
def deliver_statement(statement_id):
    body = v.body()
    delivery_channel = v.req_enum(body, "delivery_channel", DELIVERY_CHANNELS)

    statement = services.get_statement(statement_id)
    participant = services.get_participant(statement["participant_id"])
    plan = services.get_plan(participant["plan_id"])
    services.check_not_frozen(plan)

    if statement["delivery_status"] != "GENERATED":
        fail("ERR_INVALID_STATE")

    statement["delivery_status"] = "DELIVERED"
    statement["delivery_channel"] = delivery_channel
    touch(statement)
    return responses.ok(serialize(statement))


@bp.post("/_clock/set_current_utc")
@endpoint(ALL_ROLES)
def set_clock():
    body = v.body()
    raw = v.req_string(body, "to_iso8601")
    parsed = parse_iso8601(raw)
    if parsed is None:
        fail("ERR_INVALID_REQUEST", "to_iso8601 must be an ISO 8601 instant.")
    CLOCK.set(parsed)
    return responses.ok({"current_utc": CLOCK.current_utc()})
