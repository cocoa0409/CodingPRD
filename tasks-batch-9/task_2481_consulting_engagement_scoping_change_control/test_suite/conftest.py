"""Pytest wiring for the Consulting Engagement Scoping & Change Control suite."""

import pytest

from test_helpers import ConsultingApiClient, install_error_status_map
from test_helpers import fixtures as fx

# Teach the shared validators the HTTP status of every error id in PRD section 5
# so that asserting an error id also asserts its status.
install_error_status_map()


@pytest.fixture
def api() -> ConsultingApiClient:
    """A fresh client. The runner restarts the server before each test."""
    return ConsultingApiClient()


@pytest.fixture
def master_data(api: ConsultingApiClient) -> fx.Scenario:
    """Clock, one client and the five consultants the suite acts through."""
    return fx.build_master_data(api)


@pytest.fixture
def screening_pursuit(api: ConsultingApiClient) -> fx.Scenario:
    return fx.build_screening_pursuit(api)


@pytest.fixture
def qualified_pursuit(api: ConsultingApiClient) -> fx.Scenario:
    return fx.build_qualified_pursuit(api)


@pytest.fixture
def scoped_pursuit(api: ConsultingApiClient) -> fx.Scenario:
    """SCOPING with the canonical two-deliverable scope."""
    return fx.build_scoped_pursuit(api)


@pytest.fixture
def baselined_pursuit(api: ConsultingApiClient) -> fx.Scenario:
    return fx.build_baselined_pursuit(api)


@pytest.fixture
def sow_draft(api: ConsultingApiClient) -> fx.Scenario:
    """A FIXED_FEE statement of work in DRAFT on a SOW_ISSUED pursuit."""
    return fx.build_sow_draft(api)


@pytest.fixture
def sow_internal_review(api: ConsultingApiClient) -> fx.Scenario:
    return fx.build_sow_internal_review(api)


@pytest.fixture
def sow_client_review(api: ConsultingApiClient) -> fx.Scenario:
    return fx.build_sow_client_review(api)


@pytest.fixture
def signed_engagement(api: ConsultingApiClient) -> fx.Scenario:
    """A signed FIXED_FEE document whose engagement is still MOBILIZING."""
    return fx.build_signed_engagement(api)


@pytest.fixture
def active_engagement(api: ConsultingApiClient) -> fx.Scenario:
    """A mobilised engagement: delivery ACTIVE, economics ON_TRACK."""
    return fx.build_active_engagement(api)


@pytest.fixture
def started_engagement(api: ConsultingApiClient) -> fx.Scenario:
    """Delivery under way: the first deliverable is IN_PROGRESS with a lead."""
    return fx.build_started_engagement(api)


@pytest.fixture
def burned_engagement(api: ConsultingApiClient) -> fx.Scenario:
    """First deliverable accepted and 100.00 partner hours on the ledger."""
    return fx.build_burned_engagement(api)


@pytest.fixture
def closed_engagement(api: ConsultingApiClient) -> fx.Scenario:
    """An engagement driven all the way to delivery CLOSED."""
    return fx.build_closed_engagement(api)
