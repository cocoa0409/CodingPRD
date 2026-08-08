"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def intake_headers():
    return TEST_USERS["intake_headers"]


@pytest.fixture
def investigator_headers():
    return TEST_USERS["investigator_headers"]


@pytest.fixture
def adjudicator_headers():
    return TEST_USERS["adjudicator_headers"]


@pytest.fixture
def recovery_officer_headers():
    return TEST_USERS["recovery_officer_headers"]


@pytest.fixture
def supervisor_headers():
    return TEST_USERS["supervisor_headers"]
