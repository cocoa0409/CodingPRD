"""Settlement read + reverse endpoints (PRD §3.8)."""
from flask import Blueprint

import errors
import domain
from db import db
from middleware import get_principal, require_role
from serializers import serialize
from response import success
from routes.common import list_filtered

bp = Blueprint("settlements", __name__)


@bp.route("/settlements", methods=["GET"])
def list_settlements():
    _, role = get_principal()
    require_role(role, {"NetworkAdmin", "LoungeAgent"})
    return list_filtered(
        db.settlements,
        [
            ("lounge_id", "lounge_id", "str"),
            ("visit_id", "visit_id", "str"),
            ("status", "status", "str"),
        ],
    )


@bp.route("/settlements/<settlement_id>", methods=["GET"])
def get_settlement(settlement_id):
    _, role = get_principal()
    require_role(role, {"NetworkAdmin", "LoungeAgent"})
    s = domain.get_settlement(settlement_id)
    if not s:
        raise errors.not_found("Settlement not found")
    return success(serialize(s))


@bp.route("/settlements/<settlement_id>/reverse", methods=["POST"])
def reverse_settlement(settlement_id):
    _, role = get_principal()
    require_role(role, {"NetworkAdmin"})
    s = domain.get_settlement(settlement_id)
    if not s:
        raise errors.not_found("Settlement not found")
    if s["status"] != "PAYABLE":
        raise errors.err("ERR_SETTLEMENT_NOT_PAYABLE",
                         "Settlement is not PAYABLE")
    s["status"] = "REVERSED"
    lounge = domain.get_lounge(s["lounge_id"])
    if lounge:
        domain.recompute_lounge_settlement_balance(lounge)
    return success(serialize(s))
