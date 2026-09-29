"""Shared pytest fixtures for the Traffic Signal Retiming & Corridor Operations suite.

The harness restarts the server and empties the database before every single test,
so no fixture here may rely on state left behind by another test.
"""
import pytest

from test_helpers import api_client
from test_helpers.test_users import (
    TEST_USERS,
    make_public_requester_headers,
)


@pytest.fixture
def api():
    """The endpoint client for this API."""
    return api_client


@pytest.fixture
def admin_headers():
    """Headers for a SignalOpsAdmin."""
    return TEST_USERS["admin_headers"]


@pytest.fixture
def timing_engineer_headers():
    """Headers for a TimingEngineer."""
    return TEST_USERS["timing_engineer_headers"]


@pytest.fixture
def certifying_engineer_headers():
    """Headers for a CertifyingEngineer."""
    return TEST_USERS["certifying_engineer_headers"]


@pytest.fixture
def field_technician_headers():
    """Headers for a FieldTechnician."""
    return TEST_USERS["field_technician_headers"]


@pytest.fixture
def citizen_liaison_headers():
    """Headers for a CitizenLiaison."""
    return TEST_USERS["citizen_liaison_headers"]


@pytest.fixture
def public_requester_headers():
    """Headers for a PublicRequester whose X-User-ID is not any stored requester."""
    return TEST_USERS["public_requester_headers"]


@pytest.fixture
def requester_headers_factory():
    """Build PublicRequester headers bound to a particular Requester row id."""
    return make_public_requester_headers
