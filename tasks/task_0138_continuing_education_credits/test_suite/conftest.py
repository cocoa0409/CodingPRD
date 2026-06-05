"""Pytest fixtures exposing test_helpers infrastructure.

The runner sets PYTHONPATH so `test_helpers` is importable. Server lifecycle is
owned by prd-bench-local-runner; these fixtures just hand tests a ready client
and pre-built role headers.
"""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def board_admin_headers():
    return TEST_USERS["board_admin_headers"]


@pytest.fixture
def admin_initiator_headers():
    return TEST_USERS["admin_initiator_headers"]


@pytest.fixture
def auditor_headers():
    return TEST_USERS["auditor_headers"]


@pytest.fixture
def provider_headers():
    return TEST_USERS["provider_headers"]


@pytest.fixture
def licensee_headers():
    return TEST_USERS["licensee_headers"]
