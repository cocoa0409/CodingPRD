"""Style endpoints (PRD §3.1, §3.2)."""

from flask import Blueprint, request

from db import store
from middleware import require_roles, ALL_ROLES, ROLE_MERCHANDISER, ROLE_PLANT_MANAGER
from response import success_object
from util import get_body, req_str, opt_str, req_list, req_bool, req_enum
from errors import invalid_request, invalid_state, not_certifiable
from services.core import base_record, touch, public, get_style
from routes.common import list_response, active_filters

bp = Blueprint("styles", __name__)

CONTENT_CLAIMS = {"NONE", "MADE_IN_USA"}


@bp.route("/styles", methods=["POST"])
def create_style():
    _, user_id = require_roles([ROLE_MERCHANDISER])
    body = get_body()
    style_code = req_str(body, "style_code")
    description = opt_str(body, "description")
    base_size = req_str(body, "base_size")
    size_run = req_list(body, "size_run")
    declared = req_bool(body, "declared_fabric_domestic")
    target = req_enum(body, "target_content_claim", CONTENT_CLAIMS)
    if not size_run or any(not isinstance(s, str) or not s for s in size_run):
        raise invalid_request("size_run must be a non-empty array of size labels")
    if len(set(size_run)) != len(size_run):
        raise invalid_request("size_run must not contain duplicate labels")
    if base_size not in size_run:
        raise invalid_request("base_size must be a member of size_run")
    if any(s["style_code"] == style_code for s in store.styles.values()):
        raise invalid_request("style_code must be unique across all styles")

    rec = base_record()
    rec.update({
        "style_code": style_code,
        "description": description,
        "base_size": base_size,
        "size_run": list(size_run),
        "declared_fabric_domestic": declared,
        "target_content_claim": target,
        "status": "DRAFT",
        "active_tech_pack_id": None,
        "domestic_content_pct_cost": None,
        "domestic_component_ratio": None,
        "content_qualification": "UNDETERMINED",
        "certification_status": "UNCERTIFIED",
        "certified_by_user_id": None,
        "created_by_user_id": user_id,
    })
    store.styles[rec["id"]] = rec
    return success_object(public(rec), status=201)


@bp.route("/styles/<style_id>", methods=["GET"])
def get_style_endpoint(style_id):
    require_roles(ALL_ROLES)
    return success_object(public(get_style(style_id)))


@bp.route("/styles", methods=["GET"])
def list_styles():
    require_roles(ALL_ROLES)
    filters = active_filters([
        ("active_tech_pack_id", request.args.get("active_tech_pack_id")),
    ])
    return list_response(store.styles.values(), filters)


@bp.route("/styles/<style_id>/certify-content-claim", methods=["POST"])
def certify_content_claim(style_id):
    _, user_id = require_roles([ROLE_PLANT_MANAGER])
    get_body()  # tolerate an optional empty JSON body
    style = get_style(style_id)
    if style["certification_status"] not in ("UNCERTIFIED", "REVOKED"):
        raise invalid_state(
            "certification_status must be UNCERTIFIED or REVOKED to certify")
    if style["content_qualification"] != "QUALIFIED_STRICT":
        raise not_certifiable(
            "content_qualification must be QUALIFIED_STRICT to certify")
    style["certification_status"] = "CERTIFIED"
    style["certified_by_user_id"] = user_id
    touch(style)
    return success_object(public(style))
