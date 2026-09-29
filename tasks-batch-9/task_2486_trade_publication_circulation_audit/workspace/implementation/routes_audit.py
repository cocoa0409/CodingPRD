"""Audit engagements, sampling, findings, and the report cascade."""
from datetime import timedelta
from decimal import Decimal

from flask import Blueprint

import calc
import validation as V
from auth import (ROLE_CIRCULATION_AUDITOR, ROLE_CIRCULATION_MANAGER,
                  ROLE_PUBLISHER_EXECUTIVE, current_user, endpoint)
from envelope import created, ok, paginate
from errors import ApiError
from lookups import get_engagement, get_finding, get_statement, get_subscriber
from store import (base_record, collection_sorted, db, now, serialize, touch)

audit_bp = Blueprint("audit", __name__)

AUDIT_READ_ROLES = (ROLE_CIRCULATION_MANAGER, ROLE_CIRCULATION_AUDITOR,
                    ROLE_PUBLISHER_EXECUTIVE)
SAMPLING_STATUSES = ("SCHEDULED", "FIELDWORK")
AUDITABLE_STATEMENT_STATUSES = ("UNDER_AUDIT", "FINDINGS_OPEN")


def _statement_of(engagement):
    return db.statements.get(engagement["statement_id"])


def _refresh_engagement_findings(engagement):
    engagement["open_findings_count"] = len([
        f for f in calc.findings_of(engagement["id"])
        if f["status"] in calc.LIVE_FINDING_STATUSES])


# --------------------------------------------------------------------------
# POST /circulation/audit-engagements
# --------------------------------------------------------------------------
@audit_bp.route("/circulation/audit-engagements", methods=["POST"])
@endpoint(ROLE_CIRCULATION_AUDITOR)
def create_engagement():
    payload = V.body()
    stmt = get_statement(payload.get("statement_id"))
    fields = V.parse(payload, [
        V.f_id("statement_id"),
        V.f_str("auditor_org", max_len=120),
        V.f_dt("fieldwork_start"),
        V.f_dt("fieldwork_end"),
        V.f_int("sample_size", minimum=1),
    ])

    if stmt["status"] != "FILED":
        raise ApiError("ERR_INVALID_STATE",
                       "An engagement may only be opened against a FILED statement.")

    if not fields["fieldwork_start"] < fields["fieldwork_end"]:
        raise ApiError("ERR_INVALID_PERIOD_RANGE",
                       "fieldwork_start must be strictly before fieldwork_end.")

    buffer_gap = timedelta(days=calc.AUDIT_WINDOW_BUFFER_DAYS)
    for other in db.engagements.values():
        if other["status"] == "REPORT_ISSUED":
            continue
        other_stmt = db.statements.get(other["statement_id"])
        if other_stmt is None or other_stmt["publication_id"] != stmt["publication_id"]:
            continue
        if fields["fieldwork_end"] < other["fieldwork_start"]:
            gap = other["fieldwork_start"] - fields["fieldwork_end"]
        elif other["fieldwork_end"] < fields["fieldwork_start"]:
            gap = fields["fieldwork_start"] - other["fieldwork_end"]
        else:
            gap = timedelta(0)
        if gap < buffer_gap:
            raise ApiError("ERR_AUDIT_WINDOW_CONFLICT",
                           "The fieldwork window is within %s days of another engagement "
                           "on this publication." % calc.AUDIT_WINDOW_BUFFER_DAYS)

    engagement = base_record()
    engagement.update({
        "statement_id": stmt["id"],
        "auditor_org": fields["auditor_org"],
        "fieldwork_start": fields["fieldwork_start"],
        "fieldwork_end": fields["fieldwork_end"],
        "sample_size": fields["sample_size"],
        "sample_verified_count": 0,
        "verified_qualified_copies": 0,
        "open_findings_count": 0,
        "status": "SCHEDULED",
        "report_issued_at": None,
        "_sampled": [],
    })
    db.engagements[engagement["id"]] = engagement

    stmt["status"] = "UNDER_AUDIT"
    touch(stmt)
    return created(serialize(engagement))


@audit_bp.route("/circulation/statements/<stmt_id>/audit-engagements", methods=["GET"])
@endpoint(*AUDIT_READ_ROLES)
def list_engagements(stmt_id):
    stmt = get_statement(stmt_id)
    status = V.filter_enum("status", V.ENGAGEMENT_STATUSES)
    rows = [e for e in db.engagements.values() if e["statement_id"] == stmt["id"]]
    if status:
        rows = [e for e in rows if e["status"] == status]
    return paginate(collection_sorted(rows))


# --------------------------------------------------------------------------
# POST /circulation/audit-engagements/{id}/record-sample-verification
# --------------------------------------------------------------------------
@audit_bp.route("/circulation/audit-engagements/<eng_id>/record-sample-verification",
                methods=["POST"])
@endpoint(ROLE_CIRCULATION_AUDITOR)
def record_sample_verification(eng_id):
    engagement = get_engagement(eng_id)
    payload = V.body()
    sub = get_subscriber(payload.get("subscriber_id"))
    fields = V.parse(payload, [
        V.f_id("subscriber_id"),
        V.f_bool("evidence_ok"),
        V.f_int("verified_copies", minimum=0),
    ])

    if engagement["status"] == "REPORT_ISSUED":
        raise ApiError("ERR_ALREADY_TERMINAL", "This engagement has issued its report.")
    stmt = _statement_of(engagement)
    if stmt is None or stmt["status"] not in AUDITABLE_STATEMENT_STATUSES:
        raise ApiError("ERR_INVALID_STATE",
                       "The statement under audit must be UNDER_AUDIT or FINDINGS_OPEN.")
    if engagement["status"] not in SAMPLING_STATUSES:
        raise ApiError("ERR_SAMPLE_LIMIT_EXCEEDED",
                       "The engagement has reached RECONCILIATION and takes no further "
                       "sample records.")
    if sub["id"] in engagement["_sampled"]:
        raise ApiError("ERR_SAMPLE_LIMIT_EXCEEDED",
                       "This recipient has already been sampled on this engagement.")

    engagement["_sampled"].append(sub["id"])
    engagement["sample_verified_count"] = engagement["sample_verified_count"] + 1
    if fields["evidence_ok"]:
        engagement["verified_qualified_copies"] = (
            engagement["verified_qualified_copies"] + fields["verified_copies"])
    if engagement["status"] == "SCHEDULED":
        engagement["status"] = "FIELDWORK"
    if engagement["sample_verified_count"] >= engagement["sample_size"]:
        engagement["status"] = "RECONCILIATION"
    touch(engagement)
    return ok(serialize(engagement))


# --------------------------------------------------------------------------
# POST /circulation/audit-engagements/{id}/issue-report
# --------------------------------------------------------------------------
@audit_bp.route("/circulation/audit-engagements/<eng_id>/issue-report", methods=["POST"])
@endpoint(ROLE_CIRCULATION_AUDITOR)
def issue_report(eng_id):
    engagement = get_engagement(eng_id)
    payload = V.body()
    V.parse(payload, [V.f_str("report_note", required=False, max_len=1000, default=None)])

    if engagement["status"] == "REPORT_ISSUED":
        raise ApiError("ERR_ALREADY_TERMINAL", "This engagement has issued its report.")
    if engagement["status"] != "RECONCILIATION":
        raise ApiError("ERR_INVALID_STATE",
                       "The engagement must be in RECONCILIATION to issue its report.")
    stmt = _statement_of(engagement)
    if stmt is None or stmt["status"] not in AUDITABLE_STATEMENT_STATUSES:
        raise ApiError("ERR_INVALID_STATE",
                       "The statement under audit must be UNDER_AUDIT or FINDINGS_OPEN.")

    pub = db.publications.get(stmt["publication_id"])
    discrepancy_copies, discrepancy_pct = calc.reconciliation(stmt, engagement)
    materiality = Decimal(pub["materiality_pct"]) if pub else Decimal("0.00")
    condemning = discrepancy_pct >= materiality

    if not condemning and stmt["status"] == "FINDINGS_OPEN":
        raise ApiError("ERR_OPEN_FINDINGS_UNRESOLVED",
                       "The engagement still carries unresolved findings.")

    at = now()
    stmt["discrepancy_copies"] = discrepancy_copies
    stmt["discrepancy_pct"] = discrepancy_pct
    engagement["report_issued_at"] = at
    engagement["status"] = "REPORT_ISSUED"
    touch(engagement)

    if not condemning:
        stmt["status"] = "AUDIT_CLEARED"
        touch(stmt)
        return ok(serialize(engagement))

    # ---- condemning report: the five-hop cascade of PRD 3.9
    stmt["status"] = "RESTATEMENT_REQUIRED"
    touch(stmt)
    if pub is not None:
        calc.recompute_publication(pub)
        touch(pub)
        for contract in collection_sorted(calc.contracts_of(pub["id"])):
            if contract["guarantee_status"] != "ACTIVE":
                continue
            contract["guarantee_status"] = "SUSPENDED_PENDING_RESTATEMENT"
            for obligation in collection_sorted(calc.make_goods_of(contract["id"])):
                if obligation["status"] not in ("PENDING", "OFFERED"):
                    continue
                obligation["status"] = "VOID"
                obligation["closed_reason"] = "RESTATEMENT_REQUIRED_CASCADE"
                touch(obligation)
            calc.recompute_contract_ledger(contract)
            touch(contract)
    return ok(serialize(engagement))


# --------------------------------------------------------------------------
# findings
# --------------------------------------------------------------------------
@audit_bp.route("/circulation/audit-findings", methods=["POST"])
@endpoint(ROLE_CIRCULATION_AUDITOR)
def create_finding():
    payload = V.body()
    sub = None
    if isinstance(payload, dict) and payload.get("subscriber_id") is not None:
        sub = get_subscriber(payload.get("subscriber_id"))
    engagement = get_engagement(payload.get("engagement_id"))
    fields = V.parse(payload, [
        V.f_id("engagement_id"),
        V.f_id("subscriber_id", required=False, default=None),
        V.f_enum("finding_type", V.FINDING_TYPES),
        V.f_enum("severity", V.SEVERITIES),
        V.f_int("affected_copies", minimum=0),
    ])

    if engagement["status"] == "REPORT_ISSUED":
        raise ApiError("ERR_ALREADY_TERMINAL", "This engagement has issued its report.")
    stmt = _statement_of(engagement)
    if stmt is None or stmt["status"] != "UNDER_AUDIT":
        raise ApiError("ERR_INVALID_STATE",
                       "A finding may only be raised against a statement in UNDER_AUDIT.")
    if engagement["status"] not in ("FIELDWORK", "RECONCILIATION"):
        raise ApiError("ERR_INVALID_STATE",
                       "The engagement must be in FIELDWORK or RECONCILIATION.")

    finding = base_record()
    finding.update({
        "engagement_id": engagement["id"],
        "subscriber_id": sub["id"] if sub else None,
        "finding_type": fields["finding_type"],
        "severity": fields["severity"],
        "affected_copies": fields["affected_copies"],
        "status": "OPEN",
        "raised_by_user_id": current_user(),
        "response_note": None,
        "response_count": 0,
        "resolved_at": None,
    })
    db.findings[finding["id"]] = finding

    stmt["status"] = "FINDINGS_OPEN"
    touch(stmt)
    _refresh_engagement_findings(engagement)
    touch(engagement)
    pub = db.publications.get(stmt["publication_id"])
    if pub is not None:
        calc.recompute_publication(pub)
        touch(pub)
    return created(serialize(finding))


@audit_bp.route("/circulation/audit-findings/<finding_id>", methods=["GET"])
@endpoint(*AUDIT_READ_ROLES)
def read_finding(finding_id):
    return ok(serialize(get_finding(finding_id)))


@audit_bp.route("/circulation/audit-findings", methods=["GET"])
@endpoint(*AUDIT_READ_ROLES)
def list_findings():
    engagement_id = V.filter_str("engagement_id")
    subscriber_id = V.filter_str("subscriber_id")
    status = V.filter_enum("status", V.FINDING_STATUSES)
    severity = V.filter_enum("severity", V.SEVERITIES)
    rows = list(db.findings.values())
    if engagement_id:
        rows = [f for f in rows if f["engagement_id"] == engagement_id]
    if subscriber_id:
        rows = [f for f in rows if f["subscriber_id"] == subscriber_id]
    if status:
        rows = [f for f in rows if f["status"] == status]
    if severity:
        rows = [f for f in rows if f["severity"] == severity]
    return paginate(collection_sorted(rows))


@audit_bp.route("/circulation/audit-findings/<finding_id>/respond", methods=["POST"])
@endpoint(ROLE_CIRCULATION_MANAGER)
def respond_to_finding(finding_id):
    finding = get_finding(finding_id)
    payload = V.body()
    fields = V.parse(payload, [V.f_str("response_note", max_len=1000)])

    if finding["status"] == "ACCEPTED_RESOLVED":
        raise ApiError("ERR_ALREADY_TERMINAL", "This finding is already resolved.")
    if finding["status"] not in ("OPEN", "REJECTED_REOPENED"):
        raise ApiError("ERR_INVALID_STATE",
                       "Only an OPEN or REJECTED_REOPENED finding may be answered.")

    finding["status"] = "RESPONSE_SUBMITTED"
    finding["response_note"] = fields["response_note"]
    finding["response_count"] = finding["response_count"] + 1
    touch(finding)
    return ok(serialize(finding))


@audit_bp.route("/circulation/audit-findings/<finding_id>/reject-response", methods=["POST"])
@endpoint(ROLE_CIRCULATION_AUDITOR)
def reject_finding_response(finding_id):
    finding = get_finding(finding_id)
    payload = V.body()
    fields = V.parse(payload, [V.f_str("rejection_note", max_len=1000)])

    if finding["status"] == "ACCEPTED_RESOLVED":
        raise ApiError("ERR_ALREADY_TERMINAL", "This finding is already resolved.")
    if finding["status"] != "RESPONSE_SUBMITTED":
        raise ApiError("ERR_INVALID_STATE",
                       "Only a RESPONSE_SUBMITTED finding may be refused.")

    finding["status"] = "REJECTED_REOPENED"
    finding["_rejection_note"] = fields["rejection_note"]
    touch(finding)
    return ok(serialize(finding))


@audit_bp.route("/circulation/audit-findings/<finding_id>/accept-resolution", methods=["POST"])
@endpoint(ROLE_CIRCULATION_AUDITOR)
def accept_finding_resolution(finding_id):
    finding = get_finding(finding_id)
    payload = V.body()
    V.parse(payload, [V.f_str("resolution_note", required=False, max_len=1000, default=None)])

    if finding["status"] == "ACCEPTED_RESOLVED":
        raise ApiError("ERR_ALREADY_TERMINAL", "This finding is already resolved.")
    if finding["status"] != "RESPONSE_SUBMITTED":
        raise ApiError("ERR_INVALID_STATE",
                       "Only a RESPONSE_SUBMITTED finding may be accepted.")
    if current_user() == finding["raised_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "The auditor who raised a finding may not accept its resolution.")

    finding["status"] = "ACCEPTED_RESOLVED"
    finding["resolved_at"] = now()
    touch(finding)

    engagement = db.engagements.get(finding["engagement_id"])
    if engagement is not None:
        _refresh_engagement_findings(engagement)
        touch(engagement)
        stmt = _statement_of(engagement)
        if stmt is not None:
            if engagement["open_findings_count"] == 0 and stmt["status"] == "FINDINGS_OPEN":
                stmt["status"] = "UNDER_AUDIT"
                touch(stmt)
            pub = db.publications.get(stmt["publication_id"])
            if pub is not None:
                calc.recompute_publication(pub)
                touch(pub)
    return ok(serialize(finding))
