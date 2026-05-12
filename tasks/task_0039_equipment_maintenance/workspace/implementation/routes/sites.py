"""Site, clock advance, sweep tick routes."""
from datetime import datetime, timezone

from flask import Blueprint

from db import db, new_id, parse_iso, SITE_CLOCK_INIT
from errors import ERR_BAD_REQUEST, raise_err
from middleware import require_role
from response import success_object
from services.calculations import recompute_sla_breached
from services.common import get_json_body, get_site_or_404
from services.serialize import serialize_site
from services.work_order import run_plan_generation_periodic

bp = Blueprint("sites", __name__)


@bp.route("/sites", methods=["POST"])
def create_site():
    require_role(["SiteManager"])
    body = get_json_body()
    name = body.get("name")
    if not isinstance(name, str) or not name.strip():
        raise_err(ERR_BAD_REQUEST, "name is required")

    sid = new_id()
    init_clock = parse_iso(SITE_CLOCK_INIT)
    site = {
        "id": sid,
        "created_at": init_clock,
        "updated_at": init_clock,
        "version": 1,
        "name": name,
        "clock_now": init_clock,
        "sweep_run_index": 0,
    }
    db.sites[sid] = site
    return success_object(serialize_site(site), 201)


@bp.route("/sites/<site_id>", methods=["GET"])
def get_site(site_id):
    require_role(["Any"])
    site = get_site_or_404(site_id)
    return success_object(serialize_site(site))


@bp.route("/sites/<site_id>/clock/advance", methods=["POST"])
def advance_clock(site_id):
    require_role(["SiteManager", "Dispatcher"])
    site = get_site_or_404(site_id)
    body = get_json_body()
    seconds = body.get("seconds")
    if not isinstance(seconds, int) or isinstance(seconds, bool) or seconds <= 0:
        raise_err(ERR_BAD_REQUEST, "seconds must be a positive integer")
    db.advance_clock(site_id, seconds)
    return success_object(serialize_site(site))


@bp.route("/sites/<site_id>/sweep/run", methods=["POST"])
def sweep_run(site_id):
    require_role(["SiteManager", "Dispatcher"])
    site = get_site_or_404(site_id)
    site["sweep_run_index"] += 1

    # Step 1 & 2 plan generation
    run_plan_generation_periodic(site_id)

    # Recompute sla_breached on every open WorkOrder
    clock = db.site_clock(site_id)
    for w in db.work_orders_for_site(site_id):
        recompute_sla_breached(w, clock)

    return success_object(serialize_site(site))
