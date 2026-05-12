"""Direct review-task decide endpoint."""

from flask import Blueprint, request

from middleware import require_role
from response import success
from services import review
from services.serializers import serialize_review_task

bp = Blueprint("review_tasks", __name__)


@bp.post("/review-tasks/<task_id>/decide")
def decide(task_id):
    require_role("Reviewer", "LeadReviewer")
    record = review.decide_review_task(task_id, request.get_json(silent=True))
    return success(serialize_review_task(record), 200)
