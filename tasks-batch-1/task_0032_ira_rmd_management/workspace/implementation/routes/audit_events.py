"""AuditEvent endpoints (read-only; PlanAdministrator and IRSAuditor only)."""

from flask import Blueprint, request

import db
from errors import ERR_INVALID_REQUEST, raise_api
from helpers import (
    get_audit_event_or_404,
    get_pagination_params,
    paginate,
)
from middleware import parse_auth_headers, require_roles
from response import success_array, success_object
from serializers import audit_event_to_json


bp = Blueprint("audit_events", __name__, url_prefix="/ira/audit-events")


EVENT_KINDS = {
    "CONTRIBUTION_CONFIRMED",
    "DISTRIBUTION_CONFIRMED",
    "CONVERSION_COMPLETED",
    "RMD_DEADLINE_BREACHED",
    "BENEFICIARY_INHERITED",
    "OWNER_DECEASED",
    "YEAR_ROLLED_OVER",
}


@bp.route("/<e_id>", methods=["GET"])
def get_event(e_id):
    parse_auth_headers()
    require_roles("PlanAdministrator", "IRSAuditor")
    e = get_audit_event_or_404(e_id)
    return success_object(audit_event_to_json(e))


@bp.route("", methods=["GET"])
def list_events():
    parse_auth_headers()
    require_roles("PlanAdministrator", "IRSAuditor")
    limit, offset = get_pagination_params()
    owner_id = request.args.get("owner_id")
    account_id = request.args.get("account_id")
    event_kind = request.args.get("event_kind")
    tax_year_str = request.args.get("tax_year")
    rows = list(db.audit_events.values())
    if owner_id is not None:
        rows = [e for e in rows if e["owner_id"] == owner_id]
    if account_id is not None:
        rows = [e for e in rows if e["account_id"] == account_id]
    if event_kind is not None:
        if event_kind not in EVENT_KINDS:
            raise_api(ERR_INVALID_REQUEST, "event_kind filter is not a recognized value.")
        rows = [e for e in rows if e["event_kind"] == event_kind]
    if tax_year_str is not None:
        try:
            ty = int(tax_year_str)
        except ValueError:
            raise_api(ERR_INVALID_REQUEST, "tax_year filter must be an integer.")
        rows = [e for e in rows if e["tax_year"] == ty]
    page, total = paginate(rows, limit, offset)
    return success_array([audit_event_to_json(e) for e in page], limit, offset, total)
