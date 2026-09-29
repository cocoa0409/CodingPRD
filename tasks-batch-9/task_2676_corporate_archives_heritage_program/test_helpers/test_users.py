"""Pre-built auth headers for every role.

Six of the seven roles are opaque operator identities: any stable string may be
sent as ``X-User-ID`` and the API only reads it to stamp actor fields and to
enforce segregation of duties. Two distinct identities are provided for each
role that participates in a segregation-of-duties rule so that a test can
choose a colliding or a non-colliding actor deliberately.

``Requester`` is the one entity-backed role: its ``X-User-ID`` must equal the
id of the Requester row it acts for, so its headers are built per row by
``make_requester_headers``.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .types import (
    ROLE_ACCESS_SERVICES_OFFICER,
    ROLE_ARCHIVES_DIRECTOR,
    ROLE_ARCHIVIST,
    ROLE_LEGAL_COUNSEL,
    ROLE_PRESERVATION_OFFICER,
    ROLE_REQUESTER,
    ROLE_SYSTEM_OPERATOR,
)

# ─── Actor identities ─────────────────────────────────────────────────────
DIRECTOR_A_ID = "director-a"
DIRECTOR_B_ID = "director-b"
ARCHIVIST_A_ID = "archivist-a"
ARCHIVIST_B_ID = "archivist-b"
PRESERV_A_ID = "preserv-a"
PRESERV_B_ID = "preserv-b"
OFFICER_A_ID = "officer-a"
OFFICER_B_ID = "officer-b"
OFFICER_C_ID = "officer-c"
COUNSEL_A_ID = "counsel-a"
COUNSEL_B_ID = "counsel-b"
OPERATOR_ID = "operator-a"

# ─── Shared header dicts ──────────────────────────────────────────────────
DIRECTOR_A = build_user_headers(DIRECTOR_A_ID, ROLE_ARCHIVES_DIRECTOR)
DIRECTOR_B = build_user_headers(DIRECTOR_B_ID, ROLE_ARCHIVES_DIRECTOR)
ARCHIVIST_A = build_user_headers(ARCHIVIST_A_ID, ROLE_ARCHIVIST)
ARCHIVIST_B = build_user_headers(ARCHIVIST_B_ID, ROLE_ARCHIVIST)
PRESERV_A = build_user_headers(PRESERV_A_ID, ROLE_PRESERVATION_OFFICER)
PRESERV_B = build_user_headers(PRESERV_B_ID, ROLE_PRESERVATION_OFFICER)
OFFICER_A = build_user_headers(OFFICER_A_ID, ROLE_ACCESS_SERVICES_OFFICER)
OFFICER_B = build_user_headers(OFFICER_B_ID, ROLE_ACCESS_SERVICES_OFFICER)
OFFICER_C = build_user_headers(OFFICER_C_ID, ROLE_ACCESS_SERVICES_OFFICER)
COUNSEL_A = build_user_headers(COUNSEL_A_ID, ROLE_LEGAL_COUNSEL)
COUNSEL_B = build_user_headers(COUNSEL_B_ID, ROLE_LEGAL_COUNSEL)
OPERATOR = build_user_headers(OPERATOR_ID, ROLE_SYSTEM_OPERATOR)


def make_requester_headers(requester_id: str) -> Dict[str, str]:
    """Headers for the entity-backed Requester role.

    ``X-User-ID`` carries the id of the Requester row, which is how the API
    identifies which requester is speaking.
    """
    return build_user_headers(requester_id, ROLE_REQUESTER)


def make_headers(user_id: str, role: str) -> Dict[str, str]:
    """Arbitrary identity/role pair, for cross-role identity-collision tests."""
    return build_user_headers(user_id, role)


def headers_without_user_id(role: str) -> Dict[str, str]:
    """Headers that name a role but omit ``X-User-ID`` entirely."""
    return {"X-User-Role": role, "Content-Type": "application/json"}


def headers_without_role(user_id: str) -> Dict[str, str]:
    """Headers that name a user but omit ``X-User-Role`` entirely."""
    return {"X-User-ID": user_id, "Content-Type": "application/json"}
