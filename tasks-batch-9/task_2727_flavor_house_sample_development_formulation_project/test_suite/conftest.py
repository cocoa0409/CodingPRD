"""Shared pytest fixtures for the Flavor House Sample Development API suite.

The harness restarts the API server before every test, so each test observes
an empty database and a logical clock reading 2026-08-01T00:00:00Z.  No
fixture here caches state across tests.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_helpers.api_client import ApiClient  # noqa: E402
from test_helpers.test_users import (  # noqa: E402
    ACCOUNT_MANAGER,
    DIRECTOR_APPROVER,
    FLAVORIST_SUBMITTER,
    LAB_COMPOUNDER,
    LAB_QC,
    PURCHASING_MANAGER,
    REGULATORY_AFFAIRS,
    TECHNICAL_DIRECTOR,
)


@pytest.fixture
def api():
    """The API client pointed at the server under test."""
    return ApiClient()


@pytest.fixture
def account_manager_headers():
    return ACCOUNT_MANAGER


@pytest.fixture
def technical_director_headers():
    return TECHNICAL_DIRECTOR


@pytest.fixture
def flavorist_headers():
    return FLAVORIST_SUBMITTER


@pytest.fixture
def regulatory_affairs_headers():
    return REGULATORY_AFFAIRS


@pytest.fixture
def lab_tech_headers():
    return LAB_COMPOUNDER


@pytest.fixture
def purchasing_manager_headers():
    return PURCHASING_MANAGER


@pytest.fixture
def director_approver_headers():
    """The technical director who did not submit the formula under review."""
    return DIRECTOR_APPROVER


@pytest.fixture
def qc_operator_headers():
    """The laboratory operator who did not compound the lot under QC."""
    return LAB_QC
