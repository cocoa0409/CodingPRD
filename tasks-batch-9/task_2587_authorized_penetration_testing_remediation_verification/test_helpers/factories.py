"""Request-body factories for the Pentest Assurance API test suite.

Every factory returns a fresh dictionary carrying a valid, realistic body, and
accepts keyword overrides so a test can vary exactly the one field it is about
to prove something with. Passing ``None`` for an override removes the key, which
is how a test builds a body that is missing a required field.
"""

from .constants import (
    CLEARANCE_EXPIRY,
    INTERVAL_END,
    INTERVAL_START,
    WINDOW_END,
    WINDOW_START,
)
from .test_users import OWNER_USER_ID

_SENTINEL_REMOVE = None


def _merge(base, overrides):
    """Apply overrides, dropping keys whose override value is ``None``."""
    merged = dict(base)
    for key, value in overrides.items():
        if value is _SENTINEL_REMOVE:
            merged.pop(key, None)
        else:
            merged[key] = value
    return merged


# ---------------------------------------------------------------------------
# Assets
# ---------------------------------------------------------------------------
def asset_payload(**overrides):
    """A tier-1 SOC2 payments application that was last tested in 2025."""
    return _merge(
        {
            "name": "Payments API",
            "asset_class": "APPLICATION",
            "criticality_tier": 1,
            "compliance_regimes": ["SOC2"],
            "exposure_score": 88,
            "last_tested_at": "2025-10-02T00:00:00Z",
        },
        overrides,
    )


def analytics_lake_asset_payload(**overrides):
    """A tier-3 cloud estate under three regimes that has never been tested."""
    return _merge(
        {
            "name": "Analytics Lake",
            "asset_class": "CLOUD",
            "criticality_tier": 3,
            "compliance_regimes": ["PCI_DSS", "HIPAA", "SOX"],
            "exposure_score": 40,
        },
        overrides,
    )


def partner_portal_asset_payload(**overrides):
    """A tier-2 SOC2 application whose bonuses total exactly 0.50."""
    return _merge(
        {
            "name": "Partner Portal",
            "asset_class": "APPLICATION",
            "criticality_tier": 2,
            "compliance_regimes": ["SOC2"],
            "exposure_score": 60,
            "last_tested_at": "2026-01-05T00:00:00Z",
        },
        overrides,
    )


def core_network_asset_payload(**overrides):
    """A tier-2 network segment, which carries a full day of cooldown."""
    return _merge(
        {
            "name": "Core Network Segment",
            "asset_class": "NETWORK",
            "criticality_tier": 2,
            "compliance_regimes": ["SOC2"],
            "exposure_score": 55,
            "last_tested_at": "2026-01-05T00:00:00Z",
        },
        overrides,
    )


# ---------------------------------------------------------------------------
# Test plans and scope candidates
# ---------------------------------------------------------------------------
def test_plan_payload(**overrides):
    """A risk-driven FY2026 plan with an appetite of 40, so a threshold of 60."""
    return _merge(
        {
            "fiscal_year": 2026,
            "risk_appetite_score": 40,
            "planned_engagement_count": 5,
            "prioritization_mode": "RISK_DRIVEN",
        },
        overrides,
    )


def scope_item_payload(test_plan_id, asset_id, expected_test_plan_version, **overrides):
    return _merge(
        {
            "test_plan_id": test_plan_id,
            "asset_id": asset_id,
            "justification": "Annual coverage of the payments surface",
            "requested_engagement_hours": 120,
            "expected_test_plan_version": expected_test_plan_version,
        },
        overrides,
    )


def decision_payload(decision, note=None, override_note=None):
    payload = {"decision": decision}
    if note is not None:
        payload["note"] = note
    if override_note is not None:
        payload["override_note"] = override_note
    return payload


# ---------------------------------------------------------------------------
# Engagements, documents and targets
# ---------------------------------------------------------------------------
def engagement_payload(test_plan_id, scope_item_id, **overrides):
    return _merge(
        {
            "test_plan_id": test_plan_id,
            "scope_item_id": scope_item_id,
            "engagement_type": "APPLICATION_TEST",
            "window_start": WINDOW_START,
            "window_end": WINDOW_END,
            "hours_allocated": 80,
        },
        overrides,
    )


def rules_of_engagement_payload(engagement_id, **overrides):
    return _merge(
        {
            "engagement_id": engagement_id,
            "exclusions": [],
            "allowed_techniques": ["SQLI"],
            "emergency_stop_procedure": "Halt traffic and call the escalation contact",
            "escalation_contact": "soc@example.com",
        },
        overrides,
    )


def authorized_target_payload(roe_id, asset_id, **overrides):
    return _merge(
        {
            "roe_id": roe_id,
            "asset_id": asset_id,
            "window_start": WINDOW_START,
            "window_end": WINDOW_END,
            "technique_allowlist": ["SQLI"],
        },
        overrides,
    )


# ---------------------------------------------------------------------------
# Testers and access grants
# ---------------------------------------------------------------------------
def tester_payload(**overrides):
    """A tester holding OSCP and GPEN, so a qualification score of 80."""
    return _merge(
        {
            "full_name": "Tester One",
            "certifications": ["OSCP", "GPEN"],
            "clearance_expires_at": CLEARANCE_EXPIRY,
            "max_concurrent_engagements": 2,
        },
        overrides,
    )


def second_tester_payload(**overrides):
    """An independent tester who can verify the first tester's discoveries."""
    return _merge(
        {
            "full_name": "Tester Two",
            "certifications": ["CREST"],
            "clearance_expires_at": CLEARANCE_EXPIRY,
            "max_concurrent_engagements": 1,
        },
        overrides,
    )


def tester_assignment_payload(
    engagement_id, tester_id, expected_engagement_version, granted_asset_ids, **overrides
):
    return _merge(
        {
            "engagement_id": engagement_id,
            "tester_id": tester_id,
            "assignment_role": "LEAD",
            "interval_start": INTERVAL_START,
            "interval_end": INTERVAL_END,
            "requested_hours": 40,
            "granted_asset_ids": list(granted_asset_ids),
            "expected_engagement_version": expected_engagement_version,
        },
        overrides,
    )


# ---------------------------------------------------------------------------
# Findings, triage, remediation and verification
# ---------------------------------------------------------------------------
def finding_payload(engagement_id, asset_id, expected_engagement_version, **overrides):
    """A partner-facing access-control finding with a base score of 8.5."""
    return _merge(
        {
            "engagement_id": engagement_id,
            "asset_id": asset_id,
            "title": "Refund authorization bypass",
            "reproduction_steps": (
                "1. Authenticate as clerk 2. POST /refunds with another tenant id"
            ),
            "business_impact_narrative": (
                "Cross-tenant refunds move settlement funds"
            ),
            "technical_base_score": 8.5,
            "exposure_class": "PARTNER",
            "root_cause_theme": "ACCESS_CONTROL",
            "expected_engagement_version": expected_engagement_version,
        },
        overrides,
    )


def secondary_finding_payload(
    engagement_id, asset_id, expected_engagement_version, **overrides
):
    """An internal secrets-handling finding with a base score of 4.0."""
    return _merge(
        {
            "engagement_id": engagement_id,
            "asset_id": asset_id,
            "title": "Verbose stack traces in error responses",
            "reproduction_steps": (
                "1. POST malformed JSON 2. Observe stack trace in body"
            ),
            "business_impact_narrative": (
                "Internal class paths leak, easing further attacks"
            ),
            "technical_base_score": 4.0,
            "exposure_class": "INTERNAL",
            "root_cause_theme": "SECRETS_HANDLING",
            "expected_engagement_version": expected_engagement_version,
        },
        overrides,
    )


def triage_payload(action, note=None, duplicate_of_finding_id=None):
    payload = {"action": action}
    if note is not None:
        payload["note"] = note
    if duplicate_of_finding_id is not None:
        payload["duplicate_of_finding_id"] = duplicate_of_finding_id
    return payload


def remediation_payload(finding_id, **overrides):
    return _merge(
        {
            "finding_id": finding_id,
            "owner_user_id": OWNER_USER_ID,
            "validation_requirement": "RETEST_REQUIRED",
            "remediation_plan": "Add tenant scoping to the refund authorizer",
        },
        overrides,
    )


def retest_verification_payload(remediation_id, **overrides):
    return _merge(
        {
            "remediation_id": remediation_id,
            "evidence_uri": "s3://evidence/rem1/retest.har",
            "outcome": "PASS",
        },
        overrides,
    )
