"""Pytest fixtures exposing test_helpers infrastructure.

Server lifecycle (start/stop/restart-per-test) is owned by prd-bench-local-runner;
these fixtures only hand tests a ready API client and shared role headers.
"""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    return api_client


@pytest.fixture
def admin_headers():
    """PlatformAdmin — opaque identity."""
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def billing_headers():
    """BillingSpecialist — opaque identity."""
    return TEST_USERS["billing_specialist_headers"]


@pytest.fixture
def advisor_headers():
    """Advisor — shared fallback; ownership-gated calls build per-instance headers."""
    return TEST_USERS["advisor_headers"]


@pytest.fixture
def counselor_headers():
    """BenefitsCounselor — shared fallback."""
    return TEST_USERS["benefits_counselor_headers"]


@pytest.fixture
def community_manager_headers():
    """CommunityManager — shared fallback."""
    return TEST_USERS["community_manager_headers"]


@pytest.fixture
def family_headers():
    """Family — shared fallback."""
    return TEST_USERS["family_headers"]
