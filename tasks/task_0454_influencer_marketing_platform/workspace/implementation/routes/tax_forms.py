from flask import Blueprint

from db import db, bump
from middleware import get_auth, require_role
from errors import err
from response import success
import serializers as S
import services as svc

bp = Blueprint("tax_forms", __name__)


@bp.route("/tax-forms/<form_id>", methods=["GET"])
def get_form(form_id):
    _, role = get_auth()
    require_role(role, {"PlatformAdmin", "Creator", "ComplianceOfficer"})
    t = svc.get_tax_form(form_id)
    return success(S.tax_form_view(t), status=200)


@bp.route("/tax-forms/<form_id>/file", methods=["POST"])
def file_form(form_id):
    _, role = get_auth()
    require_role(role, {"ComplianceOfficer"})
    t = svc.get_tax_form(form_id)
    if t["status"] != "GENERATED":
        raise err("ERR_INVALID_STATE", "Only a GENERATED form can be filed")
    creator = db.creators.get(t["creator_id"])
    # W-9 gate (priority 17)
    if not creator or not creator["tax_id_on_file"]:
        raise err("ERR_W9_REQUIRED", "Creator must have a W-9 on file before filing")
    t["status"] = "FILED"
    bump(t)
    return success(S.tax_form_view(t), status=200)


@bp.route("/tax-forms/<form_id>/void", methods=["POST"])
def void_form(form_id):
    _, role = get_auth()
    require_role(role, {"ComplianceOfficer"})
    t = svc.get_tax_form(form_id)
    if t["status"] != "GENERATED":
        raise err("ERR_INVALID_STATE", "Only a GENERATED form can be voided")
    t["status"] = "VOIDED"
    bump(t)
    return success(S.tax_form_view(t), status=200)
