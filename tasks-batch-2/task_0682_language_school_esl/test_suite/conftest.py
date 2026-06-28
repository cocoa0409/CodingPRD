"""Pytest fixtures exposing test_helpers infrastructure.

The prd-bench-local-runner manages server lifecycle and PYTHONPATH so that
`test_helpers` is importable. Each test runs against a freshly restarted server
with an empty database.
"""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def registrar_headers():
    return TEST_USERS["registrar_headers"]


@pytest.fixture
def dso_headers():
    return TEST_USERS["dso_headers"]


@pytest.fixture
def instructor_headers():
    return TEST_USERS["instructor_headers"]


@pytest.fixture
def student_headers():
    return TEST_USERS["student_headers"]


@pytest.fixture
def corporate_sponsor_headers():
    return TEST_USERS["corporate_sponsor_headers"]
