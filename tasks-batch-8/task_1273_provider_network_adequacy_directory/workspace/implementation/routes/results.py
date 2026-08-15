"""RegionSpecialtyResult read endpoints (immutable snapshot rows)."""

from flask import Blueprint

import db
import errors
import helpers
from middleware import require_roles, ALL_ROLES
from response import success_object, success_list

bp = Blueprint("results", __name__)

RESULT_STATUSES = {"COMPLIANT", "DEFICIENT", "EXCUSED"}


@bp.route("/network/results", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_results(user_id, role):
    limit, offset = helpers.get_pagination()
    evaluation_id = helpers.query_str("evaluation_id")
    region_id = helpers.query_str("region_id")
    overall_status = helpers.query_enum("overall_status", RESULT_STATUSES)
    items = list(db.results.values())
    if evaluation_id is not None:
        items = [r for r in items if r["evaluation_id"] == evaluation_id]
    if region_id is not None:
        items = [r for r in items if r["region_id"] == region_id]
    if overall_status is not None:
        items = [r for r in items if r["overall_status"] == overall_status]
    page, total = helpers.paginate(items, limit, offset)
    return success_list([helpers.ser_result(r) for r in page], limit, offset, total)


@bp.route("/network/results/<rid>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_result(user_id, role, rid):
    rec = db.results.get(rid)
    if rec is None:
        raise errors.err_invalid(f"result id does not exist: {rid}")
    return success_object(helpers.ser_result(rec))
