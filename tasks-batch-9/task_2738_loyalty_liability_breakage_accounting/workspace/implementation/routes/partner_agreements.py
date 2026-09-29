"""PartnerAgreement endpoints (PRD §3.5)."""
from flask import Blueprint

import db
import lookup
import serialize
from auth import (ROLE_CONTROLLER, ROLE_LOYALTY_ACCOUNTANT,
                  ROLE_PARTNER_OPERATOR, ROLE_PROGRAM_ADMIN, authorize,
                  require_operator_owns)
from errors import ApiError
from response import created, ok, paginate
from util import add_days
from validate import (field_bool, field_datetime, field_enum, field_int,
                      field_ref, field_string, json_body)

bp = Blueprint("partner_agreements", __name__)

READ_ROLES = (ROLE_PROGRAM_ADMIN, ROLE_LOYALTY_ACCOUNTANT, ROLE_CONTROLLER)
RELATIONSHIP_TYPES = ("INTERCOMPANY", "THIRD_PARTY")


@bp.route("/partner-agreements", methods=["POST"])
def create_partner_agreement():
    authorize(ROLE_PROGRAM_ADMIN)
    body = json_body()
    program_id = field_ref(body, "program_id")
    partner_code = field_string(body, "partner_code", max_length=32)
    relationship_type = field_enum(body, "relationship_type", RELATIONSHIP_TYPES)
    issuance_rate = field_int(body, "issuance_rate_millicents_per_point",
                              minimum=0, maximum=100000)
    redemption_rate = field_int(body, "redemption_rate_millicents_per_point",
                                minimum=0, maximum=100000)
    settlement_lag_days = field_int(body, "settlement_lag_days", required=False,
                                    default=30, minimum=0, maximum=365)
    net_settlement_enabled = field_bool(body, "net_settlement_enabled",
                                        required=False, default=False)
    min_invoice_cents = field_int(body, "min_invoice_cents", required=False,
                                  default=5000, minimum=0)
    start = field_datetime(body, "effective_start_date")
    end = field_datetime(body, "effective_end_date")
    lookup.program(program_id)
    if not end > start:
        raise ApiError("ERR_INVALID_WINDOW", 409)
    for prior in db.rows(db.store.partner_agreements):
        if prior["program_id"] != program_id:
            continue
        if prior["partner_code"] != partner_code:
            continue
        if prior["status"] == "TERMINATED":
            continue
        buffered_end = add_days(prior["effective_end_date"],
                                prior["settlement_lag_days"])
        if start <= buffered_end:
            raise ApiError("ERR_PARTNER_WINDOW_CONFLICT", 409)
    rec = db.new_record(db.store.partner_agreements, {
        "program_id": program_id,
        "partner_code": partner_code,
        "relationship_type": relationship_type,
        "issuance_rate_millicents_per_point": issuance_rate,
        "redemption_rate_millicents_per_point": redemption_rate,
        "settlement_lag_days": settlement_lag_days,
        "net_settlement_enabled": net_settlement_enabled,
        "min_invoice_cents": min_invoice_cents,
        "effective_start_date": start,
        "effective_end_date": end,
        "status": "ACTIVE",
        "deferred_below_minimum_cents": 0,
        "outstanding_settlement_cents": 0,
    })
    return created(serialize.partner_agreement(rec))


@bp.route("/partner-agreements", methods=["GET"])
def list_partner_agreements():
    authorize(*READ_ROLES)
    rows = lookup.filtered(db.rows(db.store.partner_agreements), "program_id",
                           "partner_code", "status", "relationship_type")
    return paginate(rows, serialize.partner_agreement)


@bp.route("/partner-agreements/<agreement_id>", methods=["GET"])
def read_partner_agreement(agreement_id):
    user_id, role = authorize(*READ_ROLES, ROLE_PARTNER_OPERATOR)
    agreement = lookup.partner_agreement(agreement_id)
    require_operator_owns(user_id, role, agreement["id"])
    return ok(serialize.partner_agreement(agreement))


@bp.route("/partner-agreements/<agreement_id>/terminate", methods=["POST"])
def terminate_partner_agreement(agreement_id):
    authorize(ROLE_PROGRAM_ADMIN)
    agreement = lookup.partner_agreement(agreement_id)
    if agreement["status"] not in ("ACTIVE", "SUSPENDED"):
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409)
    if agreement["outstanding_settlement_cents"] != 0:
        raise ApiError("ERR_OUTSTANDING_SETTLEMENT", 409)
    agreement["status"] = "TERMINATED"
    db.touch(agreement)
    return ok(serialize.partner_agreement(agreement))
