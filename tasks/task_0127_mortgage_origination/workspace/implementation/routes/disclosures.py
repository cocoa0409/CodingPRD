"""Disclosure endpoints."""

from flask import Blueprint, g, request

import db
from config import (
    ROLE_ADMIN,
    ROLE_BORROWER,
    ROLE_COMPLIANCE_OFFICER,
    ROLE_LOAN_OFFICER,
)
from errors import ERR_FORBIDDEN_ROLE, raise_error
from middleware import require_role
from response import get_json_body, parse_pagination, success, success_list
from services import disclosures as svc, loan_applications as la_svc, serializers


disclosures_bp = Blueprint("disclosures", __name__)


@disclosures_bp.post("/loan-applications/<application_id>/disclosures")
def disclosure_create(application_id):
    require_role(ROLE_LOAN_OFFICER)
    application = la_svc.get_or_404(application_id)
    borrower = db.borrowers.get(application["borrower_id"])
    body = get_json_body()
    d = svc.issue(application, borrower, body)
    return success(serializers.disclosure(d), status_code=201)


@disclosures_bp.post(
    "/loan-applications/<application_id>/disclosures/<disclosure_id>/acknowledge"
)
def disclosure_acknowledge(application_id, disclosure_id):
    require_role(ROLE_BORROWER)
    application = la_svc.get_or_404(application_id)
    disclosure = svc.get_or_404(application_id, disclosure_id)
    body = get_json_body()
    d = svc.acknowledge(application, disclosure, g.user_id, body)
    return success(serializers.disclosure(d))


@disclosures_bp.get("/loan-applications/<application_id>/disclosures")
def disclosures_list(application_id):
    require_role(ROLE_LOAN_OFFICER, ROLE_COMPLIANCE_OFFICER, ROLE_ADMIN, ROLE_BORROWER)
    application = la_svc.get_or_404(application_id)

    # Borrower ownership check on the parent app.
    if g.role == ROLE_BORROWER and application["borrower_id"] != g.user_id:
        raise_error(
            ERR_FORBIDDEN_ROLE,
            "Borrower may only list disclosures on their own application.",
        )

    kind = request.args.get("kind")
    limit, offset = parse_pagination(request.args)
    items, total = svc.list_for_app(application_id, kind=kind, limit=limit, offset=offset)
    return success_list(
        [serializers.disclosure(i) for i in items],
        total_count=total,
        limit=limit,
        offset=offset,
    )
