"""Pytest fixtures exposing test_helpers infrastructure.

The runner manages the server lifecycle (it restarts the API before every
individual test) and sets PYTHONPATH so test_helpers is importable. These
fixtures only wire up the client and the pre-built role headers.
"""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def organizer_headers():
    return TEST_USERS["organizer_headers"]


@pytest.fixture
def auction_manager_headers():
    return TEST_USERS["auction_manager_headers"]


@pytest.fixture
def finance_headers():
    return TEST_USERS["finance_headers"]


@pytest.fixture
def finance_headers_2():
    return TEST_USERS["finance_headers_2"]


@pytest.fixture
def bidder_headers():
    return TEST_USERS["bidder_headers"]


@pytest.fixture
def sponsor_headers():
    return TEST_USERS["sponsor_headers"]
