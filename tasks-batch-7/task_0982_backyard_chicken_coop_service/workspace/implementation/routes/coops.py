"""CoopSite endpoints (PRD §3.4). Lifecycle is entirely system-driven."""
from flask import Blueprint, request

from db import new_id, serialize, stamp_new, store
from errors import fail
from middleware import ALL_ROLES, authenticate, body, require_owner, require_role
from response import list_response, ok
from util import is_int, req_str

bp = Blueprint("coops", __name__)

CUSTOMER_OR_ADMIN = {"Customer", "PlatformAdmin"}


def get_coop(cid):
    c = store.coops.get(cid)
    if c is None:
        fail("ERR_COOP_SITE_NOT_FOUND", f"Coop site {cid} does not exist")
    return c


@bp.route("/coopcare/coop-sites", methods=["POST"])
def create_coop():
    uid, role = authenticate()
    require_role(role, CUSTOMER_OR_ADMIN)
    data = body()
    household_id = data.get("household_id")
    require_owner(uid, role, household_id if isinstance(household_id, str) else None)
    if not isinstance(household_id, str) or not household_id.strip():
        fail("ERR_INVALID_REQUEST", "household_id is required")
    if household_id not in store.households:
        fail("ERR_HOUSEHOLD_NOT_FOUND", f"Household {household_id} does not exist")
    site_label = req_str(data, "site_label")
    capacity = data.get("coop_capacity_hens")
    if not is_int(capacity) or capacity < 0:
        fail("ERR_INVALID_REQUEST", "coop_capacity_hens is required and must be an integer >= 0")
    rec = stamp_new({
        "id": new_id(),
        "household_id": household_id,
        "site_label": site_label,
        "coop_capacity_hens": capacity,
        "predator_grade": "NONE",
        "status": "PLANNED",
    })
    store.coops[rec["id"]] = rec
    return ok(serialize(rec), 201)


@bp.route("/coopcare/coop-sites", methods=["GET"])
def list_coops():
    uid, role = authenticate()
    require_role(role, set(ALL_ROLES))
    filters = []
    for key in ("household_id", "status"):
        v = request.args.get(key)
        if v is not None:
            filters.append((key, v))
    return list_response(store.coops.values(), filters)


@bp.route("/coopcare/coop-sites/<cid>", methods=["GET"])
def read_coop(cid):
    uid, role = authenticate()
    require_role(role, set(ALL_ROLES))
    return ok(serialize(get_coop(cid)), 200)
