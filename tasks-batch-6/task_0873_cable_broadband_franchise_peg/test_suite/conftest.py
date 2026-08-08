"""Pytest fixtures exposing test_helpers infrastructure.

The runner sets PYTHONPATH so test_helpers is importable, injects API_BASE_URL,
and restarts the server before every test (empty DB, logical clock reset to
2026-05-01T00:00:00Z).
"""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS
from test_helpers import (
    make_authority_headers, make_operator_headers,
    make_resident_headers, anonymous_headers,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def authority_headers():
    return TEST_USERS["authority_headers"]


@pytest.fixture
def resident_headers():
    return TEST_USERS["resident_headers"]


@pytest.fixture
def operator_headers():
    return TEST_USERS["operator_headers"]


@pytest.fixture
def make_authority():
    return make_authority_headers


@pytest.fixture
def make_operator():
    return make_operator_headers


@pytest.fixture
def make_resident():
    return make_resident_headers


@pytest.fixture
def anon_headers():
    return anonymous_headers()
