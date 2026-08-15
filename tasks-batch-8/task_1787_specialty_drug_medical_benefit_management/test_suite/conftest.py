"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def plan_admin_headers():
    return TEST_USERS["plan_admin_headers"]


@pytest.fixture
def mpo_headers():
    return TEST_USERS["mpo_headers"]


@pytest.fixture
def provider_rep_headers():
    """Shared ProviderRep headers — only for calls that are NOT ownership-gated
    (PRD §2.1). For ownership-gated calls use
    make_provider_rep_headers(provider_account["id"])."""
    return TEST_USERS["provider_rep_headers"]


@pytest.fixture
def case_manager_headers():
    return TEST_USERS["case_manager_headers"]


@pytest.fixture
def pharmacy_analyst_headers():
    return TEST_USERS["pharmacy_analyst_headers"]
