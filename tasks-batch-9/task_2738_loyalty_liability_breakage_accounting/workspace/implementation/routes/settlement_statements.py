"""SettlementStatement endpoints and the dispute cycle (PRD §3.5)."""
from flask import Blueprint

import calc
import db
import lookup
import serialize
from auth import (ROLE_CONTROLLER, ROLE_LOYALTY_ACCOUNTANT,
                  ROLE_PARTNER_OPERATOR, ROLE_PROGRAM_ADMIN, authorize,
                  require_operator_owns)
from errors import ApiError
from response import created, ok, paginate
from util import clock
from validate import field_int, field_ref, field_string, json_body

bp = Blueprint("settlement_statements", __name__)

READ_ROLES = (ROLE_PROGRAM_ADMIN, ROLE_LOYALTY_ACCOUNTANT, ROLE_CONTROLLER)


def pair_lots(agreement_id, period_id):
    return db.rows(
        db.store.point_lots,
        lambda l: l["partner_agreement_id"] == agreement_id
        and l["period_id"] == period_id
        and l["settlement_state"] == "PENDING_SETTLEMENT",
    )


@bp.route("/settlement-statements", methods=["POST"])
def create_settlement_statement():
    authorize(ROLE_LOYALTY_ACCOUNTANT)
    body = json_body()
    agreement_id = field_ref(body, "partner_agreement_id")
    period_id = field_ref(body, "period_id")
    expected_version = field_int(body, "expected_partner_agreement_version",
                                 minimum=0)
    agreement = lookup.partner_agreement(agreement_id)
    period = lookup.period(period_id)
    if expected_version != agreement["version"]:
        raise ApiError("ERR_STALE_AGREEMENT_VERSION", 412)
    if agreement["status"] != "ACTIVE":
        raise ApiError("ERR_AGREEMENT_NOT_ACTIVE", 409)
    if period["state"] == "HARD_CLOSED":
        raise ApiError("ERR_PERIOD_HARD_CLOSED", 409)
    if period["program_id"] != agreement["program_id"]:
        raise ApiError("ERR_PERIOD_PROGRAM_MISMATCH", 409)
    measured = calc.settlement_measurement(agreement, period)
    fields = {
        "partner_agreement_id": agreement["id"],
        "period_id": period["id"],
        "state": "DRAFT",
        "dispute_reason": None,
        "resolution_note": None,
        "write_off_reason": None,
        "dispute_count": 0,
        "issued_at": None,
        "paid_at": None,
    }
    fields.update(measured)
    rec = db.new_record(db.store.settlement_statements, fields)
    agreement["deferred_below_minimum_cents"] = rec["deferred_below_minimum_cents"]
    for prior in db.rows(db.store.settlement_statements):
        if prior["id"] == rec["id"]:
            continue
        if (prior["partner_agreement_id"] == agreement["id"]
                and prior["period_id"] == period["id"]
                and prior["state"] == "DRAFT"):
            prior["state"] = "SUPERSEDED"
            db.touch(prior)
    db.touch(agreement)
    return created(serialize.settlement_statement(rec))


@bp.route("/settlement-statements", methods=["GET"])
def list_settlement_statements():
    user_id, role = authorize(*READ_ROLES, ROLE_PARTNER_OPERATOR)
    rows = db.rows(db.store.settlement_statements)
    if role == ROLE_PARTNER_OPERATOR:
        rows = [r for r in rows if r["partner_agreement_id"] == user_id]
    rows = lookup.filtered(rows, "partner_agreement_id", "period_id", "state",
                           "settlement_basis")
    return paginate(rows, serialize.settlement_statement)


@bp.route("/settlement-statements/<statement_id>", methods=["GET"])
def read_settlement_statement(statement_id):
    user_id, role = authorize(*READ_ROLES, ROLE_PARTNER_OPERATOR)
    statement = lookup.settlement_statement(statement_id)
    require_operator_owns(user_id, role, statement["partner_agreement_id"])
    return ok(serialize.settlement_statement(statement))


@bp.route("/settlement-statements/<statement_id>/issue", methods=["POST"])
def issue_settlement_statement(statement_id):
    authorize(ROLE_LOYALTY_ACCOUNTANT)
    statement = lookup.settlement_statement(statement_id)
    agreement = lookup.partner_agreement(statement["partner_agreement_id"])
    period = lookup.period(statement["period_id"])
    if statement["state"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409)
    if agreement["status"] != "ACTIVE":
        raise ApiError("ERR_AGREEMENT_NOT_ACTIVE", 409)
    if period["state"] == "HARD_CLOSED":
        raise ApiError("ERR_PERIOD_HARD_CLOSED", 409)
    statement["state"] = "ISSUED"
    statement["issued_at"] = clock.now()
    agreement["outstanding_settlement_cents"] = (
        agreement["outstanding_settlement_cents"] + statement["net_due_cents"]
    )
    db.touch(agreement)
    db.touch(statement)
    return ok(serialize.settlement_statement(statement))


@bp.route("/settlement-statements/<statement_id>/dispute", methods=["POST"])
def dispute_settlement_statement(statement_id):
    user_id, role = authorize(ROLE_PARTNER_OPERATOR)
    statement = lookup.settlement_statement(statement_id)
    require_operator_owns(user_id, role, statement["partner_agreement_id"])
    body = json_body()
    reason = field_string(body, "dispute_reason", max_length=500)
    if statement["state"] != "ISSUED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409)
    if statement["dispute_count"] >= 2:
        raise ApiError("ERR_DISPUTE_LIMIT_EXCEEDED", 409)
    statement["state"] = "DISPUTED"
    statement["dispute_reason"] = reason
    statement["dispute_count"] = statement["dispute_count"] + 1
    db.touch(statement)
    return ok(serialize.settlement_statement(statement))


@bp.route("/settlement-statements/<statement_id>/resolve", methods=["POST"])
def resolve_settlement_statement(statement_id):
    authorize(ROLE_LOYALTY_ACCOUNTANT)
    body = json_body()
    note = field_string(body, "resolution_note", max_length=500)
    statement = lookup.settlement_statement(statement_id)
    if statement["state"] != "DISPUTED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409)
    statement["state"] = "ISSUED"
    statement["resolution_note"] = note
    statement["issued_at"] = clock.now()
    db.touch(statement)
    return ok(serialize.settlement_statement(statement))


@bp.route("/settlement-statements/<statement_id>/pay", methods=["POST"])
def pay_settlement_statement(statement_id):
    authorize(ROLE_CONTROLLER)
    statement = lookup.settlement_statement(statement_id)
    period = lookup.period(statement["period_id"])
    if statement["state"] != "ISSUED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409)
    if period["state"] == "HARD_CLOSED":
        raise ApiError("ERR_PERIOD_HARD_CLOSED", 409)
    agreement = lookup.partner_agreement(statement["partner_agreement_id"])
    statement["state"] = "PAID"
    statement["paid_at"] = clock.now()
    agreement["outstanding_settlement_cents"] = (
        agreement["outstanding_settlement_cents"] - statement["net_due_cents"]
    )
    for lot in pair_lots(agreement["id"], period["id"]):
        lot["settlement_state"] = "SETTLED"
        db.touch(lot)
    db.touch(agreement)
    db.touch(statement)
    return ok(serialize.settlement_statement(statement))


@bp.route("/settlement-statements/<statement_id>/write-off", methods=["POST"])
def write_off_settlement_statement(statement_id):
    authorize(ROLE_CONTROLLER)
    body = json_body()
    reason = field_string(body, "write_off_reason", max_length=500)
    statement = lookup.settlement_statement(statement_id)
    period = lookup.period(statement["period_id"])
    if statement["state"] not in ("ISSUED", "DISPUTED"):
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409)
    if period["state"] == "HARD_CLOSED":
        raise ApiError("ERR_PERIOD_HARD_CLOSED", 409)
    agreement = lookup.partner_agreement(statement["partner_agreement_id"])
    statement["state"] = "WRITTEN_OFF"
    statement["write_off_reason"] = reason
    agreement["outstanding_settlement_cents"] = (
        agreement["outstanding_settlement_cents"] - statement["net_due_cents"]
    )
    for lot in pair_lots(agreement["id"], period["id"]):
        lot["settlement_state"] = "WRITTEN_OFF"
        db.touch(lot)
    if agreement["status"] == "ACTIVE":
        agreement["status"] = "SUSPENDED"
    db.touch(agreement)
    db.touch(statement)
    return ok(serialize.settlement_statement(statement))
