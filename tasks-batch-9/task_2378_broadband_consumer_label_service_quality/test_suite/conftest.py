"""Pytest fixtures exposing the test_helpers infrastructure."""

import pytest

from test_helpers import ApiClient, api_client
from test_helpers.fixtures import (
    ReferenceEnvironment,
    build_reference_environment,
    set_clock,
)
from test_helpers.test_users import (
    COMPLAINT_ANALYST_2_HEADERS,
    COMPLAINT_ANALYST_HEADERS,
    COMPLIANCE_OFFICER_2_HEADERS,
    COMPLIANCE_OFFICER_HEADERS,
    LOCALIZATION_SPECIALIST_2_HEADERS,
    LOCALIZATION_SPECIALIST_HEADERS,
    NETWORK_ENGINEER_2_HEADERS,
    NETWORK_ENGINEER_HEADERS,
    REGULATORY_LIAISON_HEADERS,
    RETAIL_AGENT_HEADERS,
    make_subscriber_headers,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return api_client


# ---------------------------------------------------------------------------
# Role headers
# ---------------------------------------------------------------------------


@pytest.fixture
def compliance_officer_headers():
    return COMPLIANCE_OFFICER_HEADERS


@pytest.fixture
def second_compliance_officer_headers():
    return COMPLIANCE_OFFICER_2_HEADERS


@pytest.fixture
def network_engineer_headers():
    return NETWORK_ENGINEER_HEADERS


@pytest.fixture
def second_network_engineer_headers():
    return NETWORK_ENGINEER_2_HEADERS


@pytest.fixture
def localization_specialist_headers():
    return LOCALIZATION_SPECIALIST_HEADERS


@pytest.fixture
def second_localization_specialist_headers():
    return LOCALIZATION_SPECIALIST_2_HEADERS


@pytest.fixture
def complaint_analyst_headers():
    return COMPLAINT_ANALYST_HEADERS


@pytest.fixture
def second_complaint_analyst_headers():
    return COMPLAINT_ANALYST_2_HEADERS


@pytest.fixture
def regulatory_liaison_headers():
    return REGULATORY_LIAISON_HEADERS


@pytest.fixture
def retail_agent_headers():
    return RETAIL_AGENT_HEADERS


@pytest.fixture
def subscriber_headers_for():
    """Builder for `Subscriber` headers: `X-User-ID` is the account's own id."""
    return make_subscriber_headers


# ---------------------------------------------------------------------------
# Domain scenarios
# ---------------------------------------------------------------------------


@pytest.fixture
def clock():
    """Reposition the logical clock from within a test."""
    return set_clock


@pytest.fixture
def reference_environment() -> ReferenceEnvironment:
    """A published, substantiated label on a fibre plan with five fee lines,
    plus one enrolled account."""
    return build_reference_environment()
