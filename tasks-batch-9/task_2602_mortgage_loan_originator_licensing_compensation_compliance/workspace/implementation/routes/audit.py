"""The append-only compliance trail (PRD 2.5)."""
from flask import Blueprint

import serializers
from db import db
from middleware import ALL_ROLES, endpoint
from response import paginated
from routes.common import filters, matches

bp = Blueprint("audit_events", __name__)


@bp.route("/audit-events", methods=["GET"])
@endpoint(*ALL_ROLES)
def list_audit_events():
    active = filters("subject_type", "subject_ref", "event_type")
    rows = [r for r in db.audit_events.values() if matches(r, active)]
    # The trail is always ordered by its global sequence_no ascending.
    rows.sort(key=lambda r: r["sequence_no"])
    return paginated(rows, serializers.audit_event)
