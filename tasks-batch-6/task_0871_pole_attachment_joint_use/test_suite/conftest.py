"""Pytest fixtures exposing test_helpers infrastructure. Server lifecycle is
managed by prd-bench-local-runner; these fixtures only wire up the client and
role headers.
"""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def coordinator_headers():
    return TEST_USERS["coordinator_headers"]


@pytest.fixture
def engineer_headers():
    return TEST_USERS["engineer_headers"]


@pytest.fixture
def permit_officer_headers():
    return TEST_USERS["permit_officer_headers"]


@pytest.fixture
def field_auditor_headers():
    return TEST_USERS["field_auditor_headers"]


@pytest.fixture
def attacher_headers():
    return TEST_USERS["attacher_headers"]
