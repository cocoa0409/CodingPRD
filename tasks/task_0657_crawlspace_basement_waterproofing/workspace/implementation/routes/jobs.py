"""Job endpoints (PRD §3.1, §3.5-§3.7, §3.9, §3.12)."""
from flask import Blueprint, request

import db
import errors
import helpers
from clock import clock
from middleware import authenticate, authorize, get_json_body, get_pagination
from response import object_response, array_response
from serializers import serialize, serialize_list
from services import factory

bp = Blueprint("jobs", __name__)

STRUCTURE_TYPES = ["CRAWLSPACE", "BASEMENT", "COMBINED"]


@bp.route("/jobs", methods=["POST"])
def create_job():
    _uid, role = authenticate()
    authorize(role, ["Estimator", "Homeowner"])
    body = get_json_body()
    # body FK check (priority 4) before request validity (priority 5): homeowner_id
    helpers.require_fields(body, ["homeowner_id"])
    homeowner_id = body["homeowner_id"]
    helpers.fk_or_422(db.homeowners, homeowner_id, "Homeowner")

    property_address = helpers.require_string(body, "property_address")
    structure_type = helpers.require_enum(body, "structure_type", STRUCTURE_TYPES)
    footprint_sqft = helpers.require_int(body, "footprint_sqft")
    # footprint_sqft >= 1 (PRD §3.1) -> ERR_VALIDATION (business rule).
    if footprint_sqft < 1:
        raise errors.err(errors.ERR_VALIDATION, "footprint_sqft must be at least 1")

    entity = factory.create_job(homeowner_id, property_address, structure_type, footprint_sqft)
    return object_response(serialize(entity), status=201)


@bp.route("/jobs/<job_id>", methods=["GET"])
def get_job(job_id):
    _uid, role = authenticate()
    authorize(role, ["Estimator", "Homeowner", "Scheduler", "WarrantyAdmin", "Inspector", "FinancePartner"])
    entity = helpers.find_or_404(db.jobs, job_id)
    return object_response(serialize(entity), status=200)


@bp.route("/jobs", methods=["GET"])
def list_jobs():
    _uid, role = authenticate()
    authorize(role, ["Estimator", "Scheduler", "WarrantyAdmin"])
    limit, offset = get_pagination()
    homeowner_id = request.args.get("homeowner_id")
    lifecycle_status = request.args.get("lifecycle_status")

    def pred(j):
        if homeowner_id is not None and j["homeowner_id"] != homeowner_id:
            return False
        if lifecycle_status is not None and j["lifecycle_status"] != lifecycle_status:
            return False
        return True

    page, total = helpers.paginate_list(db.jobs, limit, offset, pred)
    return array_response(serialize_list(page), limit, offset, total)


@bp.route("/jobs/<job_id>/mark-lost", methods=["POST"])
def mark_lost(job_id):
    _uid, role = authenticate()
    authorize(role, ["Estimator"])
    job = helpers.find_or_404(db.jobs, job_id)
    if job["lifecycle_status"] not in ("LEAD", "INSPECTED", "QUOTED"):
        raise errors.err(errors.ERR_INVALID_STATE, "Job cannot be marked lost from %s" % job["lifecycle_status"])
    # Decline every DRAFT/SENT quote on this job.
    for q in db.quotes.items.values():
        if q["job_id"] == job_id and q["status"] in ("DRAFT", "SENT"):
            q["status"] = "DECLINED"
            helpers.touch(q)
    job["lifecycle_status"] = "LOST"
    helpers.touch(job)
    return object_response(serialize(job), status=200)


@bp.route("/jobs/<job_id>/pay-cash", methods=["POST"])
def pay_cash(job_id):
    _uid, role = authenticate()
    authorize(role, ["Homeowner"])
    job = helpers.find_or_404(db.jobs, job_id)
    # Permitted only when Job is SOLD and financing_status is still NONE (PRD §3.6).
    if job["lifecycle_status"] != "SOLD" or job["financing_status"] != "NONE":
        raise errors.err(errors.ERR_INVALID_STATE, "pay-cash requires a SOLD job with financing_status NONE")
    job["financing_status"] = "CASH"
    helpers.touch(job)
    return object_response(serialize(job), status=200)


@bp.route("/jobs/<job_id>/install-orders", methods=["POST"])
def create_install_order(job_id):
    _uid, role = authenticate()
    authorize(role, ["Scheduler"])
    job = helpers.find_or_404(db.jobs, job_id)
    body = get_json_body()

    # request validity (priority 5)
    scheduled_start = helpers.require_datetime(body, "scheduled_start")
    scheduled_end = helpers.require_datetime(body, "scheduled_end")
    expected_job_version = helpers.require_int(body, "expected_job_version")

    # state legality (priority 6): Job must be SOLD.
    if job["lifecycle_status"] != "SOLD":
        raise errors.err(errors.ERR_INVALID_STATE, "Install order requires a SOLD job")

    # OCC (priority 7): expected_job_version must match.
    if expected_job_version != job["version"]:
        raise errors.err(errors.ERR_STALE_VERSION, "expected_job_version does not match the Job's current version")

    # business rule (priority 12): financing resolved (CASH or APPROVED).
    if job["financing_status"] not in ("CASH", "APPROVED"):
        raise errors.err(errors.ERR_FINANCING_UNRESOLVED, "Scheduling requires CASH or APPROVED financing")

    order = factory.create_install_order(
        job["id"], job["accepted_quote_id"],
        helpers.iso_from_dt(scheduled_start), helpers.iso_from_dt(scheduled_end),
    )
    job["install_order_id"] = order["id"]
    job["lifecycle_status"] = "SCHEDULED"
    helpers.touch(job)
    return object_response(serialize(order), status=201)


@bp.route("/jobs/<job_id>/warranty", methods=["POST"])
def issue_warranty(job_id):
    _uid, role = authenticate()
    authorize(role, ["WarrantyAdmin"])
    job = helpers.find_or_404(db.jobs, job_id)
    body = get_json_body()
    # coverage_years optional (default 25 — lifetime covenant).
    coverage_years = helpers.optional_int(body, "coverage_years", 25)

    # state: Job INSTALLED and its install order COMPLETED (PRD §3.9).
    if job["lifecycle_status"] != "INSTALLED":
        raise errors.err(errors.ERR_INVALID_STATE, "Warranty issuance requires an INSTALLED job")
    order = db.install_orders.items.get(job["install_order_id"])
    if order is None or order["status"] != "COMPLETED":
        raise errors.err(errors.ERR_INVALID_STATE, "Warranty issuance requires a COMPLETED install order")

    next_due = helpers.iso_from_dt(helpers.add_years(clock.now(), 1))
    warranty = factory.create_warranty(
        job["id"], order["id"], job["homeowner_id"], coverage_years, next_due
    )
    job["lifecycle_status"] = "WARRANTED"
    helpers.touch(job)
    return object_response(serialize(warranty), status=201)


@bp.route("/jobs/<job_id>/close", methods=["POST"])
def close_job(job_id):
    _uid, role = authenticate()
    authorize(role, ["WarrantyAdmin"])
    job = helpers.find_or_404(db.jobs, job_id)
    # state: WARRANTED (PRD §3.12).
    if job["lifecycle_status"] != "WARRANTED":
        raise errors.err(errors.ERR_INVALID_STATE, "Close requires a WARRANTED job")
    # business rule (priority 18): open_claim_count == 0.
    if job["open_claim_count"] != 0:
        raise errors.err(errors.ERR_OPEN_CLAIMS_BLOCK_CLOSE, "Cannot close a job with open claims")
    job["lifecycle_status"] = "CLOSED"
    helpers.touch(job)
    return object_response(serialize(job), status=200)
