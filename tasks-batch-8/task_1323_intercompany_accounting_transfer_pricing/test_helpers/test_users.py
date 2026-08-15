"""Pre-built role headers for every role in the PRD.

All five roles are opaque: per PRD section 2.1, X-User-ID is an operator
identifier never compared to any entity's id. Shared constants are therefore
the canonical form. The per-role builders exist so segregation-of-duties
probes can pin a specific X-User-ID under a different role header (PRD 2.10
compares the acting X-User-ID against the stored creator/submitter id).
"""
from prd_bench_local_runner.testing import build_user_headers


TEST_USERS = {
    "group_tax_admin_headers": build_user_headers("admin-1", "GroupTaxAdmin"),
    "tax_analyst_headers": build_user_headers("ana-1", "TaxAnalyst"),
    "tax_manager_headers": build_user_headers("mgr-1", "TaxManager"),
    "transfer_pricing_lead_headers": build_user_headers("tpl-1",
                                                        "TransferPricingLead"),
    "treasury_manager_headers": build_user_headers("tre-1", "TreasuryManager"),
}

# Short aliases used throughout fixtures and tests.
ADMIN = TEST_USERS["group_tax_admin_headers"]
ANALYST = TEST_USERS["tax_analyst_headers"]
MANAGER = TEST_USERS["tax_manager_headers"]
TP_LEAD = TEST_USERS["transfer_pricing_lead_headers"]
TREASURY = TEST_USERS["treasury_manager_headers"]


def make_group_tax_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "GroupTaxAdmin")


def make_tax_analyst_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "TaxAnalyst")


def make_tax_manager_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "TaxManager")


def make_transfer_pricing_lead_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "TransferPricingLead")


def make_treasury_manager_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "TreasuryManager")
