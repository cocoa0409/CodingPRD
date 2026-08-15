"""Sites (PRD §3.1)."""

from flask import Blueprint, request

from db import store
from errors import conflict, ERR_INVALID_STATE_TRANSITION
from middleware import require_roles, ALL_ROLES, ROLE_INTEGRATOR_ADMIN
from response import success_object, paginate
from services.core import (
    new_record, touch, ser_site, reconcile_site_capacity, GROUP_ACTIVE_STATUSES,
)
from util import get_body, req, as_str, load_or_404

bp = Blueprint("sites", __name__)


@bp.route("/sites", methods=["POST"])
def create_site():
    require_roles([ROLE_INTEGRATOR_ADMIN])
    body = get_body()
    name = as_str(req(body, "name"), "name")
    state_code = as_str(req(body, "state_code"), "state_code")
    county = as_str(req(body, "county"), "county")
    rec = new_record()
    rec.update({
        "name": name, "state_code": state_code, "county": county,
        "site_status": "ACTIVE", "total_capacity_head": 0,
    })
    store.sites[rec["id"]] = rec
    return success_object(ser_site(rec), 201)


@bp.route("/sites", methods=["GET"])
def list_sites():
    require_roles(ALL_ROLES)
    status = request.args.get("site_status")
    items = list(store.sites.values())
    if status is not None:
        items = [s for s in items if s["site_status"] == status]
    return paginate(items, request.args, ser_site)


@bp.route("/sites/<sid>", methods=["GET"])
def get_site(sid):
    require_roles(ALL_ROLES)
    return success_object(ser_site(load_or_404(store.sites, sid, "Site")))


@bp.route("/sites/<sid>/suspend", methods=["POST"])
def suspend_site(sid):
    require_roles([ROLE_INTEGRATOR_ADMIN])
    site = load_or_404(store.sites, sid, "Site")
    if site["site_status"] != "ACTIVE":
        raise conflict(ERR_INVALID_STATE_TRANSITION,
                       f"Cannot suspend a site in {site['site_status']}")
    site["site_status"] = "SUSPENDED"
    touch(site)
    return success_object(ser_site(site))


@bp.route("/sites/<sid>/reinstate", methods=["POST"])
def reinstate_site(sid):
    require_roles([ROLE_INTEGRATOR_ADMIN])
    site = load_or_404(store.sites, sid, "Site")
    if site["site_status"] != "SUSPENDED":
        raise conflict(ERR_INVALID_STATE_TRANSITION,
                       f"Cannot reinstate a site in {site['site_status']}")
    site["site_status"] = "ACTIVE"
    touch(site)
    return success_object(ser_site(site))


@bp.route("/sites/<sid>/decommission", methods=["POST"])
def decommission_site(sid):
    require_roles([ROLE_INTEGRATOR_ADMIN])
    site = load_or_404(store.sites, sid, "Site")
    if site["site_status"] != "ACTIVE":
        raise conflict(ERR_INVALID_STATE_TRANSITION,
                       f"Cannot decommission a site in {site['site_status']}")
    # blocked while any contract covering the site is ACTIVE
    for c in store.contracts.values():
        if c["site_id"] == sid and c["contract_status"] == "ACTIVE":
            raise conflict(ERR_INVALID_STATE_TRANSITION,
                           "Site still has an ACTIVE contract")
    # blocked while any pig group on the site's barns is live
    barn_ids = {b["id"] for b in store.barns.values() if b["site_id"] == sid}
    for g in store.pig_groups.values():
        if g["barn_id"] in barn_ids and g["group_status"] in GROUP_ACTIVE_STATUSES:
            raise conflict(ERR_INVALID_STATE_TRANSITION,
                           "Site still has live pig groups")
    site["site_status"] = "DECOMMISSIONED"
    touch(site)
    return success_object(ser_site(site))
