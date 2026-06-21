"""Pre-built role headers for every role in the PRD (§2.1).

ElectionAdmin, ElectionOfficial, PollWorker, and Canvasser carry OPAQUE operator
identifiers: the X-User-ID is recorded for attribution (tally recorder, registration
reviewer, cure adjudicator) but is never compared to any entity's id. Distinct
official / canvasser identities exist because separation-of-duties compares the
acting X-User-ID against the recorded prior actor, so tests must control who acts.

Voter is ENTITY-BACKED by a VoterRegistration: its X-User-ID must equal a
VoterRegistration.id the voter owns, so a voter header MUST be built per-instance
via make_voter_headers(registration_id) whenever a call is ownership-gated.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles and for tests that do not exercise
# Voter ownership (e.g. 401/403/404 paths).
TEST_USERS = {
    "election_admin_headers": build_user_headers("admin", "ElectionAdmin"),
    # Default ElectionOfficial (reviewer / submitter identity in most fixtures).
    "election_official_headers": build_user_headers("off-1", "ElectionOfficial"),
    # A second, distinct ElectionOfficial (the cure adjudicator under segregation).
    "election_official2_headers": build_user_headers("off-2", "ElectionOfficial"),
    "poll_worker_headers": build_user_headers("pw-1", "PollWorker"),
    # The Canvasser who records precinct tallies.
    "canvasser_tally_headers": build_user_headers("canvasser-tally-1", "Canvasser"),
    # A distinct Canvasser who runs recount passes (segregation from the tally recorder).
    "canvasser_recount_headers": build_user_headers("canvasser-recount-2", "Canvasser"),
    # Opaque Voter fallback — used ONLY for non-ownership tests (e.g. 403/404).
    "voter_headers": build_user_headers("voter-unbound", "Voter"),
}


def make_election_admin_headers(user_id: str = "admin") -> dict:
    """ElectionAdmin (opaque). user_id is recorded but never identity-checked."""
    return build_user_headers(user_id, "ElectionAdmin")


def make_election_official_headers(user_id: str = "off-1") -> dict:
    """ElectionOfficial (opaque). Pass a distinct user_id to drive segregation of duties."""
    return build_user_headers(user_id, "ElectionOfficial")


def make_poll_worker_headers(user_id: str = "pw-1") -> dict:
    """PollWorker (opaque)."""
    return build_user_headers(user_id, "PollWorker")


def make_canvasser_headers(user_id: str) -> dict:
    """Canvasser (opaque). Pass a distinct user_id to drive recount segregation."""
    return build_user_headers(user_id, "Canvasser")


def make_voter_headers(registration_id: str) -> dict:
    """Voter (entity_backed:VoterRegistration). Pass the actual VoterRegistration.id
    as user_id whenever the call is ownership-gated (own ballot / own cure case)."""
    return build_user_headers(registration_id, "Voter")


# Canonical opaque-identity header dicts reused by tests and fixtures. Distinct
# official / canvasser identities exist so separation-of-duties tests can choose
# who acts (reviewer vs adjudicator; tally recorder vs recount canvasser).
ADMIN = TEST_USERS["election_admin_headers"]
OFF1 = TEST_USERS["election_official_headers"]
OFF2 = TEST_USERS["election_official2_headers"]
PW1 = TEST_USERS["poll_worker_headers"]
CANV_TALLY = TEST_USERS["canvasser_tally_headers"]
CANV_RECOUNT = TEST_USERS["canvasser_recount_headers"]
