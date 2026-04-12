from flask import Blueprint, request
import db
from errors import raise_error, ERR_BAD_REQUEST
from middleware import require_roles
from response import success_response, list_response
from services.overlap import parse_dt

audit_logs_bp = Blueprint("audit_logs", __name__)


@audit_logs_bp.route("/audit-logs", methods=["GET"])
def list_audit_logs():
    require_roles("facility_admin")
    args = request.args

    filtered = list(db.audit_logs.values())

    if "resource_type" in args:
        filtered = [a for a in filtered if a["resource_type"] == args["resource_type"]]
    if "resource_id" in args:
        filtered = [a for a in filtered if a["resource_id"] == args["resource_id"]]
    if "actor_id" in args:
        filtered = [a for a in filtered if a["actor_id"] == args["actor_id"]]
    if "action" in args:
        filtered = [a for a in filtered if a["action"] == args["action"]]
    if "start_after" in args:
        try:
            sa = parse_dt(args["start_after"])
            filtered = [a for a in filtered if parse_dt(a["timestamp"]) > sa]
        except (ValueError, TypeError):
            pass
    if "start_before" in args:
        try:
            sb = parse_dt(args["start_before"])
            filtered = [a for a in filtered if parse_dt(a["timestamp"]) < sb]
        except (ValueError, TypeError):
            pass

    filtered.sort(key=lambda x: x["timestamp"])
    total_count = len(filtered)

    limit = min(max(int(args.get("limit", 20)), 1), 100)
    offset = max(int(args.get("offset", 0)), 0)

    page = filtered[offset:offset + limit]
    return list_response(page, total_count, limit, offset)


@audit_logs_bp.route("/audit-logs/<log_id>", methods=["GET"])
def get_audit_log(log_id):
    require_roles("facility_admin")
    log = db.audit_logs.get(log_id)
    if not log:
        raise_error(("ERR_NOT_FOUND", 404), "Audit log entry not found")
    return success_response(log)
