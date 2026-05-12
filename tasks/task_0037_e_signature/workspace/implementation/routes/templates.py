"""Template + TemplateVersion endpoints."""

from flask import Blueprint, g, request

from db import LOCK
from middleware import require_roles
from response import success_object, success_array
from services import templates as svc
from services.serializers import serialize_template, serialize_template_version
from ._helpers import parse_pagination, get_json_body


bp = Blueprint("templates", __name__)


# ---- Templates -------------------------------------------------------------

@bp.route("/templates", methods=["POST"])
@require_roles("TemplateAdmin")
def post_template():
    body = get_json_body()
    with LOCK:
        t = svc.create_template(body)
    return success_object(serialize_template(t), 201)


@bp.route("/templates", methods=["GET"])
@require_roles("TemplateAdmin", "ContractInitiator", "EvidenceArchivist", "PlatformAdmin")
def list_templates_route():
    limit, offset = parse_pagination()
    category = request.args.get("category")
    owner = request.args.get("owner_org_id")
    with LOCK:
        rows, total = svc.list_templates(category, owner, limit, offset)
        data = [serialize_template(r) for r in rows]
    return success_array(data, limit, offset, total)


@bp.route("/templates/<tid>", methods=["GET"])
@require_roles("TemplateAdmin", "ContractInitiator", "EvidenceArchivist", "PlatformAdmin")
def get_template_route(tid):
    with LOCK:
        t = svc.get_template(tid)
    return success_object(serialize_template(t))


@bp.route("/templates/<tid>", methods=["PATCH"])
@require_roles("TemplateAdmin")
def patch_template_route(tid):
    body = get_json_body()
    with LOCK:
        t = svc.patch_template(tid, body)
    return success_object(serialize_template(t))


# ---- TemplateVersions ------------------------------------------------------

@bp.route("/templates/<tid>/versions", methods=["POST"])
@require_roles("TemplateAdmin")
def post_template_version(tid):
    body = get_json_body()
    with LOCK:
        v = svc.create_template_version(tid, body)
    return success_object(serialize_template_version(v), 201)


@bp.route("/templates/<tid>/versions", methods=["GET"])
@require_roles("TemplateAdmin", "ContractInitiator", "EvidenceArchivist", "PlatformAdmin")
def list_template_versions_route(tid):
    limit, offset = parse_pagination()
    status = request.args.get("status")
    with LOCK:
        rows, total = svc.list_template_versions(tid, status, limit, offset)
        data = [serialize_template_version(r) for r in rows]
    return success_array(data, limit, offset, total)


@bp.route("/templates/<tid>/versions/<vid>", methods=["GET"])
@require_roles("TemplateAdmin", "ContractInitiator", "EvidenceArchivist", "PlatformAdmin")
def get_template_version_route(tid, vid):
    with LOCK:
        v = svc.get_template_version(tid, vid)
    return success_object(serialize_template_version(v))


@bp.route("/templates/<tid>/versions/<vid>", methods=["PATCH"])
@require_roles("TemplateAdmin")
def patch_template_version_route(tid, vid):
    body = get_json_body()
    with LOCK:
        v = svc.patch_template_version(tid, vid, body)
    return success_object(serialize_template_version(v))


@bp.route("/templates/<tid>/versions/<vid>/publish", methods=["POST"])
@require_roles("TemplateAdmin")
def publish_template_version_route(tid, vid):
    with LOCK:
        v = svc.publish_template_version(
            tid, vid, actor_user_id=g.user_id, actor_role=g.role
        )
    return success_object(serialize_template_version(v))


@bp.route("/templates/<tid>/versions/<vid>/deprecate", methods=["POST"])
@require_roles("TemplateAdmin")
def deprecate_template_version_route(tid, vid):
    with LOCK:
        v = svc.deprecate_template_version(
            tid, vid, actor_user_id=g.user_id, actor_role=g.role
        )
    return success_object(serialize_template_version(v))
