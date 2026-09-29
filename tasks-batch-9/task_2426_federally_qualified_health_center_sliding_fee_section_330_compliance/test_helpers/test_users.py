"""Pre-built role headers for every role in the PRD.

Six of the seven roles carry an opaque identity: the `X-User-ID` value is an
operator identifier that is never compared to any persisted entity's `id`, so a
shared constant is the canonical form for them.

`BoardChair` is different — its identity is entity-backed by a `BoardMember`
row, so board-business calls MUST use `make_board_chair_headers(board_member_id)`
with the actual seated member's `id`.
"""

from prd_bench_local_runner.testing import build_user_headers

# ---------------------------------------------------------------------------
# Shared constants — canonical for the six opaque roles; for BoardChair this is
# only a fallback for tests that deliberately act as a chair holding no seat.
# ---------------------------------------------------------------------------

TEST_USERS = {
    "platform_admin_headers": build_user_headers("admin-1", "PlatformAdmin"),
    "compliance_officer_headers": build_user_headers("co-1", "ComplianceOfficer"),
    "board_chair_headers": build_user_headers("chair-unseated-1", "BoardChair"),
    "eligibility_verifier_headers": build_user_headers("ev-1", "EligibilityVerifier"),
    "patient_services_rep_headers": build_user_headers("psr-1", "PatientServicesRep"),
    "billing_specialist_headers": build_user_headers("bs-1", "BillingSpecialist"),
    "project_officer_headers": build_user_headers("po-1", "ProjectOfficer"),
}

# A second distinct operator per role, for segregation-of-duties scenarios where
# the adjudicator must not be the operator recorded on the row.
SECOND_USERS = {
    "platform_admin_headers": build_user_headers("admin-2", "PlatformAdmin"),
    "compliance_officer_headers": build_user_headers("co-2", "ComplianceOfficer"),
    "eligibility_verifier_headers": build_user_headers("ev-2", "EligibilityVerifier"),
    "patient_services_rep_headers": build_user_headers("psr-2", "PatientServicesRep"),
    "billing_specialist_headers": build_user_headers("bs-2", "BillingSpecialist"),
    "project_officer_headers": build_user_headers("po-2", "ProjectOfficer"),
}


def make_platform_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "PlatformAdmin")


def make_compliance_officer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ComplianceOfficer")


def make_board_chair_headers(board_member_id: str) -> dict:
    """For `BoardChair`, whose identity is entity-backed by a `BoardMember` row.

    Pass the acting `BoardMember`'s `id` whenever the call is one of the three
    board-business operations guarded by the seated-seat check: taking a
    change-in-scope request under review, deciding one, and adopting a fee
    schedule.
    """
    return build_user_headers(board_member_id, "BoardChair")


def make_eligibility_verifier_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "EligibilityVerifier")


def make_patient_services_rep_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "PatientServicesRep")


def make_billing_specialist_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "BillingSpecialist")


def make_project_officer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ProjectOfficer")


# Every role that can read a health center, keyed by the role string itself.
ALL_ROLE_HEADERS = {
    "PlatformAdmin": TEST_USERS["platform_admin_headers"],
    "ComplianceOfficer": TEST_USERS["compliance_officer_headers"],
    "BoardChair": TEST_USERS["board_chair_headers"],
    "EligibilityVerifier": TEST_USERS["eligibility_verifier_headers"],
    "PatientServicesRep": TEST_USERS["patient_services_rep_headers"],
    "BillingSpecialist": TEST_USERS["billing_specialist_headers"],
    "ProjectOfficer": TEST_USERS["project_officer_headers"],
}
