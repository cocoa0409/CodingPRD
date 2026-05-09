"""BudgetItem read endpoint (top-level)."""

from flask import Blueprint

from middleware import require_roles
from response import success
from services.budget_item import get_budget_item_or_404, serialize_item


bp = Blueprint("budget_items", __name__)


@bp.route("/budget-items/<item_id>", methods=["GET"])
@require_roles("Any")
def get_budget_item(item_id):
    bi = get_budget_item_or_404(item_id)
    return success(serialize_item(bi), 200)
