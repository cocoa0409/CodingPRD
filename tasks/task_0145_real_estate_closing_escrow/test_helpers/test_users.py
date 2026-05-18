"""Pre-built role headers for every role in the PRD.

PRD §2.1 identity rules:

- EscrowOfficer, TitleOfficer, DisbursementApprover are OPAQUE. PRD §2.1:
    "When X-User-Role is EscrowOfficer, X-User-ID is an opaque operator
    identifier not tied to any persisted entity."
    "When X-User-Role is TitleOfficer, X-User-ID is an opaque operator
    identifier not tied to any persisted entity."
    "When X-User-Role is DisbursementApprover, X-User-ID is an opaque
    operator identifier not tied to any persisted entity".
  Shared constants are canonical for these roles. Two distinct
  EscrowOfficer ids exist to exercise the segregation-of-duties rule:
  the CD issuer identifier vs the wire/disbursement approver identifier
  must differ.

- Buyer is ENTITY-BACKED. PRD §2.1: "When X-User-Role is Buyer,
  X-User-ID is the id of the acting Party; ownership checks on any
  resource that references a Party compare the resource's foreign-key
  field to X-User-ID."

  Every Buyer-acting call whose success depends on owning the
  EscrowFile.buyer_party_id MUST mint headers via
  make_buyer_headers(buyer_party["id"]) using the actual Party.id
  returned by POST /parties. Falling back to BUYER_FALLBACK_ID for an
  entity-backed role reproduces the canonical bug: the literal
  "fallback-buyer-1" never equals any real Party.id, so every ownership
  check rejects every request regardless of implementation correctness.

- Seller is ENTITY-BACKED analogously — X-User-ID is the Party.id whose
  party_kind is SELLER on the targeted escrow file.

The shared *_FALLBACK_ID constants are ONLY safe for tests that DO NOT
exercise ownership (header-missing, role-mismatch on a non-existent
resource, or 404 paths).
"""
from __future__ import annotations

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers


# ---------------------------------------------------------------------------
# Canonical opaque-actor identifiers — PRD §2.1
# ---------------------------------------------------------------------------
ESCROW_OFFICER_ID: str = "escrow-officer-001"
ESCROW_OFFICER_ID_ALT: str = "escrow-officer-002"
# A third escrow officer id used when tests need a third distinct
# operator (e.g., the latest-CD-issuer was a different person than both
# the wire-confirmer and the disbursement-approver).
ESCROW_OFFICER_ID_THIRD: str = "escrow-officer-003"

TITLE_OFFICER_ID: str = "title-officer-001"
TITLE_OFFICER_ID_ALT: str = "title-officer-002"

DISBURSEMENT_APPROVER_ID: str = "disb-approver-001"
DISBURSEMENT_APPROVER_ID_ALT: str = "disb-approver-002"

# Entity-backed fallback ids — DO NOT use for ownership-gated calls.
# Safe only for header-missing / role-mismatch / NotFound paths.
BUYER_FALLBACK_ID: str = "fallback-buyer-1"
SELLER_FALLBACK_ID: str = "fallback-seller-1"


TEST_USERS: Dict[str, Dict[str, str]] = {
    # Opaque EscrowOfficer — shared constants are canonical.
    "escrow_officer_headers": build_user_headers(
        ESCROW_OFFICER_ID, "EscrowOfficer",
    ),
    "escrow_officer_headers_alt": build_user_headers(
        ESCROW_OFFICER_ID_ALT, "EscrowOfficer",
    ),
    "escrow_officer_headers_third": build_user_headers(
        ESCROW_OFFICER_ID_THIRD, "EscrowOfficer",
    ),
    # Opaque TitleOfficer.
    "title_officer_headers": build_user_headers(
        TITLE_OFFICER_ID, "TitleOfficer",
    ),
    "title_officer_headers_alt": build_user_headers(
        TITLE_OFFICER_ID_ALT, "TitleOfficer",
    ),
    # Opaque DisbursementApprover.
    "disb_approver_headers": build_user_headers(
        DISBURSEMENT_APPROVER_ID, "DisbursementApprover",
    ),
    "disb_approver_headers_alt": build_user_headers(
        DISBURSEMENT_APPROVER_ID_ALT, "DisbursementApprover",
    ),
    # Entity-backed Buyer / Seller fallbacks — DO NOT use for
    # ownership-gated calls. Safe only for header-missing /
    # role-mismatch / 404 paths.
    "buyer_fallback_headers": build_user_headers(
        BUYER_FALLBACK_ID, "Buyer",
    ),
    "seller_fallback_headers": build_user_headers(
        SELLER_FALLBACK_ID, "Seller",
    ),
}


# ---------------------------------------------------------------------------
# Per-instance builders — REQUIRED for entity-backed Buyer and Seller.
# The runtime Party.id minted by POST /parties is the value the
# implementation will compare against in ownership checks.
# ---------------------------------------------------------------------------
def make_buyer_headers(party_id: str) -> Dict[str, str]:
    """For Buyer (entity_backed:Party).

    PRD §2.1: "When X-User-Role is Buyer, X-User-ID is the id of the
    acting Party; ownership checks on any resource that references a
    Party compare the resource's foreign-key field to X-User-ID.
    Concretely, a buyer can only acknowledge a Closing Disclosure or
    sign a CC&R disclosure on an escrow file whose buyer_party_id
    equals the caller's X-User-ID."

    Pass the actual Party.id whose party_kind is BUYER (i.e.,
    escrow_file["buyer_party_id"]). Every Buyer-acting ownership-gated
    call MUST use this builder, never the shared BUYER_FALLBACK_ID
    constant.
    """
    return build_user_headers(party_id, "Buyer")


def make_seller_headers(party_id: str) -> Dict[str, str]:
    """For Seller (entity_backed:Party).

    PRD §2.1: "When X-User-Role is Seller, X-User-ID is the id of the
    acting Party; ownership checks compare the resource's foreign-key
    field (typically seller_party_id on the related EscrowFile) to
    X-User-ID."

    Pass the actual Party.id whose party_kind is SELLER (i.e.,
    escrow_file["seller_party_id"]).
    """
    return build_user_headers(party_id, "Seller")


def make_escrow_officer_headers(user_id: str) -> Dict[str, str]:
    """For EscrowOfficer (opaque). Pass any string id."""
    return build_user_headers(user_id, "EscrowOfficer")


def make_title_officer_headers(user_id: str) -> Dict[str, str]:
    """For TitleOfficer (opaque). Pass any string id."""
    return build_user_headers(user_id, "TitleOfficer")


def make_disb_approver_headers(user_id: str) -> Dict[str, str]:
    """For DisbursementApprover (opaque). Pass any string id."""
    return build_user_headers(user_id, "DisbursementApprover")


__all__ = [
    "ESCROW_OFFICER_ID",
    "ESCROW_OFFICER_ID_ALT",
    "ESCROW_OFFICER_ID_THIRD",
    "TITLE_OFFICER_ID",
    "TITLE_OFFICER_ID_ALT",
    "DISBURSEMENT_APPROVER_ID",
    "DISBURSEMENT_APPROVER_ID_ALT",
    "BUYER_FALLBACK_ID",
    "SELLER_FALLBACK_ID",
    "TEST_USERS",
    "make_buyer_headers",
    "make_seller_headers",
    "make_escrow_officer_headers",
    "make_title_officer_headers",
    "make_disb_approver_headers",
]
