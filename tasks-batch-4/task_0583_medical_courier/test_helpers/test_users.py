"""Pre-built role headers for every role in the Medical Courier PRD (§2.1).

`Dispatcher` and `ComplianceOfficer` are opaque operator identities — their
X-User-ID is never compared to a persisted entity id, so the shared constants
below are the canonical form.

`Driver` and `LabClient` are ownership-scoped: X-User-ID must be the acting
Driver's / LabClient's own `id`. Any ownership-gated call MUST therefore use the
per-instance builders below with the real entity id.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque operator identities — safe as shared constants.
    "dispatcher_headers": build_user_headers("op-dispatch-1", "Dispatcher"),
    "compliance_headers": build_user_headers("op-compliance-1", "ComplianceOfficer"),
    # Ownership-scoped roles: these fallbacks are only for tests that do NOT
    # depend on owning the subject resource (e.g. role-not-permitted checks).
    "driver_headers": build_user_headers("op-driver-1", "Driver"),
    "lab_client_headers": build_user_headers("op-lab-1", "LabClient"),
    # An unrecognized role — used only for authentication-rejection scenarios.
    "unknown_role_headers": build_user_headers("op-anon-1", "Auditor"),
}


def make_driver_headers(driver_id: str) -> dict:
    """Headers for the Driver whose own `id` is `driver_id` (PRD §2.1)."""
    return build_user_headers(driver_id, "Driver")


def make_lab_client_headers(lab_client_id: str) -> dict:
    """Headers for the LabClient whose own `id` is `lab_client_id` (PRD §2.1)."""
    return build_user_headers(lab_client_id, "LabClient")


def make_dispatcher_headers(user_id: str = "op-dispatch-1") -> dict:
    return build_user_headers(user_id, "Dispatcher")


def make_compliance_headers(user_id: str = "op-compliance-1") -> dict:
    return build_user_headers(user_id, "ComplianceOfficer")
