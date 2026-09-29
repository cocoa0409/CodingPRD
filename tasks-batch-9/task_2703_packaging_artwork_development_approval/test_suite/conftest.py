"""Pytest bridge: exposes the shared API client and the role headers.

The runner starts a fresh server before every individual test, so every test
builds all of its own preconditions from scratch through the endpoints declared
in PRD §4.
"""

import pytest

from test_helpers import TEST_USERS, api_client


@pytest.fixture(scope="session")
def api():
    """The API client bound to the running service."""
    return api_client


@pytest.fixture
def coordinator_headers():
    """PRD §2.1: a PackagingCoordinator owns the artwork pipeline end to end."""
    return TEST_USERS["coordinator_headers"]


@pytest.fixture
def brand_reviewer_headers():
    """PRD §2.1: a BrandReviewer decides review tasks bound to the BRAND
    discipline."""
    return TEST_USERS["brand_reviewer_headers"]


@pytest.fixture
def legal_reviewer_headers():
    """PRD §2.1: a LegalReviewer records clearance decisions on marketing claims
    and decides LEGAL tasks."""
    return TEST_USERS["legal_reviewer_headers"]


@pytest.fixture
def regulatory_reviewer_headers():
    """PRD §2.1: a RegulatoryReviewer approves or rejects briefs, waives failed
    mandatory-element verdicts, and decides REGULATORY tasks."""
    return TEST_USERS["regulatory_reviewer_headers"]


@pytest.fixture
def quality_reviewer_headers():
    """PRD §2.1: a QualityReviewer owns proof verdicts across all three proof
    dimensions."""
    return TEST_USERS["quality_reviewer_headers"]


@pytest.fixture
def printer_rep_headers():
    """PRD §2.1: a PrinterRep acts on behalf of exactly one print vendor.

    This identity is not tied to a Printer row, so it is only usable where
    ownership is not being exercised.
    """
    return TEST_USERS["printer_rep_headers"]


@pytest.fixture
def platform_admin_headers():
    """PRD §2.1: a PlatformAdmin onboards print vendors, settles or writes off
    escapes, reverses scrap dispositions and drives the logical clock."""
    return TEST_USERS["platform_admin_headers"]
