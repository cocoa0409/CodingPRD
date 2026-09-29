"""Caller identities and auth headers.

§2.1 of the PRD splits identity into two very different shapes and the split is
load-bearing:

* ``PlatformAdmin``, ``Declarant``, ``Auditor`` and ``ElectionInspector`` carry
  "an opaque operator identifier not tied to any persisted entity", so a
  module-level constant is the right representation.
* ``TransitionCommittee`` does **not**: "When ``X-User-Role`` is
  ``TransitionCommittee``, ``X-User-ID`` is the ``id`` of the acting
  ``Association``". There is therefore deliberately **no** committee header
  constant in this module — a committee header can only be built once the
  association exists, via ``make_transition_committee_headers``. Reusing a
  fixed committee id would make every committee-driven setup call fail with
  ``ERR_ROLE_NOT_PERMITTED``.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ROLE_AUDITOR,
    ROLE_DECLARANT,
    ROLE_ELECTION_INSPECTOR,
    ROLE_PLATFORM_ADMIN,
    ROLE_TRANSITION_COMMITTEE,
)

# ─── Opaque operator identifiers ──────────────────────

PLATFORM_ADMIN_USER_ID = "admin-1"
DECLARANT_USER_ID = "declarant-1"
AUDITOR_USER_ID = "auditor-9"
ELECTION_INSPECTOR_USER_ID = "inspector-1"

# A single human who acts both as the ledger poster and as the auditor, used to
# exercise the segregation-of-duties comparison of §2.1.
SHARED_OPERATOR_USER_ID = "shared-1"
# A poster whose entries sit outside the audited window: "an auditor who posted
# money outside the window is untainted and may still issue."
OUTSIDE_WINDOW_OPERATOR_USER_ID = "outsider-2"

# ─── Ready-made headers for the opaque roles ──────────

ADMIN_HEADERS: Dict[str, str] = build_user_headers(
    PLATFORM_ADMIN_USER_ID, ROLE_PLATFORM_ADMIN
)
DECLARANT_HEADERS: Dict[str, str] = build_user_headers(
    DECLARANT_USER_ID, ROLE_DECLARANT
)
AUDITOR_HEADERS: Dict[str, str] = build_user_headers(AUDITOR_USER_ID, ROLE_AUDITOR)
INSPECTOR_HEADERS: Dict[str, str] = build_user_headers(
    ELECTION_INSPECTOR_USER_ID, ROLE_ELECTION_INSPECTOR
)


def make_transition_committee_headers(association_id: str) -> Dict[str, str]:
    """Committee headers for the association the committee actually represents.

    §2.1: "ownership checks on any resource that references an ``Association``
    compare the resource's ``association_id`` foreign-key field to
    ``X-User-ID``".
    """
    return build_user_headers(association_id, ROLE_TRANSITION_COMMITTEE)


def make_declarant_headers(user_id: str) -> Dict[str, str]:
    """Declarant headers for a specific operator identifier."""
    return build_user_headers(user_id, ROLE_DECLARANT)


def make_auditor_headers(user_id: str) -> Dict[str, str]:
    """Auditor headers for a specific operator identifier."""
    return build_user_headers(user_id, ROLE_AUDITOR)


def make_inspector_headers(user_id: str) -> Dict[str, str]:
    """Election inspector headers for a specific operator identifier."""
    return build_user_headers(user_id, ROLE_ELECTION_INSPECTOR)


def make_admin_headers(user_id: str) -> Dict[str, str]:
    """Platform administrator headers for a specific operator identifier."""
    return build_user_headers(user_id, ROLE_PLATFORM_ADMIN)


def make_headers(user_id: str, role: str) -> Dict[str, str]:
    """Arbitrary identity/role pair, including role spellings the API rejects."""
    return build_user_headers(user_id, role)


# ─── Malformed auth headers (§2.1 / ladder rung 1) ────

HEADERS_WITHOUT_ROLE: Dict[str, str] = {
    "X-User-ID": PLATFORM_ADMIN_USER_ID,
    "Content-Type": "application/json",
}

HEADERS_WITHOUT_USER_ID: Dict[str, str] = {
    "X-User-Role": ROLE_PLATFORM_ADMIN,
    "Content-Type": "application/json",
}

HEADERS_NO_AUTH: Dict[str, str] = {"Content-Type": "application/json"}

UNKNOWN_ROLE_NAME = "CommunityManager"

HEADERS_UNKNOWN_ROLE: Dict[str, str] = build_user_headers(
    PLATFORM_ADMIN_USER_ID, UNKNOWN_ROLE_NAME
)
