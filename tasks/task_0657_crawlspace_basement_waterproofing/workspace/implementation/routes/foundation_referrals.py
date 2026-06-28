"""FoundationReferral endpoints (PRD §3.3)."""
from flask import Blueprint, request

import db
import errors
import helpers
from middleware import authenticate, authorize, get_json_body, get_pagination
from response import object_response, array_response
from serializers import serialize, serialize_list
from services import factory

bp = Blueprint("foundation_referrals", __name__)

OUTCOMES = ["ACCEPT", "REJECT"]


@bp.route("/jobs/<job_id>/foundation-referrals", methods=["POST"])
def draft_referral(job_id):
    _uid, role = authenticate()
    authorize(role, ["Inspector"])
    job = helpers.find_or_404(db.jobs, job_id)
    body = get_json_body()
    # body FK check (priority 4): inspection_id.
    helpers.require_fields(body, ["inspection_id"])
    helpers.fk_or_422(db.inspections, body["inspection_id"], "Inspection")
    partner_name = helpers.require_string(body, "partner_name")

    entity = factory.create_foundation_referral(job_id, body["inspection_id"], partner_name)
    return object_response(serialize(entity), status=201)


@bp.route("/foundation-referrals/<referral_id>", methods=["GET"])
def get_referral(referral_id):
    _uid, role = authenticate()
    authorize(role, ["Inspector", "Estimator"])
    entity = helpers.find_or_404(db.foundation_referrals, referral_id)
    return object_response(serialize(entity), status=200)


@bp.route("/foundation-referrals", methods=["GET"])
def list_referrals():
    _uid, role = authenticate()
    authorize(role, ["Inspector", "Estimator"])
    limit, offset = get_pagination()
    job_id = request.args.get("job_id")
    inspection_id = request.args.get("inspection_id")
    status = request.args.get("status")

    def pred(r):
        if job_id is not None and r["job_id"] != job_id:
            return False
        if inspection_id is not None and r["inspection_id"] != inspection_id:
            return False
        if status is not None and r["status"] != status:
            return False
        return True

    page, total = helpers.paginate_list(db.foundation_referrals, limit, offset, pred)
    return array_response(serialize_list(page), limit, offset, total)


@bp.route("/foundation-referrals/<referral_id>/send", methods=["POST"])
def send_referral(referral_id):
    _uid, role = authenticate()
    authorize(role, ["Inspector"])
    referral = helpers.find_or_404(db.foundation_referrals, referral_id)
    # state: DRAFT (PRD §3.3).
    if referral["status"] != "DRAFT":
        raise errors.err(errors.ERR_INVALID_STATE, "Only a DRAFT referral can be sent")
    # business rule (priority 10): inspection FINALIZED with severity SEVERE.
    inspection = db.inspections.items.get(referral["inspection_id"])
    if inspection is None or inspection["status"] != "FINALIZED" or inspection["severity"] != "SEVERE":
        raise errors.err(errors.ERR_REFERRAL_NOT_ELIGIBLE, "Referral requires a FINALIZED SEVERE inspection")
    referral["status"] = "SENT"
    helpers.touch(referral)
    return object_response(serialize(referral), status=200)


@bp.route("/foundation-referrals/<referral_id>/resolve", methods=["POST"])
def resolve_referral(referral_id):
    _uid, role = authenticate()
    authorize(role, ["Inspector"])
    referral = helpers.find_or_404(db.foundation_referrals, referral_id)
    body = get_json_body()
    outcome = helpers.require_enum(body, "outcome", OUTCOMES)
    # state: SENT (PRD §3.3).
    if referral["status"] != "SENT":
        raise errors.err(errors.ERR_INVALID_STATE, "Only a SENT referral can be resolved")
    referral["status"] = "ACCEPTED" if outcome == "ACCEPT" else "REJECTED"
    helpers.touch(referral)
    return object_response(serialize(referral), status=200)
