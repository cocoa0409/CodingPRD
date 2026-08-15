"""Factory audits: create (score computed), list, get, approve, reject."""

from flask import Blueprint, request

from db import new_id, next_seq, now_iso, public, stamp_new, store, touch
from errors import ApiError
from middleware import (
    ALL_ROLES,
    body_json,
    get_or_404,
    opt_int,
    paginate,
    req_enum,
    req_int,
    require_roles,
    sorted_created,
)
from response import success_list, success_object
from services.domain import compute_audit_score, refresh_factory_grade

bp = Blueprint("audits", __name__)

AUDIT_TYPES = ("SCREENING", "ONSITE")


@bp.route("/sourcing/factories/<factoryId>/audits", methods=["POST"])
def create_audit(factoryId):
    uid, _ = require_roles("SourcingAgent")
    factory = get_or_404(store.factories, factoryId, "ERR_FACTORY_NOT_FOUND", "Factory")
    data = body_json()
    audit_type = req_enum(data, "audit_type", AUDIT_TYPES)
    qs = req_int(data, "quality_system_score", lo=0, hi=100)
    sc = req_int(data, "social_compliance_score", lo=0, hi=100)
    pc = req_int(data, "production_capability_score", lo=0, hi=100)
    fs = req_int(data, "financial_stability_score", lo=0, hi=100)
    critical_findings = opt_int(data, "critical_findings", default=0, lo=0)
    score, grade = compute_audit_score(audit_type, qs, sc, pc, fs, critical_findings)
    audit = stamp_new(
        {
            "id": new_id(),
            "factory_id": factory["id"],
            "conducted_by_agent_id": uid,
            "audit_type": audit_type,
            "quality_system_score": qs,
            "social_compliance_score": sc,
            "production_capability_score": pc,
            "financial_stability_score": fs,
            "critical_findings": critical_findings,
            "score": score,
            "grade": grade,
            "approved_at": None,
            "status": "SUBMITTED",
            "_approved_dt": None,
            "_approved_seq": None,
        }
    )
    store.audits[audit["id"]] = audit
    return success_object(public(audit), 201)


@bp.route("/sourcing/audits", methods=["GET"])
def list_audits():
    require_roles(*ALL_ROLES)
    items = list(store.audits.values())
    factory_id = request.args.get("factory_id")
    agent_id = request.args.get("conducted_by_agent_id")
    if factory_id is not None:
        items = [a for a in items if a["factory_id"] == factory_id]
    if agent_id is not None:
        items = [a for a in items if a["conducted_by_agent_id"] == agent_id]
    items = sorted_created(items)
    page, limit, offset, total = paginate(items)
    return success_list([public(a) for a in page], limit, offset, total)


@bp.route("/sourcing/audits/<auditId>", methods=["GET"])
def get_audit(auditId):
    require_roles(*ALL_ROLES)
    audit = get_or_404(store.audits, auditId, "ERR_AUDIT_NOT_FOUND", "FactoryAudit")
    return success_object(public(audit))


@bp.route("/sourcing/audits/<auditId>/approve", methods=["POST"])
def approve_audit(auditId):
    require_roles("ComplianceOfficer")
    audit = get_or_404(store.audits, auditId, "ERR_AUDIT_NOT_FOUND", "FactoryAudit")
    if audit["status"] != "SUBMITTED":
        raise ApiError("ERR_AUDIT_NOT_REVIEWABLE", "Audit is not SUBMITTED", 409)
    audit["status"] = "APPROVED"
    audit["approved_at"] = now_iso()
    audit["_approved_dt"] = store.clock
    audit["_approved_seq"] = next_seq()
    touch(audit)
    if audit["audit_type"] == "ONSITE":
        factory = store.factories.get(audit["factory_id"])
        if factory is not None:
            refresh_factory_grade(factory)
    return success_object(public(audit))


@bp.route("/sourcing/audits/<auditId>/reject", methods=["POST"])
def reject_audit(auditId):
    require_roles("ComplianceOfficer")
    audit = get_or_404(store.audits, auditId, "ERR_AUDIT_NOT_FOUND", "FactoryAudit")
    if audit["status"] != "SUBMITTED":
        raise ApiError("ERR_AUDIT_NOT_REVIEWABLE", "Audit is not SUBMITTED", 409)
    audit["status"] = "REJECTED"
    touch(audit)
    return success_object(public(audit))
