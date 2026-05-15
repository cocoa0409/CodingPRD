"""ShipmentDocument routes."""
from __future__ import annotations

from flask import Flask

from ..auth import current_actor, require_auth
from ..errors import ApiError
from ..services import documents
from ..services.serializers import serialize_document
from ..store import get_store
from ._helpers import get_json_body, ok, with_lock


def register(app: Flask) -> None:
    @app.post("/customs/declarations/<declaration_id>/documents")
    @require_auth("DeclarationOfficer", "ClientUser")
    @with_lock
    def _attach(declaration_id):
        body = get_json_body()
        store = get_store()
        # ClientUser ownership
        user_id, role = current_actor()
        if role == "ClientUser":
            declaration = store.declarations.get(declaration_id)
            if declaration is None:
                raise ApiError("ERR_NOT_FOUND", f"Declaration {declaration_id!r} not found.")
            agreement = store.agreements.get(declaration.get("agreement_id"))
            if not agreement or agreement.get("client_id") != user_id:
                raise ApiError("ERR_FORBIDDEN", "Cross-tenant access denied.")
        record = documents.attach_document(declaration_id, body)
        return ok(serialize_document(record), status=201)

    @app.post("/customs/documents/<document_id>/screen")
    @require_auth("DocReviewer")
    @with_lock
    def _screen(document_id):
        body = get_json_body()
        record = documents.screen_document(document_id, body)
        return ok(serialize_document(record))
