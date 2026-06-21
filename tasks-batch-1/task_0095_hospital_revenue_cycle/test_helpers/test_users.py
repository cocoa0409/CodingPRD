"""Pre-built role headers for every role in the PRD (PRD §2.1).

All four roles use an opaque X-User-ID not tied to any persisted entity, so the
shared-constant form is canonical. The server records X-User-ID only where a
workflow explicitly captures the acting operator (finalized_by_user_id,
approved_by_user_id) and compares those recorded values to each other, never to
an entity id. The per-id builder is provided for the segregation-of-duties tests
that need to control the exact operator identity.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "registrar_headers": build_user_headers("registrar-1", "Registrar"),
    "coder_headers": build_user_headers("coder-1", "Coder"),
    "billing_headers": build_user_headers("billing-1", "BillingSpecialist"),
    "finance_headers": build_user_headers("finance-mgr-1", "FinanceManager"),
}


def make_registrar_headers(user_id: str) -> dict:
    """Registrar headers with an explicit X-User-ID."""
    return build_user_headers(user_id, "Registrar")


def make_coder_headers(user_id: str) -> dict:
    """Coder headers with an explicit X-User-ID. Used to control finalized_by_user_id."""
    return build_user_headers(user_id, "Coder")


def make_billing_headers(user_id: str) -> dict:
    """BillingSpecialist headers with an explicit X-User-ID."""
    return build_user_headers(user_id, "BillingSpecialist")


def make_finance_headers(user_id: str) -> dict:
    """FinanceManager headers with an explicit X-User-ID. Used to control the
    write-off approver identity for segregation-of-duties tests."""
    return build_user_headers(user_id, "FinanceManager")
