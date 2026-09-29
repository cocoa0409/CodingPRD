"""Cycles in the case lifecycle and the multi-hop cascades that drive them.

Three of these behaviours are loops: the polling-tally-objection arc that runs a
second time after a sustained objection sends the case back to a scheduled
election, the eligible-voter list that heals itself by re-entering the filed
state from the cure state, and the campaign message that visits legal review
twice in one life. The rest are fan-outs: a single Board ruling or a single
docketed charge that settles four levels of consequence inside one request,
touching rounds, poll sessions, voter lists, classifications, election
arrangements and campaign messages that the request never named.
"""
import pytest

from test_helpers import (
    ANALYST,
    BOARD,
    COUNSEL,
    DIRECTOR,
    TRAINER,
    UNION,
    ApiErrorId,
    accuracy_review,
    add_classification,
    add_voter_entry,
    api_client,
    assert_absent,
    assert_ballot_conservation,
    assert_campaign_communication,
    assert_election_round,
    assert_headcount_conservation,
    assert_instant_equals,
    assert_objection,
    assert_petition,
    assert_poll_session,
    assert_supervisor,
    assert_ulp_charge,
    assert_voter_list,
    close_poll_session,
    create_campaign_message,
    create_election_agreement,
    create_petition,
    create_poll_session,
    create_voter_list,
    file_objection,
    latest_round,
    make_counsel_headers,
    make_director_headers,
    open_polls,
    open_scope_analysis,
    plus_hours,
    post_tally,
    read_campaign_message,
    read_petition,
    read_poll_session,
    read_round,
    read_voter_list,
    register_supervisor,
    review_message,
    review_voter_list,
    rounds_for_petition,
    rule_classification,
    score_classification,
    segregate_ballot,
    set_clock,
    stipulate_agreement,
    submit_message_for_review,
    submit_voter_list,
    train_supervisor,
    validate_error,
    validate_success,
    verify_showing,
)

# The drafting director and the reviewing counsel are different users, which is
# what the segregation-of-duties rule on a legal review disposition requires.
AUTHOR = make_director_headers("u_dir_1")
REVIEWER = make_counsel_headers("u_counsel_1")

DOCKET_CLOCK = "2026-08-03T09:00:00Z"
STIPULATION_CLOCK = "2026-08-20T15:00:00Z"
LIST_FILING_CLOCK = "2026-08-21T10:00:00Z"
POLLS_OPEN_AT = "2026-09-01T06:00:00Z"
POLLS_CLOSE_AT = "2026-09-01T17:00:00Z"
POLLS_CLOSED_CLOCK = "2026-09-01T17:30:00Z"
TALLY_CLOCK = "2026-09-02T12:00:00Z"

PROD_SPEC = {
    "code": "PROD", "title": "Production Operator", "headcount": 60,
    "avg_hourly_wage_cents": 2400, "shift_code": "A", "work_location": "PLANT_1",
    "supervisory_authority_count": 0, "employer_position": "INCLUDE",
    "union_position": "INCLUDE", "supervision_overlap": 88, "skills_overlap": 90,
    "functional_integration": 92, "interchange_rate": 74, "work_conditions_overlap": 95,
}
MAINT_SPEC = {
    "code": "MAINT", "title": "Maintenance Mechanic", "headcount": 30,
    "avg_hourly_wage_cents": 3200, "shift_code": "A", "work_location": "PLANT_1",
    "supervisory_authority_count": 0, "employer_position": "INCLUDE",
    "union_position": "INCLUDE", "supervision_overlap": 82, "skills_overlap": 78,
    "functional_integration": 86, "interchange_rate": 61, "work_conditions_overlap": 84,
}
QC_SPEC = {
    "code": "QC", "title": "Quality Inspector", "headcount": 12,
    "avg_hourly_wage_cents": 2900, "shift_code": "B", "work_location": "PLANT_1_LAB",
    "supervisory_authority_count": 0, "employer_position": "EXCLUDE",
    "union_position": "INCLUDE", "supervision_overlap": 41, "skills_overlap": 55,
    "functional_integration": 61, "interchange_rate": 21, "work_conditions_overlap": 71,
}
LEAD_SPEC = {
    "code": "LEAD", "title": "Lead Operator", "headcount": 8,
    "avg_hourly_wage_cents": 2800, "shift_code": "A", "work_location": "PLANT_1",
    "supervisory_authority_count": 4, "employer_position": "EXCLUDE",
    "union_position": "INCLUDE", "supervision_overlap": 78, "skills_overlap": 82,
    "functional_integration": 80, "interchange_rate": 66, "work_conditions_overlap": 88,
}

# 40 submitted cards less 3 duplicate, 2 undated, 2 stale and 3 non-unit cards.
THIRTY_VALID_CARDS = {
    "submitted_card_count": 40, "duplicate_card_count": 3, "undated_card_count": 2,
    "stale_card_count": 2, "nonunit_card_count": 3,
}
# 45 submitted cards less 4 duplicate, 3 undated, 2 stale and 2 non-unit cards.
THIRTY_FOUR_VALID_CARDS = {
    "submitted_card_count": 45, "duplicate_card_count": 4, "undated_card_count": 3,
    "stale_card_count": 2, "nonunit_card_count": 2,
}
# 40 submitted cards less 3 duplicate, 2 undated and 2 stale cards.
THIRTY_THREE_VALID_CARDS = {
    "submitted_card_count": 40, "duplicate_card_count": 3, "undated_card_count": 2,
    "stale_card_count": 2, "nonunit_card_count": 0,
}

VOTER_A = {
    "full_name": "Ana Ruiz", "hire_date": "2024-03-11",
    "home_address": "12 Elm St, Flint MI",
    "personal_email": "ana@example.com", "personal_phone": "555-0101",
}
VOTER_B = {
    "full_name": "Ben Okafor", "hire_date": "2023-07-02",
    "home_address": "44 Oak Ave, Flint MI",
    "personal_email": "ben@example.com", "personal_phone": "555-0102",
}
VOTER_C = {
    "full_name": "Cara Lindqvist", "hire_date": "2022-11-28",
    "home_address": "9 Pine Rd, Flint MI",
    "personal_email": "cara@example.com", "personal_phone": "555-0103",
}
# Dov's row is missing both statutory contact fields, so it does not count as complete.
VOTER_D_UNCURED = {
    "full_name": "Dov Perlman", "hire_date": "2021-05-04",
    "home_address": "77 Birch Ln, Flint MI",
    "personal_email": None, "personal_phone": None,
}

CONDUCT_OBJECTION = {
    "filed_by_party": "UNION",
    "ground_code": "PROHIBITED_SUPERVISOR_CONDUCT",
    "conduct_occurred_at": "2026-08-28T14:00:00Z",
    "alleged_affected_voter_count": 5,
    "description": "Shift supervisor interrogated five voters about card signing",
}
SUSTAIN_RATIONALE = "Conduct could reasonably have affected a margin of three"
OVERRULE_RATIONALE = "The conduct alleged could not have affected a margin of three"


def _ruled_unit_case(specs=(PROD_SPEC, MAINT_SPEC), rulings=("INCLUDED", "INCLUDED"),
                     cards=None, clock=DOCKET_CLOCK):
    """Docket a case, rule the named classifications and verify the showing of interest."""
    set_clock(clock)
    petition = create_petition()
    open_scope_analysis(petition["id"])
    classifications = []
    for spec, ruling in zip(specs, rulings):
        row = add_classification(petition["id"], **spec)
        if ruling is not None:
            score_classification(row["id"], "TRADITIONAL", COUNSEL)
            row = rule_classification(row["id"], ruling, "Community of interest with the core group")
        classifications.append(row)
    petition = verify_showing(petition["id"], **(cards or THIRTY_VALID_CARDS))
    return petition, classifications


def _stipulated_election(petition_id):
    """Agree the election on the record, which schedules round 1 and sets the list deadline."""
    agreement = create_election_agreement(
        petition_id, proposed_election_date="2026-09-01", proposed_voting_method="MANUAL"
    )
    set_clock(STIPULATION_CLOCK)
    agreement = stipulate_agreement(
        agreement["id"], approved_election_date="2026-09-01", voting_method="MANUAL",
        polls_open_at=POLLS_OPEN_AT, polls_close_at=POLLS_CLOSE_AT,
    )
    return agreement, latest_round(petition_id)


def _list_with_entries(petition_id, agreement_id, entry_specs):
    """Open a list and populate it, leaving it in DRAFT."""
    voter_list = create_voter_list(petition_id, agreement_id)
    entries = [
        add_voter_entry(voter_list["id"], classification_id, **fields)
        for classification_id, fields in entry_specs
    ]
    return voter_list, entries


def _accepted_voter_list(petition_id, agreement_id, classifications):
    """A complete three-voter list, filed on time and accepted by the Board."""
    prod_id, maint_id = classifications[0]["id"], classifications[1]["id"]
    voter_list, entries = _list_with_entries(petition_id, agreement_id, [
        (prod_id, VOTER_A), (prod_id, VOTER_B), (maint_id, VOTER_C),
    ])
    set_clock(LIST_FILING_CLOCK)
    submit_voter_list(voter_list["id"])
    voter_list = review_voter_list(voter_list["id"], "ACCEPT")
    return voter_list, entries


def _approved_email_message(petition_id, summary="How collective bargaining works at this plant",
                            audience_scope="UNIT_WIDE", material_claim_count=3,
                            unsupported_material_claim_count=0):
    """Draft, accuracy-review, submit and approve one plain email message."""
    message = create_campaign_message(
        petition_id, AUTHOR, channel="EMAIL", audience_scope=audience_scope,
        planned_delivery_at="2026-08-24T13:00:00Z", message_summary=summary,
        threat_statement_count=0, contains_interrogation=False,
        contains_promise_of_benefit=False, contains_surveillance_reference=False,
        material_claim_count=material_claim_count,
        unsupported_material_claim_count=unsupported_material_claim_count,
    )
    accuracy_review(
        message["id"], ANALYST, material_claim_count=material_claim_count,
        unsupported_material_claim_count=unsupported_material_claim_count,
    )
    submit_message_for_review(message["id"], AUTHOR)
    return review_message(message["id"], "APPROVE", headers=REVIEWER)


def _first_election_through_tally(with_challenged_ballots=False, with_approved_message=False):
    """Run one full election arc up to a posted provisional tally of 42 for, 39 against, 1 void."""
    petition, classifications = _ruled_unit_case()
    message = _approved_email_message(petition["id"]) if with_approved_message else None
    agreement, first_round = _stipulated_election(petition["id"])
    voter_list, entries = _accepted_voter_list(
        petition["id"], agreement["id"], classifications
    )
    session = create_poll_session(
        first_round["id"], location_code="PLANT_1_CAFETERIA",
        session_start_at=POLLS_OPEN_AT, session_end_at=POLLS_CLOSE_AT, method="MANUAL",
    )
    set_clock(POLLS_OPEN_AT)
    open_polls(first_round["id"])
    if with_challenged_ballots:
        segregate_ballot(session["id"], voter_list_entry_id=entries[0]["id"],
                         challenger_party="EMPLOYER", basis="SUPERVISOR")
        segregate_ballot(session["id"], voter_list_entry_id=entries[1]["id"],
                         challenger_party="UNION", basis="NOT_ON_LIST")
        segregate_ballot(session["id"], voter_list_entry_id=entries[2]["id"],
                         challenger_party="EMPLOYER", basis="OUTSIDE_UNIT")
    set_clock(POLLS_CLOSED_CLOCK)
    close_poll_session(session["id"], votes_for_count=42, votes_against_count=39, void_count=1)
    set_clock(TALLY_CLOCK)
    post_tally(first_round["id"])
    return {
        "petition": petition, "classifications": classifications, "agreement": agreement,
        "first_round": first_round, "voter_list": voter_list, "entries": entries,
        "session": session, "message": message,
    }


# --------------------------------------------------------------------------
# The case comes back round to a scheduled election
# --------------------------------------------------------------------------
def test_sustained_objection_and_rerun_return_the_case_to_election_set():
    """A case that has already voted, tallied and been objected to re-enters the
    scheduled-election state instead of stopping at the tally.

    PRD: "The lifecycle is not a straight line: `TALLY_POSTED` may move to
    `OBJECTIONS_PENDING` and back again, and a sustained objection sends the case
    through `RERUN_DIRECTED` back to `ELECTION_SET`, so the whole
    polling-tally-objection arc can run more than once on one case."
    PRD: "Third, because the round has been set aside, the case's `case_status`
    becomes `RERUN_DIRECTED` and its `pending_objection_count` is reset to 0."

    Design: Difficulty/non_linear_state_machine/petition_rerun_cycle_reenters_election_set
    """
    ctx = _first_election_through_tally(with_challenged_ballots=True)
    petition_id = ctx["petition"]["id"]
    first_round_id = ctx["first_round"]["id"]

    objection = file_objection(first_round_id, UNION, **CONDUCT_OBJECTION)
    assert read_petition(petition_id)["case_status"] == "OBJECTIONS_PENDING", (
        "filing an objection on a posted tally moves the case to OBJECTIONS_PENDING"
    )

    ruled = validate_success(api_client.rule_objection(
        objection["id"],
        {"disposition": "SUSTAIN", "disposition_rationale": SUSTAIN_RATIONALE},
        BOARD,
    ))
    assert_objection(ruled)
    assert ruled["status"] == "SUSTAINED", (
        f"a sustained objection reaches the terminal SUSTAINED state, got {ruled['status']}"
    )
    assert ruled["rerun_directed"] is True, (
        "sustaining an objection directs a rerun, expected rerun_directed true"
    )

    directed = read_petition(petition_id)
    assert directed["case_status"] == "RERUN_DIRECTED", (
        f"the set-aside round sends the case to RERUN_DIRECTED, got {directed['case_status']}"
    )
    assert directed["pending_objection_count"] == 0, (
        "sustaining resets the pending objection counter to 0, got "
        f"{directed['pending_objection_count']}"
    )

    validate_success(api_client.schedule_rerun(petition_id, {
        "rerun_election_date": "2026-10-06", "voting_method": "MANUAL",
        "polls_open_at": "2026-10-06T06:00:00Z", "polls_close_at": "2026-10-06T17:00:00Z",
    }, BOARD), 201)

    cycled = read_petition(petition_id)
    assert cycled["case_status"] == "ELECTION_SET", (
        "scheduling the rerun returns the case to ELECTION_SET a second time, got "
        f"{cycled['case_status']}"
    )
    assert read_round(first_round_id)["status"] == "SET_ASIDE", (
        "the objected round stays terminally set aside once the case cycles"
    )


def test_the_rerun_round_is_numbered_two_and_points_back_at_the_set_aside_round():
    """The second election round carries the next round number and names the round it
    replaces, while the set-aside round keeps its tally for the record.

    PRD: "The system creates the next election round with `round_number` one higher
    than the set-aside round's, with `prior_round_id` pointing at the set-aside round,
    and with `status` `SCHEDULED`; the case returns to `ELECTION_SET`, and the whole
    layout-polling-tally-objection arc runs again from the beginning, including the
    requirement for a newly built and newly accepted voter list."
    PRD: "Second, because the objection is sustained, the objected round moves to the
    terminal `SET_ASIDE` state; its provisional and revised tallies stay readable for
    the record but the round can never be certified."

    Design: Difficulty/non_linear_state_machine/petition_rerun_cycle_reenters_election_set
    """
    ctx = _first_election_through_tally(with_challenged_ballots=True)
    petition_id = ctx["petition"]["id"]
    first_round_id = ctx["first_round"]["id"]

    objection = file_objection(first_round_id, UNION, **CONDUCT_OBJECTION)
    validate_success(api_client.rule_objection(
        objection["id"],
        {"disposition": "SUSTAIN", "disposition_rationale": SUSTAIN_RATIONALE},
        BOARD,
    ))

    rerun_round = validate_success(api_client.schedule_rerun(petition_id, {
        "rerun_election_date": "2026-10-06", "voting_method": "MANUAL",
        "polls_open_at": "2026-10-06T06:00:00Z", "polls_close_at": "2026-10-06T17:00:00Z",
    }, BOARD), 201)
    assert_election_round(rerun_round)
    assert rerun_round["round_number"] == 2, (
        f"the rerun is round 2, got {rerun_round['round_number']}"
    )
    assert rerun_round["prior_round_id"] == first_round_id, (
        "the rerun round must point back at the set-aside round, got "
        f"{rerun_round['prior_round_id']}"
    )
    assert rerun_round["status"] == "SCHEDULED", (
        f"a freshly minted rerun round is SCHEDULED, got {rerun_round['status']}"
    )

    set_aside = read_round(first_round_id)
    assert set_aside["status"] == "SET_ASIDE", (
        f"the first round stays SET_ASIDE, got {set_aside['status']}"
    )
    assert set_aside["provisional_votes_for"] == 42, (
        "the set-aside round keeps its provisional tally readable, expected 42 for, got "
        f"{set_aside['provisional_votes_for']}"
    )
    assert_ballot_conservation(set_aside)
    assert len(rounds_for_petition(petition_id)) == 2, (
        "the case now holds two rounds, the set-aside first and the scheduled rerun"
    )


# --------------------------------------------------------------------------
# The eligible voter list heals itself inside the cure window
# --------------------------------------------------------------------------
CURE_REVIEW_CLOCK = "2026-08-21T18:00:00Z"
CURE_WORK_CLOCK = "2026-08-22T09:00:00Z"


def _list_returned_for_cure():
    """A four-voter list, one row short of complete, filed on time and sent back to cure."""
    petition, classifications = _ruled_unit_case()
    agreement, _round = _stipulated_election(petition["id"])
    prod_id, maint_id = classifications[0]["id"], classifications[1]["id"]
    voter_list, entries = _list_with_entries(petition["id"], agreement["id"], [
        (prod_id, VOTER_A), (prod_id, VOTER_B), (maint_id, VOTER_C),
        (maint_id, VOTER_D_UNCURED),
    ])
    set_clock(LIST_FILING_CLOCK)
    submitted = submit_voter_list(voter_list["id"])
    set_clock(CURE_REVIEW_CLOCK)
    returned = review_voter_list(
        voter_list["id"], "RETURN_FOR_CURE", ["MISSING_EMAIL", "MISSING_PHONE"]
    )
    return {
        "petition": petition, "agreement": agreement, "voter_list": voter_list,
        "entries": entries, "submitted": submitted, "returned": returned,
    }


def test_cured_voter_list_re_enters_submitted_with_a_compliant_grade():
    """A deficient list that has had its missing contact details filled in comes back
    into the filed state, regraded upward, with the resubmission counted.

    PRD: "A successful resubmission increments `resubmission_count`, re-stamps
    `submitted_at`, returns the list to `SUBMITTED`, and re-grades `completeness_pct`,
    `is_late` and `list_grade` from the entry rows as they now stand — so curing entries
    between the review and the resubmission genuinely improves the grade, while the
    lateness test is applied afresh against the original `due_at`."
    PRD: "The base tier follows from the rounded percentage: exactly 100.00 is
    `COMPLIANT`, at least 90.00 is `MINOR_DEFECT`, at least 75.00 is `MATERIAL_DEFECT`,
    and anything below 75.00 is `GROSSLY_DEFICIENT`."

    Design: Difficulty/non_linear_state_machine/voter_list_cure_cycle_returns_to_submitted
    """
    ctx = _list_returned_for_cure()
    voter_list_id = ctx["voter_list"]["id"]
    assert ctx["submitted"]["list_grade"] == "MATERIAL_DEFECT", (
        "three of four complete entries is 75.00 per cent, a material defect, got "
        f"{ctx['submitted']['list_grade']}"
    )
    assert ctx["returned"]["status"] == "DEFICIENT", (
        f"a returned list waits in DEFICIENT, got {ctx['returned']['status']}"
    )

    set_clock(CURE_WORK_CLOCK)
    validate_success(api_client.update_voter_list_entry(
        ctx["entries"][3]["id"],
        {"personal_email": "dov@example.com", "personal_phone": "555-0104"},
        ANALYST,
    ))

    resubmitted = validate_success(api_client.resubmit_voter_list(
        voter_list_id, {"attested_by_title": "Director of Labor Relations"}, DIRECTOR
    ))
    assert_voter_list(resubmitted)
    assert resubmitted["status"] == "SUBMITTED", (
        f"the cured list re-enters SUBMITTED from DEFICIENT, got {resubmitted['status']}"
    )
    assert resubmitted["resubmission_count"] == 1, (
        f"the first resubmission counts as 1, got {resubmitted['resubmission_count']}"
    )
    assert resubmitted["completeness_pct"] == pytest.approx(100.00, abs=0.005), (
        "all four rows now carry every statutory content field, expected 100.00, got "
        f"{resubmitted['completeness_pct']}"
    )
    assert resubmitted["list_grade"] == "COMPLIANT", (
        f"a fully complete list grades COMPLIANT, got {resubmitted['list_grade']}"
    )
    assert resubmitted["is_late"] is False, (
        "the cured list was refiled well before the deadline, expected is_late false"
    )
    assert_instant_equals(
        resubmitted["submitted_at"], CURE_WORK_CLOCK, "voter_list.submitted_at"
    )
    assert_instant_equals(
        resubmitted["cure_deadline_at"], plus_hours(CURE_REVIEW_CLOCK, 24),
        "voter_list.cure_deadline_at",
    )


def test_resubmitting_an_uncured_list_counts_the_attempt_and_regrades_to_the_same_defect():
    """Refiling without touching the entries still consumes a cure attempt, and the
    regrade reads the rows exactly as they stand rather than assuming an improvement.

    PRD: "A successful resubmission increments `resubmission_count`, re-stamps
    `submitted_at`, returns the list to `SUBMITTED`, and re-grades `completeness_pct`,
    `is_late` and `list_grade` from the entry rows as they now stand — so curing entries
    between the review and the resubmission genuinely improves the grade, while the
    lateness test is applied afresh against the original `due_at`."
    PRD: "`completeness_pct` is `complete_entry_count` multiplied by 100, divided by
    `total_entry_count`, rounded half-up to two decimals — where the complete-entry count
    is the number of entries whose `is_statutory_content_complete` is true."

    Design: Difficulty/non_linear_state_machine/voter_list_cure_cycle_returns_to_submitted
    """
    ctx = _list_returned_for_cure()

    set_clock(CURE_WORK_CLOCK)
    resubmitted = validate_success(api_client.resubmit_voter_list(
        ctx["voter_list"]["id"], {"attested_by_title": "Director of Labor Relations"},
        DIRECTOR,
    ))
    assert resubmitted["status"] == "SUBMITTED", (
        f"the loop back to SUBMITTED does not depend on any cure, got {resubmitted['status']}"
    )
    assert resubmitted["resubmission_count"] == 1, (
        f"the attempt is spent either way, expected 1, got {resubmitted['resubmission_count']}"
    )
    assert resubmitted["completeness_pct"] == pytest.approx(75.00, abs=0.005), (
        "three complete rows out of four is still 75.00 per cent, got "
        f"{resubmitted['completeness_pct']}"
    )
    assert resubmitted["list_grade"] == "MATERIAL_DEFECT", (
        f"an unimproved list regrades to MATERIAL_DEFECT, got {resubmitted['list_grade']}"
    )
    assert resubmitted["is_late"] is False, (
        "the deadline test is applied afresh against the original due_at, expected false"
    )
    assert_instant_equals(
        resubmitted["submitted_at"], CURE_WORK_CLOCK, "voter_list.submitted_at"
    )


# --------------------------------------------------------------------------
# A campaign message visits legal review twice
# --------------------------------------------------------------------------
DRAFTING_CLOCK = "2026-08-10T09:00:00Z"
REVISION_NOTE = "Soften the pension comparison and cite the plan document"


def _message_returned_for_revision(review_clock=None):
    """An email draft that counsel has sent back once for revision."""
    set_clock(DRAFTING_CLOCK)
    petition = create_petition()
    open_scope_analysis(petition["id"])
    message = create_campaign_message(
        petition["id"], AUTHOR, channel="EMAIL", audience_scope="UNIT_WIDE",
        planned_delivery_at="2026-08-24T13:00:00Z",
        message_summary="Facts about the pension plan under a collective agreement",
        threat_statement_count=0, contains_interrogation=False,
        contains_promise_of_benefit=False, contains_surveillance_reference=False,
        material_claim_count=4, unsupported_material_claim_count=1,
    )
    accuracy_review(message["id"], ANALYST, material_claim_count=4,
                    unsupported_material_claim_count=1)
    submit_message_for_review(message["id"], AUTHOR)
    if review_clock is not None:
        set_clock(review_clock)
    returned = review_message(
        message["id"], "REQUEST_REVISION", review_note=REVISION_NOTE, headers=REVIEWER
    )
    return petition, message, returned


def test_a_revised_message_returns_to_legal_review_and_is_approved_on_the_second_pass():
    """A message that counsel sent back once goes into legal review a second time and out
    the far side approved, with the revision counted and the two acting users recorded.

    PRD: "A disposition of `REQUEST_REVISION` moves the message to `REVISION_REQUIRED`,
    increments `revision_round` and records the reviewer; it is refused with
    `ERR_REVISION_LIMIT_EXCEEDED` once `revision_round` has already reached 3."
    PRD: "The revision loop therefore runs `DRAFT` to `PENDING_LEGAL_REVIEW` to
    `REVISION_REQUIRED` and back to `PENDING_LEGAL_REVIEW`, up to three completed rounds."
    PRD: "A disposition of `APPROVE` moves the message to `APPROVED` and records the
    acting user in `reviewed_by_user_id`; it additionally requires
    `peerless_plywood_violation` to be false and the escalation acknowledgement described
    above when the score is elevated."

    Design: Difficulty/non_linear_state_machine/campaign_message_revision_loop
    """
    _petition, message, returned = _message_returned_for_revision()
    assert returned["status"] == "REVISION_REQUIRED", (
        f"the first pass sends the message back, got {returned['status']}"
    )
    assert returned["revision_round"] == 1, (
        f"one completed revision round, got {returned['revision_round']}"
    )

    accuracy_review(message["id"], ANALYST, material_claim_count=4,
                    unsupported_material_claim_count=0)
    resubmitted = validate_success(
        api_client.submit_communication_for_review(message["id"], AUTHOR)
    )
    assert resubmitted["status"] == "PENDING_LEGAL_REVIEW", (
        "the message re-enters PENDING_LEGAL_REVIEW from REVISION_REQUIRED, got "
        f"{resubmitted['status']}"
    )
    assert resubmitted["revision_round"] == 1, (
        f"re-entering review changes no counter, expected 1, got {resubmitted['revision_round']}"
    )

    approved = validate_success(
        api_client.review_communication(message["id"], {"disposition": "APPROVE"}, REVIEWER)
    )
    assert_campaign_communication(approved)
    assert approved["status"] == "APPROVED", (
        f"the second review approves the message, got {approved['status']}"
    )
    assert approved["revision_round"] == 1, (
        "the revision counter is not reset by the loop, expected 1, got "
        f"{approved['revision_round']}"
    )
    assert approved["risk_score"] == 10, (
        "an email to the whole unit with one unsupported claim scores 5 plus 5, got "
        f"{approved['risk_score']}"
    )
    assert approved["reviewed_by_user_id"] == "u_counsel_1", (
        f"the approving counsel is recorded, got {approved['reviewed_by_user_id']}"
    )
    assert approved["authored_by_user_id"] == "u_dir_1", (
        f"the drafting director is unchanged by the loop, got {approved['authored_by_user_id']}"
    )


def test_a_message_may_not_re_enter_review_on_a_stale_accuracy_review():
    """Coming back around from revision needs a fresh accuracy review, so a message whose
    only review predates counsel's last look is refused and stays where it is.

    PRD: "When the message is coming back around from `REVISION_REQUIRED`, two further
    conditions apply: `revision_round` must still be below its ceiling of 3, and the
    accuracy review must be **fresh** — `accuracy_reviewed_at` must be at or after the
    instant of the last legal review, since an edited message has to be re-reviewed for
    accuracy before it can be re-submitted, and a stale review is again
    `ERR_ACCURACY_REVIEW_MISSING`."

    Design: Difficulty/non_linear_state_machine/campaign_message_revision_loop
    """
    _petition, message, returned = _message_returned_for_revision(
        review_clock="2026-08-10T11:00:00Z"
    )
    assert returned["status"] == "REVISION_REQUIRED", (
        f"counsel sent the message back, got {returned['status']}"
    )

    refused = api_client.submit_communication_for_review(message["id"], AUTHOR)
    validate_error(refused, ApiErrorId.ERR_ACCURACY_REVIEW_MISSING)

    stuck = read_campaign_message(message["id"], AUTHOR)
    assert stuck["status"] == "REVISION_REQUIRED", (
        f"the refused submission leaves the message in REVISION_REQUIRED, got {stuck['status']}"
    )
    assert stuck["revision_round"] == 1, (
        f"a refused submission increments nothing, expected 1, got {stuck['revision_round']}"
    )

    accuracy_review(message["id"], ANALYST, material_claim_count=4,
                    unsupported_material_claim_count=0)
    accepted = validate_success(
        api_client.submit_communication_for_review(message["id"], AUTHOR)
    )
    assert accepted["status"] == "PENDING_LEGAL_REVIEW", (
        "a fresh accuracy review reopens the loop, got " f"{accepted['status']}"
    )


# --------------------------------------------------------------------------
# One objection ruling settles four levels of consequence
# --------------------------------------------------------------------------
def test_sustaining_one_objection_supersedes_the_list_and_blocks_approved_messages():
    """A single sustain request walks the objection, the round, the case and then two
    collections nobody named in the request.

    PRD: "Sustaining is the loud path, and it fires a four-hop cascade inside the same
    request."
    PRD: "Fourth, two collections react to the case entering `RERUN_DIRECTED`: the voter
    list on the case whose `status` is `ACCEPTED` becomes `SUPERSEDED`, because a rerun
    requires a brand-new list, and every campaign communication whose `status` is
    `APPROVED` or `PENDING_LEGAL_REVIEW` becomes `BLOCKED` with `blocked_reason` set to
    `RERUN_BLACKOUT`."

    Design: Difficulty/transitive_cascade/objection_sustained_four_hop_cascade
    """
    ctx = _first_election_through_tally(with_approved_message=True)
    petition_id = ctx["petition"]["id"]
    first_round_id = ctx["first_round"]["id"]
    voter_list_id = ctx["voter_list"]["id"]
    message_id = ctx["message"]["id"]
    assert ctx["message"]["status"] == "APPROVED", (
        f"the campaign message starts out approved, got {ctx['message']['status']}"
    )

    objection = file_objection(first_round_id, UNION, **CONDUCT_OBJECTION)
    assert objection["affects_results"] is True, (
        "five alleged affected voters clears a margin of three, expected affects_results true"
    )

    ruled = validate_success(api_client.rule_objection(
        objection["id"],
        {"disposition": "SUSTAIN", "disposition_rationale": SUSTAIN_RATIONALE},
        BOARD,
    ))
    assert ruled["status"] == "SUSTAINED" and ruled["rerun_directed"] is True, (
        f"hop 1 writes the objection, got {ruled['status']} / {ruled['rerun_directed']}"
    )

    set_aside = read_round(first_round_id)
    assert set_aside["status"] == "SET_ASIDE", (
        f"hop 2 sets the objected round aside, got {set_aside['status']}"
    )
    assert set_aside["provisional_votes_for"] == 42, (
        "the set-aside round keeps its tally for the record, expected 42, got "
        f"{set_aside['provisional_votes_for']}"
    )

    cascaded = read_petition(petition_id)
    assert cascaded["case_status"] == "RERUN_DIRECTED", (
        f"hop 3 moves the case to RERUN_DIRECTED, got {cascaded['case_status']}"
    )
    assert cascaded["pending_objection_count"] == 0, (
        f"hop 3 zeroes the objection counter, got {cascaded['pending_objection_count']}"
    )

    superseded = read_voter_list(voter_list_id)
    assert superseded["status"] == "SUPERSEDED", (
        f"hop 4 supersedes the accepted voter list, got {superseded['status']}"
    )

    blocked = read_campaign_message(message_id, AUTHOR)
    assert blocked["status"] == "BLOCKED", (
        f"hop 4 blocks the approved campaign message, got {blocked['status']}"
    )
    assert blocked["blocked_reason"] == "RERUN_BLACKOUT", (
        f"the rerun blackout is the stated reason, got {blocked['blocked_reason']}"
    )


def test_overruling_the_only_objection_leaves_the_round_list_and_message_alone():
    """The quiet path returns the case to its posted tally and touches none of the
    collections that a sustained objection would have swept up.

    PRD: "Overruling is the quiet path: it stamps `ruled_at` and the rationale, moves the
    objection to the terminal `OVERRULED` state, and lowers the case's
    `pending_objection_count` by 1."
    PRD: "When that count reaches 0 with no objection on the round having been sustained,
    the case returns from `OBJECTIONS_PENDING` to `TALLY_POSTED`, so certification may
    proceed."

    Design: Difficulty/transitive_cascade/objection_sustained_four_hop_cascade
    """
    ctx = _first_election_through_tally(with_approved_message=True)
    petition_id = ctx["petition"]["id"]
    first_round_id = ctx["first_round"]["id"]

    objection = file_objection(first_round_id, UNION, **CONDUCT_OBJECTION)
    ruled = validate_success(api_client.rule_objection(
        objection["id"],
        {"disposition": "OVERRULE", "disposition_rationale": OVERRULE_RATIONALE},
        BOARD,
    ))
    assert_objection(ruled)
    assert ruled["status"] == "OVERRULED", (
        f"the objection reaches the terminal OVERRULED state, got {ruled['status']}"
    )
    assert ruled["rerun_directed"] is False, (
        "overruling directs no rerun, expected rerun_directed false"
    )

    quiet = read_petition(petition_id)
    assert quiet["case_status"] == "TALLY_POSTED", (
        f"the case returns to its posted tally, got {quiet['case_status']}"
    )
    assert quiet["pending_objection_count"] == 0, (
        f"the last pending objection is spent, got {quiet['pending_objection_count']}"
    )

    untouched_round = read_round(first_round_id)
    assert untouched_round["status"] == "TALLY_POSTED", (
        f"the round is not set aside on the quiet path, got {untouched_round['status']}"
    )
    assert read_voter_list(ctx["voter_list"]["id"])["status"] == "ACCEPTED", (
        "no rerun means no brand-new list, so the accepted list stays accepted"
    )

    message = read_campaign_message(ctx["message"]["id"], AUTHOR)
    assert message["status"] == "APPROVED", (
        f"the approved message survives an overruled objection, got {message['status']}"
    )
    assert_absent(message, "blocked_reason", "campaign_communication")


# --------------------------------------------------------------------------
# A re-audited showing that falls short dismisses the case and clears the file
# --------------------------------------------------------------------------
def _case_awaiting_a_re_audit():
    """A verified case with two rulings still outstanding and a full open file hanging off it."""
    petition, classifications = _ruled_unit_case(
        specs=(PROD_SPEC, MAINT_SPEC, QC_SPEC, LEAD_SPEC),
        rulings=("INCLUDED", "INCLUDED", None, None),
        cards=THIRTY_FOUR_VALID_CARDS,
    )
    agreement = create_election_agreement(
        petition["id"], proposed_election_date="2026-09-01", proposed_voting_method="MANUAL"
    )
    message = create_campaign_message(
        petition["id"], AUTHOR, channel="EMAIL", audience_scope="UNIT_WIDE",
        planned_delivery_at="2026-08-24T13:00:00Z",
        message_summary="Facts about the current benefits package",
        threat_statement_count=0, contains_interrogation=False,
        contains_promise_of_benefit=False, contains_surveillance_reference=False,
        material_claim_count=2, unsupported_material_claim_count=0,
    )
    voter_list = create_voter_list(petition["id"], agreement["id"])
    return {
        "petition": petition, "classifications": classifications, "agreement": agreement,
        "message": message, "voter_list": voter_list,
    }


def test_a_re_audit_that_falls_short_dismisses_the_case_and_clears_four_collections():
    """A second audit of the authorization cards drops the showing below the statutory
    threshold, and the dismissal reaches the classifications, the arrangement, the message
    and the draft list in the same request.

    PRD: "An `INSUFFICIENT` verdict dismisses the case, and it does so through a cascade
    that reaches four other resource types inside the same request."
    PRD: "Because the case is dismissed, every classification on it whose `scope_ruling` is
    still `PENDING` becomes `MOOT` — and since moot headcount stays inside
    `pending_headcount`, no bucket totals change."
    PRD: "Because the case is dismissed, every election agreement on it whose `status` is
    `PROPOSED` or `HEARING_REQUESTED` becomes `VOID` and its `voter_list_due_at` is cleared
    to absent, while a `hearing_requested_at` already recorded is retained for the record."

    Design: Difficulty/transitive_cascade/insufficient_showing_dismissal_fan_out
    """
    ctx = _case_awaiting_a_re_audit()
    petition_id = ctx["petition"]["id"]
    assert ctx["petition"]["showing_verdict"] == "SUFFICIENT", (
        "the first audit of 34 valid cards over 110 clears the threshold, got "
        f"{ctx['petition']['showing_verdict']}"
    )

    dismissed = validate_success(api_client.verify_showing(
        petition_id, dict(THIRTY_VALID_CARDS), BOARD
    ))
    assert_petition(dismissed)
    assert dismissed["valid_card_count"] == 30, (
        f"40 cards less 3, 2, 2 and 3 leaves 30 valid, got {dismissed['valid_card_count']}"
    )
    assert dismissed["showing_of_interest_pct"] == pytest.approx(27.27, abs=0.005), (
        "30 valid cards over the as-petitioned base of 110 is 27.27 per cent, got "
        f"{dismissed['showing_of_interest_pct']}"
    )
    assert dismissed["showing_headcount_basis"] == "AS_PETITIONED", (
        "two classifications are still unruled, so the denominator stays as petitioned, got "
        f"{dismissed['showing_headcount_basis']}"
    )
    assert dismissed["showing_verdict"] == "INSUFFICIENT", (
        f"27.27 per cent falls short of 30.00, got {dismissed['showing_verdict']}"
    )
    assert dismissed["case_status"] == "DISMISSED", (
        f"an insufficient showing dismisses the case, got {dismissed['case_status']}"
    )
    assert dismissed["pending_headcount"] == 20, (
        "the quality inspectors and lead operators stay in the pending bucket even as moot, "
        f"expected 20, got {dismissed['pending_headcount']}"
    )
    assert_headcount_conservation(dismissed)

    for classification in ctx["classifications"][2:]:
        moot = validate_success(api_client.get_classification(classification["id"], BOARD))
        assert moot["scope_ruling"] == "MOOT", (
            f"an unruled classification is mooted by the dismissal, got {moot['scope_ruling']}"
        )
    already_ruled = validate_success(
        api_client.get_classification(ctx["classifications"][0]["id"], BOARD)
    )
    assert already_ruled["scope_ruling"] == "INCLUDED", (
        f"a classification already ruled is untouched, got {already_ruled['scope_ruling']}"
    )

    voided = validate_success(
        api_client.get_election_agreement(ctx["agreement"]["id"], DIRECTOR)
    )
    assert voided["status"] == "VOID", (
        f"the proposed arrangement is voided, got {voided['status']}"
    )
    assert_absent(voided, "voter_list_due_at", "election_agreement")

    blocked = read_campaign_message(ctx["message"]["id"], AUTHOR)
    assert blocked["status"] == "BLOCKED", (
        f"the draft campaign message is blocked, got {blocked['status']}"
    )
    assert blocked["blocked_reason"] == "CASE_DISMISSED", (
        f"the dismissal is the stated reason, got {blocked['blocked_reason']}"
    )

    cancelled = read_voter_list(ctx["voter_list"]["id"])
    assert cancelled["status"] == "CANCELLED", (
        f"the draft voter list is cancelled, got {cancelled['status']}"
    )


def test_a_re_audit_landing_exactly_on_the_threshold_cascades_to_nothing():
    """Thirty per cent to the decimal is still a sufficient showing, so the re-verification
    is a self-loop and every collection on the case is left exactly as it was.

    PRD: "`showing_verdict` is `SUFFICIENT` when the rounded percentage is at least 30.00,
    and `INSUFFICIENT` otherwise; exactly 30.00 is sufficient, since the comparison is
    inclusive at the threshold."
    PRD: "The Board may also **re-verify** a case that is already `SOI_VERIFIED`, which is
    the ordinary response to a scope ruling having changed the denominator; that is a
    self-loop from `SOI_VERIFIED` to `SOI_VERIFIED` that overwrites all four output fields
    from the card counts supplied in the fresh request."

    Design: Difficulty/transitive_cascade/insufficient_showing_dismissal_fan_out
    """
    ctx = _case_awaiting_a_re_audit()

    reverified = validate_success(api_client.verify_showing(
        ctx["petition"]["id"], dict(THIRTY_THREE_VALID_CARDS), BOARD
    ))
    assert reverified["valid_card_count"] == 33, (
        f"40 cards less 3, 2 and 2 leaves 33 valid, got {reverified['valid_card_count']}"
    )
    assert reverified["showing_of_interest_pct"] == pytest.approx(30.00, abs=0.005), (
        "33 valid cards over 110 is exactly 30.00 per cent, got "
        f"{reverified['showing_of_interest_pct']}"
    )
    assert reverified["showing_verdict"] == "SUFFICIENT", (
        f"exactly 30.00 per cent is sufficient, got {reverified['showing_verdict']}"
    )
    assert reverified["case_status"] == "SOI_VERIFIED", (
        f"the case loops back onto SOI_VERIFIED, got {reverified['case_status']}"
    )

    still_pending = validate_success(
        api_client.get_classification(ctx["classifications"][2]["id"], BOARD)
    )
    assert still_pending["scope_ruling"] == "PENDING", (
        f"no dismissal means no mooting, got {still_pending['scope_ruling']}"
    )
    proposed = validate_success(
        api_client.get_election_agreement(ctx["agreement"]["id"], DIRECTOR)
    )
    assert proposed["status"] == "PROPOSED", (
        f"the arrangement is not voided, got {proposed['status']}"
    )
    draft_message = read_campaign_message(ctx["message"]["id"], AUTHOR)
    assert draft_message["status"] == "DRAFT", (
        f"the campaign message stays a draft, got {draft_message['status']}"
    )
    assert_absent(draft_message, "blocked_reason", "campaign_communication")
    assert read_voter_list(ctx["voter_list"]["id"])["status"] == "DRAFT", (
        "the draft voter list is not cancelled by a sufficient re-audit"
    )


# --------------------------------------------------------------------------
# A blocking charge runs down the posture dimension
# --------------------------------------------------------------------------
CHARGE_CLOCK = "2026-08-27T09:00:00Z"


def _charge_payload(petition_id, blocking_requested):
    return {
        "petition_id": petition_id, "charging_party": "UNION", "charged_party": "EMPLOYER",
        "section_code": "8A1",
        "allegation_summary": "Threats of plant closure during pre-election meetings",
        "conduct_occurred_at": "2026-08-25T15:00:00Z",
        "blocking_requested": blocking_requested,
    }


def _case_awaiting_a_charge():
    """An agreed election with round 1 scheduled, one session laid out and one live message."""
    petition, classifications = _ruled_unit_case()
    message = _approved_email_message(
        petition["id"], summary="What the election timetable looks like",
        material_claim_count=2,
    )
    agreement, first_round = _stipulated_election(petition["id"])
    session = create_poll_session(
        first_round["id"], location_code="PLANT_1_CAFETERIA",
        session_start_at=POLLS_OPEN_AT, session_end_at=POLLS_CLOSE_AT, method="MANUAL",
    )
    set_clock(CHARGE_CLOCK)
    return {
        "petition": petition, "agreement": agreement, "first_round": first_round,
        "session": session, "message": message,
    }


def test_a_blocking_charge_suspends_the_round_and_cancels_its_sessions():
    """Docketing a charge that asks for the election to be blocked changes the posture and
    then walks down through the round to its sessions, leaving the lifecycle alone.

    PRD: "If the case's highest-numbered round is *not* in `POLLS_CLOSED`, `TALLY_POSTED` or
    `TALLY_REVISED`, the posture becomes `BLOCKED`, and three further hops follow: because
    the posture is `BLOCKED`, the highest-numbered round in `SCHEDULED` becomes `SUSPENDED`;
    because that round is suspended, each of its poll sessions in `SCHEDULED` becomes
    `CANCELLED` and the round's `scheduled_session_count` is recomputed to 0; and, fanning
    out from the posture change itself, every campaign communication on the case whose
    `status` is `APPROVED` becomes `BLOCKED` with `blocked_reason` `POSTURE_BLOCKED`."
    PRD: "In neither case does `case_status` move; the two dimensions are genuinely
    independent."

    Design: Difficulty/transitive_cascade/blocking_charge_suspension_four_hop
    """
    ctx = _case_awaiting_a_charge()
    petition_id = ctx["petition"]["id"]
    round_id = ctx["first_round"]["id"]

    charge = validate_success(
        api_client.create_ulp_charge(_charge_payload(petition_id, True), UNION), 201
    )
    assert_ulp_charge(charge)
    assert charge["status"] == "FILED", (
        f"a docketed charge starts at FILED, got {charge['status']}"
    )
    assert_instant_equals(charge["filed_at"], CHARGE_CLOCK, "ulp_charge.filed_at")

    blocked_case = read_petition(petition_id)
    assert blocked_case["blocking_charge_count"] == 1, (
        f"the blocking charge is counted, got {blocked_case['blocking_charge_count']}"
    )
    assert blocked_case["case_posture"] == "BLOCKED", (
        f"the posture dimension flips to BLOCKED, got {blocked_case['case_posture']}"
    )
    assert blocked_case["case_status"] == "ELECTION_SET", (
        f"the lifecycle dimension does not move, got {blocked_case['case_status']}"
    )

    suspended = read_round(round_id)
    assert suspended["status"] == "SUSPENDED", (
        f"the scheduled round is suspended, got {suspended['status']}"
    )
    assert suspended["scheduled_session_count"] == 0, (
        "the round's scheduled session count is recomputed to 0, got "
        f"{suspended['scheduled_session_count']}"
    )

    cancelled = read_poll_session(ctx["session"]["id"])
    assert_poll_session(cancelled)
    assert cancelled["status"] == "CANCELLED", (
        f"the laid-out session is cancelled, got {cancelled['status']}"
    )

    message = read_campaign_message(ctx["message"]["id"], AUTHOR)
    assert message["status"] == "BLOCKED", (
        f"the approved message is blocked by the posture change, got {message['status']}"
    )
    assert message["blocked_reason"] == "POSTURE_BLOCKED", (
        f"the posture is the stated reason, got {message['blocked_reason']}"
    )


def test_a_charge_that_does_not_ask_for_blocking_leaves_the_election_running():
    """The same charge without a blocking request is filed and nothing else happens: the
    posture, the round, its session and the live message all stay as they were.

    PRD: "A charge that does **not** request blocking simply sits on the record."
    PRD: "A charge starts at `status` `FILED` with `filed_at` stamped from the logical clock
    and with `remedy_code`, `settlement_type`, `notice_posting_days`, `determined_at` and
    `settled_at` all absent."

    Design: Difficulty/transitive_cascade/blocking_charge_suspension_four_hop
    """
    ctx = _case_awaiting_a_charge()
    petition_id = ctx["petition"]["id"]

    charge = validate_success(
        api_client.create_ulp_charge(_charge_payload(petition_id, False), UNION), 201
    )
    assert charge["status"] == "FILED", (
        f"the charge is still docketed, got {charge['status']}"
    )
    assert_absent(charge, "determined_at", "ulp_charge")

    quiet_case = read_petition(petition_id)
    assert quiet_case["blocking_charge_count"] == 0, (
        "a charge that asks for nothing raises no blocking count, got "
        f"{quiet_case['blocking_charge_count']}"
    )
    assert quiet_case["case_posture"] == "OPEN", (
        f"the posture stays OPEN, got {quiet_case['case_posture']}"
    )
    assert quiet_case["case_status"] == "ELECTION_SET", (
        f"the lifecycle is untouched either way, got {quiet_case['case_status']}"
    )

    running = read_round(ctx["first_round"]["id"])
    assert running["status"] == "SCHEDULED", (
        f"the round is not suspended, got {running['status']}"
    )
    assert running["scheduled_session_count"] == 1, (
        f"the laid-out session still counts, got {running['scheduled_session_count']}"
    )
    assert read_poll_session(ctx["session"]["id"])["status"] == "SCHEDULED", (
        "the poll session is not cancelled by a non-blocking charge"
    )

    message = read_campaign_message(ctx["message"]["id"], AUTHOR)
    assert message["status"] == "APPROVED", (
        f"the approved message stays approved, got {message['status']}"
    )
    assert_absent(message, "blocked_reason", "campaign_communication")


# --------------------------------------------------------------------------
# Losing a presenter's certification runs up from the supervisor to the case
# --------------------------------------------------------------------------
TRAINING_MODULES = ["TIPS_BOUNDARIES", "PROHIBITED_CONDUCT", "SOLICITATION_RULES"]
VIOLATION_CLOCK = "2026-08-24T16:00:00Z"


def _meeting_message(petition_id, supervisor_id, planned_delivery_at, summary):
    """A small-group meeting message approved behind a certified presenter."""
    message = create_campaign_message(
        petition_id, AUTHOR, channel="SMALL_GROUP_MEETING", audience_scope="CLASSIFICATION",
        presenter_supervisor_id=supervisor_id, planned_delivery_at=planned_delivery_at,
        duration_minutes=60, message_summary=summary, threat_statement_count=0,
        contains_interrogation=False, contains_promise_of_benefit=False,
        contains_surveillance_reference=False, material_claim_count=3,
        unsupported_material_claim_count=1,
    )
    accuracy_review(message["id"], ANALYST, material_claim_count=3,
                    unsupported_material_claim_count=1)
    submit_message_for_review(message["id"], AUTHOR)
    return review_message(message["id"], "APPROVE", headers=REVIEWER)


def _case_with_two_certified_presenters():
    """Two trained shift supervisors, each fronting one approved meeting message."""
    set_clock(DRAFTING_CLOCK)
    petition = create_petition()
    open_scope_analysis(petition["id"])
    supervisor_a = register_supervisor(
        petition["id"], TRAINER, full_name="Marta Kowalski", job_title="Shift Supervisor",
        span_of_control=18, has_hire_fire_authority=True,
    )
    supervisor_b = register_supervisor(
        petition["id"], TRAINER, full_name="Terrence Boyd", job_title="Shift Supervisor",
        span_of_control=14, has_hire_fire_authority=True,
    )
    supervisor_a = train_supervisor(
        supervisor_a["id"], TRAINER, modules_completed=list(TRAINING_MODULES), quiz_score=92
    )
    supervisor_b = train_supervisor(
        supervisor_b["id"], TRAINER, modules_completed=list(TRAINING_MODULES), quiz_score=92
    )
    message_a = _meeting_message(
        petition["id"], supervisor_a["id"], "2026-08-25T10:00:00Z",
        "Shift briefing on the election process",
    )
    message_b = _meeting_message(
        petition["id"], supervisor_b["id"], "2026-08-25T15:00:00Z",
        "Maintenance crew briefing on the election process",
    )
    set_clock(VIOLATION_CLOCK)
    return {
        "petition": petition, "supervisor_a": supervisor_a, "supervisor_b": supervisor_b,
        "message_a": message_a, "message_b": message_b,
    }


def test_a_substantiated_violation_blocks_only_that_presenter_s_messages():
    """Decertifying one shift supervisor blocks the message they were to present, leaves the
    other presenter's message alone, and flags the case for retraining.

    PRD: "First, `violation_count` increments, `last_violation_code` is written,
    `certified_at` is cleared to absent, and `training_status` returns to `UNTRAINED`."
    PRD: "Second, because the presenter has lost certification, every campaign
    communication naming this supervisor in `presenter_supervisor_id` whose `status` is
    `PENDING_LEGAL_REVIEW` or `APPROVED` becomes `BLOCKED` with `blocked_reason` set to
    `PRESENTER_DECERTIFIED`."
    PRD: "Third, because at least one message was blocked for decertification, the case's
    `retraining_required` becomes true."

    Design: Difficulty/transitive_cascade/presenter_decertification_three_hop
    """
    ctx = _case_with_two_certified_presenters()
    assert ctx["message_a"]["risk_score"] == 20, (
        "a small-group meeting at classification scope with one unsupported claim scores 20, "
        f"got {ctx['message_a']['risk_score']}"
    )

    decertified = validate_success(api_client.record_violation(
        ctx["supervisor_a"]["id"],
        {"violation_code": "INTERROGATION", "substantiated": True},
        COUNSEL,
    ))
    assert_supervisor(decertified)
    assert decertified["violation_count"] == 1, (
        f"the finding is counted, got {decertified['violation_count']}"
    )
    assert decertified["last_violation_code"] == "INTERROGATION", (
        f"the code of the finding is written, got {decertified['last_violation_code']}"
    )
    assert decertified["training_status"] == "UNTRAINED", (
        f"a substantiated finding decertifies the presenter, got {decertified['training_status']}"
    )
    assert_absent(decertified, "certified_at", "supervisor")
    assert decertified["training_attempt_count"] == 1, (
        "the one qualifying attempt is not rewound by the finding, got "
        f"{decertified['training_attempt_count']}"
    )

    blocked = read_campaign_message(ctx["message_a"]["id"], AUTHOR)
    assert blocked["status"] == "BLOCKED", (
        f"the decertified presenter's message is blocked, got {blocked['status']}"
    )
    assert blocked["blocked_reason"] == "PRESENTER_DECERTIFIED", (
        f"the lost certification is the stated reason, got {blocked['blocked_reason']}"
    )

    untouched = read_campaign_message(ctx["message_b"]["id"], AUTHOR)
    assert untouched["status"] == "APPROVED", (
        f"the other presenter's message is not named by the finding, got {untouched['status']}"
    )
    assert_absent(untouched, "blocked_reason", "campaign_communication")

    other_presenter = validate_success(
        api_client.get_supervisor(ctx["supervisor_b"]["id"], TRAINER)
    )
    assert other_presenter["training_status"] == "TRAINED", (
        f"the second supervisor keeps their certification, got {other_presenter['training_status']}"
    )

    flagged = read_petition(ctx["petition"]["id"])
    assert flagged["retraining_required"] is True, (
        "one blocked message flags the case for retraining, expected retraining_required true"
    )


def test_retraining_the_presenter_does_not_unblock_their_message():
    """A supervisor can earn their certification back, but the message that was blocked when
    they lost it stays blocked for that reason.

    PRD: "The supervisor may afterwards train again and return to `TRAINED` — and doing so
    does **not** unblock the messages, which stay blocked permanently for that reason."
    PRD: "A qualifying attempt increments `training_attempt_count`, records the score and the
    modules, stamps `certified_at` with the logical clock, and moves `training_status` from
    `UNTRAINED` to `TRAINED`."

    Design: Difficulty/transitive_cascade/presenter_decertification_three_hop
    """
    ctx = _case_with_two_certified_presenters()
    validate_success(api_client.record_violation(
        ctx["supervisor_a"]["id"],
        {"violation_code": "INTERROGATION", "substantiated": True},
        COUNSEL,
    ))
    assert read_campaign_message(ctx["message_a"]["id"], AUTHOR)["status"] == "BLOCKED", (
        "the message is blocked before the presenter trains again"
    )

    set_clock("2026-08-25T08:00:00Z")
    retrained = validate_success(api_client.train_supervisor(
        ctx["supervisor_a"]["id"],
        {"modules_completed": list(TRAINING_MODULES), "quiz_score": 92},
        TRAINER,
    ))
    assert retrained["training_status"] == "TRAINED", (
        f"a second qualifying attempt re-certifies the supervisor, got {retrained['training_status']}"
    )
    assert retrained["training_attempt_count"] == 2, (
        f"the attempt counter keeps climbing, got {retrained['training_attempt_count']}"
    )
    assert_instant_equals(retrained["certified_at"], "2026-08-25T08:00:00Z", "supervisor.certified_at")

    still_blocked = read_campaign_message(ctx["message_a"]["id"], AUTHOR)
    assert still_blocked["status"] == "BLOCKED", (
        f"regaining certification does not revive the message, got {still_blocked['status']}"
    )
    assert still_blocked["blocked_reason"] == "PRESENTER_DECERTIFIED", (
        "the message stays blocked for the presenter's decertification, got "
        f"{still_blocked['blocked_reason']}"
    )
