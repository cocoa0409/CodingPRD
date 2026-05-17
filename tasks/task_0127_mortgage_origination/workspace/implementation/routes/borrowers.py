"""Borrower endpoints."""

from flask import Blueprint, g

from config import (
    ROLE_ADMIN,
    ROLE_BORROWER,
    ROLE_COMPLIANCE_OFFICER,
    ROLE_LOAN_OFFICER,
)
from errors import ERR_APPLICATION_NOT_FOUND, ERR_FORBIDDEN_ROLE, raise_error
from middleware import require_role
from response import get_json_body, success
from services import borrowers as svc, serializers


borrowers_bp = Blueprint("borrowers", __name__)


@borrowers_bp.post("/borrowers")
def create_borrower():
    require_role(ROLE_LOAN_OFFICER, ROLE_ADMIN)
    body = get_json_body()
    b = svc.create(body)
    return success(serializers.borrower(b), status_code=201)


@borrowers_bp.get("/borrowers/<borrower_id>")
def get_borrower(borrower_id):
    require_role(ROLE_LOAN_OFFICER, ROLE_COMPLIANCE_OFFICER, ROLE_ADMIN, ROLE_BORROWER)
    b = svc.get(borrower_id)
    if b is None:
        # 404 — borrowers are top-level resources; PRD doesn't define a specific err id for
        # borrower-not-found, so use ERR_APPLICATION_NOT_FOUND? No — the closest catalog match
        # is ERR_RESOURCE_NOT_FOUND. Use it to signal a missing nested-style top-level resource.
        from errors import ERR_RESOURCE_NOT_FOUND
        raise_error(ERR_RESOURCE_NOT_FOUND, "Borrower not found.")

    # Borrower role may only read their own borrower record.
    if g.role == ROLE_BORROWER and g.user_id != b["id"]:
        raise_error(ERR_FORBIDDEN_ROLE, "Borrower may only read their own record.")

    return success(serializers.borrower(b))
