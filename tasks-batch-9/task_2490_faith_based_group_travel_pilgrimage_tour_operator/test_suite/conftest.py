"""Shared pytest fixtures for the pilgrimage tour-operator PRD suite."""

from __future__ import annotations

import pytest

from test_helpers import TEST_USERS, api_client


@pytest.fixture(scope="session")
def api():
    """The single HTTP client every test drives the API through."""
    return api_client


@pytest.fixture
def planner_headers() -> dict[str, str]:
    return TEST_USERS["program_manager"]


@pytest.fixture
def risk_officer_headers() -> dict[str, str]:
    return TEST_USERS["risk_officer"]


@pytest.fixture
def air_desk_headers() -> dict[str, str]:
    return TEST_USERS["air_desk_agent"]


@pytest.fixture
def land_contractor_headers() -> dict[str, str]:
    return TEST_USERS["land_contractor"]


@pytest.fixture
def finance_headers() -> dict[str, str]:
    return TEST_USERS["finance_controller"]


@pytest.fixture
def protection_headers() -> dict[str, str]:
    return TEST_USERS["protection_administrator"]
