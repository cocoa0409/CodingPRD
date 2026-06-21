"""AwardLineItem read endpoints — PRD §3.6."""
from flask import Blueprint

from db import STORE
from middleware import get_auth, require_roles
from response import success
from services.common import lookup, list_response
from services.models import serialize

bp = Blueprint("award_line_items", __name__)

ALL_ROLES = ["ProgramAdmin", "Caseworker", "Inspector"]


@bp.route("/disaster-relief/award-line-items", methods=["GET"])
def list_line_items():
    _uid, role = get_auth()
    require_roles(role, ALL_ROLES)
    with STORE.lock:
        data, pg = list_response(
            STORE.award_line_items.values(),
            {"ihp_case_id": "ihp_case_id", "category": "category", "li_status": "li_status"},
        )
    return success(data, pagination=pg)


@bp.route("/disaster-relief/award-line-items/<lid>", methods=["GET"])
def get_line_item(lid):
    _uid, role = get_auth()
    require_roles(role, ALL_ROLES)
    with STORE.lock:
        li = lookup("award_line_items", lid)
        return success(serialize(li))
