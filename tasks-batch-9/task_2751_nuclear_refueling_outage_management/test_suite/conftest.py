"""Shared pytest fixtures for the refueling outage management suite.

The harness restarts the API server before every individual test, so no
database cleanup is needed here --- each test begins against an empty station
and builds its own preconditions through the declared endpoints.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_helpers import (  # noqa: E402
    api_client,
    make_access_authority_headers,
    make_contractor_coordinator_headers,
    make_outage_director_headers,
    make_outage_planner_headers,
    make_rad_protection_manager_headers,
    make_rad_protection_planner_headers,
    make_reactor_engineer_headers,
    make_regulatory_affairs_headers,
    make_station_admin_headers,
)


@pytest.fixture(scope="session")
def api():
    return api_client


@pytest.fixture
def station_admin():
    return make_station_admin_headers()


@pytest.fixture
def outage_director():
    return make_outage_director_headers()


@pytest.fixture
def outage_planner():
    return make_outage_planner_headers()


@pytest.fixture
def reactor_engineer():
    return make_reactor_engineer_headers()


@pytest.fixture
def contractor_coordinator():
    return make_contractor_coordinator_headers()


@pytest.fixture
def access_authority():
    return make_access_authority_headers()


@pytest.fixture
def rad_protection_planner():
    return make_rad_protection_planner_headers()


@pytest.fixture
def rad_protection_manager():
    return make_rad_protection_manager_headers()


@pytest.fixture
def regulatory_affairs():
    return make_regulatory_affairs_headers()
