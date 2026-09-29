"""Pre-built identity headers for every role in the PRD.

Authentication is by the `X-User-ID` and `X-User-Role` headers. The `Generator`
role is entity backed: its `X-User-ID` must be the id of the Generator row it
acts for, so generator headers are always built per generator with
`make_generator_headers`.
"""

from prd_bench_local_runner.testing import build_user_headers

# Stable user ids. Two ids exist for every role that participates in a
# separation-of-duties rule so a distinct second signer is always available.
ADMIN_USER_ID = "admin-01"
COMPLIANCE_MANAGER_USER_ID = "cm-01"
COMPLIANCE_MANAGER_2_USER_ID = "cm-02"
CLERK_USER_ID = "clerk-01"
CHEMIST_USER_ID = "chem-01"
CHEMIST_2_USER_ID = "chem-02"
OPERATOR_USER_ID = "op-01"
OPERATOR_2_USER_ID = "op-02"
INSPECTOR_USER_ID = "insp-01"

TEST_USERS = {
    "admin": build_user_headers(ADMIN_USER_ID, "PlatformAdmin"),
    "compliance_manager": build_user_headers(COMPLIANCE_MANAGER_USER_ID, "ComplianceManager"),
    "compliance_manager_2": build_user_headers(COMPLIANCE_MANAGER_2_USER_ID, "ComplianceManager"),
    "clerk": build_user_headers(CLERK_USER_ID, "ReceivingClerk"),
    "chemist": build_user_headers(CHEMIST_USER_ID, "WasteApprovalChemist"),
    "chemist_2": build_user_headers(CHEMIST_2_USER_ID, "WasteApprovalChemist"),
    "operator": build_user_headers(OPERATOR_USER_ID, "TreatmentOperator"),
    "operator_2": build_user_headers(OPERATOR_2_USER_ID, "TreatmentOperator"),
    "inspector": build_user_headers(INSPECTOR_USER_ID, "RegulatoryInspector"),
}

# No identity headers at all: every business endpoint must answer 401.
NO_AUTH_HEADERS = {"Content-Type": "application/json"}


def make_generator_headers(generator_id: str):
    """Headers for the entity-backed Generator role acting for `generator_id`."""
    return build_user_headers(generator_id, "Generator")


def make_headers(user_id: str, role: str):
    """Headers for an arbitrary user id holding `role` (dual-hatted users)."""
    return build_user_headers(user_id, role)
