"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers


# Shared constants — safe for opaque roles and for tests that do not exercise
# entity-backed ownership checks.
TEST_USERS = {
    "platform_admin_headers": build_user_headers("admin-1", "PlatformAdmin"),
    "intake_clerk_headers": build_user_headers("clerk-1", "IntakeClerk"),
    "prep_technician_headers": build_user_headers("prep-1", "PrepTechnician"),
    "scan_operator_headers": build_user_headers("scan-1", "ScanOperator"),
    "qa_reviewer_headers": build_user_headers("qa-1", "QAReviewer"),
    "indexer_headers": build_user_headers("idx-1", "Indexer"),
    "destruction_specialist_headers": build_user_headers("ds-1", "DestructionSpecialist"),
    "compliance_officer_headers": build_user_headers("co-1", "ComplianceOfficer"),
    "billing_clerk_headers": build_user_headers("bill-1", "BillingClerk"),
    # ClientUser is entity_backed:Client — this shared constant is only a
    # fallback for tests that do NOT exercise ownership gating.
    "client_user_headers": build_user_headers("client-1", "ClientUser"),
}


def make_platform_admin_headers(user_id: str = "admin-1") -> dict:
    return build_user_headers(user_id, "PlatformAdmin")


def make_intake_clerk_headers(user_id: str = "clerk-1") -> dict:
    return build_user_headers(user_id, "IntakeClerk")


def make_prep_technician_headers(user_id: str = "prep-1") -> dict:
    return build_user_headers(user_id, "PrepTechnician")


def make_scan_operator_headers(user_id: str = "scan-1") -> dict:
    return build_user_headers(user_id, "ScanOperator")


def make_qa_reviewer_headers(user_id: str = "qa-1") -> dict:
    return build_user_headers(user_id, "QAReviewer")


def make_indexer_headers(user_id: str = "idx-1") -> dict:
    return build_user_headers(user_id, "Indexer")


def make_destruction_specialist_headers(user_id: str = "ds-1") -> dict:
    return build_user_headers(user_id, "DestructionSpecialist")


def make_compliance_officer_headers(user_id: str = "co-1") -> dict:
    return build_user_headers(user_id, "ComplianceOfficer")


def make_billing_clerk_headers(user_id: str = "bill-1") -> dict:
    return build_user_headers(user_id, "BillingClerk")


def make_client_user_headers(client_id: str) -> dict:
    """ClientUser is entity_backed:Client. The X-User-ID MUST equal the target
    client id for ownership-gated calls (grants, downloads, request-return)."""
    return build_user_headers(client_id, "ClientUser")
