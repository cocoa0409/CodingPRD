"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def underwriter_headers():
    return TEST_USERS["underwriter_headers"]


@pytest.fixture
def operations_headers():
    return TEST_USERS["operations_headers"]


@pytest.fixture
def risk_officer_headers():
    return TEST_USERS["risk_officer_headers"]


@pytest.fixture
def finance_headers():
    return TEST_USERS["finance_headers"]


@pytest.fixture
def originator_ops_headers():
    """Fallback OriginatorOps headers for probes that do not exercise ownership."""
    return TEST_USERS["originator_ops_headers"]
