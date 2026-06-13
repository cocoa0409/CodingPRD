"""Pre-built role headers for every role in the Earned Wage Access PRD (§2.1).

PlatformAdmin, PayrollOfficer, and ComplianceOfficer are opaque roles: X-User-ID is an
operator identifier never compared to any entity's id. Worker is entity_backed: its
X-User-ID must equal the acting Worker.id for ownership-gated calls — use
make_worker_headers(worker_id) in those cases.

Segregation of duties (§2.8) requires the approver, batch poster, and statement signer in
one period to be three distinct X-User-IDs. The distinct PayrollOfficer / ComplianceOfficer
operator identities below support that separation.
"""
from prd_bench_local_runner.testing import build_user_headers


# Shared constants — opaque roles use these directly; entity_backed Worker uses the
# shared constant only for non-ownership tests (e.g., authorization-denied checks).
TEST_USERS = {
    "platform_admin_headers": build_user_headers("admin-1", "PlatformAdmin"),
    # Default PayrollOfficer operator (acts as advance approver + disburser).
    "payroll_officer_headers": build_user_headers("officer-approver", "PayrollOfficer"),
    # Distinct PayrollOfficer operator used to POST repayment batches (SoD vs approver).
    "payroll_poster_headers": build_user_headers("officer-poster", "PayrollOfficer"),
    # ComplianceOfficer operator used to sign statements / write off (SoD vs poster+approver).
    "compliance_officer_headers": build_user_headers("compliance-signer", "ComplianceOfficer"),
    # Worker shared constant — only for tests that do NOT exercise ownership.
    "worker_headers": build_user_headers("worker-unowned", "Worker"),
}


def make_payroll_officer_headers(user_id: str) -> dict:
    """PayrollOfficer with an explicit operator identity (opaque). Use to control
    which X-User-ID is recorded as approver/poster for segregation-of-duties tests."""
    return build_user_headers(user_id, "PayrollOfficer")


def make_compliance_officer_headers(user_id: str) -> dict:
    """ComplianceOfficer with an explicit operator identity (opaque). Use to control
    which X-User-ID signs/writes-off for segregation-of-duties tests."""
    return build_user_headers(user_id, "ComplianceOfficer")


def make_worker_headers(user_id: str) -> dict:
    """Worker (entity_backed:Worker). Pass the actual Worker.id as user_id for any
    ownership-gated call (advance create where worker_id == X-User-ID, self reads)."""
    return build_user_headers(user_id, "Worker")
