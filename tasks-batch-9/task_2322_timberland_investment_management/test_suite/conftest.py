"""Shared pytest fixtures for the Timberland Investment Management compliance suite.

The server is started and reset by the harness, so every test begins against an
empty database and builds its own preconditions through the API.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_helpers import ApiClient  # noqa: E402
from test_helpers.test_users import (  # noqa: E402
    make_analyst_headers,
    make_appraiser_headers,
    make_auditor_headers,
    make_carbon_developer_headers,
    make_committee_headers,
    make_forest_manager_headers,
    make_fund_admin_headers,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    return ApiClient()


@pytest.fixture
def fund_admin_headers():
    return make_fund_admin_headers()


@pytest.fixture
def analyst_headers():
    return make_analyst_headers()


@pytest.fixture
def committee_headers():
    return make_committee_headers()


@pytest.fixture
def forest_manager_headers():
    return make_forest_manager_headers()


@pytest.fixture
def auditor_headers():
    return make_auditor_headers()


@pytest.fixture
def carbon_developer_headers():
    return make_carbon_developer_headers()


@pytest.fixture
def appraiser_headers():
    return make_appraiser_headers()
