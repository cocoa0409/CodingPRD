"""Pre-built role headers for every role named in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Opaque operator identifiers.  Distinct ids per role so segregation-of-duties
# comparisons between recorded audit fields are meaningful by default.
ANALYST_ID = "user-analyst-01"
ANALYST_ID_2 = "user-analyst-02"
OFFICER_ID = "user-officer-01"
OFFICER_ID_2 = "user-officer-02"
RM_ID = "user-rm-01"
RM_ID_2 = "user-rm-02"
COMMITTEE_ID = "user-committee-01"
COMMITTEE_ID_2 = "user-committee-02"
ADMIN_ID = "user-admin-01"

TEST_USERS = {
    "analyst_headers": build_user_headers(ANALYST_ID, "ComplianceAnalyst"),
    "analyst2_headers": build_user_headers(ANALYST_ID_2, "ComplianceAnalyst"),
    "officer_headers": build_user_headers(OFFICER_ID, "SanctionsOfficer"),
    "officer2_headers": build_user_headers(OFFICER_ID_2, "SanctionsOfficer"),
    "rm_headers": build_user_headers(RM_ID, "FIGRelationshipManager"),
    "rm2_headers": build_user_headers(RM_ID_2, "FIGRelationshipManager"),
    "committee_headers": build_user_headers(COMMITTEE_ID, "CommitteeApprover"),
    "committee2_headers": build_user_headers(COMMITTEE_ID_2, "CommitteeApprover"),
    "admin_headers": build_user_headers(ADMIN_ID, "PlatformAdmin"),
    # RespondentContact is entity_backed: this shared constant is a fallback for
    # tests that never exercise ownership scoping (it is never a real respondent id).
    "respondent_headers": build_user_headers("not-a-respondent-id", "RespondentContact"),
}

HEADERS_BY_ROLE = {
    "ComplianceAnalyst": TEST_USERS["analyst_headers"],
    "SanctionsOfficer": TEST_USERS["officer_headers"],
    "FIGRelationshipManager": TEST_USERS["rm_headers"],
    "CommitteeApprover": TEST_USERS["committee_headers"],
    "PlatformAdmin": TEST_USERS["admin_headers"],
    "RespondentContact": TEST_USERS["respondent_headers"],
}


def make_respondent_headers(respondent_bank_id: str) -> dict:
    """For RespondentContact.  X-User-ID is the id of the acting RespondentBank,
    so every ownership-scoped call must pass the real respondent id."""
    return build_user_headers(respondent_bank_id, "RespondentContact")


def make_analyst_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ComplianceAnalyst")


def make_officer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "SanctionsOfficer")


def make_rm_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "FIGRelationshipManager")


def make_committee_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "CommitteeApprover")


def make_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "PlatformAdmin")
