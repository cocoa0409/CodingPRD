"""Pytest fixtures exposing test_helpers infrastructure.

The runner sets PYTHONPATH so that `test_helpers` is importable and injects
API_BASE_URL; the server lifecycle is owned by prd-bench-local-runner. These
fixtures simply surface the shared API client and role headers.
"""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. The server is restarted before every test by
    the runner, so each test starts against an empty database."""
    return api_client


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def trust_officer_headers():
    return TEST_USERS["trust_officer_headers"]


@pytest.fixture
def arbiter_headers():
    return TEST_USERS["arbiter_headers"]


@pytest.fixture
def tutor_headers():
    return TEST_USERS["tutor_headers"]


@pytest.fixture
def parent_headers():
    return TEST_USERS["parent_headers"]
