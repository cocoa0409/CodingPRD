"""Pytest fixtures exposing the test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is the runner's concern."""
    return api_client


@pytest.fixture
def admin_headers():
    """MerchOpsAdmin — reference spine, weekly actuals, logical clock."""
    return TEST_USERS["admin_headers"]


@pytest.fixture
def planner_headers():
    """MerchandisePlanner — plans, months, option plans, overlays, proposals."""
    return TEST_USERS["planner_headers"]


@pytest.fixture
def director_headers():
    """PlanningDirector — approvals, closures, adjudication."""
    return TEST_USERS["director_headers"]


@pytest.fixture
def buyer_headers():
    """CategoryBuyer — adoption and receipt commitments."""
    return TEST_USERS["buyer_headers"]


@pytest.fixture
def second_planner_headers():
    """A second MerchandisePlanner principal, for segregation-of-duties setups."""
    return TEST_USERS["second_planner_headers"]


@pytest.fixture
def second_director_headers():
    """A second PlanningDirector principal, for segregation-of-duties setups."""
    return TEST_USERS["second_director_headers"]


@pytest.fixture
def vendor_rep_headers():
    """VendorRep with an identifier bound to no vendor row. Only for tests that do
    not exercise commitment ownership."""
    return TEST_USERS["vendor_rep_headers"]
