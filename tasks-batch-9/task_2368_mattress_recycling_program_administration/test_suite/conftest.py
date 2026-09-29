"""Shared pytest fixtures for the Mattress Recycling Program API suite."""

import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    return api_client


@pytest.fixture
def admin_headers() -> dict:
    """The council program administrator that acts first in every workflow."""
    return TEST_USERS["admin_headers"]


@pytest.fixture
def admin_2_headers() -> dict:
    """A second administrator, required wherever approval must be separated from
    proposal."""
    return TEST_USERS["admin_2_headers"]


@pytest.fixture
def admin_3_headers() -> dict:
    return TEST_USERS["admin_3_headers"]


@pytest.fixture
def auditor_headers() -> dict:
    """The independent audit function."""
    return TEST_USERS["auditor_headers"]


@pytest.fixture
def auditor_2_headers() -> dict:
    """A second auditor, required wherever closing an audit must be separated from
    requesting the amendment."""
    return TEST_USERS["auditor_2_headers"]


@pytest.fixture
def registrant_headers() -> dict:
    """A registrant identity not bound to any created record; use
    `make_registrant_headers(registrant_id)` whenever ownership is in play."""
    return TEST_USERS["registrant_headers"]


@pytest.fixture
def site_operator_headers() -> dict:
    """A collection-site operator identity not bound to any created record; use
    `make_site_operator_headers(site_id)` whenever ownership is in play."""
    return TEST_USERS["site_operator_headers"]


@pytest.fixture
def hauler_headers() -> dict:
    """A hauler identity not bound to any created record; use
    `make_hauler_headers(hauler_id)` whenever ownership is in play."""
    return TEST_USERS["hauler_headers"]


@pytest.fixture
def recycler_headers() -> dict:
    """A recycler identity not bound to any created record; use
    `make_recycler_headers(recycler_id)` whenever ownership is in play."""
    return TEST_USERS["recycler_headers"]
