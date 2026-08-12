"""CodingAudit endpoints (PRD §3.8)."""
from flask import Blueprint, request

from db import sort_default, stamp_new, store, touch
from errors import (ERR_AUDIT_NOT_FOUND, ERR_AUDIT_WINDOW_OVERLAP,
                    ERR_CASE_NOT_IN_SAMPLE, ERR_CODED_CASE_NOT_FOUND,
                    ERR_CODER_CREDENTIAL_INSUFFICIENT, ERR_CODER_NOT_FOUND,
                    ERR_FORBIDDEN, ERR_INVALID_REQUEST, ERR_INVALID_STATE,
                    ERR_OPEN_FINDINGS_REMAIN, ERR_SELF_AUDIT_FORBIDDEN, fail)
from middleware import ALL_ROLES, require_roles
from response import ok_obj, paginate
from services.calc import compute_accuracy, sample_cases
from services.core import (CC_LEVELS, FINDING_TYPES, POA_VALUES, RANK,
                           ser_audit, ser_finding)
from validators import body, has, opt_enum, req_dt, req_enum, req_int, req_str

bp = Blueprint("audits", __name__)

CORRECTIVE_TYPES = ("POA_CORRECTION", "CC_MCC_REMOVED", "PRINCIPAL_RESEQUENCE")


def get_audit_or_404(audit_id):
    a = store.audits.get(audit_id)
    if a is None:
        fail(404, ERR_AUDIT_NOT_FOUND, f"CodingAudit {audit_id} does not exist")
    return a


@bp.route("/audits", methods=["POST"])
def create_audit():
    uid, _ = require_roles("Auditor")
    b = body()
    # existence tier: subject coder
    subject = None
    if has(b, "subject_coder_id"):
        subject = store.coders.get(b["subject_coder_id"])
        if subject is None:
            fail(404, ERR_CODER_NOT_FOUND,
                 f"Coder {b['subject_coder_id']} does not exist")
    # business-safety tier: auditor credential, then self-audit ban
    auditor = store.coders.get(uid)
    if auditor is None or auditor["status"] != "ACTIVE" or RANK[auditor["credential"]] < RANK["CCS"]:
        fail(422, ERR_CODER_CREDENTIAL_INSUFFICIENT,
             "Auditor must be an ACTIVE coder of rank CCS or higher")
    if has(b, "subject_coder_id") and uid == b["subject_coder_id"]:
        fail(403, ERR_SELF_AUDIT_FORBIDDEN, "An auditor may not audit themselves")
    # business-constraint tier: required fields / window / sample size
    if subject is None:
        fail(400, ERR_INVALID_REQUEST, "subject_coder_id is required")
    window_start = req_dt(b, "window_start")
    window_end = req_dt(b, "window_end")
    if not window_end > window_start:
        fail(400, ERR_INVALID_REQUEST, "window_end must be strictly later than window_start")
    sample_size = req_int(b, "sample_size")
    if sample_size < 1:
        fail(400, ERR_INVALID_REQUEST, "sample_size must be >= 1")
    # temporal tier: half-open window overlap per subject
    for other in store.audits.values():
        if other["subject_coder_id"] != subject["id"]:
            continue
        if window_start < other["window_end"] and other["window_start"] < window_end:
            fail(409, ERR_AUDIT_WINDOW_OVERLAP,
                 "Audit window overlaps an existing audit for this subject coder")
    audit = stamp_new({
        "auditor_id": uid,
        "subject_coder_id": subject["id"],
        "window_start": window_start,
        "window_end": window_end,
        "sample_size": sample_size,
        "sampled_case_ids": sample_cases(subject["id"], window_start, window_end, sample_size),
        "status": "IN_REVIEW",
        "applied_findings_count": 0,
        "accuracy_code_based": None,
        "accuracy_financial": None,
    })
    store.audits[audit["id"]] = audit
    return ok_obj(ser_audit(audit), 201)


@bp.route("/audits/<id>", methods=["GET"])
def get_audit(id):
    require_roles(*ALL_ROLES)
    return ok_obj(ser_audit(get_audit_or_404(id)), 200)


@bp.route("/audits", methods=["GET"])
def list_audits():
    require_roles(*ALL_ROLES)
    items = list(store.audits.values())
    auditor_id = request.args.get("auditor_id")
    if auditor_id is not None:
        items = [a for a in items if a["auditor_id"] == auditor_id]
    subject_coder_id = request.args.get("subject_coder_id")
    if subject_coder_id is not None:
        items = [a for a in items if a["subject_coder_id"] == subject_coder_id]
    status = request.args.get("status")
    if status is not None:
        items = [a for a in items if a["status"] == status]
    return paginate([ser_audit(a) for a in sort_default(items)])


@bp.route("/audits/<id>/findings", methods=["POST"])
def create_finding(id):
    require_roles("Auditor")
    audit = get_audit_or_404(id)
    b = body()
    # existence tier: referenced coded case and target line
    case = None
    if has(b, "coded_case_id"):
        case = store.coded_cases.get(b["coded_case_id"])
        if case is None:
            fail(404, ERR_CODED_CASE_NOT_FOUND,
                 f"CodedCase {b['coded_case_id']} does not exist")
    target = None
    if has(b, "target_diagnosis_id"):
        target = store.dx_lines.get(b["target_diagnosis_id"])
        if target is None or (case is not None and target["chart_id"] != case["chart_id"]):
            fail(404, ERR_INVALID_REQUEST,
                 f"target_diagnosis_id {b['target_diagnosis_id']} does not resolve")
    # state tier
    if audit["status"] != "IN_REVIEW":
        fail(409, ERR_INVALID_STATE,
             f"Cannot record findings on an audit in state {audit['status']}")
    # business-constraint tier: field validation, then sample membership
    if case is None:
        fail(400, ERR_INVALID_REQUEST, "coded_case_id is required")
    finding_type = req_enum(b, "finding_type", FINDING_TYPES)
    corrected_poa = opt_enum(b, "corrected_poa", POA_VALUES) if has(b, "corrected_poa") else None
    corrected_cc = opt_enum(b, "corrected_cc_level", CC_LEVELS) if has(b, "corrected_cc_level") else None
    corrected_code = req_str(b, "corrected_icd_code") if has(b, "corrected_icd_code") else None
    if finding_type in CORRECTIVE_TYPES and target is None:
        fail(400, ERR_INVALID_REQUEST,
             f"target_diagnosis_id is required for {finding_type}")
    if finding_type == "POA_CORRECTION" and corrected_poa is None:
        fail(400, ERR_INVALID_REQUEST, "corrected_poa is required for POA_CORRECTION")
    if finding_type in ("CC_MCC_ADDED", "PRINCIPAL_RESEQUENCE") and corrected_code is None:
        fail(400, ERR_INVALID_REQUEST,
             f"corrected_icd_code is required for {finding_type}")
    if finding_type == "CC_MCC_ADDED" and corrected_cc is None:
        fail(400, ERR_INVALID_REQUEST, "corrected_cc_level is required for CC_MCC_ADDED")
    if case["id"] not in audit["sampled_case_ids"]:
        fail(422, ERR_CASE_NOT_IN_SAMPLE,
             "coded_case_id is outside the audit's sampled_case_ids")
    finding = stamp_new({
        "audit_id": audit["id"],
        "coded_case_id": case["id"],
        "finding_type": finding_type,
        "target_diagnosis_id": target["id"] if target is not None else None,
        "corrected_poa": corrected_poa,
        "corrected_icd_code": corrected_code,
        "corrected_cc_level": corrected_cc,
        "delta_reimbursement_cents": None,
        "status": "OPEN",
    })
    store.findings[finding["id"]] = finding
    return ok_obj(ser_finding(finding), 201)


@bp.route("/audits/<id>/complete", methods=["POST"])
def complete_audit(id):
    uid, _ = require_roles("Auditor")
    audit = get_audit_or_404(id)
    if audit["auditor_id"] != uid:
        fail(403, ERR_FORBIDDEN, "Only the audit's own auditor may complete it")
    if audit["status"] != "IN_REVIEW":
        fail(409, ERR_INVALID_STATE,
             f"Cannot complete an audit in state {audit['status']}")
    if any(f["audit_id"] == audit["id"] and f["status"] == "OPEN"
           for f in store.findings.values()):
        fail(409, ERR_OPEN_FINDINGS_REMAIN,
             "The audit still has OPEN findings")
    code_based, financial = compute_accuracy(audit)
    audit["accuracy_code_based"] = code_based
    audit["accuracy_financial"] = financial
    audit["status"] = "COMPLETED"
    touch(audit)
    coder = store.coders.get(audit["subject_coder_id"])
    if coder is not None:
        coder["accuracy_running"] = code_based
        coder["credential_review_required"] = code_based < 0.9500
        touch(coder)
    return ok_obj(ser_audit(audit), 200)
