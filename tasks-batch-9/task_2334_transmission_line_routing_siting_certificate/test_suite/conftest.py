"""Pytest fixtures exposing the test helpers.

Header fixtures come in two shapes. The six opaque roles get a ready-made header
dictionary, because their identity is an operator string that is never compared
to a row id. ``Landowner`` gets a builder instead, because its identity *is* the
id of the landowner row it acts for, and that id only exists once the row has
been created.

The composite state fixtures are thin wrappers over the setup helpers, called
with their default arguments. Tests needing a different shape of state call the
helper directly with keyword overrides.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, Iterator

import pytest

from test_helpers import TEST_USERS, ApiClient, api_client, constants
from test_helpers import fixtures as helpers
from test_helpers import test_users as users

# ---------------------------------------------------------------------------
# Client and clock
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture(autouse=True)
def logical_clock(api: ApiClient) -> Iterator[str]:
    """Put the logical clock back to its default reading before every test.

    Nothing in this system reads the wall clock, so an instant left behind by a
    previous test would leak into the next test's comment window, decision
    deadline, hearing eligibility and rescission window arithmetic.
    """
    yield helpers.reset_clock(api)


# ---------------------------------------------------------------------------
# Identities
# ---------------------------------------------------------------------------


@pytest.fixture
def test_users() -> Dict[str, Dict[str, str]]:
    """The identity of each acting operator, keyed by a descriptive name."""
    return TEST_USERS


@pytest.fixture
def developer_headers() -> Dict[str, str]:
    """Headers for the developer who builds the need case and draws corridors."""
    return users.DEVELOPER_HEADERS


@pytest.fixture
def developer_certifier_headers() -> Dict[str, str]:
    """Headers for the second developer, who certifies need-case sufficiency."""
    return users.DEVELOPER_CERTIFIER_HEADERS


@pytest.fixture
def developer_filer_headers() -> Dict[str, str]:
    """Headers for the developer who files the application."""
    return users.DEVELOPER_FILER_HEADERS


@pytest.fixture
def route_analyst_headers() -> Dict[str, str]:
    """Headers for the routing and environmental analyst."""
    return users.ROUTE_ANALYST_HEADERS


@pytest.fixture
def commission_staff_headers() -> Dict[str, str]:
    """Headers for commission staff."""
    return users.COMMISSION_STAFF_HEADERS


@pytest.fixture
def commission_staff_alt_headers() -> Dict[str, str]:
    """Headers for a second commission staffer."""
    return users.COMMISSION_STAFF_ALT_HEADERS


@pytest.fixture
def hearing_examiner_headers() -> Dict[str, str]:
    """Headers for the administrative hearing examiner."""
    return users.HEARING_EXAMINER_HEADERS


@pytest.fixture
def federal_permit_officer_headers() -> Dict[str, str]:
    """Headers for the federal land or waterway agency officer."""
    return users.FEDERAL_PERMIT_OFFICER_HEADERS


@pytest.fixture
def compliance_monitor_headers() -> Dict[str, str]:
    """Headers for the independent construction compliance monitor."""
    return users.COMPLIANCE_MONITOR_HEADERS


@pytest.fixture
def landowner_headers() -> Callable[[str], Dict[str, str]]:
    """Builder for landowner headers, taking the acting landowner row's id."""
    return users.make_landowner_headers


# ---------------------------------------------------------------------------
# Tier 1 and 2 state
# ---------------------------------------------------------------------------


@pytest.fixture
def project(api: ApiClient) -> Dict[str, Any]:
    """A KV_345 project opening in stage PLANNING."""
    return helpers.create_project(api)


@pytest.fixture
def landowner(api: ApiClient) -> Dict[str, Any]:
    """A landowner of record."""
    return helpers.create_landowner(api)


@pytest.fixture
def need_case(api: ApiClient) -> Dict[str, Any]:
    """A DRAFT study with one transmission and one non-wires alternative."""
    return helpers.build_need_case(api)


@pytest.fixture
def certified_study(api: ApiClient) -> Dict[str, Any]:
    """A study certified sufficient at the exact 1.1500 need margin."""
    return helpers.build_certified_study(api)


@pytest.fixture
def mapped_routes(api: ApiClient) -> Dict[str, Any]:
    """A constraint-mapped Route A and a nominated alternate Route B."""
    return helpers.setup_mapped_routes(api)


@pytest.fixture
def published_route(api: ApiClient) -> Dict[str, Any]:
    """Route A published for a 30-day window with two open houses."""
    return helpers.setup_published_route(api)


@pytest.fixture
def nominated_routes(api: ApiClient) -> Dict[str, Any]:
    """Both corridors NOMINATED with the comment window closed."""
    return helpers.setup_nominated_routes(api)


# ---------------------------------------------------------------------------
# Tier 3 state
# ---------------------------------------------------------------------------


@pytest.fixture
def filed_application(api: ApiClient) -> Dict[str, Any]:
    """An application FILED on 2026-08-31 with a 2027-08-31 decision deadline."""
    return helpers.setup_filed_application(api)


@pytest.fixture
def accepted_application(api: ApiClient) -> Dict[str, Any]:
    """An ACCEPTED application whose record dimension sits at SCHEDULING."""
    return helpers.setup_accepted_application(api)


@pytest.fixture
def closed_record(api: ApiClient) -> Dict[str, Any]:
    """An ACCEPTED application whose evidentiary record is RECORD_CLOSED."""
    return helpers.setup_closed_record(api)


@pytest.fixture
def issued_certificate(api: ApiClient) -> Dict[str, Any]:
    """An ISSUED/ACTIVE certificate carrying the three standard conditions."""
    return helpers.setup_issued_certificate(api)


# ---------------------------------------------------------------------------
# Tier 4 and 5 state
# ---------------------------------------------------------------------------


@pytest.fixture
def construction_ready(api: ApiClient) -> Dict[str, Any]:
    """A certificate with segment 1 acquired and escrow funded past the requirement."""
    return helpers.setup_construction_ready(api)


@pytest.fixture
def started_activity(api: ApiClient) -> Dict[str, Any]:
    """A crew-6 clearing activity IN_PROGRESS with segment 1 construction ACTIVE."""
    ctx = helpers.setup_construction_ready(api)
    return helpers.setup_started_activity(api, ctx)


@pytest.fixture
def paid_tract(api: ApiClient) -> Dict[str, Any]:
    """The canonical tract AGREED and PAID out of a funded escrow."""
    ctx = helpers.setup_issued_certificate(api)
    return helpers.setup_paid_tract(api, ctx)


@pytest.fixture
def stop_work_certificate(api: ApiClient) -> Dict[str, Any]:
    """A certificate driven to STOP_WORK by one severe finding."""
    ctx = helpers.setup_issued_certificate(api)
    return helpers.setup_stop_work_certificate(api, ctx)


@pytest.fixture
def revoked_certificate(api: ApiClient) -> Dict[str, Any]:
    """A certificate driven to the terminal REVOKED posture."""
    ctx = helpers.setup_issued_certificate(api)
    return helpers.setup_revoked_certificate(api, ctx)


@pytest.fixture
def two_granted_interventions(api: ApiClient) -> Dict[str, Any]:
    """An accepted docket with two granted landowner petitions."""
    ctx = helpers.setup_accepted_application(api)
    return helpers.setup_two_granted_interventions(api, ctx)


@pytest.fixture
def second_certificate(api: ApiClient) -> Dict[str, Any]:
    """Two independent dockets, each with its own issued certificate."""
    ctx = helpers.setup_issued_certificate(api)
    return helpers.setup_second_certificate(api, ctx)


# ---------------------------------------------------------------------------
# Convenience
# ---------------------------------------------------------------------------


@pytest.fixture
def clock_default() -> str:
    """The instant the logical clock reads before it has ever been set."""
    return constants.DEFAULT_CLOCK_UTC
