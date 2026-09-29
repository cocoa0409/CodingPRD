"""Pytest fixtures exposing test_helpers infrastructure."""

from typing import Dict

import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def program_admin() -> Dict[str, str]:
    """Headers for the ProgramAdmin operator who bootstraps reference data."""
    return TEST_USERS["program_admin"]


@pytest.fixture
def compliance_auditor() -> Dict[str, str]:
    """Headers for the read-only ComplianceAuditor inspector."""
    return TEST_USERS["compliance_auditor"]


@pytest.fixture
def anonymous() -> Dict[str, str]:
    """Headers for the Anonymous reporting channel."""
    return TEST_USERS["anonymous"]
