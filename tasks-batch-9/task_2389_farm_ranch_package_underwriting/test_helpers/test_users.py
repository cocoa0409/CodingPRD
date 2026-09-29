"""Pre-built role headers for the six roles the PRD defines (§2.1).

Two of the six roles are backed by persisted rows: an `Agent` caller presents
the producer agency record's `id` as `X-User-ID`, and a `LossControlSpecialist`
presents the inspector record's `id`. For any call whose success depends on
that ownership binding, use the per-instance builder below with the real row's
`id`. The shared constants are for opaque staff roles and for calls that never
reach an ownership check.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

# Shared constants.
TEST_USERS: Dict[str, Dict[str, str]] = {
    # Backed by a persisted row — the shared constant never equals a real id,
    # so it is only usable where no ownership comparison happens.
    "agent_headers": build_user_headers("test-agent-unbound-1", "Agent"),
    "loss_control_headers": build_user_headers("test-inspector-unbound-1", "LossControlSpecialist"),
    # Opaque staff identifiers — the shared constant is the canonical form.
    "underwriter_headers": build_user_headers("uw-staff-1", "Underwriter"),
    "underwriter_headers_alt": build_user_headers("uw-staff-2", "Underwriter"),
    "senior_underwriter_headers": build_user_headers("senior-uw-1", "SeniorUnderwriter"),
    "senior_underwriter_headers_alt": build_user_headers("senior-uw-2", "SeniorUnderwriter"),
    "compliance_officer_headers": build_user_headers("compliance-1", "ComplianceOfficer"),
    "platform_admin_headers": build_user_headers("platform-admin-1", "PlatformAdmin"),
}

UNDERWRITER_USER_ID = "uw-staff-1"
UNDERWRITER_ALT_USER_ID = "uw-staff-2"
SENIOR_UNDERWRITER_USER_ID = "senior-uw-1"
SENIOR_UNDERWRITER_ALT_USER_ID = "senior-uw-2"
COMPLIANCE_OFFICER_USER_ID = "compliance-1"
PLATFORM_ADMIN_USER_ID = "platform-admin-1"


def make_agent_headers(agent_id: str) -> Dict[str, str]:
    """For an `Agent` caller. Pass the producer agency record's own `id`, which
    is precisely the value an `Agent`-role caller presents as `X-User-ID`."""
    return build_user_headers(agent_id, "Agent")


def make_loss_control_headers(inspector_id: str) -> Dict[str, str]:
    """For a `LossControlSpecialist` caller. Pass the inspector record's own
    `id`, which is what a `LossControlSpecialist` presents as `X-User-ID`."""
    return build_user_headers(inspector_id, "LossControlSpecialist")


def make_underwriter_headers(user_id: str) -> Dict[str, str]:
    return build_user_headers(user_id, "Underwriter")


def make_senior_underwriter_headers(user_id: str) -> Dict[str, str]:
    return build_user_headers(user_id, "SeniorUnderwriter")


def make_compliance_officer_headers(user_id: str) -> Dict[str, str]:
    return build_user_headers(user_id, "ComplianceOfficer")


def make_platform_admin_headers(user_id: str) -> Dict[str, str]:
    return build_user_headers(user_id, "PlatformAdmin")


def blank_user_id_headers(role: str = "Underwriter") -> Dict[str, str]:
    """Headers whose `X-User-ID` is supplied blank."""
    return build_user_headers("", role)


def missing_user_id_headers(role: str = "Underwriter") -> Dict[str, str]:
    """Headers that omit `X-User-ID` altogether."""
    return {"X-User-Role": role, "Content-Type": "application/json"}


__all__ = [
    "TEST_USERS",
    "UNDERWRITER_USER_ID",
    "UNDERWRITER_ALT_USER_ID",
    "SENIOR_UNDERWRITER_USER_ID",
    "SENIOR_UNDERWRITER_ALT_USER_ID",
    "COMPLIANCE_OFFICER_USER_ID",
    "PLATFORM_ADMIN_USER_ID",
    "make_agent_headers",
    "make_loss_control_headers",
    "make_underwriter_headers",
    "make_senior_underwriter_headers",
    "make_compliance_officer_headers",
    "make_platform_admin_headers",
    "blank_user_id_headers",
    "missing_user_id_headers",
]
