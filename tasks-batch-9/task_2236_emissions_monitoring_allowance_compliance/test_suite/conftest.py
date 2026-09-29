"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def reviewer_headers():
    """RegulatoryReviewer."""
    return TEST_USERS["regulatory_reviewer_headers"]


@pytest.fixture
def operator_headers():
    """FacilityOperator of the facility whose operator_org is op_alpha."""
    return TEST_USERS["facility_operator_headers"]


@pytest.fixture
def qa_headers():
    """QAAnalyst."""
    return TEST_USERS["qa_analyst_headers"]


@pytest.fixture
def preparer_headers():
    """EmissionsReportPreparer prep_1."""
    return TEST_USERS["preparer_headers"]


@pytest.fixture
def second_preparer_headers():
    """EmissionsReportPreparer prep_2."""
    return TEST_USERS["second_preparer_headers"]


@pytest.fixture
def representative_headers():
    """DesignatedRepresentative dr_1."""
    return TEST_USERS["representative_headers"]


@pytest.fixture
def second_representative_headers():
    """DesignatedRepresentative dr_2."""
    return TEST_USERS["second_representative_headers"]


@pytest.fixture
def trader_headers():
    """AllowanceTrader."""
    return TEST_USERS["allowance_trader_headers"]
