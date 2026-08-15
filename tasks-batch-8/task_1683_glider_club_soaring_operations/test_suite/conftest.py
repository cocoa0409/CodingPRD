"""Pytest fixtures exposing test_helpers infrastructure.

The runner owns server lifecycle and PYTHONPATH; the server is restarted
before every test, so each test builds its own state from scratch.
"""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed externally."""
    return api_client


@pytest.fixture
def club_admin_headers():
    return TEST_USERS["club_admin_headers"]


@pytest.fixture
def member_headers():
    return TEST_USERS["member_headers"]


@pytest.fixture
def duty_officer_headers():
    return TEST_USERS["duty_officer_headers"]


@pytest.fixture
def instructor_headers():
    return TEST_USERS["instructor_headers"]


@pytest.fixture
def tow_pilot_headers():
    return TEST_USERS["tow_pilot_headers"]
