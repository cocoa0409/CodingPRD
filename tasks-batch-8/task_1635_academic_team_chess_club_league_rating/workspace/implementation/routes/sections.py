from flask import Blueprint, request

from db import store
from errors import state_error
from middleware import require_roles, ALL_ROLES
from response import success_object, success_array, paginate
from services.common import get_or_404, touch
from services.serializers import section_json
from validate import get_body

bp = Blueprint("sections", __name__)

READ = ALL_ROLES


@bp.route("/api/sections", methods=["GET"])
@require_roles(*READ)
def list_sections():
    items = list(store.sections.values())
    tid = request.args.get("tournament_id")
    if tid is not None:
        items = [s for s in items if s["tournament_id"] == tid]
    status = request.args.get("status")
    if status is not None:
        items = [s for s in items if s["status"] == status]
    page, limit, offset, total = paginate(items, request.args)
    return success_array([section_json(s) for s in page], 200, paginated=True,
                         limit=limit, offset=offset, total_count=total)


@bp.route("/api/sections/<sectionId>", methods=["GET"])
@require_roles(*READ)
def get_section(sectionId):
    s = get_or_404(store.sections, sectionId, "section")
    return success_object(section_json(s), 200)


@bp.route("/api/sections/<sectionId>/lock", methods=["POST"])
@require_roles("FederationAdmin")
def lock_section(sectionId):
    get_body()
    s = get_or_404(store.sections, sectionId, "section")
    if s["status"] != "OPEN":
        raise state_error("ERR_SECTION_INVALID_STATE", "Section is not OPEN")
    s["status"] = "LOCKED"
    touch(s)
    return success_object(section_json(s), 200)


@bp.route("/api/sections/<sectionId>/unlock", methods=["POST"])
@require_roles("FederationAdmin")
def unlock_section(sectionId):
    get_body()
    s = get_or_404(store.sections, sectionId, "section")
    if s["status"] != "LOCKED":
        raise state_error("ERR_SECTION_INVALID_STATE", "Section is not LOCKED")
    s["status"] = "OPEN"
    touch(s)
    return success_object(section_json(s), 200)
