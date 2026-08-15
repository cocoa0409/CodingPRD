"""ReleaseEvent reporting and regulator disposition (PRD 3.8)."""
from flask import Blueprint

from authz import (
    FACILITY_OWNER, READ_ROLES, STATE_REGULATOR, check_facility_ownership,
    require_roles,
)
from calc import recompute_posture
from cascades import close_tank_cascade, create_release_event
from db import store
from errors import (
    release_event_not_found, release_not_cleanup, release_not_confirmed,
    release_not_suspected,
)
from respond import success
from routes.facilities import get_facility_or_404
from routes.tanks import get_tank_or_404
from serialize import ser_release_event
from store_ops import (
    check_closed, get_or_404, json_body, opt_str, paginate, qparam, req_instant,
    req_str, sorted_by_creation, touch,
)

bp = Blueprint("release_events", __name__)


def get_release_or_404(rel_id):
    return get_or_404(store.release_events, rel_id, release_event_not_found)


@bp.route("/release-events", methods=["POST"])
def create_release():
    uid, _ = require_roles([FACILITY_OWNER])
    data = json_body()
    check_closed(data, {"facility_id", "tank_system_id", "discovered_at",
                        "source_description"})
    facility_id = req_str(data, "facility_id")
    tank_system_id = opt_str(data, "tank_system_id")
    discovered_at = req_instant(data, "discovered_at")
    source_description = req_str(data, "source_description")

    fac = get_facility_or_404(facility_id)
    check_facility_ownership(uid, fac)
    if tank_system_id is not None:
        get_tank_or_404(tank_system_id)

    r = create_release_event(facility_id, tank_system_id, discovered_at,
                             source_description)
    recompute_posture(fac)
    return success(ser_release_event(r), status=201)


@bp.route("/release-events", methods=["GET"])
def list_releases():
    require_roles(READ_ROLES)
    items = store.release_events.values()
    for f in ("facility_id", "tank_system_id", "status"):
        v = qparam(f)
        if v is not None:
            items = [r for r in items if r[f] == v]
    items = sorted_by_creation(items)
    page, pagination = paginate(items)
    return success([ser_release_event(r) for r in page], response_type="array",
                   pagination=pagination)


@bp.route("/release-events/<rel_id>", methods=["GET"])
def get_release(rel_id):
    require_roles(READ_ROLES)
    return success(ser_release_event(get_release_or_404(rel_id)))


def _stamp_reported(r):
    r["reported_to_state_at"] = store.clock
    r["late_notification"] = r["reported_to_state_at"] > r["report_deadline"]


@bp.route("/release-events/<rel_id>/confirm", methods=["POST"])
def confirm_release(rel_id):
    require_roles([STATE_REGULATOR])
    json_body()
    r = get_release_or_404(rel_id)
    if r["status"] != "SUSPECTED":
        raise release_not_suspected()
    _stamp_reported(r)
    r["status"] = "CONFIRMED"
    touch(r)
    # Cascade: the linked tank (unless permanently closed) temporarily closes,
    # which cancels its pending orders and falls linked re-test deficiencies
    # back to CORRECTED.
    if r["tank_system_id"]:
        tank = store.tank_systems.get(r["tank_system_id"])
        if tank is not None and tank["status"] != "PERMANENTLY_CLOSED":
            close_tank_cascade(tank, "TEMPORARILY_CLOSED")
    recompute_posture(get_facility_or_404(r["facility_id"]))
    return success(ser_release_event(r))


@bp.route("/release-events/<rel_id>/dismiss", methods=["POST"])
def dismiss_release(rel_id):
    require_roles([STATE_REGULATOR])
    json_body()
    r = get_release_or_404(rel_id)
    if r["status"] != "SUSPECTED":
        raise release_not_suspected()
    _stamp_reported(r)
    r["status"] = "DISMISSED"
    touch(r)
    recompute_posture(get_facility_or_404(r["facility_id"]))
    return success(ser_release_event(r))


@bp.route("/release-events/<rel_id>/begin-cleanup", methods=["POST"])
def begin_cleanup(rel_id):
    uid, _ = require_roles([FACILITY_OWNER])
    json_body()
    r = get_release_or_404(rel_id)
    fac = get_facility_or_404(r["facility_id"])
    check_facility_ownership(uid, fac)
    if r["status"] != "CONFIRMED":
        raise release_not_confirmed()
    r["status"] = "CLEANUP_IN_PROGRESS"
    touch(r)
    return success(ser_release_event(r))


@bp.route("/release-events/<rel_id>/close", methods=["POST"])
def close_release(rel_id):
    require_roles([STATE_REGULATOR])
    json_body()
    r = get_release_or_404(rel_id)
    if r["status"] != "CLEANUP_IN_PROGRESS":
        raise release_not_cleanup()
    r["status"] = "CLOSED"
    touch(r)
    recompute_posture(get_facility_or_404(r["facility_id"]))
    return success(ser_release_event(r))
