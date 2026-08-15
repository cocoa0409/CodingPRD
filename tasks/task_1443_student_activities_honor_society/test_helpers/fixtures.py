"""Composite setup helpers.

Every helper builds preconditions from scratch using only PRD-declared
endpoints (each test runs against a freshly restarted server with an empty
database). Setup calls use get_success_data so failures surface as clear
"Setup failed" errors. Identity threading: entity-backed roles (Officer,
Member) always build headers from the acting member's id via
make_officer_headers / make_member_headers.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    CLOCK_DEFAULT_ISO,
    CYCLE_AFTER_CLOSE_ISO,
    CYCLE_AFTER_INDUCTION_ISO,
)
from .factories import (
    create_athletics_block_payload,
    create_chapter_payload,
    create_cycle_payload,
    create_election_payload,
    create_fundraiser_payload,
    create_member_payload,
    create_minutes_payload,
    create_probation_case_payload,
    create_service_entry_payload,
    create_vote_payload,
)
from .test_users import (
    TEST_USERS,
    make_member_headers,
    make_officer_headers,
)

ADVISOR = TEST_USERS["advisor_headers"]
DIRECTOR = TEST_USERS["director_headers"]


def _fail(step, resp):
    raise AssertionError(
        f"Setup failed at {step}: HTTP {resp.status_code} {resp.text}"
    )


def _ok(step, resp, expected_status=None):
    data = get_success_data(resp)
    if expected_status is not None and isinstance(data, dict):
        status = data.get("status")
        assert status == expected_status, (
            f"Setup failed at {step}: expected status {expected_status}, "
            f"got {status}"
        )
    return data


# ---------------------------------------------------------------------------
# Tier 0 — clock and chapter stand-up
# ---------------------------------------------------------------------------

def set_clock(iso=CLOCK_DEFAULT_ISO):
    resp = api_client.set_clock({"to_iso8601": iso}, DIRECTOR)
    return _ok("set_clock", resp)


def create_chapter(**overrides):
    resp = api_client.create_chapter(create_chapter_payload(**overrides),
                                     DIRECTOR)
    return _ok("create_chapter", resp, expected_status="DRAFT")


def create_active_chapter(**overrides):
    """Create a chapter (DRAFT) and activate it. Returns the ACTIVE chapter."""
    chapter = create_chapter(**overrides)
    resp = api_client.activate_chapter(chapter["id"], DIRECTOR)
    return _ok("activate_chapter", resp, expected_status="ACTIVE")


def add_member(chapter_id, **overrides):
    resp = api_client.create_member(chapter_id, create_member_payload(**overrides),
                                    ADVISOR)
    return _ok("create_member", resp, expected_status="PROSPECTIVE")


def suspend_chapter(chapter_id):
    resp = api_client.suspend_chapter(chapter_id, DIRECTOR)
    return _ok("suspend_chapter", resp, expected_status="SUSPENDED")


# ---------------------------------------------------------------------------
# Tier 1 — membership cycle progression
# ---------------------------------------------------------------------------

def create_cycle(chapter_id, **overrides):
    resp = api_client.create_cycle(chapter_id, create_cycle_payload(**overrides),
                                   ADVISOR)
    return _ok("create_cycle", resp, expected_status="PLANNED")


def open_cycle_nominations(chapter_id, cycle_id):
    """Move a cycle PLANNED -> NOMINATION (clock already at the open date)."""
    resp = api_client.open_nominations(chapter_id, cycle_id, ADVISOR)
    return _ok("open_nominations", resp, expected_status="NOMINATION")


def nominate(chapter_id, member_id):
    resp = api_client.nominate_member(chapter_id, member_id, ADVISOR)
    return _ok("nominate", resp, expected_status="CANDIDATE")


def close_cycle_nominations(chapter_id, cycle_id):
    """Advance the clock past the close date and move NOMINATION -> REVIEW."""
    set_clock(CYCLE_AFTER_CLOSE_ISO)
    resp = api_client.close_nominations(chapter_id, cycle_id, ADVISOR)
    return _ok("close_nominations", resp, expected_status="REVIEW")


def list_applications(chapter_id, cycle_id, params=None):
    resp = api_client.list_applications(chapter_id, cycle_id, ADVISOR,
                                        params=params)
    return _ok("list_applications", resp)


def induct_cycle(chapter_id, cycle_id):
    """Induct a REVIEW cycle (OCC-guarded): reads the fresh cycle version."""
    set_clock(CYCLE_AFTER_INDUCTION_ISO)
    cycle = _ok("get_cycle", api_client.get_cycle(chapter_id, cycle_id, ADVISOR))
    resp = api_client.induct_cycle(
        chapter_id, cycle_id,
        {"expected_cycle_version": cycle["version"]}, ADVISOR)
    return _ok("induct_cycle", resp, expected_status="INDUCTED")


def setup_cycle_in_review(member_overrides=None, chapter_overrides=None):
    """Active chapter + N members nominated + cycle in REVIEW.

    Returns dict(chapter, cycle, members, applications) where applications
    are the CycleApplication rows swept to UNDER_REVIEW by the close.
    """
    set_clock()
    chapter = create_active_chapter(**(chapter_overrides or {}))
    overrides = member_overrides or [{}]
    members = [add_member(chapter["id"], **ov) for ov in overrides]
    cycle = create_cycle(chapter["id"])
    open_cycle_nominations(chapter["id"], cycle["id"])
    for m in members:
        nominate(chapter["id"], m["id"])
    cycle = close_cycle_nominations(chapter["id"], cycle["id"])
    applications = list_applications(chapter["id"], cycle["id"])
    return {"chapter": chapter, "cycle": cycle, "members": members,
            "applications": applications}


def setup_cycle_inducted_all_rejected():
    """Cycle driven to INDUCTED with every application REJECTED.

    Returns dict(chapter, cycle, members, applications).
    """
    env = setup_cycle_in_review()
    chapter, cycle = env["chapter"], env["cycle"]
    for app in env["applications"]:
        resp = api_client.reject_application(
            chapter["id"], cycle["id"], app["id"],
            {"rejection_reason": "Not selected this cycle"}, ADVISOR)
        _ok("reject_application", resp, expected_status="REJECTED")
    cycle = induct_cycle(chapter["id"], cycle["id"])
    env["cycle"] = cycle
    return env


# ---------------------------------------------------------------------------
# Tier 2 — elections and officer roles
# ---------------------------------------------------------------------------

def cast_vote(chapter_id, election_id, voter_member_id, candidate_member_id):
    resp = api_client.cast_vote(
        chapter_id, election_id,
        create_vote_payload(voter_member_id, candidate_member_id),
        make_member_headers(voter_member_id))
    return _ok("cast_vote", resp, expected_status="CAST")


def elect_officer(chapter_id, cycle_id, office, winner_member_id,
                  voter_member_ids=None):
    """Run an election DRAFT -> OPEN -> TALLIED -> CERTIFIED and return
    (election, officer_role). The winner receives every vote cast."""
    resp = api_client.create_election(
        chapter_id, create_election_payload(cycle_id, office), ADVISOR)
    election = _ok("create_election", resp, expected_status="DRAFT")
    election = _ok("open_election",
                   api_client.open_election(chapter_id, election["id"], ADVISOR),
                   expected_status="OPEN")
    for voter_id in (voter_member_ids or [winner_member_id]):
        cast_vote(chapter_id, election["id"], voter_id, winner_member_id)
    election = _ok("tally_election",
                   api_client.tally_election(chapter_id, election["id"], ADVISOR),
                   expected_status="TALLIED")
    election = _ok(
        "certify_election",
        api_client.certify_election(chapter_id, election["id"], ADVISOR),
        expected_status="CERTIFIED")
    roles = _ok("list_officer_roles",
                api_client.list_officer_roles(chapter_id, ADVISOR))
    role = next(r for r in roles
                if r["member_id"] == winner_member_id and r["office"] == office
                and r["status"] == "ACTIVE")
    return election, role


def setup_chapter_with_officer(office="PRESIDENT", num_members=1):
    """Active chapter + REVIEW cycle + one certified officer.

    Returns dict(chapter, cycle, members, officer_member, election, role).
    """
    env = setup_cycle_in_review(member_overrides=[{} for _ in range(num_members)])
    officer_member = env["members"][0]
    election, role = elect_officer(
        env["chapter"]["id"], env["cycle"]["id"], office, officer_member["id"],
        [m["id"] for m in env["members"]])
    env.update({"officer_member": officer_member, "election": election,
                "role": role})
    return env


# ---------------------------------------------------------------------------
# Tier 3 — fundraiser / ledger pipeline
# ---------------------------------------------------------------------------

def create_fundraiser(chapter_id, role, officer_member, **overrides):
    resp = api_client.create_fundraiser(
        chapter_id,
        create_fundraiser_payload(role["id"], **overrides),
        make_officer_headers(officer_member["id"]))
    return _ok("create_fundraiser", resp, expected_status="DRAFT")


def submit_fundraiser(chapter_id, fundraiser_id, officer_member):
    resp = api_client.submit_fundraiser(
        chapter_id, fundraiser_id, make_officer_headers(officer_member["id"]))
    return _ok("submit_fundraiser", resp, expected_status="SUBMITTED")


def advisor_approve_fundraiser(chapter_id, fundraiser_id,
                               advisor_headers=None):
    """Advisor approval with a freshly read chapter version (OCC)."""
    chapter = _ok("get_chapter", api_client.get_chapter(chapter_id, ADVISOR))
    resp = api_client.advisor_approve_fundraiser(
        chapter_id, fundraiser_id,
        {"expected_chapter_version": chapter["version"]},
        advisor_headers or ADVISOR)
    return _ok("advisor_approve_fundraiser", resp,
               expected_status="ADVISOR_APPROVED")


def director_approve_fundraiser(chapter_id, fundraiser_id,
                                director_headers=None):
    resp = api_client.director_approve_fundraiser(
        chapter_id, fundraiser_id, director_headers or DIRECTOR)
    return _ok("director_approve_fundraiser", resp,
               expected_status="DIRECTOR_APPROVED")


def setup_fundraiser_submitted(**fundraiser_overrides):
    """Chapter + TREASURER officer + fundraiser in SUBMITTED."""
    env = setup_chapter_with_officer(office="TREASURER")
    fundraiser = create_fundraiser(env["chapter"]["id"], env["role"],
                                   env["officer_member"],
                                   **fundraiser_overrides)
    fundraiser = submit_fundraiser(env["chapter"]["id"], fundraiser["id"],
                                   env["officer_member"])
    env["fundraiser"] = fundraiser
    return env


def setup_fundraiser_director_approved(**fundraiser_overrides):
    env = setup_fundraiser_submitted(**fundraiser_overrides)
    fundraiser = advisor_approve_fundraiser(env["chapter"]["id"],
                                            env["fundraiser"]["id"])
    fundraiser = director_approve_fundraiser(env["chapter"]["id"],
                                             fundraiser["id"])
    env["fundraiser"] = fundraiser
    return env


def execute_fundraiser(env, actual_gross_cents, execute_at="2026-09-20T18:00:00Z"):
    """Advance the clock to the scheduled date and record actuals."""
    set_clock(execute_at)
    resp = api_client.execute_fundraiser(
        env["chapter"]["id"], env["fundraiser"]["id"],
        {"actual_gross_cents": actual_gross_cents},
        make_officer_headers(env["officer_member"]["id"]))
    return _ok("execute_fundraiser", resp, expected_status="EXECUTED")


def list_ledger_entries(chapter_id, params=None):
    resp = api_client.list_ledger_entries(chapter_id, ADVISOR, params=params)
    return _ok("list_ledger_entries", resp)


def find_ledger_entry(chapter_id, entry_type, fundraiser_id=None):
    entries = list_ledger_entries(chapter_id)
    for e in entries:
        if e["entry_type"] != entry_type:
            continue
        if fundraiser_id is not None and e.get("fundraiser_id") != fundraiser_id:
            continue
        return e
    raise AssertionError(
        f"Setup failed: no ledger entry of type {entry_type} found")


def clear_ledger_entry(chapter_id, entry_id):
    resp = api_client.clear_ledger_entry(chapter_id, entry_id, ADVISOR)
    return _ok("clear_ledger_entry", resp, expected_status="CLEARED")


def setup_funded_chapter(amount_cents):
    """Chapter whose fund balance is exactly amount_cents (CLEARED deposit)."""
    env = setup_fundraiser_director_approved(upfront_cost_cents=0)
    env["fundraiser"] = execute_fundraiser(env, amount_cents)
    deposit = find_ledger_entry(env["chapter"]["id"], "FUNDRAISER_DEPOSIT",
                                env["fundraiser"]["id"])
    clear_ledger_entry(env["chapter"]["id"], deposit["id"])
    env["deposit"] = deposit
    return env


def get_chapter(chapter_id):
    return _ok("get_chapter", api_client.get_chapter(chapter_id, ADVISOR))


# ---------------------------------------------------------------------------
# Tier 4 — probation cases and athletics blocks
# ---------------------------------------------------------------------------

def open_probation_case(chapter_id, member_id, **overrides):
    resp = api_client.create_probation_case(
        chapter_id, member_id,
        create_probation_case_payload("adv-1", **overrides), ADVISOR)
    return _ok("create_probation_case", resp, expected_status="OPEN")


def resolve_probation_case(chapter_id, member_id, case_id,
                           outcome="STANDARDS_VIOLATION_CONFIRMED",
                           probation_end_date="2026-12-01T00:00:00Z"):
    payload = {"outcome": outcome}
    if probation_end_date is not None:
        payload["probation_end_date"] = probation_end_date
    resp = api_client.resolve_probation_case(chapter_id, member_id, case_id,
                                             payload, ADVISOR)
    return _ok("resolve_probation_case", resp, expected_status="RESOLVED")


def add_athletics_block(chapter_id, member_id, **overrides):
    resp = api_client.create_athletics_block(
        chapter_id, create_athletics_block_payload(member_id, **overrides),
        ADVISOR)
    return _ok("create_athletics_block", resp, expected_status="ACTIVE")


# ---------------------------------------------------------------------------
# Tier 5 — meeting minutes
# ---------------------------------------------------------------------------

def draft_minutes(chapter_id, role, officer_member, **overrides):
    resp = api_client.create_minutes(
        chapter_id,
        create_minutes_payload(role["id"], [officer_member["id"]], **overrides),
        make_officer_headers(officer_member["id"]))
    return _ok("create_minutes", resp, expected_status="DRAFT")


def setup_secretary_with_minutes():
    """Chapter + certified SECRETARY + minutes drafted by that secretary."""
    env = setup_chapter_with_officer(office="SECRETARY")
    minutes = draft_minutes(env["chapter"]["id"], env["role"],
                            env["officer_member"])
    env["minutes"] = minutes
    return env
