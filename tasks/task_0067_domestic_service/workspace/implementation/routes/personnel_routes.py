"""Personnel + SkillCertification routes."""
from flask import Blueprint, request

from db import store
from errors import ERR_NOT_FOUND, ERR_VALIDATION_ERROR, raise_error
from response import success_response
from middleware import require_roles
from services import personnel as svc
from services.utils import parse_pagination, paginate


bp = Blueprint("personnel", __name__)


@bp.route("/dsd/personnel", methods=["POST"])
def create_personnel():
    require_roles({"PlatformOperator"})
    body = request.get_json(silent=True) or {}
    p = svc.create_personnel(body)
    return success_response(p, http_status=201)


@bp.route("/dsd/personnel/<pid>", methods=["GET"])
def get_personnel(pid):
    require_roles({"PlatformOperator", "ServicePersonnel", "Customer"})
    if pid not in store.personnel:
        raise_error(ERR_NOT_FOUND, "Personnel not found")
    return success_response(store.personnel[pid])


@bp.route("/dsd/personnel", methods=["GET"])
def list_personnel():
    require_roles({"PlatformOperator"})
    limit, offset = parse_pagination()
    status_f = request.args.get("status")
    skill_tag_f = request.args.get("skill_tag")
    tier_f = request.args.get("tier")
    items = list(store.personnel.values())
    if status_f:
        items = [x for x in items if x["status"] == status_f]
    if skill_tag_f:
        items = [x for x in items if skill_tag_f in x.get("skill_tags", [])]
    if tier_f:
        items = [x for x in items if x["tier"] == tier_f]
    window, page = paginate(items, limit, offset)
    return success_response(window, pagination=page)


@bp.route("/dsd/personnel/<pid>/verify-identity", methods=["POST"])
def verify_identity(pid):
    require_roles({"PlatformOperator"})
    if pid not in store.personnel:
        raise_error(ERR_NOT_FOUND, "Personnel not found")
    p = svc.verify_identity(pid)
    return success_response(p)


@bp.route("/dsd/personnel/<pid>/activate", methods=["POST"])
def activate(pid):
    require_roles({"PlatformOperator"})
    if pid not in store.personnel:
        raise_error(ERR_NOT_FOUND, "Personnel not found")
    p = svc.activate_personnel(pid)
    return success_response(p)


@bp.route("/dsd/personnel/<pid>/suspend", methods=["POST"])
def suspend(pid):
    require_roles({"PlatformOperator"})
    if pid not in store.personnel:
        raise_error(ERR_NOT_FOUND, "Personnel not found")
    p = svc.suspend_personnel(pid)
    return success_response(p)


@bp.route("/dsd/personnel/<pid>/reinstate", methods=["POST"])
def reinstate(pid):
    require_roles({"PlatformOperator"})
    if pid not in store.personnel:
        raise_error(ERR_NOT_FOUND, "Personnel not found")
    p = svc.reinstate_personnel(pid)
    return success_response(p)


@bp.route("/dsd/personnel/<pid>/disqualify", methods=["POST"])
def disqualify(pid):
    require_roles({"PlatformOperator"})
    if pid not in store.personnel:
        raise_error(ERR_NOT_FOUND, "Personnel not found")
    p = svc.disqualify_personnel(pid)
    return success_response(p)


# ---------- Certifications ----------
@bp.route("/dsd/certifications", methods=["POST"])
def create_cert():
    require_roles({"PlatformOperator"})
    body = request.get_json(silent=True) or {}
    c = svc.create_certification(body)
    return success_response(c, http_status=201)


@bp.route("/dsd/certifications/<cid>/approve", methods=["POST"])
def approve_cert(cid):
    require_roles({"PlatformOperator"})
    if cid not in store.certifications:
        raise_error(ERR_NOT_FOUND, "Certification not found")
    c = svc.approve_certification(cid)
    return success_response(c)


@bp.route("/dsd/certifications/<cid>/revoke", methods=["POST"])
def revoke_cert(cid):
    require_roles({"PlatformOperator"})
    if cid not in store.certifications:
        raise_error(ERR_NOT_FOUND, "Certification not found")
    c = svc.revoke_certification(cid)
    return success_response(c)


@bp.route("/dsd/personnel/<pid>/certifications", methods=["GET"])
def list_certs_for_personnel(pid):
    require_roles({"PlatformOperator", "ServicePersonnel"})
    if pid not in store.personnel:
        raise_error(ERR_NOT_FOUND, "Personnel not found")
    limit, offset = parse_pagination()
    items = [c for c in store.certifications.values() if c["personnel_id"] == pid]
    window, page = paginate(items, limit, offset)
    return success_response(window, pagination=page)
