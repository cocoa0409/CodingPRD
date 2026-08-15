"""Site registry and SiteActivation lifecycle."""
import clock
import db
from auth import require_roles, ALL_ROLES
from errors import (
    raise_err, ERR_NOT_FOUND, ERR_INVALID_STATE, ERR_STALE_VERSION,
    ERR_EPISODE_NOT_ACTIVE, ERR_OVERNIGHT_COVERAGE_GAP,
    ERR_LEAD_COVERAGE_MISSING, ERR_VALIDATION, ERR_STAYS_STILL_ACTIVE,
)
from flask import Blueprint, request
from response import respond, respond_list
from services import (
    episodes_activations, close_activation, coverage, ser_activation,
    ser_site,
)
from util import (
    body, opt_int, opt_str, paginate, req_int, req_str, touch,
)

bp = Blueprint("sites", __name__)


def get_site(site_id):
    site = db.store["sites"].get(site_id)
    if site is None:
        raise_err(ERR_NOT_FOUND, f"Site {site_id} not found")
    return site


def get_activation(act_id):
    act = db.store["activations"].get(act_id)
    if act is None:
        raise_err(ERR_NOT_FOUND, f"SiteActivation {act_id} not found")
    return act


def _validate_capacity(b, name):
    return opt_int(b, name, default=None, min_value=0)


# ------------------------------------------------------------------ sites
@bp.route("/sites", methods=["POST"])
@require_roles("EOCManager")
def create_site():
    b = body()
    name = req_str(b, "name")
    address = req_str(b, "address")
    bed_capacity = req_int(b, "bed_capacity", min_value=0)
    pet_capacity = req_int(b, "pet_capacity", min_value=0)
    locker_capacity = req_int(b, "locker_capacity", min_value=0)
    now = clock.now()
    site = {
        "id": db.new_id(),
        "_seq": db.next_seq(),
        "name": name,
        "address": address,
        "bed_capacity": bed_capacity,
        "pet_capacity": pet_capacity,
        "locker_capacity": locker_capacity,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.store["sites"][site["id"]] = site
    return respond(ser_site(site), 201)


@bp.route("/sites/<site_id>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_one_site(site_id):
    return respond(ser_site(get_site(site_id)), 200)


@bp.route("/sites/<site_id>", methods=["PATCH"])
@require_roles("EOCManager")
def patch_site(site_id):
    site = get_site(site_id)
    b = body()
    # OCC guard (priority 4) precedes payload validation.
    if "expected_site_version" not in b or b["expected_site_version"] is None:
        raise_err(ERR_VALIDATION, "Missing required field: expected_site_version")
    expected = b["expected_site_version"]
    if not isinstance(expected, int) or isinstance(expected, bool):
        raise_err(ERR_VALIDATION, "expected_site_version must be an integer")
    if expected != site["version"]:
        raise_err(
            ERR_STALE_VERSION,
            f"expected_site_version {expected} does not match current "
            f"version {site['version']}",
        )
    name = opt_str(b, "name", default=None)
    address = opt_str(b, "address", default=None)
    bed_capacity = _validate_capacity(b, "bed_capacity")
    pet_capacity = _validate_capacity(b, "pet_capacity")
    locker_capacity = _validate_capacity(b, "locker_capacity")
    if name is not None:
        site["name"] = name
    if address is not None:
        site["address"] = address
    if bed_capacity is not None:
        site["bed_capacity"] = bed_capacity
    if pet_capacity is not None:
        site["pet_capacity"] = pet_capacity
    if locker_capacity is not None:
        site["locker_capacity"] = locker_capacity
    touch(site)
    return respond(ser_site(site), 200)


# --------------------------------------------------------- site activations
@bp.route("/episodes/<episode_id>/site-activations", methods=["POST"])
@require_roles("EOCManager")
def designate_site(episode_id):
    ep = db.store["episodes"].get(episode_id)
    if ep is None:
        raise_err(ERR_NOT_FOUND, f"Episode {episode_id} not found")
    b = body()
    site = None
    if b.get("site_id") is not None:
        site = get_site(b["site_id"])
    if ep["status"] not in ("STANDBY", "ACTIVATING", "ACTIVE"):
        raise_err(
            ERR_INVALID_STATE,
            f"Cannot designate a site while the episode is {ep['status']}",
        )
    if site is None:
        if "site_id" not in b or b["site_id"] is None:
            raise_err(ERR_VALIDATION, "Missing required field: site_id")
        site = get_site(b["site_id"])
    capacity_override = _validate_capacity(b, "capacity_override")
    now = clock.now()
    act = {
        "id": db.new_id(),
        "_seq": db.next_seq(),
        "episode_id": ep["id"],
        "site_id": site["id"],
        "capacity_override": capacity_override,
        "status": "OPENING",
        "beds_effective": None,
        "opened_at": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.store["activations"][act["id"]] = act
    return respond(ser_activation(act), 201)


@bp.route("/site-activations", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_activations():
    items = list(db.store["activations"].values())
    episode_id = request.args.get("episode_id")
    site_id = request.args.get("site_id")
    status = request.args.get("status")
    if episode_id is not None:
        items = [a for a in items if a["episode_id"] == episode_id]
    if site_id is not None:
        items = [a for a in items if a["site_id"] == site_id]
    if status is not None:
        items = [a for a in items if a["status"] == status]
    items.sort(key=lambda a: (a["created_at"], a["_seq"]))
    page, pagination = paginate([ser_activation(a) for a in items])
    return respond_list(page, pagination)


@bp.route("/site-activations/<act_id>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_one_activation(act_id):
    return respond(ser_activation(get_activation(act_id)), 200)


@bp.route("/site-activations/<act_id>/open", methods=["POST"])
@require_roles("SiteLead")
def open_activation(act_id):
    act = get_activation(act_id)
    ep = db.store["episodes"].get(act["episode_id"])
    if ep is None or ep["status"] != "ACTIVE":
        raise_err(
            ERR_EPISODE_NOT_ACTIVE,
            "Opening requires the episode to be ACTIVE",
        )
    if act["status"] != "OPENING":
        raise_err(
            ERR_INVALID_STATE,
            f"Cannot open a site activation in status {act['status']}",
        )
    site = db.store["sites"].get(act["site_id"])
    beds_to_pin = (act["capacity_override"] if act["capacity_override"] is not None
                   else (site["bed_capacity"] if site else 0))
    if beds_to_pin < 1:
        raise_err(
            ERR_VALIDATION,
            "beds_effective to be pinned must be at least 1",
        )
    gap, lead_ok = coverage(act)
    if gap != 0:
        raise_err(
            ERR_OVERNIGHT_COVERAGE_GAP,
            f"Overnight coverage gap is {gap} minutes; must be 0",
        )
    if not lead_ok:
        raise_err(
            ERR_LEAD_COVERAGE_MISSING,
            "No CONFIRMED SITE_LEAD shift fully contains the overnight window",
        )
    act["status"] = "OPEN"
    act["beds_effective"] = beds_to_pin
    if act["opened_at"] is None:
        act["opened_at"] = clock.now()
    touch(act)
    return respond(ser_activation(act), 200)


@bp.route("/site-activations/<act_id>/close", methods=["POST"])
@require_roles("SiteLead")
def close_activation_route(act_id):
    act = get_activation(act_id)
    if act["status"] not in ("OPENING", "DRAINING"):
        raise_err(
            ERR_INVALID_STATE,
            f"Cannot close a site activation in status {act['status']}",
        )
    active_stays = any(
        s for s in db.store["stays"].values()
        if s["site_activation_id"] == act["id"]
        and s["status"] in ("RESERVED", "CHECKED_IN")
    )
    if active_stays:
        raise_err(
            ERR_STAYS_STILL_ACTIVE,
            "Stays in RESERVED or CHECKED_IN remain at this activation",
        )
    close_activation(act)
    return respond(ser_activation(act), 200)
