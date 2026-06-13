"""Worker endpoints: register, fetch, list, suspend, reinstate, terminate."""
from flask import Blueprint, request

import db
import errors
from middleware import authenticate, require_role
from response import object_response, array_response
from services import domain, serialize, validate

bp = Blueprint("workers", __name__)


@bp.route("/workers", methods=["POST"])
def create_worker():
    _, role = authenticate()
    require_role(role, {"PayrollOfficer"})
    body = validate.get_body()
    employer_id = validate.require_str(body, "employer_id")
    employer = db.employers.get(employer_id)
    if employer is None:
        raise errors.not_found("Employer not found")
    external_ref = validate.require_str(body, "external_payroll_ref")
    full_name = validate.require_str(body, "full_name")
    rate = validate.require_int(body, "hourly_rate_cents", minimum=0)
    validate.require_datetime(body, "hire_date")
    hire_date = validate.require_str(body, "hire_date")

    # external_payroll_ref unique per employer among non-TERMINATED workers
    # (PRD §3.2, validation priority 18).
    for w in db.workers.values():
        if (w["employer_id"] == employer_id
                and w["external_payroll_ref"] == external_ref
                and w["employment_status"] != "TERMINATED"):
            raise errors.ApiError(errors.ERR_DUPLICATE_PAYROLL_REF, 409,
                                  "external_payroll_ref already in use")

    common = db.new_common_fields()
    worker = {
        **common,
        "employer_id": employer_id,
        "external_payroll_ref": external_ref,
        "full_name": full_name,
        "hourly_rate_cents": rate,
        "hire_date": hire_date,
        "employment_status": "ACTIVE",
        "advance_eligibility": "ELIGIBLE",
    }
    db.workers[worker["id"]] = worker
    return object_response(serialize.worker(worker), status=201)


@bp.route("/workers/<worker_id>", methods=["GET"])
def get_worker(worker_id):
    user_id, role = authenticate()
    require_role(role, {"PayrollOfficer", "ComplianceOfficer", "Worker"})
    worker = db.workers.get(worker_id)
    if worker is None:
        raise errors.not_found()
    # Worker self-service ownership (PRD §2.1): a Worker may only read its own profile.
    if role == "Worker" and worker_id != user_id:
        raise errors.unauthorized()
    return object_response(serialize.worker(worker))


@bp.route("/workers", methods=["GET"])
def list_workers():
    _, role = authenticate()
    require_role(role, {"PayrollOfficer", "ComplianceOfficer"})
    limit, offset = validate.pagination()
    emp_filter = request.args.get("employer_id")
    ref_filter = request.args.get("external_payroll_ref")
    items = []
    for w in db.workers.values():
        if emp_filter is not None and w["employer_id"] != emp_filter:
            continue
        if ref_filter is not None and w["external_payroll_ref"] != ref_filter:
            continue
        items.append(w)
    page, total = validate.paginate(items, limit, offset)
    return array_response([serialize.worker(w) for w in page], limit, offset, total)


def _transition(worker_id, valid_from, to_state):
    _, role = authenticate()
    require_role(role, {"PayrollOfficer"})
    worker = db.workers.get(worker_id)
    if worker is None:
        raise errors.not_found()
    if worker["employment_status"] not in valid_from:
        raise errors.invalid_state()
    return worker, role


@bp.route("/workers/<worker_id>/suspend", methods=["POST"])
def suspend_worker(worker_id):
    worker, _ = _transition(worker_id, {"ACTIVE"}, "SUSPENDED")
    worker["employment_status"] = "SUSPENDED"
    db.touch(worker)
    return object_response(serialize.worker(worker))


@bp.route("/workers/<worker_id>/reinstate", methods=["POST"])
def reinstate_worker(worker_id):
    worker, _ = _transition(worker_id, {"SUSPENDED"}, "ACTIVE")
    worker["employment_status"] = "ACTIVE"
    db.touch(worker)
    return object_response(serialize.worker(worker))


@bp.route("/workers/<worker_id>/terminate", methods=["POST"])
def terminate_worker(worker_id):
    worker, _ = _transition(worker_id, {"ACTIVE", "SUSPENDED"}, "TERMINATED")
    # Blocked while the worker has any advance in {DISBURSED, RECOUPING, DEFAULTED}
    # (PRD §3.2).
    for a in domain.worker_advances(worker_id):
        if a["status"] in ("DISBURSED", "RECOUPING", "DEFAULTED"):
            raise errors.ApiError(errors.ERR_WORKER_HAS_OPEN_ADVANCE, 409,
                                  "Worker has an open advance")
    worker["employment_status"] = "TERMINATED"
    db.touch(worker)
    return object_response(serialize.worker(worker))
