from flask import Blueprint, request

from db import store
from errors import err
from middleware import require_roles
from response import success
from services.common import serialize_project_template, stamp_immutable_create
from services.validation import (DOMAINS, PRICING_MODES, require_enum, require_int,
                                  require_string)

bp = Blueprint("project_templates", __name__)


@bp.post("/project-templates")
@require_roles("ProjectManager")
def create_template():
    body = request.get_json(silent=True) or {}
    name = require_string(body, "name", min_len=1, max_len=200)
    default_domain = require_enum(body, "default_domain", DOMAINS)
    default_unit_pricing_mode = require_enum(body, "default_unit_pricing_mode", PRICING_MODES)
    default_base_unit_price_cents = require_int(body, "default_base_unit_price_cents", min_val=1)
    default_package_size_segments = require_int(body, "default_package_size_segments", min_val=1, max_val=500)
    t = {
        "name": name,
        "default_domain": default_domain,
        "default_unit_pricing_mode": default_unit_pricing_mode,
        "default_base_unit_price_cents": default_base_unit_price_cents,
        "default_package_size_segments": default_package_size_segments,
    }
    stamp_immutable_create(t)
    store.project_templates[t["id"]] = t
    return success(serialize_project_template(t), status=201)


@bp.get("/project-templates/<id>")
@require_roles("ProjectManager")
def get_template(id):
    t = store.project_templates.get(id)
    if not t:
        raise err("ERR_NOT_FOUND", "project template not found")
    return success(serialize_project_template(t))
