"""Program + logical clock routes."""
from flask import Blueprint
from datetime import datetime, timezone

from db import store, new_id, now_iso
from middleware import get_auth, require_role, get_body, req_string, req_int, opt_number, apply_pagination
from response import success_object, success_list
from errors import not_found, invalid_request
from services.core import parse_iso

bp = Blueprint("programs", __name__)


def program_view(p):
    return {
        "id": p["id"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
        "name": p["name"],
        "state_code": p["state_code"],
        "companion_guide_version": p["companion_guide_version"],
        "completeness_threshold": p["completeness_threshold"],
        "accuracy_threshold": p["accuracy_threshold"],
        "provider_yellow_threshold": p["provider_yellow_threshold"],
        "provider_red_threshold": p["provider_red_threshold"],
        "penalty_cap_percent": p["penalty_cap_percent"],
        "penalty_threshold_cents": p["penalty_threshold_cents"],
        "posture": p["posture"],
        "penalties_outstanding_cents": p["penalties_outstanding_cents"],
    }


@bp.route("/programs", methods=["POST"])
def create_program():
    _, role = get_auth()
    require_role(role, {"StateAgency"})
    body = get_body()
    for f in ("name", "state_code", "companion_guide_version"):
        req_string(body, f)
    penalty_threshold_cents = req_int(body, "penalty_threshold_cents")
    if penalty_threshold_cents < 0:
        raise invalid_request("penalty_threshold_cents must not be negative")
    completeness_threshold = opt_number(body, "completeness_threshold", 0.98)
    accuracy_threshold = opt_number(body, "accuracy_threshold", 0.95)
    provider_yellow_threshold = opt_number(body, "provider_yellow_threshold", 0.02)
    provider_red_threshold = opt_number(body, "provider_red_threshold", 0.05)
    penalty_cap_percent = opt_number(body, "penalty_cap_percent", 0.10)

    pid = new_id()
    p = {
        "id": pid,
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "version": 1,
        "name": body["name"],
        "state_code": body["state_code"],
        "companion_guide_version": body["companion_guide_version"],
        "completeness_threshold": completeness_threshold,
        "accuracy_threshold": accuracy_threshold,
        "provider_yellow_threshold": provider_yellow_threshold,
        "provider_red_threshold": provider_red_threshold,
        "penalty_cap_percent": penalty_cap_percent,
        "penalty_threshold_cents": penalty_threshold_cents,
        # Posture is derived: outstanding (0 at creation) >= threshold flips RESTRICTED,
        # boundary inclusive — so a zero threshold program is born RESTRICTED.
        "posture": "RESTRICTED" if 0 >= penalty_threshold_cents else "OPEN",
        "penalties_outstanding_cents": 0,
    }
    store.programs[pid] = p
    return success_object(program_view(p), 201)


@bp.route("/programs/<pid>", methods=["GET"])
def get_program(pid):
    get_auth()
    p = store.programs.get(pid)
    if p is None:
        raise not_found()
    return success_object(program_view(p))


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    _, role = get_auth()
    require_role(role, {"StateAgency"})
    body = get_body()
    to_iso8601 = req_string(body, "to_iso8601")
    store.clock = parse_iso(to_iso8601, "to_iso8601")
    store.clock_raw = to_iso8601
    return success_object({"current_utc": to_iso8601})
