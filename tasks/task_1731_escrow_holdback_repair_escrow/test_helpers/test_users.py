"""Pre-built role headers for every role in the PRD (§2.1).

All seven roles are opaque user identifiers: X-User-ID is recorded on created
resources and compared against stored party-id fields, never against entity
ids. Shared constants below use the canonical party ids from constants.PARTIES;
the make_*_headers builders cover ad-hoc users (e.g. a non-party buyer).
"""
from prd_bench_local_runner.testing import build_user_headers

from .constants import PARTIES
from .types import UserRole

TEST_USERS = {
    "officer_headers": build_user_headers(PARTIES["officer"], UserRole.ESCROW_OFFICER.value),
    "buyer_1_headers": build_user_headers(PARTIES["buyer"], UserRole.BUYER.value),
    "seller_1_headers": build_user_headers(PARTIES["seller"], UserRole.SELLER.value),
    "lender_1_headers": build_user_headers(PARTIES["lender"], UserRole.LENDER.value),
    "insurer_1_headers": build_user_headers(PARTIES["insurer"], UserRole.INSURER.value),
    "contr_1_headers": build_user_headers(PARTIES["contractor"], UserRole.CONTRACTOR.value),
    "contr_2_headers": build_user_headers(PARTIES["contractor_b"], UserRole.CONTRACTOR.value),
    "insp_1_headers": build_user_headers(PARTIES["inspector"], UserRole.INSPECTOR.value),
    "insp_2_headers": build_user_headers(PARTIES["inspector_b"], UserRole.INSPECTOR.value),
}


def make_officer_headers(user_id: str = PARTIES["officer"]) -> dict:
    return build_user_headers(user_id, UserRole.ESCROW_OFFICER.value)


def make_buyer_headers(user_id: str) -> dict:
    """Buyer headers; pass the file's buyer_user_id for bid selection (PRD §3.3)."""
    return build_user_headers(user_id, UserRole.BUYER.value)


def make_seller_headers(user_id: str) -> dict:
    return build_user_headers(user_id, UserRole.SELLER.value)


def make_lender_headers(user_id: str) -> dict:
    """Lender headers; pass the file's lender_user_id to decide LENDER approvals."""
    return build_user_headers(user_id, UserRole.LENDER.value)


def make_insurer_headers(user_id: str) -> dict:
    """Insurer headers; pass the file's insurer_user_id to decide INSURER approvals."""
    return build_user_headers(user_id, UserRole.INSURER.value)


def make_contractor_headers(user_id: str) -> dict:
    """Contractor headers; pass the engaged contractor_user_id for draws/completion."""
    return build_user_headers(user_id, UserRole.CONTRACTOR.value)


def make_inspector_headers(user_id: str) -> dict:
    """Inspector headers; pass the inspection's inspector_user_id to report."""
    return build_user_headers(user_id, UserRole.INSPECTOR.value)
