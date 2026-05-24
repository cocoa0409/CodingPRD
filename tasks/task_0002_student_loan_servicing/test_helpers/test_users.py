"""Pre-built role headers for every role in the PRD.

- LoanServicer / PSLFAdjudicator / VADischargeOfficer are opaque-identity roles
  (PRD §2.1); the shared constants here are the canonical form for tests under
  any role-gated endpoint.

- Borrower is entity_backed — the X-User-ID MUST equal the actual Borrower.id
  the test created. Tests that exercise Borrower-role calls MUST use
  `make_borrower_headers(borrower["id"])`, NOT the shared constant. Falling
  back to the shared constant reproduces the canonical ownership-check failure
  (X-User-ID never equals any real Borrower's id).
"""
from prd_bench_local_runner.testing import build_user_headers


TEST_USERS = {
    # Opaque-identity roles: shared constants are the canonical form.
    "servicer_headers": build_user_headers("svc-test-1", "LoanServicer"),
    "servicer_alt_headers": build_user_headers("svc-test-2", "LoanServicer"),
    "pslf_adjudicator_headers": build_user_headers("adj-test-1", "PSLFAdjudicator"),
    "pslf_adjudicator_alt_headers": build_user_headers("adj-test-2", "PSLFAdjudicator"),
    "va_officer_headers": build_user_headers("vad-test-1", "VADischargeOfficer"),
    # Borrower fallback constant — used only for tests where the rejection is
    # explicitly "no such borrower / not the owner" so the literal ID is fine.
    "borrower_headers": build_user_headers("borrower-test-fallback", "Borrower"),
}


def make_borrower_headers(borrower_id: str) -> dict:
    """Per-instance builder for the entity_backed Borrower role.

    Any Borrower-role test whose success depends on the caller owning the
    subject resource MUST use this builder with the real Borrower.id so that
    the server's ownership check (X-User-ID == borrower_id) passes.
    """
    return build_user_headers(borrower_id, "Borrower")


def make_servicer_headers(user_id: str) -> dict:
    """Per-instance builder for a LoanServicer with a specific opaque user_id.

    Used when a test needs to record an action under a controlled X-User-ID
    (for example to set up an SoD violation by recording a payment under the
    same ID that later attempts a PSLF discharge approval).
    """
    return build_user_headers(user_id, "LoanServicer")


def make_pslf_adjudicator_headers(user_id: str) -> dict:
    """Per-instance builder for a PSLFAdjudicator with a specific opaque user_id."""
    return build_user_headers(user_id, "PSLFAdjudicator")


def make_va_officer_headers(user_id: str) -> dict:
    """Per-instance builder for a VADischargeOfficer with a specific opaque user_id."""
    return build_user_headers(user_id, "VADischargeOfficer")
