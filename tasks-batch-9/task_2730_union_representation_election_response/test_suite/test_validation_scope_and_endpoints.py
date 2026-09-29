"""Caller-supplied count coherence, cross-case reference refusals, uniqueness
scopes, and the voter-entry, polling, challenged-ballot and case-read endpoints.
"""
from test_helpers import (
    ANALYST,
    BOARD,
    DIRECTOR,
    NON_EXISTENT_UUID,
    ApiErrorId,
    accuracy_review_payload,
    add_complete_entries,
    add_classification,
    api_client,
    assert_ballot_conservation,
    assert_challenged_ballot,
    assert_classification,
    assert_election_round,
    assert_headcount_conservation,
    assert_instant_equals,
    assert_instants_equal,
    assert_pagination_meta,
    assert_petition,
    assert_poll_session,
    assert_voter_list,
    assert_voter_list_entry,
    close_session_payload,
    create_campaign_communication_payload,
    create_campaign_message,
    create_challenged_ballot_payload,
    create_classification_payload,
    create_election_agreement,
    create_election_agreement_payload,
    create_petition_in_scope_analysis,
    create_petition_payload,
    create_supervisor_payload,
    create_voter_list,
    create_voter_list_entry_payload,
    create_voter_list_payload,
    get_success_data,
    petition_version,
    read_campaign_message,
    read_petition,
    read_poll_session,
    read_round,
    read_voter_list,
    register_supervisor,
    reopen_ballot,
    request_hearing,
    resolve_ballot,
    score_and_rule,
    score_classification,
    segregate_ballot,
    set_clock,
    setup_election_set,
    setup_polls_closed,
    setup_polls_open,
    setup_scope_analysis,
    setup_sessions_laid_out,
    setup_soi_verified,
    setup_tally_posted,
    stipulate_payload,
    submit_voter_list,
    unique_case_number,
    unique_classification_code,
    validate_error,
    validate_paginated,
    validate_success,
    verify_showing_payload,
)


# ---------------------------------------------------------------------------
# Arithmetic coherence of the counts a caller supplies
# ---------------------------------------------------------------------------
def test_struck_cards_may_not_exceed_the_submitted_card_count():
    """Verifying a showing whose four struck counts add up past the submitted count is
    refused and leaves the card counters untouched.

    PRD: "If the four struck counts together exceed the submitted count, so that the valid count would be negative, the request fails with `ERR_CARD_COUNTS_INCONSISTENT` (HTTP 422) before anything is written."

    Design: Corner/validations/caller_supplied_counts_must_be_arithmetically_coherent
    """
    ctx = setup_scope_analysis()
    petition_id = ctx["petition"]["id"]

    resp = api_client.verify_showing(
        petition_id,
        verify_showing_payload(
            submitted_card_count=40,
            duplicate_card_count=20,
            undated_card_count=15,
            stale_card_count=10,
            nonunit_card_count=0,
        ),
        BOARD,
    )
    validate_error(resp, ApiErrorId.ERR_CARD_COUNTS_INCONSISTENT)

    petition = read_petition(petition_id)
    assert_petition(petition)
    for counter in (
        "submitted_card_count", "duplicate_card_count", "undated_card_count",
        "stale_card_count", "nonunit_card_count",
    ):
        assert petition[counter] == 0, f"{counter} must still be 0 after the refusal"
    assert petition["showing_verdict"] == "PENDING"


def test_a_showing_cannot_be_measured_against_an_empty_voting_unit():
    """When every classification has been ruled out of the unit the selected denominator is
    zero, and the verification is refused rather than scored at zero percent.

    PRD: "If the selected denominator is zero, that is not a zero-percent showing — the request fails with `ERR_UNIT_HEADCOUNT_ZERO` (HTTP 422) and nothing is written."

    Design: Corner/validations/caller_supplied_counts_must_be_arithmetically_coherent
    """
    ctx = setup_scope_analysis()
    petition_id = ctx["petition"]["id"]
    score_and_rule(ctx["classifications"][0]["id"], "EXCLUDED")

    petition = read_petition(petition_id)
    assert petition["included_headcount"] == 0
    assert petition["excluded_headcount"] == 60

    resp = api_client.verify_showing(petition_id, verify_showing_payload(), BOARD)
    validate_error(resp, ApiErrorId.ERR_UNIT_HEADCOUNT_ZERO)

    petition = read_petition(petition_id)
    assert petition["submitted_card_count"] == 0
    assert petition["showing_verdict"] == "PENDING"
    assert petition["case_status"] == "SCOPE_ANALYSIS"


def test_unsupported_claims_may_not_outnumber_the_material_claims_counted():
    """An accuracy review reporting more unsourced claims than material claims is refused and
    the message keeps its unreviewed draft shape.

    PRD: "The request supplies `material_claim_count`, the number of material factual claims the reviewer counted, and `unsupported_material_claim_count`, the number the reviewer could not source; if the unsupported count exceeds the material count, the request fails with `ERR_CLAIM_COUNTS_INCONSISTENT` (HTTP 422)."

    Design: Corner/validations/caller_supplied_counts_must_be_arithmetically_coherent
    """
    petition = create_petition_in_scope_analysis()
    message = create_campaign_message(petition["id"])

    resp = api_client.accuracy_review_communication(
        message["id"],
        accuracy_review_payload(material_claim_count=2, unsupported_material_claim_count=3),
        DIRECTOR,
    )
    validate_error(resp, ApiErrorId.ERR_CLAIM_COUNTS_INCONSISTENT)

    stored = read_campaign_message(message["id"])
    assert stored["status"] == "DRAFT"
    assert stored["risk_score"] == 0
    assert stored.get("accuracy_reviewed_at") is None


# ---------------------------------------------------------------------------
# Rows belonging to a neighbouring case
# ---------------------------------------------------------------------------
def test_a_voter_entry_cannot_borrow_a_classification_from_another_case():
    """An entry joining one case's list while naming another case's classification is
    refused, and the list's own entry from the same case is unaffected.

    PRD: "Concretely, a voter entry's classification must sit on the same petition as the list it joins; a voter list's election agreement must belong to the list's petition; a campaign message's presenting supervisor must be registered on the message's petition, as must a supervisor named as an observer; and a charge consolidated with an objection must name an objection whose round belongs to the charge's petition."

    Design: Corner/validations/rows_from_a_neighbouring_case_are_refused_on_every_declared_edge
    """
    ctx = setup_election_set()
    voter_list = create_voter_list(ctx["petition"]["id"], ctx["agreement"]["id"])
    neighbour = create_petition_in_scope_analysis()
    neighbour_classification = add_classification(neighbour["id"])

    own = api_client.create_voter_list_entry(
        create_voter_list_entry_payload(voter_list["id"], ctx["classifications"][0]["id"]),
        ANALYST,
    )
    validate_success(own, 201)
    assert_voter_list_entry(get_success_data(own))

    resp = api_client.create_voter_list_entry(
        create_voter_list_entry_payload(voter_list["id"], neighbour_classification["id"]),
        ANALYST,
    )
    validate_error(resp, ApiErrorId.ERR_CROSS_PETITION_REFERENCE)

    stored = read_voter_list(voter_list["id"])
    assert_voter_list(stored)
    assert stored["total_entry_count"] == 1, "the refused entry must not have been written"


def test_a_campaign_message_cannot_name_a_presenter_from_another_case():
    """A meeting message may only name a supervisor registered on its own petition.

    PRD: "Every entity named in a request must belong to the same petition as the request's target, and a mismatch is reported as `ERR_CROSS_PETITION_REFERENCE` (HTTP 409)."

    Design: Corner/validations/rows_from_a_neighbouring_case_are_refused_on_every_declared_edge
    """
    petition = create_petition_in_scope_analysis()
    neighbour = create_petition_in_scope_analysis()
    own_supervisor = register_supervisor(petition["id"])
    neighbour_supervisor = register_supervisor(neighbour["id"], full_name="Kim Delacroix")

    resp = api_client.create_campaign_communication(
        create_campaign_communication_payload(
            petition["id"],
            channel="SMALL_GROUP_MEETING",
            presenter_supervisor_id=neighbour_supervisor["id"],
        ),
        DIRECTOR,
    )
    validate_error(resp, ApiErrorId.ERR_CROSS_PETITION_REFERENCE)

    accepted = api_client.create_campaign_communication(
        create_campaign_communication_payload(
            petition["id"],
            channel="SMALL_GROUP_MEETING",
            presenter_supervisor_id=own_supervisor["id"],
        ),
        DIRECTOR,
    )
    validate_success(accepted, 201)
    assert get_success_data(accepted)["presenter_supervisor_id"] == own_supervisor["id"]


def test_a_voter_list_cannot_be_opened_against_another_cases_arrangement():
    """A list create naming the arrangement of a different case is refused even though the
    asserted petition version is current, and no list is written.

    PRD: "Every entity named in a request must belong to the same petition as the request's target, and a mismatch is reported as `ERR_CROSS_PETITION_REFERENCE` (HTTP 409)."

    Design: Corner/validations/rows_from_a_neighbouring_case_are_refused_on_every_declared_edge
    """
    ctx = setup_election_set()
    neighbour_ctx = setup_election_set()
    petition_id = ctx["petition"]["id"]

    resp = api_client.create_voter_list(
        create_voter_list_payload(
            petition_id, neighbour_ctx["agreement"]["id"], petition_version(petition_id)
        ),
        DIRECTOR,
    )
    validate_error(resp, ApiErrorId.ERR_CROSS_PETITION_REFERENCE)

    listed = api_client.list_voter_lists(DIRECTOR, params={"petition_id": petition_id})
    rows, _ = validate_paginated(listed)
    assert rows == [], "the refused list create must not have persisted a row"


# ---------------------------------------------------------------------------
# Scoring, ruling and reconsideration gates on a classification
# ---------------------------------------------------------------------------
def test_a_classification_that_was_never_scored_cannot_be_ruled():
    """A ruling on a classification whose community-of-interest score is still absent is
    refused, and the headcount stays in the pending bucket.

    PRD: "A classification that has never been scored cannot be ruled at all: `coi_score` must already hold a value, and if it does not the request fails with `ERR_CLASSIFICATION_NOT_SCORED`."

    Design: Corner/validations/the_scored_check_runs_before_the_already_ruled_check
    """
    ctx = setup_scope_analysis()
    classification = ctx["classifications"][0]
    assert classification.get("coi_score") is None
    assert classification["scope_ruling"] == "PENDING"

    resp = api_client.rule_classification(
        classification["id"],
        {"ruling": "INCLUDED", "ruling_rationale": "Shares a community of interest."},
        BOARD,
    )
    validate_error(resp, ApiErrorId.ERR_CLASSIFICATION_NOT_SCORED)

    stored = get_success_data(api_client.get_classification(classification["id"], BOARD))
    assert_classification(stored)
    assert stored["scope_ruling"] == "PENDING"

    petition = read_petition(ctx["petition"]["id"])
    assert petition["pending_headcount"] == 60
    assert petition["included_headcount"] == 0
    assert_headcount_conservation(petition)


def test_a_classification_still_pending_cannot_be_reconsidered():
    """Reconsideration is a compensating action for a ruled classification, so a scored but
    still pending one is refused by the state check on the classification itself.

    PRD: "**Own-state precondition** — the target row is in a state from which the requested transition is declared, else the state code for that resource type: `ERR_PETITION_STATUS_INVALID`, `ERR_CLASSIFICATION_ALREADY_RULED`, `ERR_AGREEMENT_STATUS_INVALID`, `ERR_VOTER_LIST_STATUS_INVALID`, `ERR_COMMUNICATION_STATUS_INVALID`, `ERR_ROUND_NOT_SCHEDULED`, `ERR_ROUND_STATUS_INVALID`, `ERR_POLL_SESSION_STATUS_INVALID`, `ERR_BALLOT_STATUS_INVALID`, `ERR_OBJECTION_ALREADY_RULED` or `ERR_CHARGE_STATUS_INVALID`, each HTTP 409."

    Design: Corner/validations/the_scored_check_runs_before_the_already_ruled_check
    """
    ctx = setup_scope_analysis()
    classification = ctx["classifications"][0]
    scored = score_classification(classification["id"])
    assert scored["coi_score"] is not None
    assert scored["scope_ruling"] == "PENDING"

    resp = api_client.reconsider_classification(
        classification["id"], {"reconsideration_note": "Revisiting the unit placement."}, BOARD
    )
    validate_error(resp, ApiErrorId.ERR_CLASSIFICATION_ALREADY_RULED)

    stored = get_success_data(api_client.get_classification(classification["id"], BOARD))
    assert stored["scope_ruling"] == "PENDING"
    assert read_petition(ctx["petition"]["id"])["pending_headcount"] == 60


def test_a_classification_that_has_been_ruled_cannot_be_ruled_again():
    """A second ruling on the same classification is refused and the headcount movement the
    first ruling made is not repeated.

    PRD: "A ruling is only possible while the classification's `scope_ruling` is still `PENDING` and while the case sits in either `SCOPE_ANALYSIS` or `SOI_VERIFIED`; a classification that has already been ruled, or one that has become moot, is refused with `ERR_CLASSIFICATION_ALREADY_RULED`."

    Design: Corner/validations/the_scored_check_runs_before_the_already_ruled_check
    """
    ctx = setup_scope_analysis()
    classification = ctx["classifications"][0]
    ruled = score_and_rule(classification["id"], "INCLUDED")
    assert ruled["scope_ruling"] == "INCLUDED"

    resp = api_client.rule_classification(
        classification["id"],
        {"ruling": "EXCLUDED", "ruling_rationale": "Second thoughts about the unit."},
        BOARD,
    )
    validate_error(resp, ApiErrorId.ERR_CLASSIFICATION_ALREADY_RULED)

    stored = get_success_data(api_client.get_classification(classification["id"], BOARD))
    assert stored["scope_ruling"] == "INCLUDED"

    petition = read_petition(ctx["petition"]["id"])
    assert petition["included_headcount"] == 60
    assert petition["excluded_headcount"] == 0
    assert petition["pending_headcount"] == 0
    assert_headcount_conservation(petition)


# ---------------------------------------------------------------------------
# The reopen ceiling on a segregated ballot
# ---------------------------------------------------------------------------
def _case_with_a_segregated_ballot_and_a_posted_tally():
    """A case whose tally is posted with one challenged ballot still in the box."""
    ctx = setup_polls_open(entry_count=3)
    ballot = segregate_ballot(
        ctx["sessions"][0]["id"], voter_list_entry_id=ctx["entries"][0]["id"]
    )
    ctx = setup_polls_closed(ctx)
    ctx = setup_tally_posted(ctx)
    ctx["ballot"] = ballot
    return ctx


def test_a_ballot_may_be_reopened_twice_but_never_a_third_time():
    """Two resolve-and-reopen cycles are accepted, and the reopen attempt that would take the
    count past two is refused with the ballot left in its last resolution.

    PRD: "Reopening is only possible while the round is `TALLY_POSTED` or `TALLY_REVISED`, only on a ballot that is not `OPEN`, and only while `reopen_count` is still below its ceiling of 2; a third reopen is refused with `ERR_REOPEN_LIMIT_EXCEEDED`."

    Design: Corner/validations/the_reopen_limit_is_inclusive_at_two_per_ballot
    """
    ctx = _case_with_a_segregated_ballot_and_a_posted_tally()
    ballot_id = ctx["ballot"]["id"]

    assert resolve_ballot(ballot_id, resolution="COUNTED_FOR")["resolution"] == "COUNTED_FOR"
    first_reopen = reopen_ballot(ballot_id, "The challenger produced the payroll record.")
    assert first_reopen["resolution"] == "OPEN"
    assert first_reopen["reopen_count"] == 1

    assert resolve_ballot(ballot_id, resolution="COUNTED_AGAINST")["resolution"] == "COUNTED_AGAINST"
    second_reopen = reopen_ballot(ballot_id, "The employer disputed the payroll record.")
    assert second_reopen["resolution"] == "OPEN"
    assert second_reopen["reopen_count"] == 2

    assert resolve_ballot(ballot_id, resolution="VOIDED")["resolution"] == "VOIDED"
    resp = api_client.reopen_challenged_ballot(
        ballot_id, {"reopen_reason": "A third look at the same ballot."}, BOARD
    )
    validate_error(resp, ApiErrorId.ERR_REOPEN_LIMIT_EXCEEDED)

    stored = get_success_data(api_client.get_challenged_ballot(ballot_id, BOARD))
    assert_challenged_ballot(stored)
    assert stored["resolution"] == "VOIDED"
    assert stored["reopen_count"] == 2

    assert_ballot_conservation(read_round(ctx["round"]["id"]))


def test_reopening_a_ballot_undoes_exactly_the_bucket_the_resolution_filled():
    """A resolution moves the ballot out of the open bucket into one other bucket, and the
    reopen moves that same ballot back without changing the number of ballots in the box.

    PRD: "Resolution and reopening are exact inverses of one another: a resolution moves one ballot out of the open bucket and into exactly one other bucket, and a reopen moves that same ballot back."

    Design: Corner/validations/the_reopen_limit_is_inclusive_at_two_per_ballot
    """
    ctx = _case_with_a_segregated_ballot_and_a_posted_tally()
    ballot_id = ctx["ballot"]["id"]
    round_id = ctx["round"]["id"]

    before = read_round(round_id)
    assert_election_round(before)
    assert before["challenged_open_count"] == 1
    assert before["challenged_counted_for_count"] == 0

    resolve_ballot(ballot_id, resolution="COUNTED_FOR")
    during = read_round(round_id)
    assert during["challenged_open_count"] == 0
    assert during["challenged_counted_for_count"] == 1
    assert during["ballots_cast_total"] == before["ballots_cast_total"]
    assert_ballot_conservation(during)

    reopen_ballot(ballot_id)
    after = read_round(round_id)
    assert after["challenged_open_count"] == 1
    assert after["challenged_counted_for_count"] == 0
    assert after["ballots_cast_total"] == before["ballots_cast_total"]
    assert_ballot_conservation(after)


# ---------------------------------------------------------------------------
# The scope of each uniqueness key
# ---------------------------------------------------------------------------
def test_a_docket_number_may_be_used_by_only_one_case_in_the_system():
    """The docket number collides system-wide, while any unused number is accepted.

    PRD: "The docket number is unique across the entire system, and a second petition asserting a number already in use is rejected with `ERR_DUPLICATE_CASE_NUMBER`."

    Design: Corner/validations/uniqueness_keys_are_scoped_exactly_as_declared
    """
    docket_number = unique_case_number()
    first = api_client.create_petition(
        create_petition_payload(case_number=docket_number), DIRECTOR
    )
    validate_success(first, 201)
    assert_petition(get_success_data(first))

    resp = api_client.create_petition(
        create_petition_payload(
            case_number=docket_number, union_name="Allied Trades Council Local 88"
        ),
        DIRECTOR,
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_CASE_NUMBER)

    fresh = api_client.create_petition(create_petition_payload(), DIRECTOR)
    validate_success(fresh, 201)


def test_a_classification_code_is_unique_only_inside_its_own_case():
    """The same classification code collides within one case and is accepted on another.

    PRD: "A classification code must be unique within its own case, though two different cases may use the same code; a collision inside one case is `ERR_DUPLICATE_CLASSIFICATION_CODE`."

    Design: Corner/validations/uniqueness_keys_are_scoped_exactly_as_declared
    """
    code = unique_classification_code()
    petition = create_petition_in_scope_analysis()
    neighbour = create_petition_in_scope_analysis()

    first = api_client.create_classification(
        create_classification_payload(petition["id"], code=code), DIRECTOR
    )
    validate_success(first, 201)

    resp = api_client.create_classification(
        create_classification_payload(petition["id"], code=code, title="Warehouse Attendant"),
        DIRECTOR,
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_CLASSIFICATION_CODE)

    on_the_other_case = api_client.create_classification(
        create_classification_payload(neighbour["id"], code=code), DIRECTOR
    )
    validate_success(on_the_other_case, 201)

    stored = read_petition(petition["id"])
    assert stored["total_classified_headcount"] == 60, "the refused code must not add headcount"
    assert_headcount_conservation(stored)


def test_a_supervisor_collides_only_on_the_same_name_and_job_title():
    """The duplicate key is the pair, so the same name under a different job title is accepted
    and so is the same pair on a different case.

    PRD: "No case may hold two supervisors sharing both a name and a job title; the duplicate is rejected with `ERR_DUPLICATE_SUPERVISOR`."

    Design: Corner/validations/uniqueness_keys_are_scoped_exactly_as_declared
    """
    petition = create_petition_in_scope_analysis()
    neighbour = create_petition_in_scope_analysis()

    first = api_client.create_supervisor(create_supervisor_payload(petition["id"]), DIRECTOR)
    validate_success(first, 201)

    resp = api_client.create_supervisor(
        create_supervisor_payload(petition["id"], span_of_control=24), DIRECTOR
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_SUPERVISOR)

    other_title = api_client.create_supervisor(
        create_supervisor_payload(petition["id"], job_title="Shift Supervisor"), DIRECTOR
    )
    validate_success(other_title, 201)

    other_case = api_client.create_supervisor(
        create_supervisor_payload(neighbour["id"]), DIRECTOR
    )
    validate_success(other_case, 201)


# ---------------------------------------------------------------------------
# One live arrangement and one live voter list per case
# ---------------------------------------------------------------------------
def test_a_case_may_hold_only_one_arrangement_that_is_not_void():
    """A second arrangement opened while the first is still live is rejected.

    PRD: "A case may hold only one arrangement that is not `VOID`; attempting to open a second is rejected with `ERR_DUPLICATE_ELECTION_AGREEMENT`."

    Design: Corner/validations/one_live_agreement_and_one_live_list_per_case
    """
    ctx = setup_soi_verified()
    petition_id = ctx["petition"]["id"]
    first = create_election_agreement(petition_id)
    assert first["status"] == "PROPOSED"

    resp = api_client.create_election_agreement(
        create_election_agreement_payload(petition_id, agreement_type="CONSENT"), DIRECTOR
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_ELECTION_AGREEMENT)

    listed = api_client.list_election_agreements(DIRECTOR, params={"petition_id": petition_id})
    rows, _ = validate_paginated(listed)
    assert len(rows) == 1, "the refused arrangement must not have been written"
    assert rows[0]["id"] == first["id"]


def test_an_arrangement_that_left_proposed_can_no_longer_be_stipulated():
    """Once a hearing has been requested the arrangement is no longer in the state approval
    requires, so the approval is refused and no election round is minted.

    PRD: "Approval requires the case to be `SOI_VERIFIED` with `case_posture` `OPEN` and `showing_verdict` already `SUFFICIENT`; an arrangement in any status other than `PROPOSED` is refused with `ERR_AGREEMENT_STATUS_INVALID`."

    Design: Corner/validations/one_live_agreement_and_one_live_list_per_case
    """
    ctx = setup_soi_verified()
    petition_id = ctx["petition"]["id"]
    agreement = create_election_agreement(petition_id)
    agreement = request_hearing(agreement["id"])
    assert agreement["status"] == "HEARING_REQUESTED"

    resp = api_client.stipulate_agreement(agreement["id"], stipulate_payload(), BOARD)
    validate_error(resp, ApiErrorId.ERR_AGREEMENT_STATUS_INVALID)

    stored = get_success_data(api_client.get_election_agreement(agreement["id"], DIRECTOR))
    assert stored["status"] == "HEARING_REQUESTED"
    assert read_petition(petition_id)["case_status"] == "SOI_VERIFIED"

    rounds = api_client.list_election_rounds(BOARD, params={"petition_id": petition_id})
    round_rows, _ = validate_paginated(rounds)
    assert round_rows == [], "a refused approval must not mint an election round"


def test_a_list_with_no_entries_cannot_be_filed():
    """A list carrying no voters cannot be graded, so the attestation is refused and the list
    stays in draft.

    PRD: "Submission is only possible from `DRAFT`, requires the case to be in `ELECTION_SET` with posture `OPEN`, and requires `total_entry_count` to be at least 1 — a list with no entries cannot be graded and the attempt fails with `ERR_VOTER_LIST_EMPTY` (HTTP 422)."

    Design: Corner/validations/one_live_agreement_and_one_live_list_per_case
    """
    ctx = setup_election_set()
    voter_list = create_voter_list(ctx["petition"]["id"], ctx["agreement"]["id"])
    assert voter_list["status"] == "DRAFT"
    assert voter_list["total_entry_count"] == 0

    resp = api_client.submit_voter_list(
        voter_list["id"], {"attested_by_title": "Director of Labor Relations"}, DIRECTOR
    )
    validate_error(resp, ApiErrorId.ERR_VOTER_LIST_EMPTY)

    stored = read_voter_list(voter_list["id"])
    assert_voter_list(stored)
    assert stored["status"] == "DRAFT"
    assert stored["total_entry_count"] == 0


def test_a_filed_list_blocks_a_replacement_instead_of_being_superseded():
    """While a list sits in submitted status a fresh list cannot be opened on the same case.

    PRD: "A case that already holds a list in `SUBMITTED` or `ACCEPTED` is a different matter: such a list cannot be superseded, and the create is rejected with `ERR_DUPLICATE_VOTER_LIST`."

    Design: Corner/validations/one_live_agreement_and_one_live_list_per_case
    """
    ctx = setup_election_set()
    petition_id = ctx["petition"]["id"]
    voter_list = create_voter_list(petition_id, ctx["agreement"]["id"])
    add_complete_entries(voter_list["id"], ctx["classifications"][0]["id"], 1)
    filed = submit_voter_list(voter_list["id"])
    assert filed["status"] == "SUBMITTED"

    resp = api_client.create_voter_list(
        create_voter_list_payload(
            petition_id, ctx["agreement"]["id"], petition_version(petition_id)
        ),
        DIRECTOR,
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_VOTER_LIST)

    listed = api_client.list_voter_lists(DIRECTOR, params={"petition_id": petition_id})
    rows, _ = validate_paginated(listed)
    assert len(rows) == 1
    assert rows[0]["status"] == "SUBMITTED"


# ---------------------------------------------------------------------------
# The voter entry endpoints and the parent list they recompute
# ---------------------------------------------------------------------------
def _draft_list_with_two_complete_and_one_incomplete_entry():
    """A draft list holding two fully documented voters and one missing two fields."""
    ctx = setup_election_set()
    voter_list = create_voter_list(ctx["petition"]["id"], ctx["agreement"]["id"])
    classification_id = ctx["classifications"][0]["id"]
    add_complete_entries(voter_list["id"], classification_id, 2)
    resp = api_client.create_voter_list_entry(
        create_voter_list_entry_payload(
            voter_list["id"], classification_id,
            full_name="Priya Raman", personal_email=None, personal_phone=None,
        ),
        ANALYST,
    )
    validate_success(resp, 201)
    ctx["voter_list"] = read_voter_list(voter_list["id"])
    ctx["incomplete_entry"] = get_success_data(resp)
    return ctx


def test_an_entry_counts_the_statutory_fields_it_is_missing():
    """A voter added without an email address or a phone number is stored with a missing-field
    count of two and is still eligible to vote.

    PRD: "The five statutory content fields are counted: `missing_field_count` is the number of them that are absent, null or empty, so it runs from 0 to 5, and `is_statutory_content_complete` is true exactly when that count is 0."

    Design: Corner/endpoints/voter_list_entry_crud_round_trips_and_recomputes_its_parent
    """
    ctx = _draft_list_with_two_complete_and_one_incomplete_entry()
    entry = ctx["incomplete_entry"]

    assert_voter_list_entry(entry)
    assert entry["missing_field_count"] == 2
    assert entry["is_statutory_content_complete"] is False
    assert entry["eligibility_status"] == "ELIGIBLE"
    assert entry.get("ineligibility_reason") is None

    parent = ctx["voter_list"]
    assert_voter_list(parent)
    assert parent["total_entry_count"] == 3
    assert parent["complete_entry_count"] == 2


def test_curing_an_entry_lifts_the_parent_lists_complete_entry_count():
    """Supplying the two missing statutory fields makes the entry complete and the parent
    list's counters are recomputed on the update.

    PRD: "Every create and every update re-runs the eligibility rules and recomputes the parent list's counters."

    Design: Corner/endpoints/voter_list_entry_crud_round_trips_and_recomputes_its_parent
    """
    ctx = _draft_list_with_two_complete_and_one_incomplete_entry()
    entry_id = ctx["incomplete_entry"]["id"]

    resp = api_client.update_voter_list_entry(
        entry_id,
        {"personal_email": "priya.raman@example.com", "personal_phone": "+1-555-0199"},
        ANALYST,
    )
    validate_success(resp)
    cured = get_success_data(resp)
    assert_voter_list_entry(cured)
    assert cured["missing_field_count"] == 0
    assert cured["is_statutory_content_complete"] is True
    assert cured["eligibility_status"] == "ELIGIBLE"

    parent = read_voter_list(ctx["voter_list"]["id"])
    assert parent["total_entry_count"] == 3
    assert parent["complete_entry_count"] == 3


def test_a_permanent_layoff_recorded_on_an_entry_defeats_its_eligibility():
    """Recording a permanent layoff on an otherwise complete entry makes it ineligible without
    disturbing the statutory-content counters.

    PRD: "Fourth, if `on_leave_type` is `PERMANENT_LAYOFF`, the entry is `INELIGIBLE` with reason `PERMANENT_LAYOFF`."

    Design: Corner/endpoints/voter_list_entry_crud_round_trips_and_recomputes_its_parent
    """
    ctx = _draft_list_with_two_complete_and_one_incomplete_entry()
    entry_id = ctx["incomplete_entry"]["id"]
    validate_success(
        api_client.update_voter_list_entry(
            entry_id,
            {"personal_email": "priya.raman@example.com", "personal_phone": "+1-555-0199"},
            ANALYST,
        )
    )

    resp = api_client.update_voter_list_entry(
        entry_id, {"on_leave_type": "PERMANENT_LAYOFF"}, ANALYST
    )
    validate_success(resp)
    laid_off = get_success_data(resp)
    assert_voter_list_entry(laid_off)
    assert laid_off["eligibility_status"] == "INELIGIBLE"
    assert laid_off["ineligibility_reason"] == "PERMANENT_LAYOFF"
    assert laid_off["missing_field_count"] == 0
    assert laid_off["is_statutory_content_complete"] is True

    parent = read_voter_list(ctx["voter_list"]["id"])
    assert parent["total_entry_count"] == 3
    assert parent["complete_entry_count"] == 3


def test_entries_can_be_listed_by_list_and_by_eligibility_outcome():
    """Filtering the entry listing by its list and by an eligibility outcome returns only the
    matching voters, and the total count reflects the filter.

    PRD: "Entry listings may be filtered by `voter_list_id`, by `classification_id`, or by `eligibility_status`."

    Design: Corner/endpoints/voter_list_entry_crud_round_trips_and_recomputes_its_parent
    """
    ctx = _draft_list_with_two_complete_and_one_incomplete_entry()
    voter_list_id = ctx["voter_list"]["id"]
    validate_success(
        api_client.update_voter_list_entry(
            ctx["incomplete_entry"]["id"], {"on_leave_type": "PERMANENT_LAYOFF"}, ANALYST
        )
    )

    resp = api_client.list_voter_list_entries(
        DIRECTOR,
        params={
            "voter_list_id": voter_list_id,
            "eligibility_status": "ELIGIBLE",
            "limit": 2,
            "offset": 0,
        },
    )
    rows, _ = validate_paginated(resp)
    assert len(rows) == 2
    assert all(row["eligibility_status"] == "ELIGIBLE" for row in rows)
    assert_pagination_meta(resp, limit=2, offset=0, total_count=2, has_more=False)

    ineligible = api_client.list_voter_list_entries(
        DIRECTOR, params={"voter_list_id": voter_list_id, "eligibility_status": "INELIGIBLE"}
    )
    ineligible_rows, _ = validate_paginated(ineligible)
    assert len(ineligible_rows) == 1
    assert ineligible_rows[0]["id"] == ctx["incomplete_entry"]["id"]


def test_reading_an_entry_that_does_not_exist_reports_the_entry_not_found_code():
    """An unknown identifier in the path is resolved first and answers with the voter entry's
    own not-found code.

    PRD: "The identifier in the path is resolved first: if no such row exists, the request fails with that resource type's own not-found code — `ERR_PETITION_NOT_FOUND`, `ERR_CLASSIFICATION_NOT_FOUND`, `ERR_ELECTION_AGREEMENT_NOT_FOUND`, `ERR_VOTER_LIST_NOT_FOUND`, `ERR_VOTER_LIST_ENTRY_NOT_FOUND`, `ERR_SUPERVISOR_NOT_FOUND`, `ERR_CAMPAIGN_COMMUNICATION_NOT_FOUND`, `ERR_ELECTION_ROUND_NOT_FOUND`, `ERR_POLL_SESSION_NOT_FOUND`, `ERR_CHALLENGED_BALLOT_NOT_FOUND`, `ERR_OBJECTION_NOT_FOUND` or `ERR_ULP_CHARGE_NOT_FOUND` — all with HTTP 404."

    Design: Corner/endpoints/voter_list_entry_crud_round_trips_and_recomputes_its_parent
    """
    resp = api_client.get_voter_list_entry(NON_EXISTENT_UUID, DIRECTOR)
    validate_error(resp, ApiErrorId.ERR_VOTER_LIST_ENTRY_NOT_FOUND)

    patched = api_client.update_voter_list_entry(
        NON_EXISTENT_UUID, {"personal_phone": "+1-555-0101"}, ANALYST
    )
    validate_error(patched, ApiErrorId.ERR_VOTER_LIST_ENTRY_NOT_FOUND)


# ---------------------------------------------------------------------------
# Preconditions on the polling action endpoints
# ---------------------------------------------------------------------------
TWO_GATE_SESSIONS = [
    {
        "location_code": "GATE_A",
        "session_start_at": "2026-09-01T08:00:00Z",
        "session_end_at": "2026-09-01T12:00:00Z",
        "method": "MANUAL",
    },
    {
        "location_code": "GATE_B",
        "session_start_at": "2026-09-01T08:00:00Z",
        "session_end_at": "2026-09-01T12:00:00Z",
        "method": "MANUAL",
    },
]


def test_the_polls_cannot_be_opened_one_second_before_the_scheduled_instant():
    """With an accepted list and a session laid out, the opening still waits for the clock to
    reach the scheduled opening instant, which is inclusive.

    PRD: "Four conditions must hold beyond the posture gate: the case must hold a voter list in `ACCEPTED` status, and if it does not the request is refused with `ERR_VOTER_LIST_NOT_ACCEPTED`; the round's `scheduled_session_count` must be at least 1; and the logical clock must have reached the round's `polls_open_at`, since opening early is refused with `ERR_POLLS_NOT_YET_OPEN`."

    Design: Corner/endpoints/polling_action_endpoints_enforce_their_own_preconditions
    """
    ctx = setup_sessions_laid_out()
    round_id = ctx["round"]["id"]
    assert_instant_equals(ctx["round"]["polls_open_at"], "2026-09-01T08:00:00Z")
    assert ctx["round"]["scheduled_session_count"] == 1
    assert read_voter_list(ctx["voter_list"]["id"])["status"] == "ACCEPTED"

    set_clock("2026-09-01T07:59:59Z")
    resp = api_client.open_polls(round_id, BOARD)
    validate_error(resp, ApiErrorId.ERR_POLLS_NOT_YET_OPEN)
    assert read_round(round_id)["status"] == "SCHEDULED"

    set_clock("2026-09-01T08:00:00Z")
    opened = api_client.open_polls(round_id, BOARD)
    validate_success(opened)
    round_row = get_success_data(opened)
    assert_election_round(round_row)
    assert round_row["status"] == "POLLS_OPEN"


def test_closing_a_session_moves_one_session_out_of_the_scheduled_bucket():
    """Closing one of two sessions records its counts and shifts exactly one session from the
    scheduled bucket to the closed bucket, leaving the round open.

    PRD: "Closing moves the session to the terminal `CLOSED` state, stamps `closed_at`, records the three counts, raises the round's `closed_session_count` by 1 and lowers its `scheduled_session_count` by 1."

    Design: Corner/endpoints/polling_action_endpoints_enforce_their_own_preconditions
    """
    ctx = setup_polls_open(session_specs=TWO_GATE_SESSIONS)
    round_id = ctx["round"]["id"]
    before = read_round(round_id)
    assert before["scheduled_session_count"] == 2
    assert before["closed_session_count"] == 0

    set_clock("2026-09-01T12:00:00Z")
    resp = api_client.close_poll_session(
        ctx["sessions"][0]["id"], close_session_payload(), BOARD
    )
    validate_success(resp)
    closed = get_success_data(resp)
    assert_poll_session(closed)
    assert closed["status"] == "CLOSED"
    assert closed["votes_for_count"] == 30
    assert closed["votes_against_count"] == 25
    assert closed["void_count"] == 1
    assert_instant_equals(closed["closed_at"], "2026-09-01T12:00:00Z")

    after = read_round(round_id)
    assert after["scheduled_session_count"] == 1
    assert after["closed_session_count"] == 1
    assert after["status"] == "POLLS_OPEN"


def test_a_session_that_has_already_closed_cannot_be_closed_again():
    """A second closing of the same session is refused and neither the session's counts nor
    the round's session counters move.

    PRD: "A session that is already closed, or one that was cancelled, is refused with `ERR_POLL_SESSION_STATUS_INVALID`."

    Design: Corner/endpoints/polling_action_endpoints_enforce_their_own_preconditions
    """
    ctx = setup_polls_open(session_specs=TWO_GATE_SESSIONS)
    round_id = ctx["round"]["id"]
    session_id = ctx["sessions"][0]["id"]

    set_clock("2026-09-01T12:00:00Z")
    validate_success(
        api_client.close_poll_session(session_id, close_session_payload(), BOARD)
    )

    resp = api_client.close_poll_session(
        session_id,
        close_session_payload(votes_for_count=11, votes_against_count=9, void_count=0),
        BOARD,
    )
    validate_error(resp, ApiErrorId.ERR_POLL_SESSION_STATUS_INVALID)

    stored = read_poll_session(session_id)
    assert stored["status"] == "CLOSED"
    assert stored["votes_for_count"] == 30
    assert stored["votes_against_count"] == 25
    assert stored["void_count"] == 1

    round_row = read_round(round_id)
    assert round_row["scheduled_session_count"] == 1
    assert round_row["closed_session_count"] == 1
    assert round_row["status"] == "POLLS_OPEN"


# ---------------------------------------------------------------------------
# Segregating a challenged ballot between a session and a voter entry
# ---------------------------------------------------------------------------
def test_segregating_a_ballot_raises_the_session_and_round_counters_together():
    """A challenged ballot opens unresolved, counts against its session, and counts as a real
    ballot in the box on its round.

    PRD: "A segregated ballot begins with `resolution` `OPEN`, `reopen_count` 0 and no `resolved_at`; it raises the session's `challenged_ballot_count` by 1, the round's `challenged_open_count` by 1, and the round's `ballots_cast_total` by 1, because a challenged ballot is a real ballot that entered the box."

    Design: Corner/endpoints/a_challenged_ballot_links_a_session_to_a_voter_entry
    """
    ctx = setup_polls_open(session_specs=TWO_GATE_SESSIONS, entry_count=3)
    session_id = ctx["sessions"][0]["id"]
    round_id = ctx["round"]["id"]
    before = read_round(round_id)
    assert before["challenged_open_count"] == 0
    assert before["ballots_cast_total"] == 0

    resp = api_client.create_challenged_ballot(
        create_challenged_ballot_payload(
            session_id, voter_list_entry_id=ctx["entries"][0]["id"]
        ),
        BOARD,
    )
    validate_success(resp, 201)
    ballot = get_success_data(resp)
    assert_challenged_ballot(ballot)
    assert ballot["poll_session_id"] == session_id
    assert ballot["voter_list_entry_id"] == ctx["entries"][0]["id"]
    assert ballot["resolution"] == "OPEN"
    assert ballot["reopen_count"] == 0
    assert ballot.get("resolved_at") is None

    assert read_poll_session(session_id)["challenged_ballot_count"] == 1
    after = read_round(round_id)
    assert after["challenged_open_count"] == 1
    assert after["ballots_cast_total"] == 1
    assert_ballot_conservation(after)


def test_the_same_voter_cannot_be_challenged_twice_at_one_session():
    """A repeat challenge against the same voter at the same session is refused, while the same
    voter may be challenged again at a different session.

    PRD: "The same voter entry may not be challenged twice at the same session, and a repeat is `ERR_DUPLICATE_CHALLENGED_BALLOT`."

    Design: Corner/endpoints/a_challenged_ballot_links_a_session_to_a_voter_entry
    """
    ctx = setup_polls_open(session_specs=TWO_GATE_SESSIONS, entry_count=3)
    first_session, second_session = ctx["sessions"][0], ctx["sessions"][1]
    entry_id = ctx["entries"][0]["id"]
    segregate_ballot(first_session["id"], voter_list_entry_id=entry_id)

    resp = api_client.create_challenged_ballot(
        create_challenged_ballot_payload(
            first_session["id"],
            voter_list_entry_id=entry_id,
            challenger_party="UNION",
            basis="IDENTITY",
        ),
        BOARD,
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_CHALLENGED_BALLOT)
    assert read_poll_session(first_session["id"])["challenged_ballot_count"] == 1

    elsewhere = api_client.create_challenged_ballot(
        create_challenged_ballot_payload(
            second_session["id"], voter_list_entry_id=entry_id
        ),
        BOARD,
    )
    validate_success(elsewhere, 201)

    round_row = read_round(ctx["round"]["id"])
    assert round_row["challenged_open_count"] == 2
    assert round_row["ballots_cast_total"] == 2
    assert_ballot_conservation(round_row)


def test_challenged_ballots_can_be_listed_by_session_by_voter_and_by_resolution():
    """Each of the three declared filters narrows the challenged-ballot listing.

    PRD: "Challenged ballots may be listed by `poll_session_id`, by `voter_list_entry_id` or by `resolution`."

    Design: Corner/endpoints/a_challenged_ballot_links_a_session_to_a_voter_entry
    """
    ctx = setup_polls_open(session_specs=TWO_GATE_SESSIONS, entry_count=3)
    first_session, second_session = ctx["sessions"][0], ctx["sessions"][1]
    first_entry, second_entry = ctx["entries"][0]["id"], ctx["entries"][1]["id"]
    segregate_ballot(first_session["id"], voter_list_entry_id=first_entry)
    segregate_ballot(first_session["id"], voter_list_entry_id=second_entry)
    segregate_ballot(second_session["id"], voter_list_entry_id=first_entry)

    by_session = api_client.list_challenged_ballots(
        BOARD, params={"poll_session_id": first_session["id"]}
    )
    session_rows, _ = validate_paginated(by_session)
    assert len(session_rows) == 2
    assert all(row["poll_session_id"] == first_session["id"] for row in session_rows)

    by_voter = api_client.list_challenged_ballots(
        BOARD, params={"voter_list_entry_id": first_entry}
    )
    voter_rows, _ = validate_paginated(by_voter)
    assert len(voter_rows) == 2
    assert all(row["voter_list_entry_id"] == first_entry for row in voter_rows)

    by_resolution = api_client.list_challenged_ballots(BOARD, params={"resolution": "OPEN"})
    open_rows, _ = validate_paginated(by_resolution)
    assert len(open_rows) == 3

    counted = api_client.list_challenged_ballots(BOARD, params={"resolution": "COUNTED_FOR"})
    counted_rows, _ = validate_paginated(counted)
    assert counted_rows == []


def test_a_ballot_naming_an_unknown_session_or_voter_reports_that_types_not_found_code():
    """Each foreign key in the body is resolved and answers with the referenced type's own
    not-found code.

    PRD: "Only then are the foreign keys in the body resolved, in the order the endpoint declares its input fields, each producing the referenced type's own not-found code."

    Design: Corner/endpoints/a_challenged_ballot_links_a_session_to_a_voter_entry
    """
    ctx = setup_polls_open(session_specs=TWO_GATE_SESSIONS, entry_count=3)
    session_id = ctx["sessions"][0]["id"]
    entry_id = ctx["entries"][0]["id"]

    unknown_session = api_client.create_challenged_ballot(
        create_challenged_ballot_payload(NON_EXISTENT_UUID, voter_list_entry_id=entry_id),
        BOARD,
    )
    validate_error(unknown_session, ApiErrorId.ERR_POLL_SESSION_NOT_FOUND)

    unknown_entry = api_client.create_challenged_ballot(
        create_challenged_ballot_payload(session_id, voter_list_entry_id=NON_EXISTENT_UUID),
        BOARD,
    )
    validate_error(unknown_entry, ApiErrorId.ERR_VOTER_LIST_ENTRY_NOT_FOUND)

    round_row = read_round(ctx["round"]["id"])
    assert round_row["ballots_cast_total"] == 0
    assert round_row["challenged_open_count"] == 0


# ---------------------------------------------------------------------------
# The aggregates a single case read has to expose at once
# ---------------------------------------------------------------------------
MIXED_CLASSIFICATION_SPECS = [
    {
        "code": "PROD", "title": "Production Operator", "headcount": 60,
        "avg_hourly_wage_cents": 2400, "employer_position": "INCLUDE",
        "union_position": "INCLUDE", "supervision_overlap": 88, "skills_overlap": 90,
        "functional_integration": 92, "interchange_rate": 74, "work_conditions_overlap": 95,
    },
    {
        "code": "MAINT", "title": "Maintenance Technician", "headcount": 30,
        "avg_hourly_wage_cents": 3200, "employer_position": "INCLUDE",
        "union_position": "INCLUDE", "supervision_overlap": 80, "skills_overlap": 70,
        "functional_integration": 85, "interchange_rate": 60, "work_conditions_overlap": 90,
    },
    {
        "code": "QC", "title": "Quality Inspector", "headcount": 12,
        "avg_hourly_wage_cents": 2900, "employer_position": "EXCLUDE",
        "union_position": "INCLUDE", "supervision_overlap": 41, "skills_overlap": 55,
        "functional_integration": 61, "interchange_rate": 21, "work_conditions_overlap": 71,
    },
]


def _case_with_two_classifications_in_and_one_out():
    """A verified case whose three classifications have all been ruled."""
    return setup_soi_verified(
        rulings=["INCLUDED", "INCLUDED", "EXCLUDED"],
        classification_specs=MIXED_CLASSIFICATION_SPECS,
    )


def test_the_case_read_splits_the_classified_headcount_across_its_buckets():
    """Every ruling has moved its classification's headcount out of the pending bucket, and the
    case read shows the three buckets reconciling to the classified total.

    PRD: "When the ruling lands, the classification's `headcount` moves out of the case's `pending_headcount` and into either `included_headcount` or `excluded_headcount` according to the ruling, the rationale is written, the conservation identity is re-checked, and the petition's `version` increments."

    Design: Corner/endpoints/the_petition_read_exposes_every_derived_aggregate_at_once
    """
    ctx = _case_with_two_classifications_in_and_one_out()

    petition = read_petition(ctx["petition"]["id"])
    assert_petition(petition)
    assert petition["total_classified_headcount"] == 102
    assert petition["included_headcount"] == 90
    assert petition["excluded_headcount"] == 12
    assert petition["pending_headcount"] == 0
    assert_headcount_conservation(petition)


def test_the_case_read_exposes_the_core_wage_frozen_by_the_first_scoring_call():
    """The headcount-weighted average of the two undisputed classifications is frozen on the
    case together with the instant it was calculated.

    PRD: "For that group, multiply each classification's `headcount` by its `avg_hourly_wage_cents`, sum those products, divide the sum by the total headcount of the group, and round half-up to a whole cent; the result is written to `core_avg_hourly_wage_cents` and the instant of the calculation is written to `core_wage_locked_at`."

    Design: Corner/endpoints/the_petition_read_exposes_every_derived_aggregate_at_once
    """
    ctx = _case_with_two_classifications_in_and_one_out()

    petition = read_petition(ctx["petition"]["id"])
    assert petition["core_avg_hourly_wage_cents"] == 2667
    assert_instant_equals(petition["core_wage_locked_at"], "2026-08-03T09:00:00Z")


def test_the_case_read_reports_the_showing_basis_percentage_and_verdict_together():
    """With scope settled the showing is measured against the included headcount, and the read
    carries the basis, the percentage and the verdict at once.

    PRD: "If every classification on the case has been ruled — that is, each one's `scope_ruling` is either `INCLUDED` or `EXCLUDED` — the basis is `AS_RULED` and the denominator is the case's `included_headcount`, because once scope is settled only the classifications actually inside the voting unit form the base."

    Design: Corner/endpoints/the_petition_read_exposes_every_derived_aggregate_at_once
    """
    ctx = _case_with_two_classifications_in_and_one_out()

    petition = read_petition(ctx["petition"]["id"])
    assert petition["case_status"] == "SOI_VERIFIED"
    assert petition["showing_headcount_basis"] == "AS_RULED"
    assert petition["submitted_card_count"] == 40
    assert petition["valid_card_count"] == 30
    assert float(petition["showing_of_interest_pct"]) == 33.33
    assert petition["showing_verdict"] == "SUFFICIENT"


def test_cases_filter_by_lifecycle_and_classifications_filter_by_ruling():
    """The case listing narrows by the two state dimensions and the classification listing by
    the ruling recorded on each row.

    PRD: "Classification listings may be narrowed by `petition_id` or by `scope_ruling`, and case listings by `case_status`, by `case_posture`, or by `certified_round_id` for the narrow question of which case rests on a particular round."

    Design: Corner/endpoints/the_petition_read_exposes_every_derived_aggregate_at_once
    """
    ctx = _case_with_two_classifications_in_and_one_out()
    petition_id = ctx["petition"]["id"]

    verified = api_client.list_petitions(
        DIRECTOR, params={"case_status": "SOI_VERIFIED", "case_posture": "OPEN"}
    )
    verified_rows, _ = validate_paginated(verified)
    assert [row["id"] for row in verified_rows] == [petition_id]

    elsewhere = api_client.list_petitions(DIRECTOR, params={"case_status": "CERTIFIED"})
    elsewhere_rows, _ = validate_paginated(elsewhere)
    assert elsewhere_rows == []

    included = api_client.list_classifications(
        DIRECTOR, params={"petition_id": petition_id, "scope_ruling": "INCLUDED"}
    )
    included_rows, _ = validate_paginated(included)
    assert sorted(row["code"] for row in included_rows) == ["MAINT", "PROD"]
    for row in included_rows:
        assert_classification(row)

    excluded = api_client.list_classifications(
        DIRECTOR, params={"petition_id": petition_id, "scope_ruling": "EXCLUDED"}
    )
    excluded_rows, _ = validate_paginated(excluded)
    assert [row["code"] for row in excluded_rows] == ["QC"]


# ---------------------------------------------------------------------------
# Opening a fresh voter list over a draft one
# ---------------------------------------------------------------------------
def test_a_fresh_list_supersedes_the_draft_it_replaces_and_keeps_its_entries():
    """The new list starts empty at the arrangement's due instant while the draft it replaces
    moves to the terminal superseded state with its entries intact.

    PRD: "A successful create copies `due_at` from the arrangement's `voter_list_due_at`, starts the list at `status` `DRAFT`, and — this is the point of opening a fresh list — **supersedes** any list on the same case that is still `DRAFT` or `DEFICIENT`, moving each to the terminal `SUPERSEDED` state where it keeps its entries and its `cure_deadline_at` for the record but can never be submitted again."

    Design: Corner/endpoints/a_new_voter_list_supersedes_the_draft_it_replaces
    """
    ctx = setup_election_set()
    petition_id = ctx["petition"]["id"]
    agreement = ctx["agreement"]
    first = create_voter_list(petition_id, agreement["id"])
    add_complete_entries(first["id"], ctx["classifications"][0]["id"], 2)
    assert read_voter_list(first["id"])["total_entry_count"] == 2

    resp = api_client.create_voter_list(
        create_voter_list_payload(petition_id, agreement["id"], petition_version(petition_id)),
        DIRECTOR,
    )
    validate_success(resp, 201)
    replacement = get_success_data(resp)
    assert_voter_list(replacement)
    assert replacement["status"] == "DRAFT"
    assert replacement["total_entry_count"] == 0
    assert replacement["complete_entry_count"] == 0
    assert_instants_equal(replacement["due_at"], agreement["voter_list_due_at"])

    superseded = read_voter_list(first["id"])
    assert superseded["status"] == "SUPERSEDED"
    assert superseded["total_entry_count"] == 2

    entries = api_client.list_voter_list_entries(
        DIRECTOR, params={"voter_list_id": first["id"]}
    )
    entry_rows, _ = validate_paginated(entries)
    assert len(entry_rows) == 2


def test_opening_a_list_moves_the_case_version_so_the_same_create_cannot_be_replayed():
    """The create advances the petition version by exactly one, which is why replaying it with
    the version the caller first observed conflicts.

    PRD: "On success the petition's `version` increments by exactly 1, so replaying the same create with the same asserted value conflicts."

    Design: Corner/endpoints/a_new_voter_list_supersedes_the_draft_it_replaces
    """
    ctx = setup_election_set()
    petition_id = ctx["petition"]["id"]
    agreement_id = ctx["agreement"]["id"]
    observed_version = petition_version(petition_id)

    resp = api_client.create_voter_list(
        create_voter_list_payload(petition_id, agreement_id, observed_version), DIRECTOR
    )
    validate_success(resp, 201)
    assert read_petition(petition_id)["version"] == observed_version + 1

    replay = api_client.create_voter_list(
        create_voter_list_payload(petition_id, agreement_id, observed_version), DIRECTOR
    )
    validate_error(replay, ApiErrorId.ERR_STALE_PETITION_VERSION)

    listed = api_client.list_voter_lists(DIRECTOR, params={"petition_id": petition_id})
    rows, _ = validate_paginated(listed)
    assert len(rows) == 1, "the conflicted replay must not have written a second list"


def test_voter_lists_can_be_listed_by_case_by_arrangement_and_by_status():
    """After a supersession each of the three declared list filters returns the row it should.

    PRD: "Lists may be listed by `petition_id`, by `election_agreement_id`, or by `status`."

    Design: Corner/endpoints/a_new_voter_list_supersedes_the_draft_it_replaces
    """
    ctx = setup_election_set()
    petition_id = ctx["petition"]["id"]
    agreement_id = ctx["agreement"]["id"]
    first = create_voter_list(petition_id, agreement_id)
    replacement = create_voter_list(petition_id, agreement_id)

    by_case = api_client.list_voter_lists(DIRECTOR, params={"petition_id": petition_id})
    case_rows, _ = validate_paginated(by_case)
    assert len(case_rows) == 2

    by_arrangement = api_client.list_voter_lists(
        DIRECTOR, params={"election_agreement_id": agreement_id}
    )
    arrangement_rows, _ = validate_paginated(by_arrangement)
    assert len(arrangement_rows) == 2

    drafts = api_client.list_voter_lists(DIRECTOR, params={"status": "DRAFT"})
    draft_rows, _ = validate_paginated(drafts)
    assert [row["id"] for row in draft_rows] == [replacement["id"]]

    superseded = api_client.list_voter_lists(DIRECTOR, params={"status": "SUPERSEDED"})
    superseded_rows, _ = validate_paginated(superseded)
    assert [row["id"] for row in superseded_rows] == [first["id"]]
