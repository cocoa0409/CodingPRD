"""Acting identities used by the suite.

For the five operator roles the PRD says `X-User-ID` is "an opaque operator
identifier not tied to any persisted entity", so fixed opaque strings are used.
A `LicenseeAgent`'s `X-User-ID` must be "the `id` of the acting `Licensee`", so
agent identities are built per licensee at call time by
:func:`test_helpers.api_client.make_licensee_agent_headers`.
"""

from prd_bench_local_runner.testing import build_user_headers

# Opaque operator identifiers.
LICENSING_OFFICER_ID = "off-01"
LICENSING_OFFICER_ALT_ID = "off-02"
RETURNS_EXAMINER_ID = "exam-01"
RETURNS_EXAMINER_ALT_ID = "exam-02"
TAX_SUPERVISOR_ID = "sup-01"
TAX_SUPERVISOR_ALT_ID = "sup-02"
AUDIT_MANAGER_ID = "aud-01"
AUDIT_MANAGER_ALT_ID = "aud-02"
FIELD_INSPECTOR_ID = "insp-01"

ROLE_LICENSEE_AGENT = "LicenseeAgent"
ROLE_LICENSING_OFFICER = "LicensingOfficer"
ROLE_RETURNS_EXAMINER = "ReturnsExaminer"
ROLE_TAX_SUPERVISOR = "TaxSupervisor"
ROLE_AUDIT_MANAGER = "AuditManager"
ROLE_FIELD_INSPECTOR = "FieldInspector"

ALL_ROLES = [
    ROLE_LICENSEE_AGENT,
    ROLE_LICENSING_OFFICER,
    ROLE_RETURNS_EXAMINER,
    ROLE_TAX_SUPERVISOR,
    ROLE_AUDIT_MANAGER,
    ROLE_FIELD_INSPECTOR,
]

OPERATOR_ROLES = [
    ROLE_LICENSING_OFFICER,
    ROLE_RETURNS_EXAMINER,
    ROLE_TAX_SUPERVISOR,
    ROLE_AUDIT_MANAGER,
    ROLE_FIELD_INSPECTOR,
]

TEST_USERS = {
    "licensing_officer": {"user_id": LICENSING_OFFICER_ID, "role": ROLE_LICENSING_OFFICER},
    "licensing_officer_alt": {
        "user_id": LICENSING_OFFICER_ALT_ID,
        "role": ROLE_LICENSING_OFFICER,
    },
    "returns_examiner": {"user_id": RETURNS_EXAMINER_ID, "role": ROLE_RETURNS_EXAMINER},
    "returns_examiner_alt": {
        "user_id": RETURNS_EXAMINER_ALT_ID,
        "role": ROLE_RETURNS_EXAMINER,
    },
    "tax_supervisor": {"user_id": TAX_SUPERVISOR_ID, "role": ROLE_TAX_SUPERVISOR},
    "tax_supervisor_alt": {"user_id": TAX_SUPERVISOR_ALT_ID, "role": ROLE_TAX_SUPERVISOR},
    "audit_manager": {"user_id": AUDIT_MANAGER_ID, "role": ROLE_AUDIT_MANAGER},
    "audit_manager_alt": {"user_id": AUDIT_MANAGER_ALT_ID, "role": ROLE_AUDIT_MANAGER},
    "field_inspector": {"user_id": FIELD_INSPECTOR_ID, "role": ROLE_FIELD_INSPECTOR},
}


def headers_for(key):
    """Headers for one of the named entries of :data:`TEST_USERS`."""
    user = TEST_USERS[key]
    return build_user_headers(user["user_id"], user["role"])


__all__ = [
    "TEST_USERS",
    "headers_for",
    "ALL_ROLES",
    "OPERATOR_ROLES",
    "LICENSING_OFFICER_ID",
    "LICENSING_OFFICER_ALT_ID",
    "RETURNS_EXAMINER_ID",
    "RETURNS_EXAMINER_ALT_ID",
    "TAX_SUPERVISOR_ID",
    "TAX_SUPERVISOR_ALT_ID",
    "AUDIT_MANAGER_ID",
    "AUDIT_MANAGER_ALT_ID",
    "FIELD_INSPECTOR_ID",
    "ROLE_LICENSEE_AGENT",
    "ROLE_LICENSING_OFFICER",
    "ROLE_RETURNS_EXAMINER",
    "ROLE_TAX_SUPERVISOR",
    "ROLE_AUDIT_MANAGER",
    "ROLE_FIELD_INSPECTOR",
]
