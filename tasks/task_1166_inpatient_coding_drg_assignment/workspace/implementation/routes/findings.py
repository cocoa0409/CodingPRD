"""AuditFinding endpoints and the APPLY correction cascade (PRD §3.8)."""
from flask import Blueprint, request

from db import now, sort_default, stamp_new, store, touch
from errors import (ERR_FINDING_NOT_FOUND, ERR_INVALID_REQUEST,
                    ERR_INVALID_STATE, fail)
from middleware import ALL_ROLES, require_roles
from response import ok_obj, paginate
from services.calc import regroup_case
from services.core import (RESOLUTIONS, active_dx_lines, bill_for_account,
                           ser_finding)
from validators import body, req_enum

bp = Blueprint("findings", __name__)


def get_finding_or_404(finding_id):
    f = store.findings.get(finding_id)
    if f is None:
        fail(404, ERR_FINDING_NOT_FOUND, f"AuditFinding {finding_id} does not exist")
    return f


@bp.route("/audit-findings/<id>", methods=["GET"])
def get_finding(id):
    require_roles(*ALL_ROLES)
    return ok_obj(ser_finding(get_finding_or_404(id)), 200)


@bp.route("/audit-findings", methods=["GET"])
def list_findings():
    require_roles(*ALL_ROLES)
    items = list(store.findings.values())
    audit_id = request.args.get("audit_id")
    if audit_id is not None:
        items = [f for f in items if f["audit_id"] == audit_id]
    coded_case_id = request.args.get("coded_case_id")
    if coded_case_id is not None:
        items = [f for f in items if f["coded_case_id"] == coded_case_id]
    target_diagnosis_id = request.args.get("target_diagnosis_id")
    if target_diagnosis_id is not None:
        items = [f for f in items if f["target_diagnosis_id"] == target_diagnosis_id]
    status = request.args.get("status")
    if status is not None:
        items = [f for f in items if f["status"] == status]
    return paginate([ser_finding(f) for f in sort_default(items)])


def _apply_line_mutation(finding, case):
    """Hop 1: land the correction on the chart's lines."""
    chart_id = case["chart_id"]
    ftype = finding["finding_type"]
    if ftype == "POA_CORRECTION":
        line = store.dx_lines[finding["target_diagnosis_id"]]
        line["poa"] = finding["corrected_poa"]
        touch(line)
    elif ftype == "CC_MCC_REMOVED":
        line = store.dx_lines[finding["target_diagnosis_id"]]
        if line["status"] != "VOID":
            line["status"] = "VOID"
            touch(line)
    elif ftype == "PRINCIPAL_RESEQUENCE":
        line = store.dx_lines[finding["target_diagnosis_id"]]
        line["icd_code"] = finding["corrected_icd_code"]
        if finding["corrected_cc_level"] is not None:
            line["cc_level"] = finding["corrected_cc_level"]
        line["is_principal"] = True
        for other in active_dx_lines(chart_id):
            if other["id"] != line["id"] and other["is_principal"]:
                other["is_principal"] = False
                touch(other)
        touch(line)
    elif ftype == "CC_MCC_ADDED":
        seqs = [l["sequence"] for l in active_dx_lines(chart_id)]
        line = stamp_new({
            "chart_id": chart_id,
            "icd_code": finding["corrected_icd_code"],
            "poa": "Y",
            "sequence": (max(seqs) + 1) if seqs else 1,
            "is_principal": False,
            "cc_level": finding["corrected_cc_level"],
            "is_manifestation": False,
            "manifestation_of_id": None,
            "status": "ACTIVE",
        })
        store.dx_lines[line["id"]] = line
    elif ftype == "PROCEDURE_ADDED":
        proc = stamp_new({
            "chart_id": chart_id,
            "pcs_code": finding["corrected_icd_code"],
            "is_or": True,
            "performed_at": now(),
        })
        store.proc_lines[proc["id"]] = proc


@bp.route("/audit-findings/<id>/resolve", methods=["POST"])
def resolve_finding(id):
    require_roles("Auditor")
    finding = get_finding_or_404(id)
    audit = store.audits[finding["audit_id"]]
    if finding["status"] != "OPEN":
        fail(409, ERR_INVALID_STATE,
             f"Cannot resolve a finding in state {finding['status']}")
    if audit["status"] != "IN_REVIEW":
        fail(409, ERR_INVALID_STATE,
             f"Cannot resolve findings on an audit in state {audit['status']}")
    b = body()
    resolution = req_enum(b, "resolution", RESOLUTIONS)
    case = store.coded_cases[finding["coded_case_id"]]
    if resolution == "DISMISS":
        finding["delta_reimbursement_cents"] = 0
        finding["status"] = "DISMISSED"
        touch(finding)
        return ok_obj(ser_finding(finding), 200)
    # APPLY: pre-bill instrument only
    chart = store.charts[case["chart_id"]]
    bill = bill_for_account(chart["account_id"])
    if bill is not None and bill["status"] not in ("DRAFT", "READY"):
        fail(409, ERR_INVALID_STATE,
             "APPLY is permitted only while the account's bill is DRAFT or READY")
    old_expected = case["expected_reimbursement_cents"] or 0
    _apply_line_mutation(finding, case)          # hop 1
    regroup_case(case)                            # hops 2 + 3 (case + bill refresh)
    audit["applied_findings_count"] += 1          # hop 4
    touch(audit)
    finding["delta_reimbursement_cents"] = (
        (case["expected_reimbursement_cents"] or 0) - old_expected)
    finding["status"] = "APPLIED"
    touch(finding)
    return ok_obj(ser_finding(finding), 200)
