"""ComplianceEvent listing."""
from __future__ import annotations

from flask import Blueprint, request

import db
import middleware
import response
from routes._helpers import parse_pagination, sort_events
from services import access, serialize

bp = Blueprint("compliance_events", __name__)


@bp.route("/business-entities/<be_id>/compliance-events", methods=["GET"])
def list_compliance_events(be_id: str):
    middleware.require_auth(["Filer", "StateAdmin", "ComplianceOfficer"])
    be = access.get_business_entity_or_404(be_id)

    limit, offset = parse_pagination()
    et = request.args.get("event_type")
    items = [e for e in db.compliance_events.values() if e["business_entity_id"] == be["id"]]
    if et is not None:
        items = [x for x in items if x["event_type"] == et]
    items = sort_events(items)
    total = len(items)
    page = items[offset:offset + limit]
    return response.success_array([serialize.compliance_event(x) for x in page],
                                  limit=limit, offset=offset, total_count=total)
