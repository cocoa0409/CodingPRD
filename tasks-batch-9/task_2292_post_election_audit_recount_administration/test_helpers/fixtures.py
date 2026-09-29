"""Composite setup helpers.

Every helper drives the API exactly as a client would and uses the lenient
get_success_data() validator so a broken precondition surfaces as a setup
failure rather than as a confusing assertion inside a test.

The service starts each test with an empty database and its logical clock at
its initial value, so every helper that depends on "now" sets the clock first.
"""

from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import TEST_DEFAULTS
from .factories import (
    batch_line,
    bipartisan_members_payload,
    bulk_ballot_batches_payload,
    canvass_results_payload,
    create_audit_payload,
    create_ballot_interpretation_payload,
    create_contest_payload,
    create_election_payload,
    create_manual_tally_payload,
    create_observer_credential_payload,
    create_recount_payload,
    create_tally_team_payload,
    retrieve_audit_batch_payload,
    seed_audit_payload,
    six_uniform_batch_lines,
)
from .test_users import (
    TEST_USERS,
    make_candidate_representative_headers,
    make_canvassing_board_member_headers,
    make_elections_director_headers,
    make_tally_team_lead_headers,
)

DIRECTOR = TEST_USERS["elections_director_headers"]
AUDIT_MANAGER = TEST_USERS["audit_manager_headers"]
CUSTODY_OFFICER = TEST_USERS["custody_officer_headers"]
BOARD = TEST_USERS["canvassing_board_member_headers"]

CANVASS_DAY = TEST_DEFAULTS["CLOCK_CANVASS_DAY"]


# ---------------------------------------------------------------------------
# Tier 0: primitives
# ---------------------------------------------------------------------------
def set_clock(current_utc: str = CANVASS_DAY) -> str:
    """Move the logical clock and return the value it now reports."""
    data = get_success_data(api_client.set_clock(current_utc, DIRECTOR))
    return data["current_utc"]


def create_election(**overrides) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_election(create_election_payload(**overrides), DIRECTOR)
    )


def create_contest(election_id: str, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_contest(
            create_contest_payload(election_id, **overrides), DIRECTOR
        )
    )


def create_batches(
    election_id: str,
    contest_id: str,
    batches: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """Bulk-create the batches, then read them back in batch_label order."""
    get_success_data(
        api_client.bulk_create_ballot_batches(
            bulk_ballot_batches_payload(election_id, contest_id, batches),
            CUSTODY_OFFICER,
        )
    )
    return list_batches(contest_id)


def list_batches(contest_id: str) -> List[Dict[str, Any]]:
    """All batches of a contest, in the batch_label order the PRD mandates."""
    return get_success_data(
        api_client.list_ballot_batches(
            CUSTODY_OFFICER, params={"contest_id": contest_id, "limit": 100}
        )
    )


def read_batch(ballot_batch_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_ballot_batch(ballot_batch_id, CUSTODY_OFFICER))


def read_contest(contest_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_contest(contest_id, DIRECTOR))


def read_election(election_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_election(election_id, DIRECTOR))


def read_audit(audit_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_audit(audit_id, AUDIT_MANAGER))


def read_audit_round(audit_round_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_audit_round(audit_round_id, AUDIT_MANAGER))


def read_audit_batch(audit_batch_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_audit_batch(audit_batch_id, AUDIT_MANAGER))


def read_manual_tally(manual_tally_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_manual_tally(manual_tally_id, AUDIT_MANAGER))


def read_recount(recount_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_recount(recount_id, DIRECTOR))


def read_discrepancy(discrepancy_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_discrepancy(discrepancy_id, AUDIT_MANAGER))


def read_ballot_interpretation(ballot_interpretation_id: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.get_ballot_interpretation(ballot_interpretation_id, AUDIT_MANAGER)
    )


def read_tally_team(tally_team_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_tally_team(tally_team_id, DIRECTOR))


def read_observer_credential(observer_credential_id: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.get_observer_credential(observer_credential_id, DIRECTOR)
    )


def read_corrective_action(corrective_action_id: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.get_corrective_action(corrective_action_id, BOARD)
    )


def batch_by_label(batches: List[Dict[str, Any]], batch_label: str) -> Dict[str, Any]:
    for batch in batches:
        if batch["batch_label"] == batch_label:
            return batch
    raise AssertionError(f"Setup step failed: no batch labelled {batch_label}")


def list_audit_batches(audit_round_id: str) -> List[Dict[str, Any]]:
    """Drawn batches of a round, in selection_index order."""
    return get_success_data(
        api_client.list_audit_batches(
            CUSTODY_OFFICER, params={"audit_round_id": audit_round_id, "limit": 100}
        )
    )


def list_audit_rounds(audit_id: str) -> List[Dict[str, Any]]:
    """Rounds of an audit, in round_number order."""
    return get_success_data(
        api_client.list_audit_rounds(
            AUDIT_MANAGER, params={"audit_id": audit_id, "limit": 100}
        )
    )


def list_custody_events(ballot_batch_id: str, **params) -> List[Dict[str, Any]]:
    """Custody log of one batch, in sequence_no order."""
    query = {"limit": 100}
    query.update(params)
    return get_success_data(
        api_client.list_ballot_batch_custody_events(
            ballot_batch_id, CUSTODY_OFFICER, params=query
        )
    )


def list_discrepancies(manual_tally_id: str, **params) -> List[Dict[str, Any]]:
    query = {"manual_tally_id": manual_tally_id, "limit": 100}
    query.update(params)
    return get_success_data(api_client.list_discrepancies(AUDIT_MANAGER, params=query))


def only_discrepancy(manual_tally_id: str) -> Dict[str, Any]:
    rows = list_discrepancies(manual_tally_id)
    assert rows, f"Setup step failed: no discrepancy recorded for tally {manual_tally_id}"
    return rows[0]


# ---------------------------------------------------------------------------
# Tier 1: state progression of a contest
# ---------------------------------------------------------------------------
def setup_election_with_contest_and_batches(
    clock: str = CANVASS_DAY,
    contest_overrides: Optional[Dict[str, Any]] = None,
    election_overrides: Optional[Dict[str, Any]] = None,
    batches: Optional[List[Dict[str, Any]]] = None,
    sibling_contests: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Election plus one PENDING_CANVASS contest plus its batches in custody.

    ``sibling_contests`` registers further contests of the same election *before*
    any canvass is recorded.  PRD §3.1 requires the election to still be `OPEN`
    when a canvass is recorded, and the election leaves `OPEN` as soon as every
    one of its contests is `CANVASSED`, so a sibling that is meant to be
    canvassable later has to exist before the first contest is canvassed.
    """
    set_clock(clock)
    election = create_election(**(election_overrides or {}))
    contest = create_contest(election["id"], **(contest_overrides or {}))
    batch_rows = create_batches(election["id"], contest["id"], batches)
    scenario = {"election": election, "contest": contest, "batches": batch_rows}
    if sibling_contests:
        scenario["sibling_contests"] = [
            create_contest(election["id"], **overrides)
            for overrides in sibling_contests
        ]
    return scenario


def canvass_contest(contest_id: str, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api_client.submit_canvass_results(
            contest_id, canvass_results_payload(**overrides), DIRECTOR
        )
    )


def setup_canvassed_contest(
    clock: str = CANVASS_DAY,
    contest_overrides: Optional[Dict[str, Any]] = None,
    election_overrides: Optional[Dict[str, Any]] = None,
    batches: Optional[List[Dict[str, Any]]] = None,
    reported_votes: Optional[Dict[str, int]] = None,
    sibling_contests: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """The six-batch State Auditor contest, canvassed.

    Returns election, contest (post-canvass) and batches, plus sibling_contests
    (still `PENDING_CANVASS`) when any were requested.
    """
    scenario = setup_election_with_contest_and_batches(
        clock=clock,
        contest_overrides=contest_overrides,
        election_overrides=election_overrides,
        batches=batches,
        sibling_contests=sibling_contests,
    )
    kwargs = {}
    if reported_votes is not None:
        kwargs["reported_votes"] = reported_votes
    scenario["contest"] = canvass_contest(scenario["contest"]["id"], **kwargs)
    return scenario


# ---------------------------------------------------------------------------
# Tier 2: tally teams
# ---------------------------------------------------------------------------
def create_bipartisan_team(
    election_id: str,
    team_label: str = "T-1",
    room_code: str = "ROOM-A",
    dem_user_id: str = TEST_DEFAULTS["TEAM_DEM_USER_ID"],
    rep_user_id: str = TEST_DEFAULTS["TEAM_REP_USER_ID"],
) -> Dict[str, Any]:
    """A READY, bipartisan two-seat team."""
    team = get_success_data(
        api_client.create_tally_team(
            create_tally_team_payload(
                election_id, team_label=team_label, room_code=room_code
            ),
            DIRECTOR,
        )
    )
    return get_success_data(
        api_client.set_tally_team_members(
            team["id"], bipartisan_members_payload(dem_user_id, rep_user_id), DIRECTOR
        )
    )


# ---------------------------------------------------------------------------
# Tier 3: audit lifecycle shortcuts
# ---------------------------------------------------------------------------
def create_audit(contest_id: str, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_audit(create_audit_payload(contest_id, **overrides), AUDIT_MANAGER)
    )


def seed_audit(audit_id: str, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api_client.seed_audit(audit_id, seed_audit_payload(**overrides), AUDIT_MANAGER)
    )


def open_round(audit_id: str, **payload_overrides) -> Dict[str, Any]:
    """Open the next round of an audit, reading the audit's current version first."""
    audit = read_audit(audit_id)
    payload: Dict[str, Any] = {"expected_audit_version": audit["version"]}
    payload.update(payload_overrides)
    return get_success_data(
        api_client.create_audit_round(audit_id, payload, AUDIT_MANAGER)
    )


def setup_seeded_audit(
    contest_id: str,
    audit_type: str = "RISK_LIMITING",
    **audit_overrides,
) -> Dict[str, Any]:
    """Create an audit of the given type and publish its seed."""
    payload_overrides: Dict[str, Any] = {"audit_type": audit_type}
    if audit_type == "COMPARISON":
        payload_overrides["prior_error_rate"] = TEST_DEFAULTS["PRIOR_ERROR_RATE"]
    if audit_type == "FIXED_PERCENTAGE":
        payload_overrides["risk_limit_alpha"] = None
        payload_overrides.pop("risk_limit_alpha", None)
        payload_overrides["fixed_percentage_pct"] = 5
    payload_overrides.update(audit_overrides)
    if audit_type == "FIXED_PERCENTAGE":
        payload_overrides.pop("risk_limit_alpha", None)
        audit = get_success_data(
            api_client.create_audit(
                {
                    "contest_id": contest_id,
                    "audit_type": "FIXED_PERCENTAGE",
                    **{
                        key: value
                        for key, value in payload_overrides.items()
                        if key != "audit_type"
                    },
                },
                AUDIT_MANAGER,
            )
        )
    else:
        audit = create_audit(contest_id, **payload_overrides)
    return seed_audit(audit["id"])


def setup_audit_round_one(
    contest_id: str,
    audit_type: str = "RISK_LIMITING",
    **audit_overrides,
) -> Dict[str, Any]:
    """Seeded audit plus its first round plus the drawn batches.

    Returns audit, round and audit_batches (in selection_index order).
    """
    audit = setup_seeded_audit(contest_id, audit_type=audit_type, **audit_overrides)
    audit_round = open_round(audit["id"])
    return {
        "audit": read_audit(audit["id"]),
        "round": audit_round,
        "audit_batches": list_audit_batches(audit_round["id"]),
    }


# ---------------------------------------------------------------------------
# Tier 3b: custody shortcuts
# ---------------------------------------------------------------------------
def retrieve_batch(
    audit_batch_id: str, ballot_batch_id: str, observed_seal_number: str, **overrides
) -> Dict[str, Any]:
    """Check a drawn batch out, reading its physical batch version first."""
    batch = read_batch(ballot_batch_id)
    payload = retrieve_audit_batch_payload(
        batch["version"], observed_seal_number, **overrides
    )
    return get_success_data(
        api_client.retrieve_audit_batch(audit_batch_id, payload, CUSTODY_OFFICER)
    )


def return_batch(audit_batch_id: str, reseal_number: str, **overrides) -> Dict[str, Any]:
    payload = {"reseal_number": reseal_number}
    payload.update(overrides)
    return get_success_data(
        api_client.return_audit_batch(audit_batch_id, payload, CUSTODY_OFFICER)
    )


# ---------------------------------------------------------------------------
# Tier 3c: the canonical hand-count scenario
# ---------------------------------------------------------------------------
def setup_round_one_with_checked_out_batch(
    audit_type: str = "RISK_LIMITING",
    clock: str = CANVASS_DAY,
    with_team: bool = True,
    sibling_contests: Optional[List[Dict[str, Any]]] = None,
    **audit_overrides,
) -> Dict[str, Any]:
    """Canvassed contest, bipartisan team, seeded audit, round 1, B-003 checked out.

    Returns election, contest, batches, team, audit, round, audit_batches,
    target_audit_batch (the drawn B-003) and target_batch (physical B-003).
    """
    scenario = setup_canvassed_contest(clock=clock, sibling_contests=sibling_contests)
    if with_team:
        scenario["team"] = create_bipartisan_team(scenario["election"]["id"])
    scenario.update(
        setup_audit_round_one(
            scenario["contest"]["id"], audit_type=audit_type, **audit_overrides
        )
    )
    target_audit_batch = scenario["audit_batches"][0]
    target_batch = read_batch(target_audit_batch["ballot_batch_id"])
    retrieve_batch(
        target_audit_batch["id"],
        target_batch["id"],
        target_batch["current_seal_number"],
    )
    scenario["target_audit_batch"] = read_audit_batch(target_audit_batch["id"])
    scenario["target_batch"] = read_batch(target_batch["id"])
    return scenario


def open_manual_tally(
    audit_batch_id: str,
    tally_team_id: str,
    session_start_at: str = CANVASS_DAY,
    session_end_at: str = "2026-11-05T11:00:00Z",
    **overrides,
) -> Dict[str, Any]:
    """Open a DRAFT hand count for a drawn batch as that team's lead."""
    payload = create_manual_tally_payload(
        audit_batch_id, tally_team_id, session_start_at, session_end_at, **overrides
    )
    return get_success_data(
        api_client.create_manual_tally(payload, make_tally_team_lead_headers(tally_team_id))
    )


def submit_manual_tally(manual_tally_id: str, tally_team_id: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.submit_manual_tally(
            manual_tally_id, make_tally_team_lead_headers(tally_team_id)
        )
    )


def reopen_manual_tally(
    manual_tally_id: str, tally_team_id: str, reason: str = "Stack recount ordered."
) -> Dict[str, Any]:
    return get_success_data(
        api_client.reopen_manual_tally(
            manual_tally_id, {"reason": reason}, make_tally_team_lead_headers(tally_team_id)
        )
    )


def setup_draft_tally(
    counted_votes: Optional[Dict[str, int]] = None,
    ambiguous_ballot_count: int = 0,
    no_vote_count: int = 0,
    session_start_at: str = CANVASS_DAY,
    session_end_at: str = "2026-11-05T11:00:00Z",
    audit_type: str = "RISK_LIMITING",
    clock: str = CANVASS_DAY,
    sibling_contests: Optional[List[Dict[str, Any]]] = None,
    **audit_overrides,
) -> Dict[str, Any]:
    """The full chain up to a DRAFT hand count of the first drawn batch.

    counted_votes defaults to an exact machine match (525 / 475).
    """
    scenario = setup_round_one_with_checked_out_batch(
        audit_type=audit_type,
        clock=clock,
        sibling_contests=sibling_contests,
        **audit_overrides,
    )
    scenario["manual_tally"] = open_manual_tally(
        scenario["target_audit_batch"]["id"],
        scenario["team"]["id"],
        session_start_at=session_start_at,
        session_end_at=session_end_at,
        counted_votes=(
            dict(counted_votes)
            if counted_votes is not None
            else dict(TEST_DEFAULTS["C1_BATCH_MACHINE_VOTES"])
        ),
        ambiguous_ballot_count=ambiguous_ballot_count,
        no_vote_count=no_vote_count,
    )
    return scenario


def setup_submitted_tally(
    counted_votes: Optional[Dict[str, int]] = None,
    **overrides,
) -> Dict[str, Any]:
    """setup_draft_tally, then submit.  Adds submitted_tally to the scenario."""
    scenario = setup_draft_tally(counted_votes=counted_votes, **overrides)
    scenario["submitted_tally"] = submit_manual_tally(
        scenario["manual_tally"]["id"], scenario["team"]["id"]
    )
    return scenario


def setup_open_discrepancy(
    counted_votes: Optional[Dict[str, int]] = None, **overrides
) -> Dict[str, Any]:
    """A submitted, discrepant hand count with its OPEN discrepancy row.

    counted_votes defaults to 520 / 480, ten votes of overstatement.
    """
    scenario = setup_submitted_tally(
        counted_votes=counted_votes
        if counted_votes is not None
        else {"ALVAREZ": 520, "BRENNAN": 480},
        **overrides,
    )
    scenario["discrepancy"] = only_discrepancy(scenario["manual_tally"]["id"])
    return scenario


def document_discrepancy(
    discrepancy_id: str,
    documentation_note: str = "Overstatement confirmed against the machine tape.",
    board_user_id: str = TEST_DEFAULTS["BOARD_DEM_USER_ID"],
) -> Dict[str, Any]:
    return get_success_data(
        api_client.document_discrepancy(
            discrepancy_id,
            {"documentation_note": documentation_note},
            make_canvassing_board_member_headers(board_user_id),
        )
    )


def setup_documented_discrepancy(**overrides) -> Dict[str, Any]:
    """An OPEN discrepancy walked to DOCUMENTED by a board member."""
    scenario = setup_open_discrepancy(**overrides)
    scenario["discrepancy"] = document_discrepancy(scenario["discrepancy"]["id"])
    return scenario


def escalate_discrepancy(
    discrepancy_id: str,
    escalation_reason: str = "Round measure above the risk limit; hand count ordered.",
    board_user_id: str = TEST_DEFAULTS["BOARD_DEM_USER_ID"],
) -> Dict[str, Any]:
    return get_success_data(
        api_client.escalate_discrepancy(
            discrepancy_id,
            {"escalation_reason": escalation_reason},
            make_canvassing_board_member_headers(board_user_id),
        )
    )


def setup_escalated_audit(**overrides) -> Dict[str, Any]:
    """A documented discrepancy escalated into a full hand count round."""
    scenario = setup_documented_discrepancy(**overrides)
    scenario["discrepancy"] = escalate_discrepancy(scenario["discrepancy"]["id"])
    scenario["rounds"] = list_audit_rounds(scenario["audit"]["id"])
    scenario["escalation_round"] = scenario["rounds"][-1]
    scenario["escalation_batches"] = list_audit_batches(
        scenario["escalation_round"]["id"]
    )
    scenario["audit"] = read_audit(scenario["audit"]["id"])
    return scenario


# ---------------------------------------------------------------------------
# Tier 3d: adjudication
# ---------------------------------------------------------------------------
def refer_ballot_interpretation(
    manual_tally_id: str, tally_team_id: str, **overrides
) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_ballot_interpretation(
            create_ballot_interpretation_payload(manual_tally_id, **overrides),
            make_tally_team_lead_headers(tally_team_id),
        )
    )


def cast_board_vote(
    ballot_interpretation_id: str, board_user_id: str, party: str, vote: str
) -> Dict[str, Any]:
    return get_success_data(
        api_client.cast_ballot_interpretation_vote(
            ballot_interpretation_id,
            {"party": party, "vote": vote},
            make_canvassing_board_member_headers(board_user_id),
        )
    )


def setup_pending_adjudication(
    counted_votes: Optional[Dict[str, int]] = None,
    ambiguous_ballot_count: int = 1,
    **overrides,
) -> Dict[str, Any]:
    """A submitted tally with one PENDING voter-intent referral.

    counted_votes defaults to 519 / 480 with one ambiguous ballot, so the
    accounting identity holds at 1000.
    """
    scenario = setup_submitted_tally(
        counted_votes=counted_votes
        if counted_votes is not None
        else {"ALVAREZ": 519, "BRENNAN": 480},
        ambiguous_ballot_count=ambiguous_ballot_count,
        **overrides,
    )
    scenario["interpretation"] = refer_ballot_interpretation(
        scenario["manual_tally"]["id"], scenario["team"]["id"]
    )
    return scenario


# ---------------------------------------------------------------------------
# Tier 3e: the two-audit scenario that shares one physical batch
# ---------------------------------------------------------------------------
def setup_two_audits_sharing_first_batch(clock: str = CANVASS_DAY) -> Dict[str, Any]:
    """One canvassed contest carrying both a risk-limiting and a comparison audit.

    Both audits are seeded with the same seed, so both draw B-003 first.  The
    physical batch is checked out once, under the risk-limiting audit's drawing.
    """
    scenario = setup_canvassed_contest(clock=clock)
    scenario["team"] = create_bipartisan_team(scenario["election"]["id"])
    rla = setup_audit_round_one(scenario["contest"]["id"], audit_type="RISK_LIMITING")
    comparison = setup_audit_round_one(
        scenario["contest"]["id"], audit_type="COMPARISON"
    )
    scenario["rla"] = rla
    scenario["comparison"] = comparison
    shared = rla["audit_batches"][0]
    physical = read_batch(shared["ballot_batch_id"])
    retrieve_batch(shared["id"], physical["id"], physical["current_seal_number"])
    scenario["shared_batch"] = read_batch(physical["id"])
    scenario["rla_target"] = read_audit_batch(shared["id"])
    scenario["comparison_target"] = read_audit_batch(
        comparison["audit_batches"][0]["id"]
    )
    return scenario


# ---------------------------------------------------------------------------
# Tier 4: the recount money scenario
# ---------------------------------------------------------------------------
def c2_batch_lines() -> List[Dict[str, Any]]:
    """Three deliberately uneven batches: 1000, 995 and 1005 ballots."""
    return [
        batch_line("C2-B01", 1000, {"CHEN": 525, "DAVIS": 475}, "S2-01", "VAULT-2"),
        batch_line("C2-B02", 995, {"CHEN": 522, "DAVIS": 473}, "S2-02", "VAULT-2"),
        batch_line("C2-B03", 1005, {"CHEN": 528, "DAVIS": 477}, "S2-03", "VAULT-2"),
    ]


def c3_batch_lines() -> List[Dict[str, Any]]:
    """Two batches of 1250 and 1000 ballots."""
    return [
        batch_line("C3-B01", 1250, {"FORD": 660, "GRANT": 590}, "S3-01", "VAULT-3"),
        batch_line("C3-B02", 1000, {"FORD": 520, "GRANT": 480}, "S3-02", "VAULT-3"),
    ]


def setup_canvassed_treasurer_contest(clock: str = CANVASS_DAY) -> Dict[str, Any]:
    """Election ST-02 with contest C2 canvassed over its three uneven batches."""
    set_clock(clock)
    election = create_election(jurisdiction_code=TEST_DEFAULTS["E2_JURISDICTION_CODE"])
    contest = create_contest(
        election["id"],
        contest_label=TEST_DEFAULTS["C2_LABEL"],
        office_name=TEST_DEFAULTS["C2_OFFICE_NAME"],
        candidate_names=list(TEST_DEFAULTS["C2_CANDIDATES"]),
        ballots_cast=TEST_DEFAULTS["C2_BALLOTS_CAST"],
        cvr_available=False,
    )
    batches = create_batches(election["id"], contest["id"], c2_batch_lines())
    contest = canvass_contest(
        contest["id"], reported_votes=dict(TEST_DEFAULTS["C2_REPORTED_VOTES"])
    )
    return {"election": election, "contest": contest, "batches": batches}


def setup_canvassed_two_contest_election(clock: str = CANVASS_DAY) -> Dict[str, Any]:
    """Election ST-02 with both C2 and C3 canvassed, so the election is CANVASSED.

    Both contests are registered *before* either canvass runs: PRD §3.1 requires
    the election to still be `OPEN` when a canvass is recorded, and the election
    only leaves `OPEN` once every one of its contests is `CANVASSED`.  Canvassing
    C2 first and adding C3 afterwards would therefore make C3's canvass illegal.
    """
    set_clock(clock)
    election = create_election(jurisdiction_code=TEST_DEFAULTS["E2_JURISDICTION_CODE"])
    contest = create_contest(
        election["id"],
        contest_label=TEST_DEFAULTS["C2_LABEL"],
        office_name=TEST_DEFAULTS["C2_OFFICE_NAME"],
        candidate_names=list(TEST_DEFAULTS["C2_CANDIDATES"]),
        ballots_cast=TEST_DEFAULTS["C2_BALLOTS_CAST"],
        cvr_available=False,
    )
    batches = create_batches(election["id"], contest["id"], c2_batch_lines())
    contest_c3 = create_contest(
        election["id"],
        contest_label=TEST_DEFAULTS["C3_LABEL"],
        office_name=TEST_DEFAULTS["C3_OFFICE_NAME"],
        candidate_names=list(TEST_DEFAULTS["C3_CANDIDATES"]),
        ballots_cast=TEST_DEFAULTS["C3_BALLOTS_CAST"],
        cvr_available=False,
    )
    batches_c3 = create_batches(election["id"], contest_c3["id"], c3_batch_lines())
    canvass_contest(contest["id"], reported_votes=dict(TEST_DEFAULTS["C2_REPORTED_VOTES"]))
    canvass_contest(
        contest_c3["id"], reported_votes=dict(TEST_DEFAULTS["C3_REPORTED_VOTES"])
    )
    return {
        "election": read_election(election["id"]),
        "contest": read_contest(contest["id"]),
        "batches": batches,
        "contest_c3": read_contest(contest_c3["id"]),
        "batches_c3": batches_c3,
    }


def file_recount(
    contest_id: str,
    requester_user_id: str = "rep-davis",
    role: str = "CandidateRepresentative",
    **payload_overrides,
) -> Dict[str, Any]:
    """File a recount, reading the contest's current version first."""
    contest = read_contest(contest_id)
    payload = create_recount_payload(contest_id, contest["version"], **payload_overrides)
    headers = (
        make_candidate_representative_headers(requester_user_id)
        if role == "CandidateRepresentative"
        else make_elections_director_headers(requester_user_id)
    )
    return get_success_data(api_client.create_recount(payload, headers))


def post_deposit(
    recount_id: str, amount_cents: int, requester_user_id: str = "rep-davis"
) -> Dict[str, Any]:
    return get_success_data(
        api_client.post_recount_deposit(
            recount_id,
            {"amount_cents": amount_cents},
            make_candidate_representative_headers(requester_user_id),
        )
    )


def start_recount(recount_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.start_recount(recount_id, DIRECTOR))


def complete_recount(
    recount_id: str, final_votes: Dict[str, int], team_hours: float
) -> Dict[str, Any]:
    return get_success_data(
        api_client.complete_recount(
            recount_id, {"final_votes": final_votes, "team_hours": team_hours}, DIRECTOR
        )
    )


def setup_funded_recount(
    contest_id: str,
    amount_cents: int,
    requester_user_id: str = "rep-davis",
    **payload_overrides,
) -> Dict[str, Any]:
    """File a candidate-requested recount and post its deposit in full."""
    recount = file_recount(
        contest_id, requester_user_id=requester_user_id, **payload_overrides
    )
    return post_deposit(recount["id"], amount_cents, requester_user_id)


def setup_recount_in_progress(
    contest_id: str,
    amount_cents: int,
    requester_user_id: str = "rep-davis",
    **payload_overrides,
) -> Dict[str, Any]:
    """A funded recount already started, ready to be completed."""
    recount = setup_funded_recount(
        contest_id,
        amount_cents,
        requester_user_id=requester_user_id,
        **payload_overrides,
    )
    return start_recount(recount["id"])


# ---------------------------------------------------------------------------
# Tier 5: observers, corrective actions and finalisation
# ---------------------------------------------------------------------------
def create_observer_credential(election_id: str, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_observer_credential(
            create_observer_credential_payload(election_id, **overrides), DIRECTOR
        )
    )


def setup_room_at_observer_capacity(
    election_id: str, room_code: str = "ROOM-A"
) -> List[Dict[str, Any]]:
    """Two ACTIVE credentials covering the same room for the same window."""
    first = create_observer_credential(
        election_id,
        organization_name="League of Voters",
        party_affiliation="DEM",
        room_code=room_code,
    )
    second = create_observer_credential(
        election_id,
        organization_name="Citizens Watch",
        party_affiliation="REP",
        room_code=room_code,
    )
    return [first, second]


def create_corrective_action(discrepancy_id: str, **overrides) -> Dict[str, Any]:
    from .factories import create_corrective_action_payload

    return get_success_data(
        api_client.create_corrective_action(
            create_corrective_action_payload(discrepancy_id, **overrides), BOARD
        )
    )


def transition_corrective_action(
    corrective_action_id: str,
    to_status: str,
    board_user_id: str = TEST_DEFAULTS["BOARD_DEM_USER_ID"],
    **overrides,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"to_status": to_status}
    payload.update(overrides)
    return get_success_data(
        api_client.transition_corrective_action(
            corrective_action_id,
            payload,
            make_canvassing_board_member_headers(board_user_id),
        )
    )


def resolve_discrepancy(
    discrepancy_id: str,
    resolution_note: str = "Finding closed after the corrective action was verified.",
    board_user_id: str = TEST_DEFAULTS["BOARD_DEM_USER_ID"],
) -> Dict[str, Any]:
    return get_success_data(
        api_client.resolve_discrepancy(
            discrepancy_id,
            {"resolution_note": resolution_note},
            make_canvassing_board_member_headers(board_user_id),
        )
    )


def terminate_audit(
    audit_id: str, terminated_reason: str = "Superseded by a full-contest recount."
) -> Dict[str, Any]:
    return get_success_data(
        api_client.terminate_audit(audit_id, {"terminated_reason": terminated_reason}, DIRECTOR)
    )


def setup_terminated_audit(**overrides) -> Dict[str, Any]:
    """A seeded audit with one open round, then terminated."""
    scenario = setup_canvassed_contest(**overrides)
    scenario.update(setup_audit_round_one(scenario["contest"]["id"]))
    scenario["audit"] = terminate_audit(scenario["audit"]["id"])
    return scenario


def setup_clean_counted_round(clock: str = CANVASS_DAY) -> Dict[str, Any]:
    """Round 1 with all three drawn batches hand counted at an exact machine match.

    Every drawn batch is retrieved, counted 525 / 475, submitted and resealed, so
    the audit carries no discrepancy and the round is ready to be closed.
    """
    scenario = setup_canvassed_contest(clock=clock)
    scenario["team"] = create_bipartisan_team(scenario["election"]["id"])
    scenario.update(setup_audit_round_one(scenario["contest"]["id"]))
    tallies = []
    session_windows = [
        (CANVASS_DAY, "2026-11-05T11:00:00Z"),
        ("2026-11-05T11:30:00Z", "2026-11-05T13:30:00Z"),
        ("2026-11-05T14:00:00Z", "2026-11-05T16:00:00Z"),
    ]
    for audit_batch, (start_at, end_at) in zip(
        scenario["audit_batches"], session_windows
    ):
        physical = read_batch(audit_batch["ballot_batch_id"])
        retrieve_batch(
            audit_batch["id"], physical["id"], physical["current_seal_number"]
        )
        tally = open_manual_tally(
            audit_batch["id"],
            scenario["team"]["id"],
            session_start_at=start_at,
            session_end_at=end_at,
            counted_votes=dict(TEST_DEFAULTS["C1_BATCH_MACHINE_VOTES"]),
            ambiguous_ballot_count=0,
            no_vote_count=0,
        )
        tallies.append(submit_manual_tally(tally["id"], scenario["team"]["id"]))
        return_batch(
            audit_batch["id"], f"{physical['current_seal_number']}R"
        )
    scenario["tallies"] = tallies
    scenario["audit"] = read_audit(scenario["audit"]["id"])
    scenario["round"] = read_audit_round(scenario["round"]["id"])
    return scenario
