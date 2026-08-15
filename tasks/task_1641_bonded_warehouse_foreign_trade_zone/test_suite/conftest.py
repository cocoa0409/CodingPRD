"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import (
    ApiClient,
    TEST_USERS,
    api_client,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def zone_operator_headers():
    return TEST_USERS["zone_operator_headers"]


@pytest.fixture
def importer_headers():
    return TEST_USERS["importer_headers"]


@pytest.fixture
def customs_officer_headers():
    return TEST_USERS["customs_officer_headers"]


@pytest.fixture
def gate_officer_headers():
    return TEST_USERS["gate_officer_headers"]
