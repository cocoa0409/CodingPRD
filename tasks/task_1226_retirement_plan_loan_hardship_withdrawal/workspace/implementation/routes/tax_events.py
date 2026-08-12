"""Tax event endpoints."""

from flask import Blueprint

import db
import errors
from middleware import require_roles, check_participant_ownership, paginate
from response import success_object, success_list
from services import audit
from services.state import get_participant, get_tax_event
from services.util import touch

bp = Blueprint("tax_events", __name__)


@bp.route("/participants/<participant_id>/tax-events", methods=["GET"])
def list_tax_events(participant_id):
    user_id, role = require_roles("RecordkeeperAdmin", "Auditor", "Participant")
    participant = get_participant(participant_id)
    check_participant_ownership(user_id, role, participant["id"])
    items = sorted([t for t in db.tax_events.values()
                    if t["participant_id"] == participant["id"]],
                   key=lambda r: r["created_at"])
    page, total, limit, offset = paginate(items)
    return success_list(page, total, limit, offset)


@bp.route("/tax-events/<tax_event_id>", methods=["GET"])
def read_tax_event(tax_event_id):
    user_id, role = require_roles("RecordkeeperAdmin", "Auditor", "Participant")
    evt = get_tax_event(tax_event_id)
    check_participant_ownership(user_id, role, evt["participant_id"])
    return success_object(evt)


@bp.route("/tax-events/<tax_event_id>/mark-reported", methods=["POST"])
def mark_reported(tax_event_id):
    user_id, role = require_roles("RecordkeeperAdmin")
    evt = get_tax_event(tax_event_id)
    if evt["status"] != "PENDING":
        raise errors.err(errors.ERR_TAX_EVENT_ALREADY_REPORTED,
                         f"Tax event already {evt['status']}", 409)
    evt["status"] = "REPORTED"
    touch(evt)
    participant = get_participant(evt["participant_id"])
    audit.append(participant["plan_id"], role, user_id, "TAX_EVENT_REPORTED",
                 "TaxEvent", evt["id"], {})
    return success_object(evt)
