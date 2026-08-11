"""The barn: registration, holds and the workload ledger (PRD §3.3)."""

from flask import Blueprint, request

from core import timeutil as T
from core.constants import HOLD_TYPES_MANUAL, HORSE_HOLD_REASON_MANUAL
from core.envelope import object_response
from core.errors import fail
from core.ladder import Field, endpoint, validate_body
from core.lookups import horse_or_404
from core.store import clock, new_row, touch
from domain import policy, serialize, workload

bp = Blueprint("horses", __name__)

WORKLOAD_VARIANTS = ["committed", "delivered"]


@bp.post("/horses")
@endpoint(["ProgramAdmin"])
def create_horse():
    payload = validate_body([
        Field("name", "string", required=True),
        Field("body_weight_lb", "number", required=True, exclusive_min=0),
        Field("tack_weight_lb", "number", required=True, minimum=0),
    ])
    row = new_row("horses")
    row.update({
        "name": payload["name"],
        "body_weight_lb": payload["body_weight_lb"],
        "tack_weight_lb": payload["tack_weight_lb"],
        "max_load_lb": policy.max_load_lb(payload["body_weight_lb"]),
        "status": "AVAILABLE",
        "hold_release_at": None,
        "hold_reason": None,
        "_hold_incident_id": None,
    })
    return object_response(serialize.horse(row), 201)


@bp.get("/horses/<horse_id>")
@endpoint(["ProgramAdmin", "Instructor", "VolunteerCoordinator"])
def read_horse(horse_id):
    return object_response(serialize.horse(horse_or_404(horse_id)))


@bp.post("/horses/<horse_id>/hold")
@endpoint(["ProgramAdmin"])
def place_hold(horse_id):
    payload = validate_body([
        Field("hold_type", "enum", required=True, members=HOLD_TYPES_MANUAL),
        Field("release_at", "instant", required=True),
    ])
    row = horse_or_404(horse_id)
    if row["status"] != "AVAILABLE":
        fail("ERR_INVALID_STATE", "The horse is already on a hold.")
    row["status"] = payload["hold_type"]
    # §2.5: a MANUAL hold echoes the caller-supplied release_at byte for byte,
    # while the incident cascade DERIVES hold_release_at and renders .mmmZ.
    row["hold_release_at"] = T.echoed(payload["release_at"])
    row["hold_reason"] = HORSE_HOLD_REASON_MANUAL
    row["_hold_incident_id"] = None
    touch(row)
    return object_response(serialize.horse(row))


@bp.post("/horses/<horse_id>/release-hold")
@endpoint(["ProgramAdmin"])
def release_hold(horse_id):
    row = horse_or_404(horse_id)
    if row["status"] not in ("VET_HOLD", "FARRIER_HOLD", "REST_HOLD"):
        fail("ERR_INVALID_STATE", "The horse is not on a hold.")
    hold_release_at = row.get("hold_release_at")
    if hold_release_at is not None and clock.now() < hold_release_at.dt:
        fail("ERR_INVALID_STATE", "hold_release_at has not been reached.")
    row["status"] = "AVAILABLE"
    row["hold_release_at"] = None
    row["hold_reason"] = None
    row["_hold_incident_id"] = None
    touch(row)
    return object_response(serialize.horse(row))


@bp.get("/horses/<horse_id>/workload")
@endpoint(["ProgramAdmin", "Instructor"])
def horse_workload(horse_id):
    raw_date = request.args.get("on_date")
    if raw_date is None:
        fail("ERR_VALIDATION", "on_date is required.")
    on_date = T.parse_date(raw_date)
    if on_date is None:
        fail("ERR_VALIDATION", "on_date must be a YYYY-MM-DD date.")
    variant = request.args.get("variant")
    if variant is None:
        variant = "committed"
    elif variant not in WORKLOAD_VARIANTS:
        fail("ERR_VALIDATION", "Unsupported variant %r." % variant)
    horse_or_404(horse_id)
    view = workload.workload_view(horse_id, on_date, variant)
    view["on_date"] = raw_date
    return object_response(view)
