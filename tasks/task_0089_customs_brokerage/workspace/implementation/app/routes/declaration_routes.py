"""Declaration routes."""
from __future__ import annotations

from flask import Flask, request

from ..auth import current_actor, require_auth
from ..errors import ApiError
from ..pagination import parse_limit_offset
from ..services import declarations
from ..services.serializers import serialize_declaration
from ._helpers import get_json_body, ok, ok_list, with_lock


def register(app: Flask) -> None:
    @app.post("/customs/declarations")
    @require_auth("DeclarationOfficer", "BrokerOps")
    @with_lock
    def _create_declaration():
        body = get_json_body()
        record = declarations.create_declaration(body)
        return ok(serialize_declaration(record), status=201)

    @app.get("/customs/declarations/<declaration_id>")
    @require_auth(
        "DeclarationOfficer",
        "DocReviewer",
        "FilingOfficer",
        "SettlementOfficer",
        "BrokerOps",
        "ClientUser",
        "SystemAdmin",
    )
    @with_lock
    def _get_declaration(declaration_id):
        record = declarations.get_declaration(declaration_id)
        user_id, role = current_actor()
        if role == "ClientUser":
            from ..store import get_store

            agreement = get_store().agreements.get(record.get("agreement_id"))
            if not agreement or agreement.get("client_id") != user_id:
                raise ApiError("ERR_FORBIDDEN", "Cross-tenant access denied.")
        return ok(serialize_declaration(record))

    @app.get("/customs/declarations")
    @require_auth(
        "DeclarationOfficer",
        "DocReviewer",
        "FilingOfficer",
        "SettlementOfficer",
        "BrokerOps",
        "SystemAdmin",
        "ClientUser",
    )
    @with_lock
    def _list_declarations():
        limit, offset = parse_limit_offset()
        status = request.args.get("status")
        agreement_id = request.args.get("agreement_id")
        items = declarations.list_declarations(status, agreement_id, limit, offset)
        return ok_list([serialize_declaration(d) for d in items], limit, offset)

    @app.patch("/customs/declarations/<declaration_id>")
    @require_auth("DeclarationOfficer")
    @with_lock
    def _patch_declaration(declaration_id):
        body = get_json_body()
        record = declarations.update_declaration(declaration_id, body)
        return ok(serialize_declaration(record))

    @app.post("/customs/declarations/<declaration_id>/request-documents")
    @require_auth("DeclarationOfficer")
    @with_lock
    def _request_documents(declaration_id):
        body = get_json_body()
        record = declarations.request_documents(declaration_id, body)
        return ok(serialize_declaration(record))

    @app.post("/customs/declarations/<declaration_id>/pre-validate")
    @require_auth("DocReviewer")
    @with_lock
    def _pre_validate(declaration_id):
        body = get_json_body()
        record = declarations.pre_validate(declaration_id, body)
        return ok(serialize_declaration(record))

    @app.post("/customs/declarations/<declaration_id>/file")
    @require_auth("FilingOfficer")
    @with_lock
    def _file(declaration_id):
        body = get_json_body()
        record = declarations.file_declaration(declaration_id, body)
        return ok(serialize_declaration(record))

    @app.post("/customs/declarations/<declaration_id>/respond-query")
    @require_auth("FilingOfficer")
    @with_lock
    def _respond_query(declaration_id):
        body = get_json_body()
        record = declarations.respond_query(declaration_id, body)
        return ok(serialize_declaration(record))

    @app.post("/customs/declarations/<declaration_id>/amend")
    @require_auth("DeclarationOfficer")
    @with_lock
    def _amend(declaration_id):
        body = get_json_body()
        record = declarations.amend_declaration(declaration_id, body)
        return ok(serialize_declaration(record))

    @app.post("/customs/declarations/<declaration_id>/withdraw")
    @require_auth("BrokerOps")
    @with_lock
    def _withdraw(declaration_id):
        body = get_json_body()
        record = declarations.withdraw_declaration(declaration_id, body)
        return ok(serialize_declaration(record))
