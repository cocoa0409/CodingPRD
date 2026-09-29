"""Pre-built role headers for every role the PRD defines.

Five of the six roles are opaque operator identities, so a shared constant is
the canonical form for them.  DealerPrincipal is different: its X-User-ID is the
identifier of the Dealer it acts for, so every ownership-gated DealerPrincipal
call must go through make_dealer_principal_headers(dealer_id).
"""
from prd_bench_local_runner.testing import build_user_headers

# Canonical operator identities used throughout the suite.
CREDIT_OFFICER_USER_ID = "u-co-1"
CREDIT_RISK_MANAGER_USER_ID = "u-crm-1"
CREDIT_RISK_MANAGER_2_USER_ID = "u-crm-2"
FIELD_AUDITOR_USER_ID = "u-fa-1"
FIELD_AUDITOR_2_USER_ID = "u-fa-2"
AUDIT_MANAGER_USER_ID = "u-am-1"
AUDIT_MANAGER_2_USER_ID = "u-am-2"
SYSTEM_OPERATOR_USER_ID = "u-sys-1"

TEST_USERS = {
    # Opaque operator roles — the shared constant is the canonical form.
    "credit_officer_headers": build_user_headers(
        CREDIT_OFFICER_USER_ID, "CreditOfficer"
    ),
    "credit_risk_manager_headers": build_user_headers(
        CREDIT_RISK_MANAGER_USER_ID, "CreditRiskManager"
    ),
    "credit_risk_manager_2_headers": build_user_headers(
        CREDIT_RISK_MANAGER_2_USER_ID, "CreditRiskManager"
    ),
    "field_auditor_headers": build_user_headers(FIELD_AUDITOR_USER_ID, "FieldAuditor"),
    "field_auditor_2_headers": build_user_headers(
        FIELD_AUDITOR_2_USER_ID, "FieldAuditor"
    ),
    "audit_manager_headers": build_user_headers(AUDIT_MANAGER_USER_ID, "AuditManager"),
    "audit_manager_2_headers": build_user_headers(
        AUDIT_MANAGER_2_USER_ID, "AuditManager"
    ),
    "system_operator_headers": build_user_headers(
        SYSTEM_OPERATOR_USER_ID, "SystemOperator"
    ),
    # DealerPrincipal: fallback only for tests that never touch dealer ownership.
    "dealer_principal_headers": build_user_headers(
        "u-dealer-unbound-1", "DealerPrincipal"
    ),
}


def make_dealer_principal_headers(dealer_id: str) -> dict:
    """Headers for a DealerPrincipal acting for the dealer whose id is dealer_id.

    Pass the real Dealer.id: the API treats X-User-ID as the dealer identifier
    and rejects any dealer-scoped access whose dealer_id differs from it.
    """
    return build_user_headers(dealer_id, "DealerPrincipal")


def make_credit_officer_headers(user_id: str) -> dict:
    """Headers for a CreditOfficer with an explicit operator id."""
    return build_user_headers(user_id, "CreditOfficer")


def make_credit_risk_manager_headers(user_id: str) -> dict:
    """Headers for a CreditRiskManager with an explicit operator id."""
    return build_user_headers(user_id, "CreditRiskManager")


def make_field_auditor_headers(user_id: str) -> dict:
    """Headers for a FieldAuditor with an explicit operator id."""
    return build_user_headers(user_id, "FieldAuditor")


def make_audit_manager_headers(user_id: str) -> dict:
    """Headers for an AuditManager with an explicit operator id."""
    return build_user_headers(user_id, "AuditManager")


def make_system_operator_headers(user_id: str) -> dict:
    """Headers for a SystemOperator with an explicit operator id."""
    return build_user_headers(user_id, "SystemOperator")
