import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """The shared API client. Base URL comes from ``API_BASE_URL``."""
    return api_client


@pytest.fixture
def program_admin_headers():
    return TEST_USERS["program_admin_headers"]


@pytest.fixture
def item_author_headers():
    return TEST_USERS["item_author_headers"]


@pytest.fixture
def item_reviewer_1_headers():
    return TEST_USERS["item_reviewer_1_headers"]


@pytest.fixture
def item_reviewer_2_headers():
    return TEST_USERS["item_reviewer_2_headers"]


@pytest.fixture
def item_reviewer_3_headers():
    return TEST_USERS["item_reviewer_3_headers"]


@pytest.fixture
def psychometrician_headers():
    return TEST_USERS["psychometrician_headers"]


@pytest.fixture
def psychometrician_2_headers():
    return TEST_USERS["psychometrician_2_headers"]


@pytest.fixture
def panelist_1_headers():
    return TEST_USERS["panelist_1_headers"]


@pytest.fixture
def panelist_2_headers():
    return TEST_USERS["panelist_2_headers"]


@pytest.fixture
def eligibility_reviewer_1_headers():
    return TEST_USERS["eligibility_reviewer_1_headers"]


@pytest.fixture
def eligibility_reviewer_2_headers():
    return TEST_USERS["eligibility_reviewer_2_headers"]


@pytest.fixture
def eligibility_reviewer_3_headers():
    return TEST_USERS["eligibility_reviewer_3_headers"]


@pytest.fixture
def eligibility_reviewer_4_headers():
    return TEST_USERS["eligibility_reviewer_4_headers"]


@pytest.fixture
def exam_operations_headers():
    return TEST_USERS["exam_operations_headers"]


@pytest.fixture
def ethics_officer_1_headers():
    return TEST_USERS["ethics_officer_1_headers"]


@pytest.fixture
def ethics_officer_2_headers():
    return TEST_USERS["ethics_officer_2_headers"]


@pytest.fixture
def candidate_headers():
    return TEST_USERS["candidate_headers"]


@pytest.fixture
def certificant_headers():
    return TEST_USERS["certificant_headers"]
