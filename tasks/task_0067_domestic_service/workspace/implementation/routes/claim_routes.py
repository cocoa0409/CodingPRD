"""Insurance claims, audit logs, settlement, sweep, system event routes."""
from flask import Blueprint, request

from db import store
from errors import ERR_NOT_FOUND, ERR_VALIDATION_ERROR, raise_error
from response import success_response
from middleware import require_roles, require_roles_optional
from services import claims as claims_svc
from services import sweeps as sweeps_svc
from services.utils import parse_pagination, paginate


bp = Blueprint("claims_and_admin", __name__)


# ---------- Claims ----------
@bp.route("/dsd/claims/<cid>", methods=["GET"])
def get_claim(cid):
    require_roles({"PlatformOperator"})
    if cid not in store.insurance_claims:
        raise_error(ERR_NOT_FOUND, "Claim not found")
    return success_response(store.insurance_claims[cid])


@bp.route("/dsd/claims/<cid>/evidence", methods=["POST"])
def attach_evidence(cid):
    require_roles({"PlatformOperator"})
    body = request.get_json(silent=True) or {}
    c = claims_svc.attach_evidence(cid, body)
    return success_response(c)


@bp.route("/dsd/claims/<cid>/request-evidence", methods=["POST"])
def request_evidence(cid):
    role, user_id = require_roles({"PlatformOperator"})
    c = claims_svc.request_evidence(cid, role, user_id)
    return success_response(c)


@bp.route("/dsd/claims/<cid>/file", methods=["POST"])
def file_claim(cid):
    role, user_id = require_roles({"PlatformOperator"})
    c = claims_svc.file_claim(cid, role, user_id)
    return success_response(c)


@bp.route("/dsd/claims/<cid>/mark-paid", methods=["POST"])
def mark_paid(cid):
    role, user_id = require_roles({"PlatformOperator"})
    c = claims_svc.mark_paid(cid, role, user_id)
    return success_response(c)


@bp.route("/dsd/claims/<cid>/archive", methods=["POST"])
def archive(cid):
    require_roles({"PlatformOperator"})
    c = claims_svc.archive_claim(cid)
    return success_response(c)


# ---------- Audit Logs ----------
@bp.route("/dsd/audit-logs", methods=["GET"])
def list_audit():
    require_roles({"PlatformOperator"})
    limit, offset = parse_pagination()
    items = list(store.audit_log.values())
    st = request.args.get("subject_type")
    sid = request.args.get("subject_id")
    at = request.args.get("action_type")
    if st:
        items = [x for x in items if x["subject_type"] == st]
    if sid:
        items = [x for x in items if x["subject_id"] == sid]
    if at:
        items = [x for x in items if x["action_type"] == at]
    window, page = paginate(items, limit, offset)
    return success_response(window, pagination=page)


# ---------- Settlement listing ----------
@bp.route("/dsd/personnel/<pid>/settlement", methods=["GET"])
def list_settlement(pid):
    role, user_id = require_roles({"PlatformOperator", "ServicePersonnel"})
    if pid not in store.personnel:
        raise_error(ERR_NOT_FOUND, "Personnel not found")
    if role == "ServicePersonnel" and user_id != pid:
        raise_error(ERR_NOT_FOUND, "Personnel not found")
    limit, offset = parse_pagination()
    items = [e for e in store.settlement_entries.values() if e["personnel_id"] == pid]
    cycle = request.args.get("cycle_id")
    if cycle:
        items = [x for x in items if x.get("cycle_id") == cycle]
    window, page = paginate(items, limit, offset)
    return success_response(window, pagination=page)


# ---------- Test-driving / system endpoints ----------
@bp.route("/dsd/_clock/advance", methods=["POST"])
def clock_advance():
    # The auth presence check is bypassed for /dsd/_clock/advance per PRD §2.1.
    # Still, if X-User-Role is supplied, it must be "system".
    require_roles_optional({"system"})
    body = request.get_json(silent=True) or {}
    if "seconds" not in body:
        raise_error(ERR_VALIDATION_ERROR, "Missing seconds")
    try:
        secs = float(body["seconds"])
    except (TypeError, ValueError):
        raise_error(ERR_VALIDATION_ERROR, "seconds must be a number")
    sweeps_svc.advance_clock(secs)
    return success_response({}, http_status=200)


@bp.route("/dsd/_sweep/recertification", methods=["POST"])
def sweep_recert():
    # Sweep endpoints bypass header-presence check but enforce role when supplied
    require_roles_optional({"system", "PlatformOperator"})
    sweeps_svc.run_recertification_sweep()
    return success_response({}, http_status=200)


@bp.route("/dsd/_sweep/settlement", methods=["POST"])
def sweep_settlement():
    require_roles_optional({"system", "PlatformOperator"})
    body = request.get_json(silent=True) or {}
    cycle_id = body.get("cycle_id")
    if not cycle_id:
        raise_error(ERR_VALIDATION_ERROR, "Missing cycle_id")
    sweeps_svc.run_settlement_sweep(cycle_id)
    return success_response({}, http_status=200)


@bp.route("/dsd/_events/insurance-decision", methods=["POST"])
def insurance_decision():
    require_roles_optional({"system"})
    body = request.get_json(silent=True) or {}
    c = claims_svc.insurance_decision(body)
    return success_response(c)


@bp.route("/dsd/_events/payment-received", methods=["POST"])
def payment_received():
    require_roles_optional({"system"})
    body = request.get_json(silent=True) or {}
    # Informational only — verify order exists, do nothing else
    oid = body.get("order_id")
    if not oid or oid not in store.orders:
        raise_error(ERR_NOT_FOUND, "Order not found")
    return success_response({}, http_status=200)
