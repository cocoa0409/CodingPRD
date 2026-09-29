"""Audit engagements, findings and underreporting recovery (PRD 3.7)."""
from flask import Blueprint

import constants as K
from auth import enforce_scope, guard
from calc import audit_recovery, engagement_findings
from cascades import audit_rights_alive
from common import (
    BUSINESS_READ_ROLES,
    created,
    list_endpoint,
    ok,
    read_endpoint,
    scope_from_body_agreement,
)
from errors import ApiError
from lookup import must, put
from store import D, db, new_entity, now, touch
from validation import bad, check_body, field

bp = Blueprint("audits", __name__)
BASE = "/carriage/audit-engagements"
FINDINGS_BASE = "/carriage/audit-findings"

ENGAGEMENT_ACTIONS = ["START_FIELDWORK", "ISSUE_FINDINGS", "CLOSE_NO_FINDING"]


def _in_sample(engagement, period_month):
    return (
        engagement["sample_period_start"]
        <= period_month
        <= engagement["sample_period_end"]
    )


@bp.route(BASE, methods=["POST"])
def create_engagement():
    caller = guard(["AuditManager"])
    scope_from_body_agreement(caller)
    body = check_body(
        {
            "agreement_id": field("id", required=True),
            "sample_period_start": field("period", required=True),
            "sample_period_end": field("period", required=True),
            "rate_basis": field("enum", required=True, enum=K.RATE_BASES),
        }
    )
    if body["sample_period_end"] < body["sample_period_start"]:
        bad("sample_period_end must be at or after sample_period_start")

    agreement = must("agreement", body["agreement_id"])

    if not audit_rights_alive(agreement, body["sample_period_end"]):
        raise ApiError(
            "ERR_AUDIT_RIGHTS_EXPIRED",
            "the audit rights for this sample have lapsed",
        )

    record = new_entity()
    record.update(
        {
            "agreement_id": agreement["id"],
            "sample_period_start": body["sample_period_start"],
            "sample_period_end": body["sample_period_end"],
            "rate_basis": body["rate_basis"],
            "total_variance_subscribers": 0,
            "total_reported_subscribers": 0,
            "underreporting_pct": D(0),
            "penalty_multiplier": D("1.0"),
            "base_recovery_cents": 0,
            "interest_cents": 0,
            "audit_cost_shift_cents": 0,
            "recovery_amount_cents": 0,
            "recovery_invoice_id": None,
            "findings_issued_at": None,
            "status": "OPENED",
            "_findings_issued_by": None,
        }
    )
    put("engagement", record)
    return created(record)


@bp.route(BASE, methods=["GET"])
def list_engagements():
    return list_endpoint(
        "engagement",
        BUSINESS_READ_ROLES,
        ["agreement_id", "status", "recovery_invoice_id", "rate_basis"],
    )


@bp.route(BASE + "/<engagement_id>", methods=["GET"])
def read_engagement(engagement_id):
    return read_endpoint("engagement", BUSINESS_READ_ROLES, engagement_id)


@bp.route(BASE + "/<engagement_id>/lifecycle", methods=["POST"])
def engagement_lifecycle(engagement_id):
    caller = guard(["AuditManager"])
    body = check_body(
        {"action": field("enum", required=True, enum=ENGAGEMENT_ACTIONS)}
    )
    engagement = must("engagement", engagement_id)
    agreement = db.agreements.get(engagement["agreement_id"])
    enforce_scope(caller, agreement["distributor_id"] if agreement else None)
    action = body["action"]

    if action == "START_FIELDWORK":
        if engagement["status"] != "OPENED":
            raise ApiError(
                "ERR_INVALID_ENGAGEMENT_STATE", "fieldwork starts from OPENED only"
            )
        if agreement["lifecycle_status"] not in ("EXECUTED", "SUSPENDED", "EXPIRED"):
            raise ApiError(
                "ERR_AGREEMENT_NOT_EXECUTED",
                "audit rights exist only while EXECUTED, SUSPENDED or EXPIRED",
            )
        if not audit_rights_alive(agreement, engagement["sample_period_end"]):
            raise ApiError(
                "ERR_AUDIT_RIGHTS_EXPIRED", "the audit rights for this sample have lapsed"
            )
        substantiated = [
            r
            for r in db.subscriber_reports.values()
            if r["agreement_id"] == agreement["id"]
            and r["status"] in ("ACCEPTED", "AUDIT_ADJUSTED")
            and _in_sample(engagement, r["period_month"])
        ]
        if not substantiated:
            raise ApiError(
                "ERR_AUDIT_PERIOD_NOT_REPORTED",
                "the sample contains no substantiated report",
            )
        engagement["status"] = "FIELDWORK"
        touch(engagement)
        return ok(engagement)

    if action == "ISSUE_FINDINGS":
        if engagement["status"] != "FIELDWORK":
            raise ApiError(
                "ERR_INVALID_ENGAGEMENT_STATE", "findings issue from FIELDWORK only"
            )
        findings = engagement_findings(engagement["id"])
        positive = [
            f
            for f in findings
            if max(0, f["audited_subscribers"] - f["reported_subscribers"]) > 0
        ]
        if not positive:
            raise ApiError(
                "ERR_NO_AUDIT_FINDINGS",
                "the zero-variance case must take the CLOSED_NO_FINDING branch",
            )

        result = audit_recovery(engagement, agreement)

        for stamp in result["stamps"]:
            finding = stamp["finding"]
            finding["variance_subscribers"] = stamp["variance_subscribers"]
            finding["rate_applied_cents_per_sub"] = stamp["rate_applied_cents_per_sub"]
            finding["finding_recovery_cents"] = stamp["finding_recovery_cents"]

        engagement["total_variance_subscribers"] = result["total_variance_subscribers"]
        engagement["total_reported_subscribers"] = result["total_reported_subscribers"]
        engagement["underreporting_pct"] = result["underreporting_pct"]
        engagement["penalty_multiplier"] = result["penalty_multiplier"]
        engagement["base_recovery_cents"] = result["base_recovery_cents"]
        engagement["interest_cents"] = result["interest_cents"]
        engagement["audit_cost_shift_cents"] = result["audit_cost_shift_cents"]
        engagement["recovery_amount_cents"] = result["recovery_amount_cents"]
        engagement["findings_issued_at"] = now()
        engagement["_findings_issued_by"] = caller.user_id
        engagement["status"] = "FINDINGS_ISSUED"
        touch(engagement)

        # LINK 1 - each cited report carries its own recovery
        applied_total = 0
        for stamp in result["stamps"]:
            if stamp["variance_subscribers"] <= 0:
                continue
            report = db.subscriber_reports.get(stamp["finding"]["subscriber_report_id"])
            if report is None:
                continue
            recovery = stamp["finding_recovery_cents"]
            report["audit_adjustment_cents"] += recovery
            report["license_fee_due_cents"] += recovery
            if report["status"] == "ACCEPTED":
                report["status"] = "AUDIT_ADJUSTED"
            applied_total += recovery
            touch(report)

        # LINK 2 and LINK 3 - revenue rises, the compliant run is broken
        agreement["recognized_revenue_cents"] += applied_total
        agreement["consecutive_compliant_periods"] = 0
        if agreement["penetration_breach_count"] > 0:
            agreement["penetration_compliance_status"] = "BREACH"
        touch(agreement)
        return ok(engagement)

    # CLOSE_NO_FINDING
    if engagement["status"] != "FIELDWORK":
        raise ApiError(
            "ERR_INVALID_ENGAGEMENT_STATE", "closing is possible from FIELDWORK only"
        )
    for finding in engagement_findings(engagement["id"]):
        if max(0, finding["audited_subscribers"] - finding["reported_subscribers"]) > 0:
            raise ApiError(
                "ERR_FINDINGS_PRESENT_CANNOT_CLOSE",
                "a positive-variance finding exists on this engagement",
            )
    engagement["total_variance_subscribers"] = 0
    engagement["total_reported_subscribers"] = 0
    engagement["underreporting_pct"] = D(0)
    engagement["penalty_multiplier"] = D("1.0")
    engagement["base_recovery_cents"] = 0
    engagement["interest_cents"] = 0
    engagement["audit_cost_shift_cents"] = 0
    engagement["recovery_amount_cents"] = 0
    engagement["status"] = "CLOSED_NO_FINDING"
    touch(engagement)
    return ok(engagement)


@bp.route(BASE + "/<engagement_id>/findings", methods=["POST"])
def create_finding(engagement_id):
    caller = guard(["AuditManager"])
    body = check_body(
        {
            "subscriber_report_id": field("id", required=True),
            "audited_subscribers": field("int", required=True, minimum=0),
        }
    )
    engagement = must("engagement", engagement_id)
    report = must("report", body["subscriber_report_id"])
    agreement = db.agreements.get(engagement["agreement_id"])
    enforce_scope(caller, agreement["distributor_id"] if agreement else None)

    if engagement["status"] != "FIELDWORK":
        raise ApiError(
            "ERR_INVALID_ENGAGEMENT_STATE",
            "findings are recorded only while the engagement is in FIELDWORK",
        )

    if (
        report["agreement_id"] != engagement["agreement_id"]
        or report["status"] not in ("ACCEPTED", "AUDIT_ADJUSTED")
        or not _in_sample(engagement, report["period_month"])
    ):
        raise ApiError(
            "ERR_AUDIT_PERIOD_NOT_REPORTED",
            "the cited report is not a substantiated period of this sample",
        )

    # id and created_at only: an audit finding is immutable.
    record = new_entity(versioned=False, created=True)
    record.update(
        {
            "engagement_id": engagement["id"],
            "subscriber_report_id": report["id"],
            "period_month": report["period_month"],
            "audited_subscribers": body["audited_subscribers"],
            "reported_subscribers": report["reported_subscribers"],
            "variance_subscribers": max(
                0, body["audited_subscribers"] - report["reported_subscribers"]
            ),
            "rate_applied_cents_per_sub": D(0),
            "finding_recovery_cents": 0,
        }
    )
    put("finding", record)
    return created(record)


@bp.route(FINDINGS_BASE, methods=["GET"])
def list_findings():
    return list_endpoint(
        "finding", BUSINESS_READ_ROLES, ["engagement_id", "subscriber_report_id"]
    )


@bp.route(FINDINGS_BASE + "/<finding_id>", methods=["GET"])
def read_finding(finding_id):
    return read_endpoint("finding", BUSINESS_READ_ROLES, finding_id)
