"""ProjectTemplate routes."""
from flask import Blueprint, request

import db
from middleware import require_roles
from response import success, list_response, parse_pagination
from services.lookup import get_template


bp = Blueprint("templates", __name__)


@bp.post("/project-templates")
def create_template():
    require_roles("Auditor")
    body = request.get_json(silent=True) or {}
    template = {
        "name": body.get("name"),
        "scale": body.get("scale"),
        "default_milestones": body.get("default_milestones") or [],
    }
    template["id"] = db.gen_id()
    template["created_at"] = db.now_iso()
    db.templates[template["id"]] = template
    return success(template, status=201)


@bp.get("/project-templates")
def list_templates():
    require_roles("Planner", "Auditor")
    limit, offset = parse_pagination(request.args)
    scale_q = request.args.get("scale")
    items = list(db.templates.values())
    if scale_q:
        items = [t for t in items if t.get("scale") == scale_q]
    items.sort(key=lambda t: t["created_at"])
    return list_response(items, limit, offset)


@bp.get("/project-templates/<template_id>")
def get_template_route(template_id):
    require_roles("Planner", "Auditor")
    t = get_template(template_id)
    return success(t)
