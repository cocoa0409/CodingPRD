"""Shared pytest fixtures for the hydrogen production and fuelling API suite.

The server is restarted before every test, so each test builds the world it
needs from scratch through published endpoints only.
"""

import sys
from pathlib import Path

import pytest

# The helper package sits beside this suite in the task directory.
_TASK_DIR = Path(__file__).resolve().parent.parent
if str(_TASK_DIR) not in sys.path:
    sys.path.insert(0, str(_TASK_DIR))

from test_helpers import (  # noqa: E402
    api_client,
    make_compliance_admin_headers,
    make_logistics_dispatcher_headers,
    make_platform_admin_headers,
    make_production_engineer_headers,
    make_program_auditor_headers,
    make_quality_analyst_headers,
    make_safety_officer_headers,
    make_station_operator_headers,
)


@pytest.fixture()
def api():
    """The API client every test drives the service through."""
    return api_client


@pytest.fixture()
def platform_admin_headers():
    return make_platform_admin_headers()


@pytest.fixture()
def production_engineer_headers():
    return make_production_engineer_headers()


@pytest.fixture()
def quality_analyst_headers():
    return make_quality_analyst_headers()


@pytest.fixture()
def safety_officer_headers():
    return make_safety_officer_headers()


@pytest.fixture()
def compliance_admin_headers():
    return make_compliance_admin_headers()


@pytest.fixture()
def logistics_dispatcher_headers():
    return make_logistics_dispatcher_headers()


@pytest.fixture()
def program_auditor_headers():
    return make_program_auditor_headers()


@pytest.fixture()
def operator_headers_for():
    """Build StationOperator headers whose user id is the station's own id."""
    return make_station_operator_headers
