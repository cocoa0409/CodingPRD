"""Pytest fixtures exposing test_helpers infrastructure for the Research Funding API."""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def pi_headers():
    """Default PI headers (X-User-ID = DEFAULT_PI_ID). Use only for tests whose project
    was created with DEFAULT_PI_ID as principal_investigator_id."""
    return TEST_USERS["pi_headers"]


@pytest.fixture
def dept_headers():
    return TEST_USERS["dept_headers"]


@pytest.fixture
def dept_headers_alt():
    return TEST_USERS["dept_headers_alt"]


@pytest.fixture
def finance_headers():
    return TEST_USERS["finance_headers"]


@pytest.fixture
def finance_headers_alt():
    return TEST_USERS["finance_headers_alt"]


@pytest.fixture
def research_admin_headers():
    return TEST_USERS["research_admin_headers"]


@pytest.fixture
def audit_officer_headers():
    return TEST_USERS["audit_officer_headers"]


@pytest.fixture
def peer_reviewer_headers():
    return TEST_USERS["peer_reviewer_headers"]


@pytest.fixture
def test_driver_headers():
    return TEST_USERS["test_driver_headers"]
