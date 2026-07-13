"""Pytest fixtures exposing test_helpers infrastructure.

The runner manages PYTHONPATH so test_helpers is importable, and manages the
server lifecycle (restart before every test → empty DB, clock at 2026-03-01).
"""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def scale_operator_headers():
    return TEST_USERS["scale_operator_headers"]


@pytest.fixture
def sort_manager_headers():
    return TEST_USERS["sort_manager_headers"]


@pytest.fixture
def commodity_trader_headers():
    return TEST_USERS["commodity_trader_headers"]


@pytest.fixture
def settlement_clerk_headers():
    return TEST_USERS["settlement_clerk_headers"]


@pytest.fixture
def municipality_headers():
    return TEST_USERS["municipality_headers"]
