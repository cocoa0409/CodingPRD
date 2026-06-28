"""Pytest fixtures exposing test_helpers infrastructure.

The runner sets PYTHONPATH so test_helpers is importable, injects API_BASE_URL, and manages
server lifecycle (the server is killed and relaunched before every individual test, so each
test starts against an empty database).
"""
import pytest
from test_helpers import (
    api_client,
    ApiClient,
    TEST_USERS,
    make_underwriter_headers,
    make_servicer_headers,
    make_credit_officer_headers,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def underwriter_headers():
    return TEST_USERS["underwriter_headers"]


@pytest.fixture
def underwriter2_headers():
    return TEST_USERS["underwriter2_headers"]


@pytest.fixture
def servicer_headers():
    return TEST_USERS["servicer_headers"]


@pytest.fixture
def credit_officer_headers():
    return TEST_USERS["credit_officer_headers"]


@pytest.fixture
def credit_officer2_headers():
    return TEST_USERS["credit_officer2_headers"]


@pytest.fixture
def headers_factory():
    """Builder functions so tests can mint per-identity headers for segregation-of-duties."""
    return {
        "underwriter": make_underwriter_headers,
        "servicer": make_servicer_headers,
        "credit_officer": make_credit_officer_headers,
    }
