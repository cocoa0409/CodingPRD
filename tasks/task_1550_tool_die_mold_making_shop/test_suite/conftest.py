"""Pytest fixtures exposing test_helpers infrastructure.

Server lifecycle is managed by prd-bench-local-runner; tests assume the API
is already reachable at API_BASE_URL.
"""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client."""
    return api_client


@pytest.fixture
def shop_admin_headers():
    return TEST_USERS["shop_admin_headers"]


@pytest.fixture
def estimator_headers():
    return TEST_USERS["estimator_headers"]


@pytest.fixture
def tooling_engineer_headers():
    return TEST_USERS["tooling_engineer_headers"]


@pytest.fixture
def project_manager_headers():
    return TEST_USERS["project_manager_headers"]


@pytest.fixture
def quality_manager_headers():
    return TEST_USERS["quality_manager_headers"]


@pytest.fixture
def finance_issuer_headers():
    return TEST_USERS["finance_issuer_headers"]


@pytest.fixture
def finance_payer_headers():
    return TEST_USERS["finance_payer_headers"]
