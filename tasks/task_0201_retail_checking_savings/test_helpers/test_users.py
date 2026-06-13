"""Pre-built role headers for every role in the PRD (PRD §2.1).

The PRD recognizes exactly three roles, spelled precisely: AccountHolder, Teller,
ComplianceOfficer.

- Teller and ComplianceOfficer are OPAQUE-identity roles: X-User-ID is an opaque
  operator id that the server never compares to a stored entity id. For these,
  shared constants are the canonical form. Segregation-of-duties (PRD §3.3) compares
  the approving/rejecting officer's X-User-ID against the application's recorded
  submitted_by_user_id, so tests need *distinct* opaque ids (e.g. teller-1 vs
  officer-1, and officer-1 vs officer-2) to exercise / avoid that gate.

- AccountHolder is ENTITY-BACKED (entity_backed:Customer): X-User-ID is the acting
  Customer's id, and ownership checks compare it to the account's active owner set
  (PRD §2.1). For ownership-gated calls callers MUST build headers with the real
  Customer.id via make_account_holder_headers(customer_id); the shared constant
  carries a fake id usable only for non-ownership paths (401/403/404).
"""
from prd_bench_local_runner.testing import build_user_headers


TEST_USERS = {
    # Opaque roles — shared constants are canonical.
    "teller_headers": build_user_headers("teller-1", "Teller"),
    "teller2_headers": build_user_headers("teller-2", "Teller"),
    "officer_headers": build_user_headers("officer-1", "ComplianceOfficer"),
    "officer2_headers": build_user_headers("officer-2", "ComplianceOfficer"),
    # Entity-backed role — fake-id fallback for non-ownership tests only.
    "account_holder_headers": build_user_headers(
        "00000000-0000-0000-0000-0000000000ff", "AccountHolder"
    ),
}


def make_account_holder_headers(customer_id: str) -> dict:
    """Headers for the AccountHolder role bound to a specific Customer.id.

    Pass the real Customer.id whenever the call is ownership-gated (deposit,
    withdrawal, close, stop-payment, owner management) — per PRD §2.1 the server
    compares X-User-ID against the account's active owner set.
    """
    return build_user_headers(customer_id, "AccountHolder")


def make_teller_headers(user_id: str = "teller-1") -> dict:
    """Headers for the Teller role (opaque id)."""
    return build_user_headers(user_id, "Teller")


def make_officer_headers(user_id: str = "officer-1") -> dict:
    """Headers for the ComplianceOfficer role (opaque id)."""
    return build_user_headers(user_id, "ComplianceOfficer")


def make_headers(user_id: str, role: str) -> dict:
    """Generic constructor for parametrized RBAC tests."""
    return build_user_headers(user_id, role)
