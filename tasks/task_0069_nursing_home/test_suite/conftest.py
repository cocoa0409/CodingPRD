"""Pytest fixtures exposing test_helpers infrastructure.

The runner sets ``API_BASE_URL`` and ``PYTHONPATH``; this file only
adapts test_helpers into pytest-style fixtures.
"""
from __future__ import annotations
import pytest

from test_helpers import (
    ApiClient,
    api_client,
    TEST_USERS,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["admin_headers"]


@pytest.fixture
def admin_headers_alt():
    return TEST_USERS["admin_headers_alt"]


@pytest.fixture
def supervisor_headers():
    return TEST_USERS["supervisor_headers"]


@pytest.fixture
def supervisor_headers_alt():
    return TEST_USERS["supervisor_headers_alt"]


@pytest.fixture
def physician_headers():
    return TEST_USERS["physician_headers"]


@pytest.fixture
def physician_headers_alt():
    return TEST_USERS["physician_headers_alt"]


@pytest.fixture
def nurse_headers():
    return TEST_USERS["nurse_headers"]


@pytest.fixture
def nurse_headers_alt():
    return TEST_USERS["nurse_headers_alt"]


@pytest.fixture
def nurse_headers_third():
    return TEST_USERS["nurse_headers_third"]


@pytest.fixture
def caregiver_headers():
    return TEST_USERS["caregiver_headers"]


@pytest.fixture
def family_headers():
    return TEST_USERS["family_headers"]


@pytest.fixture
def finance_headers():
    return TEST_USERS["finance_headers"]


@pytest.fixture
def systemsync_headers():
    return TEST_USERS["systemsync_headers"]
