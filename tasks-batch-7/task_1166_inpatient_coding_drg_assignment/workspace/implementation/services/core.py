"""Domain constants, cross-aggregate lookups, and resource serializers."""
from __future__ import annotations

from decimal import Decimal

from db import iso, store

# ---- domain constants (from SCAFFOLD calculations/roles) ----
RANK = {"CCA": 1, "CCS": 2, "RHIT": 3, "RHIA": 4}
ACUITY_MIN_RANK = {"MEDICAL_LOW": 1, "MEDICAL_HIGH": 2, "SURGICAL": 3}
ACUITY_WEIGHT = {"MEDICAL_LOW": 1, "MEDICAL_HIGH": 2, "SURGICAL": 3}
ACUITY_PRIORITY = {"MEDICAL_LOW": 0, "MEDICAL_HIGH": 10, "SURGICAL": 20}

PATIENT_CLASSES = ("INPATIENT", "OBSERVATION")
FINANCIAL_CLASSES = ("MEDICARE", "MEDICAID", "COMMERCIAL", "SELF_PAY")
DISCHARGE_DISPOSITIONS = ("HOME", "SNF", "REHAB", "EXPIRED", "AMA")
ACUITIES = ("MEDICAL_LOW", "MEDICAL_HIGH", "SURGICAL")
DEFICIENCY_TYPES = ("MISSING_H_AND_P", "MISSING_DISCHARGE_SUMMARY",
                    "MISSING_SIGNATURE", "MISSING_OP_REPORT")
POA_VALUES = ("Y", "N", "U", "W", "EXEMPT")
CC_LEVELS = ("NONE", "CC", "MCC")
CREDENTIALS = ("CCA", "CCS", "RHIT", "RHIA")
GROUPER_VARIANTS = ("MS_DRG", "AP_DRG")
FINDING_TYPES = ("PRINCIPAL_RESEQUENCE", "POA_CORRECTION", "CC_MCC_ADDED",
                 "CC_MCC_REMOVED", "PROCEDURE_ADDED")
RESOLUTIONS = ("APPLY", "DISMISS")

NON_TERMINAL_ASSIGNMENT = ("QUEUED", "ASSIGNED", "IN_PROGRESS", "SUBMITTED", "RETURNED")

# ---- cross-aggregate lookups ----

def chart_for_account(account_id):
    for c in store.charts.values():
        if c["account_id"] == account_id:
            return c
    return None


def bill_for_account(account_id):
    for b in store.bills.values():
        if b["account_id"] == account_id:
            return b
    return None


def case_for_chart(chart_id):
    for c in store.coded_cases.values():
        if c["chart_id"] == chart_id:
            return c
    return None


def assignment_for_chart(chart_id, statuses=None):
    for a in store.assignments.values():
        if a["chart_id"] == chart_id and (statuses is None or a["status"] in statuses):
            return a
    return None


def active_dx_lines(chart_id):
    return [l for l in store.dx_lines.values()
            if l["chart_id"] == chart_id and l["status"] == "ACTIVE"]


def proc_lines(chart_id):
    return [p for p in store.proc_lines.values() if p["chart_id"] == chart_id]


# ---- serializers (internal datetimes/Decimals -> JSON-safe values) ----
# Common fields on every resource: id, created_at, updated_at, version.

def _common(r):
    return {
        "id": r["id"],
        "created_at": iso(r["created_at"]),
        "updated_at": iso(r["updated_at"]),
        "version": r["version"],
    }


def ser_account(a):
    d = _common(a)
    d.update({
        "mrn": a["mrn"],
        "admit_at": iso(a["admit_at"]),
        "discharge_at": iso(a["discharge_at"]),
        "patient_class": a["patient_class"],
        "financial_class": a["financial_class"],
        "discharge_disposition": a["discharge_disposition"],
        "total_charges_cents": a["total_charges_cents"],
        "status": a["status"],
        "dnfb_flag": a["dnfb_flag"],
        "dnfb_flagged_at": iso(a["dnfb_flagged_at"]),
    })
    return d


def ser_chart(c):
    d = _common(c)
    d.update({
        "account_id": c["account_id"],
        "acuity": c["acuity"],
        "status": c["status"],
        "open_deficiency_count": c["open_deficiency_count"],
    })
    return d


def ser_deficiency(x):
    d = _common(x)
    d.update({
        "chart_id": x["chart_id"],
        "type": x["type"],
        "due_at": iso(x["due_at"]),
        "status": x["status"],
        "resolved_at": iso(x["resolved_at"]),
    })
    return d


def ser_dx_line(l):
    d = _common(l)
    d.update({
        "chart_id": l["chart_id"],
        "icd_code": l["icd_code"],
        "poa": l["poa"],
        "sequence": l["sequence"],
        "is_principal": l["is_principal"],
        "cc_level": l["cc_level"],
        "is_manifestation": l["is_manifestation"],
        "manifestation_of_id": l["manifestation_of_id"],
        "status": l["status"],
    })
    return d


def ser_proc_line(p):
    d = _common(p)
    d.update({
        "chart_id": p["chart_id"],
        "pcs_code": p["pcs_code"],
        "is_or": p["is_or"],
        "performed_at": iso(p["performed_at"]),
    })
    return d


def ser_coder(c):
    d = _common(c)
    d.update({
        "employee_no": c["employee_no"],
        "full_name": c["full_name"],
        "credential": c["credential"],
        "status": c["status"],
        "workload_units": c["workload_units"],
        "accepted_count": c["accepted_count"],
        "accepted_weighted_units": c["accepted_weighted_units"],
        "productivity_units_per_day": c["productivity_units_per_day"],
        "accuracy_running": c["accuracy_running"],
        "credential_review_required": c["credential_review_required"],
    })
    return d


def ser_assignment(a):
    d = _common(a)
    d.update({
        "chart_id": a["chart_id"],
        "coder_id": a["coder_id"],
        "status": a["status"],
        "priority_score": a["priority_score"],
        "due_at": iso(a["due_at"]),
        "assigned_at": iso(a["assigned_at"]),
        "started_at": iso(a["started_at"]),
        "submitted_at": iso(a["submitted_at"]),
        "accepted_at": iso(a["accepted_at"]),
        "returned_count": a["returned_count"],
        "return_reason": a["return_reason"],
    })
    return d


def ser_case(c):
    d = _common(c)
    w = c["relative_weight"]
    d.update({
        "chart_id": c["chart_id"],
        "principal_dx_id": c["principal_dx_id"],
        "grouper_variant": c["grouper_variant"],
        "base_partition": c["base_partition"],
        "severity_level": c["severity_level"],
        "relative_weight": (float(w) if isinstance(w, Decimal) else w),
        "expected_reimbursement_cents": c["expected_reimbursement_cents"],
        "status": c["status"],
    })
    return d


def ser_bill(b):
    d = _common(b)
    d.update({
        "account_id": b["account_id"],
        "status": b["status"],
        "expected_reimbursement_cents": b["expected_reimbursement_cents"],
        "billed_amount_cents": b["billed_amount_cents"],
        "paid_amount_cents": b["paid_amount_cents"],
        "net_receivable_cents": b["net_receivable_cents"],
        "finalized_at": iso(b["finalized_at"]),
        "paid_at": iso(b["paid_at"]),
    })
    return d


def ser_sweep(s):
    d = _common(s)
    d.update({
        "threshold_days": s["threshold_days"],
        "as_of": iso(s["as_of"]),
        "flagged_count": s["flagged_count"],
        "flagged_account_ids": list(s["flagged_account_ids"]),
        "total_outstanding_cents": s["total_outstanding_cents"],
    })
    return d


def ser_audit(a):
    d = _common(a)
    d.update({
        "auditor_id": a["auditor_id"],
        "subject_coder_id": a["subject_coder_id"],
        "window_start": iso(a["window_start"]),
        "window_end": iso(a["window_end"]),
        "sample_size": a["sample_size"],
        "sampled_case_ids": list(a["sampled_case_ids"]),
        "status": a["status"],
        "applied_findings_count": a["applied_findings_count"],
        "accuracy_code_based": a["accuracy_code_based"],
        "accuracy_financial": a["accuracy_financial"],
    })
    return d


def ser_finding(f):
    d = _common(f)
    d.update({
        "audit_id": f["audit_id"],
        "coded_case_id": f["coded_case_id"],
        "finding_type": f["finding_type"],
        "target_diagnosis_id": f["target_diagnosis_id"],
        "corrected_poa": f["corrected_poa"],
        "corrected_icd_code": f["corrected_icd_code"],
        "corrected_cc_level": f["corrected_cc_level"],
        "delta_reimbursement_cents": f["delta_reimbursement_cents"],
        "status": f["status"],
    })
    return d


def ser_review(r):
    d = _common(r)
    d.update({
        "bill_id": r["bill_id"],
        "payer_ref": r["payer_ref"],
        "claimed_delta_cents": r["claimed_delta_cents"],
        "status": r["status"],
    })
    return d


def ser_rebill(r):
    d = _common(r)
    d.update({
        "review_id": r["review_id"],
        "delta_cents": r["delta_cents"],
        "requested_by": r["requested_by"],
        "decided_by": r["decided_by"],
        "status": r["status"],
    })
    return d
