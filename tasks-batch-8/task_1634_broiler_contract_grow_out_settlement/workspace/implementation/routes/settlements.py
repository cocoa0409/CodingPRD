"""Settlement lifecycle: approve, dispute, resolve-dispute, pay (PRD §3.10)."""
from flask import Blueprint

import db
import utils
from errors import ApiError
from helpers import get_or_404
from middleware import grower_owns_or_403, require_roles
from response import ok
from services import domain

bp = Blueprint("settlements", __name__)

GROWER = "Grower"
ANALYST = "SettlementAnalyst"


def _load_with_flock(sid):
    settlement = get_or_404(db.settlements, sid, "Settlement")
    flock = db.flocks.get(settlement["flock_id"])
    return settlement, flock


@bp.route("/api/settlements/<sid>/approve", methods=["POST"])
@require_roles(ANALYST)
def approve(sid):
    settlement, flock = _load_with_flock(sid)
    if settlement["status"] != "PENDING":
        raise ApiError(
            "ERR_INVALID_STATE",
            "Only a PENDING settlement can be approved (current: %s)."
            % settlement["status"],
            409,
        )
    group = db.settlement_groups.get(flock["settlement_group_id"])
    if group is None or group["status"] != "LOCKED" or settlement["variant"] != "FINAL":
        raise ApiError(
            "ERR_GROUP_NOT_LOCKED",
            "Approval requires the settlement group to be LOCKED and the settlement variant FINAL.",
            409,
        )
    domain.approve_settlement(settlement)
    return ok(utils.pub(settlement))


@bp.route("/api/settlements/<sid>/dispute", methods=["POST"])
@require_roles(GROWER)
def dispute(sid):
    settlement, flock = _load_with_flock(sid)
    grower_owns_or_403(domain.grower_id_of_flock(flock))
    if settlement["status"] != "PENDING":
        raise ApiError(
            "ERR_INVALID_STATE",
            "Only a PENDING settlement can be disputed (current: %s)."
            % settlement["status"],
            409,
        )
    settlement["status"] = "DISPUTED"
    domain.bump(settlement)
    return ok(utils.pub(settlement))


@bp.route("/api/settlements/<sid>/resolve-dispute", methods=["POST"])
@require_roles(ANALYST)
def resolve_dispute(sid):
    settlement, flock = _load_with_flock(sid)
    if settlement["status"] != "DISPUTED":
        raise ApiError(
            "ERR_INVALID_STATE",
            "Only a DISPUTED settlement can be resolved (current: %s)."
            % settlement["status"],
            409,
        )
    amounts = domain.compute_settlement_amounts(flock)
    for key, value in amounts.items():
        settlement[key] = value
    settlement["status"] = "PENDING"
    domain.bump(settlement)
    return ok(utils.pub(settlement))


@bp.route("/api/settlements/<sid>/pay", methods=["POST"])
@require_roles(ANALYST)
def pay(sid):
    settlement, flock = _load_with_flock(sid)
    if settlement["status"] != "APPROVED":
        raise ApiError(
            "ERR_INVALID_STATE",
            "Only an APPROVED settlement can be paid (current: %s)."
            % settlement["status"],
            409,
        )
    settlement["status"] = "PAID"
    domain.bump(settlement)
    return ok(utils.pub(settlement))
