"""Pytest fixtures exposing test_helpers infrastructure.

The runner owns server lifecycle and PYTHONPATH; this module only bridges
the shared API client and role headers into pytest fixtures.
"""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["admin_headers"]


@pytest.fixture
def investment_officer_headers():
    return TEST_USERS["io_headers"]


@pytest.fixture
def development_officer_headers():
    return TEST_USERS["dev_headers"]


@pytest.fixture
def board_member_headers():
    return TEST_USERS["board_headers"]


@pytest.fixture
def program_manager_headers():
    return TEST_USERS["program_headers"]
