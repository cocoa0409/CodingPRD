"""Pre-built role headers for every role in the PRD.

For the five opaque roles the shared constant in ``TEST_USERS`` is the canonical form:
their ``X-User-ID`` is an opaque operator identifier that is never compared to an
entity id. For ``Lessee`` the acting ``X-User-ID`` must be the id of the acting
``Lessee`` row, so ownership-gated calls must use ``make_lessee_headers(lessee_id)``.
"""

from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque operator identities.
    "lessor_ops_headers": build_user_headers("ops-controller-1", "LessorOpsController"),
    "regulatory_authority_headers": build_user_headers("caa-officer-1", "RegulatoryAuthority"),
    "maintenance_controller_headers": build_user_headers("tech-control-1", "MaintenanceController"),
    "billing_admin_headers": build_user_headers("billing-admin-1", "BillingAdmin"),
    "second_billing_admin_headers": build_user_headers("billing-admin-2", "BillingAdmin"),
    "insurance_underwriter_headers": build_user_headers("underwriter-1", "InsuranceUnderwriter"),
    # Lessee is entity-backed: this shared constant is only safe for tests that do not
    # exercise ownership (for example 401/404 shapes), never for ownership-gated calls.
    "lessee_headers": build_user_headers("lessee-not-a-real-row", "Lessee"),
}


def make_lessee_headers(user_id: str) -> dict:
    """Headers for the ``Lessee`` role. ``user_id`` must be the acting Lessee row's id
    whenever the call is ownership-gated (consent, dispute, review, and every read)."""
    return build_user_headers(user_id, "Lessee")


def make_billing_admin_headers(user_id: str) -> dict:
    """Headers for a specific ``BillingAdmin`` operator identifier — needed by the
    segregation-of-duties rule, which compares the preparer's opaque identifier to the
    approver's."""
    return build_user_headers(user_id, "BillingAdmin")


def make_lessor_ops_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "LessorOpsController")


def make_maintenance_controller_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "MaintenanceController")


def make_regulatory_authority_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "RegulatoryAuthority")


def make_insurance_underwriter_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "InsuranceUnderwriter")
