"""Pytest fixtures exposing test_helpers infrastructure.

Server lifecycle and PYTHONPATH are managed by prd-bench-local-runner; the server is
restarted (empty DB) before every individual test.
"""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def box_office_headers():
    return TEST_USERS["box_office_headers"]


@pytest.fixture
def promoter_headers():
    return TEST_USERS["promoter_headers"]


@pytest.fixture
def gate_scanner_headers():
    return TEST_USERS["gate_scanner_headers"]


@pytest.fixture
def buyer_headers():
    return TEST_USERS["buyer_headers"]


@pytest.fixture
def unknown_role_headers():
    return TEST_USERS["unknown_role_headers"]
