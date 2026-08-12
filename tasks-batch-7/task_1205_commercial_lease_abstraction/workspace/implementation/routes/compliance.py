"""ComplianceDoc endpoints."""

from flask import Blueprint

from db import db, new_resource, touch
from errors import err
from response import success_object
from services import calc
from services.validate import (
    body, req_enum, req_date, filter_arg_str,
)
from routes.helpers import (
    get_lease_or_404, get_child_or_404, list_response,
)

bp = Blueprint("compliance", __name__)

DOC_KINDS = {"INSURANCE_CERT", "ESTOPPEL", "FINANCIAL_STMT", "SNDA"}


@bp.post("/lease-admin/leases/<lease_id>/compliance-docs")
def create_doc(lease_id):
    get_lease_or_404(lease_id)
    data = body()
    kind = req_enum(data, "kind", DOC_KINDS)
    period_start = req_date(data, "period_start")
    period_end = req_date(data, "period_end")
    if calc.d(period_start) >= calc.d(period_end):
        err("ERR_INVALID_DATE_RANGE", "period_start must precede period_end")
    did, common = new_resource()
    doc = {
        **common,
        "lease_id": lease_id,
        "kind": kind,
        "period_start": period_start,
        "period_end": period_end,
        "status": "SUBMITTED",
        "rejection_reason": None,
    }
    db["compliance_docs"][did] = doc
    return success_object(doc, status=201)


@bp.get("/lease-admin/leases/<lease_id>/compliance-docs")
def list_lease_docs(lease_id):
    get_lease_or_404(lease_id)
    return list_response(
        [d for d in db["compliance_docs"].values()
         if d["lease_id"] == lease_id],
        filters=[
            (filter_arg_str("kind"), lambda r, v: r["kind"] == v),
            (filter_arg_str("status"), lambda r, v: r["status"] == v),
        ])


@bp.get("/lease-admin/compliance-docs/<doc_id>")
def get_doc(doc_id):
    return success_object(
        get_child_or_404("compliance_docs", doc_id, "ComplianceDoc"))


@bp.get("/lease-admin/compliance-docs")
def list_docs_filtered():
    return list_response(db["compliance_docs"].values(), filters=[
        (filter_arg_str("lease_id"), lambda r, v: r["lease_id"] == v),
        (filter_arg_str("kind"), lambda r, v: r["kind"] == v),
        (filter_arg_str("status"), lambda r, v: r["status"] == v),
    ])


@bp.post("/lease-admin/compliance-docs/<doc_id>/start-review")
def start_review_doc(doc_id):
    doc = get_child_or_404("compliance_docs", doc_id, "ComplianceDoc")
    if doc["status"] != "SUBMITTED":
        err("ERR_INVALID_STATE", "Start-review requires status == SUBMITTED")
    doc["status"] = "UNDER_REVIEW"
    touch(doc)
    return success_object(doc)


@bp.post("/lease-admin/compliance-docs/<doc_id>/accept")
def accept_doc(doc_id):
    doc = get_child_or_404("compliance_docs", doc_id, "ComplianceDoc")
    if doc["status"] != "UNDER_REVIEW":
        err("ERR_INVALID_STATE", "Accept requires status == UNDER_REVIEW")
    # Coverage-overlap guard (pipeline step 10): no other ACCEPTED doc with
    # the same (lease, kind) overlapping the half-open coverage window.
    ns, ne = calc.d(doc["period_start"]), calc.d(doc["period_end"])
    for other in db["compliance_docs"].values():
        if other["id"] == doc["id"]:
            continue
        if other["lease_id"] == doc["lease_id"] and \
           other["kind"] == doc["kind"] and \
           other["status"] == "ACCEPTED":
            if ns < calc.d(other["period_end"]) and \
               ne > calc.d(other["period_start"]):
                err("ERR_COVERAGE_OVERLAP",
                    "An ACCEPTED document with overlapping coverage exists")
    doc["status"] = "ACCEPTED"
    touch(doc)
    return success_object(doc)


@bp.post("/lease-admin/compliance-docs/<doc_id>/reject")
def reject_doc(doc_id):
    doc = get_child_or_404("compliance_docs", doc_id, "ComplianceDoc")
    if doc["status"] != "UNDER_REVIEW":
        err("ERR_INVALID_STATE", "Reject requires status == UNDER_REVIEW")
    data = body()
    reason = data.get("rejection_reason")
    if not isinstance(reason, str) or reason == "":
        err("ERR_REJECTION_REASON_REQUIRED",
            "rejection_reason is required when rejecting a document")
    doc["rejection_reason"] = reason
    doc["status"] = "REJECTED"
    touch(doc)
    return success_object(doc)
