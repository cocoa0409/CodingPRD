"""Shared pytest fixtures for the Joint Development Agreement API test suite."""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_helpers import (  # noqa: E402
    api_client,
    make_board_secretary_headers,
    make_grants_compliance_officer_headers,
    make_real_estate_officer_headers,
    make_system_admin_headers,
    make_transit_operations_manager_headers,
    make_valuation_officer_headers,
)


@pytest.fixture(scope="session")
def api():
    """The endpoint client. The service is restarted before each test, so the
    client itself is the only thing that can safely be shared."""
    return api_client


@pytest.fixture
def real_estate_officer():
    return make_real_estate_officer_headers()


@pytest.fixture
def valuation_officer():
    return make_valuation_officer_headers()


@pytest.fixture
def board_secretary():
    return make_board_secretary_headers()


@pytest.fixture
def grants_compliance_officer():
    return make_grants_compliance_officer_headers()


@pytest.fixture
def transit_operations_manager():
    return make_transit_operations_manager_headers()


@pytest.fixture
def system_admin():
    return make_system_admin_headers()
