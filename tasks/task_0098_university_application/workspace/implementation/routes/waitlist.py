"""Waitlist routes."""
from __future__ import annotations

from flask import Blueprint, request

from core.auth import require_roles
from core.clock import clock
from core.errors import raise_error
from core.response import success_object
from core.store import store
from services.engine import (
    app_transition_to_admitted,
    check_version,
    get_waitlist,
)
from services.serializers import waitlist_out
from services.time_utils import parse_iso

bp = Blueprint("waitlist", __name__)


@bp.get("/waitlist/<wl_id>")
@require_roles("Applicant", "AdmissionsOfficer", "PlatformAdmin")
def read_waitlist(wl_id: str):
    rec = get_waitlist(wl_id)
    return success_object(waitlist_out(rec), 200)


@bp.post("/waitlist/<wl_id>/accept-offer")
@require_roles("Applicant")
def accept_offer(wl_id: str):
    entry = get_waitlist(wl_id)
    body = request.get_json(silent=True) or {}
    if not isinstance(body, dict):
        body = {}
    if entry["status"] != "OFFERED":
        raise_error("ERR_INVALID_STATE")
    check_version(entry, body.get("version"))
    if parse_iso(clock.iso()) > parse_iso(entry["offer_expires_at"]):
        raise_error("ERR_OFFER_EXPIRED")
    app = store.applications.get(entry["application_id"])
    if app is None or app["status"] != "WAITLISTED":
        raise_error("ERR_INVALID_STATE")
    program = store.programs.get(entry["program_id"])
    if program is None:
        raise_error("ERR_INVALID_STATE")

    # The yield sweep provisionally reserved a seat via admitted_count++ when promoting this
    # entry; revert that provisional reservation so the WAITLISTED->ADMITTED cascade can re-
    # increment with a single capacity check (atomic compare-and-increment).
    if program.get("admitted_count", 0) > 0:
        program["admitted_count"] = program["admitted_count"] - 1
        store.bump(program)

    if program.get("admitted_count", 0) + 1 > program["capacity"]:
        # Restore reservation, then reject
        program["admitted_count"] = program["admitted_count"] + 1
        store.bump(program)
        raise_error("ERR_PROGRAM_AT_CAPACITY")

    entry["status"] = "ACCEPTED"
    store.bump(entry)
    # Cascade: Application WAITLISTED -> ADMITTED
    app_transition_to_admitted(app)
    return success_object(waitlist_out(entry), 200)
