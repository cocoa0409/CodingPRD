"""Pre-built role headers for every role in the PRD (section 2.1).

All seven roles are opaque: X-User-ID is an operator identifier that is never
compared against any entity's `id`. Shared constants are therefore the
canonical form. Per-instance builders exist so identity-sensitive checks can
pin a specific X-User-ID per call — the segregation-of-duties release guard
(compares against `matched_by_user_id`) and the nurse-visit resolution
ownership check (compares against `nurse_id`).
"""
from prd_bench_local_runner.testing import build_user_headers


TEST_USERS = {
    "hub_admin_headers": build_user_headers("admin-1", "HubAdmin"),
    "case_manager_headers": build_user_headers("cm-1", "CaseManager"),
    "financial_counselor_headers": build_user_headers("fc-1", "FinancialCounselor"),
    "nurse_educator_headers": build_user_headers("nurse-1", "NurseEducator"),
    "pharmacy_partner_headers": build_user_headers("rx-1", "PharmacyPartner"),
    "payer_reviewer_headers": build_user_headers("pr-1", "PayerReviewer"),
    "manufacturer_monitor_headers": build_user_headers("mm-1", "ManufacturerMonitor"),
}


def make_hub_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "HubAdmin")


def make_case_manager_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "CaseManager")


def make_financial_counselor_headers(user_id: str) -> dict:
    """Pin X-User-ID for a FinancialCounselor; anchors matched_by_user_id and
    the segregation-of-duties release check."""
    return build_user_headers(user_id, "FinancialCounselor")


def make_nurse_educator_headers(user_id: str) -> dict:
    """Pin X-User-ID for a NurseEducator; must equal a visit's nurse_id to
    resolve that visit."""
    return build_user_headers(user_id, "NurseEducator")


def make_pharmacy_partner_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "PharmacyPartner")


def make_payer_reviewer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "PayerReviewer")


def make_manufacturer_monitor_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ManufacturerMonitor")
