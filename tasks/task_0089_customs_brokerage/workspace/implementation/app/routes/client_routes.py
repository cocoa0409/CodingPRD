"""Client (ClientCompany) routes."""
from __future__ import annotations

from flask import Flask

from ..auth import current_actor, require_auth
from ..errors import ApiError
from ..pagination import parse_limit_offset
from ..services import clients
from ..services.serializers import serialize_client
from ._helpers import get_json_body, ok, ok_list, with_lock


def register(app: Flask) -> None:
    @app.post("/customs/clients")
    @require_auth("BrokerOps", "SystemAdmin")
    @with_lock
    def _create_client():
        body = get_json_body()
        record = clients.create_client(body)
        return ok(serialize_client(record), status=201)

    @app.get("/customs/clients/<client_id>")
    @require_auth("BrokerOps", "SystemAdmin", "ClientUser")
    @with_lock
    def _get_client(client_id):
        record = clients.get_client(client_id)
        user_id, role = current_actor()
        if role == "ClientUser" and user_id != record["id"]:
            raise ApiError("ERR_FORBIDDEN", "ClientUser may only read their own client.")
        return ok(serialize_client(record))

    @app.get("/customs/clients")
    @require_auth("BrokerOps", "SystemAdmin")
    @with_lock
    def _list_clients():
        from flask import request

        limit, offset = parse_limit_offset()
        status = request.args.get("status")
        items = clients.list_clients(status, limit, offset)
        return ok_list([serialize_client(c) for c in items], limit, offset)

    @app.patch("/customs/clients/<client_id>")
    @require_auth("BrokerOps", "SystemAdmin")
    @with_lock
    def _patch_client(client_id):
        body = get_json_body()
        record = clients.update_client(client_id, body)
        return ok(serialize_client(record))
