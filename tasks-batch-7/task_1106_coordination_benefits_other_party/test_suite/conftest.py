"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def eligibility_analyst_headers():
    return TEST_USERS["eligibility_analyst_headers"]


@pytest.fixture
def cob_analyst_headers():
    return TEST_USERS["cob_analyst_headers"]


@pytest.fixture
def claims_examiner_headers():
    return TEST_USERS["claims_examiner_headers"]


@pytest.fixture
def recovery_specialist_headers():
    return TEST_USERS["recovery_specialist_headers"]


@pytest.fixture
def cob_auditor_headers():
    return TEST_USERS["cob_auditor_headers"]


@pytest.fixture
def member_self_headers():
    return TEST_USERS["member_self_headers"]
