"""Pre-built role headers for every role in the PRD.

PRD §2.1 identity rules:

  "When `X-User-Role` is `AccountHolder`, `X-User-ID` is the `id` of the
   acting `Account`; ownership checks on any resource that references an
   `Account` compare the resource's `account_id` field (directly, or
   through its parent `Violation` in the case of a `Fine`) to
   `X-User-ID`, and a mismatch is rejected with `ERR_FORBIDDEN`. When
   `X-User-Role` is `AgencyAdmin` or `GantryOperator`, `X-User-ID` is an
   opaque operator identifier not tied to any persisted entity."

Therefore:

* AccountHolder is entity_backed:Account — any ownership-gated call MUST
  use make_account_holder_headers(account_id) with the REAL Account.id.
  The shared constant in TEST_USERS is only safe for non-ownership probes
  (ERR_MISSING_AUTH / ERR_INVALID_ROLE / ERR_FORBIDDEN role probes on
  endpoints AccountHolder cannot reach at all).
* AgencyAdmin is opaque — the shared constant is the canonical form.
* GantryOperator is opaque — the shared constant is the canonical form.
"""
from __future__ import annotations

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers


# ---------------------------------------------------------------------------
# Bootstrap identifiers — only AgencyAdmin and GantryOperator are opaque
# and may use shared constants.
# ---------------------------------------------------------------------------
AGENCY_ADMIN_ID: str = "agency-admin-bootstrap-0001"
GANTRY_OPERATOR_ID: str = "gantry-operator-bootstrap-0001"
ACCOUNT_HOLDER_PLACEHOLDER_ID: str = "account-holder-placeholder-0001"


TEST_USERS: Dict[str, Dict[str, str]] = {
    # AccountHolder is entity_backed — shared constant only valid for
    # tests that do not exercise ownership (auth/role probes that get
    # rejected before ownership checks fire).
    "account_holder_headers": build_user_headers(
        ACCOUNT_HOLDER_PLACEHOLDER_ID, "AccountHolder",
    ),
    # AgencyAdmin is opaque — shared constant is canonical.
    "agency_admin_headers": build_user_headers(
        AGENCY_ADMIN_ID, "AgencyAdmin",
    ),
    # GantryOperator is opaque — shared constant is canonical.
    "gantry_operator_headers": build_user_headers(
        GANTRY_OPERATOR_ID, "GantryOperator",
    ),
}


# ---------------------------------------------------------------------------
# Per-instance builder — MANDATORY for AccountHolder whenever the call is
# ownership-gated. PRD §2.1: "X-User-ID is the `id` of the acting Account".
# ---------------------------------------------------------------------------
def make_account_holder_headers(account_id: str) -> Dict[str, str]:
    """Headers for an AccountHolder identified by a real Account.id.

    Use whenever the call is ownership-gated (PATCH/GET/POST on a specific
    account's resources). Passing a non-matching id reproduces the
    canonical bug: every ownership check returns ERR_FORBIDDEN and
    cascades into Setup failures.
    """
    return build_user_headers(account_id, "AccountHolder")


def make_agency_admin_headers(operator_id: str = AGENCY_ADMIN_ID) -> Dict[str, str]:
    """Headers for an AgencyAdmin (opaque identity)."""
    return build_user_headers(operator_id, "AgencyAdmin")


def make_gantry_operator_headers(operator_id: str = GANTRY_OPERATOR_ID) -> Dict[str, str]:
    """Headers for a GantryOperator (opaque identity)."""
    return build_user_headers(operator_id, "GantryOperator")


__all__ = [
    "AGENCY_ADMIN_ID",
    "GANTRY_OPERATOR_ID",
    "ACCOUNT_HOLDER_PLACEHOLDER_ID",
    "TEST_USERS",
    "make_account_holder_headers",
    "make_agency_admin_headers",
    "make_gantry_operator_headers",
]
