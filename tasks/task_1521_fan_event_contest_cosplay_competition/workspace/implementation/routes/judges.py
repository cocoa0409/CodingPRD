"""Judge routes."""

from flask import Blueprint

from db import DB, new_id, now_ts
from errors import err_not_found, err_validation
from middleware import require_roles
from response import success
from services.helpers import body_json, req_str, req_list
from services.serializers import judge_view

bp = Blueprint("judges", __name__)


@bp.route("/judges", methods=["POST"])
def create_judge():
    require_roles("ContestLead")
    body = body_json()
    contest_id = req_str(body, "contest_id")
    display_name = req_str(body, "display_name")
    category_ids = req_list(body, "category_ids", allow_empty=False)

    linked = body.get("linked_contestant_id", None)
    if linked is not None and not isinstance(linked, str):
        raise err_validation("linked_contestant_id must be a string or null")

    contest = DB.contest_events.get(contest_id)
    if contest is None:
        raise err_not_found("ContestEvent not found")
    for cat_id in category_ids:
        if cat_id not in DB.categories:
            raise err_not_found(f"Category {cat_id} not found")
    if linked is not None and linked not in DB.contestants:
        raise err_not_found("Linked contestant not found")

    ts = now_ts()
    judge = {
        "id": new_id(),
        "contest_id": contest_id,
        "display_name": display_name,
        "category_ids": list(category_ids),
        "linked_contestant_id": linked,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    DB.judges[judge["id"]] = judge
    return success(judge_view(judge), status=201)
