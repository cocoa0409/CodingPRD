"""Pre-built role headers for every role in the PRD (§2.1).

`Subscriber` is the only role whose `X-User-ID` is the `id` of a persisted
entity, so ownership-gated calls MUST use ``make_subscriber_headers(subscriber_id)``
with the real subscriber id.  The other four roles carry opaque operator
identifiers that the server never compares to any entity's `id`, so shared
constants are the canonical form for them — except where a test needs two
distinct operator identities (segregation of duties on a margin exception).
"""

from prd_bench_local_runner.testing import build_user_headers

# Shared constants.  Safe for the four opaque roles, and for Subscriber-role
# tests that never reach an ownership check (bad payload, missing resource).
TEST_USERS = {
    "subscriber_headers": build_user_headers("test-subscriber-1", "Subscriber"),
    "retention_specialist_headers": build_user_headers("rs_1", "RetentionSpecialist"),
    "billing_operator_headers": build_user_headers("bo_1", "BillingOperator"),
    "compliance_officer_headers": build_user_headers("co_1", "ComplianceOfficer"),
    "platform_admin_headers": build_user_headers("pa_1", "PlatformAdmin"),
}


def make_subscriber_headers(user_id: str) -> dict:
    """For `Subscriber` — pass the acting `Subscriber` entity's own `id`.

    Required for every ownership-gated call: the server compares `X-User-ID`
    against the `subscriber_id` of the resource chain being touched.
    """
    return build_user_headers(user_id, "Subscriber")


def make_retention_specialist_headers(user_id: str) -> dict:
    """For `RetentionSpecialist` — an opaque operator identifier.

    Recorded as `presented_by_user_id`, so tests that assert on that field or
    that exercise segregation of duties must pin the identifier explicitly.
    """
    return build_user_headers(user_id, "RetentionSpecialist")


def make_billing_operator_headers(user_id: str) -> dict:
    """For `BillingOperator` — an opaque operator identifier."""
    return build_user_headers(user_id, "BillingOperator")


def make_compliance_officer_headers(user_id: str) -> dict:
    """For `ComplianceOfficer` — an opaque operator identifier.

    Recorded as `decided_by_user_id`; must differ from the grant's
    `presented_by_user_id` for the decision to be accepted.
    """
    return build_user_headers(user_id, "ComplianceOfficer")


def make_platform_admin_headers(user_id: str) -> dict:
    """For `PlatformAdmin` — an opaque operator identifier."""
    return build_user_headers(user_id, "PlatformAdmin")


def headers_for_role(role: str, user_id: str) -> dict:
    """Build headers for an arbitrary role name, including unrecognised ones.

    Used by authentication tests that declare a role outside the five the PRD
    recognises.
    """
    return build_user_headers(user_id, role)
