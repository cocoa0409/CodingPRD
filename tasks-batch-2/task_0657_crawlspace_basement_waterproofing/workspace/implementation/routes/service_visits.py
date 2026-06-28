"""ServiceVisit endpoints (PRD §3.10)."""
from flask import Blueprint, request

import db
import errors
import helpers
from middleware import authenticate, authorize, get_json_body, get_pagination
from response import object_response, array_response
from serializers import serialize, serialize_list
from services import factory, derived

bp = Blueprint("service_visits", __name__)

VISIT_TYPES = ["ANNUAL", "CLAIM_REPAIR"]
MIN_VISIT_GAP_DAYS = 7


@bp.route("/warranties/<warranty_id>/service-visits", methods=["POST"])
def schedule_visit(warranty_id):
    _uid, role = authenticate()
    authorize(role, ["WarrantyAdmin"])
    warranty = helpers.find_or_404(db.warranties, warranty_id)
    body = get_json_body()
    visit_type = helpers.require_enum(body, "visit_type", VISIT_TYPES)
    scheduled_for = helpers.require_datetime(body, "scheduled_for")
    claim_id = body.get("claim_id")

    # If a claim_id is supplied it must reference an existing Claim (body FK, priority 4).
    if claim_id is not None:
        helpers.fk_or_422(db.claims, claim_id, "Claim")

    # business rule (priority 17): CLAIM_REPAIR requires IN_PROGRESS claim_id; ANNUAL requires none.
    if visit_type == "CLAIM_REPAIR":
        if claim_id is None:
            raise errors.err(errors.ERR_VISIT_CLAIM_MISMATCH, "CLAIM_REPAIR requires a claim_id")
        claim = db.claims.items.get(claim_id)
        if claim["status"] != "IN_PROGRESS":
            raise errors.err(errors.ERR_VISIT_CLAIM_MISMATCH, "CLAIM_REPAIR requires an IN_PROGRESS claim")
    else:  # ANNUAL
        if claim_id is not None:
            raise errors.err(errors.ERR_VISIT_CLAIM_MISMATCH, "ANNUAL visit must not carry a claim_id")

    # business rule (priority 19): min 7-day gap from every other SCHEDULED visit on the warranty.
    for v in db.service_visits.items.values():
        if v["warranty_id"] != warranty_id or v["status"] != "SCHEDULED":
            continue
        other = helpers.parse_iso(v["scheduled_for"])
        delta_days = abs((scheduled_for - other).total_seconds()) / 86400.0
        if delta_days < MIN_VISIT_GAP_DAYS:
            raise errors.err(errors.ERR_VISIT_TOO_CLOSE, "Visit within 7 days of another SCHEDULED visit")

    entity = factory.create_service_visit(
        warranty_id, visit_type, claim_id if visit_type == "CLAIM_REPAIR" else None,
        helpers.iso_from_dt(scheduled_for),
    )
    return object_response(serialize(entity), status=201)


@bp.route("/service-visits/<visit_id>", methods=["GET"])
def get_visit(visit_id):
    _uid, role = authenticate()
    authorize(role, ["WarrantyAdmin", "Homeowner"])
    entity = helpers.find_or_404(db.service_visits, visit_id)
    return object_response(serialize(entity), status=200)


@bp.route("/service-visits", methods=["GET"])
def list_visits():
    _uid, role = authenticate()
    authorize(role, ["WarrantyAdmin", "Homeowner"])
    limit, offset = get_pagination()
    warranty_id = request.args.get("warranty_id")
    status = request.args.get("status")
    visit_type = request.args.get("visit_type")

    def pred(v):
        if warranty_id is not None and v["warranty_id"] != warranty_id:
            return False
        if status is not None and v["status"] != status:
            return False
        if visit_type is not None and v["visit_type"] != visit_type:
            return False
        return True

    page, total = helpers.paginate_list(db.service_visits, limit, offset, pred)
    return array_response(serialize_list(page), limit, offset, total)


@bp.route("/service-visits/<visit_id>/complete", methods=["POST"])
def complete_visit(visit_id):
    _uid, role = authenticate()
    authorize(role, ["WarrantyAdmin"])
    visit = helpers.find_or_404(db.service_visits, visit_id)
    warranty = db.warranties.items.get(visit["warranty_id"])
    # state: visit SCHEDULED and warranty ACTIVE (PRD §3.10).
    if visit["status"] != "SCHEDULED":
        raise errors.err(errors.ERR_INVALID_STATE, "Only a SCHEDULED visit can be completed")
    if warranty is None or warranty["status"] != "ACTIVE":
        raise errors.err(errors.ERR_INVALID_STATE, "Completion requires an ACTIVE warranty")

    visit["status"] = "COMPLETED"
    helpers.touch(visit)

    if visit["visit_type"] == "ANNUAL":
        completion = db.now_iso()
        warranty["last_service_at"] = completion
        warranty["next_service_due"] = helpers.iso_from_dt(helpers.add_years(helpers.parse_iso(completion), 1))
        helpers.touch(warranty)
    else:  # CLAIM_REPAIR -> resolve the referenced claim if IN_PROGRESS
        claim = db.claims.items.get(visit["claim_id"])
        if claim is not None and claim["status"] == "IN_PROGRESS":
            claim["status"] = "RESOLVED"
            helpers.touch(claim)
            job = db.jobs.items.get(claim["job_id"])
            if job is not None:
                derived.recompute_open_claim_count(job)
                helpers.touch(job)
    return object_response(serialize(visit), status=200)


@bp.route("/service-visits/<visit_id>/cancel", methods=["POST"])
def cancel_visit(visit_id):
    _uid, role = authenticate()
    authorize(role, ["WarrantyAdmin"])
    visit = helpers.find_or_404(db.service_visits, visit_id)
    if visit["status"] != "SCHEDULED":
        raise errors.err(errors.ERR_INVALID_STATE, "Only a SCHEDULED visit can be cancelled")
    visit["status"] = "CANCELLED"
    helpers.touch(visit)
    return object_response(serialize(visit), status=200)
