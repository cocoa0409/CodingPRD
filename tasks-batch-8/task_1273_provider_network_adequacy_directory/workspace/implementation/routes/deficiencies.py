"""DeficiencyRecord read endpoints (created only by the finalize cascade)."""

from flask import Blueprint

import db
import errors
import helpers
from middleware import require_roles, ALL_ROLES
from response import success_object, success_list

bp = Blueprint("deficiencies", __name__)

DEFICIENCY_STATUSES = {"OPEN", "EXCUSED", "CLOSED"}


@bp.route("/network/deficiencies", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_deficiencies(user_id, role):
    limit, offset = helpers.get_pagination()
    evaluation_id = helpers.query_str("evaluation_id")
    region_id = helpers.query_str("region_id")
    status = helpers.query_enum("status", DEFICIENCY_STATUSES)
    items = list(db.deficiencies.values())
    if evaluation_id is not None:
        items = [d for d in items if d["evaluation_id"] == evaluation_id]
    if region_id is not None:
        items = [d for d in items if d["region_id"] == region_id]
    if status is not None:
        items = [d for d in items if d["status"] == status]
    page, total = helpers.paginate(items, limit, offset)
    return success_list([helpers.ser_deficiency(d) for d in page], limit, offset, total)


@bp.route("/network/deficiencies/<did>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_deficiency(user_id, role, did):
    rec = db.deficiencies.get(did)
    if rec is None:
        raise errors.err_deficiency_not_found()
    return success_object(helpers.ser_deficiency(rec))
