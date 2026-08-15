"""Waitlist endpoints."""
from flask import Blueprint, request

from db import store
from errors import (
    ApiError, ERR_INVALID_REQUEST, ERR_NOT_FOUND, ERR_INTAKE_PAUSED,
    ERR_CYCLE_PHASE_MISMATCH, ERR_WAITLIST_EMPTY,
)
from middleware import require_roles
from response import success_object, success_list
from services.derived import (
    recompute_program, recompute_cycle, select_top_waitlist_entry,
    activate_waitlist_entry,
)
from services.serializers import serialize_waitlist_entry

bp = Blueprint("waitlist", __name__, url_prefix="/enrollment")


@bp.route("/waitlist-entries/<entryId>", methods=["GET"])
def get_entry(entryId):
    require_roles("SystemAdmin", "EnrollmentManager", "AdmissionsOfficer")
    e = store.waitlist_entries.get(entryId)
    if not e:
        raise ApiError(ERR_NOT_FOUND, 404, "Waitlist entry not found")
    return success_object(serialize_waitlist_entry(e))


@bp.route("/waitlist-entries", methods=["GET"])
def list_entries():
    require_roles("SystemAdmin", "EnrollmentManager", "AdmissionsOfficer")
    program_id = request.args.get("program_id")
    application_id = request.args.get("application_id")
    status = request.args.get("status")
    try:
        limit = int(request.args.get("limit", 10))
        offset = int(request.args.get("offset", 0))
    except (ValueError, TypeError):
        raise ApiError(ERR_INVALID_REQUEST, 400, "limit/offset must be integers")
    limit = max(1, min(100, limit))
    offset = max(0, offset)

    items = list(store.waitlist_entries.values())
    if program_id:
        items = [e for e in items if e["program_id"] == program_id]
    if application_id:
        items = [e for e in items if e["application_id"] == application_id]
    if status:
        items = [e for e in items if e["status"] == status]
    items.sort(key=lambda e: (e["created_at"], e["id"]))
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serialize_waitlist_entry(e) for e in page], limit, offset, total)


@bp.route("/waitlist-activations", methods=["POST"])
def activate():
    require_roles("EnrollmentManager")
    body = request.get_json(silent=True) or {}
    program_id = body.get("program_id")
    if not program_id or program_id not in store.programs:
        raise ApiError(ERR_NOT_FOUND, 404, "program_id not found")
    program = store.programs[program_id]
    cycle = store.cycles.get(program["cycle_id"])

    recompute_program(program)
    if program["intake_posture"] != "OPEN":
        raise ApiError(ERR_INTAKE_PAUSED, 409, "intake_posture not OPEN")
    if cycle and cycle["status"] not in ("DECISIONS_RELEASED", "ENROLLMENT_TRACKING"):
        raise ApiError(ERR_CYCLE_PHASE_MISMATCH, 409, "cycle phase mismatch")

    entry = select_top_waitlist_entry(program_id)
    if not entry:
        raise ApiError(ERR_WAITLIST_EMPTY, 409, "No ACTIVE waitlist entry")

    activate_waitlist_entry(entry)
    if cycle:
        recompute_cycle(cycle)
    return success_object(serialize_waitlist_entry(entry))
