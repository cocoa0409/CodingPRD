"""Shared pytest fixtures for the performing arts center season suite.

Every test runs against a freshly launched server with an empty database, so
these fixtures hand out nothing but the shared client and the pre-built role
headers; all domain preconditions are built inside the test from the endpoints
the PRD declares.
"""

import pytest

from test_helpers import (
    TEST_USERS,
    api_client,
    make_artist_representative_headers,
    make_rental_client_contact_headers,
)


@pytest.fixture
def api():
    """The API client, one method per endpoint of the specification."""
    return api_client


@pytest.fixture
def center_admin_headers():
    return TEST_USERS["center_admin_headers"]


@pytest.fixture
def programming_director_headers():
    return TEST_USERS["programming_director_headers"]


@pytest.fixture
def rental_manager_headers():
    return TEST_USERS["rental_manager_headers"]


@pytest.fixture
def technical_director_headers():
    return TEST_USERS["technical_director_headers"]


@pytest.fixture
def box_office_manager_headers():
    return TEST_USERS["box_office_manager_headers"]


@pytest.fixture
def finance_controller_headers():
    return TEST_USERS["finance_controller_headers"]


@pytest.fixture
def artist_representative_headers():
    """Fallback agency headers for scenarios that never reach an ownership
    comparison; ownership-gated calls must build headers from the real artist
    id instead."""
    return TEST_USERS["artist_representative_headers"]


@pytest.fixture
def rental_client_contact_headers():
    """Fallback client-contact headers for scenarios that never reach an
    ownership comparison."""
    return TEST_USERS["rental_client_contact_headers"]


@pytest.fixture
def artist_headers_factory():
    """Build ownership-correct agency headers for a given artist id."""
    return make_artist_representative_headers


@pytest.fixture
def client_contact_headers_factory():
    """Build ownership-correct client-contact headers for a given client id."""
    return make_rental_client_contact_headers
