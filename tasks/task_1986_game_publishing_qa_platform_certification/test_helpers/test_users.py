"""Pre-built role headers for every role in the PRD (§2.1).

Every role's X-User-ID is an opaque operator identifier, never compared to
any entity's id (PRD §2.1). The shared constants below are the canonical
per-role headers. Segregation-of-duties workflows compare two recorded
X-User-ID values, so tests exercising those rules build per-user headers
with the make_*_headers builders.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "release_manager_headers": build_user_headers("rm-1", "ReleaseManager"),
    "qa_lead_headers": build_user_headers("qa-1", "QALead"),
    "vendor_manager_headers": build_user_headers("vm-1", "VendorManager"),
    "certification_lead_headers": build_user_headers("cl-1", "CertificationLead"),
    "platform_reviewer_headers": build_user_headers("pr-1", "PlatformReviewer"),
    "compliance_manager_headers": build_user_headers("cm-1", "ComplianceManager"),
    "platform_admin_headers": build_user_headers("pa-1", "PlatformAdmin"),
    # Generic reader for the read-only endpoints open to every declared role.
    "reader_headers": build_user_headers("reader-1", "QALead"),
}


def make_release_manager_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ReleaseManager")


def make_qa_lead_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "QALead")


def make_vendor_manager_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "VendorManager")


def make_certification_lead_headers(user_id: str) -> dict:
    """CertificationLead headers with a specific X-User-ID — needed where the
    recorded submitter id is compared at decision time (PRD §3.5)."""
    return build_user_headers(user_id, "CertificationLead")


def make_platform_reviewer_headers(user_id: str) -> dict:
    """PlatformReviewer headers with a specific X-User-ID — needed where the
    decider id must differ from the recorded submitter id (PRD §3.5)."""
    return build_user_headers(user_id, "PlatformReviewer")


def make_compliance_manager_headers(user_id: str) -> dict:
    """ComplianceManager headers with a specific X-User-ID — needed where the
    waiver decider id must differ from the requester id (PRD §3.6)."""
    return build_user_headers(user_id, "ComplianceManager")


def make_platform_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "PlatformAdmin")
