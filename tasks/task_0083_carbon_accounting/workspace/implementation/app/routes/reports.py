"""Report endpoints: create, compile, verify, request-revisions, reopen, publish."""
from __future__ import annotations

from decimal import Decimal

from flask import Blueprint, g

from ..auth import require_auth
from ..errors import api_error
from ..response import success_envelope
from ..services.calculations import compile_totals, compute_net
from ..store import store, now_ts
from ..utils import (
    check_version,
    get_json_body,
    require_enum,
    require_str,
)
from ._helpers import get_org_or_404, get_report_or_404


reports_bp = Blueprint("reports", __name__)


STANDARDS = {"GHG_PROTOCOL", "ISO_14064", "CDP", "TCFD", "LOCAL_MANDATORY"}

PINNED_TOTAL_FIELDS = [
    "gross_scope1_kg_co2e",
    "gross_scope2_location_kg_co2e",
    "gross_scope2_market_kg_co2e",
    "gross_scope3_kg_co2e",
    "applied_offsets_kg_co2e",
    "net_emissions_kg_co2e",
    "intensity_per_revenue",
    "intensity_per_employee",
    "intensity_per_unit_output",
    "completeness_pct",
    "completeness_passes",
    "assurance_ready",
]


def _bump(row: dict) -> None:
    row["updated_at"] = now_ts()
    row["version"] = row.get("version", 0) + 1


@reports_bp.route("/organizations/<org_id>/reports", methods=["POST"])
@require_auth(["DataSteward"])
def create_report(org_id):
    get_org_or_404(org_id)
    body = get_json_body()

    period_id = body.get("reporting_period_id")
    if not isinstance(period_id, str) or not period_id:
        raise api_error("ERR_VALIDATION_FAILED", "reporting_period_id is required")
    period = store.reporting_periods.get(period_id)
    if not period:
        raise api_error("ERR_NOT_FOUND", "reporting_period_id not found")
    if period.get("organization_id") != org_id:
        raise api_error("ERR_CROSS_ORG_REFERENCE", "reporting_period_id belongs to a different organization")

    standard = require_enum(body, "standard", STANDARDS)

    payload = {
        "organization_id": org_id,
        "reporting_period_id": period_id,
        "standard": standard,
        "gross_scope1_kg_co2e": None,
        "gross_scope2_location_kg_co2e": None,
        "gross_scope2_market_kg_co2e": None,
        "gross_scope3_kg_co2e": None,
        "applied_offsets_kg_co2e": None,
        "net_emissions_kg_co2e": None,
        "intensity_per_revenue": None,
        "intensity_per_employee": None,
        "intensity_per_unit_output": None,
        "completeness_pct": None,
        "completeness_passes": None,
        "assurance_ready": None,
        "compiled_at": None,
        "verified_at": None,
        "verifier_user_id": None,
        "published_at": None,
        "status": "DRAFT",
    }
    with store.lock:
        store.stamp_create(payload)
        store.reports[payload["id"]] = payload
    return success_envelope(payload, status=201)


@reports_bp.route("/organizations/<org_id>/reports/<report_id>/compile", methods=["POST"])
@require_auth(["DataSteward"])
def compile_report(org_id, report_id):
    get_org_or_404(org_id)
    report = get_report_or_404(org_id, report_id)
    body = get_json_body()

    if report.get("status") != "DRAFT":
        raise api_error("ERR_INVALID_STATE", "Report must be DRAFT to compile")
    check_version(body, report)

    period = store.reporting_periods.get(report["reporting_period_id"])
    if not period or period.get("status") not in ("OPEN", "CLOSED"):
        raise api_error("ERR_INVALID_STATE", "Reporting period must be OPEN or CLOSED")

    # No STALE EmissionRecord on this period
    for er in store.emission_records.values():
        if er.get("reporting_period_id") == report["reporting_period_id"] and er.get("status") == "STALE":
            raise api_error("ERR_INVALID_STATE", "Period has STALE EmissionRecords")

    # Traceability check: every FRESH EmissionRecord -> factor with status ACTIVE/SUPERSEDED and non-empty traceability_url
    for er in store.emission_records.values():
        if er.get("reporting_period_id") != report["reporting_period_id"]:
            continue
        if er.get("status") != "FRESH":
            continue
        f = store.emission_factors.get(er.get("emission_factor_id"))
        if not f:
            raise api_error("ERR_TRACEABILITY_MISSING", "Pinned factor not found")
        if f.get("status") not in ("ACTIVE", "SUPERSEDED"):
            raise api_error("ERR_TRACEABILITY_MISSING", "Pinned factor not in ACTIVE/SUPERSEDED")
        url = f.get("traceability_url")
        if not isinstance(url, str) or not url:
            raise api_error("ERR_TRACEABILITY_MISSING", "Pinned factor lacks traceability_url")

    actor_user_id = g.user_id
    actor_role = g.user_role

    with store.lock:
        totals = compile_totals(report)
        for k, v in totals.items():
            report[k] = v
        report["compiled_at"] = now_ts()
        report["status"] = "UNDER_REVIEW"
        _bump(report)
        store.append_audit(
            organization_id=org_id,
            actor_user_id=actor_user_id,
            actor_role=actor_role,
            event_type="REPORT_COMPILE",
            target_entity="Report",
            target_id=report["id"],
            payload_json={"reporting_period_id": report["reporting_period_id"]},
        )
    return success_envelope(report)


@reports_bp.route("/organizations/<org_id>/reports/<report_id>/verify", methods=["POST"])
@require_auth(["Verifier"])
def verify_report(org_id, report_id):
    get_org_or_404(org_id)
    report = get_report_or_404(org_id, report_id)
    body = get_json_body()

    if report.get("status") != "UNDER_REVIEW":
        raise api_error("ERR_INVALID_STATE", "Report must be UNDER_REVIEW to verify")
    check_version(body, report)

    # Segregation of duties (priority 6 — before assurance check)
    actor_user_id = g.user_id
    actor_role = g.user_role
    for ad in store.activity_data.values():
        if ad.get("reporting_period_id") == report["reporting_period_id"]:
            if ad.get("entered_by_user_id") == actor_user_id:
                raise api_error(
                    "ERR_SEGREGATION_OF_DUTIES",
                    "Same user cannot enter activity data and verify the report",
                )

    # Assurance readiness
    if not report.get("assurance_ready"):
        raise api_error("ERR_ASSURANCE_NOT_READY", "Report assurance_ready==false")

    with store.lock:
        report["status"] = "VERIFIED"
        report["verified_at"] = now_ts()
        report["verifier_user_id"] = actor_user_id
        _bump(report)
        store.append_audit(
            organization_id=org_id,
            actor_user_id=actor_user_id,
            actor_role=actor_role,
            event_type="REPORT_VERIFY",
            target_entity="Report",
            target_id=report["id"],
            payload_json={},
        )
    return success_envelope(report)


@reports_bp.route("/organizations/<org_id>/reports/<report_id>/request-revisions", methods=["POST"])
@require_auth(["Verifier"])
def request_revisions(org_id, report_id):
    get_org_or_404(org_id)
    report = get_report_or_404(org_id, report_id)
    body = get_json_body()

    if report.get("status") != "UNDER_REVIEW":
        raise api_error("ERR_INVALID_STATE", "Report must be UNDER_REVIEW to request revisions")
    check_version(body, report)

    with store.lock:
        report["status"] = "REVISIONS_REQUIRED"
        _bump(report)
    return success_envelope(report)


@reports_bp.route("/organizations/<org_id>/reports/<report_id>/reopen", methods=["POST"])
@require_auth(["DataSteward"])
def reopen_report(org_id, report_id):
    get_org_or_404(org_id)
    report = get_report_or_404(org_id, report_id)
    body = get_json_body()

    if report.get("status") not in ("REVISIONS_REQUIRED", "RECOMPUTE_REQUIRED"):
        raise api_error("ERR_INVALID_STATE", "Report must be REVISIONS_REQUIRED or RECOMPUTE_REQUIRED to reopen")
    check_version(body, report)

    with store.lock:
        report["status"] = "DRAFT"
        report["compiled_at"] = None
        for field in PINNED_TOTAL_FIELDS:
            report[field] = None
        _bump(report)
    return success_envelope(report)


@reports_bp.route("/organizations/<org_id>/reports/<report_id>/publish", methods=["POST"])
@require_auth(["Discloser"])
def publish_report(org_id, report_id):
    get_org_or_404(org_id)
    report = get_report_or_404(org_id, report_id)
    body = get_json_body()

    if report.get("status") != "VERIFIED":
        raise api_error("ERR_INVALID_STATE", "Report must be VERIFIED to publish")
    check_version(body, report)

    # No CarbonCredit on this period may remain PURCHASED
    for c in store.carbon_credits.values():
        if (
            c.get("reporting_period_id") == report["reporting_period_id"]
            and c.get("status") == "PURCHASED"
        ):
            raise api_error("ERR_INVALID_STATE", "All purchased credits must be retired before publish")

    actor_user_id = g.user_id
    actor_role = g.user_role
    with store.lock:
        report["status"] = "PUBLISHED"
        report["published_at"] = now_ts()
        _bump(report)
        store.append_audit(
            organization_id=org_id,
            actor_user_id=actor_user_id,
            actor_role=actor_role,
            event_type="REPORT_PUBLISH",
            target_entity="Report",
            target_id=report["id"],
            payload_json={},
        )
    return success_envelope(report)


@reports_bp.route("/organizations/<org_id>/reports/<report_id>", methods=["GET"])
@require_auth(["DataSteward", "FactorManager", "Verifier", "Discloser"])
def read_report(org_id, report_id):
    get_org_or_404(org_id)
    report = get_report_or_404(org_id, report_id)
    return success_envelope(report)


@reports_bp.route("/organizations/<org_id>/reports/<report_id>/dual-scope2", methods=["GET"])
@require_auth(["DataSteward", "Verifier", "Discloser"])
def dual_scope2(org_id, report_id):
    get_org_or_404(org_id)
    report = get_report_or_404(org_id, report_id)

    def _d(v) -> Decimal:
        return Decimal(str(v if v is not None else 0))

    g_s1 = _d(report.get("gross_scope1_kg_co2e"))
    g_s2_loc = _d(report.get("gross_scope2_location_kg_co2e"))
    g_s2_mkt = _d(report.get("gross_scope2_market_kg_co2e"))
    g_s3 = _d(report.get("gross_scope3_kg_co2e"))
    applied = _d(report.get("applied_offsets_kg_co2e"))

    net_loc = compute_net(g_s1, g_s2_loc, g_s3, applied)
    net_mkt = compute_net(g_s1, g_s2_mkt, g_s3, applied)
    delta = net_loc - net_mkt

    data = {
        "net_with_location_scope2": float(net_loc),
        "net_with_market_scope2": float(net_mkt),
        "delta_kg_co2e": float(delta),
    }
    return success_envelope(data)
