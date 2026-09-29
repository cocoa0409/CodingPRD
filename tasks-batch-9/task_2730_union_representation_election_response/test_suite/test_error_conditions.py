"""Refusals raised when a case is asked to move from the wrong state.

Every test here drives a case to a state the contract declares unfit for the next
act — a list still in draft, a charge already disposed of, a hearing whose scope
rulings are unfinished, a round whose tally has not been revised, a message whose
accuracy review predates the last legal review, an objection that could not have
changed the outcome, a blocking charge that a merit finding does not lift, and a
ballot naming a voter from a superseded list — and checks both the refusal and
the successful call that follows once the missing condition is supplied.
"""
from test_helpers import (
    BOARD,
    COUNSEL,
    DIRECTOR,
    UNION,
    ApiErrorId,
    accuracy_review,
    add_business_days,
    add_complete_entries,
    api_client,
    assert_absent,
    assert_instant_equals,
    certify_petition,
    create_campaign_message,
    create_challenged_ballot_payload,
    create_election_agreement,
    create_poll_session,
    create_voter_list,
    determine_charge,
    direct_election,
    direct_election_payload,
    docket_blocking_charge,
    docket_charge,
    file_objection,
    get_success_data,
    latest_round,
    open_polls,
    post_tally,
    read_campaign_message,
    read_petition,
    read_round,
    read_voter_list,
    request_hearing,
    resolve_ballot,
    review_message,
    review_voter_list,
    revise_tally,
    rule_classification,
    rule_objection,
    schedule_rerun,
    segregate_ballot,
    set_clock,
    settle_charge,
    setup_accepted_voter_list,
    setup_draft_voter_list,
    setup_election_set,
    setup_polls_open,
    setup_soi_verified,
    setup_tally_posted,
    submit_message_for_review,
    submit_voter_list,
    close_poll_session,
    validate_error,
    validate_success,
)

ATTESTATION_TITLE = "Director of Labor Relations"

CAFETERIA_SESSION = {
    "location_code": "PLANT_1_CAFETERIA",
    "session_start_at": "2026-09-01T08:00:00Z",
    "session_end_at": "2026-09-01T12:00:00Z",
    "method": "MANUAL",
}
BREAKROOM_SESSION = {
    "location_code": "PLANT_2_BREAKROOM",
    "session_start_at": "2026-09-01T08:00:00Z",
    "session_end_at": "2026-09-01T12:00:00Z",
    "method": "MANUAL",
}
TWO_SESSION_LAYOUT = [CAFETERIA_SESSION, BREAKROOM_SESSION]
TWO_SESSION_COUNTS = [
    {"votes_for_count": 30, "votes_against_count": 25, "void_count": 1},
    {"votes_for_count": 12, "votes_against_count": 14, "void_count": 0},
]

POLLS_CLOSE_CLOCK = "2026-09-01T12:00:00Z"
TALLY_CLOCK = "2026-09-02T12:00:00Z"
CERTIFY_CLOCK = "2026-09-15T09:00:00Z"

THREE_CLASSIFICATION_UNIT = [
    {
        "code": "PROD", "title": "Production Operator", "headcount": 60,
        "avg_hourly_wage_cents": 2400, "employer_position": "INCLUDE",
        "union_position": "INCLUDE", "supervision_overlap": 88, "skills_overlap": 90,
        "functional_integration": 92, "interchange_rate": 74, "work_conditions_overlap": 95,
    },
    {
        "code": "MAINT", "title": "Maintenance Technician", "headcount": 30,
        "avg_hourly_wage_cents": 2600, "employer_position": "INCLUDE",
        "union_position": "INCLUDE", "supervision_overlap": 80, "skills_overlap": 70,
        "functional_integration": 84, "interchange_rate": 60, "work_conditions_overlap": 88,
    },
    {
        "code": "QC", "title": "Quality Inspector", "headcount": 12,
        "avg_hourly_wage_cents": 2800, "employer_position": "EXCLUDE",
        "union_position": "INCLUDE", "supervision_overlap": 40, "skills_overlap": 35,
        "functional_integration": 45, "interchange_rate": 20, "work_conditions_overlap": 50,
    },
]
THREE_CLASSIFICATION_CARDS = {
    "submitted_card_count": 45,
    "duplicate_card_count": 3,
    "undated_card_count": 2,
    "stale_card_count": 2,
    "nonunit_card_count": 3,
}


def _read_charge(charge_id):
    return get_success_data(api_client.get_ulp_charge(charge_id, BOARD))


def _read_objection(objection_id):
    return get_success_data(api_client.get_objection(objection_id, BOARD))


def _read_agreement(agreement_id):
    return get_success_data(api_client.get_election_agreement(agreement_id, DIRECTOR))


def _hearing_awaiting_the_last_scope_ruling():
    """A hearing branch on a three-classification unit whose last ruling is missing."""
    ctx = setup_soi_verified(
        classification_specs=THREE_CLASSIFICATION_UNIT,
        rulings=["INCLUDED", "INCLUDED", None],
        card_counts=THREE_CLASSIFICATION_CARDS,
    )
    agreement = create_election_agreement(ctx["petition"]["id"], agreement_type="CONSENT")
    set_clock("2026-08-10T09:00:00Z")
    ctx["agreement"] = request_hearing(agreement["id"], "EMPLOYER")
    set_clock("2026-08-24T09:00:00Z")
    ctx["petition"] = read_petition(ctx["petition"]["id"])
    return ctx


def _case_with_a_posted_tally_and_resolved_challenges():
    """Two sessions closed, a tally posted, and all three challenged ballots resolved."""
    ctx = setup_polls_open(session_specs=TWO_SESSION_LAYOUT, entry_count=3)
    entries = ctx["entries"]
    sessions = ctx["sessions"]
    ballots = [
        segregate_ballot(sessions[0]["id"], voter_list_entry_id=entries[0]["id"]),
        segregate_ballot(sessions[0]["id"], voter_list_entry_id=entries[1]["id"]),
        segregate_ballot(sessions[1]["id"], voter_list_entry_id=entries[2]["id"]),
    ]
    set_clock(POLLS_CLOSE_CLOCK)
    for session, counts in zip(sessions, TWO_SESSION_COUNTS):
        close_poll_session(session["id"], **counts)
    set_clock(TALLY_CLOCK)
    ctx["round"] = post_tally(ctx["round"]["id"])
    resolve_ballot(ballots[0]["id"], resolution="COUNTED_FOR")
    resolve_ballot(ballots[1]["id"], resolution="COUNTED_FOR")
    resolve_ballot(ballots[2]["id"], resolution="VOIDED")
    ctx["ballots"] = ballots
    ctx["round"] = read_round(ctx["round"]["id"])
    ctx["petition"] = read_petition(ctx["petition"]["id"])
    return ctx


def _case_with_a_rerun_round_at_the_polls():
    """Round 1 set aside, a rerun scheduled, and a brand-new list accepted for it."""
    ctx = setup_tally_posted(
        session_specs=TWO_SESSION_LAYOUT,
        session_counts=TWO_SESSION_COUNTS,
        entry_count=1,
    )
    petition_id = ctx["petition"]["id"]
    ctx["first_round"] = ctx["round"]
    ctx["superseded_entry"] = ctx["entries"][0]
    ctx["superseded_list"] = ctx["voter_list"]
    set_clock("2026-09-03T09:00:00Z")
    objection = file_objection(ctx["first_round"]["id"], alleged_affected_voter_count=9)
    set_clock("2026-09-04T09:00:00Z")
    ctx["objection"] = rule_objection(
        objection["id"], disposition="SUSTAIN",
        disposition_rationale="Conduct affecting the results is established on this record.",
    )
    set_clock("2026-09-05T09:00:00Z")
    rerun_round = schedule_rerun(
        petition_id,
        rerun_election_date="2026-10-01",
        polls_open_at="2026-10-01T06:00:00Z",
        polls_close_at="2026-10-01T17:00:00Z",
    )
    set_clock("2026-09-20T09:00:00Z")
    fresh_list = create_voter_list(petition_id, ctx["agreement"]["id"])
    ctx["fresh_entries"] = add_complete_entries(
        fresh_list["id"], ctx["classifications"][0]["id"], 2
    )
    submit_voter_list(fresh_list["id"], late_submission_ack=True)
    set_clock("2026-09-21T09:00:00Z")
    ctx["voter_list"] = review_voter_list(fresh_list["id"], "ACCEPT")
    ctx["rerun_session"] = create_poll_session(
        rerun_round["id"],
        location_code="PLANT_1_CAFETERIA",
        session_start_at="2026-10-01T06:00:00Z",
        session_end_at="2026-10-01T17:00:00Z",
    )
    set_clock("2026-10-01T06:00:00Z")
    ctx["round"] = open_polls(rerun_round["id"])
    ctx["petition"] = read_petition(petition_id)
    return ctx


def test_a_draft_voter_list_cannot_be_reviewed():
    """The Board cannot dispose of a list the director has not filed yet, and the
    same list is reviewable only after it has been filed.

    PRD: "A disposition whose grade prerequisite is unmet, or a list not in `SUBMITTED`, is refused with `ERR_VOTER_LIST_STATUS_INVALID`."

    PRD: "On success the list moves to `SUBMITTED`, `submitted_at` is stamped with the logical clock, `submitted_by_user_id` records the attesting director's `X-User-ID`, and the title is stored."

    Design: Corner/errors/every_voter_list_action_checks_the_list_status_first
    """
    ctx = setup_draft_voter_list(entry_count=1)
    voter_list = ctx["voter_list"]
    assert voter_list["status"] == "DRAFT"

    response = api_client.review_voter_list(
        voter_list["id"], {"disposition": "ACCEPT"}, BOARD
    )
    validate_error(response, ApiErrorId.ERR_VOTER_LIST_STATUS_INVALID)

    untouched = read_voter_list(voter_list["id"])
    assert untouched["status"] == "DRAFT"
    assert_absent(untouched, "reviewed_at", "voter list")

    filed = submit_voter_list(voter_list["id"], attested_by_title=ATTESTATION_TITLE)
    assert filed["status"] == "SUBMITTED"
    assert_instant_equals(filed["submitted_at"], "2026-08-03T09:00:00Z", "submitted_at")
    assert filed["attested_by_title"] == ATTESTATION_TITLE


def test_a_draft_voter_list_cannot_be_resubmitted():
    """Resubmission is the cure path, so it is closed to a list that has never
    been filed at all.

    PRD: "Resubmission is only possible from `DEFICIENT`, only while the logical clock is at or before `cure_deadline_at` — later is `ERR_CURE_WINDOW_EXPIRED` — and only while `resubmission_count` is still below its ceiling of 2, since a third cure attempt is refused with `ERR_RESUBMISSION_LIMIT_EXCEEDED`."

    PRD: "the target row is in a state from which the requested transition is declared, else the state code for that resource type: `ERR_PETITION_STATUS_INVALID`, `ERR_CLASSIFICATION_ALREADY_RULED`, `ERR_AGREEMENT_STATUS_INVALID`, `ERR_VOTER_LIST_STATUS_INVALID`, `ERR_COMMUNICATION_STATUS_INVALID`, `ERR_ROUND_NOT_SCHEDULED`, `ERR_ROUND_STATUS_INVALID`, `ERR_POLL_SESSION_STATUS_INVALID`, `ERR_BALLOT_STATUS_INVALID`, `ERR_OBJECTION_ALREADY_RULED` or `ERR_CHARGE_STATUS_INVALID`, each HTTP 409."

    Design: Corner/errors/every_voter_list_action_checks_the_list_status_first
    """
    ctx = setup_draft_voter_list(entry_count=1)
    voter_list = ctx["voter_list"]

    response = api_client.resubmit_voter_list(
        voter_list["id"], {"attested_by_title": ATTESTATION_TITLE}, DIRECTOR
    )
    validate_error(response, ApiErrorId.ERR_VOTER_LIST_STATUS_INVALID)

    untouched = read_voter_list(voter_list["id"])
    assert untouched["status"] == "DRAFT"
    assert untouched["resubmission_count"] == 0
    assert_absent(untouched, "submitted_at", "voter list")


def test_a_filed_voter_list_cannot_be_resubmitted():
    """A list awaiting Board review has no open cure window, so the resubmission
    endpoint is closed to it as well.

    PRD: "Resubmission is only possible from `DEFICIENT`, only while the logical clock is at or before `cure_deadline_at` — later is `ERR_CURE_WINDOW_EXPIRED` — and only while `resubmission_count` is still below its ceiling of 2, since a third cure attempt is refused with `ERR_RESUBMISSION_LIMIT_EXCEEDED`."

    PRD: "the target row is in a state from which the requested transition is declared, else the state code for that resource type: `ERR_PETITION_STATUS_INVALID`, `ERR_CLASSIFICATION_ALREADY_RULED`, `ERR_AGREEMENT_STATUS_INVALID`, `ERR_VOTER_LIST_STATUS_INVALID`, `ERR_COMMUNICATION_STATUS_INVALID`, `ERR_ROUND_NOT_SCHEDULED`, `ERR_ROUND_STATUS_INVALID`, `ERR_POLL_SESSION_STATUS_INVALID`, `ERR_BALLOT_STATUS_INVALID`, `ERR_OBJECTION_ALREADY_RULED` or `ERR_CHARGE_STATUS_INVALID`, each HTTP 409."

    Design: Corner/errors/every_voter_list_action_checks_the_list_status_first
    """
    ctx = setup_draft_voter_list(entry_count=1)
    filed = submit_voter_list(ctx["voter_list"]["id"], attested_by_title=ATTESTATION_TITLE)
    assert filed["status"] == "SUBMITTED"

    response = api_client.resubmit_voter_list(
        filed["id"], {"attested_by_title": ATTESTATION_TITLE}, DIRECTOR
    )
    validate_error(response, ApiErrorId.ERR_VOTER_LIST_STATUS_INVALID)

    untouched = read_voter_list(filed["id"])
    assert untouched["status"] == "SUBMITTED"
    assert untouched["resubmission_count"] == 0
    assert_instant_equals(untouched["submitted_at"], filed["submitted_at"], "submitted_at")


def test_an_accepted_voter_list_cannot_be_filed_again():
    """Once the Board has accepted the list, filing it a second time is refused
    and none of its attestation fields move.

    PRD: "Submission is only possible from `DRAFT`, requires the case to be in `ELECTION_SET` with posture `OPEN`, and requires `total_entry_count` to be at least 1 — a list with no entries cannot be graded and the attempt fails with `ERR_VOTER_LIST_EMPTY` (HTTP 422)."

    PRD: "the target row is in a state from which the requested transition is declared, else the state code for that resource type: `ERR_PETITION_STATUS_INVALID`, `ERR_CLASSIFICATION_ALREADY_RULED`, `ERR_AGREEMENT_STATUS_INVALID`, `ERR_VOTER_LIST_STATUS_INVALID`, `ERR_COMMUNICATION_STATUS_INVALID`, `ERR_ROUND_NOT_SCHEDULED`, `ERR_ROUND_STATUS_INVALID`, `ERR_POLL_SESSION_STATUS_INVALID`, `ERR_BALLOT_STATUS_INVALID`, `ERR_OBJECTION_ALREADY_RULED` or `ERR_CHARGE_STATUS_INVALID`, each HTTP 409."

    Design: Corner/errors/every_voter_list_action_checks_the_list_status_first
    """
    ctx = setup_accepted_voter_list(entry_count=1)
    accepted = ctx["voter_list"]
    assert accepted["status"] == "ACCEPTED"

    response = api_client.submit_voter_list(
        accepted["id"], {"attested_by_title": ATTESTATION_TITLE}, DIRECTOR
    )
    validate_error(response, ApiErrorId.ERR_VOTER_LIST_STATUS_INVALID)

    untouched = read_voter_list(accepted["id"])
    assert untouched["status"] == "ACCEPTED"
    assert untouched["resubmission_count"] == 0
    assert_instant_equals(untouched["submitted_at"], accepted["submitted_at"], "submitted_at")


def _charge_on_a_verified_case(**overrides):
    """A docketed charge on an SOI_VERIFIED case, with the clock at the disposal date."""
    ctx = setup_soi_verified()
    set_clock("2026-08-10T09:00:00Z")
    overrides.setdefault("conduct_occurred_at", "2026-08-05T15:00:00Z")
    ctx["charge"] = docket_charge(ctx["petition"]["id"], **overrides)
    return ctx


def test_a_dismissed_charge_refuses_a_second_determination():
    """A charge the Board has already dismissed is closed to a further finding.

    PRD: "A determination of `DISMISS` stamps `determined_at`, moves the charge to the terminal `DISMISSED` state, and — when the charge had requested blocking — lowers `blocking_charge_count` by 1, potentially firing the unblock chain."

    PRD: "A charge that has already been determined or settled is refused with `ERR_CHARGE_STATUS_INVALID`."

    Design: Corner/errors/a_determined_or_settled_charge_refuses_further_dispositions
    """
    ctx = _charge_on_a_verified_case()
    charge = ctx["charge"]

    dismissed = determine_charge(charge["id"], determination="DISMISS")
    assert dismissed["status"] == "DISMISSED"
    assert_instant_equals(dismissed["determined_at"], "2026-08-10T09:00:00Z", "determined_at")

    response = api_client.determine_ulp_charge(
        charge["id"], {"determination": "MERIT", "remedy_code": "REINSTATEMENT"}, BOARD
    )
    validate_error(response, ApiErrorId.ERR_CHARGE_STATUS_INVALID)

    untouched = _read_charge(charge["id"])
    assert untouched["status"] == "DISMISSED"
    assert_absent(untouched, "remedy_code", "charge")


def test_a_dismissed_charge_cannot_be_settled():
    """Settlement runs from the two live charge states, so a dismissed charge is
    beyond settling too.

    PRD: "Settling is available to `EmploymentCounsel` or to a `BoardAgent` and works from `FILED` or from `MERIT_FOUND`."

    PRD: "A charge that has already been determined or settled is refused with `ERR_CHARGE_STATUS_INVALID`."

    Design: Corner/errors/a_determined_or_settled_charge_refuses_further_dispositions
    """
    ctx = _charge_on_a_verified_case()
    charge = ctx["charge"]
    determine_charge(charge["id"], determination="DISMISS")

    response = api_client.settle_ulp_charge(
        charge["id"], {"settlement_type": "NON_BOARD"}, COUNSEL
    )
    validate_error(response, ApiErrorId.ERR_CHARGE_STATUS_INVALID)

    untouched = _read_charge(charge["id"])
    assert untouched["status"] == "DISMISSED"
    assert_absent(untouched, "settled_at", "charge")
    assert_absent(untouched, "settlement_type", "charge")


def test_a_settled_charge_refuses_a_second_settlement():
    """A charge settled out of a merit finding is terminal, and settling it again
    changes nothing on the charge or on the case.

    PRD: "Settlement stamps `settled_at`, moves the charge to the terminal `SETTLED` state, lowers `blocking_charge_count` by 1 when the charge was a blocking one, and, when `notice_posting_days` is greater than 0, sets the case's `notice_posting_end_at` to `settled_at` plus that many days."

    PRD: "A charge that has already been determined or settled is refused with `ERR_CHARGE_STATUS_INVALID`."

    PRD: "A charge that does **not** request blocking simply sits on the record."

    Design: Corner/errors/a_determined_or_settled_charge_refuses_further_dispositions
    """
    ctx = _charge_on_a_verified_case()
    charge = ctx["charge"]

    merit = determine_charge(charge["id"], determination="MERIT", remedy_code="REINSTATEMENT")
    assert merit["status"] == "MERIT_FOUND"

    settled = settle_charge(charge["id"], settlement_type="FORMAL")
    assert settled["status"] == "SETTLED"
    assert_instant_equals(settled["settled_at"], "2026-08-10T09:00:00Z", "settled_at")

    response = api_client.settle_ulp_charge(
        charge["id"], {"settlement_type": "NON_BOARD"}, COUNSEL
    )
    validate_error(response, ApiErrorId.ERR_CHARGE_STATUS_INVALID)

    untouched = _read_charge(charge["id"])
    assert untouched["status"] == "SETTLED"
    assert untouched["settlement_type"] == "FORMAL"

    case = read_petition(ctx["petition"]["id"])
    assert case["case_posture"] == "OPEN"
    assert case["blocking_charge_count"] == 0
    assert_absent(case, "notice_posting_end_at", "petition")


def test_a_merit_determination_without_a_remedy_is_rejected():
    """A merit finding must name the remedy it orders, and the charge stays open
    until one is supplied.

    PRD: "A determination of `MERIT` requires a `remedy_code` — one of `NOTICE_POSTING`, `REINSTATEMENT`, `BARGAINING_ORDER` or `RERUN_ELECTION` — stamps `determined_at`, records the remedy, and moves the charge to `MERIT_FOUND`."

    PRD: "the body parses, every required field is present, every enumerated value is in range, integers are integers, community-of-interest factors lie between 0 and 100 inclusive, pagination is in range, and every datetime is ISO 8601 with a `Z` offset."

    Design: Corner/errors/a_determined_or_settled_charge_refuses_further_dispositions
    """
    ctx = _charge_on_a_verified_case()
    charge = ctx["charge"]

    response = api_client.determine_ulp_charge(charge["id"], {"determination": "MERIT"}, BOARD)
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST)

    untouched = _read_charge(charge["id"])
    assert untouched["status"] == "FILED"
    assert_absent(untouched, "determined_at", "charge")

    found = determine_charge(charge["id"], determination="MERIT", remedy_code="REINSTATEMENT")
    assert found["status"] == "MERIT_FOUND"
    assert found["remedy_code"] == "REINSTATEMENT"


def test_direction_is_refused_while_one_classification_is_still_pending():
    """A Decision and Direction of Election cannot issue while the hearing has
    left one classification unruled, and the arrangement stays untouched.

    PRD: "The direction is only available once the hearing has actually resolved scope: **every** classification on the case must have a `scope_ruling` other than `PENDING`, and if even one remains pending the request fails with `ERR_SCOPE_RULINGS_INCOMPLETE`."

    PRD: "The new arrangement begins with `status` `PROPOSED` and `route` `PENDING`, and its `approved_election_date`, `voting_method`, `polls_open_at`, `polls_close_at`, `hearing_requested_at`, `hearing_requested_by_party`, `decision_date` and `voter_list_due_at` are all still absent."

    Design: Corner/errors/an_election_cannot_be_directed_while_scope_is_unresolved
    """
    ctx = _hearing_awaiting_the_last_scope_ruling()
    agreement = ctx["agreement"]
    assert agreement["status"] == "HEARING_REQUESTED"
    assert ctx["classifications"][2]["scope_ruling"] == "PENDING"

    response = api_client.direct_election(
        agreement["id"], direct_election_payload(decision_date="2026-08-20"), BOARD
    )
    validate_error(response, ApiErrorId.ERR_SCOPE_RULINGS_INCOMPLETE)

    untouched = _read_agreement(agreement["id"])
    assert untouched["status"] == "HEARING_REQUESTED"
    assert untouched["route"] == "PENDING"
    assert_absent(untouched, "approved_election_date", "election agreement")
    assert_absent(untouched, "decision_date", "election agreement")
    assert_absent(untouched, "voter_list_due_at", "election agreement")
    assert read_petition(ctx["petition"]["id"])["case_status"] == "SOI_VERIFIED"


def test_direction_succeeds_once_every_classification_is_ruled():
    """With the last scope ruling in place the direction issues, and it anchors the
    list deadline on the decision date rather than on the recording instant.

    PRD: "The hearing branch resolves when a `BoardAgent` issues a Decision and Direction of Election, moving the arrangement from `HEARING_REQUESTED` to `DIRECTED`."

    PRD: "The direction is only available once the hearing has actually resolved scope: **every** classification on the case must have a `scope_ruling` other than `PENDING`, and if even one remains pending the request fails with `ERR_SCOPE_RULINGS_INCOMPLETE`."

    PRD: "Direction sets `route` to `DIRECTED` and computes `voter_list_due_at` as the end of the second business day after `decision_date`, which may be earlier or later than the instant the direction was actually recorded."

    PRD: "As on the stipulated branch, an election round with `round_number` 1 and `status` `SCHEDULED` is created, and the case moves to `ELECTION_SET` with its `version` incremented."

    Design: Corner/errors/an_election_cannot_be_directed_while_scope_is_unresolved
    """
    ctx = _hearing_awaiting_the_last_scope_ruling()
    rule_classification(
        ctx["classifications"][2]["id"], ruling="EXCLUDED",
        ruling_rationale="The inspectors do not share a community of interest with the core group.",
    )

    directed = direct_election(ctx["agreement"]["id"], decision_date="2026-08-20")
    assert directed["status"] == "DIRECTED"
    assert directed["route"] == "DIRECTED"
    assert directed["decision_date"] == "2026-08-20"
    assert_instant_equals(
        directed["voter_list_due_at"], add_business_days("2026-08-20", 2), "voter_list_due_at"
    )
    assert_instant_equals(
        directed["voter_list_due_at"], "2026-08-24T23:59:59Z", "voter_list_due_at"
    )

    assert read_petition(ctx["petition"]["id"])["case_status"] == "ELECTION_SET"
    first_round = latest_round(ctx["petition"]["id"])
    assert first_round["round_number"] == 1
    assert first_round["status"] == "SCHEDULED"


def test_certification_is_refused_while_the_round_is_only_tally_posted():
    """Every other certification condition is satisfied — no open challenge, a
    closed objection window, an open posture — yet the provisional tally alone
    cannot carry a certification.

    PRD: "The case must be in `TALLY_POSTED`, its `case_posture` must be `OPEN`, the named round's `status` must be `TALLY_REVISED` — a round that has not been revised is refused with `ERR_ROUND_NOT_REVISED` — the logical clock must be **strictly after** that round's `objection_window_close_at`, since certifying at or before the window's close is refused with `ERR_OBJECTION_WINDOW_OPEN`, `pending_objection_count` must be 0 or the attempt is refused with `ERR_PENDING_OBJECTIONS`, `blocking_charge_count` must be 0 or it is refused with `ERR_BLOCKING_CHARGE_PENDING`, and `notice_posting_end_at` must be either absent or at or before the logical clock, since a still-running settlement notice period is refused with `ERR_NOTICE_POSTING_ACTIVE`."

    Design: Corner/errors/certification_requires_the_named_round_to_be_revised
    """
    ctx = _case_with_a_posted_tally_and_resolved_challenges()
    petition_id = ctx["petition"]["id"]
    round_id = ctx["round"]["id"]
    assert ctx["round"]["status"] == "TALLY_POSTED"
    assert ctx["round"]["challenged_open_count"] == 0
    assert ctx["petition"]["case_status"] == "TALLY_POSTED"
    assert ctx["petition"]["case_posture"] == "OPEN"
    assert ctx["petition"]["pending_objection_count"] == 0
    set_clock(CERTIFY_CLOCK)

    response = api_client.certify_petition(
        petition_id, {"election_round_id": round_id}, BOARD
    )
    validate_error(response, ApiErrorId.ERR_ROUND_NOT_REVISED)

    case = read_petition(petition_id)
    assert case["case_status"] == "TALLY_POSTED"
    assert_absent(case, "certified_at", "petition")
    assert_absent(case, "certified_round_id", "petition")
    assert read_round(round_id)["status"] == "TALLY_POSTED"


def test_certification_issues_once_the_tally_has_been_revised():
    """Revising the tally supplies the one missing condition, and the certification
    then stamps the case and the round together.

    PRD: "`tally_revised_at` is stamped and the round moves to `TALLY_REVISED`."

    PRD: "The case must be in `TALLY_POSTED`, its `case_posture` must be `OPEN`, the named round's `status` must be `TALLY_REVISED` — a round that has not been revised is refused with `ERR_ROUND_NOT_REVISED` — the logical clock must be **strictly after** that round's `objection_window_close_at`, since certifying at or before the window's close is refused with `ERR_OBJECTION_WINDOW_OPEN`, `pending_objection_count` must be 0 or the attempt is refused with `ERR_PENDING_OBJECTIONS`, `blocking_charge_count` must be 0 or it is refused with `ERR_BLOCKING_CHARGE_PENDING`, and `notice_posting_end_at` must be either absent or at or before the logical clock, since a still-running settlement notice period is refused with `ERR_NOTICE_POSTING_ACTIVE`."

    PRD: "The certification itself stamps `certified_at` with the logical clock, records the named round in `certified_round_id`, moves the case to the terminal `CERTIFIED` status, and moves that round to the terminal `ROUND_CERTIFIED` status."

    Design: Corner/errors/certification_requires_the_named_round_to_be_revised
    """
    ctx = _case_with_a_posted_tally_and_resolved_challenges()
    petition_id = ctx["petition"]["id"]
    round_id = ctx["round"]["id"]
    set_clock(CERTIFY_CLOCK)

    revised = revise_tally(round_id)
    assert revised["status"] == "TALLY_REVISED"

    certified = certify_petition(petition_id, round_id)
    assert certified["case_status"] == "CERTIFIED"
    assert certified["certified_round_id"] == round_id
    assert_instant_equals(certified["certified_at"], CERTIFY_CLOCK, "certified_at")
    assert read_round(round_id)["status"] == "ROUND_CERTIFIED"


def test_a_message_without_an_accuracy_review_cannot_enter_legal_review():
    """A draft message may not reach counsel until the factual-accuracy review has
    been performed on it.

    PRD: "The message must have been accuracy-reviewed: `accuracy_reviewed_at` must hold a value, and if it does not the request fails with `ERR_ACCURACY_REVIEW_MISSING`."

    PRD: "Sending a message into legal review is the director's act and moves it from `DRAFT` — or from `REVISION_REQUIRED` — to `PENDING_LEGAL_REVIEW`."

    Design: Corner/errors/the_accuracy_review_must_be_fresher_than_the_last_legal_review
    """
    ctx = setup_election_set()
    set_clock("2026-08-21T09:00:00Z")
    message = create_campaign_message(
        ctx["petition"]["id"], channel="EMAIL", audience_scope="UNIT_WIDE"
    )
    assert message["status"] == "DRAFT"

    response = api_client.submit_communication_for_review(message["id"], DIRECTOR)
    validate_error(response, ApiErrorId.ERR_ACCURACY_REVIEW_MISSING)

    untouched = read_campaign_message(message["id"])
    assert untouched["status"] == "DRAFT"
    assert_absent(untouched, "accuracy_reviewed_at", "campaign communication")

    accuracy_review(message["id"])
    set_clock("2026-08-21T09:30:00Z")
    submitted = submit_message_for_review(message["id"])
    assert submitted["status"] == "PENDING_LEGAL_REVIEW"


def test_a_stale_accuracy_review_cannot_carry_a_message_back_into_review():
    """An edited message has to be re-reviewed for accuracy: the review that
    preceded counsel's revision request is too old to support resubmission.

    PRD: "A disposition of `REQUEST_REVISION` moves the message to `REVISION_REQUIRED`, increments `revision_round` and records the reviewer; it is refused with `ERR_REVISION_LIMIT_EXCEEDED` once `revision_round` has already reached 3."

    PRD: "When the message is coming back around from `REVISION_REQUIRED`, two further conditions apply: `revision_round` must still be below its ceiling of 3, and the accuracy review must be **fresh** — `accuracy_reviewed_at` must be at or after the instant of the last legal review, since an edited message has to be re-reviewed for accuracy before it can be re-submitted, and a stale review is again `ERR_ACCURACY_REVIEW_MISSING`."

    Design: Corner/errors/the_accuracy_review_must_be_fresher_than_the_last_legal_review
    """
    ctx = setup_election_set()
    set_clock("2026-08-21T09:00:00Z")
    message = create_campaign_message(
        ctx["petition"]["id"], channel="EMAIL", audience_scope="UNIT_WIDE"
    )
    accuracy_review(message["id"])
    set_clock("2026-08-21T09:30:00Z")
    submit_message_for_review(message["id"])

    set_clock("2026-08-21T10:00:00Z")
    returned = review_message(
        message["id"], disposition="REQUEST_REVISION",
        review_note="Soften the plant-closure language before this goes out.",
    )
    assert returned["status"] == "REVISION_REQUIRED"
    assert returned["revision_round"] == 1

    set_clock("2026-08-21T10:30:00Z")
    response = api_client.submit_communication_for_review(message["id"], DIRECTOR)
    validate_error(response, ApiErrorId.ERR_ACCURACY_REVIEW_MISSING)

    stale = read_campaign_message(message["id"])
    assert stale["status"] == "REVISION_REQUIRED"
    assert stale["revision_round"] == 1
    assert_instant_equals(
        stale["accuracy_reviewed_at"], "2026-08-21T09:00:00Z", "accuracy_reviewed_at"
    )

    set_clock("2026-08-21T11:00:00Z")
    accuracy_review(message["id"])
    resubmitted = submit_message_for_review(message["id"])
    assert resubmitted["status"] == "PENDING_LEGAL_REVIEW"
    assert resubmitted["revision_round"] == 1


def _objection_that_could_not_have_changed_the_outcome():
    """A posted tally with a margin of three, objected to on two affected voters."""
    ctx = setup_tally_posted(
        session_specs=TWO_SESSION_LAYOUT,
        session_counts=TWO_SESSION_COUNTS,
        entry_count=1,
    )
    set_clock("2026-09-03T09:00:00Z")
    ctx["objection"] = file_objection(
        ctx["round"]["id"], headers=UNION,
        filed_by_party="UNION",
        ground_code="CAPTIVE_AUDIENCE_TIMING",
        alleged_affected_voter_count=2,
    )
    ctx["petition"] = read_petition(ctx["petition"]["id"])
    return ctx


def test_a_non_determinative_objection_cannot_be_sustained():
    """Conduct reaching fewer voters than the margin could not have changed the
    outcome, so the Board may not set the election aside on it.

    PRD: "A new objection starts at `status` `FILED` with `rerun_directed` false and no `ruled_at` or `disposition_rationale`, and the system immediately computes `affects_results`: it is true exactly when `alleged_affected_voter_count` is greater than or equal to the absolute value of the objected round's `provisional_margin`."

    PRD: "An objection may only be sustained when `affects_results` is true — conduct that could not have changed the outcome may not set an election aside, and the attempt is refused with `ERR_OBJECTION_NOT_DETERMINATIVE` — and only while the objected round is `TALLY_POSTED` or `TALLY_REVISED`."

    PRD: "Filing raises the case's `pending_objection_count` by 1, and the first objection accepted against the current round moves `case_status` from `TALLY_POSTED` to `OBJECTIONS_PENDING`."

    Design: Corner/errors/a_non_determinative_objection_cannot_be_sustained
    """
    ctx = _objection_that_could_not_have_changed_the_outcome()
    objection = ctx["objection"]
    round_id = ctx["round"]["id"]
    assert objection["affects_results"] is False
    assert objection["status"] == "FILED"
    assert objection["rerun_directed"] is False

    response = api_client.rule_objection(
        objection["id"],
        {
            "disposition": "SUSTAIN",
            "disposition_rationale": "The union asks that the election be set aside.",
        },
        BOARD,
    )
    validate_error(response, ApiErrorId.ERR_OBJECTION_NOT_DETERMINATIVE)

    untouched = _read_objection(objection["id"])
    assert untouched["status"] == "FILED"
    assert untouched["rerun_directed"] is False
    assert_absent(untouched, "ruled_at", "objection")
    assert read_round(round_id)["status"] == "TALLY_POSTED"

    case = read_petition(ctx["petition"]["id"])
    assert case["case_status"] == "OBJECTIONS_PENDING"
    assert case["pending_objection_count"] == 1


def test_overruling_a_non_determinative_objection_returns_the_case_to_tally_posted():
    """The quiet path is the one open to a non-determinative objection, and it
    hands the case back for certification without directing a rerun.

    PRD: "A new objection starts at `status` `FILED` with `rerun_directed` false and no `ruled_at` or `disposition_rationale`, and the system immediately computes `affects_results`: it is true exactly when `alleged_affected_voter_count` is greater than or equal to the absolute value of the objected round's `provisional_margin`."

    PRD: "Overruling is the quiet path: it stamps `ruled_at` and the rationale, moves the objection to the terminal `OVERRULED` state, and lowers the case's `pending_objection_count` by 1."

    PRD: "When that count reaches 0 with no objection on the round having been sustained, the case returns from `OBJECTIONS_PENDING` to `TALLY_POSTED`, so certification may proceed."

    Design: Corner/errors/a_non_determinative_objection_cannot_be_sustained
    """
    ctx = _objection_that_could_not_have_changed_the_outcome()
    objection = ctx["objection"]
    round_id = ctx["round"]["id"]

    overruled = rule_objection(
        objection["id"], disposition="OVERRULE",
        disposition_rationale="The conduct alleged could not have affected the results.",
    )
    assert overruled["status"] == "OVERRULED"
    assert overruled["rerun_directed"] is False
    assert_instant_equals(overruled["ruled_at"], "2026-09-03T09:00:00Z", "ruled_at")

    case = read_petition(ctx["petition"]["id"])
    assert case["case_status"] == "TALLY_POSTED"
    assert case["pending_objection_count"] == 0
    assert read_round(round_id)["status"] == "TALLY_POSTED"


def _impounded_case_on_a_revised_tally():
    """A revised tally whose ballots a blocking charge has impounded."""
    ctx = _case_with_a_posted_tally_and_resolved_challenges()
    set_clock(CERTIFY_CLOCK)
    ctx["round"] = revise_tally(ctx["round"]["id"])
    ctx["charge"] = docket_blocking_charge(
        ctx["petition"]["id"],
        charging_party="UNION",
        charged_party="EMPLOYER",
        section_code="8A3",
    )
    ctx["petition"] = read_petition(ctx["petition"]["id"])
    ctx["round"] = read_round(ctx["round"]["id"])
    return ctx


def test_certification_is_refused_while_a_blocking_charge_impounds_the_ballots():
    """A blocking charge docketed once the ballots are counted impounds them, and
    the posture gate then closes certification.

    PRD: "A charge that **does** request blocking, docketed against a case whose `case_status` is neither `DISMISSED` nor `CERTIFIED`, raises the case's `blocking_charge_count` by 1 and changes the posture — and which posture it produces depends on how far the balloting has got."

    PRD: "If instead the highest-numbered round *is* in `POLLS_CLOSED`, `TALLY_POSTED` or `TALLY_REVISED` — ballots are already cast — the posture becomes `IMPOUNDED` and that round's `ballots_impounded` flag becomes true, which is what makes a subsequent tally posting fail."

    PRD: "The posture is written only by unfair labor practice charge activity, and its purpose is to act as a gate: while the posture is anything other than `OPEN`, every write that would advance the election is refused with `ERR_CASE_POSTURE_BLOCKED` (HTTP 409)."

    PRD: "Nine operations sit behind that gate: opening the polls, closing a poll session, posting a tally, revising a tally, submitting a voter list, reviewing a voter list, delivering a campaign communication, scheduling a rerun, and certifying the election."

    Design: Corner/errors/the_blocking_hold_survives_a_merit_finding_and_only_a_settlement_lifts_it
    """
    ctx = _impounded_case_on_a_revised_tally()
    petition_id = ctx["petition"]["id"]
    round_id = ctx["round"]["id"]
    assert ctx["petition"]["case_posture"] == "IMPOUNDED"
    assert ctx["petition"]["blocking_charge_count"] == 1
    assert ctx["round"]["ballots_impounded"] is True
    assert ctx["round"]["status"] == "TALLY_REVISED"

    response = api_client.certify_petition(
        petition_id, {"election_round_id": round_id}, BOARD
    )
    validate_error(response, ApiErrorId.ERR_CASE_POSTURE_BLOCKED)

    case = read_petition(petition_id)
    assert_absent(case, "certified_at", "petition")
    assert read_round(round_id)["status"] == "TALLY_REVISED"


def test_a_merit_finding_does_not_lift_the_blocking_hold():
    """Finding the charge meritorious disposes of the charge without releasing the
    case: certification is still refused on the posture.

    PRD: "A determination of `MERIT` requires a `remedy_code` — one of `NOTICE_POSTING`, `REINSTATEMENT`, `BARGAINING_ORDER` or `RERUN_ELECTION` — stamps `determined_at`, records the remedy, and moves the charge to `MERIT_FOUND`."

    PRD: "Critically, a merit finding does **not** lower `blocking_charge_count`: a meritorious blocking charge keeps the case `BLOCKED` or `IMPOUNDED` until it is settled."

    PRD: "When the remedy is `NOTICE_POSTING`, the case's `notice_posting_end_at` is set to `determined_at` plus `notice_posting_days` days."

    PRD: "The posture is written only by unfair labor practice charge activity, and its purpose is to act as a gate: while the posture is anything other than `OPEN`, every write that would advance the election is refused with `ERR_CASE_POSTURE_BLOCKED` (HTTP 409)."

    Design: Corner/errors/the_blocking_hold_survives_a_merit_finding_and_only_a_settlement_lifts_it
    """
    ctx = _impounded_case_on_a_revised_tally()
    petition_id = ctx["petition"]["id"]
    round_id = ctx["round"]["id"]

    found = determine_charge(
        ctx["charge"]["id"], determination="MERIT", remedy_code="REINSTATEMENT"
    )
    assert found["status"] == "MERIT_FOUND"
    assert found["remedy_code"] == "REINSTATEMENT"
    assert_instant_equals(found["determined_at"], CERTIFY_CLOCK, "determined_at")

    case = read_petition(petition_id)
    assert case["blocking_charge_count"] == 1
    assert case["case_posture"] == "IMPOUNDED"
    assert_absent(case, "notice_posting_end_at", "petition")
    assert read_round(round_id)["ballots_impounded"] is True

    response = api_client.certify_petition(
        petition_id, {"election_round_id": round_id}, BOARD
    )
    validate_error(response, ApiErrorId.ERR_CASE_POSTURE_BLOCKED)


def test_settling_the_blocking_charge_releases_the_hold_and_lets_certification_issue():
    """Only settlement takes the blocking count back to zero, which returns the
    posture to open, un-impounds the ballots and clears the way to certify.

    PRD: "Settlement stamps `settled_at`, moves the charge to the terminal `SETTLED` state, lowers `blocking_charge_count` by 1 when the charge was a blocking one, and, when `notice_posting_days` is greater than 0, sets the case's `notice_posting_end_at` to `settled_at` plus that many days."

    PRD: "The unblock chain runs whenever a dismissal or a settlement leaves `blocking_charge_count` at 0, and it is deliberately narrower than the block was."

    PRD: "When the posture had been `IMPOUNDED`, the impounded round's `ballots_impounded` flag returns to false."

    PRD: "The certification itself stamps `certified_at` with the logical clock, records the named round in `certified_round_id`, moves the case to the terminal `CERTIFIED` status, and moves that round to the terminal `ROUND_CERTIFIED` status."

    Design: Corner/errors/the_blocking_hold_survives_a_merit_finding_and_only_a_settlement_lifts_it
    """
    ctx = _impounded_case_on_a_revised_tally()
    petition_id = ctx["petition"]["id"]
    round_id = ctx["round"]["id"]
    determine_charge(ctx["charge"]["id"], determination="MERIT", remedy_code="REINSTATEMENT")

    settled = settle_charge(ctx["charge"]["id"], settlement_type="NON_BOARD")
    assert settled["status"] == "SETTLED"
    assert settled["settlement_type"] == "NON_BOARD"
    assert settled["remedy_code"] == "REINSTATEMENT"
    assert_absent(settled, "notice_posting_days", "charge")

    unblocked = read_petition(petition_id)
    assert unblocked["case_posture"] == "OPEN"
    assert unblocked["blocking_charge_count"] == 0
    assert read_round(round_id)["ballots_impounded"] is False

    certified = certify_petition(petition_id, round_id)
    assert certified["case_status"] == "CERTIFIED"
    assert certified["certified_round_id"] == round_id
    assert_instant_equals(certified["certified_at"], CERTIFY_CLOCK, "certified_at")
    assert read_round(round_id)["status"] == "ROUND_CERTIFIED"


def test_a_ballot_naming_a_superseded_list_entry_is_refused():
    """The rerun runs on a brand-new list, so a voter row from the set-aside
    round's list can no longer be named at the polls.

    PRD: "Fourth, two collections react to the case entering `RERUN_DIRECTED`: the voter list on the case whose `status` is `ACCEPTED` becomes `SUPERSEDED`, because a rerun requires a brand-new list, and every campaign communication whose `status` is `APPROVED` or `PENDING_LEGAL_REVIEW` becomes `BLOCKED` with `blocked_reason` set to `RERUN_BLACKOUT`."

    PRD: "When a `voter_list_entry_id` is supplied it must name an entry sitting on a voter list in `ACCEPTED` status for the same case as the session's round; otherwise the request is refused with `ERR_BALLOT_VOTER_NOT_ON_ACCEPTED_LIST`."

    PRD: "a challenged ballot naming a voter entry must name one that sits on an `ACCEPTED` voter list for the round's petition, else `ERR_BALLOT_VOTER_NOT_ON_ACCEPTED_LIST` (409)."

    Design: Corner/errors/a_ballot_may_only_name_an_entry_from_the_currently_accepted_list
    """
    ctx = _case_with_a_rerun_round_at_the_polls()
    assert read_voter_list(ctx["superseded_list"]["id"])["status"] == "SUPERSEDED"
    assert ctx["voter_list"]["status"] == "ACCEPTED"
    assert ctx["round"]["status"] == "POLLS_OPEN"

    response = api_client.create_challenged_ballot(
        create_challenged_ballot_payload(
            ctx["rerun_session"]["id"],
            voter_list_entry_id=ctx["superseded_entry"]["id"],
        ),
        BOARD,
    )
    validate_error(response, ApiErrorId.ERR_BALLOT_VOTER_NOT_ON_ACCEPTED_LIST)

    rerun_round = read_round(ctx["round"]["id"])
    assert rerun_round["challenged_open_count"] == ctx["round"]["challenged_open_count"]
    assert rerun_round["ballots_cast_total"] == ctx["round"]["ballots_cast_total"]


def test_a_ballot_naming_an_entry_on_the_new_accepted_list_is_segregated():
    """The same challenge succeeds when it names a voter from the list the Board
    accepted for the rerun round.

    PRD: "When a `voter_list_entry_id` is supplied it must name an entry sitting on a voter list in `ACCEPTED` status for the same case as the session's round; otherwise the request is refused with `ERR_BALLOT_VOTER_NOT_ON_ACCEPTED_LIST`."

    PRD: "A segregated ballot begins with `resolution` `OPEN`, `reopen_count` 0 and no `resolved_at`; it raises the session's `challenged_ballot_count` by 1, the round's `challenged_open_count` by 1, and the round's `ballots_cast_total` by 1, because a challenged ballot is a real ballot that entered the box."

    PRD: "The system creates the next election round with `round_number` one higher than the set-aside round's, with `prior_round_id` pointing at the set-aside round, and with `status` `SCHEDULED`; the case returns to `ELECTION_SET`, and the whole layout-polling-tally-objection arc runs again from the beginning, including the requirement for a newly built and newly accepted voter list."

    PRD: "Second, because the objection is sustained, the objected round moves to the terminal `SET_ASIDE` state; its provisional and revised tallies stay readable for the record but the round can never be certified."

    Design: Corner/errors/a_ballot_may_only_name_an_entry_from_the_currently_accepted_list
    """
    ctx = _case_with_a_rerun_round_at_the_polls()
    fresh_entry = ctx["fresh_entries"][0]
    open_before = ctx["round"]["challenged_open_count"]
    cast_before = ctx["round"]["ballots_cast_total"]

    response = api_client.create_challenged_ballot(
        create_challenged_ballot_payload(
            ctx["rerun_session"]["id"], voter_list_entry_id=fresh_entry["id"]
        ),
        BOARD,
    )
    ballot = validate_success(response, 201)
    assert ballot["resolution"] == "OPEN"
    assert ballot["voter_list_entry_id"] == fresh_entry["id"]
    assert ballot["reopen_count"] == 0

    rerun_round = read_round(ctx["round"]["id"])
    assert rerun_round["round_number"] == 2
    assert rerun_round["prior_round_id"] == ctx["first_round"]["id"]
    assert rerun_round["challenged_open_count"] == open_before + 1
    assert rerun_round["ballots_cast_total"] == cast_before + 1

    set_aside = read_round(ctx["first_round"]["id"])
    assert set_aside["status"] == "SET_ASIDE"
