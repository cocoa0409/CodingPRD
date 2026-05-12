"""External event ingestion + alerts."""

from flask import Blueprint, request
import middleware
import response
from services import external_events as svc
from services import clock as clock_svc

bp = Blueprint("external_events", __name__)


@bp.route("/external-events", methods=["POST"])
def ingest():
    middleware.require_auth()
    middleware.require_role("Operator")
    event, replayed = svc.ingest(request.get_json(silent=True) or {})
    # Spec: idempotent replay returns success-shaped response on the prior row.
    # We always return 201 for new, 200 for replay.
    if replayed:
        return response.success(event, 200)
    return response.success(event, 201)


@bp.route("/external-events/<event_id>", methods=["GET"])
def get_event(event_id):
    middleware.require_auth()
    middleware.require_role("Operator", "Auditor")
    return response.success(svc.get_event(event_id))


@bp.route("/letters-of-credit/<lc_id>/expiry-alerts", methods=["GET"])
def list_expiry_alerts(lc_id):
    middleware.require_auth()
    middleware.require_role("Applicant", "Beneficiary", "IssuingBank", "Operator", "Auditor")
    limit, offset = response.parse_pagination(request.args)
    items, total = clock_svc.list_expiry_alerts(lc_id, limit, offset)
    return response.success_list(items, total, limit, offset)
