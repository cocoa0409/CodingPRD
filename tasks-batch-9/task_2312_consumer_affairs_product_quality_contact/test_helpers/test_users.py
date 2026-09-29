"""Acting identities.

Every staff-backed role must act as a real ``StaffUser`` row, so the header
builders below are the normal way to address the API: create the staff user,
then thread its own id through ``make_<role>_headers``.  ``TEST_USERS`` is only
for calls where no entity row is required (the SystemAdmin surface) or where the
point of the test is that the id does not resolve.
"""

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ROLE_CARE_AGENT,
    ROLE_CARE_SUPERVISOR,
    ROLE_CONSUMER,
    ROLE_QUALITY_LEAD,
    ROLE_REGULATORY_OFFICER,
    ROLE_SYSTEM_ADMIN,
)

TEST_USERS = {
    "system_admin_headers": build_user_headers("test-system-admin-1", ROLE_SYSTEM_ADMIN),
    "care_agent_headers": build_user_headers("test-care-agent-1", ROLE_CARE_AGENT),
    "care_supervisor_headers": build_user_headers(
        "test-care-supervisor-1", ROLE_CARE_SUPERVISOR
    ),
    "quality_lead_headers": build_user_headers("test-quality-lead-1", ROLE_QUALITY_LEAD),
    "regulatory_officer_headers": build_user_headers(
        "test-regulatory-officer-1", ROLE_REGULATORY_OFFICER
    ),
    "consumer_headers": build_user_headers("test-consumer-1", ROLE_CONSUMER),
}

# A request that carries no acting principal at all.
NO_ACTOR_HEADERS = {"Content-Type": "application/json"}

# The clock is the one route that declares a role but needs no acting principal.
CLOCK_HEADERS = {"X-User-Role": ROLE_SYSTEM_ADMIN, "Content-Type": "application/json"}

# A request whose acting principal is present but blank.
BLANK_ACTOR_HEADERS = {"X-User-ID": "", "X-User-Role": ROLE_CARE_AGENT,
                       "Content-Type": "application/json"}


def make_system_admin_headers(user_id: str = "test-system-admin-1") -> dict:
    return build_user_headers(user_id, ROLE_SYSTEM_ADMIN)


def make_care_agent_headers(user_id: str) -> dict:
    return build_user_headers(user_id, ROLE_CARE_AGENT)


def make_care_supervisor_headers(user_id: str) -> dict:
    return build_user_headers(user_id, ROLE_CARE_SUPERVISOR)


def make_quality_lead_headers(user_id: str) -> dict:
    return build_user_headers(user_id, ROLE_QUALITY_LEAD)


def make_regulatory_officer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, ROLE_REGULATORY_OFFICER)


def make_consumer_headers(consumer_id: str) -> dict:
    """The self-service role is backed by a ``Consumer`` row, not a staff row."""
    return build_user_headers(consumer_id, ROLE_CONSUMER)


HEADER_BUILDER_FOR_ROLE = {
    ROLE_SYSTEM_ADMIN: make_system_admin_headers,
    ROLE_CARE_AGENT: make_care_agent_headers,
    ROLE_CARE_SUPERVISOR: make_care_supervisor_headers,
    ROLE_QUALITY_LEAD: make_quality_lead_headers,
    ROLE_REGULATORY_OFFICER: make_regulatory_officer_headers,
    ROLE_CONSUMER: make_consumer_headers,
}
