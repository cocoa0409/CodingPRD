"""Pre-built role headers for every role the PRD defines.

`X-User-ID` means different things for different roles. For a
`ReceivingRegistrar` it is the `id` of the acting District, so ownership-gated
calls MUST use `make_receiving_registrar_headers(district["id"])`. For a
`Parent` it must equal the student's `guardian_user_id`, and for an
`EligibleStudent` it must equal the student's `student_user_id`. For the
remaining roles it is an opaque operator identifier, but the server records it
on the rows they touch, so tests that care about which operator acted (for
example the segregation-of-duties rule on amendment decisions) must pass an
explicit identifier.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for the roles whose X-User-ID is opaque, and for any
# test that does not exercise ownership or operator identity.
TEST_USERS = {
    "system_admin_headers": build_user_headers("admin-1", "SystemAdmin"),
    "records_clerk_headers": build_user_headers("clerk-1", "RecordsClerk"),
    "records_officer_headers": build_user_headers("officer-1", "RecordsOfficer"),
    "compliance_officer_headers": build_user_headers("compliance-1", "ComplianceOfficer"),
    "legal_affairs_officer_headers": build_user_headers("legal-1", "LegalAffairsOfficer"),
    # ReceivingRegistrar's X-User-ID must be a real District id; this shared
    # constant is a fallback for tests that never pass the ownership check.
    "receiving_registrar_headers": build_user_headers("registrar-1", "ReceivingRegistrar"),
    "parent_headers": build_user_headers("guardian-1", "Parent"),
    "eligible_student_headers": build_user_headers("student-1", "EligibleStudent"),
}


def make_system_admin_headers(user_id: str = "admin-1") -> dict:
    return build_user_headers(user_id, "SystemAdmin")


def make_records_clerk_headers(user_id: str = "clerk-1") -> dict:
    return build_user_headers(user_id, "RecordsClerk")


def make_records_officer_headers(user_id: str = "officer-1") -> dict:
    """The acting X-User-ID is recorded as `certified_by_user_id` and as
    `initial_decided_by_user_id` / `hearing_decided_by_user_id`, so pass a
    distinct identifier wherever the operator's identity is load-bearing."""
    return build_user_headers(user_id, "RecordsOfficer")


def make_compliance_officer_headers(user_id: str = "compliance-1") -> dict:
    return build_user_headers(user_id, "ComplianceOfficer")


def make_legal_affairs_officer_headers(user_id: str = "legal-1") -> dict:
    return build_user_headers(user_id, "LegalAffairsOfficer")


def make_receiving_registrar_headers(district_id: str) -> dict:
    """For a ReceivingRegistrar, X-User-ID is the `id` of the acting District.
    Always pass the real District id, or every ownership check refuses."""
    return build_user_headers(district_id, "ReceivingRegistrar")


def make_parent_headers(guardian_user_id: str) -> dict:
    """X-User-ID must equal the student's `guardian_user_id`."""
    return build_user_headers(guardian_user_id, "Parent")


def make_eligible_student_headers(student_user_id: str) -> dict:
    """X-User-ID must equal the student's `student_user_id`."""
    return build_user_headers(student_user_id, "EligibleStudent")


ROLE_HEADER_BUILDERS = {
    "SystemAdmin": make_system_admin_headers,
    "RecordsClerk": make_records_clerk_headers,
    "RecordsOfficer": make_records_officer_headers,
    "ComplianceOfficer": make_compliance_officer_headers,
    "LegalAffairsOfficer": make_legal_affairs_officer_headers,
    "ReceivingRegistrar": make_receiving_registrar_headers,
    "Parent": make_parent_headers,
    "EligibleStudent": make_eligible_student_headers,
}
