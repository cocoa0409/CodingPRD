"""System-wide compliance event query."""

from flask import request as flask_request

from db import db
from middleware import ALL_ROLES, authorize
from response import list_response
from . import make_blueprint

bp = make_blueprint("events")


def _q(name):
    v = flask_request.args.get(name)
    return v if v not in (None, "") else None


@bp.route("/compliance-events", methods=["GET"])
def list_compliance_events():
    authorize(*ALL_ROLES)
    event_type = _q("event_type")
    request_id = _q("request_id")
    provider_id = _q("provider_id")
    items = [
        e
        for e in db.events.values()
        if (event_type is None or e["event_type"] == event_type)
        and (request_id is None or e["request_id"] == request_id)
        and (provider_id is None or e["provider_id"] == provider_id)
    ]
    return list_response(items)
