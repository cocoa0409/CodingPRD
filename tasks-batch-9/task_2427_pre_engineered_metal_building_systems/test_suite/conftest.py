"""Pytest fixtures exposing the shared test infrastructure."""

import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def platform_admin_headers() -> dict:
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def sales_engineer_headers() -> dict:
    return TEST_USERS["sales_engineer_headers"]


@pytest.fixture
def engineer_headers() -> dict:
    return TEST_USERS["engineer_headers"]


@pytest.fixture
def engineer_two_headers() -> dict:
    return TEST_USERS["engineer_two_headers"]


@pytest.fixture
def engineering_manager_headers() -> dict:
    return TEST_USERS["engineering_manager_headers"]


@pytest.fixture
def engineering_manager_two_headers() -> dict:
    return TEST_USERS["engineering_manager_two_headers"]


@pytest.fixture
def sealing_engineer_headers() -> dict:
    return TEST_USERS["sealing_engineer_headers"]


@pytest.fixture
def production_planner_headers() -> dict:
    return TEST_USERS["production_planner_headers"]


@pytest.fixture
def logistics_coordinator_headers() -> dict:
    return TEST_USERS["logistics_coordinator_headers"]


@pytest.fixture
def builder_headers() -> dict:
    """Shared Builder headers carrying an identifier that is no builder's ``id``.

    Only for calls that never pass an ownership check: use
    ``make_builder_headers(builder["id"])`` whenever the call is
    ownership-gated, because a Builder's ``X-User-ID`` is the ``id`` of the
    acting Builder row.
    """
    return TEST_USERS["builder_headers"]
