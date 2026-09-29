"""Logical-clock capability plus the epoch sweep (PRD 2.5)."""

from flask import Blueprint

from db import db
from response import obj
from routes.common import auth
from services import domain
from validation import bad, body, parse_instant, req_str

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    auth("RecruitmentOfficer", "ComplianceOfficer")
    data = body()
    raw = req_str(data, "to_iso8601", min_len=1)
    moment = parse_instant(raw)
    if moment is None:
        bad("Field 'to_iso8601' must be an ISO 8601 instant")

    db.clock = moment
    return obj(domain.epoch_sweep())
