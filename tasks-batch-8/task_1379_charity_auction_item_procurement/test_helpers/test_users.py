"""Pre-built role headers for every role in the PRD.

GalaAdmin, ProcurementOfficer, ValuationApprover, CatalogManager and
FinanceOfficer carry opaque operator identifiers. Bidder and Donor are
entity-backed: whenever a call is ownership-gated (paying an invoice,
redeeming a certificate, responding to a disposition) the headers MUST be
built with the actual entity id via make_bidder_headers / make_donor_headers.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles and for tests that do not
# exercise ownership (400-on-bad-payload, 404-on-missing-resource, and
# any call by the five opaque roles).
TEST_USERS = {
    "gala_admin_headers": build_user_headers("gala-admin-1", "GalaAdmin"),
    "procurement_officer_headers": build_user_headers("po_1",
                                                      "ProcurementOfficer"),
    "valuation_approver_headers": build_user_headers("va_1",
                                                     "ValuationApprover"),
    "catalog_manager_headers": build_user_headers("cm_1", "CatalogManager"),
    "finance_officer_headers": build_user_headers("fo_1", "FinanceOfficer"),
    # Entity-backed roles: fallback constants for non-ownership tests only.
    "bidder_headers": build_user_headers("test-bidder-1", "Bidder"),
    "donor_headers": build_user_headers("test-donor-1", "Donor"),
}


def make_gala_admin_headers(user_id="gala-admin-1") -> dict:
    return build_user_headers(user_id, "GalaAdmin")


def make_procurement_officer_headers(user_id="po_1") -> dict:
    return build_user_headers(user_id, "ProcurementOfficer")


def make_valuation_approver_headers(user_id="va_1") -> dict:
    return build_user_headers(user_id, "ValuationApprover")


def make_catalog_manager_headers(user_id="cm_1") -> dict:
    return build_user_headers(user_id, "CatalogManager")


def make_finance_officer_headers(user_id="fo_1") -> dict:
    return build_user_headers(user_id, "FinanceOfficer")


def make_bidder_headers(user_id: str) -> dict:
    """For Bidder (entity-backed:Bidder). Pass the actual Bidder.id whenever
    the call is ownership-gated."""
    return build_user_headers(user_id, "Bidder")


def make_donor_headers(user_id: str) -> dict:
    """For Donor (entity-backed:Donor). Pass the actual Donor.id whenever
    the call is ownership-gated."""
    return build_user_headers(user_id, "Donor")
