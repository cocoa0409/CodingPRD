"""Claim endpoints (PRD §3.11)."""
from flask import Blueprint, request

import db
import errors
import helpers
from middleware import authenticate, authorize, get_json_body, get_pagination
from response import object_response, array_response
from serializers import serialize, serialize_list
from services import factory, derived

bp = Blueprint("claims", __name__)

CATEGORIES = ["WATER_INTRUSION", "PUMP_FAILURE", "STRUCTURAL"]
# STRUCTURAL is explicitly NOT covered (PRD §3.11).
COVERED_CATEGORIES = {"WATER_INTRUSION", "PUMP_FAILURE"}


@bp.route("/claims", methods=["POST"])
def file_claim():
    _uid, role = authenticate()
    authorize(role, ["Homeowner", "WarrantyAdmin"])
    body = get_json_body()
    # body FK check (priority 4): job_id, warranty_id.
    helpers.require_fields(body, ["job_id", "warranty_id"])
    job = helpers.fk_or_422(db.jobs, body["job_id"], "Job")
    helpers.fk_or_422(db.warranties, body["warranty_id"], "Warranty")
    # request validity (priority 5): category enum, description present.
    category = helpers.require_enum(body, "category", CATEGORIES)
    description = helpers.require_string(body, "description")

    claim = factory.create_claim(body["job_id"], body["warranty_id"], category, description)
    derived.recompute_open_claim_count(job)
    helpers.touch(job)
    return object_response(serialize(claim), status=201)


@bp.route("/claims/<claim_id>", methods=["GET"])
def get_claim(claim_id):
    _uid, role = authenticate()
    authorize(role, ["Homeowner", "WarrantyAdmin"])
    entity = helpers.find_or_404(db.claims, claim_id)
    return object_response(serialize(entity), status=200)


@bp.route("/claims", methods=["GET"])
def list_claims():
    _uid, role = authenticate()
    authorize(role, ["Homeowner", "WarrantyAdmin"])
    limit, offset = get_pagination()
    job_id = request.args.get("job_id")
    warranty_id = request.args.get("warranty_id")
    status = request.args.get("status")

    def pred(c):
        if job_id is not None and c["job_id"] != job_id:
            return False
        if warranty_id is not None and c["warranty_id"] != warranty_id:
            return False
        if status is not None and c["status"] != status:
            return False
        return True

    page, total = helpers.paginate_list(db.claims, limit, offset, pred)
    return array_response(serialize_list(page), limit, offset, total)


@bp.route("/claims/<claim_id>/triage", methods=["POST"])
def triage_claim(claim_id):
    _uid, role = authenticate()
    authorize(role, ["WarrantyAdmin"])
    claim = helpers.find_or_404(db.claims, claim_id)
    body = get_json_body()
    accept = helpers.require_bool(body, "accept")

    job = db.jobs.items.get(claim["job_id"])
    warranty = db.warranties.items.get(claim["warranty_id"])

    if accept:
        # accept: OPEN or REOPENED -> IN_PROGRESS, requires warranty ACTIVE (PRD §3.11).
        if claim["status"] not in ("OPEN", "REOPENED"):
            raise errors.err(errors.ERR_INVALID_STATE, "Only an OPEN or REOPENED claim can be accepted")
        if warranty is None or warranty["status"] != "ACTIVE":
            raise errors.err(errors.ERR_INVALID_STATE, "Triage-accept requires an ACTIVE warranty")
        # business rule (priority 9): coverage. STRUCTURAL not covered.
        if claim["category"] not in COVERED_CATEGORIES:
            raise errors.err(errors.ERR_CLAIM_NOT_COVERED, "Claim category is not covered by the warranty")
        claim["status"] = "IN_PROGRESS"
        helpers.touch(claim)
    else:
        # deny: OPEN -> DENIED (PRD §3.11).
        if claim["status"] != "OPEN":
            raise errors.err(errors.ERR_INVALID_STATE, "Only an OPEN claim can be denied")
        claim["status"] = "DENIED"
        helpers.touch(claim)

    if job is not None:
        derived.recompute_open_claim_count(job)
        helpers.touch(job)
    return object_response(serialize(claim), status=200)


@bp.route("/claims/<claim_id>/reopen", methods=["POST"])
def reopen_claim(claim_id):
    _uid, role = authenticate()
    authorize(role, ["Homeowner"])
    claim = helpers.find_or_404(db.claims, claim_id)
    warranty = db.warranties.items.get(claim["warranty_id"])
    # state: RESOLVED and warranty ACTIVE (PRD §3.11).
    if claim["status"] != "RESOLVED":
        raise errors.err(errors.ERR_INVALID_STATE, "Only a RESOLVED claim can be reopened")
    if warranty is None or warranty["status"] != "ACTIVE":
        raise errors.err(errors.ERR_INVALID_STATE, "Reopen requires an ACTIVE warranty")
    claim["status"] = "REOPENED"
    claim["reopen_count"] += 1
    helpers.touch(claim)
    job = db.jobs.items.get(claim["job_id"])
    if job is not None:
        derived.recompute_open_claim_count(job)
        helpers.touch(job)
    return object_response(serialize(claim), status=200)
