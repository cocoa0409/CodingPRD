"""Settlement routes."""
from __future__ import annotations

from flask import Flask, request

from ..auth import current_actor, require_auth
from ..errors import ApiError
from ..pagination import parse_limit_offset
from ..services import settlements
from ..services.serializers import serialize_settlement
from ..store import get_store
from ._helpers import get_json_body, ok, ok_list, with_lock


def register(app: Flask) -> None:
    @app.get("/customs/settlements/<settlement_id>")
    @require_auth("SettlementOfficer", "BrokerOps", "ClientUser", "SystemAdmin")
    @with_lock
    def _get_settlement(settlement_id):
        record = settlements.get_settlement(settlement_id)
        user_id, role = current_actor()
        if role == "ClientUser":
            store = get_store()
            declaration = store.declarations.get(record.get("declaration_id"))
            agreement = (
                store.agreements.get(declaration.get("agreement_id")) if declaration else None
            )
            if not agreement or agreement.get("client_id") != user_id:
                raise ApiError("ERR_FORBIDDEN", "Cross-tenant access denied.")
        return ok(serialize_settlement(record))

    @app.get("/customs/settlements")
    @require_auth(
        "SettlementOfficer", "BrokerOps", "SystemAdmin", "ClientUser"
    )
    @with_lock
    def _list_settlements():
        limit, offset = parse_limit_offset()
        status = request.args.get("status")
        declaration_id = request.args.get("declaration_id")
        items = settlements.list_settlements(status, declaration_id, limit, offset)
        return ok_list([serialize_settlement(s) for s in items], limit, offset)

    @app.post("/customs/settlements/<settlement_id>/advance")
    @require_auth("SettlementOfficer")
    @with_lock
    def _advance(settlement_id):
        body = get_json_body()
        record = settlements.advance_settlement(settlement_id, body)
        return ok(serialize_settlement(record))
