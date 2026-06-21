"""Pre-built role headers for every role in the PRD (Section 2.1).

Clerk, Judge, and Mediator are opaque operator identities — the shared constants
are the canonical form. Petitioner and Respondent are entity_backed:Party
identities: their shared constants are only a fallback for tests that do NOT
exercise ownership; ownership-gated calls MUST use the per-instance builders with
the bound Party's user_id (PRD §2.1).
"""
from prd_bench_local_runner.testing import build_user_headers


TEST_USERS = {
    # Opaque officer roles — shared constant is canonical.
    "clerk_headers": build_user_headers("u-clerk", "Clerk"),
    "judge_headers": build_user_headers("u-judge", "Judge"),
    "mediator_headers": build_user_headers("u-med", "Mediator"),
    # entity_backed roles — fallback only; use the builders below for ownership.
    "petitioner_headers": build_user_headers("u-pet", "Petitioner"),
    "respondent_headers": build_user_headers("u-res", "Respondent"),
}


def make_clerk_headers(user_id: str = "u-clerk") -> dict:
    """Clerk is opaque; user_id is an arbitrary operator identifier."""
    return build_user_headers(user_id, "Clerk")


def make_judge_headers(user_id: str = "u-judge") -> dict:
    """Judge is opaque; user_id is the acting operator identifier (recorded as
    judge_user_id on final-judgment entry, and compared to mediator_user_id for SoD)."""
    return build_user_headers(user_id, "Judge")


def make_mediator_headers(user_id: str = "u-med") -> dict:
    """Mediator is opaque; user_id must equal Case.mediator_user_id for session ops."""
    return build_user_headers(user_id, "Mediator")


def make_petitioner_headers(user_id: str) -> dict:
    """For the Petitioner role (entity_backed:Party). Pass the petitioning Party's
    user_id so ownership-gated calls (submit disclosure, propose/agree/revise plan)
    resolve against the bound Party."""
    return build_user_headers(user_id, "Petitioner")


def make_respondent_headers(user_id: str) -> dict:
    """For the Respondent role (entity_backed:Party). Pass the responding Party's
    user_id so ownership-gated calls resolve against the bound Party."""
    return build_user_headers(user_id, "Respondent")
