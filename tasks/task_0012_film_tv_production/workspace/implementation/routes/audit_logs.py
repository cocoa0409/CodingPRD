"""Audit log read endpoint."""
from flask import Blueprint, request

import errors as E
from db import store
from middleware import require_roles, parse_pagination
from response import ok_array
from services.serializers import serialize_audit_log, paginate
from services.audit import VALID_ACTIONS


bp = Blueprint("audit_logs", __name__)


@bp.route("/productions/<pid>/audit-logs", methods=["GET"])
@require_roles("ExecutiveProducer", "FinanceController")
def list_audit_logs(pid):
    p = store.productions.get(pid)
    if not p:
        E.not_found(f"Production {pid} not found")
    limit, offset = parse_pagination()
    action_filter = request.args.get("action")
    items = [a for a in store.audit_logs.values() if a["production_id"] == pid]
    if action_filter:
        if action_filter not in VALID_ACTIONS:
            E.validation_err("Invalid action filter")
        items = [a for a in items if a["action"] == action_filter]
    page, total, has_more = paginate(items, limit, offset)
    return ok_array([serialize_audit_log(a) for a in page], limit, offset, total, has_more)
