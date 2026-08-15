"""Applicator registration endpoint (PRD 3.1)."""
from flask import Blueprint

import db
from middleware import require_roles
from response import ok
from services import core
from util import as_dt, as_str, body, required

bp = Blueprint("applicators", __name__)


@bp.route("/grain/applicators", methods=["POST"])
def create_applicator():
    require_roles("SiteManager")
    data = body()
    name = as_str(required(data, "name"), "name")
    license_no = as_str(required(data, "license_no"), "license_no")
    cert_expires_at = as_dt(required(data, "cert_expires_at"), "cert_expires_at")

    rec = core.new_common()
    rec.update({
        "name": name,
        "license_no": license_no,
        "cert_expires_at": cert_expires_at,
    })
    db.applicators[rec["id"]] = rec
    return ok(core.applicator_view(rec), 201)
