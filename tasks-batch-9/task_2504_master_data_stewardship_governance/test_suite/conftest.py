"""Pytest fixtures exposing the test_helpers infrastructure."""

import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is the runner's concern."""
    return api_client


@pytest.fixture
def governance_admin_headers():
    return TEST_USERS["governance_admin_headers"]


@pytest.fixture
def auditor_headers():
    return TEST_USERS["auditor_headers"]


@pytest.fixture
def data_owner_headers():
    """Shared data-owner headers. Use make_data_owner_headers(steward_id) for
    any call that is gated on the acting steward's accountability."""
    return TEST_USERS["data_owner_headers"]


@pytest.fixture
def data_steward_headers():
    """Shared data-steward headers. Use make_data_steward_headers(steward_id)
    for any call that is gated on the acting steward's accountability."""
    return TEST_USERS["data_steward_headers"]


@pytest.fixture
def consumer_rep_headers():
    """Shared consumer-representative headers. Use
    make_consumer_rep_headers(subscription_id) for ownership-gated calls."""
    return TEST_USERS["consumer_rep_headers"]
