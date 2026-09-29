"""Pytest wiring: exposes the shared client and the five role header sets."""

import os
import sys
from typing import Dict

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_helpers import TEST_USERS, ApiClient, api_client  # noqa: E402


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """The HTTP client for the API under test."""
    return api_client


@pytest.fixture(scope="session")
def network_admin() -> Dict[str, str]:
    return TEST_USERS["network_admin"]


@pytest.fixture(scope="session")
def benefits_admin() -> Dict[str, str]:
    return TEST_USERS["benefits_admin"]


@pytest.fixture(scope="session")
def care_coordinator() -> Dict[str, str]:
    return TEST_USERS["care_coordinator"]


@pytest.fixture(scope="session")
def provider_manager() -> Dict[str, str]:
    """Shared provider_manager identity.

    A provider_manager is recognised through the Provider it owns, so any
    ownership-gated call must instead use make_provider_manager_headers with
    that provider's owner_user_id.
    """
    return TEST_USERS["provider_manager"]


@pytest.fixture(scope="session")
def employee_user() -> Dict[str, str]:
    """Shared employee_user identity.

    An employee_user is recognised through the Employee row carrying the same
    user_id, so ownership-gated calls must use make_employee_user_headers.
    """
    return TEST_USERS["employee_user"]
