"""Pre-built role headers for every role in the PRD.

All five roles carry an opaque X-User-ID that the server never compares to any
entity id (PRD §2.1). The server does, however, freeze the caller's X-User-ID
into an inspection's inspector_id / decided_by and compare those two to each
other for the segregation-of-duties rule (§3.3). Tests that exercise that rule
therefore need to control the acting X-User-ID, which the builder functions
below provide.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — distinct default X-User-IDs per role. The Inspector and
# Supervisor defaults differ so ordinary inspection acceptance passes the
# segregation-of-duties check without extra wiring.
TEST_USERS = {
    "supervisor_headers": build_user_headers("sup-default", "Supervisor"),
    "inspector_headers": build_user_headers("insp-default", "Inspector"),
    "dispatcher_headers": build_user_headers("disp-default", "Dispatcher"),
    "crewlead_headers": build_user_headers("crew-default", "CrewLead"),
    "coordinator_headers": build_user_headers("coord-default", "Coordinator"),
}

# Request with no auth headers — for the ERR_UNAUTHENTICATED path (PRD §2.1).
ANON_HEADERS = {"Content-Type": "application/json"}


def supervisor_headers(user_id: str = "sup-default") -> dict:
    return build_user_headers(user_id, "Supervisor")


def inspector_headers(user_id: str = "insp-default") -> dict:
    return build_user_headers(user_id, "Inspector")


def dispatcher_headers(user_id: str = "disp-default") -> dict:
    return build_user_headers(user_id, "Dispatcher")


def crewlead_headers(user_id: str = "crew-default") -> dict:
    return build_user_headers(user_id, "CrewLead")


def coordinator_headers(user_id: str = "coord-default") -> dict:
    return build_user_headers(user_id, "Coordinator")
