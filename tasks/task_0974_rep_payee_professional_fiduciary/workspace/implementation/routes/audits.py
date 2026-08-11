"""Audit cases endpoints."""

from flask import Blueprint, request

from db import store
from errors import (
    ERR_ALREADY_TERMINAL,
    ERR_AUDIT_NOT_FOUND,
    ERR_CLIENT_NOT_FOUND,
    ERR_INVALID_STATE,
    err,
)
from middleware import require_roles
from response import success_object, success_list
from serializers import serialize_audit_case
from services.cascade import clock_now_iso, cascade_misuse_confirmed
from util import (
    new_id,
    parse_date,
    parse_pagination,
    require_body,
    get_string,
    get_int,
    get_enum,
    reject_unexpected,
)

bp = Blueprint("audits", __name__)

READ_ROLES = ("FiduciaryAdmin", "CaseManager", "FinancialOfficer", "ConservatorOfficer", "ComplianceAuditor")
AUTHORITIES = ("SSA", "STATE_COURT", "BONDING_COMPANY")
SCOPES = ("CLIENT_ACCOUNT", "ORG_WIDE")


@bp.route("/audit-cases", methods=["POST"])
def create_audit():
    require_roles("ComplianceAuditor")
    body = require_body()
    reject_unexpected(body, {
        "client_id", "authority", "scope", "period_start_date", "period_end_date",
    })
    client_id = get_string(body, "client_id")
    authority = get_enum(body, "authority", AUTHORITIES)
    scope = get_enum(body, "scope", SCOPES)
    ps = parse_date(get_string(body, "period_start_date"), "period_start_date")
    pe = parse_date(get_string(body, "period_end_date"), "period_end_date")
    from errors import ERR_INVALID_REQUEST
    if pe < ps:
        raise err(ERR_INVALID_REQUEST, 400, "period_end_date must be >= period_start_date")
    if client_id not in store.clients:
        raise err(ERR_CLIENT_NOT_FOUND, 404, "client not found")
    now = clock_now_iso()
    aid = new_id()
    a = {
        "id": aid,
        "client_id": client_id,
        "authority": authority,
        "scope": scope,
        "period_start_date": ps,
        "period_end_date": pe,
        "misuse_amount_cents": None,
        "findings_count": None,
        "status": "OPENED",
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    store.audit_cases[aid] = a
    return success_object(serialize_audit_case(a), status=201)


@bp.route("/audit-cases", methods=["GET"])
def list_audits():
    require_roles(*READ_ROLES)
    limit, offset = parse_pagination()
    client_id = request.args.get("client_id")
    authority = request.args.get("authority")
    status = request.args.get("status")
    items = list(store.audit_cases.values())
    if client_id is not None:
        items = [a for a in items if a["client_id"] == client_id]
    if authority is not None:
        items = [a for a in items if a["authority"] == authority]
    if status is not None:
        items = [a for a in items if a["status"] == status]
    items.sort(key=lambda a: a["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serialize_audit_case(a) for a in page], limit, offset, total)


def _get_or_404(aid):
    a = store.audit_cases.get(aid)
    if not a:
        raise err(ERR_AUDIT_NOT_FOUND, 404, "audit case not found")
    return a


@bp.route("/audit-cases/<aid>", methods=["GET"])
def get_audit(aid):
    require_roles(*READ_ROLES)
    a = _get_or_404(aid)
    return success_object(serialize_audit_case(a))


@bp.route("/audit-cases/<aid>/issue-findings", methods=["POST"])
def issue_findings(aid):
    require_roles("ComplianceAuditor")
    a = _get_or_404(aid)
    if a["status"] in ("CLOSED_NO_ACTION", "MISUSE_CONFIRMED"):
        raise err(ERR_ALREADY_TERMINAL, 409, "Audit is terminal")
    if a["status"] != "OPENED":
        raise err(ERR_INVALID_STATE, 409, "Only OPENED -> FINDINGS_ISSUED")
    body = require_body()
    reject_unexpected(body, {"misuse_amount_cents", "findings_count"})
    misuse = get_int(body, "misuse_amount_cents", min_value=0)
    findings = get_int(body, "findings_count", min_value=0)
    now = clock_now_iso()
    a["misuse_amount_cents"] = misuse
    a["findings_count"] = findings
    a["status"] = "FINDINGS_ISSUED"
    a["updated_at"] = now
    a["version"] += 1
    return success_object(serialize_audit_case(a))


@bp.route("/audit-cases/<aid>/close", methods=["POST"])
def close_audit(aid):
    require_roles("ComplianceAuditor")
    a = _get_or_404(aid)
    if a["status"] in ("CLOSED_NO_ACTION", "MISUSE_CONFIRMED"):
        raise err(ERR_ALREADY_TERMINAL, 409, "Audit is terminal")
    if a["status"] != "FINDINGS_ISSUED":
        raise err(ERR_INVALID_STATE, 409, "Only FINDINGS_ISSUED -> close")
    now = clock_now_iso()
    if a.get("misuse_amount_cents", 0) == 0:
        a["status"] = "CLOSED_NO_ACTION"
    else:
        a["status"] = "MISUSE_CONFIRMED"
        cascade_misuse_confirmed(a["client_id"], now)
    a["updated_at"] = now
    a["version"] += 1
    return success_object(serialize_audit_case(a))
