"""ManufactureOrder endpoints (PRD §3.5)."""
from datetime import timedelta

from flask import Blueprint

import errors
import response
from db import db
from middleware import require_roles
from services import common, serialize, calculations
from services.quote_builder import build_quote
from services.permit_expiry import evaluate_expiry

bp = Blueprint("manufacture", __name__)


def _build_authorizing_permit(project_id):
    """The project's permit that authorizes the build.

    Returns the APPROVED permit, or one already lazily flipped to EXPIRED that
    still carries an expires_at (so the expiry gate can still reject the build).
    """
    candidate = None
    for p in db.permit_applications.values():
        if p["project_id"] != project_id:
            continue
        if p["status"] == "APPROVED":
            return p
        if p["status"] == "EXPIRED" and p.get("expires_at") is not None:
            candidate = p
    return candidate


@bp.route("/manufacture-orders", methods=["POST"])
def create_manufacture():
    require_roles({"Manufacturer"})
    body = common.get_json()

    project_id = common.require_field(body, "project_id", expected_types=["string"])
    quote_id = common.require_field(body, "quote_id", expected_types=["string"])

    # existence left-to-right: project then quote (priority 4)
    project = common.get_project(project_id)
    common.get_quote(quote_id)

    # state (priority 5)
    if project["status"] != "APPROVED_TO_BUILD":
        raise errors.invalid_state("Project must be APPROVED_TO_BUILD to manufacture.")

    # permit expiry gate (priority 14): clock_now >= expires_at -> ERR_PERMIT_EXPIRED
    # Evaluated against the recorded expiry deadline whether or not the permit was
    # already lazily flipped to EXPIRED on a prior read (PRD §3.5, §2.9).
    permit = _build_authorizing_permit(project_id)
    if permit is not None and permit.get("expires_at") is not None:
        if db.now() >= permit["expires_at"]:
            raise errors.ApiError(
                errors.ERR_PERMIT_EXPIRED, 409,
                "The approved permit has expired.")

    lead_time = calculations.manufacture_lead_time(
        project["material"], project["footprint_sqft"], project["structure_type"])
    promised = db.now() + timedelta(days=lead_time)

    entity = {
        "project_id": project_id,
        "quote_id": quote_id,
        "lead_time_days": lead_time,
        "promised_ready_at": promised,
        "ready_at": None,
        "status": "QUEUED",
    }
    common.stamp_create(entity)
    db.manufacture_orders[entity["id"]] = entity

    project["status"] = "IN_MANUFACTURE"
    common.touch(project)
    return response.success(serialize.manufacture(entity), status=201)


@bp.route("/manufacture-orders/<mid>/start", methods=["POST"])
def start_manufacture(mid):
    require_roles({"Manufacturer"})
    common.get_json()
    order = common.get_manufacture(mid)
    project = common.get_project(order["project_id"])

    # state (priority 5)
    if order["status"] != "QUEUED":
        raise errors.invalid_state("Manufacture order must be QUEUED to start.")

    order["status"] = "IN_PRODUCTION"
    common.touch(order)

    # dual-variant reconciliation: create FINAL quote recomputed against current
    # accepted measurement; supersede prior ACCEPTED quote; repoint accepted_quote_id.
    # The FINAL quote becomes the project's accepted (binding) quote (PRD §3.5).
    final_quote = build_quote(project, variant="FINAL", status="ACCEPTED")
    prior_accepted_id = project.get("accepted_quote_id")
    if prior_accepted_id is not None:
        prior = db.quotes.get(prior_accepted_id)
        if prior is not None and prior["status"] == "ACCEPTED":
            prior["status"] = "SUPERSEDED"
            common.touch(prior)
    project["accepted_quote_id"] = final_quote["id"]
    common.touch(project)
    return response.success(serialize.manufacture(order), status=200)


@bp.route("/manufacture-orders/<mid>/ready", methods=["POST"])
def ready_manufacture(mid):
    require_roles({"Manufacturer"})
    common.get_json()
    order = common.get_manufacture(mid)

    # state (priority 5)
    if order["status"] != "IN_PRODUCTION":
        raise errors.invalid_state("Manufacture order must be IN_PRODUCTION to mark ready.")

    order["ready_at"] = db.now()
    order["status"] = "READY"
    common.touch(order)
    return response.success(serialize.manufacture(order), status=200)
