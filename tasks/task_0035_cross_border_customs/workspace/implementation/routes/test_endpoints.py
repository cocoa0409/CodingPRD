"""Test-driving endpoints — clock advance and synthetic external events."""

from flask import Blueprint

from clock import CLOCK, now, parse_iso, to_iso
from db import DB, LOCK
from errors import APIError, ERR_INVALID_REQUEST
from middleware import require_roles
from response import success_object
from services.common import emit_audit, touch
from services.serializers import serialize_audit


bp = Blueprint("test_endpoints", __name__)


VALID_EXTERNAL_EVENT_TYPES = {
    "CUSTOMS_SINGLE_WINDOW_ACK",
    "PAYMENT_GATEWAY_PUSH",
    "LOGISTICS_PICKUP_ACK",
    "ERP_ORDER_UPDATE",
}


@bp.route("/_clock/advance", methods=["POST"])
@require_roles("CustomsOfficer")
def advance_clock():
    from services.common import get_body
    body = get_body()
    seconds = body.get("seconds")
    if not isinstance(seconds, int) or isinstance(seconds, bool):
        raise APIError(ERR_INVALID_REQUEST, "seconds must be integer", 400)
    if seconds < 0:
        raise APIError(ERR_INVALID_REQUEST, "seconds must be non-negative", 400)

    with LOCK:
        new_now = CLOCK.advance_seconds(seconds)
        # Re-evaluate PENDING payment notices
        n = new_now
        for pn in DB.payment_notices.values():
            if pn["status"] != "PENDING":
                continue
            due_dt = parse_iso(pn["due_at"])
            if n >= due_dt:
                pn["status"] = "EXPIRED"
                touch(pn)
        return success_object({"now": to_iso(new_now)}, status=200)


@bp.route("/_events/emit", methods=["POST"])
@require_roles("CustomsOfficer")
def emit_external_event():
    from services.common import get_body
    body = get_body()
    event_type = body.get("event_type")
    subject_id = body.get("subject_id")
    if event_type not in VALID_EXTERNAL_EVENT_TYPES:
        raise APIError(ERR_INVALID_REQUEST, "Invalid event_type", 400)
    if not isinstance(subject_id, str) or subject_id.strip() == "":
        raise APIError(ERR_INVALID_REQUEST, "subject_id required", 400)

    # Resolve subject_type from where the id lives
    subject_type = None
    if subject_id in DB.declarations:
        subject_type = "DECLARATION"
    elif subject_id in DB.payment_notices:
        subject_type = "PAYMENT_NOTICE"
    elif subject_id in DB.refunds:
        subject_type = "REFUND"
    else:
        # Default to DECLARATION when unknown — tests typically pin subject_id
        # to the entity they're verifying.
        subject_type = "DECLARATION"

    ev = emit_audit(subject_type, subject_id, "EXTERNAL_SYNC",
                    before_value={},
                    after_value={"external_system": event_type})
    return success_object(serialize_audit(ev), status=200)
