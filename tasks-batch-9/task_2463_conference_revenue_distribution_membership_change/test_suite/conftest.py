"""Pytest fixtures exposing the test_helpers infrastructure."""

from typing import Callable, Dict

import pytest

from test_helpers import (
    ApiClient,
    api_client,
    make_auditor_headers,
    make_commissioner_headers,
    make_compliance_officer_headers,
    make_finance_officer_headers,
    make_member_representative_headers,
    make_platform_admin_headers,
    make_schedule_coordinator_headers,
    make_treasurer_headers,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def commissioner_headers() -> Dict[str, str]:
    return make_commissioner_headers()


@pytest.fixture
def finance_officer_headers() -> Dict[str, str]:
    return make_finance_officer_headers()


@pytest.fixture
def treasurer_headers() -> Dict[str, str]:
    return make_treasurer_headers()


@pytest.fixture
def auditor_headers() -> Dict[str, str]:
    return make_auditor_headers()


@pytest.fixture
def compliance_officer_headers() -> Dict[str, str]:
    return make_compliance_officer_headers()


@pytest.fixture
def schedule_coordinator_headers() -> Dict[str, str]:
    return make_schedule_coordinator_headers()


@pytest.fixture
def platform_admin_headers() -> Dict[str, str]:
    return make_platform_admin_headers()


@pytest.fixture
def member_representative_headers() -> Callable[[str], Dict[str, str]]:
    """Builder for representative headers, whose user id is the member's own id."""
    return make_member_representative_headers
