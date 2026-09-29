"""Pre-built role headers for every role the PRD declares.

Three roles carry an opaque `X-User-ID` (BoardAdmin, AccreditationReviewer,
AppealsPanelist), so a shared constant is the canonical form for them. Two
roles bind their `X-User-ID` to a real record — a ProviderAdmin acts as the
sponsor whose identifier is its `X-User-ID`, and an Attorney acts as the
attorney whose identifier is its `X-User-ID` — so every ownership-gated call
by those roles MUST use the per-instance builder with the real record id.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants. Safe for the opaque roles, and for tests that never touch
# an ownership check (missing-record reads, malformed payloads, role checks).
TEST_USERS = {
    "board_admin_headers": build_user_headers("board-admin-1", "BoardAdmin"),
    "accreditation_reviewer_headers": build_user_headers(
        "reviewer-alpha", "AccreditationReviewer"
    ),
    "appeals_panelist_headers": build_user_headers("panelist-one", "AppealsPanelist"),
    # Entity-backed roles: fallback only, never for ownership-gated calls.
    "provider_admin_headers": build_user_headers("provider-admin-1", "ProviderAdmin"),
    "attorney_headers": build_user_headers("attorney-1", "Attorney"),
}


def make_board_admin_headers(user_id: str) -> dict:
    """BoardAdmin headers under a specific acting identity. Needed where the
    separation-of-duties rule compares one board member against another."""
    return build_user_headers(user_id, "BoardAdmin")


def make_reviewer_headers(user_id: str) -> dict:
    """AccreditationReviewer headers under a specific acting identity."""
    return build_user_headers(user_id, "AccreditationReviewer")


def make_panelist_headers(user_id: str) -> dict:
    """AppealsPanelist headers under a specific acting identity."""
    return build_user_headers(user_id, "AppealsPanelist")


def make_provider_admin_headers(provider_id: str) -> dict:
    """ProviderAdmin headers. Pass the sponsor's own identifier: the PRD binds
    a ProviderAdmin's `X-User-ID` to the provider record it administers."""
    return build_user_headers(provider_id, "ProviderAdmin")


def make_attorney_headers(attorney_id: str) -> dict:
    """Attorney headers. Pass the attorney's own identifier: the PRD binds an
    Attorney's `X-User-ID` to the attorney record it represents."""
    return build_user_headers(attorney_id, "Attorney")


ALL_ROLE_NAMES = [
    "BoardAdmin",
    "AccreditationReviewer",
    "AppealsPanelist",
    "ProviderAdmin",
    "Attorney",
]
