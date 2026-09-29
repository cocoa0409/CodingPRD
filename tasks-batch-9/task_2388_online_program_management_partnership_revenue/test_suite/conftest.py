"""Shared pytest fixtures for the Online Program Management Partnership suite."""

from typing import Callable, Dict

import pytest

from test_helpers import (
    ApiClient,
    TEST_USERS,
    api_client,
    make_bursar_headers,
    make_compliance_auditor_headers,
    make_faculty_chair_headers,
    make_partner_account_lead_headers,
    make_platform_admin_headers,
    make_provost_headers,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    return api_client


@pytest.fixture
def admin_headers() -> Dict[str, str]:
    return make_platform_admin_headers()


@pytest.fixture
def provost_headers() -> Dict[str, str]:
    return make_provost_headers()


@pytest.fixture
def bursar_headers() -> Dict[str, str]:
    return make_bursar_headers()


@pytest.fixture
def faculty_headers() -> Dict[str, str]:
    return make_faculty_chair_headers()


@pytest.fixture
def auditor_headers() -> Dict[str, str]:
    return make_compliance_auditor_headers()


@pytest.fixture
def partner_headers() -> Callable[[str], Dict[str, str]]:
    """The partner account lead's identity is its partnership id, so headers are per partnership."""
    return make_partner_account_lead_headers


@pytest.fixture
def test_users() -> Dict[str, Dict[str, str]]:
    return TEST_USERS
