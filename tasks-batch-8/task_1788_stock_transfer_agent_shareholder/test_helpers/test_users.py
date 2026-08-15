"""Pre-built role headers for every role in the PRD.

Shareholder is entity-backed by ShareholderAccount (X-User-ID is the acting
account's id) and IssuerOfficer is entity-backed by Issuer (X-User-ID is the
issuing security's id): ownership-gated calls MUST use the per-instance
builders with the real entity id. The other five roles are opaque operator
identities; the shared constants are canonical for them.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that do not exercise
# ownership (400-on-bad-payload, 404-on-missing-resource, wrong-role checks).
TEST_USERS = {
    "agent_admin_headers": build_user_headers("admin_1", "AgentAdmin"),
    # entity_backed roles: shared constants are fallbacks for non-ownership tests only.
    "shareholder_headers": build_user_headers("test-shareholder-1", "Shareholder"),
    "transfer_examiner_headers": build_user_headers("exam_1", "TransferExaminer"),
    "transfer_supervisor_headers": build_user_headers("sup_1", "TransferSupervisor"),
    "issuer_officer_headers": build_user_headers("test-issuer-officer-1", "IssuerOfficer"),
    "compliance_officer_headers": build_user_headers("compliance_1", "ComplianceOfficer"),
    "service_agent_headers": build_user_headers("agent_1", "ServiceAgent"),
}


def make_agent_admin_headers(user_id: str = "admin_1") -> dict:
    return build_user_headers(user_id, "AgentAdmin")


def make_shareholder_headers(account_id: str) -> dict:
    """For Shareholder (entity_backed:ShareholderAccount). Pass the acting
    ShareholderAccount.id whenever the call is ownership-gated."""
    return build_user_headers(account_id, "Shareholder")


def make_examiner_headers(user_id: str = "exam_1") -> dict:
    return build_user_headers(user_id, "TransferExaminer")


def make_supervisor_headers(user_id: str = "sup_1") -> dict:
    return build_user_headers(user_id, "TransferSupervisor")


def make_issuer_officer_headers(issuer_id: str) -> dict:
    """For IssuerOfficer (entity_backed:Issuer). Pass the acting Issuer.id
    whenever the call is ownership-gated."""
    return build_user_headers(issuer_id, "IssuerOfficer")


def make_compliance_headers(user_id: str = "compliance_1") -> dict:
    return build_user_headers(user_id, "ComplianceOfficer")


def make_service_agent_headers(user_id: str = "agent_1") -> dict:
    return build_user_headers(user_id, "ServiceAgent")
