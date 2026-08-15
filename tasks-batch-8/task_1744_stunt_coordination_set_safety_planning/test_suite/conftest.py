"""Pytest fixtures exposing test_helpers infrastructure.

The server lifecycle is managed by the test runner: the server is restarted
before every test, so each test starts against an empty database and the
logical clock at its startup default (2026-08-01T00:00:00Z, PRD §2.5).
"""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def executive_headers():
    return TEST_USERS["executive_headers"]


@pytest.fixture
def coordinator_headers():
    return TEST_USERS["coordinator_headers"]


@pytest.fixture
def safety_headers():
    return TEST_USERS["safety_headers"]


@pytest.fixture
def department_head_headers():
    return TEST_USERS["department_head_headers"]


@pytest.fixture
def inspector_headers():
    return TEST_USERS["inspector_headers"]
