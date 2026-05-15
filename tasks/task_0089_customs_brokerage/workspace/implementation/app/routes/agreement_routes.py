"""CommissionAgreement routes."""
from __future__ import annotations

from flask import Flask

from ..auth import require_auth, current_actor
from ..errors import ApiError
from ..services import agreements
from ..services.serializers import serialize_agreement
from ._helpers import get_json_body, ok, with_lock


def register(app: Flask) -> None:
    @app.post("/customs/agreements")
    @require_auth("BrokerOps")
    @with_lock
    def _create_agreement():
        body = get_json_body()
        record = agreements.create_agreement(body)
        return ok(serialize_agreement(record), status=201)

    @app.get("/customs/agreements/<agreement_id>")
    @require_auth(
        "BrokerOps",
        "DeclarationOfficer",
        "FilingOfficer",
        "SettlementOfficer",
        "ClientUser",
        "SystemAdmin",
    )
    @with_lock
    def _get_agreement(agreement_id):
        record = agreements.get_agreement(agreement_id)
        user_id, role = current_actor()
        if role == "ClientUser" and record.get("client_id") != user_id:
            raise ApiError("ERR_FORBIDDEN", "ClientUser may only read their own agreements.")
        return ok(serialize_agreement(record))

    @app.post("/customs/agreements/<agreement_id>/request-signature")
    @require_auth("BrokerOps")
    @with_lock
    def _request_signature(agreement_id):
        body = get_json_body()
        record = agreements.request_signature(agreement_id, body)
        return ok(serialize_agreement(record))

    @app.post("/customs/agreements/<agreement_id>/sign")
    @require_auth("ClientUser")
    @with_lock
    def _sign(agreement_id):
        body = get_json_body()
        record = agreements.sign_agreement(agreement_id, body)
        return ok(serialize_agreement(record))

    @app.post("/customs/agreements/<agreement_id>/terminate")
    @require_auth("BrokerOps")
    @with_lock
    def _terminate(agreement_id):
        body = get_json_body()
        record = agreements.terminate_agreement(agreement_id, body)
        return ok(serialize_agreement(record))
