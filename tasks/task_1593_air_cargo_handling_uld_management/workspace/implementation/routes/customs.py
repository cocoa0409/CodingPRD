"""Customs hold release (PRD 3.6)."""

from flask import Blueprint

import db
import serializers
from envelope import success_object
from errors import raise_err, ERR_NOT_FOUND, ERR_HOLD_NOT_ACTIVE
from middleware import require_roles
from util import get_json_body, optional_string

bp = Blueprint("customs_holds", __name__)


@bp.route("/customs-holds/<hold_id>/release", methods=["POST"])
@require_roles("CustomsOfficer")
def release_hold(hold_id: str, _user_id: str, _role: str):
    hold = db.customs_holds.get(hold_id)
    if hold is None:
        raise_err(ERR_NOT_FOUND, f"CustomsHold {hold_id} not found")
    body = get_json_body()
    release_note = optional_string(body, "release_note")
    if hold["status"] != "ACTIVE":
        raise_err(ERR_HOLD_NOT_ACTIVE, "Release requires hold ACTIVE")
    hold["status"] = "RELEASED"
    hold["released_at"] = db.now_iso()
    hold["release_note"] = release_note
    db.touch(hold)
    return success_object(serializers.customs_hold(hold))
