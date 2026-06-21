"""Pytest fixtures exposing test_helpers infrastructure.

The runner sets PYTHONPATH so test_helpers and the framework are importable,
and manages the server lifecycle (restarting it with an empty DB before each
test). Tests therefore start against a fresh database.
"""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def box_office_headers():
    return TEST_USERS["box_office_headers"]


@pytest.fixture
def finance_headers():
    return TEST_USERS["finance_headers"]


@pytest.fixture
def account_holder_headers():
    return TEST_USERS["account_holder_headers"]
