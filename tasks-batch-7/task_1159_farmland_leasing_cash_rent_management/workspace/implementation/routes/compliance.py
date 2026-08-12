from flask import Blueprint, request
from middleware import get_caller, require_role, get_json_body
from services.common import require_string, parse_pagination
from response import success_object, success_list
from errors import ApiError
from db import db, touch
from services.serialize import serialize
from services.sweeps import SCORE_CAP, NON_COMPLIANCE_PENALTY

bp = Blueprint("compliance", __name__)
READ_ROLES = {"FarmManager", "Landlord", "Tenant"}


@bp.route("/compliance-records/<recordId>", methods=["GET"])
def get_record(recordId):
    _, role = get_caller()
    require_role(role, READ_ROLES)
    rec = db.compliance_records.get(recordId)
    if rec is None:
        raise ApiError("ERR_NOT_FOUND", 404, f"ComplianceRecord {recordId} not found")
    return success_object(serialize("compliance", rec))


@bp.route("/compliance-records", methods=["GET"])
def list_records():
    _, role = get_caller()
    require_role(role, READ_ROLES)
    limit, offset = parse_pagination(request.args)
    items = sorted(db.compliance_records.values(), key=lambda r: r["created_at"])
    lease_q = request.args.get("lease_id")
    if lease_q is not None:
        items = [r for r in items if r["lease_id"] == lease_q]
    status_q = request.args.get("status")
    if status_q is not None:
        items = [r for r in items if r["status"] == status_q]
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serialize("compliance", r) for r in page], limit, offset, total)


@bp.route("/compliance-records/<recordId>/submit_evidence", methods=["POST"])
def submit_evidence(recordId):
    user_id, role = get_caller()
    require_role(role, {"Tenant"})
    body = get_json_body()
    note = require_string(body, "evidence_note")
    rec = db.compliance_records.get(recordId)
    if rec is None:
        raise ApiError("ERR_NOT_FOUND", 404, f"ComplianceRecord {recordId} not found")
    lease = db.leases.get(rec["lease_id"])
    if lease is None or lease["tenant_id"] != user_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", 403, "Caller is not the lease tenant")
    if rec["status"] not in ("PENDING", "REJECTED"):
        raise ApiError("ERR_INVALID_STATE", 409,
                       f"Record in state {rec['status']} cannot accept evidence")
    rec["status"] = "EVIDENCE_SUBMITTED"
    rec["evidence_note"] = note
    touch(rec)
    return success_object(serialize("compliance", rec))


@bp.route("/compliance-records/<recordId>/verify", methods=["POST"])
def verify_record(recordId):
    user_id, role = get_caller()
    require_role(role, {"FarmManager"})
    rec = db.compliance_records.get(recordId)
    if rec is None:
        raise ApiError("ERR_NOT_FOUND", 404, f"ComplianceRecord {recordId} not found")
    if rec["status"] != "EVIDENCE_SUBMITTED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       f"Record in state {rec['status']} cannot be verified")
    rec["status"] = "VERIFIED"
    rec["verified_by"] = user_id
    touch(rec)
    return success_object(serialize("compliance", rec))


@bp.route("/compliance-records/<recordId>/reject_evidence", methods=["POST"])
def reject_evidence(recordId):
    _, role = get_caller()
    require_role(role, {"FarmManager"})
    body = get_json_body()
    require_string(body, "reason")
    rec = db.compliance_records.get(recordId)
    if rec is None:
        raise ApiError("ERR_NOT_FOUND", 404, f"ComplianceRecord {recordId} not found")
    if rec["status"] != "EVIDENCE_SUBMITTED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       f"Record in state {rec['status']} cannot be rejected")
    rec["status"] = "REJECTED"
    touch(rec)
    return success_object(serialize("compliance", rec))


@bp.route("/compliance-records/<recordId>/waive", methods=["POST"])
def waive_record(recordId):
    _, role = get_caller()
    require_role(role, {"FarmManager"})
    body = get_json_body()
    require_string(body, "reason")
    rec = db.compliance_records.get(recordId)
    if rec is None:
        raise ApiError("ERR_NOT_FOUND", 404, f"ComplianceRecord {recordId} not found")
    if rec["status"] not in ("PENDING", "EVIDENCE_SUBMITTED", "REJECTED", "NON_COMPLIANT"):
        raise ApiError("ERR_INVALID_STATE", 409,
                       f"Record in state {rec['status']} cannot be waived")
    was_noncompliant = rec["status"] == "NON_COMPLIANT"
    rec["status"] = "WAIVED"
    touch(rec)
    if was_noncompliant:
        lease = db.leases.get(rec["lease_id"])
        if lease is not None:
            tenant = db.tenants.get(lease["tenant_id"])
            if tenant is not None:
                tenant["compliance_score"] = min(
                    SCORE_CAP, tenant["compliance_score"] + NON_COMPLIANCE_PENALTY)
                touch(tenant)
    return success_object(serialize("compliance", rec))
