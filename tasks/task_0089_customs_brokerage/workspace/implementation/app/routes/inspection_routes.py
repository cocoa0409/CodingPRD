"""InspectionCase routes."""
from __future__ import annotations

from flask import Flask

from ..auth import current_actor, require_auth
from ..errors import ApiError
from ..services import inspection
from ..services.serializers import serialize_inspection_case
from ..store import get_store
from ._helpers import get_json_body, ok, with_lock


def register(app: Flask) -> None:
    @app.post("/customs/inspection-cases")
    @require_auth("InspectionOfficer", "BrokerOps")
    @with_lock
    def _create_case():
        body = get_json_body()
        record = inspection.create_inspection_case(body)
        return ok(serialize_inspection_case(record), status=201)

    @app.get("/customs/inspection-cases/<inspection_case_id>")
    @require_auth(
        "InspectionOfficer",
        "BrokerOps",
        "DeclarationOfficer",
        "ClientUser",
        "SystemAdmin",
    )
    @with_lock
    def _get_case(inspection_case_id):
        record = inspection.get_inspection_case(inspection_case_id)
        user_id, role = current_actor()
        if role == "ClientUser":
            store = get_store()
            filing = store.filings.get(record.get("filing_id"))
            declaration = store.declarations.get(filing.get("declaration_id")) if filing else None
            agreement = store.agreements.get(declaration.get("agreement_id")) if declaration else None
            if not agreement or agreement.get("client_id") != user_id:
                raise ApiError("ERR_FORBIDDEN", "Cross-tenant access denied.")
        return ok(serialize_inspection_case(record))

    @app.post("/customs/inspection-cases/<inspection_case_id>/provide-sample")
    @require_auth("ClientUser", "BrokerOps")
    @with_lock
    def _provide_sample(inspection_case_id):
        body = get_json_body()
        record = inspection.provide_sample(inspection_case_id, body)
        return ok(serialize_inspection_case(record))

    @app.post("/customs/inspection-cases/<inspection_case_id>/record-outcome")
    @require_auth("InspectionOfficer")
    @with_lock
    def _record_outcome(inspection_case_id):
        body = get_json_body()
        record = inspection.record_outcome(inspection_case_id, body)
        return ok(serialize_inspection_case(record))
