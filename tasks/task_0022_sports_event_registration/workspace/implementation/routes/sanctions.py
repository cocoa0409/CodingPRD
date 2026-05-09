"""Sanction + appeal endpoints."""
from flask import Blueprint, g

import db
from errors import err
from middleware import require_auth
from response import success
from services import doping as doping_svc
from services.validation import get_body


bp = Blueprint("sanctions", __name__)


@bp.route("/sanctions/<sanction_id>", methods=["GET"])
@require_auth(roles={"DisciplinaryOfficer", "AppealsBoard", "Participant"})
def get_sanction(sanction_id):
    sr = db.sanction_records.get(sanction_id)
    if not sr:
        raise err("ERR_NOT_FOUND", "sanction not found")
    return success(db.public(sr), 200)


@bp.route("/appeals", methods=["POST"])
@require_auth(roles={"Participant"})
def post_appeal():
    body = get_body()
    a = doping_svc.file_appeal(body, g.user_id, g.user_role)
    return success(db.public(a), 201)


@bp.route("/appeals/<appeal_id>/decide", methods=["POST"])
@require_auth(roles={"AppealsBoard"})
def decide_appeal(appeal_id):
    body = get_body()
    a = doping_svc.decide_appeal(appeal_id, body, g.user_id, g.user_role)
    return success(db.public(a), 200)
