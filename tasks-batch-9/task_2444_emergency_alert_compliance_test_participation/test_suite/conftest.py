"""Pytest fixtures exposing test_helpers infrastructure."""

import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def admin_headers() -> dict:
    """ComplianceAdmin request headers."""
    return TEST_USERS["admin_headers"]


@pytest.fixture
def engineer_headers() -> dict:
    """StationEngineer request headers for the operator the fixtures roster."""
    return TEST_USERS["engineer_headers"]


@pytest.fixture
def officer_headers() -> dict:
    """CertifyingOfficer request headers for the operator the fixtures roster."""
    return TEST_USERS["officer_headers"]


@pytest.fixture
def inspector_headers() -> dict:
    """FieldInspector request headers."""
    return TEST_USERS["inspector_headers"]


@pytest.fixture
def dual_engineer_headers() -> dict:
    """StationEngineer headers for the operator who also holds the officer duty."""
    return TEST_USERS["dual_engineer_headers"]


@pytest.fixture
def dual_officer_headers() -> dict:
    """CertifyingOfficer headers for the operator who also holds the engineer duty."""
    return TEST_USERS["dual_officer_headers"]
