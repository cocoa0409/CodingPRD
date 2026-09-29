"""Pre-built role headers for the six roles the API recognises (PRD §2.1).

`ZoneAdmin`, `Dispatcher`, `FinanceAnalyst` and `FundingAgencyAuditor` present an
opaque operator identifier, so a shared constant is the canonical form for them.
`Rider` and `DriverUser` present the `id` of a persisted row, so the per-instance
builders below must be used with the real rider or driver `id` whenever the call
is ownership-gated.
"""

from prd_bench_local_runner.testing import build_user_headers

# Opaque operator identifiers used by the report workflow. Two analysts and two
# auditors exist so segregation of duties can be exercised in both directions.
FINANCE_ANALYST_ID = "fa-1"
FINANCE_ANALYST_2_ID = "fa-2"
AUDITOR_ID = "aud-1"
AUDITOR_2_ID = "aud-2"

TEST_USERS = {
    "zone_admin_headers": build_user_headers("za-1", "ZoneAdmin"),
    "dispatcher_headers": build_user_headers("disp-1", "Dispatcher"),
    "finance_analyst_headers": build_user_headers(FINANCE_ANALYST_ID, "FinanceAnalyst"),
    "finance_analyst_2_headers": build_user_headers(
        FINANCE_ANALYST_2_ID, "FinanceAnalyst"
    ),
    "auditor_headers": build_user_headers(AUDITOR_ID, "FundingAgencyAuditor"),
    "auditor_2_headers": build_user_headers(AUDITOR_2_ID, "FundingAgencyAuditor"),
    # Shared fallbacks for the two entity-backed roles. Safe only for tests that
    # deliberately present an identifier which resolves to no row.
    "rider_headers": build_user_headers("no-such-rider", "Rider"),
    "driver_headers": build_user_headers("no-such-driver", "DriverUser"),
}

ZONE_ADMIN_HEADERS = TEST_USERS["zone_admin_headers"]
DISPATCHER_HEADERS = TEST_USERS["dispatcher_headers"]
FINANCE_ANALYST_HEADERS = TEST_USERS["finance_analyst_headers"]
FINANCE_ANALYST_2_HEADERS = TEST_USERS["finance_analyst_2_headers"]
AUDITOR_HEADERS = TEST_USERS["auditor_headers"]
AUDITOR_2_HEADERS = TEST_USERS["auditor_2_headers"]


def make_rider_headers(rider_id: str) -> dict:
    """Headers for a `Rider` caller. `rider_id` must be the id of the acting
    rider row, because ownership checks compare it to the resource's rider
    foreign key."""
    return build_user_headers(rider_id, "Rider")


def make_driver_headers(driver_id: str) -> dict:
    """Headers for a `DriverUser` caller. `driver_id` must be the id of the
    acting driver row, because the four manifest actions require it to equal the
    block's `driver_id`."""
    return build_user_headers(driver_id, "DriverUser")


def make_zone_admin_headers(user_id: str = "za-1") -> dict:
    return build_user_headers(user_id, "ZoneAdmin")


def make_dispatcher_headers(user_id: str = "disp-1") -> dict:
    return build_user_headers(user_id, "Dispatcher")


def make_finance_analyst_headers(user_id: str = FINANCE_ANALYST_ID) -> dict:
    return build_user_headers(user_id, "FinanceAnalyst")


def make_auditor_headers(user_id: str = AUDITOR_ID) -> dict:
    return build_user_headers(user_id, "FundingAgencyAuditor")


def headers_without_identity() -> dict:
    """Headers with X-User-ID and X-User-Role omitted entirely."""
    return {"Content-Type": "application/json"}
