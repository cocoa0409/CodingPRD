"""Trade and vote routes."""
from __future__ import annotations

from flask import Blueprint, request

from core.auth import current_user_id, require_roles
from core.envelope import get_json_body, success_response
from core.pagination import paginate, parse_pagination
from core.serializers import serialize_entity, serialize_list
from core.utils import lock
from services import trade_service


bp = Blueprint("trades", __name__)


@bp.post("/leagues/<league_id>/trades")
@require_roles("Manager")
def propose(league_id):
    with lock():
        body = get_json_body()
        t = trade_service.propose_trade(league_id, body, current_user_id())
        return success_response(serialize_entity(t), status=201)


@bp.get("/leagues/<league_id>/trades")
@require_roles("Commissioner", "Manager")
def list_trades(league_id):
    limit, offset = parse_pagination()
    status = request.args.get("status")
    team_id = request.args.get("team_id")
    items = trade_service.list_trades(league_id, status=status, team_id=team_id)
    sliced, meta = paginate(items, limit, offset)
    return success_response(
        serialize_list(sliced),
        response_type="array",
        pagination=meta,
    )


@bp.post("/trades/<trade_id>/accept")
@require_roles("Manager")
def accept(trade_id):
    with lock():
        t = trade_service.accept_trade(trade_id, current_user_id())
        return success_response(serialize_entity(t))


@bp.post("/trades/<trade_id>/reject")
@require_roles("Manager")
def reject(trade_id):
    with lock():
        t = trade_service.reject_trade(trade_id, current_user_id())
        return success_response(serialize_entity(t))


@bp.post("/trades/<trade_id>/cancel")
@require_roles("Manager")
def cancel(trade_id):
    with lock():
        t = trade_service.cancel_trade(trade_id, current_user_id())
        return success_response(serialize_entity(t))


@bp.post("/trades/<trade_id>/votes")
@require_roles("Manager")
def vote(trade_id):
    with lock():
        body = get_json_body()
        v = trade_service.cast_vote(trade_id, body, current_user_id())
        return success_response(serialize_entity(v), status=201)
