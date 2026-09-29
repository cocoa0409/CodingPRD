"""
Auth headers for the six declared roles.

Identity binding is not uniform, and the difference is load-bearing.

- ``ProgramAdmin``, ``StateAgencyReviewer`` and ``Lender`` present an opaque operator
  identifier that the server records but never resolves to a ``Party`` row, so the
  module-level constants below are correct for them. Three distinct reviewer
  identities are provided because two rules in the contract compare one reviewer's
  identifier against another's: the reviewer who voids a certification may not be the
  one who imposed the duty, and the reviewer who issues a closure letter may not be
  the one who approved the plan.
- ``Redeveloper``, ``EnvironmentalConsultant`` and ``Insurer`` present the ``id`` of
  the ``Party`` row they act as, and the server compares it against
  ``owner_party_id``, ``consultant_party_id`` and ``insurer_party_id``. For those
  three, always build headers from the real party id with
  ``make_redeveloper_headers`` / ``make_consultant_headers`` /
  ``make_insurer_headers``. Reusing a fixed constant for them turns every
  ownership-checked call into ERR_NOT_RESOURCE_OWNER or ERR_PARTY_TYPE_MISMATCH.
"""

from prd_bench_local_runner.testing import build_user_headers

from .types import (
    ROLE_ENVIRONMENTAL_CONSULTANT,
    ROLE_INSURER,
    ROLE_LENDER,
    ROLE_PROGRAM_ADMIN,
    ROLE_REDEVELOPER,
    ROLE_STATE_AGENCY_REVIEWER,
)

# ─── Opaque-identity roles: fixed headers are correct ─────────────────────────

PROGRAM_ADMIN_USER_ID = "admin-1"
REVIEWER_ALPHA_USER_ID = "reviewer-alpha"
REVIEWER_BETA_USER_ID = "reviewer-beta"
REVIEWER_GAMMA_USER_ID = "reviewer-gamma"
LENDER_USER_ID = "lender-1"

PROGRAM_ADMIN = build_user_headers(PROGRAM_ADMIN_USER_ID, ROLE_PROGRAM_ADMIN)
REVIEWER_ALPHA = build_user_headers(REVIEWER_ALPHA_USER_ID, ROLE_STATE_AGENCY_REVIEWER)
REVIEWER_BETA = build_user_headers(REVIEWER_BETA_USER_ID, ROLE_STATE_AGENCY_REVIEWER)
REVIEWER_GAMMA = build_user_headers(REVIEWER_GAMMA_USER_ID, ROLE_STATE_AGENCY_REVIEWER)
LENDER = build_user_headers(LENDER_USER_ID, ROLE_LENDER)

# The reviewer identity most setup steps act under.
REVIEWER = REVIEWER_ALPHA


# ─── Entity-backed roles: build headers from the real Party id ────────────────


def make_redeveloper_headers(party_id: str):
    """Headers for a ``Redeveloper`` acting as the REDEVELOPER Party ``party_id``."""
    return build_user_headers(party_id, ROLE_REDEVELOPER)


def make_consultant_headers(party_id: str):
    """Headers for an ``EnvironmentalConsultant`` acting as the CONSULTANT Party."""
    return build_user_headers(party_id, ROLE_ENVIRONMENTAL_CONSULTANT)


def make_insurer_headers(party_id: str):
    """Headers for an ``Insurer`` acting as the INSURER Party ``party_id``."""
    return build_user_headers(party_id, ROLE_INSURER)


def make_reviewer_headers(user_id: str = REVIEWER_ALPHA_USER_ID):
    """Headers for a ``StateAgencyReviewer`` (identifier is opaque)."""
    return build_user_headers(user_id, ROLE_STATE_AGENCY_REVIEWER)


def make_lender_headers(user_id: str = LENDER_USER_ID):
    """Headers for a ``Lender`` (identifier is opaque)."""
    return build_user_headers(user_id, ROLE_LENDER)


def make_program_admin_headers(user_id: str = PROGRAM_ADMIN_USER_ID):
    """Headers for a ``ProgramAdmin`` (identifier is opaque)."""
    return build_user_headers(user_id, ROLE_PROGRAM_ADMIN)


_ENTITY_BACKED = {
    ROLE_REDEVELOPER: make_redeveloper_headers,
    ROLE_ENVIRONMENTAL_CONSULTANT: make_consultant_headers,
    ROLE_INSURER: make_insurer_headers,
}

_OPAQUE_DEFAULTS = {
    ROLE_STATE_AGENCY_REVIEWER: REVIEWER_ALPHA_USER_ID,
    ROLE_LENDER: LENDER_USER_ID,
    ROLE_PROGRAM_ADMIN: PROGRAM_ADMIN_USER_ID,
}


def headers_for_role(role: str, entity_id: str = None):
    """
    Build headers for any declared role by name.

    ``entity_id`` is required for ``Redeveloper``, ``EnvironmentalConsultant`` and
    ``Insurer`` because their identifier is compared against a persisted Party row.
    """
    if role in _ENTITY_BACKED:
        assert entity_id is not None, f"{role} needs the id of its backing Party row"
        return _ENTITY_BACKED[role](entity_id)
    return build_user_headers(entity_id or _OPAQUE_DEFAULTS[role], role)
