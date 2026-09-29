"""Shared pytest fixtures.

The harness restarts the API server before every individual test, so each
fixture below rebuilds its state from an empty database using only endpoints
the PRD declares.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_helpers import (  # noqa: E402
    ADMIN_HEADERS,
    EPA_HEADERS,
    PM_HEADERS,
    QA_HEADERS,
    TECH_HEADERS,
    ApiClient,
    base_environment,
    canonical_environment,
    operating_site_environment,
    twelve_validated_quarters,
)


@pytest.fixture
def api() -> ApiClient:
    return ApiClient()


@pytest.fixture
def admin_headers():
    return ADMIN_HEADERS


@pytest.fixture
def tech_headers():
    return TECH_HEADERS


@pytest.fixture
def qa_headers():
    return QA_HEADERS


@pytest.fixture
def pm_headers():
    return PM_HEADERS


@pytest.fixture
def epa_headers():
    return EPA_HEADERS


@pytest.fixture
def base_env(api):
    """Logical clock, one pollutant, one designated method, one network."""
    return base_environment(api)


@pytest.fixture
def site_env(api):
    """Base reference data plus one operating population-oriented site."""
    return operating_site_environment(api)


@pytest.fixture
def monitor_env(api):
    """One operating site carrying one commissioned, QC-current instrument."""
    return canonical_environment(api)


@pytest.fixture
def data_env(api):
    """Twelve validated, fully complete quarters on one primary instrument."""
    return twelve_validated_quarters(api)
