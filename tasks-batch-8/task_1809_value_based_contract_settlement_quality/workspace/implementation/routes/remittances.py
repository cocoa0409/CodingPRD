"""DistributionRemittance endpoints."""

from __future__ import annotations

from flask import Blueprint

import db
from errors import (
    raise_err,
    ERR_GROUP_NOT_ACTIVE,
    ERR_INVALID_STATE_TRANSITION,
    ERR_NOT_FOUND,
    ERR_SETTLEMENT_NOT_AUTHORIZED,
)
from middleware import ALL_ROLES, require_roles
from response import success_list, success_object
from services import calculations as calc
from util import (
    apply_filters,
    paginate,
    parse_pagination,
    sort_by_created_at,
)

bp = Blueprint("remittances", __name__)


def _get_remittance_or_404(remittance_id: str) -> dict:
    remittance = db.distribution_remittances.get(remittance_id)
    if remittance is None:
        raise_err(ERR_NOT_FOUND, "DistributionRemittance id does not exist")
    return remittance


@bp.route("/vbc/distribution-remittances", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_remittances(_user_id: str, _role: str):
    limit, offset = parse_pagination()
    items = sort_by_created_at(list(db.distribution_remittances.values()))
    items = apply_filters(items, ["settlement_id", "practice_id", "remittance_status"])
    page, total = paginate(items, limit, offset)
    return success_list(page, limit, offset, total)


@bp.route("/vbc/distribution-remittances/<remittance_id>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_remittance(remittance_id: str, _user_id: str, _role: str):
    return success_object(_get_remittance_or_404(remittance_id))


@bp.route("/vbc/distribution-remittances/<remittance_id>/approve", methods=["POST"])
@require_roles("PaymentOps")
def approve_remittance(remittance_id: str, _user_id: str, _role: str):
    remittance = _get_remittance_or_404(remittance_id)
    if remittance["remittance_status"] != "SCHEDULED":
        raise_err(ERR_INVALID_STATE_TRANSITION, "Only a SCHEDULED remittance can be approved")
    settlement = db.settlements[remittance["settlement_id"]]
    if settlement["settlement_status"] != "AUTHORIZED":
        raise_err(ERR_SETTLEMENT_NOT_AUTHORIZED, "Settlement must be AUTHORIZED")
    practice = db.practices.get(remittance["practice_id"])
    group = db.practice_groups.get(practice["practice_group_id"]) if practice else None
    if group is None or group["group_status"] != "ACTIVE":
        raise_err(ERR_GROUP_NOT_ACTIVE, "The practice's group must be ACTIVE")
    remittance["remittance_status"] = "APPROVED"
    db.touch(remittance)
    return success_object(remittance)


@bp.route("/vbc/distribution-remittances/<remittance_id>/mark-paid", methods=["POST"])
@require_roles("PaymentOps")
def mark_remittance_paid(remittance_id: str, _user_id: str, _role: str):
    remittance = _get_remittance_or_404(remittance_id)
    if remittance["remittance_status"] != "APPROVED":
        raise_err(ERR_INVALID_STATE_TRANSITION, "Only an APPROVED remittance can be marked paid")
    remittance["remittance_status"] = "PAID"
    remittance["paid_on"] = db.clock_date_iso()
    db.touch(remittance)
    # When every remittance of the settlement is PAID: AUTHORIZED -> DISTRIBUTED.
    settlement = db.settlements[remittance["settlement_id"]]
    siblings = [
        r for r in db.distribution_remittances.values()
        if r["settlement_id"] == settlement["id"]
    ]
    if siblings and all(r["remittance_status"] == "PAID" for r in siblings):
        db.apply_updates(settlement, {"settlement_status": "DISTRIBUTED"})
    return success_object(remittance)


@bp.route("/vbc/distribution-remittances/<remittance_id>/return", methods=["POST"])
@require_roles("PaymentOps")
def return_remittance(remittance_id: str, _user_id: str, _role: str):
    remittance = _get_remittance_or_404(remittance_id)
    if remittance["remittance_status"] != "APPROVED":
        raise_err(ERR_INVALID_STATE_TRANSITION, "Only an APPROVED remittance can be returned")
    remittance["remittance_status"] = "RETURNED"
    db.touch(remittance)
    # The RETURNED amount is released back into the undistributed balance.
    settlement = db.settlements[remittance["settlement_id"]]
    db.apply_updates(
        settlement,
        {"undistributed_balance_cents": calc.recompute_undistributed(settlement)},
    )
    return success_object(remittance)


@bp.route("/vbc/distribution-remittances/<remittance_id>/requeue", methods=["POST"])
@require_roles("PaymentOps")
def requeue_remittance(remittance_id: str, _user_id: str, _role: str):
    remittance = _get_remittance_or_404(remittance_id)
    if remittance["remittance_status"] != "RETURNED":
        raise_err(ERR_INVALID_STATE_TRANSITION, "Only a RETURNED remittance can be requeued")
    settlement = db.settlements[remittance["settlement_id"]]
    if settlement["settlement_status"] != "AUTHORIZED":
        raise_err(ERR_SETTLEMENT_NOT_AUTHORIZED, "Settlement must be AUTHORIZED")
    remittance["remittance_status"] = "SCHEDULED"
    db.touch(remittance)
    db.apply_updates(
        settlement,
        {"undistributed_balance_cents": calc.recompute_undistributed(settlement)},
    )
    return success_object(remittance)
