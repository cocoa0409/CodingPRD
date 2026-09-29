"""Shared pytest wiring for the landfill airspace API conformance suite.

The harness restarts the service before every individual test, so each test runs
against an empty database and builds all of its own state through the API.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from test_helpers.api_client import api_client as _api_client  # noqa: E402
from test_helpers.test_users import (  # noqa: E402
    TEST_USERS,
    make_scale_operator_headers,
    make_site_operator_headers,
)


@pytest.fixture()
def api():
    """The HTTP client bound to the service under test."""
    return _api_client


@pytest.fixture()
def platform_admin_headers():
    """PlatformAdmin acts with an opaque operator id."""
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture()
def cqa_engineer_headers():
    """The reviewing engineer of record, distinct from any package submitter."""
    return TEST_USERS["cqa_engineer_headers"]


@pytest.fixture()
def cqa_engineer_alt_headers():
    """A second, independent engineer of record."""
    return TEST_USERS["cqa_engineer_alt_headers"]


@pytest.fixture()
def surveyor_headers():
    return TEST_USERS["surveyor_headers"]


@pytest.fixture()
def environmental_manager_headers():
    return TEST_USERS["environmental_manager_headers"]


@pytest.fixture()
def regulatory_agency_headers():
    return TEST_USERS["regulatory_agency_headers"]


@pytest.fixture()
def finance_filer_headers():
    """The FinanceOfficer who files cost updates and drafts host agreements."""
    return TEST_USERS["finance_filer_headers"]


@pytest.fixture()
def finance_certifier_headers():
    """A second FinanceOfficer, who may certify what the filer filed."""
    return TEST_USERS["finance_certifier_headers"]


@pytest.fixture()
def site_operator_headers_for():
    """Build SiteOperator headers whose X-User-ID is a real landfill id."""
    return make_site_operator_headers


@pytest.fixture()
def scale_operator_headers_for():
    """Build ScaleOperator headers whose X-User-ID is a real landfill id."""
    return make_scale_operator_headers
