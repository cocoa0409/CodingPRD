"""Pre-built role headers for every role in the PRD.

PRD §2.1 identity rules — verbatim:

    "When `X-User-Role` is `LeagueAdmin`, `X-User-ID` is an opaque
    operator identifier not tied to any persisted entity."

    "When `X-User-Role` is `Coach`, `X-User-ID` is the `id` of the
    acting `Coach`; ownership checks on any resource that references a
    `Coach` (for example, drafting onto a `Team`) compare the
    resource's `head_coach_id` to `X-User-ID`."

    "When `X-User-Role` is `Referee`, `X-User-ID` is the `id` of the
    acting `Referee`; visibility filters on games compare each `Game`'s
    `referee_id` to `X-User-ID`."

    "When `X-User-Role` is `Guardian`, `X-User-ID` is the `id` of the
    acting `Guardian`; ownership checks on a `Player` compare the
    player's `guardian_id` to `X-User-ID`, and ownership checks on a
    `VolunteerShift` compare the shift's `guardian_id` to `X-User-ID`."

Three of the four roles are entity-backed (Coach, Referee, Guardian).
For each, the shared-constant TEST_USERS entry is a FALLBACK suitable
only for tests that do not exercise ownership (auth/role probes, 404
probes). Every ownership-gated call MUST mint headers via the
`make_*_headers(entity_id)` builder with the entity's actual `id` —
otherwise ownership checks would reject every request.

LeagueAdmin is opaque; the shared constant is the canonical form.
"""
from __future__ import annotations

import uuid
from typing import Dict

from prd_bench_local_runner.testing import build_user_headers


# ---------------------------------------------------------------------------
# Stable opaque ids.
# ---------------------------------------------------------------------------
LEAGUE_ADMIN_SHARED_ID: str = "league-admin-op-0001"
LEAGUE_ADMIN_SECONDARY_ID: str = "league-admin-op-0002"

# Entity-backed placeholders — do NOT resolve to any real Coach / Referee
# / Guardian. Used only for auth, role, or 404 probes — NEVER for calls
# whose success depends on ownership.
COACH_PLACEHOLDER_ID: str = "coach-placeholder-0000-0000-0000"
REFEREE_PLACEHOLDER_ID: str = "referee-placeholder-0000-0000-0000"
GUARDIAN_PLACEHOLDER_ID: str = "guardian-placeholder-0000-0000-0000"


TEST_USERS: Dict[str, Dict[str, str]] = {
    # Opaque LeagueAdmin — shared constant is canonical.
    "league_admin_headers": build_user_headers(
        LEAGUE_ADMIN_SHARED_ID, "LeagueAdmin",
    ),
    "league_admin_secondary_headers": build_user_headers(
        LEAGUE_ADMIN_SECONDARY_ID, "LeagueAdmin",
    ),
    # Entity-backed placeholders — for tests that DO NOT exercise
    # ownership. Never use these where ownership matters; build per-
    # entity headers with the actual id via `make_*_headers`.
    "coach_headers": build_user_headers(
        COACH_PLACEHOLDER_ID, "Coach",
    ),
    "referee_headers": build_user_headers(
        REFEREE_PLACEHOLDER_ID, "Referee",
    ),
    "guardian_headers": build_user_headers(
        GUARDIAN_PLACEHOLDER_ID, "Guardian",
    ),
}


# ---------------------------------------------------------------------------
# Per-instance builders — MANDATORY for ownership-gated calls.
# ---------------------------------------------------------------------------
def make_league_admin_headers(operator_id: str) -> Dict[str, str]:
    """LeagueAdmin headers with a specific opaque operator id.

    PRD §2.1: "X-User-ID is an opaque operator identifier not tied to
    any persisted entity. The server may record it ... but does not
    compare it to any entity's `id`."
    """
    return build_user_headers(operator_id, "LeagueAdmin")


def make_coach_headers(coach_id: str) -> Dict[str, str]:
    """Coach headers — MUST carry the Coach.id of the acting head coach
    when calling POST /league/teams/{id}/draft-pick on the team this
    coach owns.

    PRD §2.1: "ownership checks on any resource that references a
    `Coach` (for example, drafting onto a `Team`) compare the resource's
    `head_coach_id` to `X-User-ID`."
    """
    return build_user_headers(coach_id, "Coach")


def make_referee_headers(referee_id: str) -> Dict[str, str]:
    """Referee headers — carry the Referee.id of the acting referee.

    PRD §2.1: "visibility filters on games compare each `Game`'s
    `referee_id` to `X-User-ID`."
    """
    return build_user_headers(referee_id, "Referee")


def make_guardian_headers(guardian_id: str) -> Dict[str, str]:
    """Guardian headers — MUST carry the Guardian.id of the acting
    guardian for every ownership-gated call:
    - POST /league/players (registering own child),
    - POST /league/players/{id}/withdraw (own child),
    - POST /league/volunteer-shifts (own shift),
    - POST /league/volunteer-shifts/{id}/check-in (own shift),
    - DELETE /league/volunteer-shifts/{id} (own shift).

    PRD §2.1: "ownership checks on a `Player` compare the player's
    `guardian_id` to `X-User-ID`, and ownership checks on a
    `VolunteerShift` compare the shift's `guardian_id` to `X-User-ID`."
    """
    return build_user_headers(guardian_id, "Guardian")


# ---------------------------------------------------------------------------
# Operator id generators — for tests that need distinct opaque ids.
# ---------------------------------------------------------------------------
def new_admin_id(prefix: str = "admin") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


__all__ = [
    "LEAGUE_ADMIN_SHARED_ID",
    "LEAGUE_ADMIN_SECONDARY_ID",
    "COACH_PLACEHOLDER_ID",
    "REFEREE_PLACEHOLDER_ID",
    "GUARDIAN_PLACEHOLDER_ID",
    "TEST_USERS",
    "make_league_admin_headers",
    "make_coach_headers",
    "make_referee_headers",
    "make_guardian_headers",
    "new_admin_id",
]
