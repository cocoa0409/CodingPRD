"""Pre-built role headers for every role in the PRD.

PRD §2.1 identity rules:

    "All three roles use opaque identity semantics: X-User-ID is an
    opaque operator identifier and the server does not compare it to
    any entity's id for ownership purposes."

All three roles (Paralegal, Attorney, ManagingPartner) are OPAQUE.
Shared *_headers constants are canonical.

There is exactly one place where X-User-ID is compared:

    "The one place this opaque identity is compared, narrowly and by
    design, is the segregation-of-duties check at disbursement
    approval (§3 and validation priority 31)."

For that check, tests must arrange that the ManagingPartner's
X-User-ID differs from the Case.assigned_attorney_id (or matches it,
for the negative case). Two distinct constants per role plus the
per-instance builder make_*_headers(id) cover all scenarios.
"""
from __future__ import annotations

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers


# ---------------------------------------------------------------------------
# Canonical opaque-actor identifiers — PRD §2.1.
# Each role provides two distinct ids so SoD scenarios can disambiguate.
# ---------------------------------------------------------------------------
PARALEGAL_ID: str = "paralegal-001"
PARALEGAL_ID_ALT: str = "paralegal-002"

ATTORNEY_ID: str = "attorney-001"
ATTORNEY_ID_ALT: str = "attorney-002"

MANAGING_PARTNER_ID: str = "managing-partner-001"
MANAGING_PARTNER_ID_ALT: str = "managing-partner-002"


TEST_USERS: Dict[str, Dict[str, str]] = {
    # All three roles are opaque; shared constants are canonical.
    "paralegal_headers": build_user_headers(PARALEGAL_ID, "Paralegal"),
    "paralegal_headers_alt": build_user_headers(
        PARALEGAL_ID_ALT, "Paralegal",
    ),
    "attorney_headers": build_user_headers(ATTORNEY_ID, "Attorney"),
    "attorney_headers_alt": build_user_headers(
        ATTORNEY_ID_ALT, "Attorney",
    ),
    "managing_partner_headers": build_user_headers(
        MANAGING_PARTNER_ID, "ManagingPartner",
    ),
    "managing_partner_headers_alt": build_user_headers(
        MANAGING_PARTNER_ID_ALT, "ManagingPartner",
    ),
}


# ---------------------------------------------------------------------------
# Per-instance builders — useful when a test needs to align (or mis-align)
# X-User-ID with Case.assigned_attorney_id for the segregation-of-duties
# check at disbursement approval. PRD §3.10: "the acting user's X-User-ID
# must not equal Case.assigned_attorney_id".
# ---------------------------------------------------------------------------
def make_paralegal_headers(user_id: str) -> Dict[str, str]:
    """Build headers for a specific Paralegal operator id."""
    return build_user_headers(user_id, "Paralegal")


def make_attorney_headers(user_id: str) -> Dict[str, str]:
    """Build headers for a specific Attorney operator id. Use when a
    test needs the acting attorney's X-User-ID to match (or mismatch)
    a Case.assigned_attorney_id value.
    """
    return build_user_headers(user_id, "Attorney")


def make_managing_partner_headers(user_id: str) -> Dict[str, str]:
    """Build headers for a specific ManagingPartner operator id.

    The segregation-of-duties check at disbursement approval (PRD
    §3.10) compares this id to Case.assigned_attorney_id. Tests that
    want to trigger ERR_SEGREGATION_OF_DUTIES build headers via this
    function passing the same id used as assigned_attorney_id when
    the case was opened.
    """
    return build_user_headers(user_id, "ManagingPartner")


__all__ = [
    "PARALEGAL_ID",
    "PARALEGAL_ID_ALT",
    "ATTORNEY_ID",
    "ATTORNEY_ID_ALT",
    "MANAGING_PARTNER_ID",
    "MANAGING_PARTNER_ID_ALT",
    "TEST_USERS",
    "make_paralegal_headers",
    "make_attorney_headers",
    "make_managing_partner_headers",
]
