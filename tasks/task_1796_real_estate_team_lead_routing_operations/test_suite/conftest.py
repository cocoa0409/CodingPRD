"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["team_admin_headers"]


@pytest.fixture
def leader_headers():
    """Shared TeamLeader constant — only for tests without ownership checks."""
    return TEST_USERS["team_leader_headers"]


@pytest.fixture
def agent_headers():
    """Shared Agent constant — only for tests without ownership checks."""
    return TEST_USERS["agent_headers"]


@pytest.fixture
def partner_headers():
    """Shared ReferralPartner constant — only for tests without ownership checks."""
    return TEST_USERS["referral_partner_headers"]
