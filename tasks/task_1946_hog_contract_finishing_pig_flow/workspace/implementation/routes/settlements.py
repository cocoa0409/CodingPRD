"""Settlements (PRD §3.8): dispute cycle, refinalize with signed adjustment,
approve/pay with segregation of duties, grower lifetime ledger."""

from flask import Blueprint, request

from db import store
from errors import conflict, segregation_of_duties, ERR_INVALID_STATE_TRANSITION
from middleware import (
    require_roles, check_grower_ownership, settlement_owner_id,
    ROLE_INTEGRATOR_ADMIN, ROLE_FIELD_TECH, ROLE_GROWER,
)
from response import success_object, paginate
from services.core import touch, ser_settlement
from util import get_body, req, as_str, as_int, load_or_404

bp = Blueprint("settlements", __name__)

ROLES_READ = [ROLE_INTEGRATOR_ADMIN, ROLE_FIELD_TECH, ROLE_GROWER]


@bp.route("/settlements", methods=["GET"])
def list_settlements():
    require_roles(ROLES_READ)
    group_id = request.args.get("group_id")
    contract_id = request.args.get("contract_id")
    status = request.args.get("settlement_status")
    items = list(store.settlements.values())
    if group_id is not None:
        items = [s for s in items if s["group_id"] == group_id]
    if contract_id is not None:
        items = [s for s in items if s["contract_id"] == contract_id]
    if status is not None:
        items = [s for s in items if s["settlement_status"] == status]
    return paginate(items, request.args, ser_settlement)


@bp.route("/settlements/<sid>", methods=["GET"])
def get_settlement(sid):
    role, user_id = require_roles(ROLES_READ)
    settlement = load_or_404(store.settlements, sid, "Settlement")
    check_grower_ownership(role, user_id, settlement_owner_id(settlement))
    return success_object(ser_settlement(settlement))


@bp.route("/settlements/<sid>/dispute", methods=["POST"])
def dispute_settlement(sid):
    role, user_id = require_roles([ROLE_GROWER])
    settlement = load_or_404(store.settlements, sid, "Settlement")
    # only the owning grower may dispute (§3.8)
    check_grower_ownership(role, user_id, settlement_owner_id(settlement))
    body = get_body()
    as_str(req(body, "reason"), "reason")
    if settlement["settlement_status"] != "FINALIZED":
        raise conflict(ERR_INVALID_STATE_TRANSITION,
                       f"Cannot dispute a settlement in {settlement['settlement_status']}")
    settlement["settlement_status"] = "DISPUTED"
    touch(settlement)
    return success_object(ser_settlement(settlement))


@bp.route("/settlements/<sid>/refinalize", methods=["POST"])
def refinalize_settlement(sid):
    require_roles([ROLE_FIELD_TECH])
    settlement = load_or_404(store.settlements, sid, "Settlement")
    body = get_body()
    adjustment = as_int(req(body, "adjustment_cents"), "adjustment_cents")
    if settlement["settlement_status"] != "DISPUTED":
        raise conflict(ERR_INVALID_STATE_TRANSITION,
                       f"Cannot refinalize a settlement in {settlement['settlement_status']}")
    # each refinalize REPLACES adjustment_cents (never accumulates)
    settlement["adjustment_cents"] = adjustment
    settlement["total_pay_cents"] = (settlement["base_pay_cents"]
                                     + settlement["bonus_cents"] + adjustment
                                     - settlement["deductions_cents"])
    settlement["settlement_status"] = "FINALIZED"
    touch(settlement)
    return success_object(ser_settlement(settlement))


@bp.route("/settlements/<sid>/approve", methods=["POST"])
def approve_settlement(sid):
    role, user_id = require_roles([ROLE_INTEGRATOR_ADMIN])
    settlement = load_or_404(store.settlements, sid, "Settlement")
    if settlement["settlement_status"] != "FINALIZED":
        raise conflict(ERR_INVALID_STATE_TRANSITION,
                       f"Cannot approve a settlement in {settlement['settlement_status']}")
    settlement["approved_by"] = user_id
    settlement["settlement_status"] = "APPROVED"
    touch(settlement)
    return success_object(ser_settlement(settlement))


@bp.route("/settlements/<sid>/pay", methods=["POST"])
def pay_settlement(sid):
    role, user_id = require_roles([ROLE_INTEGRATOR_ADMIN])
    settlement = load_or_404(store.settlements, sid, "Settlement")
    if settlement["settlement_status"] != "APPROVED":
        raise conflict(ERR_INVALID_STATE_TRANSITION,
                       f"Cannot pay a settlement in {settlement['settlement_status']}")
    # SoD: the payer must differ from the approver (§2.11)
    if user_id == settlement["approved_by"]:
        raise segregation_of_duties("Payer must differ from the settlement approver")
    settlement["paid_by"] = user_id
    settlement["settlement_status"] = "PAID"
    touch(settlement)
    # the grower's lifetime ledger moves by exactly total_pay_cents
    contract = store.contracts.get(settlement["contract_id"])
    if contract is not None:
        grower = store.growers.get(contract["grower_id"])
        if grower is not None:
            grower["lifetime_paid_cents"] += settlement["total_pay_cents"]
            touch(grower)
    return success_object(ser_settlement(settlement))
