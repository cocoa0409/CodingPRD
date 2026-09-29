"""Pytest fixtures exposing test_helpers infrastructure."""

from __future__ import annotations

import pytest

from test_helpers import (
    ApiClient,
    api_client,
    make_compliance_approver_headers,
    make_data_steward_headers,
    make_platform_admin_headers,
    make_privacy_officer_headers,
    make_security_engineer_headers,
)

# Composite setup fixtures are defined in test_helpers.fixtures; importing them
# into this module's namespace is what makes pytest collect them for every test
# module in this suite.
from test_helpers.fixtures import (  # noqa: F401
    approved_assessment,
    clock_at_epoch,
    consent_record,
    consumer,
    element,
    executed_vendor,
    product,
    purpose,
    regulated_product,
    share_disclosure_chain,
    vendor,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def platform_admin_headers() -> dict[str, str]:
    """Headers for the PlatformAdmin role."""
    return make_platform_admin_headers()


@pytest.fixture
def privacy_officer_headers() -> dict[str, str]:
    """Headers for the PrivacyOfficer role."""
    return make_privacy_officer_headers()


@pytest.fixture
def compliance_approver_headers() -> dict[str, str]:
    """Headers for the ComplianceApprover role."""
    return make_compliance_approver_headers()


@pytest.fixture
def data_steward_headers() -> dict[str, str]:
    """Headers for the DataSteward role."""
    return make_data_steward_headers()


@pytest.fixture
def security_engineer_headers() -> dict[str, str]:
    """Headers for the SecurityEngineer role."""
    return make_security_engineer_headers()
