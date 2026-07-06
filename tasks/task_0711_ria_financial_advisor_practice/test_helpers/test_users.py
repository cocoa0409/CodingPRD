"""Pre-built role headers for every role in the RIA Practice PRD (§2.1).

All three roles use an opaque X-User-ID that is never compared to an entity id
(PRD §2.1), so shared constants are the canonical form. Distinct operator ids
within a role are still needed for the separation-of-duties checks (a fee-run
finalizer must differ from its creator; an IPS approver must differ from the
proposing advisor), so explicit user-id builders are provided too.
"""
from prd_bench_local_runner.testing import build_user_headers


# Shared constants — every role's X-User-ID is opaque (PRD §2.1).
TEST_USERS = {
    "advisor_headers": build_user_headers("adv-1", "Advisor"),
    "compliance_headers": build_user_headers("co-1", "ComplianceOfficer"),
    "billing_headers": build_user_headers("billing-1", "BillingAdmin"),
}


def make_advisor_headers(user_id: str) -> dict:
    """Advisor headers with an explicit operator id. Used for separation-of-duties
    scenarios (e.g. the proposing advisor that must differ from the approver)."""
    return build_user_headers(user_id, "Advisor")


def make_compliance_headers(user_id: str) -> dict:
    """ComplianceOfficer headers with an explicit operator id."""
    return build_user_headers(user_id, "ComplianceOfficer")


def make_billing_headers(user_id: str) -> dict:
    """BillingAdmin headers with an explicit operator id. The fee-run creator and
    finalizer must be different operator ids (PRD §3.5 separation of duties)."""
    return build_user_headers(user_id, "BillingAdmin")
