"""Excursions: creation reserves an OPEN slot and auto-creates the DRAFT
provisioning manifest; events PUBLISH (OCC) / BEGIN_BOARDING (service-date gated)
/ MARK_OPERATED / CANCEL (OperationsManager, with cancel_reason)."""
from flask import Blueprint, request

import db
from auth import ALL_ROLES, require_event_role, require_roles
from db import clock_now, new_entity, public, touch
from envelope import success_list, success_obj
from errors import (
    ApiError,
    ERR_CONSIST_INCOMPLETE,
    ERR_CREW_COVERAGE_INCOMPLETE,
    ERR_INVALID_REFERENCE,
    ERR_INVALID_STATE,
    ERR_NOT_FOUND,
    ERR_NOT_SERVICE_DATE,
    ERR_STALE_VERSION,
    ERR_SURGE_MULTIPLIER_INVALID,
    ERR_VALIDATION,
)
from services.core import (
    MAX_SURGE_BP,
    MIN_HOLIDAY_SURGE_BP,
    cancel_excursion,
    consist_complete,
    crew_coverage_ok,
    excursion_view,
    manifest_view,
    mark_operated,
    find_manifest,
)
from validators import (
    body,
    opt_int,
    paginate,
    pagination,
    req_enum,
    req_int,
    req_str,
)

bp = Blueprint("excursions", __name__)

EVENT_TYPES = ("REGULAR", "HOLIDAY")
EVENT_ROLES = {
    "PUBLISH": ("Scheduler",),
    "BEGIN_BOARDING": ("Scheduler",),
    "MARK_OPERATED": ("Scheduler",),
    "CANCEL": ("OperationsManager",),
}
CANCEL_REASONS = ("WEATHER", "EVENT", "OPERATOR")


def get_excursion_or_404(excursion_id):
    exc = db.excursions.get(excursion_id)
    if exc is None:
        raise ApiError(ERR_NOT_FOUND, "Excursion not found", 404)
    return exc


@bp.post("/railroad/excursions")
def create_excursion():
    require_roles("Scheduler")
    data = body()
    title = req_str(data, "title")
    slot_id = req_str(data, "slot_id")
    event_type = req_enum(data, "event_type", EVENT_TYPES)
    surge = req_int(data, "surge_multiplier_bp")
    # Referenced parent-state gate (tier 5): the slot must be OPEN.
    slot = db.slots.get(slot_id)
    if slot is not None and slot["status"] != "OPEN":
        raise ApiError(
            ERR_INVALID_STATE, "Excursions can only be created on an OPEN slot", 409
        )
    if slot is None:
        raise ApiError(ERR_INVALID_REFERENCE, "slot_id does not exist", 422)
    # Shape tier (8a): surge bounds by event_type.
    if event_type == "REGULAR" and surge != 10000:
        raise ApiError(
            ERR_SURGE_MULTIPLIER_INVALID,
            "REGULAR excursions require surge_multiplier_bp of exactly 10000",
            422,
        )
    if event_type == "HOLIDAY" and not (MIN_HOLIDAY_SURGE_BP <= surge <= MAX_SURGE_BP):
        raise ApiError(
            ERR_SURGE_MULTIPLIER_INVALID,
            "HOLIDAY excursions require surge_multiplier_bp between 12000 and "
            "20000 inclusive",
            422,
        )
    exc = new_entity(
        {
            "title": title,
            "slot_id": slot["id"],
            "event_type": event_type,
            "surge_multiplier_bp": surge,
            "service_date": slot["service_date"],
            "status": "DRAFT",
            "cancel_reason": None,
        }
    )
    db.excursions[exc["id"]] = exc
    # Creating the excursion reserves the slot (OPEN -> RESERVED).
    slot["status"] = "RESERVED"
    touch(slot)
    # Exactly one provisioning manifest per excursion, born DRAFT with zeroes.
    manifest = new_entity(
        {
            "excursion_id": exc["id"],
            "status": "DRAFT",
            "early_diner_count": 0,
            "late_diner_count": 0,
            "galley_load_units": 0,
            "locked_at": None,
            "actual_loaded_units": None,
        }
    )
    db.manifests[manifest["id"]] = manifest
    return success_obj(excursion_view(exc), 201)


@bp.get("/railroad/excursions/<eid>")
def get_excursion(eid):
    require_roles(*ALL_ROLES)
    return success_obj(excursion_view(get_excursion_or_404(eid)), 200)


@bp.get("/railroad/excursions")
def list_excursions():
    require_roles(*ALL_ROLES)
    items = list(db.excursions.values())
    slot_id = request.args.get("slot_id")
    status = request.args.get("status")
    event_type = request.args.get("event_type")
    if slot_id is not None:
        items = [e for e in items if e["slot_id"] == slot_id]
    if status is not None:
        items = [e for e in items if e["status"] == status]
    if event_type is not None:
        items = [e for e in items if e["event_type"] == event_type]
    limit, offset = pagination()
    page, total = paginate(items, limit, offset)
    return success_list([excursion_view(e) for e in page], limit, offset, total)


@bp.get("/railroad/excursions/<eid>/provisioning-manifests")
def get_excursion_manifest(eid):
    require_roles(*ALL_ROLES)
    exc = get_excursion_or_404(eid)
    manifest = find_manifest(exc["id"])
    items = [manifest] if manifest is not None else []
    limit, offset = pagination()
    page, total = paginate(items, limit, offset)
    return success_list([manifest_view(m) for m in page], limit, offset, total)


@bp.post("/railroad/excursions/<eid>/events")
def excursion_event(eid):
    data = body()
    require_event_role(
        data, EVENT_ROLES, ("Scheduler", "OperationsManager")
    )
    exc = get_excursion_or_404(eid)
    event_type = data.get("event_type")

    if event_type == "PUBLISH":
        if exc["status"] != "DRAFT":
            raise ApiError(
                ERR_INVALID_STATE, "Only a DRAFT excursion can be published", 409
            )
        # OCC (tier 6): a stale expected version is rejected with 412.
        expected = opt_int(data, "expected_excursion_version")
        if expected is not None and expected != exc["version"]:
            raise ApiError(
                ERR_STALE_VERSION,
                "expected_excursion_version does not match the current version",
                412,
            )
        if not consist_complete(exc["id"]):
            raise ApiError(
                ERR_CONSIST_INCOMPLETE,
                "Consist needs at least one LOCO and one passenger car",
                409,
            )
        if not crew_coverage_ok(exc["id"]):
            raise ApiError(
                ERR_CREW_COVERAGE_INCOMPLETE,
                "Required crew positions are not covered",
                409,
            )
        exc["status"] = "PUBLISHED"
        touch(exc)
    elif event_type == "BEGIN_BOARDING":
        if exc["status"] != "PUBLISHED":
            raise ApiError(
                ERR_INVALID_STATE,
                "Only a PUBLISHED excursion can begin boarding",
                409,
            )
        # Tier 8(j) crew coverage is re-evaluated before the tier 9(h) date gate.
        if not crew_coverage_ok(exc["id"]):
            raise ApiError(
                ERR_CREW_COVERAGE_INCOMPLETE,
                "Required crew positions are no longer covered",
                409,
            )
        if clock_now().date().isoformat() != exc["service_date"]:
            raise ApiError(
                ERR_NOT_SERVICE_DATE,
                "Boarding is only allowed on the service date",
                409,
            )
        exc["status"] = "BOARDING"
        touch(exc)
    elif event_type == "MARK_OPERATED":
        if exc["status"] != "BOARDING":
            raise ApiError(
                ERR_INVALID_STATE,
                "Only a BOARDING excursion can be marked operated",
                409,
            )
        mark_operated(exc)
    elif event_type == "CANCEL":
        if exc["status"] not in ("DRAFT", "PUBLISHED", "BOARDING"):
            raise ApiError(
                ERR_INVALID_STATE,
                "Excursion can no longer be cancelled",
                409,
            )
        reason = req_enum(data, "cancel_reason", CANCEL_REASONS)
        cancel_excursion(exc, reason, "OPEN")
    else:
        raise ApiError(ERR_VALIDATION, "Unknown event_type: %r" % event_type, 400)
    return success_obj(excursion_view(exc), 200)
