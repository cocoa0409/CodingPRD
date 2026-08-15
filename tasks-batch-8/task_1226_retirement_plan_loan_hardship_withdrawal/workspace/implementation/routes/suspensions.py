"""Suspension record listing endpoint."""

from flask import Blueprint

import db
from middleware import require_roles, check_participant_ownership, paginate
from response import success_list
from services.state import get_participant

bp = Blueprint("suspensions", __name__)


@bp.route("/participants/<participant_id>/suspension-records", methods=["GET"])
def list_suspension_records(participant_id):
    user_id, role = require_roles("RecordkeeperAdmin", "PlanSponsor", "Auditor", "Participant")
    participant = get_participant(participant_id)
    check_participant_ownership(user_id, role, participant["id"])
    items = sorted([s for s in db.suspension_records.values()
                    if s["participant_id"] == participant["id"]],
                   key=lambda r: r["created_at"])
    page, total, limit, offset = paginate(items)
    return success_list(page, total, limit, offset)
