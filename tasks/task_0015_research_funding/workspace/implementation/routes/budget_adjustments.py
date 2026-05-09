"""BudgetAdjustment endpoints."""

from flask import Blueprint, g, request

from common import get_json_body, paginate_list, parse_pagination
from middleware import require_roles
from response import paginated, success
from services.budget_adjustment import (
    create_adjustment,
    dept_approve_adjustment,
    finance_approve_adjustment,
    get_adjustment_or_404,
    list_adjustments,
    reject_adjustment,
    serialize_adjustment,
    submit_adjustment,
)


bp = Blueprint("budget_adjustments", __name__)


@bp.route("/budget-adjustments", methods=["POST"])
@require_roles("PrincipalInvestigator")
def post_adjustment():
    body = get_json_body()
    a = create_adjustment(g.user_id, body)
    return success(serialize_adjustment(a), 201)


@bp.route("/budget-adjustments", methods=["GET"])
@require_roles("Any")
def list_adjustments_view():
    limit, offset = parse_pagination()
    project_id = request.args.get("project_id")
    status = request.args.get("status")
    items = list_adjustments(project_id=project_id, status=status)
    page, total = paginate_list(items, limit, offset)
    return paginated([serialize_adjustment(a) for a in page], limit, offset, total)


@bp.route("/budget-adjustments/<adjustment_id>", methods=["GET"])
@require_roles("Any")
def get_adjustment(adjustment_id):
    a = get_adjustment_or_404(adjustment_id)
    return success(serialize_adjustment(a), 200)


@bp.route("/budget-adjustments/<adjustment_id>/submit", methods=["POST"])
@require_roles("PrincipalInvestigator")
def post_submit(adjustment_id):
    a = submit_adjustment(adjustment_id, g.user_id)
    return success(serialize_adjustment(a), 200)


@bp.route("/budget-adjustments/<adjustment_id>/dept-approve", methods=["POST"])
@require_roles("DepartmentApprover")
def post_dept_approve(adjustment_id):
    a = dept_approve_adjustment(adjustment_id, g.user_id)
    return success(serialize_adjustment(a), 200)


@bp.route("/budget-adjustments/<adjustment_id>/finance-approve", methods=["POST"])
@require_roles("FinanceOfficer")
def post_finance_approve(adjustment_id):
    a = finance_approve_adjustment(adjustment_id, g.user_id)
    return success(serialize_adjustment(a), 200)


@bp.route("/budget-adjustments/<adjustment_id>/reject", methods=["POST"])
@require_roles("DepartmentApprover", "FinanceOfficer")
def post_reject(adjustment_id):
    body = get_json_body()
    a = reject_adjustment(adjustment_id, g.user_id, g.user_role, body)
    return success(serialize_adjustment(a), 200)
