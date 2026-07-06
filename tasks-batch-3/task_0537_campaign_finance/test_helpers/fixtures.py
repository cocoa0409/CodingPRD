"""Composite setup helpers.

Every helper builds its preconditions from scratch using only PRD-declared endpoints,
because the server database is empty at the start of every test. Setup calls use the
lenient get_success_data() validator so a broken precondition surfaces as "Setup failed"
rather than an obscure assertion error.

Identity threading: after creating an entity_backed entity (Committee / LobbyingRegistrant),
ownership-gated calls use make_treasurer_headers(committee_id) / make_registrant_headers(
registrant_id) with the real entity id — never the shared TEST_USERS fallback.
"""
from prd_bench_local_runner.testing import get_success_data
from .test_users import (
    TEST_USERS, make_treasurer_headers, make_registrant_headers,
)
from .factories import (
    create_committee_payload, create_contribution_payload, create_expenditure_payload,
    create_reporting_period_payload, create_registrant_payload, create_client_payload,
    create_lobbying_period_payload, create_activity_payload,
)

REGULATOR = TEST_USERS["regulator_headers"]


# --------------------------------------------------------------------------- #
# Logical clock
# --------------------------------------------------------------------------- #
def set_clock(api, to_iso8601: str):
    """Pin the server's logical UTC clock (RegulatorAuditor-only)."""
    return get_success_data(api.set_clock(to_iso8601, REGULATOR))


# --------------------------------------------------------------------------- #
# Committee helpers
# --------------------------------------------------------------------------- #
def register_committee(api, **overrides) -> dict:
    """Register a committee; returns the PENDING committee."""
    return get_success_data(
        api.create_committee(create_committee_payload(**overrides), TEST_USERS["treasurer_headers"])
    )


def create_active_committee(api, **overrides) -> dict:
    """Register + approve a committee. Returns the ACTIVE committee (freshly re-fetched)."""
    committee = register_committee(api, **overrides)
    cid = committee["id"]
    get_success_data(api.approve_committee(cid, REGULATOR))
    return get_success_data(api.get_committee(cid, make_treasurer_headers(cid)))


def get_committee(api, cid: str) -> dict:
    return get_success_data(api.get_committee(cid, make_treasurer_headers(cid)))


def committee_version(api, cid: str) -> int:
    return get_committee(api, cid)["version"]


def add_contribution(api, cid: str, **overrides) -> dict:
    """Record a contribution against a committee (owner Treasurer)."""
    return get_success_data(
        api.create_contribution(cid, create_contribution_payload(**overrides), make_treasurer_headers(cid))
    )


def add_deposited_contribution(api, cid: str, **overrides) -> dict:
    """Record then deposit a contribution. Returns the DEPOSITED contribution."""
    con = add_contribution(api, cid, **overrides)
    return get_success_data(api.deposit_contribution(con["id"], make_treasurer_headers(cid)))


def add_expenditure(api, cid: str, **overrides) -> dict:
    return get_success_data(
        api.create_expenditure(cid, create_expenditure_payload(**overrides), make_treasurer_headers(cid))
    )


# --------------------------------------------------------------------------- #
# Reporting period helpers
# --------------------------------------------------------------------------- #
def create_reporting_period(api, **overrides) -> dict:
    """Create a campaign-finance reporting period (OPEN)."""
    return get_success_data(
        api.create_reporting_period(create_reporting_period_payload(**overrides), REGULATOR)
    )


def create_closed_reporting_period(api, **overrides) -> dict:
    """Create + close a campaign-finance reporting period. Returns the CLOSED period."""
    period = create_reporting_period(api, **overrides)
    return get_success_data(api.close_reporting_period(period["id"], REGULATOR))


# --------------------------------------------------------------------------- #
# Report helpers
# --------------------------------------------------------------------------- #
def create_draft_report(api, cid: str, period_id: str, expected_version: int = None) -> dict:
    """Create a DRAFT report (OCC-guarded). Reads the committee's current version if not given."""
    if expected_version is None:
        expected_version = committee_version(api, cid)
    payload = {"period_id": period_id, "expected_committee_version": expected_version}
    return get_success_data(api.create_report(cid, payload, make_treasurer_headers(cid)))


def create_filed_report(api, cid: str, period_id: str) -> dict:
    """Create a DRAFT report then file it. Returns the FILED report."""
    report = create_draft_report(api, cid, period_id)
    return get_success_data(api.file_report(report["id"], make_treasurer_headers(cid)))


def setup_committee_with_closed_period(api, committee_overrides=None, period_overrides=None):
    """ACTIVE committee + CLOSED campaign-finance period. Returns (committee, period)."""
    committee = create_active_committee(api, **(committee_overrides or {}))
    period = create_closed_reporting_period(api, **(period_overrides or {}))
    return committee, period


# --------------------------------------------------------------------------- #
# Lobbying helpers
# --------------------------------------------------------------------------- #
def create_registrant(api, **overrides) -> dict:
    """Register a lobbying registrant; returns the ACTIVE registrant."""
    return get_success_data(
        api.create_registrant(create_registrant_payload(**overrides), TEST_USERS["registrant_headers"])
    )


def get_registrant(api, rgid: str) -> dict:
    return get_success_data(api.get_registrant(rgid, make_registrant_headers(rgid)))


def add_client(api, rgid: str, **overrides) -> dict:
    return get_success_data(
        api.create_client(rgid, create_client_payload(**overrides), make_registrant_headers(rgid))
    )


def create_lobbying_period(api, **overrides) -> dict:
    """Create a lobbying reporting period (OPEN)."""
    return get_success_data(
        api.create_lobbying_period(create_lobbying_period_payload(**overrides), REGULATOR)
    )


def create_closed_lobbying_period(api, **overrides) -> dict:
    period = create_lobbying_period(api, **overrides)
    return get_success_data(api.close_lobbying_period(period["id"], REGULATOR))


def add_activity(api, rgid: str, client_id: str, period_id: str, **overrides) -> dict:
    return get_success_data(
        api.create_activity(
            rgid, create_activity_payload(client_id, period_id, **overrides), make_registrant_headers(rgid)
        )
    )


def setup_registrant_with_client_and_period(api, registrant_overrides=None,
                                            client_overrides=None, period_overrides=None):
    """ACTIVE registrant + one ACTIVE client + one OPEN lobbying period.
    Returns (registrant, client, period)."""
    registrant = create_registrant(api, **(registrant_overrides or {}))
    client = add_client(api, registrant["id"], **(client_overrides or {}))
    period = create_lobbying_period(api, **(period_overrides or {}))
    return registrant, client, period
