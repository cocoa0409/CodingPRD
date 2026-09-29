"""Pre-built role headers for every role the PRD declares.

Two roles carry a meaningful identity: a `CrossingGuard`'s `X-User-ID` is the
`Guard.id` of the guard themselves, and a `SchoolLiaison`'s `X-User-ID` is the
`School.id` of the school they represent. For those two roles the shared
constants below are only usable by tests that do not exercise ownership; every
ownership-gated call must go through the per-instance builders.
"""
from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

# Stable opaque user ids. Two distinct TrafficEngineer ids are required because
# the engineer who opens a warrant study may not finalize it.
ADMIN_USER_ID = "adm-1"
ENGINEER_USER_ID = "eng-1"
SECOND_ENGINEER_USER_ID = "eng-2"
SUPERVISOR_USER_ID = "sup-1"
PUBLIC_REPORTER_USER_ID = "pub-1"

TEST_USERS: Dict[str, Dict[str, str]] = {
    "program_admin_headers": build_user_headers(ADMIN_USER_ID, "ProgramAdmin"),
    "traffic_engineer_headers": build_user_headers(ENGINEER_USER_ID, "TrafficEngineer"),
    "second_traffic_engineer_headers": build_user_headers(
        SECOND_ENGINEER_USER_ID, "TrafficEngineer"),
    "crossing_supervisor_headers": build_user_headers(
        SUPERVISOR_USER_ID, "CrossingSupervisor"),
    "public_reporter_headers": build_user_headers(
        PUBLIC_REPORTER_USER_ID, "PublicReporter"),
    # Identity-bearing roles: fallbacks for non-ownership tests only.
    "crossing_guard_headers": build_user_headers("test-guard-1", "CrossingGuard"),
    "school_liaison_headers": build_user_headers("test-school-1", "SchoolLiaison"),
}


def make_program_admin_headers(user_id: str = ADMIN_USER_ID) -> Dict[str, str]:
    """Headers for a ProgramAdmin. The identity is opaque to the API."""
    return build_user_headers(user_id, "ProgramAdmin")


def make_traffic_engineer_headers(user_id: str = ENGINEER_USER_ID) -> Dict[str, str]:
    """Headers for a TrafficEngineer. Pass a distinct id when a study must be
    finalized by someone other than its author."""
    return build_user_headers(user_id, "TrafficEngineer")


def make_crossing_supervisor_headers(
        user_id: str = SUPERVISOR_USER_ID) -> Dict[str, str]:
    """Headers for a CrossingSupervisor. The identity is opaque to the API."""
    return build_user_headers(user_id, "CrossingSupervisor")


def make_public_reporter_headers(
        user_id: str = PUBLIC_REPORTER_USER_ID) -> Dict[str, str]:
    """Headers for a PublicReporter. The identity is opaque to the API."""
    return build_user_headers(user_id, "PublicReporter")


def make_crossing_guard_headers(guard_id: str) -> Dict[str, str]:
    """Headers for a CrossingGuard. Pass the actual Guard.id: filing an absence
    requires it to equal the assignment's `guard_id`, and answering an offer
    requires it to equal `current_offer_guard_id`."""
    return build_user_headers(guard_id, "CrossingGuard")


def make_school_liaison_headers(school_id: str) -> Dict[str, str]:
    """Headers for a SchoolLiaison. Pass the actual School.id of the school
    whose routes or surveys are being written."""
    return build_user_headers(school_id, "SchoolLiaison")


def make_headers(user_id: str, role: str) -> Dict[str, str]:
    """Escape hatch for undeclared roles and malformed identity headers."""
    return build_user_headers(user_id, role)


ALL_ROLE_NAMES = [
    "ProgramAdmin",
    "TrafficEngineer",
    "CrossingSupervisor",
    "CrossingGuard",
    "SchoolLiaison",
    "PublicReporter",
]
