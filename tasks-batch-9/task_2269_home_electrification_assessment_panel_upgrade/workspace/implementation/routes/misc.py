"""Clawback-action reads and the logical-clock control endpoint."""
from flask import Blueprint, request

import clock
import domain
import envelope
import fields
import guards
import store
from guards import PROGRAM_ADMIN, PROGRAM_REVIEWER, authorize

bp = Blueprint("misc", __name__)


@bp.get("/clawback-actions/<action_id>")
@authorize(PROGRAM_REVIEWER, PROGRAM_ADMIN)
def read_clawback_action(action_id):
    action = domain.get_clawback_action(action_id)
    return envelope.object_response(store.public(action))


@bp.get("/clawback-actions")
@authorize(PROGRAM_REVIEWER, PROGRAM_ADMIN)
def list_clawback_actions():
    limit, offset = guards.pagination()
    project_id = request.args.get("project_id")
    reservation_id = request.args.get("reservation_id")
    inspection_id = request.args.get("triggered_by_inspection_id")
    reason = request.args.get("reason")
    records = store.ordered(
        store.clawback_actions,
        lambda a: (project_id is None or a["project_id"] == project_id)
        and (reservation_id is None or a["reservation_id"] == reservation_id)
        and (inspection_id is None or a["triggered_by_inspection_id"] == inspection_id)
        and (reason is None or a["reason"] == reason),
    )
    page = [store.public(r) for r in guards.paginate(records, limit, offset)]
    return envelope.list_response(page, limit, offset, len(records))


@bp.post("/_clock/set_current_utc")
@authorize(PROGRAM_ADMIN)
def set_current_utc():
    payload = guards.body()
    value = fields.req_datetime(payload, "current_utc")
    previous = clock.set_now(value)
    return envelope.object_response({
        "current_utc": clock.iso(value),
        "previous_utc": clock.iso(previous),
    })
