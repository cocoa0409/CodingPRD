"""Certificate reads (PRD §3.8). Certificates are issued by the completion
side-effect; there is no create endpoint."""
from flask import Blueprint, request

import response
from db import db
from errors import err
from middleware import authenticate, require_roles
from services.common import paginate
from services.serialize import view, view_list

bp = Blueprint("certificates", __name__)


@bp.route("/certificates/<certificate_id>", methods=["GET"])
def get_certificate(certificate_id):
    principal = authenticate()
    require_roles(principal, "Learner", "Instructor", "PlatformAdmin")
    rec = db.certificates.get(certificate_id)
    if rec is None:
        raise err("ERR_NOT_FOUND")
    return response.success(view(rec), status=200)


@bp.route("/certificates", methods=["GET"])
def list_certificates():
    principal = authenticate()
    require_roles(principal, "Learner", "Instructor", "PlatformAdmin")
    args = request.args
    items = list(db.certificates.values())
    for key in ("course_id", "learner_id", "enrollment_id"):
        val = args.get(key)
        if val is not None:
            items = [c for c in items if c.get(key) == val]
    page, meta = paginate(items, args)
    return response.success(view_list(page), status=200, pagination=meta)
