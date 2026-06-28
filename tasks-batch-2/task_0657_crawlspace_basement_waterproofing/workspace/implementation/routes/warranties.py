"""Warranty endpoints (PRD §3.9)."""
from flask import Blueprint, request

import db
import errors
import helpers
from clock import clock
from middleware import authenticate, authorize, get_json_body, get_pagination
from response import object_response, array_response
from serializers import serialize, serialize_list

bp = Blueprint("warranties", __name__)

MAX_TRANSFERS = 3
SERVICE_GRACE_DAYS = 30


@bp.route("/warranties/<warranty_id>", methods=["GET"])
def get_warranty(warranty_id):
    _uid, role = authenticate()
    authorize(role, ["WarrantyAdmin", "Homeowner"])
    entity = helpers.find_or_404(db.warranties, warranty_id)
    return object_response(serialize(entity), status=200)


@bp.route("/warranties", methods=["GET"])
def list_warranties():
    _uid, role = authenticate()
    authorize(role, ["WarrantyAdmin", "Homeowner"])
    limit, offset = get_pagination()
    job_id = request.args.get("job_id")
    status = request.args.get("status")

    def pred(w):
        if job_id is not None and w["job_id"] != job_id:
            return False
        if status is not None and w["status"] != status:
            return False
        return True

    page, total = helpers.paginate_list(db.warranties, limit, offset, pred)
    return array_response(serialize_list(page), limit, offset, total)


@bp.route("/warranties/<warranty_id>/transfer", methods=["POST"])
def transfer_warranty(warranty_id):
    _uid, role = authenticate()
    authorize(role, ["WarrantyAdmin"])
    warranty = helpers.find_or_404(db.warranties, warranty_id)
    body = get_json_body()
    # body FK check (priority 4): new_holder_homeowner_id.
    helpers.require_fields(body, ["new_holder_homeowner_id"])
    helpers.fk_or_422(db.homeowners, body["new_holder_homeowner_id"], "Homeowner")
    expected_warranty_version = helpers.require_int(body, "expected_warranty_version")

    # state legality (priority 6): ACTIVE.
    if warranty["status"] != "ACTIVE":
        raise errors.err(errors.ERR_INVALID_STATE, "Only an ACTIVE warranty can be transferred")

    # OCC (priority 7).
    if expected_warranty_version != warranty["version"]:
        raise errors.err(errors.ERR_STALE_VERSION, "expected_warranty_version does not match the Warranty's current version")

    # business rule (priority 16): transfer_count < MAX_TRANSFERS.
    if warranty["transfer_count"] >= MAX_TRANSFERS:
        raise errors.err(errors.ERR_TRANSFER_LIMIT_REACHED, "Warranty has reached the transfer limit")

    # Settles back to ACTIVE within the same request (PRD §3.9).
    warranty["holder_homeowner_id"] = body["new_holder_homeowner_id"]
    warranty["transfer_count"] += 1
    warranty["status"] = "ACTIVE"
    helpers.touch(warranty)
    return object_response(serialize(warranty), status=200)


@bp.route("/warranties/<warranty_id>/void", methods=["POST"])
def void_warranty(warranty_id):
    _uid, role = authenticate()
    authorize(role, ["WarrantyAdmin"])
    warranty = helpers.find_or_404(db.warranties, warranty_id)
    if warranty["status"] != "ACTIVE":
        raise errors.err(errors.ERR_INVALID_STATE, "Only an ACTIVE warranty can be voided")
    warranty["status"] = "VOID"
    helpers.touch(warranty)
    # cascade: cancel SCHEDULED service visits on this warranty.
    for v in db.service_visits.items.values():
        if v["warranty_id"] == warranty_id and v["status"] == "SCHEDULED":
            v["status"] = "CANCELLED"
            helpers.touch(v)
    return object_response(serialize(warranty), status=200)


@bp.route("/warranties/<warranty_id>/lapse", methods=["POST"])
def lapse_warranty(warranty_id):
    _uid, role = authenticate()
    authorize(role, ["WarrantyAdmin"])
    warranty = helpers.find_or_404(db.warranties, warranty_id)
    # state: ACTIVE (PRD §3.9).
    if warranty["status"] != "ACTIVE":
        raise errors.err(errors.ERR_INVALID_STATE, "Only an ACTIVE warranty can be lapsed")
    # requires clock >= next_service_due + grace.
    threshold = helpers.add_days(helpers.parse_iso(warranty["next_service_due"]), SERVICE_GRACE_DAYS)
    if clock.now() < threshold:
        raise errors.err(errors.ERR_INVALID_STATE, "Warranty not yet overdue past grace")
    warranty["status"] = "LAPSED"
    helpers.touch(warranty)
    return object_response(serialize(warranty), status=200)
