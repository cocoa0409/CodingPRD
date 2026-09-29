"""Shared pytest fixtures for the live animal / pet travel acceptance suite.

The service lifecycle is owned entirely by the harness; these fixtures only
supply the HTTP client, the five operator identities of PRD §2.1 and the
composite state builders defined in ``test_helpers.fixtures``.
"""

from typing import Dict

import pytest

from test_helpers import *  # noqa: F401,F403
from test_helpers import ApiClient, api_client
from test_helpers.fixtures import (  # noqa: F401
    accepted_booking,
    arrived_booking,
    booking_with_reserved_segment,
    cancelled_booking,
    catalog,
    compliance_verified_booking,
    confirmed_booking,
    connecting_leg,
    departed_booking,
    investigated_incident,
    primary_leg,
    reported_incident,
    screened_booking,
    staged_kennel_allocations,
    swept_booking,
    travel_ready_booking,
    two_leg_confirmed_booking,
    workbench,
)
from test_helpers.test_users import (
    make_acceptance_agent_headers,
    make_compliance_officer_headers,
    make_program_admin_headers,
    make_reservations_agent_headers,
    make_veterinary_reviewer_headers,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    return api_client


@pytest.fixture
def program_admin_headers() -> Dict[str, str]:
    return make_program_admin_headers()


@pytest.fixture
def reservations_agent_headers() -> Dict[str, str]:
    return make_reservations_agent_headers()


@pytest.fixture
def acceptance_agent_headers() -> Dict[str, str]:
    return make_acceptance_agent_headers()


@pytest.fixture
def veterinary_reviewer_headers() -> Dict[str, str]:
    return make_veterinary_reviewer_headers()


@pytest.fixture
def compliance_officer_headers() -> Dict[str, str]:
    return make_compliance_officer_headers()
