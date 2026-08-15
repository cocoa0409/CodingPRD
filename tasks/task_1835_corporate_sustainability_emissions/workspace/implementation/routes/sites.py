"""Sites (PRD 3.1)."""
from flask import Blueprint

import domain
from envelope import ok
from errors import invalid_state, not_found
from http_util import MANAGER, READ_ROLES, get_body, require_roles, v_str
from store import db, new_entity, touch

bp = Blueprint("sites", __name__, url_prefix="/sustainability")


def load_site(site_id):
    site = db.sites.get(site_id)
    if site is None:
        raise not_found(f"Site {site_id} not found")
    return site


@bp.route("/sites", methods=["POST"])
@require_roles(MANAGER)
def create_site():
    body = get_body()
    name = v_str(body, "name")
    country_code = v_str(body, "country_code")
    grid_region_code = v_str(body, "grid_region_code")
    # Client-supplied system fields (id/created_at/version) are ignored.
    site = new_entity(
        {
            "name": name,
            "country_code": country_code,
            "grid_region_code": grid_region_code,
            "status": "ACTIVE",
        }
    )
    db.sites[site["id"]] = site
    return ok(domain.ser_site(site), status=201)


@bp.route("/sites/<site_id>", methods=["GET"])
@require_roles(*READ_ROLES)
def get_site(site_id):
    return ok(domain.ser_site(load_site(site_id)))


@bp.route("/sites/<site_id>/decommission", methods=["POST"])
@require_roles(MANAGER)
def decommission_site(site_id):
    site = load_site(site_id)
    if site["status"] != "ACTIVE":
        raise invalid_state(
            f"Site in status {site['status']} cannot be decommissioned"
        )
    site["status"] = "DECOMMISSIONED"
    touch(site)
    return ok(domain.ser_site(site))
