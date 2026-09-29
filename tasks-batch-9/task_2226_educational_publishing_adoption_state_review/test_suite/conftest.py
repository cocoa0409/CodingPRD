"""Shared pytest fixtures for the adoption-review compliance suite.

Every test runs against a freshly started service with an empty database, so
scenario state is always assembled from the endpoints the contract publishes,
using the builders in ``test_helpers.fixtures``.

The StateAdoptionOfficer role has no fixture here on purpose: an officer's
identity is the identifier of the state profile they administer, so officer
headers can only be built after a state exists. Use
``make_state_adoption_officer_headers(state_id)``, or read ``world.officer`` off
any world a builder returns.
"""

import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """The API client under test."""
    return api_client


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def publisher_editor_headers():
    return TEST_USERS["publisher_editor_headers"]


@pytest.fixture
def second_publisher_editor_headers():
    return TEST_USERS["second_publisher_editor_headers"]


@pytest.fixture
def editorial_director_headers():
    return TEST_USERS["editorial_director_headers"]


@pytest.fixture
def pricing_manager_headers():
    return TEST_USERS["pricing_manager_headers"]


@pytest.fixture
def sales_rep_headers():
    return TEST_USERS["sales_rep_headers"]


@pytest.fixture
def second_sales_rep_headers():
    return TEST_USERS["second_sales_rep_headers"]


@pytest.fixture
def committee_member_headers():
    return TEST_USERS["committee_member_headers"]


@pytest.fixture
def second_committee_member_headers():
    return TEST_USERS["second_committee_member_headers"]


@pytest.fixture
def third_committee_member_headers():
    return TEST_USERS["third_committee_member_headers"]


@pytest.fixture
def fourth_committee_member_headers():
    return TEST_USERS["fourth_committee_member_headers"]


@pytest.fixture
def public_commenter_headers():
    return TEST_USERS["public_commenter_headers"]


@pytest.fixture
def no_auth_headers():
    return TEST_USERS["no_auth_headers"]
