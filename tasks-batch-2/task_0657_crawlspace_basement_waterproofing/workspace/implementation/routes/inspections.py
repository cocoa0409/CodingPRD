"""Inspection endpoints (PRD §3.2)."""
from flask import Blueprint, request

import db
import errors
import helpers
from middleware import authenticate, authorize, get_json_body, get_pagination
from response import object_response, array_response
from serializers import serialize, serialize_list
from services import calculations, factory

bp = Blueprint("inspections", __name__)


@bp.route("/jobs/<job_id>/inspections", methods=["POST"])
def create_inspection(job_id):
    _uid, role = authenticate()
    authorize(role, ["Inspector"])
    job = helpers.find_or_404(db.jobs, job_id)
    body = get_json_body()
    moisture_pct = helpers.require_number(body, "moisture_pct")
    structural_findings_count = helpers.require_int(body, "structural_findings_count")
    standing_water = helpers.optional_bool(body, "standing_water", False)

    # field constraints (PRD §3.2): moisture 0..100, structural >= 0.
    if moisture_pct < 0 or moisture_pct > 100:
        raise errors.err(errors.ERR_VALIDATION, "moisture_pct must be between 0 and 100")
    if structural_findings_count < 0:
        raise errors.err(errors.ERR_VALIDATION, "structural_findings_count must be at least 0")

    entity = factory.create_inspection(job_id, moisture_pct, structural_findings_count, standing_water)
    return object_response(serialize(entity), status=201)


@bp.route("/inspections/<inspection_id>", methods=["GET"])
def get_inspection(inspection_id):
    _uid, role = authenticate()
    authorize(role, ["Inspector", "Estimator", "Homeowner"])
    entity = helpers.find_or_404(db.inspections, inspection_id)
    return object_response(serialize(entity), status=200)


@bp.route("/inspections", methods=["GET"])
def list_inspections():
    _uid, role = authenticate()
    authorize(role, ["Inspector", "Estimator", "Homeowner"])
    limit, offset = get_pagination()
    job_id = request.args.get("job_id")
    status = request.args.get("status")

    def pred(i):
        if job_id is not None and i["job_id"] != job_id:
            return False
        if status is not None and i["status"] != status:
            return False
        return True

    page, total = helpers.paginate_list(db.inspections, limit, offset, pred)
    return array_response(serialize_list(page), limit, offset, total)


@bp.route("/jobs/<job_id>/inspections/<inspection_id>/finalize", methods=["POST"])
def finalize_inspection(job_id, inspection_id):
    _uid, role = authenticate()
    authorize(role, ["Inspector"])
    # Path existence resolved left-to-right (PRD §2.6): job before inspection.
    job = helpers.find_or_404(db.jobs, job_id)
    inspection = helpers.find_or_404(db.inspections, inspection_id)

    # state: must be DRAFT (PRD §3.2).
    if inspection["status"] != "DRAFT":
        raise errors.err(errors.ERR_INVALID_STATE, "Only a DRAFT inspection can be finalized")

    # compute severity
    severity = calculations.compute_severity(
        inspection["moisture_pct"], inspection["structural_findings_count"], inspection["standing_water"]
    )
    inspection["severity"] = severity
    inspection["status"] = "FINALIZED"
    helpers.touch(inspection)

    # supersede any prior FINALIZED inspection on the same job.
    for other in db.inspections.items.values():
        if (other["id"] != inspection_id and other["job_id"] == job_id
                and other["status"] == "FINALIZED"):
            other["status"] = "SUPERSEDED"
            helpers.touch(other)

    # Job.assessment_severity := this severity; first finalize advances LEAD -> INSPECTED.
    job["assessment_severity"] = severity
    if job["lifecycle_status"] == "LEAD":
        job["lifecycle_status"] = "INSPECTED"
    helpers.touch(job)

    return object_response(serialize(inspection), status=200)
