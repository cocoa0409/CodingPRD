"""Shared pytest fixtures for the Convention Center Booking & Event Services suite."""

import os
import sys
from typing import Dict

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_helpers import TEST_USERS, ApiClient, api_client  # noqa: E402


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """The API client bound to the base URL under test."""
    return api_client


@pytest.fixture
def venue_admin() -> Dict[str, str]:
    return TEST_USERS["venue_admin"]


@pytest.fixture
def sales_manager() -> Dict[str, str]:
    return TEST_USERS["sales_manager"]


@pytest.fixture
def event_services_manager() -> Dict[str, str]:
    return TEST_USERS["event_services_manager"]


@pytest.fixture
def settlement_analyst() -> Dict[str, str]:
    return TEST_USERS["settlement_analyst"]


@pytest.fixture
def settlement_analyst_two() -> Dict[str, str]:
    return TEST_USERS["settlement_analyst_two"]


@pytest.fixture
def facilities_planner() -> Dict[str, str]:
    return TEST_USERS["facilities_planner"]
