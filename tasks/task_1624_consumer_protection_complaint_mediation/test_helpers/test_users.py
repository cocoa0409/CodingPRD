"""Pre-built role headers for every role in the PRD (§2.1).

Entity-backed roles (Consumer, Business, Mediator) MUST be built per instance via
the make_*_headers builders with the actual entity id whenever the call is
ownership-gated; the shared constants are fallbacks for non-ownership tests only.
Opaque roles (Anonymous, IntakeOfficer, EnforcementAttorney, UnitDirector) use the
shared constants freely — their ids are operator identifiers, never entity ids.
"""
from prd_bench_local_runner.testing import build_user_headers

# Opaque operator identifiers used across tests (segregation-of-duties anchors,
# PRD §2.7: these ids are compared between operators, never to entity ids).
OFFICER_1_ID = "officer-1"
OFFICER_2_ID = "officer-2"
ATTORNEY_1_ID = "att-1"
ATTORNEY_9_ID = "att-9"
DIRECTOR_1_ID = "dir-1"
DIRECTOR_2_ID = "dir-2"
DIRECTOR_3_ID = "dir-3"
ANONYMOUS_ID = "anon-1"

TEST_USERS = {
    # Opaque role: canonical shared form.
    "anonymous_headers": build_user_headers(ANONYMOUS_ID, "Anonymous"),
    # Entity-backed roles: shared constants are fallbacks for non-ownership tests only.
    "consumer_headers": build_user_headers("test-consumer-1", "Consumer"),
    "business_headers": build_user_headers("test-business-1", "Business"),
    "mediator_headers": build_user_headers("test-mediator-1", "Mediator"),
    # Opaque staff roles.
    "intake_officer_headers": build_user_headers(OFFICER_1_ID, "IntakeOfficer"),
    "intake_officer_2_headers": build_user_headers(OFFICER_2_ID, "IntakeOfficer"),
    "enforcement_attorney_headers": build_user_headers(ATTORNEY_1_ID, "EnforcementAttorney"),
    "enforcement_attorney_2_headers": build_user_headers(ATTORNEY_9_ID, "EnforcementAttorney"),
    "unit_director_headers": build_user_headers(DIRECTOR_1_ID, "UnitDirector"),
    "unit_director_2_headers": build_user_headers(DIRECTOR_2_ID, "UnitDirector"),
    "unit_director_3_headers": build_user_headers(DIRECTOR_3_ID, "UnitDirector"),
}


# --- Per-instance builders (mandatory for entity-backed roles) ---
def make_consumer_headers(user_id: str) -> dict:
    """Consumer is entity-backed: pass the actual Consumer.id for ownership-gated calls."""
    return build_user_headers(user_id, "Consumer")


def make_business_headers(user_id: str) -> dict:
    """Business is entity-backed: pass the actual Business.id for ownership-gated calls."""
    return build_user_headers(user_id, "Business")


def make_mediator_headers(user_id: str) -> dict:
    """Mediator is entity-backed: pass the actual Mediator.id for ownership-gated calls."""
    return build_user_headers(user_id, "Mediator")


# --- Opaque-role builders (for arbitrary operator ids) ---
def make_anonymous_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "Anonymous")


def make_intake_officer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "IntakeOfficer")


def make_enforcement_attorney_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "EnforcementAttorney")


def make_unit_director_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "UnitDirector")
