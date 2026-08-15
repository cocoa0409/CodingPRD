"""Production lines (PRD §3.3). A new line has no mold, has been verified
clean for no allergens, and starts AVAILABLE."""
from flask import Blueprint, request

from db import new_id, stamp_new, store
from errors import ApiError
from middleware import ALL_ROLES, auth, body, paginate, require_fields
from response import success_list, success_object
from serializers import changeover_json, line_json

lines_bp = Blueprint("lines", __name__)


def get_line_or_404(lid):
    line = store.production_lines.get(lid)
    if line is None:
        raise ApiError("ERR_NOT_FOUND", "Production line not found: %s" % lid)
    return line


@lines_bp.route("/production-lines", methods=["POST"])
def create_line():
    auth(("ProductionPlanner",))
    b = body()
    require_fields(b, ["name"])
    if not isinstance(b["name"], str) or not b["name"]:
        raise ApiError("ERR_INVALID_REQUEST", "name is required and must be a non-empty string.")
    line = {
        "id": new_id(),
        "name": b["name"],
        "current_mold_id": None,
        "cleared_allergens": [],
        "status": "AVAILABLE",
    }
    stamp_new(line)
    store.production_lines[line["id"]] = line
    return success_object(line_json(line), 201)


@lines_bp.route("/production-lines", methods=["GET"])
def list_lines():
    auth(ALL_ROLES)
    items = list(store.production_lines.values())
    f = request.args.get("current_mold_id")
    if f is not None:
        items = [l for l in items if l["current_mold_id"] == f]
    items.sort(key=lambda l: l["created_at"])
    page, meta = paginate(items)
    return success_list([line_json(l) for l in page], meta)


@lines_bp.route("/production-lines/<lid>", methods=["GET"])
def get_line(lid):
    auth(ALL_ROLES)
    return success_object(line_json(get_line_or_404(lid)))


@lines_bp.route("/production-lines/<lid>/changeovers", methods=["GET"])
def list_line_changeovers(lid):
    auth(ALL_ROLES)
    line = get_line_or_404(lid)
    items = [c for c in store.changeovers.values() if c["line_id"] == line["id"]]
    items.sort(key=lambda c: c["created_at"])
    page, meta = paginate(items)
    return success_list([changeover_json(c) for c in page], meta)
