"""Pytest fixtures exposing test_helpers infrastructure.

The runner manages the server lifecycle and restarts the API server before
every test, so each test starts against an empty database; all setup happens
through test_helpers fixtures inside the test body.
"""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client, make_nurse_headers


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def specialist_1():
    return TEST_USERS["specialist_1"]


@pytest.fixture
def specialist_2():
    return TEST_USERS["specialist_2"]


@pytest.fixture
def verifier_1():
    return TEST_USERS["verifier_1"]


@pytest.fixture
def verifier_2():
    return TEST_USERS["verifier_2"]


@pytest.fixture
def manager_1():
    return TEST_USERS["manager_1"]


@pytest.fixture
def compliance_1():
    return TEST_USERS["compliance_1"]


@pytest.fixture
def compliance_2():
    return TEST_USERS["compliance_2"]


@pytest.fixture
def operator_1():
    return TEST_USERS["operator_1"]


@pytest.fixture
def nurse_headers_factory():
    """Factory fixture: make_nurse_headers(nurse_id) for ownership-gated calls."""
    return make_nurse_headers
