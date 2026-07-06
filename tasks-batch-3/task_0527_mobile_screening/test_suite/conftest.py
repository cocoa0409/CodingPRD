"""Pytest fixtures exposing test_helpers infrastructure.

The prd-bench-local-runner sets PYTHONPATH so `test_helpers` is importable and
manages server lifecycle (restart before each test → empty DB).
"""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def pm_headers():
    return TEST_USERS["program_manager_headers"]


@pytest.fixture
def cs_headers():
    return TEST_USERS["clinical_staff_headers"]


@pytest.fixture
def bc_headers():
    return TEST_USERS["billing_clerk_headers"]


@pytest.fixture
def nav_headers():
    return TEST_USERS["patient_navigator_headers"]


@pytest.fixture
def sponsor_viewer_headers():
    return TEST_USERS["sponsor_viewer_headers"]
