"""Role headers for the seven roles of PRD §2.1.

`AirlineRep` is the one entity-backed identity: "When `X-User-Role` is
`AirlineRep`, `X-User-ID` is the `id` of the acting `Airline`". Every ownership-
gated call must therefore build its headers with `make_airline_rep_headers()` and
a real airline id; the module-level `airline_rep_headers` names no airline at all
and is only for probes that never reach the ownership band.

The other six roles carry "an opaque operator identifier not tied to any
persisted entity". Several of them need more than one identifier because the
service compares one recorded operator id against another: the `LoadMaster` who
sealed a cart may not issue the manifest that pins it, so `lm_alice` seals,
`lm_bob` issues and `lm_carol` reseals.
"""

from typing import Dict, List

from prd_bench_local_runner.testing import build_user_headers

# Opaque operator identifiers (PRD §2.1).
PLATFORM_ADMIN_USER_ID = "pa_admin"
SCHEDULE_FEED_OPERATOR_USER_ID = "sf_ingest"
PRODUCTION_SUPERVISOR_USER_ID = "ps_alice"
SECOND_PRODUCTION_SUPERVISOR_USER_ID = "ps_carol"
QA_OFFICER_USER_ID = "qa_dana"
LOAD_MASTER_ALICE_USER_ID = "lm_alice"
LOAD_MASTER_BOB_USER_ID = "lm_bob"
LOAD_MASTER_CAROL_USER_ID = "lm_carol"
COMPLIANCE_OFFICER_USER_ID = "co_erin"

ROLE_PLATFORM_ADMIN = "PlatformAdmin"
ROLE_SCHEDULE_FEED_OPERATOR = "ScheduleFeedOperator"
ROLE_AIRLINE_REP = "AirlineRep"
ROLE_PRODUCTION_SUPERVISOR = "ProductionSupervisor"
ROLE_QA_OFFICER = "QaOfficer"
ROLE_LOAD_MASTER = "LoadMaster"
ROLE_COMPLIANCE_OFFICER = "ComplianceOfficer"

ALL_ROLE_NAMES: List[str] = [
    ROLE_PLATFORM_ADMIN,
    ROLE_SCHEDULE_FEED_OPERATOR,
    ROLE_AIRLINE_REP,
    ROLE_PRODUCTION_SUPERVISOR,
    ROLE_QA_OFFICER,
    ROLE_LOAD_MASTER,
    ROLE_COMPLIANCE_OFFICER,
]


TEST_USERS: Dict[str, Dict[str, str]] = {
    "platform_admin_headers": build_user_headers(
        PLATFORM_ADMIN_USER_ID, ROLE_PLATFORM_ADMIN
    ),
    "schedule_feed_operator_headers": build_user_headers(
        SCHEDULE_FEED_OPERATOR_USER_ID, ROLE_SCHEDULE_FEED_OPERATOR
    ),
    "production_supervisor_headers": build_user_headers(
        PRODUCTION_SUPERVISOR_USER_ID, ROLE_PRODUCTION_SUPERVISOR
    ),
    "second_production_supervisor_headers": build_user_headers(
        SECOND_PRODUCTION_SUPERVISOR_USER_ID, ROLE_PRODUCTION_SUPERVISOR
    ),
    "qa_officer_headers": build_user_headers(QA_OFFICER_USER_ID, ROLE_QA_OFFICER),
    "load_master_alice_headers": build_user_headers(
        LOAD_MASTER_ALICE_USER_ID, ROLE_LOAD_MASTER
    ),
    "load_master_bob_headers": build_user_headers(
        LOAD_MASTER_BOB_USER_ID, ROLE_LOAD_MASTER
    ),
    "load_master_carol_headers": build_user_headers(
        LOAD_MASTER_CAROL_USER_ID, ROLE_LOAD_MASTER
    ),
    "compliance_officer_headers": build_user_headers(
        COMPLIANCE_OFFICER_USER_ID, ROLE_COMPLIANCE_OFFICER
    ),
    # Entity-backed role. This identifier names no real airline, so it is only
    # usable where the ownership band is never reached.
    "airline_rep_headers": build_user_headers("unowned-airline-rep", ROLE_AIRLINE_REP),
}


def make_airline_rep_headers(airline_id: str) -> Dict[str, str]:
    """Headers for the `AirlineRep` of one specific airline.

    "`X-User-ID` is the `id` of the acting `Airline`", which is exactly what
    every ownership check compares against (PRD §2.1).
    """
    return build_user_headers(airline_id, ROLE_AIRLINE_REP)


def make_load_master_headers(user_id: str) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_LOAD_MASTER)


def make_production_supervisor_headers(user_id: str) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_PRODUCTION_SUPERVISOR)


def make_qa_officer_headers(user_id: str) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_QA_OFFICER)


def make_compliance_officer_headers(user_id: str) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_COMPLIANCE_OFFICER)


def make_headers(role: str, user_id: str) -> Dict[str, str]:
    return build_user_headers(user_id, role)


# "Every role may read every list and detail endpoint" — these are the six
# opaque roles, usable on any read without an airline id.
OPERATOR_READ_HEADERS: List[Dict[str, str]] = [
    TEST_USERS["platform_admin_headers"],
    TEST_USERS["schedule_feed_operator_headers"],
    TEST_USERS["production_supervisor_headers"],
    TEST_USERS["qa_officer_headers"],
    TEST_USERS["load_master_alice_headers"],
    TEST_USERS["compliance_officer_headers"],
]
