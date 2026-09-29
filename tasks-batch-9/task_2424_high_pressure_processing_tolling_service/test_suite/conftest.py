"""Pytest fixtures exposing the shared test infrastructure."""

import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def facility_admin_headers() -> dict:
    return TEST_USERS["facility_admin_headers"]


@pytest.fixture
def plant_scheduler_headers() -> dict:
    return TEST_USERS["plant_scheduler_headers"]


@pytest.fixture
def plant_operator_headers() -> dict:
    """The operator who signs control-point records (op_bob)."""
    return TEST_USERS["plant_operator_headers"]


@pytest.fixture
def quality_manager_headers() -> dict:
    """The quality manager who validates and adjudicates (qm_alice)."""
    return TEST_USERS["quality_manager_headers"]


@pytest.fixture
def second_quality_manager_headers() -> dict:
    """A second quality manager (qm_carol), for four-eyes releases."""
    return TEST_USERS["quality_manager_second_headers"]


@pytest.fixture
def customer_headers() -> dict:
    """Headers for a Customer identifier that backs no persisted row.

    Only for calls that must never pass an ownership check: use
    ``make_customer_headers(customer["id"])`` whenever the call is
    ownership-gated.
    """
    return TEST_USERS["unrelated_customer_headers"]
