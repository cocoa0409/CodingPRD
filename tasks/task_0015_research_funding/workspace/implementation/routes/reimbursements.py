"""Reimbursement endpoints."""

from flask import Blueprint, g, request

from common import get_json_body, paginate_list, parse_pagination
from middleware import require_roles
from response import paginated, success
from services.reimbursement import (
    create_reimbursement,
    dept_approve_reimbursement,
    finance_approve_reimbursement,
    get_reimbursement_or_404,
    list_reimbursements,
    mark_paid,
    pi_approve_reimbursement,
    reject_reimbursement,
    rework_reimbursement,
    serialize_reimbursement,
    submit_reimbursement,
)


bp = Blueprint("reimbursements", __name__)


@bp.route("/reimbursements", methods=["POST"])
@require_roles("PrincipalInvestigator")
def post_reimbursement():
    body = get_json_body()
    r = create_reimbursement(g.user_id, body)
    return success(serialize_reimbursement(r), 201)


@bp.route("/reimbursements", methods=["GET"])
@require_roles("Any")
def get_reimbursements():
    limit, offset = parse_pagination()
    project_id = request.args.get("project_id")
    status = request.args.get("status")
    items = list_reimbursements(project_id=project_id, status=status)
    page, total = paginate_list(items, limit, offset)
    return paginated([serialize_reimbursement(r) for r in page], limit, offset, total)


@bp.route("/reimbursements/<reimbursement_id>", methods=["GET"])
@require_roles("Any")
def get_reimbursement(reimbursement_id):
    r = get_reimbursement_or_404(reimbursement_id)
    return success(serialize_reimbursement(r), 200)


@bp.route("/reimbursements/<reimbursement_id>/submit", methods=["POST"])
@require_roles("PrincipalInvestigator")
def post_submit_reimbursement(reimbursement_id):
    r = submit_reimbursement(reimbursement_id, g.user_id)
    return success(serialize_reimbursement(r), 200)


@bp.route("/reimbursements/<reimbursement_id>/pi-approve", methods=["POST"])
@require_roles("PrincipalInvestigator")
def post_pi_approve(reimbursement_id):
    r = pi_approve_reimbursement(reimbursement_id, g.user_id)
    return success(serialize_reimbursement(r), 200)


@bp.route("/reimbursements/<reimbursement_id>/dept-approve", methods=["POST"])
@require_roles("DepartmentApprover")
def post_dept_approve_reimb(reimbursement_id):
    r = dept_approve_reimbursement(reimbursement_id, g.user_id)
    return success(serialize_reimbursement(r), 200)


@bp.route("/reimbursements/<reimbursement_id>/finance-approve", methods=["POST"])
@require_roles("FinanceOfficer")
def post_finance_approve_reimb(reimbursement_id):
    r = finance_approve_reimbursement(reimbursement_id, g.user_id)
    return success(serialize_reimbursement(r), 200)


@bp.route("/reimbursements/<reimbursement_id>/mark-paid", methods=["POST"])
@require_roles("FinanceOfficer")
def post_mark_paid(reimbursement_id):
    r = mark_paid(reimbursement_id, g.user_id)
    return success(serialize_reimbursement(r), 200)


@bp.route("/reimbursements/<reimbursement_id>/reject", methods=["POST"])
@require_roles("DepartmentApprover", "FinanceOfficer")
def post_reject_reimb(reimbursement_id):
    body = get_json_body()
    r = reject_reimbursement(reimbursement_id, g.user_id, g.user_role, body)
    return success(serialize_reimbursement(r), 200)


@bp.route("/reimbursements/<reimbursement_id>/rework", methods=["POST"])
@require_roles("PrincipalInvestigator")
def post_rework_reimb(reimbursement_id):
    r = rework_reimbursement(reimbursement_id, g.user_id)
    return success(serialize_reimbursement(r), 200)
