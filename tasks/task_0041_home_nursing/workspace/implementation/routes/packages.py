"""Routes for /packages."""
from flask import Blueprint, g

from db import public
from middleware import require_auth, get_pagination, get_json_body
from response import success, success_list
from services import package as svc


bp = Blueprint("packages", __name__)


@bp.route("/packages", methods=["POST"])
@require_auth(roles={"PlatformAdmin"})
def create_pkg():
    body = get_json_body()
    pkg = svc.create_package(body)
    return success(public(pkg), status=201)


@bp.route("/packages", methods=["GET"])
@require_auth(roles={"Patient", "PlatformAdmin"})
def list_pkg():
    limit, offset = get_pagination()
    if g.user_role == "Patient":
        rows, total = svc.list_packages_for_patient(g.user_id, limit, offset)
    else:
        rows, total = svc.list_all_packages(limit, offset)
    return success_list([public(r) for r in rows], limit, offset, total)
