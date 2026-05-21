"""Composite setup helpers — multi-step preambles tests can reuse.

Most interesting test claims require the system to be in a late state
that takes 5-15 API calls to reach. Each fixture composes the lower-
level steps so the test body can focus on the rule under assertion.

IDENTITY THREADING — PRD §2.1:

    "When X-User-Role is Voter, X-User-ID is the id of the acting Voter;
    ownership checks on any resource that references a Voter compare
    that resource's voter_id foreign key to X-User-ID, and a Voter can
    only act on their own row."

After a Voter is created and activated, any voter-acting call (submit
cure, change party as VoterSelf, request own absentee ballot, PATCH
own row) MUST use make_voter_headers(voter["id"]) — never the shared
voter_headers constant.

SOD INDEPENDENCE — PRD §2.1:

    "the ReviewerClerk who acts on a CuringCase ... must present an
    X-User-ID different from the Voter.registered_by_user_id snapshot
    captured when that voter transitioned from PENDING to ACTIVE."

Fixtures use REGISTRAR_CLERK_ID when activating voters and
REVIEWER_CLERK_ID for curing-case adjudication; the two ids are
distinct so the SOD check passes by default. Tests that wish to
trigger ERR_FORBIDDEN_SOD override the reviewer id explicitly to
match the registrar id used at activation.

CLOCK ANCHORING — PRD §2.5:

    "Time in this system is not the host wall clock — it is a single
    server-controlled instant exposed through ClockState, whose now
    field can only be moved forward through an administrative
    clock-advance capability."

Setup calls use get_success_data (a lenient 2xx validator), so a
failed setup surfaces as 'Setup failed' rather than a confusing test
assertion failure downstream.
"""
from __future__ import annotations

import threading
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    add_days,
    add_millis,
    add_seconds,
    change_party_payload,
    clock_advance_payload,
    create_ballot_payload,
    create_election_payload,
    create_precinct_payload,
    create_recount_payload,
    create_voter_payload,
    create_voting_machine_payload,
    invalidate_ballot_payload,
    iso_utc,
    machine_transition_payload,
    parse_iso,
    random_serial_no,
    random_street_address,
    random_suffix,
    request_absentee_payload,
    return_absentee_payload,
    state_transition_payload,
    submit_curing_payload,
    utcnow,
    version_payload,
)
from .test_users import (
    REGISTRAR_CLERK_ID,
    REGISTRAR_CLERK_ALT_ID,
    REVIEWER_CLERK_ID,
    TEST_USERS,
    make_registrar_clerk_headers,
    make_reviewer_clerk_headers,
    make_voter_headers,
)


# ===========================================================================
# Clock helpers — PRD §2.5
# ===========================================================================
_CLOCK_LOCK = threading.Lock()
_CURRENT_CLOCK: Optional[datetime] = None


def _seed_clock() -> datetime:
    global _CURRENT_CLOCK
    with _CLOCK_LOCK:
        if _CURRENT_CLOCK is None:
            _CURRENT_CLOCK = utcnow()
        return _CURRENT_CLOCK


def current_clock() -> datetime:
    return _seed_clock()


def current_clock_iso() -> str:
    return iso_utc(current_clock())


def advance_clock_to(target_dt: datetime,
                     headers: Optional[Dict[str, str]] = None) -> str:
    """Advance the server clock to target_dt (must be >= current).

    PRD §2.5: 'whose now field can only be moved forward through an
    administrative clock-advance capability.'
    """
    global _CURRENT_CLOCK
    with _CLOCK_LOCK:
        now_dt = _CURRENT_CLOCK if _CURRENT_CLOCK is not None else utcnow()
        if target_dt < now_dt:
            target_dt = now_dt
        target_iso = iso_utc(target_dt)
        resp = api_client.advance_clock(
            clock_advance_payload(target_iso),
            headers or TEST_USERS["test_driver_headers"],
        )
        get_success_data(resp)
        _CURRENT_CLOCK = target_dt
    return target_iso


def advance_clock_by_seconds(seconds: int) -> str:
    return advance_clock_to(current_clock() + timedelta(seconds=seconds))


def advance_clock_by_days(days: int) -> str:
    return advance_clock_to(current_clock() + timedelta(days=days))


def advance_clock_iso(target_iso: str) -> str:
    return advance_clock_to(parse_iso(target_iso))


def reset_clock_tracker_to(dt: datetime) -> None:
    """Force the test-process's clock tracker to a specific value.
    Used by conftest after the server is reset between tests.
    """
    global _CURRENT_CLOCK
    with _CLOCK_LOCK:
        _CURRENT_CLOCK = dt


# ===========================================================================
# Date helpers — derive deadline dates around a chosen election_date
# ===========================================================================
def _default_election_dates(
    election_date: Optional[str] = None,
    recount_threshold_pct: Optional[float] = None,
) -> Dict[str, Any]:
    """Produce a coherent set of deadline timestamps, all derived from
    election_date (or a sensible far-future default)."""
    if election_date is None:
        # Anchor election_date one year ahead of the current clock so
        # all deadlines stay in the future even if the suite has been
        # running for a while.
        ed_dt = add_days(current_clock(), 365)
    else:
        ed_dt = parse_iso(election_date)

    reg_deadline = add_days(ed_dt, -30)
    abs_req = add_days(ed_dt, -7)
    early_starts = add_days(ed_dt, -14)
    early_ends = add_days(ed_dt, -1)
    ballot_return = add_seconds(ed_dt, 20 * 3600)
    cure = add_days(ed_dt, 7)
    cert = add_days(ed_dt, 17)
    payload = {
        "election_date": iso_utc(ed_dt),
        "registration_deadline": iso_utc(reg_deadline),
        "absentee_request_deadline": iso_utc(abs_req),
        "early_voting_starts_at": iso_utc(early_starts),
        "early_voting_ends_at": iso_utc(early_ends),
        "ballot_return_deadline": iso_utc(ballot_return),
        "cure_deadline": iso_utc(cure),
        "certification_deadline": iso_utc(cert),
    }
    if recount_threshold_pct is not None:
        payload["recount_threshold_pct"] = recount_threshold_pct
    return payload


# ===========================================================================
# Election + precinct primitives
# ===========================================================================
def create_election(
    name: Optional[str] = None,
    election_date: Optional[str] = None,
    recount_threshold_pct: Optional[float] = None,
    **overrides,
) -> Dict[str, Any]:
    """Create a DRAFT election with coherent deadline anchors."""
    dates = _default_election_dates(
        election_date=election_date,
        recount_threshold_pct=recount_threshold_pct,
    )
    dates.update(overrides)
    payload = create_election_payload(
        name=name or f"Election {random_suffix(6)}",
        **dates,
    )
    resp = api_client.create_election(
        payload, TEST_USERS["election_board_headers"],
    )
    return get_success_data(resp)


def create_precinct(election_id: str,
                    code: Optional[str] = None,
                    street_pattern: str = ".*Main.*",
                    capacity_machines: int = 2,
                    **overrides) -> Dict[str, Any]:
    payload = create_precinct_payload(
        code=code or f"P-{random_suffix(4)}",
        street_pattern=street_pattern,
        capacity_machines=capacity_machines,
        **overrides,
    )
    resp = api_client.create_precinct(
        election_id, payload, TEST_USERS["election_board_headers"],
    )
    return get_success_data(resp)


def transition_election(election_id: str, to_state: str,
                        version: Optional[int] = None,
                        headers: Optional[Dict[str, str]] = None,
                        ) -> Dict[str, Any]:
    resp = api_client.transition_election(
        election_id,
        state_transition_payload(to_state, version=version),
        headers or TEST_USERS["election_board_headers"],
    )
    return get_success_data(resp)


def open_registration(election_id: str) -> Dict[str, Any]:
    return transition_election(election_id, "OPEN_REGISTRATION")


# ===========================================================================
# Voter primitives
# ===========================================================================
def create_voter(
    election_id: str,
    residency_address: Optional[str] = None,
    residency_since: Optional[str] = None,
    date_of_birth: str = "1990-01-01T00:00:00.000Z",
    is_citizen: bool = True,
    full_name: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
    **overrides,
) -> Dict[str, Any]:
    """Create voter in PENDING. Defaults to a residency that matches the
    .*Main.* street pattern used by create_precinct().
    """
    payload = create_voter_payload(
        election_id=election_id,
        full_name=full_name,
        date_of_birth=date_of_birth,
        residency_address=residency_address or random_street_address("Main"),
        residency_since=residency_since or "2020-01-01T00:00:00.000Z",
        is_citizen=is_citizen,
        **overrides,
    )
    resp = api_client.create_voter(
        payload, headers or TEST_USERS["registrar_clerk_headers"],
    )
    return get_success_data(resp)


def activate_voter(voter_id: str,
                   version: Optional[int] = None,
                   headers: Optional[Dict[str, str]] = None,
                   ) -> Dict[str, Any]:
    """PRD §3.3: 'A RegistrarClerk activates a voter by transitioning
    PENDING → ACTIVE.' Defaults to the stable REGISTRAR_CLERK_ID so the
    voter's registered_by_user_id snapshot is known and the SOD check
    on subsequent curing-case operations passes when the reviewer uses
    REVIEWER_CLERK_ID.
    """
    resp = api_client.transition_voter(
        voter_id,
        state_transition_payload("ACTIVE", version=version),
        headers or TEST_USERS["registrar_clerk_headers"],
    )
    return get_success_data(resp)


def suspend_voter(voter_id: str, version: Optional[int] = None,
                  headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    resp = api_client.transition_voter(
        voter_id,
        state_transition_payload("SUSPENDED", version=version),
        headers or TEST_USERS["registrar_clerk_headers"],
    )
    return get_success_data(resp)


def reactivate_voter(voter_id: str, version: Optional[int] = None,
                     headers: Optional[Dict[str, str]] = None,
                     ) -> Dict[str, Any]:
    resp = api_client.transition_voter(
        voter_id,
        state_transition_payload("ACTIVE", version=version),
        headers or TEST_USERS["registrar_clerk_headers"],
    )
    return get_success_data(resp)


def get_voter(voter_id: str, headers: Optional[Dict[str, str]] = None,
              ) -> Dict[str, Any]:
    resp = api_client.get_voter(
        voter_id, headers or TEST_USERS["registrar_clerk_headers"],
    )
    return get_success_data(resp)


def get_election(election_id: str,
                 headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    resp = api_client.get_election(
        election_id, headers or TEST_USERS["election_board_headers"],
    )
    return get_success_data(resp)


def get_absentee_ballot(ballot_id: str,
                        headers: Optional[Dict[str, str]] = None,
                        ) -> Dict[str, Any]:
    resp = api_client.get_absentee_ballot(
        ballot_id, headers or TEST_USERS["registrar_clerk_headers"],
    )
    return get_success_data(resp)


def get_curing_case(case_id: str,
                    headers: Optional[Dict[str, str]] = None,
                    ) -> Dict[str, Any]:
    resp = api_client.get_curing_case(
        case_id, headers or TEST_USERS["reviewer_clerk_headers"],
    )
    return get_success_data(resp)


def get_ballot(ballot_id: str,
               headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    resp = api_client.get_ballot(
        ballot_id, headers or TEST_USERS["election_board_headers"],
    )
    return get_success_data(resp)


def get_precinct(election_id: str, precinct_id: str,
                 headers: Optional[Dict[str, str]] = None,
                 ) -> Dict[str, Any]:
    resp = api_client.get_precinct(
        election_id, precinct_id,
        headers or TEST_USERS["election_board_headers"],
    )
    return get_success_data(resp)


def get_voting_machine(machine_id: str,
                       headers: Optional[Dict[str, str]] = None,
                       ) -> Dict[str, Any]:
    resp = api_client.get_voting_machine(
        machine_id, headers or TEST_USERS["election_board_headers"],
    )
    return get_success_data(resp)


# ===========================================================================
# Voting machines
# ===========================================================================
def provision_machine(election_id: str, precinct_id: str,
                      serial_no: Optional[str] = None,
                      ) -> Dict[str, Any]:
    resp = api_client.create_voting_machine(
        election_id, precinct_id,
        create_voting_machine_payload(serial_no=serial_no),
        TEST_USERS["election_board_headers"],
    )
    return get_success_data(resp)


def mark_machine_down(machine_id: str,
                      failure_reason: str = "POWER",
                      version: Optional[int] = None,
                      ) -> Dict[str, Any]:
    resp = api_client.transition_voting_machine(
        machine_id,
        machine_transition_payload(
            "DOWN", failure_reason=failure_reason, version=version,
        ),
        TEST_USERS["precinct_officer_headers"],
    )
    return get_success_data(resp)


# ===========================================================================
# Tier 1 — drive Election through full lifecycle
# ===========================================================================
def setup_election_with_precinct(
    election_date: Optional[str] = None,
    recount_threshold_pct: Optional[float] = None,
    street_pattern: str = ".*Main.*",
    code: str = "P1",
    capacity_machines: int = 2,
    **election_overrides,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Create election + one precinct in DRAFT. Returns (election,
    precinct). Most tests start from here and continue with
    open_registration."""
    election = create_election(
        election_date=election_date,
        recount_threshold_pct=recount_threshold_pct,
        **election_overrides,
    )
    precinct = create_precinct(
        election["id"],
        code=code,
        street_pattern=street_pattern,
        capacity_machines=capacity_machines,
    )
    return election, precinct


def setup_open_registration(
    election_date: Optional[str] = None,
    recount_threshold_pct: Optional[float] = None,
    street_pattern: str = ".*Main.*",
    code: str = "P1",
    **election_overrides,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Election in OPEN_REGISTRATION with one precinct. Returns
    (election, precinct)."""
    election, precinct = setup_election_with_precinct(
        election_date=election_date,
        recount_threshold_pct=recount_threshold_pct,
        street_pattern=street_pattern,
        code=code,
        **election_overrides,
    )
    election = open_registration(election["id"])
    return election, precinct


def setup_active_voter(
    election: Optional[Dict[str, Any]] = None,
    precinct: Optional[Dict[str, Any]] = None,
    election_date: Optional[str] = None,
    street_pattern: str = ".*Main.*",
    residency_address: Optional[str] = None,
    residency_since: Optional[str] = None,
    date_of_birth: str = "1990-01-01T00:00:00.000Z",
    registrar_headers: Optional[Dict[str, str]] = None,
    **election_overrides,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """End-to-end to an ACTIVE voter. Returns (election, precinct,
    voter). The voter's registered_by_user_id is the opaque id from
    `registrar_headers` (default REGISTRAR_CLERK_ID).
    """
    if election is None or precinct is None:
        election, precinct = setup_open_registration(
            election_date=election_date,
            street_pattern=street_pattern,
            **election_overrides,
        )
    voter = create_voter(
        election_id=election["id"],
        residency_address=residency_address,
        residency_since=residency_since,
        date_of_birth=date_of_birth,
        headers=registrar_headers,
    )
    voter = activate_voter(voter["id"], headers=registrar_headers)
    return election, precinct, voter


# ===========================================================================
# Tier 2 — Election ELECTION_DAY, TALLY, RECOUNT, CERTIFIED
# ===========================================================================
def advance_to_early_voting(election: Dict[str, Any]) -> Dict[str, Any]:
    """PRD §2.5 / §3.2: clock-advance crossing early_voting_starts_at
    triggers the system-driven OPEN_REGISTRATION → EARLY_VOTING
    rollover. Returns the refreshed election row.
    """
    advance_clock_iso(election["early_voting_starts_at"])
    return get_election(election["id"])


def advance_to_election_day(election: Dict[str, Any]) -> Dict[str, Any]:
    """Advance clock past early_voting_ends_at; the system-driven
    EARLY_VOTING → ELECTION_DAY rollover fires.
    """
    advance_clock_iso(election["early_voting_ends_at"])
    return get_election(election["id"])


def advance_past_ballot_return(election: Dict[str, Any]) -> str:
    """Advance clock 1 second past ballot_return_deadline."""
    ts = add_seconds(parse_iso(election["ballot_return_deadline"]), 1)
    return advance_clock_to(ts)


def initiate_tally(election: Dict[str, Any]) -> Dict[str, Any]:
    """ElectionBoard-driven ELECTION_DAY → TALLY (requires clock past
    ballot_return_deadline and no open curing cases — caller's
    responsibility).
    """
    return transition_election(election["id"], "TALLY")


# ===========================================================================
# Tier 3 — Absentee ballot full lifecycle helpers
# ===========================================================================
def request_absentee(voter: Dict[str, Any],
                     reason_code: Optional[str] = None,
                     headers: Optional[Dict[str, str]] = None,
                     ) -> Dict[str, Any]:
    """PRD §3.5 — a Voter or RegistrarClerk requests an absentee ballot
    by supplying the election_id and optionally a reason_code. When the
    caller is the Voter themselves, headers MUST carry the Voter's id
    (ownership check). Default uses RegistrarClerk so non-ownership
    paths pass freely.
    """
    payload = request_absentee_payload(
        election_id=voter["election_id"], reason_code=reason_code,
    )
    resp = api_client.request_absentee_ballot(
        voter["id"], payload,
        headers or TEST_USERS["registrar_clerk_headers"],
    )
    return get_success_data(resp)


def issue_absentee(ballot_id: str,
                   version: Optional[int] = None) -> Dict[str, Any]:
    resp = api_client.transition_absentee_ballot(
        ballot_id,
        state_transition_payload("ISSUED", version=version),
        TEST_USERS["registrar_clerk_headers"],
    )
    return get_success_data(resp)


def return_absentee(ballot_id: str, signature_match: str,
                    voter_choice: str,
                    version: Optional[int] = None) -> Dict[str, Any]:
    resp = api_client.return_absentee_ballot(
        ballot_id,
        return_absentee_payload(
            signature_match=signature_match,
            voter_choice=voter_choice, version=version,
        ),
        TEST_USERS["registrar_clerk_headers"],
    )
    return get_success_data(resp)


def setup_returned_absentee_with_curing_case(
    election: Optional[Dict[str, Any]] = None,
    precinct: Optional[Dict[str, Any]] = None,
    voter: Optional[Dict[str, Any]] = None,
    signature_match: str = "MISMATCH",
    voter_choice: str = "A",
    election_date: Optional[str] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any],
           Dict[str, Any], Dict[str, Any]]:
    """Drive a Voter→ACTIVE through to AbsenteeBallot RETURNED with a
    linked CuringCase in OPEN_PENDING_VOTER. Returns (election,
    precinct, voter, ballot, curing_case).

    Uses RegistrarClerk REGISTRAR_CLERK_ID for activation so the SOD
    snapshot is known; downstream reviewer operations should use
    REVIEWER_CLERK_ID (a distinct opaque id).
    """
    if voter is None:
        election, precinct, voter = setup_active_voter(
            election=election, precinct=precinct,
            election_date=election_date,
        )
    ballot = request_absentee(voter)
    ballot = issue_absentee(ballot["id"])
    ballot = return_absentee(
        ballot["id"], signature_match=signature_match,
        voter_choice=voter_choice,
    )
    assert ballot["linked_curing_case_id"], (
        "Setup failed: expected linked_curing_case_id after non-MATCH "
        "return"
    )
    case = get_curing_case(ballot["linked_curing_case_id"])
    return election, precinct, voter, ballot, case


def setup_curing_case_under_review(
    election: Optional[Dict[str, Any]] = None,
    precinct: Optional[Dict[str, Any]] = None,
    voter: Optional[Dict[str, Any]] = None,
    voter_choice: str = "A",
    submission_text: str = "Voter affirms identity",
    election_date: Optional[str] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any],
           Dict[str, Any], Dict[str, Any]]:
    """Walk through to a CuringCase in UNDER_REVIEW (voter has just
    submitted). Returns (election, precinct, voter, ballot,
    curing_case).
    """
    election, precinct, voter, ballot, case = (
        setup_returned_absentee_with_curing_case(
            election=election, precinct=precinct, voter=voter,
            voter_choice=voter_choice, election_date=election_date,
        )
    )
    resp = api_client.submit_curing_case(
        case["id"],
        submit_curing_payload(
            voter_submission_text=submission_text,
            voter_choice=voter_choice,
        ),
        make_voter_headers(voter["id"]),
    )
    case = get_success_data(resp)
    return election, precinct, voter, ballot, case


# ===========================================================================
# Tier 4 — Election in TALLY state with controlled vote distribution
# ===========================================================================
def cast_in_person(voter_id: str, precinct_id: str, method: str,
                   voter_choice: str,
                   machine_id: Optional[str] = None) -> Dict[str, Any]:
    resp = api_client.create_ballot(
        create_ballot_payload(
            voter_id=voter_id, precinct_id=precinct_id, method=method,
            voter_choice=voter_choice, machine_id=machine_id,
        ),
        TEST_USERS["precinct_officer_headers"],
    )
    return get_success_data(resp)


def _bulk_active_voters(election: Dict[str, Any],
                        precinct: Dict[str, Any],
                        count: int,
                        street_token: str = "Main",
                        ) -> List[Dict[str, Any]]:
    voters: List[Dict[str, Any]] = []
    for i in range(count):
        v = create_voter(
            election_id=election["id"],
            residency_address=f"{100 + i} {street_token} Street",
            residency_since="2020-01-01T00:00:00.000Z",
        )
        v = activate_voter(v["id"])
        voters.append(v)
    return voters


def setup_election_in_tally(
    precincts_choice_counts: List[Dict[str, Dict[str, int]]],
    recount_threshold_pct: float = 0.005,
    include_provisional: Optional[Dict[str, Dict[str, int]]] = None,
    election_date: Optional[str] = None,
) -> Dict[str, Any]:
    """Drive an election through to TALLY with a precisely controlled
    BallotCast distribution.

    precincts_choice_counts:
        list of {"code": "P1", "pattern": ".*Main.*", "choices":
                 {"A": 99, "B": 100}, "method": "EARLY_IN_PERSON"}
        — one entry per precinct, declaring how many EARLY_IN_PERSON
          ballots for each voter_choice. Each ballot is cast by a
          distinct ACTIVE voter (one ballot per voter per election).

    include_provisional:
        Optional {"P1": {"A": 5}} to add ELECTION_DAY_PROVISIONAL casts
        after a machine is marked DOWN at the named precinct.

    Returns:
        {
          "election": {...},
          "precincts": {"P1": {...}, "P2": {...}},
          "machines": {"P1": {...}},  # one machine per precinct
          "voters": {"P1": [...], ...},
        }
    """
    election = create_election(
        election_date=election_date,
        recount_threshold_pct=recount_threshold_pct,
    )
    precincts: Dict[str, Dict[str, Any]] = {}
    machines: Dict[str, Dict[str, Any]] = {}
    for spec in precincts_choice_counts:
        p = create_precinct(
            election["id"],
            code=spec["code"],
            street_pattern=spec.get("pattern", ".*Main.*"),
            capacity_machines=2,
        )
        precincts[spec["code"]] = p
        m = provision_machine(election["id"], p["id"])
        machines[spec["code"]] = m

    election = open_registration(election["id"])

    # Create all voters in OPEN_REGISTRATION (eligibility easy to
    # satisfy: residency_since old enough).
    voters_per_precinct: Dict[str, List[Dict[str, Any]]] = {}
    for spec in precincts_choice_counts:
        token = spec.get("pattern", ".*Main.*").strip(".*")
        total_for_precinct = sum(spec["choices"].values())
        if include_provisional and spec["code"] in include_provisional:
            total_for_precinct += sum(
                include_provisional[spec["code"]].values()
            )
        voters_per_precinct[spec["code"]] = _bulk_active_voters(
            election, precincts[spec["code"]],
            count=total_for_precinct,
            street_token=token,
        )

    # Cast EARLY_IN_PERSON before the EARLY_VOTING→ELECTION_DAY rollover.
    # PRD §3.2: EARLY_VOTING is system-driven on clock advance.
    election = advance_to_early_voting(election)
    voter_cursor: Dict[str, int] = {k: 0 for k in voters_per_precinct}
    for spec in precincts_choice_counts:
        code = spec["code"]
        for choice, n in spec["choices"].items():
            for _ in range(n):
                v = voters_per_precinct[code][voter_cursor[code]]
                voter_cursor[code] += 1
                cast_in_person(
                    voter_id=v["id"],
                    precinct_id=precincts[code]["id"],
                    method="EARLY_IN_PERSON",
                    voter_choice=choice,
                )

    # Advance to ELECTION_DAY for any machine + provisional logic.
    election = advance_to_election_day(election)

    if include_provisional:
        for code, choices_map in include_provisional.items():
            m = machines[code]
            mark_machine_down(m["id"], failure_reason="POWER")
            for choice, n in choices_map.items():
                for _ in range(n):
                    v = voters_per_precinct[code][voter_cursor[code]]
                    voter_cursor[code] += 1
                    cast_in_person(
                        voter_id=v["id"],
                        precinct_id=precincts[code]["id"],
                        method="ELECTION_DAY_PROVISIONAL",
                        voter_choice=choice,
                    )

    advance_past_ballot_return(election)
    election = initiate_tally(election)
    return {
        "election": election,
        "precincts": precincts,
        "machines": machines,
        "voters": voters_per_precinct,
    }


# ===========================================================================
# Tier 5 — Recount lifecycle helpers
# ===========================================================================
def file_manual_recount(election_id: str,
                        petition_count: int = 100) -> Dict[str, Any]:
    resp = api_client.create_recount(
        election_id,
        create_recount_payload(petition_count=petition_count),
        TEST_USERS["election_board_headers"],
    )
    return get_success_data(resp)


def transition_recount(recount_id: str, to_state: str,
                       version: Optional[int] = None) -> Dict[str, Any]:
    resp = api_client.transition_recount(
        recount_id,
        state_transition_payload(to_state, version=version),
        TEST_USERS["election_board_headers"],
    )
    return get_success_data(resp)


def list_recounts(election_id: str) -> List[Dict[str, Any]]:
    resp = api_client.list_recounts(
        election_id, TEST_USERS["election_board_headers"],
    )
    body = resp.json()
    return body.get("data", [])


__all__ = [
    # Clock
    "current_clock", "current_clock_iso",
    "advance_clock_to", "advance_clock_by_seconds",
    "advance_clock_by_days", "advance_clock_iso",
    "reset_clock_tracker_to",
    # Election primitives
    "create_election", "create_precinct", "transition_election",
    "open_registration", "advance_to_early_voting",
    "advance_to_election_day", "advance_past_ballot_return",
    "initiate_tally",
    # Voter primitives
    "create_voter", "activate_voter", "suspend_voter",
    "reactivate_voter", "get_voter",
    # Generic getters
    "get_election", "get_absentee_ballot", "get_curing_case",
    "get_ballot", "get_precinct", "get_voting_machine",
    # Machines
    "provision_machine", "mark_machine_down",
    # Composite Tier 1 / 2
    "setup_election_with_precinct", "setup_open_registration",
    "setup_active_voter",
    # Absentee + Curing
    "request_absentee", "issue_absentee", "return_absentee",
    "setup_returned_absentee_with_curing_case",
    "setup_curing_case_under_review",
    # In-person + tally
    "cast_in_person", "setup_election_in_tally",
    # Recount
    "file_manual_recount", "transition_recount", "list_recounts",
]
