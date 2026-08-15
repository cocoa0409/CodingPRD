"""Disbursement leg routes (PRD §3.7): authorize/release/void with SoD."""

from flask import Blueprint

import db
from errors import ApiError, ERR_NOT_FOUND, ERR_FORBIDDEN_RESOURCE
from middleware import parse_enum_filter, parse_str_filter
from response import success_obj
from routes.helpers import guard, public, list_response, by_created
from services.common import touch
from services.deal_svc import check_leg_actionable, release_leg
from timeutil import logical_stamp

bp = Blueprint("legs", __name__)

LEG_PAYEE_TYPES = {"AGENT", "MENTOR", "TEAM_LEAD", "REFERRAL", "CO_BROKE", "ROYALTY", "COMPANY"}
LEG_STATUSES = {"SCHEDULED", "AUTHORIZED", "RELEASED", "VOIDED"}


def _get_leg(leg_id):
    leg = db.legs.get(leg_id)
    if leg is None:
        raise ApiError(ERR_NOT_FOUND, 404, "disbursement leg not found")
    return leg


def _leg_owner_ok(role, user_id, leg):
    """Agent-role read access: legs where the caller is the payee or the
    deal's credited agent."""
    if role != "Agent":
        return
    if leg.get("payee_agent_id") == user_id:
        return
    settlement = db.settlements.get(leg["settlement_id"])
    if settlement is not None and settlement["agent_id"] == user_id:
        return
    raise ApiError(ERR_FORBIDDEN_RESOURCE, 403, "not a leg of the caller")


@bp.route("/brokerage/disbursement-legs/<legId>", methods=["GET"])
@guard(roles=["BrokerAdmin", "OfficeManager", "TransactionCoordinator", "Auditor", "Agent"])
def get_leg(user_id, role, legId):
    leg = _get_leg(legId)
    _leg_owner_ok(role, user_id, leg)
    return success_obj(public(leg))


@bp.route("/brokerage/disbursement-legs", methods=["GET"])
@guard(roles=["BrokerAdmin", "OfficeManager", "TransactionCoordinator", "Auditor", "Agent"])
def list_legs(user_id, role):
    settlement_id = parse_str_filter("settlement_id")
    payee_agent_id = parse_str_filter("payee_agent_id")
    payee_type = parse_enum_filter("payee_type", LEG_PAYEE_TYPES)
    status = parse_enum_filter("status", LEG_STATUSES)
    items = list(db.legs.values())
    if role == "Agent":
        items = [l for l in items if l.get("payee_agent_id") == user_id]
    if settlement_id is not None:
        items = [l for l in items if l["settlement_id"] == settlement_id]
    if payee_agent_id is not None:
        items = [l for l in items if l.get("payee_agent_id") == payee_agent_id]
    if payee_type is not None:
        items = [l for l in items if l["payee_type"] == payee_type]
    if status is not None:
        items = [l for l in items if l["status"] == status]
    return list_response(by_created(items))


@bp.route("/brokerage/disbursement-legs/<legId>/authorize", methods=["POST"])
@guard(roles=["OfficeManager", "BrokerAdmin"])
def authorize_leg(user_id, role, legId):
    leg = _get_leg(legId)
    check_leg_actionable(leg, user_id, "authorize")
    leg["authorized_by_user_id"] = user_id
    leg["authorized_at"] = logical_stamp()
    leg["status"] = "AUTHORIZED"
    touch(leg)
    return success_obj(public(leg))


@bp.route("/brokerage/disbursement-legs/<legId>/release", methods=["POST"])
@guard(roles=["OfficeManager", "BrokerAdmin"])
def release(user_id, role, legId):
    leg = _get_leg(legId)
    release_leg(leg, user_id)
    return success_obj(public(leg))


@bp.route("/brokerage/disbursement-legs/<legId>/void", methods=["POST"])
@guard(roles=["OfficeManager", "BrokerAdmin"])
def void_leg(user_id, role, legId):
    leg = _get_leg(legId)
    check_leg_actionable(leg, user_id, "void")
    leg["status"] = "VOIDED"
    touch(leg)
    return success_obj(public(leg))
