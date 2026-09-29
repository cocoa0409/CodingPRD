"""Payload builders.

Each builder returns a valid request body with domain-plausible defaults and
lets a caller override any field with a keyword argument. Passing
`field=None` where the PRD allows null is honoured; to drop a key entirely,
delete it from the returned dict.
"""
from . import constants as C


def control_requirement_payload(
    control_key="MFA_PRIVILEGED",
    min_level_required="FULL",
    weight=30,
    is_mandatory=True,
    **overrides,
):
    payload = {
        "control_key": control_key,
        "min_level_required": min_level_required,
        "weight": weight,
        "is_mandatory": is_mandatory,
    }
    payload.update(overrides)
    return payload


def insured_account_payload(
    legal_name="Aurora Health",
    industry_code="HEALTHCARE",
    annual_revenue_usd=43800000,
    record_count=12345,
    primary_dependency_key="CSP_ALPHA",
    **overrides,
):
    payload = {
        "legal_name": legal_name,
        "industry_code": industry_code,
        "annual_revenue_usd": annual_revenue_usd,
        "record_count": record_count,
        "primary_dependency_key": primary_dependency_key,
    }
    payload.update(overrides)
    return payload


def application_payload(
    insured_account_id,
    requested_aggregate_limit_usd=5000000,
    requested_retention_usd=250000,
    dependent_bi_definition="NAMED_PLUS_SUPPLY_CHAIN",
    **overrides,
):
    payload = {
        "insured_account_id": insured_account_id,
        "requested_aggregate_limit_usd": requested_aggregate_limit_usd,
        "requested_retention_usd": requested_retention_usd,
        "dependent_bi_definition": dependent_bi_definition,
    }
    payload.update(overrides)
    return payload


def control_attestation_payload(control_key="MFA_PRIVILEGED", attested_level="FULL", **overrides):
    payload = {"control_key": control_key, "attested_level": attested_level}
    payload.update(overrides)
    return payload


def external_scan_payload(scan_vendor_name="Perimeter Signal", scan_score=68, **overrides):
    payload = {"scan_vendor_name": scan_vendor_name, "scan_score": scan_score}
    payload.update(overrides)
    return payload


def scan_finding(control_key="OFFLINE_BACKUPS", severity="CRITICAL", observed_level="PARTIAL"):
    return {
        "control_key": control_key,
        "severity": severity,
        "observed_level": observed_level,
    }


def scan_complete_payload(outcome="COMPLETED", findings=None, **overrides):
    payload = {"outcome": outcome, "findings": findings if findings is not None else []}
    payload.update(overrides)
    return payload


def quote_payload(expected_application_version, **overrides):
    payload = {"expected_application_version": expected_application_version}
    payload.update(overrides)
    return payload


def decline_payload(declined_reason="RISK_APPETITE", **overrides):
    payload = {"declined_reason": declined_reason}
    payload.update(overrides)
    return payload


def coverage_section_payload(
    section_key="FIRST_PARTY_RESPONSE",
    sublimit_usd=1000000,
    waiting_period_hours=None,
    coinsurance_pct=0.0,
    erosion_priority=10,
):
    return {
        "section_key": section_key,
        "sublimit_usd": sublimit_usd,
        "waiting_period_hours": waiting_period_hours,
        "coinsurance_pct": coinsurance_pct,
        "erosion_priority": erosion_priority,
    }


def bind_payload(
    expected_application_version,
    period_start="2026-08-01T00:00:00Z",
    period_end="2027-08-01T00:00:00Z",
    bi_baseline_method="TRAILING_12M",
    coverage_sections=None,
    **overrides,
):
    payload = {
        "expected_application_version": expected_application_version,
        "period_start": period_start,
        "period_end": period_end,
        "bi_baseline_method": bi_baseline_method,
        "coverage_sections": (
            coverage_sections if coverage_sections is not None else list(C.STANDARD_TOWER)
        ),
    }
    payload.update(overrides)
    return payload


def warranty_report_payload(lapsed_control_keys=None, **overrides):
    payload = {
        "lapsed_control_keys": (
            lapsed_control_keys if lapsed_control_keys is not None else []
        )
    }
    payload.update(overrides)
    return payload


def cancel_policy_payload(cancellation_reason="NON_PAYMENT", **overrides):
    # `cancelled_at` is stamped from the logical clock, never supplied.
    payload = {"cancellation_reason": cancellation_reason}
    payload.update(overrides)
    return payload


def panel_vendor_payload(
    vendor_name="Postmark Notify",
    vendor_type="NOTIFICATION",
    pre_approved_hourly_rate_usd=200,
    per_record_notification_rate_usd=3.5,
    specialty_sectors=None,
    tier=1,
    capacity_concurrent_engagements=5,
    **overrides,
):
    payload = {
        "vendor_name": vendor_name,
        "vendor_type": vendor_type,
        "pre_approved_hourly_rate_usd": pre_approved_hourly_rate_usd,
        "per_record_notification_rate_usd": per_record_notification_rate_usd,
        "specialty_sectors": (
            specialty_sectors if specialty_sectors is not None else ["HEALTHCARE", "TECHNOLOGY"]
        ),
        "tier": tier,
        "capacity_concurrent_engagements": capacity_concurrent_engagements,
    }
    payload.update(overrides)
    return payload


def incident_claim_payload(
    policy_id,
    incident_type="RANSOMWARE",
    incident_discovered_at="2026-09-01T00:00:00Z",
    **overrides,
):
    payload = {
        "policy_id": policy_id,
        "incident_type": incident_type,
        "incident_discovered_at": incident_discovered_at,
    }
    payload.update(overrides)
    return payload


def confirm_coverage_payload(covered_section_keys=None, initial_reserve_usd=250000, **overrides):
    payload = {
        "covered_section_keys": (
            covered_section_keys
            if covered_section_keys is not None
            else ["FIRST_PARTY_RESPONSE", "BUSINESS_INTERRUPTION"]
        ),
        "initial_reserve_usd": initial_reserve_usd,
    }
    payload.update(overrides)
    return payload


def deny_claim_payload(denial_reason="EXCLUDED_CAUSE", **overrides):
    payload = {"denial_reason": denial_reason}
    payload.update(overrides)
    return payload


def vendor_engagement_payload(
    vendor_type="NOTIFICATION",
    deployment_start_at="2026-09-10T00:00:00Z",
    deployment_end_at="2026-09-20T00:00:00Z",
    authorized_hours_cap=40,
    **overrides,
):
    payload = {
        "vendor_type": vendor_type,
        "deployment_start_at": deployment_start_at,
        "deployment_end_at": deployment_end_at,
        "authorized_hours_cap": authorized_hours_cap,
    }
    payload.update(overrides)
    return payload


def log_hours_payload(hours=1, records_notified=None, **overrides):
    """`hours` is required by the PRD; pass `hours=None` to omit the key."""
    payload = {}
    if hours is not None:
        payload["hours"] = hours
    if records_notified is not None:
        payload["records_notified"] = records_notified
    payload.update(overrides)
    return payload


def proof_of_loss_payload(
    expected_claim_version,
    claimed_bi_loss_usd=400000,
    trailing_12m_revenue_usd=43800000,
    prior_year_same_period_revenue_usd=1200000,
    prior_year_same_period_hours=200,
    gross_profit_margin_pct=0.8,
    extra_expense_usd=0,
    mitigation_savings_usd=0,
    **overrides,
):
    payload = {
        "expected_claim_version": expected_claim_version,
        "claimed_bi_loss_usd": claimed_bi_loss_usd,
        "trailing_12m_revenue_usd": trailing_12m_revenue_usd,
        "prior_year_same_period_revenue_usd": prior_year_same_period_revenue_usd,
        "prior_year_same_period_hours": prior_year_same_period_hours,
        "gross_profit_margin_pct": gross_profit_margin_pct,
        "extra_expense_usd": extra_expense_usd,
        "mitigation_savings_usd": mitigation_savings_usd,
    }
    payload.update(overrides)
    return payload


def request_info_payload(info_request_note="Please supply the ledger extract.", **overrides):
    payload = {"info_request_note": info_request_note}
    payload.update(overrides)
    return payload


def reverse_payment_payload(reversal_reason="ADJUSTER_ERROR", **overrides):
    payload = {"reversal_reason": reversal_reason}
    payload.update(overrides)
    return payload


def renewal_assessment_payload(required_control_keys=None, **overrides):
    payload = {
        "required_control_keys": (
            required_control_keys if required_control_keys is not None else ["OFFLINE_BACKUPS"]
        )
    }
    payload.update(overrides)
    return payload


def submit_remediation_payload(submitted_control_keys=None, **overrides):
    payload = {
        "submitted_control_keys": (
            submitted_control_keys if submitted_control_keys is not None else ["OFFLINE_BACKUPS"]
        )
    }
    payload.update(overrides)
    return payload


def verify_remediation_payload(verified_control_keys=None, **overrides):
    payload = {
        "verified_control_keys": (
            verified_control_keys if verified_control_keys is not None else ["OFFLINE_BACKUPS"]
        )
    }
    payload.update(overrides)
    return payload


def issue_renewal_quote_payload(expected_policy_version, **overrides):
    payload = {"expected_policy_version": expected_policy_version}
    payload.update(overrides)
    return payload


def systemic_scenario_payload(
    dependency_key="CSP_ALPHA",
    assumed_outage_hours=240,
    footprint_pct=0.5,
    portfolio_capacity_usd=100000,
    qualifying_definitions=None,
    **overrides,
):
    payload = {
        "dependency_key": dependency_key,
        "assumed_outage_hours": assumed_outage_hours,
        "footprint_pct": footprint_pct,
        "portfolio_capacity_usd": portfolio_capacity_usd,
        "qualifying_definitions": (
            qualifying_definitions
            if qualifying_definitions is not None
            else ["NAMED_ONLY", "NAMED_PLUS_SUPPLY_CHAIN", "BROAD_SYSTEM_FAILURE"]
        ),
    }
    payload.update(overrides)
    return payload


def resubmit_controls_payload(attestations=None, **overrides):
    payload = {
        "attestations": (
            attestations
            if attestations is not None
            else [{"control_key": "OFFLINE_BACKUPS", "attested_level": "FULL"}]
        )
    }
    payload.update(overrides)
    return payload
