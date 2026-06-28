"""Pytest fixtures exposing test_helpers infrastructure.

The runner sets PYTHONPATH so `test_helpers` is importable and manages server
lifecycle (restarting the server via start.sh before every individual test). This
file only wires test_helpers into pytest fixtures.
"""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def director_headers():
    return TEST_USERS["director_headers"]


@pytest.fixture
def examiner_headers():
    return TEST_USERS["examiner_headers"]


@pytest.fixture
def zoning_officer_headers():
    return TEST_USERS["zoning_officer_headers"]


@pytest.fixture
def adjudication_officer_headers():
    return TEST_USERS["adjudication_officer_headers"]


@pytest.fixture
def investigator_headers():
    return TEST_USERS["investigator_headers"]


@pytest.fixture
def anonymous_headers():
    return TEST_USERS["anonymous_headers"]


@pytest.fixture
def applicant_headers():
    return TEST_USERS["applicant_headers"]
