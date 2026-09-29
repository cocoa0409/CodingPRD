"""Pytest wiring for the Supplement Label Claim Compliance suite.

The runner restarts the server before every test, so each test opens against an
empty database and builds all of its own state through PRD endpoints.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_helpers import (  # noqa: E402
    AUDITOR_HEADERS,
    CAO_ALT_HEADERS,
    CAO_HEADERS,
    QAM_ALT_HEADERS,
    QAM_HEADERS,
    RAS_ALT_HEADERS,
    RAS_HEADERS,
    REVIEWER_ALT_HEADERS,
    REVIEWER_HEADERS,
    SupplementComplianceClient,
)


@pytest.fixture
def api() -> SupplementComplianceClient:
    """A client bound to the API under test."""
    return SupplementComplianceClient()


@pytest.fixture
def specialist_headers():
    """``RegulatoryAffairsSpecialist`` — the label and dossier author."""
    return RAS_HEADERS


@pytest.fixture
def specialist_alt_headers():
    """A second ``RegulatoryAffairsSpecialist`` identity."""
    return RAS_ALT_HEADERS


@pytest.fixture
def reviewer_headers():
    """``SubstantiationReviewer`` — clears evidence but never approves a claim."""
    return REVIEWER_HEADERS


@pytest.fixture
def reviewer_alt_headers():
    """A second ``SubstantiationReviewer`` identity."""
    return REVIEWER_ALT_HEADERS


@pytest.fixture
def officer_headers():
    """``ClaimApprovalOfficer`` — locks panels, approves claims, files with FDA."""
    return CAO_HEADERS


@pytest.fixture
def officer_alt_headers():
    """A second ``ClaimApprovalOfficer`` identity."""
    return CAO_ALT_HEADERS


@pytest.fixture
def quality_headers():
    """``QualityAssuranceManager`` — the supply chain and adverse-event role."""
    return QAM_HEADERS


@pytest.fixture
def quality_alt_headers():
    """A second ``QualityAssuranceManager`` identity."""
    return QAM_ALT_HEADERS


@pytest.fixture
def auditor_headers():
    """``ComplianceAuditor`` — read-only oversight across every fetch endpoint."""
    return AUDITOR_HEADERS
