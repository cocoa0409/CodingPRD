"""LoanApplication endpoints (lifecycle + read/list)."""

from flask import Blueprint, g, request

from config import (
    ROLE_ADMIN,
    ROLE_BORROWER,
    ROLE_COMPLIANCE_OFFICER,
    ROLE_LOAN_OFFICER,
)
from errors import ERR_FORBIDDEN_ROLE, raise_error
from middleware import require_role
from response import get_json_body, parse_pagination, success, success_list
from services import loan_applications as svc, serializers


loan_applications_bp = Blueprint("loan_applications", __name__)


def _ownership_filter_for_borrower(app: dict) -> None:
    if g.role == ROLE_BORROWER and app["borrower_id"] != g.user_id:
        raise_error(ERR_FORBIDDEN_ROLE, "Borrower may only read their own application.")


@loan_applications_bp.post("/loan-applications")
def create_application():
    require_role(ROLE_LOAN_OFFICER, ROLE_ADMIN)
    body = get_json_body()
    app = svc.create(body)
    return success(serializers.loan_application(app), status_code=201)


@loan_applications_bp.get("/loan-applications/<application_id>")
def get_application(application_id):
    require_role(ROLE_LOAN_OFFICER, ROLE_COMPLIANCE_OFFICER, ROLE_ADMIN, ROLE_BORROWER)
    app = svc.get_or_404(application_id)
    _ownership_filter_for_borrower(app)
    return success(serializers.loan_application(app))


@loan_applications_bp.get("/loan-applications")
def list_applications():
    require_role(ROLE_LOAN_OFFICER, ROLE_COMPLIANCE_OFFICER, ROLE_ADMIN)
    limit, offset = parse_pagination(request.args)
    items, total = svc.list_paginated(
        status=request.args.get("status"),
        borrower_id=request.args.get("borrower_id"),
        limit=limit,
        offset=offset,
    )
    return success_list(
        [serializers.loan_application(i) for i in items],
        total_count=total,
        limit=limit,
        offset=offset,
    )


@loan_applications_bp.post("/loan-applications/<application_id>/pre-qualify")
def pre_qualify(application_id):
    require_role(ROLE_LOAN_OFFICER)
    body = get_json_body()
    app = svc.pre_qualify(application_id, body)
    return success(serializers.loan_application(app))


@loan_applications_bp.post("/loan-applications/<application_id>/submit-underwriting")
def submit_underwriting(application_id):
    require_role(ROLE_LOAN_OFFICER)
    body = get_json_body()
    app = svc.submit_underwriting(application_id, g.user_id, body)
    return success(serializers.loan_application(app))


@loan_applications_bp.post("/loan-applications/<application_id>/underwrite-decision")
def underwrite_decision(application_id):
    require_role(ROLE_LOAN_OFFICER)
    body = get_json_body()
    app = svc.underwrite_decision(application_id, g.user_id, body)
    return success(serializers.loan_application(app))


@loan_applications_bp.post("/loan-applications/<application_id>/clear-to-close")
def clear_to_close(application_id):
    require_role(ROLE_LOAN_OFFICER)
    body = get_json_body()
    app = svc.clear_to_close(application_id, g.user_id, body)
    return success(serializers.loan_application(app))


@loan_applications_bp.post("/loan-applications/<application_id>/close")
def close(application_id):
    require_role(ROLE_LOAN_OFFICER)
    body = get_json_body()
    app = svc.close(application_id, body)
    return success(serializers.loan_application(app))


@loan_applications_bp.post("/loan-applications/<application_id>/withdraw")
def withdraw(application_id):
    require_role(ROLE_LOAN_OFFICER)
    body = get_json_body()
    app = svc.withdraw(application_id, body)
    return success(serializers.loan_application(app))
