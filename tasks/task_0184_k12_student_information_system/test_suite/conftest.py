"""Pytest fixtures exposing test_helpers infrastructure.

The runner manages server lifecycle and PYTHONPATH; these fixtures just surface
the shared API client and role headers.
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
def teacher_headers():
    return TEST_USERS["teacher_headers"]


@pytest.fixture
def administrator_headers():
    return TEST_USERS["administrator_headers"]


@pytest.fixture
def state_reporting_officer_headers():
    return TEST_USERS["state_reporting_officer_headers"]


@pytest.fixture
def parent_headers():
    return TEST_USERS["parent_headers"]
