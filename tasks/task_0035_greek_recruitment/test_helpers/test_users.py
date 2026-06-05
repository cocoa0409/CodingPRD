"""Pre-built role headers for every role in the PRD (PRD §2.1).

Per PRD §2.1, two roles are entity-backed:
- `ChapterOfficer` -> `X-User-ID` MUST equal an existing `Chapter.id`. Ownership
  checks compare `Party.chapter_id` / `BidMatch.chapter_id` to `X-User-ID`.
- `PNM` -> `X-User-ID` MUST equal an existing `PNM.id`. Ownership checks
  compare `PartyInvitation.pnm_id` / `BidMatch.pnm_id` to `X-User-ID`.

For entity-backed roles, fixtures and tests MUST call
`make_chapter_officer_headers(chapter_id)` / `make_pnm_headers(pnm_id)` with
the actual entity's UUID. The `TEST_USERS` shared constants for these roles
are non-ownership fallbacks only (401/403/404 negative paths).

`PanhellenicAdmin`, `RecruitmentChair`, `RiskOfficer`, and `Anonymous` are
opaque; the shared constants are the canonical form for those.
"""
from prd_bench_local_runner.testing import build_user_headers


TEST_USERS = {
    # Opaque roles — shared constants are the canonical form.
    "panhellenic_admin_headers": build_user_headers(
        "test-admin-1", "PanhellenicAdmin"
    ),
    "recruitment_chair_headers": build_user_headers(
        "test-recruitment-chair-1", "RecruitmentChair"
    ),
    "risk_officer_headers": build_user_headers("test-risk-officer-1", "RiskOfficer"),
    "anonymous_headers": build_user_headers("test-anonymous-1", "Anonymous"),
    # Entity-backed fallbacks — DO NOT use for ownership-gated calls.
    "chapter_officer_headers": build_user_headers(
        "test-chapter-officer-1", "ChapterOfficer"
    ),
    "pnm_headers": build_user_headers("test-pnm-1", "PNM"),
}


def make_panhellenic_admin_headers(user_id: str = "test-admin-1") -> dict:
    return build_user_headers(user_id, "PanhellenicAdmin")


def make_recruitment_chair_headers(
    user_id: str = "test-recruitment-chair-1",
) -> dict:
    return build_user_headers(user_id, "RecruitmentChair")


def make_risk_officer_headers(user_id: str = "test-risk-officer-1") -> dict:
    return build_user_headers(user_id, "RiskOfficer")


def make_chapter_officer_headers(chapter_id: str) -> dict:
    """Headers for ChapterOfficer bound to the Chapter.id whose resources are being
    acted upon (PRD §2.1). Pass the actual Chapter.id."""
    return build_user_headers(chapter_id, "ChapterOfficer")


def make_pnm_headers(pnm_id: str) -> dict:
    """Headers for PNM bound to the PNM.id whose resources are being acted upon
    (PRD §2.1). Pass the actual PNM.id."""
    return build_user_headers(pnm_id, "PNM")


def make_anonymous_headers(user_id: str = "test-anonymous-1") -> dict:
    return build_user_headers(user_id, "Anonymous")


def make_headers(user_id: str, role: str) -> dict:
    """Generic constructor for parametrized RBAC tests."""
    return build_user_headers(user_id, role)
