"""Sharing agreement endpoints."""
from flask import Blueprint

import db
from clock import parse_iso8601, now
from errors import raise_error
from middleware import (
    require_roles,
    get_json_body,
    check_known_fields,
    require_fields,
    validate_string,
    validate_use_list,
    validate_positive_number,
    ALL_ROLES,
)
from response import success_object
from serializers import agreement_out
from services.common import make_record, get_or_404, touch

bp = Blueprint("agreements", __name__)


@bp.route("/biobank/sharing-agreements", methods=["POST"])
def create_agreement():
    require_roles({"BiobankAdmin"})
    body = get_json_body()
    check_known_fields(body, {
        "recipient_institution", "scope_uses", "total_committed_volume_ml",
        "effective_from", "effective_to",
    })
    require_fields(body, [
        "recipient_institution", "scope_uses", "total_committed_volume_ml",
        "effective_from", "effective_to",
    ])
    recipient = validate_string(body["recipient_institution"], "recipient_institution")
    scope_uses = validate_use_list(body["scope_uses"], "scope_uses", non_empty=True)
    total = validate_positive_number(body["total_committed_volume_ml"], "total_committed_volume_ml")
    effective_from = parse_iso8601(body["effective_from"], "effective_from")
    effective_to = parse_iso8601(body["effective_to"], "effective_to")
    agreement = make_record(db.sharing_agreements, {
        "recipient_institution": recipient,
        "scope_uses": list(scope_uses),
        "total_committed_volume_ml": total,
        "remaining_volume_ml": 0,
        "reserved_volume_ml": 0,
        "fulfilled_volume_ml": 0,
        "effective_from": effective_from,
        "effective_to": effective_to,
        "status": "DRAFT",
    })
    return success_object(agreement_out(agreement), status=201)


@bp.route("/biobank/sharing-agreements/<agreementId>", methods=["GET"])
def get_agreement(agreementId):
    require_roles(ALL_ROLES)
    agreement = get_or_404(db.sharing_agreements, agreementId, "sharing agreement")
    return success_object(agreement_out(agreement))


@bp.route("/biobank/sharing-agreements/<agreementId>/activate", methods=["POST"])
def activate_agreement(agreementId):
    require_roles({"BiobankAdmin"})
    agreement = get_or_404(db.sharing_agreements, agreementId, "sharing agreement")
    get_json_body()
    if agreement["status"] != "DRAFT":
        raise_error("ERR_INVALID_STATE", "Agreement must be DRAFT to activate")
    if now() >= agreement["effective_to"]:
        raise_error("ERR_AGREEMENT_NOT_EFFECTIVE", "Agreement window has already closed")
    agreement["status"] = "ACTIVE"
    agreement["remaining_volume_ml"] = agreement["total_committed_volume_ml"]
    touch(agreement)
    return success_object(agreement_out(agreement))


@bp.route("/biobank/sharing-agreements/<agreementId>/terminate", methods=["POST"])
def terminate_agreement(agreementId):
    require_roles({"BiobankAdmin"})
    agreement = get_or_404(db.sharing_agreements, agreementId, "sharing agreement")
    get_json_body()
    if agreement["status"] != "ACTIVE":
        raise_error("ERR_INVALID_STATE", "Agreement must be ACTIVE to terminate")
    if agreement["reserved_volume_ml"] != 0:
        raise_error("ERR_AGREEMENT_HAS_ACTIVE_RESERVATIONS", "Agreement has outstanding reservations")
    agreement["status"] = "TERMINATED"
    touch(agreement)
    return success_object(agreement_out(agreement))
