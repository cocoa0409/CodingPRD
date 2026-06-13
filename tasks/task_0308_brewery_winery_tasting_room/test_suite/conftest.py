"""Pytest fixtures exposing test_helpers infrastructure.

The runner sets PYTHONPATH so test_helpers is importable and manages server
lifecycle (the API is killed and re-launched via start.sh before every test).
"""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def compliance_officer_headers():
    return TEST_USERS["compliance_officer_headers"]


@pytest.fixture
def cellar_manager_headers():
    return TEST_USERS["cellar_manager_headers"]


@pytest.fixture
def club_manager_headers():
    return TEST_USERS["club_manager_headers"]


@pytest.fixture
def tasting_room_staff_headers():
    return TEST_USERS["tasting_room_staff_headers"]


@pytest.fixture
def member_headers():
    return TEST_USERS["member_headers"]
