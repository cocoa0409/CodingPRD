"""Pre-built role headers for every role named in PRD §2.1.

`DsoDealCounsel`, `DsoIntegrationLead` and `DsoFinanceController` are opaque
identities, so a shared constant identifier is the canonical form for them.
`ClinicalDirector` and `Dentist` are entity-backed: their `X-User-ID` must be
the `id` of the acting `Doctor`, so ownership-gated calls MUST go through the
per-instance builders below.
"""

from prd_bench_local_runner.testing import build_user_headers

from .constants import FINANCE_RESERVER_USER_ID, FINANCE_SETTLER_USER_ID

TEST_USERS = {
    # Opaque roles — shared constants are the canonical form.
    "deal_counsel_headers": build_user_headers("u-counsel-1", "DsoDealCounsel"),
    "integration_lead_headers": build_user_headers("u-lead-1", "DsoIntegrationLead"),
    "finance_controller_headers": build_user_headers(
        FINANCE_RESERVER_USER_ID, "DsoFinanceController"
    ),
    "finance_settler_headers": build_user_headers(
        FINANCE_SETTLER_USER_ID, "DsoFinanceController"
    ),
    # Entity-backed roles — these constants are only safe for calls that never
    # resolve the caller to a Doctor row (payload-shape and not-found probes,
    # plus the reads that any role may perform).
    "clinical_director_headers": build_user_headers("u-director-1", "ClinicalDirector"),
    "dentist_headers": build_user_headers("u-dentist-1", "Dentist"),
}


def make_deal_counsel_headers(user_id: str = "u-counsel-1") -> dict:
    """Headers for DsoDealCounsel, an opaque operator identity."""
    return build_user_headers(user_id, "DsoDealCounsel")


def make_integration_lead_headers(user_id: str = "u-lead-1") -> dict:
    """Headers for DsoIntegrationLead, an opaque operator identity."""
    return build_user_headers(user_id, "DsoIntegrationLead")


def make_finance_controller_headers(user_id: str = FINANCE_RESERVER_USER_ID) -> dict:
    """Headers for DsoFinanceController, an opaque operator identity.

    Segregation of duties on settlement compares the recorded reserving user to
    the settling user, so pass two different identifiers when both operations
    must succeed.
    """
    return build_user_headers(user_id, "DsoFinanceController")


def make_clinical_director_headers(doctor_id: str) -> dict:
    """Headers for ClinicalDirector. `doctor_id` must be a real Doctor.id."""
    return build_user_headers(doctor_id, "ClinicalDirector")


def make_dentist_headers(doctor_id: str) -> dict:
    """Headers for Dentist. `doctor_id` must be a real Doctor.id."""
    return build_user_headers(doctor_id, "Dentist")


def no_identity_headers() -> dict:
    """A request carrying neither X-User-ID nor X-User-Role."""
    return {"Content-Type": "application/json"}


ALL_ROLE_NAMES = [
    "DsoDealCounsel",
    "DsoIntegrationLead",
    "DsoFinanceController",
    "ClinicalDirector",
    "Dentist",
]

__all__ = [
    "TEST_USERS",
    "ALL_ROLE_NAMES",
    "make_deal_counsel_headers",
    "make_integration_lead_headers",
    "make_finance_controller_headers",
    "make_clinical_director_headers",
    "make_dentist_headers",
    "no_identity_headers",
]
