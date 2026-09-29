"""Pre-built role headers for every role in the PRD (§2.1).

Four roles carry an opaque identity, so a shared constant operator id is the
canonical form for them. `RightsHolderRep` is entity-backed: its `X-User-ID` is
the `id` of the acting `Archive`, so ownership-gated calls MUST use
`make_rights_holder_rep_headers(archive_id)` with a real archive id.
"""
from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

# Stable operator identifiers. The two counsel ids and the supervisor id are kept
# distinct because the segregation-of-duties rule of PRD §3.7 compares them.
PRODUCTION_ADMIN_USER_ID = "admin-one"
ARCHIVE_RESEARCHER_USER_ID = "researcher-one"
CLEARANCE_SUPERVISOR_USER_ID = "supervisor-one"
LEGAL_COUNSEL_USER_ID = "counsel-alpha"
REVIEWING_COUNSEL_USER_ID = "counsel-beta"
SECOND_SUPERVISOR_USER_ID = "supervisor-two"

TEST_USERS: Dict[str, Dict[str, str]] = {
    # Opaque roles — the shared constant is the canonical form.
    "production_admin_headers": build_user_headers(
        PRODUCTION_ADMIN_USER_ID, "ProductionAdmin"),
    "archive_researcher_headers": build_user_headers(
        ARCHIVE_RESEARCHER_USER_ID, "ArchiveResearcher"),
    "clearance_supervisor_headers": build_user_headers(
        CLEARANCE_SUPERVISOR_USER_ID, "ClearanceSupervisor"),
    "legal_counsel_headers": build_user_headers(
        LEGAL_COUNSEL_USER_ID, "LegalCounsel"),
    # A second counsel operator, used where the reviewer must differ from the
    # lawyer who issued the opinion letter being relied upon.
    "reviewing_counsel_headers": build_user_headers(
        REVIEWING_COUNSEL_USER_ID, "LegalCounsel"),
    "second_supervisor_headers": build_user_headers(
        SECOND_SUPERVISOR_USER_ID, "ClearanceSupervisor"),
    # entity_backed role: this shared constant never equals a real Archive id, so
    # it is a fallback for non-ownership tests only (401/403/404 probes).
    "rights_holder_rep_headers": build_user_headers(
        "rep-unowned", "RightsHolderRep"),
}


def make_rights_holder_rep_headers(archive_id: str) -> Dict[str, str]:
    """Headers for a `RightsHolderRep` acting as the archive at `archive_id`.

    PRD §2.1: when `X-User-Role` is `RightsHolderRep`, `X-User-ID` is the `id` of
    the acting `Archive`. Pass the real archive id whenever the call is
    ownership-gated (appending a negotiation round, driving a licence's status,
    reading a single licence, listing an archive's rate cards).
    """
    return build_user_headers(archive_id, "RightsHolderRep")


def make_production_admin_headers(user_id: str) -> Dict[str, str]:
    return build_user_headers(user_id, "ProductionAdmin")


def make_archive_researcher_headers(user_id: str) -> Dict[str, str]:
    return build_user_headers(user_id, "ArchiveResearcher")


def make_clearance_supervisor_headers(user_id: str) -> Dict[str, str]:
    return build_user_headers(user_id, "ClearanceSupervisor")


def make_legal_counsel_headers(user_id: str) -> Dict[str, str]:
    return build_user_headers(user_id, "LegalCounsel")


# Convenience aliases used throughout the fixtures.
PRODUCTION_ADMIN = TEST_USERS["production_admin_headers"]
ARCHIVE_RESEARCHER = TEST_USERS["archive_researcher_headers"]
CLEARANCE_SUPERVISOR = TEST_USERS["clearance_supervisor_headers"]
LEGAL_COUNSEL = TEST_USERS["legal_counsel_headers"]
REVIEWING_COUNSEL = TEST_USERS["reviewing_counsel_headers"]
SECOND_SUPERVISOR = TEST_USERS["second_supervisor_headers"]
