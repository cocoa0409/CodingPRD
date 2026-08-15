"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def requester_headers():
    return TEST_USERS["requester_headers"]


@pytest.fixture
def officer_headers():
    return TEST_USERS["officer_headers"]


@pytest.fixture
def negotiator_headers():
    return TEST_USERS["negotiator_headers"]


@pytest.fixture
def payer_headers():
    return TEST_USERS["payer_headers"]


@pytest.fixture
def ingest_headers():
    return TEST_USERS["ingest_headers"]


@pytest.fixture
def certifier_headers():
    return TEST_USERS["certifier_headers"]


@pytest.fixture
def curator_headers():
    return TEST_USERS["curator_headers"]
