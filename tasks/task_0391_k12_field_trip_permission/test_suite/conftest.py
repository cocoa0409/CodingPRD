"""Pytest fixtures exposing test_helpers infrastructure.

The runner sets PYTHONPATH so test_helpers is importable; server lifecycle is the
runner's job (it restarts the API server before every test).
"""
import pytest
from test_helpers import (
    api_client,
    ApiClient,
    TEST_USERS,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


# Shared-constant role headers (opaque roles, and non-ownership tests).
@pytest.fixture
def teacher_headers():
    return TEST_USERS["teacher_headers"]


@pytest.fixture
def guardian_headers():
    return TEST_USERS["guardian_headers"]


@pytest.fixture
def principal_headers():
    return TEST_USERS["principal_headers"]


@pytest.fixture
def district_admin_headers():
    return TEST_USERS["district_admin_headers"]
