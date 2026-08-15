"""TimelineCommitment endpoints."""

from flask import Blueprint, request

import db
from errors import (
    ERR_COMMITMENT_NOT_REVISABLE,
    ERR_DATE_IN_PAST,
    ERR_FORBIDDEN_OWNER,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_STALE_VERSION,
    raise_error,
)
from middleware import (
    ANY_ROLE,
    check_app_mutable,
    get_body,
    paginate,
    parse_iso_date,
    require_enum,
    require_fields,
    require_roles,
)
from response import success_list, success_object
from services.domain import get_application, get_commitment, touch

bp = Blueprint("timeline_commitments", __name__)

ATTRIBUTIONS = ("UTILITY", "BUILDER", "MUNICIPALITY", "WEATHER")


def _owns(user_id, app):
    if app["builder_id"] != user_id:
        raise_error(ERR_FORBIDDEN_OWNER, "Builder does not own this application")


@bp.route("/timeline-commitments/<cid>", methods=["GET"])
def get_one_commitment(cid):
    require_roles(*ANY_ROLE)
    return success_object(get_commitment(cid))


@bp.route("/timeline-commitments", methods=["GET"])
def list_commitments():
    require_roles(*ANY_ROLE)
    records = list(db.timeline_commitments.values())
    app_id = request.args.get("service_application_id")
    if app_id is not None:
        records = [c for c in records if c["service_application_id"] == app_id]
    page, limit, offset, total = paginate(records)
    return success_list(page, limit, offset, total)


@bp.route("/timeline-commitments/<cid>/accept", methods=["POST"])
def accept_commitment(cid):
    user_id, _ = require_roles("Builder")
    commitment = get_commitment(cid)
    app = get_application(commitment["service_application_id"])
    _owns(user_id, app)
    check_app_mutable(app)
    if commitment["status"] != "PROPOSED":
        raise_error(ERR_INVALID_STATE, "Only PROPOSED commitments can be accepted")
    commitment["status"] = "ACCEPTED"
    touch(commitment)
    return success_object(commitment)


@bp.route("/timeline-commitments/<cid>/propose-revision", methods=["POST"])
def propose_revision(cid):
    user_id, _ = require_roles("Builder")
    commitment = get_commitment(cid)
    app = get_application(commitment["service_application_id"])
    _owns(user_id, app)
    body = get_body()
    require_fields(body, "requested_completion_date", "expected_commitment_version")
    requested = parse_iso_date(body["requested_completion_date"], "requested_completion_date")
    if body["expected_commitment_version"] != commitment["version"]:
        raise_error(ERR_STALE_VERSION, "Commitment version is stale")
    check_app_mutable(app)
    if commitment["status"] != "ACCEPTED":
        raise_error(ERR_COMMITMENT_NOT_REVISABLE, "Only ACCEPTED commitments can be revised")
    if requested <= db.today_date():
        raise_error(ERR_DATE_IN_PAST, "requested_completion_date must fall after the current date")
    commitment["requested_completion_date"] = body["requested_completion_date"]
    commitment["status"] = "REVISION_PENDING"
    touch(commitment)
    return success_object(commitment)


@bp.route("/timeline-commitments/<cid>/respond-revision", methods=["POST"])
def respond_revision(cid):
    require_roles("NewBusinessRep")
    commitment = get_commitment(cid)
    app = get_application(commitment["service_application_id"])
    body = get_body()
    require_fields(body, "decision")
    decision = require_enum(body, "decision", ("ACCEPT", "REJECT"))
    check_app_mutable(app)
    if commitment["status"] != "REVISION_PENDING":
        raise_error(ERR_INVALID_STATE, "Only REVISION_PENDING commitments can be answered")
    if decision == "ACCEPT":
        commitment["committed_completion_date"] = commitment["requested_completion_date"]
    commitment["requested_completion_date"] = None
    commitment["status"] = "ACCEPTED"
    touch(commitment)
    return success_object(commitment)


@bp.route("/timeline-commitments/<cid>/mark-delayed", methods=["POST"])
def mark_delayed(cid):
    require_roles("NewBusinessRep")
    commitment = get_commitment(cid)
    app = get_application(commitment["service_application_id"])
    body = get_body()
    require_fields(body, "delay_attribution", "expected_completion_date")
    attribution = require_enum(body, "delay_attribution", ATTRIBUTIONS)
    parse_iso_date(body["expected_completion_date"], "expected_completion_date")
    check_app_mutable(app)
    if commitment["status"] not in ("ACCEPTED", "AT_RISK"):
        raise_error(ERR_INVALID_STATE, "Only ACCEPTED or AT_RISK commitments can be flagged delayed")
    commitment["delay_attribution"] = attribution
    commitment["status"] = "AT_RISK"
    touch(commitment)
    return success_object(commitment)
