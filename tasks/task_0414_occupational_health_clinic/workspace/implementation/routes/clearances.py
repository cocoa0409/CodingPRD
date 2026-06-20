"""Clearance endpoints (PRD §3.8)."""

from flask import Blueprint, request

import errors
from db import LOCK, db
from errors import err
from middleware import authenticate, require_role
from response import object_response
from routes._helpers import get_json_body, paginated, sort_by_created
from services import lookup
from services.common import base_entity, touch
from services.encounter_ops import revert_worker_if_set_from
from services.serialize import public

bp = Blueprint("clearances", __name__)

READ_ROLES = {"ClinicAdmin", "Clinician", "Collector", "MRO"}
DETERMINATIONS = {"FIT", "FIT_WITH_RESTRICTIONS", "NOT_FIT"}


@bp.route("/clinic/clearances", methods=["POST"])
def create_clearance():
    caller = authenticate()
    require_role(caller, {"Clinician"})
    body = get_json_body()

    with LOCK:
        # Priority 4: body FK existence (missing OR not-found -> cross-employer).
        encounter_id = body.get("encounter_id")
        enc = db.encounters.get(encounter_id) if encounter_id is not None else None
        if enc is None:
            raise err(errors.ERR_CROSS_EMPLOYER_REFERENCE, "encounter missing or not found")

        # Priority 5: body well-formedness.
        determination = body.get("determination")
        if determination not in DETERMINATIONS:
            raise err(errors.ERR_INVALID_REQUEST, "invalid determination")
        restriction_text = body.get("restriction_text")
        if determination == "FIT_WITH_RESTRICTIONS":
            if not isinstance(restriction_text, str) or not restriction_text.strip():
                raise err(errors.ERR_INVALID_REQUEST,
                          "restriction_text is required for FIT_WITH_RESTRICTIONS")

        cl = base_entity()
        cl.update({
            "encounter_id": encounter_id,
            "employer_id": enc["employer_id"],
            "worker_id": enc["worker_id"],
            "determination": determination,
            "restriction_text": restriction_text,
            "status": "ISSUED",
        })
        db.clearances[cl["id"]] = cl
        return object_response(public(cl), 201)


@bp.route("/clinic/clearances", methods=["GET"])
def list_clearances():
    caller = authenticate()
    require_role(caller, READ_ROLES)
    args = request.args
    items = list(db.clearances.values())
    for key in ("encounter_id", "employer_id", "worker_id"):
        val = args.get(key)
        if val is not None:
            items = [c for c in items if c.get(key) == val]
    return paginated(sort_by_created(items))


@bp.route("/clinic/clearances/<clearance_id>", methods=["GET"])
def get_clearance(clearance_id):
    caller = authenticate()
    require_role(caller, READ_ROLES)
    cl = lookup.get_clearance(clearance_id)
    return object_response(public(cl), 200)


@bp.route("/clinic/clearances/<clearance_id>/rescind", methods=["POST"])
def rescind(clearance_id):
    caller = authenticate()
    require_role(caller, {"Clinician"})
    with LOCK:
        cl = lookup.get_clearance(clearance_id)
        if cl["status"] != "ISSUED":
            raise err(errors.ERR_CLEARANCE_NOT_ISSUED, "Clearance must be ISSUED to rescind")
        enc = db.encounters.get(cl["encounter_id"])
        if enc is not None and enc["status"] == "COMPLETED":
            raise err(errors.ERR_ENCOUNTER_LOCKED,
                      "Parent encounter is COMPLETED; rescind via void only")
        cl["status"] = "RESCINDED"
        touch(cl)
        worker = db.workers.get(cl["worker_id"])
        revert_worker_if_set_from(worker, cl["id"])
        return object_response(public(cl), 200)
