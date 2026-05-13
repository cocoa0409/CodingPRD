"""Compliance reporting tests (PRD §3.12)."""
from __future__ import annotations

from datetime import timedelta

import pytest

from test_helpers import (
    COMPLIANCE,
    ApiErrorId,
    assert_compliance_report,
    create_compliance_report_payload,
    get_clock_now,
    parse_iso,
    validate_error,
    validate_success,
)


def test_create_compliance_report_in_draft(api):
    """PRD §3.12: 'A COMPLIANCE_OFFICER creates a ComplianceReport in
    DRAFT.'"""
    now = parse_iso(get_clock_now())
    payload = create_compliance_report_payload(
        regulatory_domain="FOOD",
        period_start=now - timedelta(days=1),
        period_end=now + timedelta(days=1),
    )
    report = validate_success(
        api.create_compliance_report(payload, COMPLIANCE),
        expected_status=201,
    )
    assert_compliance_report(report)
    assert report["status"] == "DRAFT"


def test_create_compliance_report_invalid_period_rejected(api):
    """PRD §3.12: 'an inclusive-start, exclusive-end period defined by
    period_start and period_end (each ISO 8601 UTC, with period_end
    strictly greater than period_start).'"""
    now = parse_iso(get_clock_now())
    payload = create_compliance_report_payload(
        regulatory_domain="FOOD",
        period_start=now + timedelta(days=1),
        period_end=now - timedelta(days=1),  # inverted
    )
    resp = api.create_compliance_report(payload, COMPLIANCE)
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value)


def test_generate_advances_to_generated(api):
    """PRD §3.12: 'Generating the report advances it from DRAFT to
    GENERATED and populates three counts.'"""
    now = parse_iso(get_clock_now())
    payload = create_compliance_report_payload(
        regulatory_domain="FOOD",
        period_start=now - timedelta(days=1),
        period_end=now + timedelta(days=1),
    )
    report = validate_success(
        api.create_compliance_report(payload, COMPLIANCE),
        expected_status=201,
    )
    generated = validate_success(
        api.generate_compliance_report(report["id"], COMPLIANCE)
    )
    assert generated["status"] == "GENERATED"
    for key in ("task_count", "alert_count", "critical_alert_count"):
        assert key in generated, (
            f"PRD §3.12 requires {key} populated after /generate"
        )
        assert isinstance(generated[key], int)
        assert generated[key] >= 0


def test_lifecycle_progression(api):
    """PRD §3.12: 'Submission moves the report from GENERATED to
    SUBMITTED; the regulator's acknowledgement moves it from SUBMITTED
    to ACKNOWLEDGED.'"""
    now = parse_iso(get_clock_now())
    payload = create_compliance_report_payload(
        regulatory_domain="FOOD",
        period_start=now - timedelta(days=1),
        period_end=now + timedelta(days=1),
    )
    report = validate_success(
        api.create_compliance_report(payload, COMPLIANCE),
        expected_status=201,
    )
    report = validate_success(
        api.generate_compliance_report(report["id"], COMPLIANCE)
    )
    report = validate_success(
        api.submit_compliance_report(report["id"], COMPLIANCE)
    )
    assert report["status"] == "SUBMITTED"
    report = validate_success(
        api.acknowledge_compliance_report(report["id"], COMPLIANCE)
    )
    assert report["status"] == "ACKNOWLEDGED"
