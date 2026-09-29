"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def admin_headers():
    """PlatformAdmin caller."""
    return TEST_USERS["admin_headers"]


@pytest.fixture
def advertiser_headers():
    """Advertiser caller with no particular entity behind it. Ownership-gated
    calls must use make_advertiser_headers(advertiser["id"]) instead."""
    return TEST_USERS["advertiser_headers"]


@pytest.fixture
def publisher_headers():
    """Publisher caller with no particular entity behind it. Ownership-gated
    calls must use make_publisher_headers(publisher["id"]) instead."""
    return TEST_USERS["publisher_headers"]


@pytest.fixture
def analyst_headers():
    """ClassificationAnalyst caller - the classification author identity."""
    return TEST_USERS["analyst_headers"]


@pytest.fixture
def analyst_reviewer_headers():
    """A second ClassificationAnalyst, distinct from the author."""
    return TEST_USERS["analyst_reviewer_headers"]


@pytest.fixture
def officer_headers():
    """DisputeOfficer caller."""
    return TEST_USERS["officer_headers"]


@pytest.fixture
def officer_second_headers():
    """A second DisputeOfficer, distinct from the first."""
    return TEST_USERS["officer_second_headers"]


@pytest.fixture
def auditor_headers():
    """AccreditationAuditor caller - the methodology author identity."""
    return TEST_USERS["auditor_headers"]


@pytest.fixture
def auditor_concluder_headers():
    """A second AccreditationAuditor, who may conclude the author's audit."""
    return TEST_USERS["auditor_concluder_headers"]


@pytest.fixture
def operator_headers():
    """MeasurementOperator caller."""
    return TEST_USERS["operator_headers"]
