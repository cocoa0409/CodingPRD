"""Shared pytest fixtures for the curtain wall fabrication and installation suite.

The harness restarts the service before every individual test, so each test
begins against an empty store and every fixture below builds its state from
the service's own endpoints.
"""
import pytest

from test_helpers.api_client import api_client as _api_client
from test_helpers.constants import CLOCK_T0
from test_helpers import fixtures as fx
from test_helpers.test_users import TEST_USERS


@pytest.fixture
def client():
    return _api_client


@pytest.fixture
def project_manager_headers():
    return TEST_USERS["cw_project_manager_headers"]


@pytest.fixture
def detailer_headers():
    return TEST_USERS["cw_detailer_headers"]


@pytest.fixture
def engineer_headers():
    return TEST_USERS["delegated_engineer_headers"]


@pytest.fixture
def architect_headers():
    return TEST_USERS["architect_of_record_headers"]


@pytest.fixture
def procurement_headers():
    return TEST_USERS["glazing_procurement_headers"]


@pytest.fixture
def structural_headers():
    return TEST_USERS["structural_contractor_headers"]


@pytest.fixture
def superintendent_headers():
    return TEST_USERS["field_superintendent_headers"]


@pytest.fixture
def inspector_headers():
    return TEST_USERS["qc_inspector_headers"]


@pytest.fixture
def clock_at_t0():
    """The logical clock parked at the canonical scenario instant."""
    fx.set_clock(CLOCK_T0)


@pytest.fixture
def fresh_package():
    """A package still in DESIGN_ASSIST with its system fork undecided."""
    return fx.new_project(system_type=None)


@pytest.fixture
def unitized_package():
    """A package whose system fork is fixed at UNITIZED."""
    return fx.new_project()


@pytest.fixture
def qualified_package():
    """A UNITIZED package whose mockup has passed."""
    return fx.setup_qualified_package()


@pytest.fixture
def package_ready_for_release():
    """Approved submittal, received glass and one zone registered."""
    return fx.setup_ready_for_release()


@pytest.fixture
def released_zone():
    """One fabrication release, so zone A owns a batched panel lot."""
    return fx.setup_released_zone()


@pytest.fixture
def zone_ready_to_hang():
    return fx.setup_zone_ready_to_hang()


@pytest.fixture
def hung_zone():
    return fx.setup_hung_zone()


@pytest.fixture
def hung_zone_with_crew_days():
    return fx.setup_hung_zone_with_crew_days()


@pytest.fixture
def zone_ready_to_certify():
    return fx.setup_zone_ready_to_certify()


@pytest.fixture
def certified_zone():
    return fx.setup_certified_zone()


@pytest.fixture
def two_certified_zones():
    return fx.setup_two_certified_zones()
