"""Pytest fixtures exposing the test_helpers infrastructure."""

import pytest

from test_helpers import (
    ADMIN,
    BILLING,
    GRADER,
    LOGISTICS,
    PLANNER,
    TEST_USERS,
    VENDOR,
    WAREHOUSE,
    ApiClient,
    api_client,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client.  Server lifecycle is the runner's job."""
    return api_client


@pytest.fixture
def admin_headers():
    return ADMIN


@pytest.fixture
def warehouse_headers():
    return WAREHOUSE


@pytest.fixture
def grader_headers():
    return GRADER


@pytest.fixture
def vendor_headers():
    return VENDOR


@pytest.fixture
def logistics_headers():
    return LOGISTICS


@pytest.fixture
def billing_headers():
    return BILLING


@pytest.fixture
def planner_headers():
    return PLANNER


@pytest.fixture
def unowned_member_headers():
    """A Member-role identity that owns nothing — for 404/422 probes only."""
    return TEST_USERS["member_headers"]
