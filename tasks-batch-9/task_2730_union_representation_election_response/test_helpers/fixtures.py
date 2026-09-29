"""Composite setup helpers.

Every helper builds its preconditions from scratch through PRD-declared
endpoints, so a test can start from an empty database and reach a deep case
state in one call. Setup calls use the lenient success validator, so a broken
precondition surfaces as a setup failure rather than as a confusing assertion.

The scenario helpers thread a plain ``ctx`` dict with these keys as they are
reached: ``petition``, ``classifications``, ``agreement``, ``round``,
``voter_list``, ``entries``, ``sessions``, ``ballots``, ``supervisors``,
``messages``, ``objections``, ``charges``.
"""
from typing import Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import REQUIRED_TRAINING_MODULES, TEST_DEFAULTS
from .factories import (
    accuracy_review_payload,
    close_session_payload,
    create_campaign_communication_payload,
    create_challenged_ballot_payload,
    create_classification_payload,
    create_election_agreement_payload,
    create_objection_payload,
    create_petition_payload,
    create_poll_session_payload,
    create_supervisor_payload,
    create_ulp_charge_payload,
    create_voter_list_entry_payload,
    create_voter_list_payload,
    designate_observer_payload,
    direct_election_payload,
    resolve_ballot_payload,
    rule_objection_payload,
    stipulate_payload,
    train_payload,
    verify_showing_payload,
)
from .test_users import ANALYST, BOARD, COUNSEL, DIRECTOR, TRAINER, UNION

DEFAULT_CLOCK = TEST_DEFAULTS["CLOCK"]


# --------------------------------------------------------------------------
# Logical clock
# --------------------------------------------------------------------------
def set_clock(instant: str, headers: Optional[dict] = None) -> None:
    """Move the logical UTC clock to ``instant``."""
    resp = api_client.set_clock({"current_utc": instant}, headers or DIRECTOR)
    get_success_data(resp)


# --------------------------------------------------------------------------
# Single-step helpers
# --------------------------------------------------------------------------
def create_petition(headers: Optional[dict] = None, **overrides) -> dict:
    resp = api_client.create_petition(create_petition_payload(**overrides), headers or DIRECTOR)
    return get_success_data(resp)


def read_petition(petition_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(api_client.get_petition(petition_id, headers or DIRECTOR))


def petition_version(petition_id: str) -> int:
    """The petition's current version, for the read-consistent voter-list create."""
    return read_petition(petition_id)["version"]


def open_scope_analysis(petition_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(api_client.open_scope_analysis(petition_id, headers or DIRECTOR))


def create_petition_in_scope_analysis(headers: Optional[dict] = None, **overrides) -> dict:
    petition = create_petition(headers, **overrides)
    return open_scope_analysis(petition["id"], headers)


def add_classification(petition_id: str, headers: Optional[dict] = None, **overrides) -> dict:
    resp = api_client.create_classification(
        create_classification_payload(petition_id, **overrides), headers or DIRECTOR
    )
    return get_success_data(resp)


def score_classification(classification_id: str, scoring_standard: str = "TRADITIONAL",
                         headers: Optional[dict] = None) -> dict:
    resp = api_client.score_classification(
        classification_id, {"scoring_standard": scoring_standard}, headers or DIRECTOR
    )
    return get_success_data(resp)


def rule_classification(classification_id: str, ruling: str = "INCLUDED",
                        ruling_rationale: str = "Shares a community of interest with the core group.",
                        headers: Optional[dict] = None) -> dict:
    resp = api_client.rule_classification(
        classification_id, {"ruling": ruling, "ruling_rationale": ruling_rationale},
        headers or BOARD,
    )
    return get_success_data(resp)


def reconsider_classification(classification_id: str, reconsideration_note: Optional[str] = None,
                              headers: Optional[dict] = None) -> dict:
    payload = {} if reconsideration_note is None else {"reconsideration_note": reconsideration_note}
    resp = api_client.reconsider_classification(classification_id, payload, headers or BOARD)
    return get_success_data(resp)


def score_and_rule(classification_id: str, ruling: str = "INCLUDED",
                   scoring_standard: str = "TRADITIONAL") -> dict:
    """Score then rule one classification, the order the Board ruling requires."""
    score_classification(classification_id, scoring_standard)
    return rule_classification(classification_id, ruling)


def verify_showing(petition_id: str, headers: Optional[dict] = None, **counts) -> dict:
    resp = api_client.verify_showing(
        petition_id, verify_showing_payload(**counts), headers or BOARD
    )
    return get_success_data(resp)


def create_election_agreement(petition_id: str, headers: Optional[dict] = None, **overrides) -> dict:
    resp = api_client.create_election_agreement(
        create_election_agreement_payload(petition_id, **overrides), headers or DIRECTOR
    )
    return get_success_data(resp)


def stipulate_agreement(agreement_id: str, headers: Optional[dict] = None, **overrides) -> dict:
    resp = api_client.stipulate_agreement(
        agreement_id, stipulate_payload(**overrides), headers or BOARD
    )
    return get_success_data(resp)


def request_hearing(agreement_id: str, party: str = "EMPLOYER",
                    headers: Optional[dict] = None) -> dict:
    resp = api_client.request_hearing(
        agreement_id, {"hearing_requested_by_party": party}, headers or DIRECTOR
    )
    return get_success_data(resp)


def direct_election(agreement_id: str, headers: Optional[dict] = None, **overrides) -> dict:
    resp = api_client.direct_election(
        agreement_id, direct_election_payload(**overrides), headers or BOARD
    )
    return get_success_data(resp)


def rounds_for_petition(petition_id: str, headers: Optional[dict] = None) -> List[dict]:
    resp = api_client.list_election_rounds(headers or BOARD, params={"petition_id": petition_id})
    return get_success_data(resp)


def latest_round(petition_id: str) -> dict:
    """The highest-numbered election round on the case."""
    rows = rounds_for_petition(petition_id)
    assert rows, f"no election round exists for petition {petition_id}"
    return sorted(rows, key=lambda r: r["round_number"])[-1]


def read_round(round_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(api_client.get_election_round(round_id, headers or BOARD))


def round_version(round_id: str) -> int:
    """The round's current version, for the read-consistent poll-session create."""
    return read_round(round_id)["version"]


def create_voter_list(petition_id: str, election_agreement_id: str,
                      expected_petition_version: Optional[int] = None,
                      headers: Optional[dict] = None, **overrides) -> dict:
    version = (
        expected_petition_version
        if expected_petition_version is not None
        else petition_version(petition_id)
    )
    resp = api_client.create_voter_list(
        create_voter_list_payload(petition_id, election_agreement_id, version, **overrides),
        headers or DIRECTOR,
    )
    return get_success_data(resp)


def read_voter_list(voter_list_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(api_client.get_voter_list(voter_list_id, headers or DIRECTOR))


def add_voter_entry(voter_list_id: str, classification_id: str,
                    headers: Optional[dict] = None, **overrides) -> dict:
    resp = api_client.create_voter_list_entry(
        create_voter_list_entry_payload(voter_list_id, classification_id, **overrides),
        headers or ANALYST,
    )
    return get_success_data(resp)


def add_complete_entries(voter_list_id: str, classification_id: str, count: int,
                         **overrides) -> List[dict]:
    """Add ``count`` entries whose five statutory content fields are all present."""
    entries = []
    for index in range(count):
        entries.append(
            add_voter_entry(
                voter_list_id, classification_id,
                full_name=f"Voter {index + 1:03d}",
                personal_email=f"voter{index + 1:03d}@example.com",
                **overrides,
            )
        )
    return entries


def add_incomplete_entries(voter_list_id: str, classification_id: str, count: int,
                           missing_fields=("personal_email",), **overrides) -> List[dict]:
    """Add ``count`` entries with the named statutory content fields omitted."""
    entries = []
    for index in range(count):
        payload = {
            "full_name": f"Incomplete Voter {index + 1:03d}",
            "personal_email": f"incomplete{index + 1:03d}@example.com",
        }
        payload.update(overrides)
        for field in missing_fields:
            payload.pop(field, None)
            payload[field] = None
        entries.append(add_voter_entry(voter_list_id, classification_id, **payload))
    return entries


def submit_voter_list(voter_list_id: str, attested_by_title: str = "Director of Labor Relations",
                      late_submission_ack: Optional[bool] = None,
                      headers: Optional[dict] = None) -> dict:
    payload = {"attested_by_title": attested_by_title}
    if late_submission_ack is not None:
        payload["late_submission_ack"] = late_submission_ack
    resp = api_client.submit_voter_list(voter_list_id, payload, headers or DIRECTOR)
    return get_success_data(resp)


def resubmit_voter_list(voter_list_id: str, attested_by_title: str = "Director of Labor Relations",
                        headers: Optional[dict] = None) -> dict:
    resp = api_client.resubmit_voter_list(
        voter_list_id, {"attested_by_title": attested_by_title}, headers or DIRECTOR
    )
    return get_success_data(resp)


def review_voter_list(voter_list_id: str, disposition: str = "ACCEPT",
                      noted_defects: Optional[List[str]] = None,
                      headers: Optional[dict] = None) -> dict:
    payload: Dict[str, object] = {"disposition": disposition}
    if noted_defects is not None:
        payload["noted_defects"] = noted_defects
    resp = api_client.review_voter_list(voter_list_id, payload, headers or BOARD)
    return get_success_data(resp)


def register_supervisor(petition_id: str, headers: Optional[dict] = None, **overrides) -> dict:
    resp = api_client.create_supervisor(
        create_supervisor_payload(petition_id, **overrides), headers or DIRECTOR
    )
    return get_success_data(resp)


def train_supervisor(supervisor_id: str, headers: Optional[dict] = None, **overrides) -> dict:
    resp = api_client.train_supervisor(supervisor_id, train_payload(**overrides), headers or TRAINER)
    return get_success_data(resp)


def create_trained_supervisor(petition_id: str, **overrides) -> dict:
    """Register a supervisor and certify them with a qualifying training attempt."""
    supervisor = register_supervisor(petition_id, **overrides)
    return train_supervisor(supervisor["id"])


def record_violation(supervisor_id: str, violation_code: str = "THREAT",
                     substantiated: bool = True, headers: Optional[dict] = None) -> dict:
    resp = api_client.record_violation(
        supervisor_id, {"violation_code": violation_code, "substantiated": substantiated},
        headers or COUNSEL,
    )
    return get_success_data(resp)


def create_campaign_message(petition_id: str, headers: Optional[dict] = None, **overrides) -> dict:
    resp = api_client.create_campaign_communication(
        create_campaign_communication_payload(petition_id, **overrides), headers or DIRECTOR
    )
    return get_success_data(resp)


def read_campaign_message(communication_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(
        api_client.get_campaign_communication(communication_id, headers or DIRECTOR)
    )


def accuracy_review(communication_id: str, headers: Optional[dict] = None, **overrides) -> dict:
    resp = api_client.accuracy_review_communication(
        communication_id, accuracy_review_payload(**overrides), headers or DIRECTOR
    )
    return get_success_data(resp)


def submit_message_for_review(communication_id: str, headers: Optional[dict] = None) -> dict:
    resp = api_client.submit_communication_for_review(communication_id, headers or DIRECTOR)
    return get_success_data(resp)


def review_message(communication_id: str, disposition: str = "APPROVE",
                   escalation_ack: Optional[bool] = None, review_note: Optional[str] = None,
                   headers: Optional[dict] = None) -> dict:
    payload: Dict[str, object] = {"disposition": disposition}
    if escalation_ack is not None:
        payload["escalation_ack"] = escalation_ack
    if review_note is not None:
        payload["review_note"] = review_note
    resp = api_client.review_communication(communication_id, payload, headers or COUNSEL)
    return get_success_data(resp)


def deliver_message(communication_id: str, headers: Optional[dict] = None) -> dict:
    resp = api_client.deliver_communication(communication_id, headers or DIRECTOR)
    return get_success_data(resp)


def create_approved_message(petition_id: str, message_overrides: Optional[dict] = None,
                            review_overrides: Optional[dict] = None,
                            accuracy_overrides: Optional[dict] = None) -> dict:
    """Draft, accuracy-review, submit for legal review and approve one message.

    The drafting director and the reviewing counsel are different users, as the
    segregation-of-duties rule requires.
    """
    message = create_campaign_message(petition_id, **(message_overrides or {}))
    accuracy_review(message["id"], **(accuracy_overrides or {}))
    submit_message_for_review(message["id"])
    return review_message(message["id"], **(review_overrides or {}))


def create_poll_session(round_id: str, expected_election_round_version: Optional[int] = None,
                        headers: Optional[dict] = None, **overrides) -> dict:
    version = (
        expected_election_round_version
        if expected_election_round_version is not None
        else round_version(round_id)
    )
    resp = api_client.create_poll_session(
        create_poll_session_payload(round_id, version, **overrides), headers or BOARD
    )
    return get_success_data(resp)


def read_poll_session(session_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(api_client.get_poll_session(session_id, headers or BOARD))


def designate_observer(session_id: str, headers: Optional[dict] = None, **overrides) -> dict:
    resp = api_client.designate_observer(
        session_id, designate_observer_payload(**overrides), headers or BOARD
    )
    return get_success_data(resp)


def open_polls(round_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(api_client.open_polls(round_id, headers or BOARD))


def close_poll_session(session_id: str, headers: Optional[dict] = None, **counts) -> dict:
    resp = api_client.close_poll_session(
        session_id, close_session_payload(**counts), headers or BOARD
    )
    return get_success_data(resp)


def post_tally(round_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(api_client.post_tally(round_id, headers or BOARD))


def revise_tally(round_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(api_client.revise_tally(round_id, headers or BOARD))


def segregate_ballot(poll_session_id: str, headers: Optional[dict] = None, **overrides) -> dict:
    resp = api_client.create_challenged_ballot(
        create_challenged_ballot_payload(poll_session_id, **overrides), headers or BOARD
    )
    return get_success_data(resp)


def resolve_ballot(ballot_id: str, headers: Optional[dict] = None, **overrides) -> dict:
    resp = api_client.resolve_challenged_ballot(
        ballot_id, resolve_ballot_payload(**overrides), headers or BOARD
    )
    return get_success_data(resp)


def reopen_ballot(ballot_id: str, reopen_reason: Optional[str] = None,
                  headers: Optional[dict] = None) -> dict:
    payload = {} if reopen_reason is None else {"reopen_reason": reopen_reason}
    resp = api_client.reopen_challenged_ballot(ballot_id, payload, headers or BOARD)
    return get_success_data(resp)


def file_objection(round_id: str, headers: Optional[dict] = None, **overrides) -> dict:
    resp = api_client.create_objection(
        create_objection_payload(round_id, **overrides), headers or DIRECTOR
    )
    return get_success_data(resp)


def rule_objection(objection_id: str, headers: Optional[dict] = None, **overrides) -> dict:
    resp = api_client.rule_objection(
        objection_id, rule_objection_payload(**overrides), headers or BOARD
    )
    return get_success_data(resp)


def docket_charge(petition_id: str, headers: Optional[dict] = None, **overrides) -> dict:
    resp = api_client.create_ulp_charge(
        create_ulp_charge_payload(petition_id, **overrides), headers or UNION
    )
    return get_success_data(resp)


def docket_blocking_charge(petition_id: str, **overrides) -> dict:
    """Docket a charge that asks for the election to be blocked."""
    overrides.setdefault("blocking_requested", True)
    return docket_charge(petition_id, **overrides)


def determine_charge(charge_id: str, determination: str = "DISMISS",
                     remedy_code: Optional[str] = None,
                     notice_posting_days: Optional[int] = None,
                     headers: Optional[dict] = None) -> dict:
    payload: Dict[str, object] = {"determination": determination}
    if remedy_code is not None:
        payload["remedy_code"] = remedy_code
    if notice_posting_days is not None:
        payload["notice_posting_days"] = notice_posting_days
    resp = api_client.determine_ulp_charge(charge_id, payload, headers or BOARD)
    return get_success_data(resp)


def settle_charge(charge_id: str, settlement_type: str = "NON_BOARD",
                  notice_posting_days: Optional[int] = None,
                  headers: Optional[dict] = None) -> dict:
    payload: Dict[str, object] = {"settlement_type": settlement_type}
    if notice_posting_days is not None:
        payload["notice_posting_days"] = notice_posting_days
    resp = api_client.settle_ulp_charge(charge_id, payload, headers or COUNSEL)
    return get_success_data(resp)


def certify_petition(petition_id: str, election_round_id: str,
                     headers: Optional[dict] = None) -> dict:
    resp = api_client.certify_petition(
        petition_id, {"election_round_id": election_round_id}, headers or BOARD
    )
    return get_success_data(resp)


def schedule_rerun(petition_id: str, headers: Optional[dict] = None, **overrides) -> dict:
    payload = {
        "rerun_election_date": "2026-10-06",
        "voting_method": "MANUAL",
        "polls_open_at": "2026-10-06T08:00:00Z",
        "polls_close_at": "2026-10-06T16:00:00Z",
    }
    payload.update(overrides)
    resp = api_client.schedule_rerun(petition_id, payload, headers or BOARD)
    return get_success_data(resp)


# --------------------------------------------------------------------------
# Scenario stages. Each stage accepts the ctx produced by the previous one, or
# builds the whole chain from an empty database when ctx is omitted.
# --------------------------------------------------------------------------
DEFAULT_CLASSIFICATION_SPECS = [
    {
        "code": "PROD", "title": "Production Operator", "headcount": 60,
        "avg_hourly_wage_cents": 2400, "employer_position": "INCLUDE",
        "union_position": "INCLUDE", "supervision_overlap": 88, "skills_overlap": 90,
        "functional_integration": 92, "interchange_rate": 74, "work_conditions_overlap": 95,
    },
]

DEFAULT_SESSION_SPEC = {
    "location_code": "GATE_A",
    "session_start_at": "2026-09-01T08:00:00Z",
    "session_end_at": "2026-09-01T12:00:00Z",
    "method": "MANUAL",
}


def setup_scope_analysis(clock: str = DEFAULT_CLOCK, petition_overrides: Optional[dict] = None,
                         classification_specs: Optional[List[dict]] = None) -> dict:
    """Docketed case moved into scope analysis with its classification roster."""
    set_clock(clock)
    petition = create_petition(**(petition_overrides or {}))
    petition = open_scope_analysis(petition["id"])
    specs = DEFAULT_CLASSIFICATION_SPECS if classification_specs is None else classification_specs
    classifications = [add_classification(petition["id"], **spec) for spec in specs]
    return {
        "clock": clock,
        "petition": read_petition(petition["id"]),
        "classifications": classifications,
    }


def setup_soi_verified(ctx: Optional[dict] = None, rulings: Optional[List[str]] = None,
                       card_counts: Optional[dict] = None, scoring_standard: str = "TRADITIONAL",
                       **scope_kwargs) -> dict:
    """Score and rule every classification, then verify a sufficient showing."""
    ctx = ctx or setup_scope_analysis(**scope_kwargs)
    classifications = ctx["classifications"]
    if rulings is None:
        rulings = ["INCLUDED"] * len(classifications)
    ruled = []
    for classification, ruling in zip(classifications, rulings):
        score_classification(classification["id"], scoring_standard)
        if ruling is None:
            ruled.append(
                get_success_data(api_client.get_classification(classification["id"], BOARD))
            )
        else:
            ruled.append(rule_classification(classification["id"], ruling))
    ctx["classifications"] = ruled
    ctx["petition"] = verify_showing(ctx["petition"]["id"], **(card_counts or {}))
    return ctx


def setup_election_set(ctx: Optional[dict] = None, route: str = "STIPULATED",
                       agreement_overrides: Optional[dict] = None,
                       fix_overrides: Optional[dict] = None, **soi_kwargs) -> dict:
    """Take the case to ELECTION_SET on the stipulated or the directed branch."""
    ctx = ctx or setup_soi_verified(**soi_kwargs)
    agreement = create_election_agreement(ctx["petition"]["id"], **(agreement_overrides or {}))
    if route == "STIPULATED":
        agreement = stipulate_agreement(agreement["id"], **(fix_overrides or {}))
    else:
        request_hearing(agreement["id"])
        agreement = direct_election(agreement["id"], **(fix_overrides or {}))
    ctx["agreement"] = agreement
    ctx["round"] = latest_round(ctx["petition"]["id"])
    ctx["petition"] = read_petition(ctx["petition"]["id"])
    return ctx


def setup_draft_voter_list(ctx: Optional[dict] = None, entry_count: int = 1,
                           incomplete_count: int = 0,
                           entry_overrides: Optional[dict] = None, **election_kwargs) -> dict:
    """A DRAFT voter list carrying ``entry_count`` complete entries."""
    ctx = ctx or setup_election_set(**election_kwargs)
    voter_list = create_voter_list(ctx["petition"]["id"], ctx["agreement"]["id"])
    classification_id = ctx["classifications"][0]["id"]
    entries = add_complete_entries(
        voter_list["id"], classification_id, entry_count, **(entry_overrides or {})
    )
    if incomplete_count:
        entries += add_incomplete_entries(voter_list["id"], classification_id, incomplete_count)
    ctx["voter_list"] = read_voter_list(voter_list["id"])
    ctx["entries"] = entries
    ctx["petition"] = read_petition(ctx["petition"]["id"])
    return ctx


def setup_submitted_voter_list(ctx: Optional[dict] = None, **list_kwargs) -> dict:
    """A filed list, graded, awaiting Board review."""
    ctx = ctx or setup_draft_voter_list(**list_kwargs)
    ctx["voter_list"] = submit_voter_list(ctx["voter_list"]["id"])
    return ctx


def setup_accepted_voter_list(ctx: Optional[dict] = None, **list_kwargs) -> dict:
    """A list the Board has accepted, which is what lets the polls open."""
    ctx = ctx or setup_submitted_voter_list(**list_kwargs)
    if ctx["voter_list"]["status"] == "DRAFT":
        ctx["voter_list"] = submit_voter_list(ctx["voter_list"]["id"])
    ctx["voter_list"] = review_voter_list(ctx["voter_list"]["id"], "ACCEPT")
    return ctx


def setup_deficient_voter_list(ctx: Optional[dict] = None, complete_count: int = 9,
                               incomplete_count: int = 1,
                               noted_defects: Optional[List[str]] = None,
                               **election_kwargs) -> dict:
    """A list returned for cure, with its grade-driven cure window open."""
    ctx = ctx or setup_draft_voter_list(
        entry_count=complete_count, incomplete_count=incomplete_count, **election_kwargs
    )
    ctx["voter_list"] = submit_voter_list(ctx["voter_list"]["id"])
    ctx["voter_list"] = review_voter_list(
        ctx["voter_list"]["id"], "RETURN_FOR_CURE",
        noted_defects if noted_defects is not None else ["MISSING_PERSONAL_EMAIL"],
    )
    return ctx


def setup_sessions_laid_out(ctx: Optional[dict] = None,
                            session_specs: Optional[List[dict]] = None,
                            **list_kwargs) -> dict:
    """Poll sessions laid out on a SCHEDULED round with an accepted list in place."""
    ctx = ctx or setup_accepted_voter_list(**list_kwargs)
    specs = [DEFAULT_SESSION_SPEC] if session_specs is None else session_specs
    ctx["sessions"] = [create_poll_session(ctx["round"]["id"], **spec) for spec in specs]
    ctx["round"] = read_round(ctx["round"]["id"])
    return ctx


def setup_polls_open(ctx: Optional[dict] = None, open_clock: Optional[str] = None,
                     **session_kwargs) -> dict:
    """Polls open on the round, with the logical clock at polls_open_at."""
    ctx = ctx or setup_sessions_laid_out(**session_kwargs)
    set_clock(open_clock or ctx["round"]["polls_open_at"])
    ctx["round"] = open_polls(ctx["round"]["id"])
    return ctx


def setup_polls_closed(ctx: Optional[dict] = None,
                       session_counts: Optional[List[dict]] = None,
                       close_clock: Optional[str] = None, **open_kwargs) -> dict:
    """Every session closed, so the round is POLLS_CLOSED and the case VOTING_CLOSED."""
    ctx = ctx or setup_polls_open(**open_kwargs)
    sessions = ctx["sessions"]
    counts = session_counts or [{"votes_for_count": 30, "votes_against_count": 25, "void_count": 1}]
    last_end = max(session["session_end_at"] for session in sessions)
    set_clock(close_clock or last_end)
    closed = []
    for index, session in enumerate(sessions):
        spec = counts[index] if index < len(counts) else counts[-1]
        closed.append(close_poll_session(session["id"], **spec))
    ctx["sessions"] = closed
    ctx["round"] = read_round(ctx["round"]["id"])
    ctx["petition"] = read_petition(ctx["petition"]["id"])
    return ctx


def setup_tally_posted(ctx: Optional[dict] = None, **closed_kwargs) -> dict:
    """Provisional tally posted, objection window open, case at TALLY_POSTED."""
    ctx = ctx or setup_polls_closed(**closed_kwargs)
    ctx["round"] = post_tally(ctx["round"]["id"])
    ctx["petition"] = read_petition(ctx["petition"]["id"])
    return ctx


def setup_tally_revised(ctx: Optional[dict] = None, **posted_kwargs) -> dict:
    """Revised tally issued on a round with no challenged ballot left open."""
    ctx = ctx or setup_tally_posted(**posted_kwargs)
    ctx["round"] = revise_tally(ctx["round"]["id"])
    return ctx


def setup_certification_ready(ctx: Optional[dict] = None,
                              certify_clock: str = "2026-09-15T09:00:00Z",
                              **revised_kwargs) -> dict:
    """A revised round whose objection window the logical clock has passed."""
    ctx = ctx or setup_tally_revised(**revised_kwargs)
    set_clock(certify_clock)
    ctx["clock"] = certify_clock
    return ctx


def setup_certified_case(ctx: Optional[dict] = None, **ready_kwargs) -> dict:
    """A case carried all the way to CERTIFIED on its revised tally."""
    ctx = ctx or setup_certification_ready(**ready_kwargs)
    ctx["petition"] = certify_petition(ctx["petition"]["id"], ctx["round"]["id"])
    ctx["round"] = read_round(ctx["round"]["id"])
    return ctx


def setup_rerun_directed(ctx: Optional[dict] = None,
                         alleged_affected_voter_count: int = 40,
                         **posted_kwargs) -> dict:
    """A sustained objection that set the round aside and directed a rerun."""
    ctx = ctx or setup_tally_posted(**posted_kwargs)
    objection = file_objection(
        ctx["round"]["id"], alleged_affected_voter_count=alleged_affected_voter_count
    )
    objection = rule_objection(
        objection["id"], disposition="SUSTAIN",
        disposition_rationale="Conduct affecting the results is established on this record.",
    )
    ctx["objection"] = objection
    ctx["round"] = read_round(ctx["round"]["id"])
    ctx["petition"] = read_petition(ctx["petition"]["id"])
    return ctx


def setup_blocked_case(ctx: Optional[dict] = None, charge_overrides: Optional[dict] = None,
                       **election_kwargs) -> dict:
    """A blocking charge docketed against a case whose polls have not closed."""
    ctx = ctx or setup_election_set(**election_kwargs)
    ctx["charge"] = docket_blocking_charge(
        ctx["petition"]["id"], **(charge_overrides or {})
    )
    ctx["petition"] = read_petition(ctx["petition"]["id"])
    if ctx.get("round"):
        ctx["round"] = read_round(ctx["round"]["id"])
    return ctx


def setup_impounded_case(ctx: Optional[dict] = None, charge_overrides: Optional[dict] = None,
                         **closed_kwargs) -> dict:
    """A blocking charge docketed once ballots are already cast."""
    ctx = ctx or setup_polls_closed(**closed_kwargs)
    ctx["charge"] = docket_blocking_charge(ctx["petition"]["id"], **(charge_overrides or {}))
    ctx["petition"] = read_petition(ctx["petition"]["id"])
    ctx["round"] = read_round(ctx["round"]["id"])
    return ctx


def setup_trained_presenter_message(ctx: Optional[dict] = None, channel: str = "SMALL_GROUP_MEETING",
                                    message_overrides: Optional[dict] = None,
                                    **election_kwargs) -> dict:
    """A meeting-channel draft whose presenting supervisor is TRAINED."""
    ctx = ctx or setup_election_set(**election_kwargs)
    supervisor = create_trained_supervisor(ctx["petition"]["id"])
    overrides = {"channel": channel, "presenter_supervisor_id": supervisor["id"]}
    overrides.update(message_overrides or {})
    ctx["supervisor"] = supervisor
    ctx["message"] = create_campaign_message(ctx["petition"]["id"], **overrides)
    return ctx


def setup_approved_message_on_case(ctx: Optional[dict] = None,
                                   message_overrides: Optional[dict] = None,
                                   accuracy_overrides: Optional[dict] = None,
                                   review_overrides: Optional[dict] = None,
                                   **election_kwargs) -> dict:
    """An APPROVED campaign message on a case whose election is already set."""
    ctx = ctx or setup_election_set(**election_kwargs)
    ctx["message"] = create_approved_message(
        ctx["petition"]["id"], message_overrides, review_overrides, accuracy_overrides
    )
    return ctx
