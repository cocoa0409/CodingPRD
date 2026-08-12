"""Provider and AvailabilityWindow routes."""
from datetime import timedelta
from flask import Blueprint, request

import db
from errors import (
    err_not_found, err_invalid_request, err_invalid_state, err_window_overlap,
    err_provider_not_active, err_forbidden_ownership, err_posture_gate,
)
from middleware import require_roles, check_provider_ownership
from response import success
from services.util import (
    body, req_str, req_enum, opt_bool, opt_str, req_ts, req_int,
    paginate, serialize, overlaps,
)
from services import core

bp = Blueprint("providers", __name__)

CREDENTIAL_LEVELS = {"STANDARD", "ENHANCED"}
PROVIDER_TARGETS = {"ACTIVE", "SUSPENDED", "TERMINATED"}


def _provider_or_404(pid):
    p = db.providers.get(pid)
    if p is None:
        raise err_not_found("provider")
    return p


def _window_or_404(wid):
    w = db.windows.get(wid)
    if w is None:
        raise err_not_found("window")
    return w


@bp.route("/respite/providers", methods=["POST"])
def create_provider():
    require_roles("Anonymous", "Coordinator")
    data = body()
    name = req_str(data, "name")
    credential_level = req_enum(data, "credential_level", CREDENTIAL_LEVELS)
    service_zip = req_str(data, "service_zip")
    accepts_emergency = opt_bool(data, "accepts_emergency", False)
    # posture gate: creating a provider requires ENROLLMENT_OPEN on the program.
    for prog in db.programs.values():
        if prog["posture"] != "ENROLLMENT_OPEN":
            raise err_posture_gate()
    base = db.new_common()
    p = {
        **base,
        "name": name,
        "credential_level": credential_level,
        "service_zip": service_zip,
        "accepts_emergency": bool(accepts_emergency),
        "credential_status": "APPLIED",
        "credential_expires_at": None,
        "quality_score_simple": None,
        "quality_score_weighted": None,
        "suspension_reason": None,
    }
    db.providers[p["id"]] = p
    return success(serialize(p, "provider"), status=201)


@bp.route("/respite/providers/<pid>", methods=["GET"])
def get_provider(pid):
    require_roles("Provider", "Caregiver", "Coordinator", "FunderAdmin")
    p = _provider_or_404(pid)
    return success(serialize(p, "provider"))


@bp.route("/respite/providers/<pid>/status-transitions", methods=["POST"])
def provider_status_transition(pid):
    require_roles("Coordinator")
    data = body()
    target = req_enum(data, "target_status", PROVIDER_TARGETS)
    reason = opt_str(data, "reason")
    p = _provider_or_404(pid)
    cur = p["credential_status"]
    allowed = {
        ("APPLIED", "ACTIVE"),
        ("APPLIED", "TERMINATED"),
        ("ACTIVE", "SUSPENDED"),
        ("ACTIVE", "TERMINATED"),
        ("SUSPENDED", "ACTIVE"),
        ("SUSPENDED", "TERMINATED"),
        ("LAPSED", "ACTIVE"),
    }
    if (cur, target) not in allowed:
        raise err_invalid_state(f"Provider transition {cur} -> {target} not permitted")
    if target == "TERMINATED" and cur in ("ACTIVE", "SUSPENDED"):
        for b in db.bookings.values():
            if b["provider_id"] == pid and b["status"] in (
                "PENDING_CONFIRMATION", "CONFIRMED", "IN_SERVICE",
            ):
                raise err_invalid_state(
                    "Provider has live bookings; cannot terminate"
                )
    if target == "ACTIVE":
        p["credential_expires_at"] = db.now() + timedelta(days=180)
        if cur == "SUSPENDED":
            p["suspension_reason"] = None
    elif target == "SUSPENDED":
        p["suspension_reason"] = reason
    p["credential_status"] = target
    db.touch(p)
    return success(serialize(p, "provider"))


@bp.route("/respite/providers/<pid>/availability-windows", methods=["GET", "POST"])
def provider_windows(pid):
    if request.method == "GET":
        require_roles("Provider", "Caregiver", "Coordinator", "FunderAdmin")
        _provider_or_404(pid)
        status = request.args.get("status")
        items = [w for w in db.windows.values() if w["provider_id"] == pid]
        if status:
            items = [w for w in items if w["status"] == status]
        page, meta = paginate(items)
        return success(
            [serialize(w, "window") for w in page],
            response_type="array",
            pagination=meta,
        )
    # POST
    user_id, role = require_roles("Provider")
    p = _provider_or_404(pid)
    check_provider_ownership(user_id, role, p["id"])
    data = body()
    start_at = req_ts(data, "start_at")
    end_at = req_ts(data, "end_at")
    capacity = req_int(data, "capacity")
    if capacity < 1:
        raise err_invalid_request("capacity must be >= 1")
    if end_at <= start_at:
        raise err_invalid_request("end_at must be after start_at")
    # provider credential check (priority 9)
    if p["credential_status"] != "ACTIVE":
        raise err_provider_not_active()
    # overlap check: no overlap with any non-WITHDRAWN window of this provider
    for w in db.windows.values():
        if w["provider_id"] != pid:
            continue
        if w["status"] in ("WITHDRAWN",):
            continue
        if overlaps(start_at, end_at, w["start_at"], w["end_at"]):
            raise err_window_overlap()
    base = db.new_common()
    window = {
        **base,
        "provider_id": pid,
        "start_at": start_at,
        "end_at": end_at,
        "capacity": capacity,
        "status": "OPEN",
    }
    db.windows[window["id"]] = window
    return success(serialize(window, "window"), status=201)


@bp.route("/respite/availability-windows/<wid>/close", methods=["POST"])
def close_window(wid):
    user_id, role = require_roles("Provider")
    w = _window_or_404(wid)
    check_provider_ownership(user_id, role, w["provider_id"])
    if w["status"] not in ("OPEN", "FULLY_BOOKED"):
        raise err_invalid_state("Window cannot be withdrawn from its current state")
    for b in db.bookings.values():
        if b.get("window_id") == wid and b["status"] in (
            "PENDING_CONFIRMATION", "CONFIRMED", "IN_SERVICE",
        ):
            raise err_invalid_state(
                "Window has live bookings; cannot withdraw"
            )
    w["status"] = "WITHDRAWN"
    db.touch(w)
    return success(serialize(w, "window"))
