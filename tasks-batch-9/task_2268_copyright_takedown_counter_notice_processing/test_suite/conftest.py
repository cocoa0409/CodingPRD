"""Pytest fixtures exposing the test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is the runner's concern."""
    return api_client


@pytest.fixture
def compliance_officer_headers():
    return TEST_USERS["compliance_officer_headers"]


@pytest.fixture
def second_compliance_officer_headers():
    return TEST_USERS["second_compliance_officer_headers"]


@pytest.fixture
def takedown_agent_headers():
    return TEST_USERS["takedown_agent_headers"]


@pytest.fixture
def abuse_investigator_headers():
    return TEST_USERS["abuse_investigator_headers"]


@pytest.fixture
def second_abuse_investigator_headers():
    return TEST_USERS["second_abuse_investigator_headers"]


@pytest.fixture
def rights_holder_rep_headers():
    """Entity-backed fallback identity: only for non-ownership RBAC probes."""
    return TEST_USERS["rights_holder_rep_headers"]


@pytest.fixture
def subscriber_headers():
    """Entity-backed fallback identity: only for non-ownership RBAC probes."""
    return TEST_USERS["subscriber_headers"]
