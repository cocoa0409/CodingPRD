"""Pre-built role headers for the six roles of PRD §2.1.

PRD §2.1: only `AthleteAgent` is tied to a persisted entity — when the role is
`AthleteAgent`, `X-User-ID` is the `id` of the acting `RepAgent`. Every
ownership-gated agent call therefore has to be made with
`make_athlete_agent_headers(rep_agent["id"])`, never with a shared constant.

The other five roles carry an opaque operator identifier. Two distinct finance
identities are pre-built because segregation of duties compares the approver's
operator id to the payer's.
"""
from prd_bench_local_runner.testing import build_user_headers

# Opaque operator identifiers used by the five non-entity roles.
DIRECTOR_USER_ID = "director-1"
TECHNICAL_OFFICIAL_USER_ID = "tech-official-1"
ANTI_DOPING_USER_ID = "adl-1"
SANCTIONING_BODY_USER_ID = "sanctioning-1"
FINANCE_APPROVER_USER_ID = "fin-approve-1"
FINANCE_PAYER_USER_ID = "fin-pay-2"
FINANCE_SECOND_APPROVER_USER_ID = "fin-approve-3"
FINANCE_SECOND_PAYER_USER_ID = "fin-pay-4"

TEST_USERS = {
    # Opaque roles — the shared constant is the canonical form.
    "elites_director_headers": build_user_headers(DIRECTOR_USER_ID, "ElitesDirector"),
    "technical_official_headers": build_user_headers(
        TECHNICAL_OFFICIAL_USER_ID, "TechnicalOfficial"
    ),
    "anti_doping_liaison_headers": build_user_headers(
        ANTI_DOPING_USER_ID, "AntiDopingLiaison"
    ),
    "sanctioning_body_headers": build_user_headers(
        SANCTIONING_BODY_USER_ID, "SanctioningBody"
    ),
    "finance_officer_headers": build_user_headers(
        FINANCE_APPROVER_USER_ID, "FinanceOfficer"
    ),
    "finance_payer_headers": build_user_headers(FINANCE_PAYER_USER_ID, "FinanceOfficer"),
    "finance_second_approver_headers": build_user_headers(
        FINANCE_SECOND_APPROVER_USER_ID, "FinanceOfficer"
    ),
    "finance_second_payer_headers": build_user_headers(
        FINANCE_SECOND_PAYER_USER_ID, "FinanceOfficer"
    ),
    # Entity-backed role — this shared constant is only safe for calls that are
    # not ownership-gated (reads, 400/404 probes).
    "athlete_agent_headers": build_user_headers("test-agent-unowned", "AthleteAgent"),
}


def make_athlete_agent_headers(rep_agent_id: str) -> dict:
    """Headers for an `AthleteAgent` acting as a specific registered agent.

    Pass the `id` returned by `POST /rep-agents`: PRD §2.1 states that an
    invitation-scoped write by an `AthleteAgent` requires `X-User-ID` to equal
    that invitation's `agent_id`.
    """
    return build_user_headers(rep_agent_id, "AthleteAgent")


def make_elites_director_headers(user_id: str) -> dict:
    """Headers for a specific `ElitesDirector` operator identifier."""
    return build_user_headers(user_id, "ElitesDirector")


def make_finance_officer_headers(user_id: str) -> dict:
    """Headers for a specific `FinanceOfficer` operator identifier."""
    return build_user_headers(user_id, "FinanceOfficer")


def make_technical_official_headers(user_id: str) -> dict:
    """Headers for a specific `TechnicalOfficial` operator identifier."""
    return build_user_headers(user_id, "TechnicalOfficial")


def make_headers(user_id: str, role: str) -> dict:
    """Headers for an arbitrary user id / role pair."""
    return build_user_headers(user_id, role)
