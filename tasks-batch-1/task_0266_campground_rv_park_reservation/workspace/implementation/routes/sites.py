"""Site, MaintenanceHold endpoints + site state transitions."""
from flask import Blueprint, request

from db import store, new_id
import errors
from middleware import get_principal, require_role, ROLE_OPERATOR, ROLE_GUEST
from response import success, success_list
from services.common import stamp_common, touch, parse_date
from services import validate as V
from services.listing import pagination, paginate
from services.serializers import serialize_site, serialize_maintenance_hold
from services import reservation_ops as ops

bp = Blueprint("sites", __name__)

SITE_TYPES = {"TENT", "RV", "CABIN"}
HOOKUP_LEVELS = {"NONE", "PARTIAL", "FULL"}


def _check_site_occ(site, body):
    """expected_site_version is required on site-guarded writes (PRD §2.6)."""
    expected = body.get("expected_site_version")
    if expected is None:
        raise errors.err(errors.ERR_INVALID_REQUEST, "Missing required field: expected_site_version")
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise errors.err(errors.ERR_INVALID_REQUEST, "expected_site_version must be an integer")
    if expected != site["version"]:
        raise errors.err(errors.ERR_STALE_SITE_VERSION, "Stale site version")


# ---------------------------------------------------------------------------
# Site create / read / list
# ---------------------------------------------------------------------------
@bp.route("/parks/<pid>/sites", methods=["POST"])
def create_site(pid):
    _, role = get_principal()
    require_role(role, {ROLE_OPERATOR})
    park = store.parks.get(pid)
    if park is None:
        raise errors.err(errors.ERR_NOT_FOUND, "Park not found")
    body = V.get_json_body()
    V.require_fields(body, ["rate_plan_id", "label", "site_type", "hookup_level", "max_length_of_stay_nights"])
    rate_plan_id = V.require_str(body, "rate_plan_id")
    label = V.require_str(body, "label")
    site_type = V.require_enum(body, "site_type", SITE_TYPES)
    hookup = V.require_enum(body, "hookup_level", HOOKUP_LEVELS)
    max_stay = V.require_int(body, "max_length_of_stay_nights")
    if max_stay < 0:
        raise errors.err(errors.ERR_INVALID_REQUEST, "max_length_of_stay_nights must be non-negative")
    buffer = V.optional_int(body, "turnover_buffer_days", default=1, non_negative=True)

    # Existence: rate plan must exist (left-to-right after park).
    rate_plan = store.rate_plans.get(rate_plan_id)
    if rate_plan is None:
        raise errors.err(errors.ERR_NOT_FOUND, "Rate plan not found")

    # Referential: RatePlan.site_type must equal Site.site_type -> 422.
    if rate_plan["site_type"] != site_type:
        raise errors.err(
            errors.ERR_RATE_PLAN_TYPE_MISMATCH,
            "Rate plan site_type does not match site site_type",
        )

    sid = new_id()
    site = {
        "id": sid,
        "park_id": pid,
        "rate_plan_id": rate_plan_id,
        "label": label,
        "site_type": site_type,
        "hookup_level": hookup,
        "max_length_of_stay_nights": max_stay,
        "turnover_buffer_days": buffer,
        "status": "ACTIVE",
    }
    stamp_common(site)
    store.sites[sid] = site
    return success(serialize_site(site), 201)


@bp.route("/sites/<sid>", methods=["GET"])
def get_site(sid):
    _, role = get_principal()
    require_role(role, {ROLE_OPERATOR, ROLE_GUEST})
    site = store.sites.get(sid)
    if site is None:
        raise errors.err(errors.ERR_NOT_FOUND, "Site not found")
    return success(serialize_site(site), 200)


@bp.route("/sites", methods=["GET"])
def list_sites():
    _, role = get_principal()
    require_role(role, {ROLE_OPERATOR, ROLE_GUEST})
    items = list(store.sites.values())
    park_id = request.args.get("park_id")
    rate_plan_id = request.args.get("rate_plan_id")
    site_type = request.args.get("site_type")
    status = request.args.get("status")
    if park_id is not None:
        items = [s for s in items if s["park_id"] == park_id]
    if rate_plan_id is not None:
        items = [s for s in items if s["rate_plan_id"] == rate_plan_id]
    if site_type is not None:
        items = [s for s in items if s["site_type"] == site_type]
    if status is not None:
        items = [s for s in items if s["status"] == status]
    limit, offset = pagination()
    page, total = paginate(items, limit, offset)
    return success_list([serialize_site(s) for s in page], limit, offset, total)


@bp.route("/parks/<pid>/sites", methods=["GET"])
def list_park_sites(pid):
    _, role = get_principal()
    require_role(role, {ROLE_OPERATOR, ROLE_GUEST})
    park = store.parks.get(pid)
    if park is None:
        raise errors.err(errors.ERR_NOT_FOUND, "Park not found")
    items = [s for s in store.sites.values() if s["park_id"] == pid]
    status = request.args.get("status")
    if status is not None:
        items = [s for s in items if s["status"] == status]
    limit, offset = pagination()
    page, total = paginate(items, limit, offset)
    return success_list([serialize_site(s) for s in page], limit, offset, total)


# ---------------------------------------------------------------------------
# Site state transitions
# ---------------------------------------------------------------------------
@bp.route("/sites/<sid>/maintenance", methods=["POST"])
def site_maintenance(sid):
    _, role = get_principal()
    require_role(role, {ROLE_OPERATOR})
    site = store.sites.get(sid)
    if site is None:
        raise errors.err(errors.ERR_NOT_FOUND, "Site not found")
    body = V.get_json_body()
    _check_site_occ(site, body)
    if site["status"] != "ACTIVE":
        raise errors.err(errors.ERR_INVALID_STATE, "Site is not ACTIVE")
    site["status"] = "MAINTENANCE"
    touch(site)
    return success(serialize_site(site), 200)


@bp.route("/sites/<sid>/reactivate", methods=["POST"])
def site_reactivate(sid):
    _, role = get_principal()
    require_role(role, {ROLE_OPERATOR})
    site = store.sites.get(sid)
    if site is None:
        raise errors.err(errors.ERR_NOT_FOUND, "Site not found")
    body = V.get_json_body()
    _check_site_occ(site, body)
    if site["status"] != "MAINTENANCE":
        raise errors.err(errors.ERR_INVALID_STATE, "Site is not in MAINTENANCE")
    site["status"] = "ACTIVE"
    touch(site)
    return success(serialize_site(site), 200)


@bp.route("/sites/<sid>/retire", methods=["POST"])
def site_retire(sid):
    _, role = get_principal()
    require_role(role, {ROLE_OPERATOR})
    site = store.sites.get(sid)
    if site is None:
        raise errors.err(errors.ERR_NOT_FOUND, "Site not found")
    body = V.get_json_body()
    _check_site_occ(site, body)
    if site["status"] not in ("ACTIVE", "MAINTENANCE"):
        raise errors.err(errors.ERR_INVALID_STATE, "Site cannot be retired from its current state")
    ops.retire_site(site)
    return success(serialize_site(site), 200)


# ---------------------------------------------------------------------------
# MaintenanceHold
# ---------------------------------------------------------------------------
@bp.route("/sites/<sid>/maintenance-holds", methods=["POST"])
def create_maintenance_hold(sid):
    _, role = get_principal()
    require_role(role, {ROLE_OPERATOR})
    site = store.sites.get(sid)
    if site is None:
        raise errors.err(errors.ERR_NOT_FOUND, "Site not found")
    body = V.get_json_body()
    V.require_fields(body, ["start_date", "end_date"])
    start_s = V.require_str(body, "start_date")
    end_s = V.require_str(body, "end_date")
    start_d = parse_date(start_s)
    end_d = parse_date(end_s)
    if end_d < start_d:
        raise errors.err(errors.ERR_INVALID_REQUEST, "end_date must be >= start_date")
    _check_site_occ(site, body)

    reason = body.get("reason")
    if reason is not None and not isinstance(reason, str):
        raise errors.err(errors.ERR_INVALID_REQUEST, "reason must be a string")

    hid = new_id()
    hold = {
        "id": hid,
        "site_id": sid,
        "start_date": start_s,
        "end_date": end_s,
        "reason": reason,
        "status": "ACTIVE",
    }
    stamp_common(hold)
    store.maintenance_holds[hid] = hold
    # Placing a hold bumps the host site's version (PRD §3.4).
    touch(site)
    return success(serialize_maintenance_hold(hold), 201)


@bp.route("/sites/<sid>/maintenance-holds", methods=["GET"])
def list_maintenance_holds(sid):
    _, role = get_principal()
    require_role(role, {ROLE_OPERATOR, ROLE_GUEST})
    site = store.sites.get(sid)
    if site is None:
        raise errors.err(errors.ERR_NOT_FOUND, "Site not found")
    items = [h for h in store.maintenance_holds.values() if h["site_id"] == sid]
    status = request.args.get("status")
    if status is not None:
        items = [h for h in items if h["status"] == status]
    limit, offset = pagination()
    page, total = paginate(items, limit, offset)
    return success_list(
        [serialize_maintenance_hold(h) for h in page], limit, offset, total
    )


@bp.route("/maintenance-holds/<hid>/clear", methods=["POST"])
def clear_maintenance_hold(hid):
    _, role = get_principal()
    require_role(role, {ROLE_OPERATOR})
    hold = store.maintenance_holds.get(hid)
    if hold is None:
        raise errors.err(errors.ERR_NOT_FOUND, "Maintenance hold not found")
    if hold["status"] != "ACTIVE":
        raise errors.err(errors.ERR_INVALID_STATE, "Maintenance hold is not ACTIVE")
    hold["status"] = "CLEARED"
    touch(hold)
    site = store.sites.get(hold["site_id"])
    if site is not None:
        touch(site)
    return success(serialize_maintenance_hold(hold), 200)
