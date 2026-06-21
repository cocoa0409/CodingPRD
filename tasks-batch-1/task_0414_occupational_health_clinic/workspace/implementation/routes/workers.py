"""Worker endpoints (PRD §3.3)."""

from flask import Blueprint, request

import errors
from db import LOCK, db
from errors import err
from middleware import authenticate, require_role
from response import object_response
from routes._helpers import get_json_body, paginated, sort_by_created
from services import lookup
from services.common import base_entity, parse_date
from services.serialize import public

bp = Blueprint("workers", __name__)

READ_ROLES = {"ClinicAdmin", "Clinician", "Collector", "MRO"}


@bp.route("/clinic/workers", methods=["POST"])
def create_worker():
    caller = authenticate()
    require_role(caller, {"ClinicAdmin", "Clinician"})
    body = get_json_body()

    with LOCK:
        # Body FK existence (priority 4): missing OR not-found -> cross-employer.
        employer_id = body.get("employer_id")
        if employer_id is None or employer_id not in db.employers:
            raise err(errors.ERR_CROSS_EMPLOYER_REFERENCE,
                      "employer_id missing or not found")

        full_name = body.get("full_name")
        if not isinstance(full_name, str) or not full_name.strip():
            raise err(errors.ERR_INVALID_REQUEST, "full_name is required")

        job_category = body.get("job_category")
        if not isinstance(job_category, str) or not job_category.strip():
            raise err(errors.ERR_INVALID_REQUEST, "job_category is required")

        dob = body.get("dob")
        if dob is None or parse_date(dob) is None:
            raise err(errors.ERR_INVALID_REQUEST, "dob must be a valid date")

        worker = base_entity()
        worker.update({
            "employer_id": employer_id,
            "full_name": full_name,
            "job_category": job_category,
            "dob": dob,
            "hire_status": "CANDIDATE",
        })
        db.workers[worker["id"]] = worker
        return object_response(public(worker), 201)


@bp.route("/clinic/workers", methods=["GET"])
def list_workers():
    caller = authenticate()
    require_role(caller, READ_ROLES)
    employer_id = request.args.get("employer_id")
    job_category = request.args.get("job_category")
    items = list(db.workers.values())
    if employer_id is not None:
        items = [w for w in items if w["employer_id"] == employer_id]
    if job_category is not None:
        items = [w for w in items if w["job_category"] == job_category]
    return paginated(sort_by_created(items))


@bp.route("/clinic/workers/<worker_id>", methods=["GET"])
def get_worker(worker_id):
    caller = authenticate()
    require_role(caller, READ_ROLES)
    worker = lookup.get_worker(worker_id)
    return object_response(public(worker), 200)
