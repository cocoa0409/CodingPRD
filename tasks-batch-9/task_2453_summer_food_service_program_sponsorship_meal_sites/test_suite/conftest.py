"""Pytest fixtures exposing the test_helpers infrastructure."""

import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def reviewer_headers():
    """StateAgencyReviewer headers; the reviewer identifier is opaque."""
    return TEST_USERS["state_agency_reviewer_headers"]


@pytest.fixture
def sponsor_admin_headers():
    """SponsorAdmin headers not tied to any sponsor. Use make_sponsor_admin_headers(sponsor_id)
    for any ownership-gated call."""
    return TEST_USERS["sponsor_admin_headers"]


@pytest.fixture
def site_supervisor_headers():
    """SiteSupervisor headers not tied to any site. Use make_site_supervisor_headers(site_id)
    for any ownership-gated call."""
    return TEST_USERS["site_supervisor_headers"]


@pytest.fixture
def field_monitor_headers():
    """FieldMonitor headers for monitor mon_1."""
    return TEST_USERS["field_monitor_headers"]
