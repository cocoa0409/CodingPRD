"""Schools (PRD §3.1 approve cascade produces them; read-only endpoints here)."""
from flask import Blueprint

import db
from middleware import ALL_ROLES, require_roles
from response import success_object
from routes.common import filter_eq, get_or_404, paginate

bp = Blueprint("schools", __name__)


@bp.get("/authorizer/schools")
def list_schools():
    require_roles(ALL_ROLES)
    from flask import request
    records = db.all_records("schools")
    records = filter_eq(records, "status", request.args.get("status"))
    return paginate(records)


@bp.get("/authorizer/schools/<id>")
def get_school(id):
    require_roles(ALL_ROLES)
    return success_object(get_or_404("schools", id))
