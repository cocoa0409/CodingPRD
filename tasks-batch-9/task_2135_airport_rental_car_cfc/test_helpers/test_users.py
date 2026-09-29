"""Pre-built role headers for every role the PRD recognises (§2.1).

`FacilityAdmin`, `AuditOfficer` and `FinanceOfficer` present an opaque operator
identifier that is never compared against any row's `id`, so the shared
constants below are the canonical form for them.

`ConcessionaireOperator` is different in kind: its `X-User-ID` is the `id` of
the acting `Concessionaire` row, and every ownership check compares that value
to the brand reached from the target resource.  Ownership-gated calls MUST
therefore use `make_operator_headers(concessionaire["id"])`.
"""

from prd_bench_local_runner.testing import build_user_headers

# Stable opaque operator identifiers used by the officer roles.
FACILITY_ADMIN_USER_ID = "adm-1"
AUDIT_OFFICER_USER_ID = "aud-1"
AUDIT_OFFICER_2_USER_ID = "aud-2"
FINANCE_OFFICER_USER_ID = "fin-1"
FINANCE_OFFICER_2_USER_ID = "fin-2"

TEST_USERS = {
    "facility_admin_headers": build_user_headers(FACILITY_ADMIN_USER_ID, "FacilityAdmin"),
    "audit_officer_headers": build_user_headers(AUDIT_OFFICER_USER_ID, "AuditOfficer"),
    "audit_officer_2_headers": build_user_headers(AUDIT_OFFICER_2_USER_ID, "AuditOfficer"),
    "finance_officer_headers": build_user_headers(FINANCE_OFFICER_USER_ID, "FinanceOfficer"),
    "finance_officer_2_headers": build_user_headers(FINANCE_OFFICER_2_USER_ID, "FinanceOfficer"),
    # Fallback only — safe for calls that never touch an ownership check
    # (role-denial probes and unknown-resource probes).
    "operator_headers": build_user_headers(
        "00000000-0000-4000-8000-000000000000", "ConcessionaireOperator"
    ),
}


def make_operator_headers(concessionaire_id: str) -> dict:
    """Headers for a ConcessionaireOperator acting as a specific brand.

    Pass the `id` returned when the airport authority registered the brand;
    that value is what every ownership check compares against.
    """
    return build_user_headers(concessionaire_id, "ConcessionaireOperator")


def make_facility_admin_headers(user_id: str = FACILITY_ADMIN_USER_ID) -> dict:
    return build_user_headers(user_id, "FacilityAdmin")


def make_audit_officer_headers(user_id: str = AUDIT_OFFICER_USER_ID) -> dict:
    return build_user_headers(user_id, "AuditOfficer")


def make_finance_officer_headers(user_id: str = FINANCE_OFFICER_USER_ID) -> dict:
    return build_user_headers(user_id, "FinanceOfficer")


# Convenience aliases used throughout the suite.
ADMIN = TEST_USERS["facility_admin_headers"]
AUDITOR = TEST_USERS["audit_officer_headers"]
AUDITOR_2 = TEST_USERS["audit_officer_2_headers"]
TREASURY = TEST_USERS["finance_officer_headers"]
TREASURY_2 = TEST_USERS["finance_officer_2_headers"]
