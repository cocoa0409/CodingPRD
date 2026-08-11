"""Pre-built role headers for every role in the PRD (§2.1).

`PlatformAdmin`, `CmraOperator`, `ComplianceOfficer` and `Notary` carry an opaque
`X-User-ID` that is never compared to any entity id, so shared constants are the
canonical form for them.

`BoxHolder` carries the `id` of the acting mailbox and `Recipient` carries the
`id` of the acting roster member, so those two MUST be built per instance with
`make_box_holder_headers(box_id)` / `make_recipient_headers(recipient_id)`.
"""

from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "platform_admin_headers": build_user_headers("pa-1", "PlatformAdmin"),
    "cmra_operator_headers": build_user_headers("op-1", "CmraOperator"),
    "compliance_officer_headers": build_user_headers("co-1", "ComplianceOfficer"),
    "second_compliance_officer_headers": build_user_headers("co-2", "ComplianceOfficer"),
    "notary_headers": build_user_headers("not-1", "Notary"),
    # Fallbacks for tests that do not exercise ownership (e.g. 401/403/404 paths).
    "box_holder_headers": build_user_headers("test-box-holder", "BoxHolder"),
    "recipient_headers": build_user_headers("test-recipient", "Recipient"),
}

PLATFORM_ADMIN = TEST_USERS["platform_admin_headers"]
CMRA_OPERATOR = TEST_USERS["cmra_operator_headers"]
COMPLIANCE_OFFICER = TEST_USERS["compliance_officer_headers"]
SECOND_COMPLIANCE_OFFICER = TEST_USERS["second_compliance_officer_headers"]
NOTARY = TEST_USERS["notary_headers"]


def make_box_holder_headers(box_id: str) -> dict:
    """For BoxHolder: X-User-ID is the id of the acting mailbox."""
    return build_user_headers(box_id, "BoxHolder")


def make_recipient_headers(recipient_id: str) -> dict:
    """For Recipient: X-User-ID is the id of the acting roster member."""
    return build_user_headers(recipient_id, "Recipient")


def make_platform_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "PlatformAdmin")


def make_cmra_operator_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "CmraOperator")


def make_compliance_officer_headers(user_id: str) -> dict:
    """The officer id is load-bearing for segregation of duties (PRD §2.1)."""
    return build_user_headers(user_id, "ComplianceOfficer")


def make_notary_headers(user_id: str) -> dict:
    """The notary id is recorded as notary_user_id and blocks that id from accepting."""
    return build_user_headers(user_id, "Notary")
