"""Monthly subscriber reports, review actions and penetration compliance."""
from flask import Blueprint

import constants as K
from auth import enforce_scope, guard
from calc import stamp_report_final, stamp_report_provisional
from cascades import block_windows_of_agreement, recompute_titles
from common import (
    BUSINESS_READ_ROLES,
    check_occ,
    created,
    list_endpoint,
    ok,
    read_endpoint,
    scope_from_body_agreement,
    sod_report_review,
)
from errors import ApiError
from lookup import must, put
from store import D, db, month_key, new_entity, now, rhu, touch
from validation import check_body, field

bp = Blueprint("reports", __name__)
BASE = "/carriage/subscriber-reports"

REVIEW_ACTIONS = ["ACCEPT", "DISPUTE", "REQUEST_RESTATEMENT", "ACCEPT_ADJUSTMENT"]


def period_inside_term(agreement, period_month):
    low = month_key(agreement["term_start_date"])
    high = month_key(agreement["term_end_date"])
    return low <= period_month <= high


def apply_penetration_compliance(agreement, report):
    """Calculation C6: inclusive comparison, both sides at four decimals."""
    compliant = rhu(D(report["penetration_pct"]), 4) >= rhu(
        D(agreement["penetration_floor_pct"]), 4
    )
    if compliant:
        agreement["consecutive_compliant_periods"] += 1
        agreement["penetration_compliance_status"] = "COMPLIANT"
        if (
            agreement["consecutive_compliant_periods"]
            >= K.PENETRATION_COMPLIANT_RESET_RUN
        ):
            # the slate is wiped, and the run itself restarts from zero
            agreement["penetration_breach_count"] = 0
            agreement["consecutive_compliant_periods"] = 0
    else:
        agreement["consecutive_compliant_periods"] = 0
        agreement["penetration_breach_count"] += 1
        agreement["penetration_compliance_status"] = "BREACH"
    return compliant


@bp.route(BASE, methods=["POST"])
def create_report():
    caller = guard(["DistributorLiaison", "RevenueAccountant"])
    scope_from_body_agreement(caller)
    body = check_body(
        {
            "agreement_id": field("id", required=True),
            "period_month": field("period", required=True),
            "reported_subscribers": field("int", required=True, minimum=0),
            "reported_tier": field("enum", required=True, enum=K.TIERS),
            "restatement_of_report_id": field("id"),
            "expected_agreement_version": field("int", required=True, minimum=0),
        }
    )
    agreement = must("agreement", body["agreement_id"])
    target = None
    if body["restatement_of_report_id"] is not None:
        target = must("report", body["restatement_of_report_id"])

    check_occ(
        agreement, body["expected_agreement_version"], "ERR_STALE_AGREEMENT_VERSION"
    )

    if target is not None:
        if (
            target["agreement_id"] != agreement["id"]
            or target["period_month"] != body["period_month"]
            or target["status"] != "RESTATED"
        ):
            raise ApiError(
                "ERR_RESTATEMENT_TARGET_INVALID",
                "the restatement target must be a RESTATED report of the same "
                "agreement and period",
            )

    distributor = db.distributors.get(agreement["distributor_id"])

    record = new_entity()
    record.update(
        {
            "agreement_id": agreement["id"],
            "period_month": body["period_month"],
            "reported_subscribers": body["reported_subscribers"],
            "reported_tier": body["reported_tier"],
            "restatement_of_report_id": body["restatement_of_report_id"],
            "invoice_id": None,
            "penetration_pct": None,
            "billable_subscribers": None,
            "rate_applied_cents_per_sub": None,
            "provisional_fee_cents": 0,
            "license_fee_due_cents": 0,
            "audit_adjustment_cents": 0,
            "tier_placement_breach": False,
            "status": "SUBMITTED",
            "accepted_at": None,
        }
    )
    stamp_report_provisional(record, agreement, distributor)
    put("report", record)

    if target is not None:
        target["status"] = "SUPERSEDED"
        touch(target)

    touch(agreement)
    return created(record)


@bp.route(BASE, methods=["GET"])
def list_reports():
    return list_endpoint(
        "report",
        BUSINESS_READ_ROLES,
        [
            "agreement_id",
            "status",
            "period_month",
            "restatement_of_report_id",
            "invoice_id",
        ],
    )


@bp.route(BASE + "/<report_id>", methods=["GET"])
def read_report(report_id):
    return read_endpoint("report", BUSINESS_READ_ROLES, report_id)


def _engagement_of_report(report_id):
    for finding in db.audit_findings.values():
        if finding["subscriber_report_id"] == report_id:
            engagement = db.audit_engagements.get(finding["engagement_id"])
            if engagement is not None:
                return engagement
    return None


@bp.route(BASE + "/<report_id>/review", methods=["POST"])
def review_report(report_id):
    caller = guard(["RevenueAccountant"])
    sod_report_review(caller, report_id)
    body = check_body(
        {
            "action": field("enum", required=True, enum=REVIEW_ACTIONS),
            "note": field("string", max_len=2000),
        }
    )
    report = must("report", report_id)
    agreement = db.agreements.get(report["agreement_id"])
    enforce_scope(caller, agreement["distributor_id"] if agreement else None)
    distributor = db.distributors.get(agreement["distributor_id"]) if agreement else None
    action = body["action"]

    if action == "ACCEPT":
        if report["status"] != "SUBMITTED":
            raise ApiError("ERR_INVALID_REPORT_STATE", "acceptance requires SUBMITTED")
        if agreement["lifecycle_status"] not in ("EXECUTED", "SUSPENDED"):
            raise ApiError(
                "ERR_AGREEMENT_NOT_EXECUTED",
                "the owning agreement is neither EXECUTED nor SUSPENDED",
            )
        for other in db.subscriber_reports.values():
            if other["id"] == report["id"]:
                continue
            if (
                other["agreement_id"] == report["agreement_id"]
                and other["period_month"] == report["period_month"]
                and other["status"] in ("ACCEPTED", "AUDIT_ADJUSTED")
            ):
                raise ApiError(
                    "ERR_DUPLICATE_ACCEPTED_PERIOD",
                    "another report for this period is already substantiated",
                )
        if not period_inside_term(agreement, report["period_month"]):
            raise ApiError(
                "ERR_PERIOD_OUTSIDE_TERM", "period_month lies outside the term"
            )

        stamp_report_final(report, agreement, distributor)
        report["status"] = "ACCEPTED"
        report["accepted_at"] = now()
        touch(report)

        # LINK 1 - revenue and compliance
        agreement["recognized_revenue_cents"] += report["license_fee_due_cents"]
        apply_penetration_compliance(agreement, report)

        # LINK 2 - the breach threshold may pull the network off the lineup
        suspending = (
            agreement["penetration_breach_count"]
            >= K.PENETRATION_BREACH_SUSPEND_THRESHOLD
            and agreement["lifecycle_status"] == "EXECUTED"
        )
        if suspending:
            agreement["lifecycle_status"] = "SUSPENDED"
            agreement["suspension_reason"] = "PENETRATION_BREACH"
        touch(agreement)

        if suspending:
            # LINK 3 and LINK 4 - windows lose their slots, titles re-derive
            recompute_titles(
                block_windows_of_agreement(agreement["id"], "AGREEMENT_SUSPENDED")
            )
        return ok(report)

    if action == "DISPUTE":
        if report["status"] != "SUBMITTED":
            raise ApiError("ERR_INVALID_REPORT_STATE", "a dispute requires SUBMITTED")
        if agreement["lifecycle_status"] not in ("EXECUTED", "SUSPENDED"):
            raise ApiError(
                "ERR_AGREEMENT_NOT_EXECUTED",
                "the owning agreement is neither EXECUTED nor SUSPENDED",
            )
        report["status"] = "DISPUTED"
        touch(report)
        return ok(report)

    if action == "REQUEST_RESTATEMENT":
        if report["status"] != "DISPUTED":
            raise ApiError(
                "ERR_INVALID_REPORT_STATE", "a restatement request requires DISPUTED"
            )
        report["status"] = "RESTATED"
        touch(report)
        return ok(report)

    # ACCEPT_ADJUSTMENT
    if report["status"] != "AUDIT_ADJUSTED":
        raise ApiError(
            "ERR_INVALID_REPORT_STATE", "accepting an adjustment requires AUDIT_ADJUSTED"
        )
    engagement = _engagement_of_report(report["id"])
    if engagement is None or engagement["status"] not in (
        "RECOVERY_INVOICED",
        "COLLECTED",
    ):
        raise ApiError(
            "ERR_INVALID_ENGAGEMENT_STATE",
            "the recovery must be billed before the adjustment can be accepted",
        )
    # audit_adjustment_cents, license_fee_due_cents and recognized revenue all
    # stay exactly as they are: the adjustment was folded in at AUDIT_ADJUSTED.
    report["status"] = "ACCEPTED"
    touch(report)
    return ok(report)
