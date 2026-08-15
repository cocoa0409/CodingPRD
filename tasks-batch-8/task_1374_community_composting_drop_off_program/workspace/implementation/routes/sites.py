"""Site endpoints."""

from flask import Blueprint

import db
import errors
from middleware import require_roles, ALL_ROLES
from response import success_object, success_list
from routes.helpers import (
    body, require_fields, require_str, require_int, get_program_or_404,
    get_site_or_404, paginate, parse_bool_param, sort_created,
)
from services import posture as posture_svc
from services.programs import touch, site_posture_touch
from services.serializers import site as serialize_site

bp = Blueprint("sites", __name__)

READ_ROLES = ALL_ROLES


@bp.route("/programs/<program_id>/sites", methods=["POST"])
def create_site(program_id):
    require_roles("ProgramAdmin")
    program = get_program_or_404(program_id)
    data = body()
    require_fields(data, "name", "address", "capacity_kg")
    name = require_str(data, "name")
    address = require_str(data, "address")
    capacity = require_int(data, "capacity_kg")

    now = db.iso_now()
    site = {
        "id": db.new_id(),
        "program_id": program["id"],
        "name": name,
        "address": address,
        "capacity_kg": capacity,
        "stored_kg": 0.0,
        "pending_pickup_kg": 0.0,
        "posture": "CLOSED",
        "host_agreement_id": None,
        "archived": False,
        "status": "ONBOARDING",
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.sites[site["id"]] = site
    return success_object(serialize_site(site), status=201)


@bp.route("/programs/<program_id>/sites", methods=["GET"])
def list_sites(program_id):
    require_roles(*READ_ROLES)
    get_program_or_404(program_id)
    include_archived = parse_bool_param("include_archived") or False
    status_filter = None
    from flask import request
    if request.args.get("status"):
        status_filter = request.args["status"]
        if status_filter not in ("ONBOARDING", "OPERATIONAL", "DECOMMISSIONED"):
            errors.raise_err(errors.ERR_INVALID_REQUEST, "Invalid status filter")
    items = [s for s in db.sites.values() if s["program_id"] == program_id]
    if not include_archived:
        items = [s for s in items if not s["archived"]]
    if status_filter:
        items = [s for s in items if s["status"] == status_filter]
    items = sort_created(items)
    page, limit, offset, total = paginate(items)
    return success_list([serialize_site(s) for s in page], limit, offset, total)


@bp.route("/programs/<program_id>/sites/<site_id>", methods=["GET"])
def get_site(program_id, site_id):
    require_roles(*READ_ROLES)
    get_program_or_404(program_id)
    site = get_site_or_404(site_id, program_id)
    return success_object(serialize_site(site))


@bp.route("/programs/<program_id>/sites/<site_id>/commission", methods=["POST"])
def commission_site(program_id, site_id):
    require_roles("ProgramAdmin")
    program = get_program_or_404(program_id)
    site = get_site_or_404(site_id, program_id)
    if site["status"] != "ONBOARDING":
        errors.raise_err(errors.ERR_INVALID_STATE, "Site must be ONBOARDING to commission")
    has_active_agreement = any(
        a["site_id"] == site["id"] and a["status"] == "ACTIVE"
        for a in db.host_agreements.values()
    )
    if not has_active_agreement:
        errors.raise_err(
            errors.ERR_SITE_NO_ACTIVE_AGREEMENT,
            "Site commission requires an ACTIVE SiteHostAgreement covering the site",
        )
    # NOTE: the scaffold lists "Program is ACTIVE" as a commission precondition,
    # but program activation itself requires an OPERATIONAL site (circular).
    # The only satisfiable bootstrap order is commission-then-activate, so the
    # program-state check is omitted; posture derives CLOSED until the program
    # is ACTIVE per the site_posture hard-override tier.
    site["status"] = "OPERATIONAL"
    posture_svc.recompute_site_posture(site)
    touch(site)
    return success_object(serialize_site(site))


@bp.route("/programs/<program_id>/sites/<site_id>/decommission", methods=["POST"])
def decommission_site(program_id, site_id):
    require_roles("ProgramAdmin")
    get_program_or_404(program_id)
    site = get_site_or_404(site_id, program_id)
    if site["status"] != "OPERATIONAL":
        errors.raise_err(errors.ERR_INVALID_STATE, "Site must be OPERATIONAL to decommission")
    if float(site["stored_kg"]) != 0:
        errors.raise_err(errors.ERR_SITE_NOT_EMPTY, "Decommission requires stored_kg == 0")
    has_scheduled = any(
        s["site_id"] == site["id"] and s["status"] == "SCHEDULED"
        for s in db.stops.values()
    )
    if has_scheduled:
        errors.raise_err(
            errors.ERR_SITE_HAS_SCHEDULED_PICKUPS,
            "Decommission blocked by SCHEDULED RouteStops",
        )
    has_grants = any(
        g["site_id"] == site["id"] and g["status"] == "ACTIVE"
        for g in db.grants.values()
    )
    if has_grants:
        errors.raise_err(
            errors.ERR_SITE_HAS_ACTIVE_GRANTS,
            "Decommission blocked by ACTIVE AccessGrants",
        )
    # Terminate the site's ACTIVE agreement if linked
    if site.get("host_agreement_id"):
        agreement = db.host_agreements.get(site["host_agreement_id"])
        if agreement and agreement["status"] == "ACTIVE":
            agreement["status"] = "TERMINATED"
            touch(agreement)
        site["host_agreement_id"] = None
    site["status"] = "DECOMMISSIONED"
    site["posture"] = "CLOSED"
    touch(site)
    return success_object(serialize_site(site))


@bp.route("/programs/<program_id>/sites/<site_id>/archive", methods=["POST"])
def archive_site(program_id, site_id):
    require_roles("ProgramAdmin")
    get_program_or_404(program_id)
    site = get_site_or_404(site_id, program_id)
    if site["status"] != "DECOMMISSIONED":
        errors.raise_err(errors.ERR_INVALID_STATE, "Site must be DECOMMISSIONED to archive")
    site["archived"] = True
    touch(site)
    return success_object(serialize_site(site))


# --- Flat aliases ---

@bp.route("/sites", methods=["GET"])
def list_sites_flat():
    require_roles(*READ_ROLES)
    from flask import request
    items = list(db.sites.values())
    if request.args.get("program_id"):
        items = [s for s in items if s["program_id"] == request.args["program_id"]]
    if request.args.get("host_agreement_id"):
        items = [s for s in items if s.get("host_agreement_id") == request.args["host_agreement_id"]]
    if request.args.get("status"):
        items = [s for s in items if s["status"] == request.args["status"]]
    include_archived = parse_bool_param("include_archived") or False
    if not include_archived:
        items = [s for s in items if not s["archived"]]
    items = sort_created(items)
    page, limit, offset, total = paginate(items)
    return success_list([serialize_site(s) for s in page], limit, offset, total)


@bp.route("/sites/<site_id>", methods=["GET"])
def get_site_flat(site_id):
    require_roles(*READ_ROLES)
    site = get_site_or_404(site_id)
    return success_object(serialize_site(site))
