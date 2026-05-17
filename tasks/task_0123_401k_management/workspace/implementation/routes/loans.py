"""Loan and LoanRepayment routes."""

from flask import Blueprint, request, g

from middleware import require_role, require_self_participant
from config import (
    ROLE_PLAN_ADMIN, ROLE_PAYROLL, ROLE_COMPLIANCE, ROLE_PARTICIPANT,
)
from services import loan_service, lookups, serializers
import response as resp
from utils import lock


loans_bp = Blueprint("loans", __name__)


@loans_bp.post("/plans/<plan_id>/participants/<participant_id>/loans")
def request_loan(plan_id, participant_id):
    require_role(ROLE_PARTICIPANT)
    with lock():
        plan, participant = lookups.resolve_participant_path(plan_id, participant_id)
        require_self_participant(participant_id)
        body = request.get_json(silent=True) or {}
        loan = loan_service.request_loan(plan, participant, body, g.user_id)
        view = serializers.loan_view(loan)
    return resp.success(view, status_code=201)


@loans_bp.get("/plans/<plan_id>/participants/<participant_id>/loans")
def list_loans(plan_id, participant_id):
    require_role(ROLE_PLAN_ADMIN, ROLE_COMPLIANCE, ROLE_PARTICIPANT)
    limit, offset = resp.parse_pagination(request.args)
    status_filter = request.args.get("status")
    with lock():
        plan, participant = lookups.resolve_participant_path(plan_id, participant_id)
        require_self_participant(participant_id)
        items, total = loan_service.list_loans(plan, participant, limit, offset, status_filter)
        views = [serializers.loan_view(l) for l in items]
    return resp.success_list(views, total, limit, offset)


@loans_bp.get("/plans/<plan_id>/participants/<participant_id>/loans/<loan_id>")
def get_loan(plan_id, participant_id, loan_id):
    require_role(ROLE_PLAN_ADMIN, ROLE_COMPLIANCE, ROLE_PARTICIPANT)
    with lock():
        plan, participant, loan = lookups.resolve_loan_path(plan_id, participant_id, loan_id)
        require_self_participant(participant_id)
        view = serializers.loan_view(loan)
    return resp.success(view)


@loans_bp.post("/plans/<plan_id>/participants/<participant_id>/loans/<loan_id>/approve")
def approve_loan(plan_id, participant_id, loan_id):
    require_role(ROLE_PLAN_ADMIN)
    with lock():
        plan, participant, loan = lookups.resolve_loan_path(plan_id, participant_id, loan_id)
        body = request.get_json(silent=True) or {}
        loan = loan_service.approve_loan(plan, participant, loan, body, g.user_id)
        view = serializers.loan_view(loan)
    return resp.success(view)


@loans_bp.post("/plans/<plan_id>/participants/<participant_id>/loans/<loan_id>/reject")
def reject_loan(plan_id, participant_id, loan_id):
    require_role(ROLE_PLAN_ADMIN)
    with lock():
        plan, participant, loan = lookups.resolve_loan_path(plan_id, participant_id, loan_id)
        body = request.get_json(silent=True) or {}
        loan = loan_service.reject_loan(plan, participant, loan, body)
        view = serializers.loan_view(loan)
    return resp.success(view)


@loans_bp.post("/plans/<plan_id>/participants/<participant_id>/loans/<loan_id>/repayments")
def post_repayment(plan_id, participant_id, loan_id):
    require_role(ROLE_PARTICIPANT, ROLE_PAYROLL)
    with lock():
        plan, participant, loan = lookups.resolve_loan_path(plan_id, participant_id, loan_id)
        require_self_participant(participant_id)
        body = request.get_json(silent=True) or {}
        repayment = loan_service.post_repayment(plan, participant, loan, body)
        view = serializers.loan_repayment_view(repayment)
    return resp.success(view, status_code=201)
