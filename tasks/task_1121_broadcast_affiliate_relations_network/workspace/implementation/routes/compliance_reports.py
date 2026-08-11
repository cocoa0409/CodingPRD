"""ComplianceReport routes."""
import uuid

from flask import Blueprint, request

from db import store, now_iso
from errors import (
    err_future_period,
    err_invalid_request,
    err_invalid_state,
    err_not_found,
)
from middleware import require_role
from response import success_list, success_object
from services.posture import recompute_network_posture
from services.serializers import compliance_report_view


bp = Blueprint("compliance_reports", __name__)


VALID_KINDS = {"FCC_302", "CHILDRENS_TELEVISION", "EEO", "POLITICAL_FILE"}


def _new_id():
    return str(uuid.uuid4())


def _parse_pagination():
    try:
        limit = int(request.args.get("limit", 10))
        offset = int(request.args.get("offset", 0))
    except ValueError:
        raise err_invalid_request("limit/offset must be integers")
    if limit < 1 or limit > 100:
        raise err_invalid_request("limit must be in [1, 100]")
    if offset < 0:
        raise err_invalid_request("offset must be >= 0")
    return limit, offset


def _paginate(items, limit, offset):
    items = sorted(items, key=lambda x: x.get("created_at", ""))
    total = len(items)
    return items[offset : offset + limit], total


def _get_scoped(nid, sid, cid=None):
    n = store.networks.get(nid)
    if n is None:
        raise err_not_found("network not found")
    s = store.stations.get(sid)
    if s is None or s.get("network_id") != nid:
        raise err_not_found("station not found")
    if cid is not None:
        c = store.compliance_reports.get(cid)
        if c is None or c.get("station_id") != sid:
            raise err_not_found("compliance report not found")
        return n, s, c
    return n, s


@bp.route("/networks/<nid>/stations/<sid>/compliance-reports", methods=["POST"])
def create_compliance_report(nid, sid):
    require_role("StationGroupOwner", "ComplianceAuditor")
    _get_scoped(nid, sid)
    body = request.get_json(silent=True) or {}
    period_index = body.get("period_index")
    report_kind = body.get("report_kind")
    if period_index is None or report_kind is None:
        raise err_invalid_request("missing required field")
    if report_kind not in VALID_KINDS:
        raise err_invalid_request("invalid report_kind")
    cid = _new_id()
    ts = now_iso()
    c = {
        "id": cid,
        "station_id": sid,
        "period_index": int(period_index),
        "report_kind": report_kind,
        "status": "OPEN",
        "finding_count": 0,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    store.compliance_reports[cid] = c
    return success_object(compliance_report_view(c), 201)


@bp.route("/networks/<nid>/stations/<sid>/compliance-reports/<cid>", methods=["GET"])
def get_compliance_report(nid, sid, cid):
    require_role("PlatformAdmin", "NetworkAffiliateRelations", "StationGroupOwner", "ComplianceAuditor")
    _, _, c = _get_scoped(nid, sid, cid)
    return success_object(compliance_report_view(c))


@bp.route("/networks/<nid>/stations/<sid>/compliance-reports", methods=["GET"])
def list_compliance_reports(nid, sid):
    require_role("PlatformAdmin", "NetworkAffiliateRelations", "StationGroupOwner", "ComplianceAuditor")
    _get_scoped(nid, sid)
    limit, offset = _parse_pagination()
    status = request.args.get("status")
    kind = request.args.get("report_kind")
    period_index = request.args.get("period_index")
    items = [c for c in store.compliance_reports.values() if c.get("station_id") == sid]
    if status is not None:
        items = [c for c in items if c.get("status") == status]
    if kind is not None:
        items = [c for c in items if c.get("report_kind") == kind]
    if period_index is not None:
        try:
            pidx = int(period_index)
        except ValueError:
            raise err_invalid_request("period_index must be integer")
        items = [c for c in items if c.get("period_index") == pidx]
    items, total = _paginate(items, limit, offset)
    return success_list([compliance_report_view(c) for c in items], limit, offset, total)


@bp.route("/networks/<nid>/stations/<sid>/compliance-reports/<cid>/submit", methods=["POST"])
def submit_compliance_report(nid, sid, cid):
    require_role("StationGroupOwner")
    n, _, c = _get_scoped(nid, sid, cid)
    if c.get("status") != "OPEN":
        raise err_invalid_state("compliance report must be OPEN to submit")
    if c["period_index"] > n.get("current_period_index", 0):
        raise err_future_period()
    c["status"] = "SUBMITTED"
    c["updated_at"] = now_iso()
    c["version"] = c.get("version", 1) + 1
    return success_object(compliance_report_view(c))


@bp.route("/networks/<nid>/stations/<sid>/compliance-reports/<cid>/audit", methods=["POST"])
def audit_compliance_report(nid, sid, cid):
    require_role("NetworkAffiliateRelations", "ComplianceAuditor")
    _, _, c = _get_scoped(nid, sid, cid)
    if c.get("status") != "SUBMITTED":
        raise err_invalid_state("compliance report must be SUBMITTED to audit")
    body = request.get_json(silent=True) or {}
    finding_count = body.get("finding_count")
    if finding_count is None:
        raise err_invalid_request("finding_count is required")
    c["finding_count"] = int(finding_count)
    c["status"] = "AUDITED"
    c["updated_at"] = now_iso()
    c["version"] = c.get("version", 1) + 1
    return success_object(compliance_report_view(c))


@bp.route("/networks/<nid>/stations/<sid>/compliance-reports/<cid>/resolve-pass", methods=["POST"])
def resolve_pass_compliance(nid, sid, cid):
    require_role("NetworkAffiliateRelations", "ComplianceAuditor")
    n, _, c = _get_scoped(nid, sid, cid)
    if c.get("status") != "AUDITED":
        raise err_invalid_state("compliance report must be AUDITED to resolve")
    if c.get("finding_count", 0) != 0:
        raise err_invalid_state("finding_count must be 0 to resolve pass")
    c["status"] = "PASSED"
    c["updated_at"] = now_iso()
    c["version"] = c.get("version", 1) + 1
    recompute_network_posture(n)
    return success_object(compliance_report_view(c))


@bp.route("/networks/<nid>/stations/<sid>/compliance-reports/<cid>/resolve-fail", methods=["POST"])
def resolve_fail_compliance(nid, sid, cid):
    require_role("NetworkAffiliateRelations", "ComplianceAuditor")
    n, _, c = _get_scoped(nid, sid, cid)
    if c.get("status") != "AUDITED":
        raise err_invalid_state("compliance report must be AUDITED to resolve")
    if c.get("finding_count", 0) < 1:
        raise err_invalid_state("finding_count must be >= 1 to resolve fail")
    c["status"] = "FAILED"
    c["updated_at"] = now_iso()
    c["version"] = c.get("version", 1) + 1
    recompute_network_posture(n)
    return success_object(compliance_report_view(c))


# Flat reverse-reachability endpoints
@bp.route("/compliance-reports/<cid>", methods=["GET"])
def get_compliance_report_flat(cid):
    require_role("PlatformAdmin", "NetworkAffiliateRelations", "StationGroupOwner", "ComplianceAuditor")
    c = store.compliance_reports.get(cid)
    if c is None:
        raise err_not_found("compliance report not found")
    return success_object(compliance_report_view(c))


@bp.route("/compliance-reports", methods=["GET"])
def list_compliance_reports_flat():
    require_role("PlatformAdmin", "NetworkAffiliateRelations", "StationGroupOwner", "ComplianceAuditor")
    limit, offset = _parse_pagination()
    sid = request.args.get("station_id")
    items = list(store.compliance_reports.values())
    if sid is not None:
        items = [c for c in items if c.get("station_id") == sid]
    items, total = _paginate(items, limit, offset)
    return success_list([compliance_report_view(c) for c in items], limit, offset, total)
