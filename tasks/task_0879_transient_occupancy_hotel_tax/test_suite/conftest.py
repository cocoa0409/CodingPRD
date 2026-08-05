"""Pytest fixtures exposing test_helpers infrastructure.

The runner sets PYTHONPATH so test_helpers is importable, injects API_BASE_URL,
and restarts the server before every test (empty DB, logical clock reset to
2026-05-01T00:00:00Z).
"""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS
from test_helpers import (
    make_taxadmin_headers, make_auditor_headers,
    make_operator_headers, anonymous_headers,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def taxadmin_headers():
    return TEST_USERS["taxadmin_headers"]


@pytest.fixture
def auditor_headers():
    return TEST_USERS["auditor_headers"]


@pytest.fixture
def operator_headers():
    return TEST_USERS["operator_headers"]


@pytest.fixture
def make_operator():
    return make_operator_headers


@pytest.fixture
def anon_headers():
    return anonymous_headers()
