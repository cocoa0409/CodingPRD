"""Pre-built role headers for every role in the PRD (§2.1).

OfficeManager, FrontDeskAgent and BankProductOfficer are opaque operator roles —
their X-User-ID is recorded but never compared to any entity id, so the shared
constants are the canonical form. TaxPreparer is the only entity-backed role:
its X-User-ID must be the acting Preparer row's id whenever a call is ownership-
gated, so use make_tax_preparer_headers(preparer_id) for those calls.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — opaque roles use these as their canonical form; the
# TaxPreparer shared constant is a fallback for non-ownership tests only.
TEST_USERS = {
    "office_manager_headers": build_user_headers("test-office-manager-1", "OfficeManager"),
    "front_desk_headers": build_user_headers("test-front-desk-1", "FrontDeskAgent"),
    "tax_preparer_headers": build_user_headers("test-tax-preparer-1", "TaxPreparer"),
    "bank_officer_headers": build_user_headers("test-bank-officer-1", "BankProductOfficer"),
}


def make_tax_preparer_headers(user_id: str) -> dict:
    """For TaxPreparer (entity_backed:Preparer). Pass the actual Preparer.id as
    user_id whenever the call is ownership-gated (e.g. efile, efile-ack, or any
    transition where TaxReturn.preparer_id must match X-User-ID)."""
    return build_user_headers(user_id, "TaxPreparer")
