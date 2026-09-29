"""The pay program's two independent lifecycles and the cyclic disclosure review loop.

A pay program tracks its design in `design_status` and the shareholder verdict in
`vote_status`, and the two dimensions advance on their own schedules: a failed
say-on-pay vote leaves the design pinned at `DISCLOSED` and only remediation
closes it. A disclosure section is not a one-way ladder either: it re-enters
`DRAFTING` from review as often as counsel asks, counting the loops in
`revision_round`, and only the `CD_AND_A` section's filing moves the program.
"""

import pytest

from test_helpers import (
    CHAIR_ONE,
    COUNSEL_ONE,
    COUNSEL_TWO,
    ApiErrorId,
    api_client,
    assert_money,
    assert_screen_stale_keeps_last_scores,
    carry_cda_draft_to_filed,
    certify_vote,
    create_cda_draft,
    create_screen,
    file_cda_draft,
    legal_clear_cda_draft,
    make_comp_committee_chair_headers,
    make_securities_counsel_headers,
    read_cda_draft,
    read_pay_program,
    read_screen,
    remediate_program,
    remediation_payload,
    request_cda_revision,
    rerun_screen,
    setup_disclosed_program,
    setup_pay_program,
    setup_program_with_outreach_coverage,
    submit_cda_review,
    validate_error,
    vote_certification_payload,
)


# ===========================================================================
# The program's vote dimension moves while its design dimension holds
# ===========================================================================
def _disclosed_program_with_coverage():
    """A DISCLOSED program, one current ISS screen and outreach coverage 31.00.

    The two held engagements are BlackRock at 20.00 percent and Vanguard at
    11.00 percent of shares outstanding, so the program's coverage clears the
    30.00 percent remediation floor.
    """
    env = setup_pay_program(metric_curves=("ADJ_EPS_LINEAR", "COST_RATIO_STEP"))
    env = setup_disclosed_program(env=env)
    env = setup_program_with_outreach_coverage(env=env)
    # Holding the engagements withdrew the screen's claim to currency; re-run it
    # so it is current again immediately before the ballot is certified.
    env["screens"]["ISS"] = rerun_screen(env["screens"]["ISS"]["id"])
    return env


def test_failed_say_on_pay_vote_leaves_the_design_dimension_at_disclosed():
    """A ballot that fails moves only the vote dimension of the program.

    "On the **failing** branch, `vote_status` becomes `FAILED`, `enhanced_engagement_required` is true, `design_status` stays at `DISCLOSED` — a failed vote does not close a program — and `alignment_status` is set to `MISALIGNED`."

    "Otherwise `support_pct` is `votes_for` divided by that denominator, multiplied by 100 and rounded half-up to two decimal places."

    "Caused by that, every `SCREENED` screen of the program moves to `STALE`, the failed vote being a new policy input in its own right."

    Design: Difficulty/non_linear_state_machine/program_vote_dimension_advances_while_design_dimension_holds
    """
    env = _disclosed_program_with_coverage()
    program_id = env["program"]["id"]
    screen_before = env["screens"]["ISS"]
    assert screen_before["status"] == "SCREENED"

    before = read_pay_program(program_id)
    assert before["design_status"] == "DISCLOSED"
    assert before["vote_status"] == "NOT_VOTED"
    assert_money(before["outreach_coverage_pct"], 31.00, "outreach_coverage_pct")

    certify_vote(program_id, 400000, 600000)

    program = read_pay_program(program_id)
    assert_money(program["support_pct"], 40.00, "support_pct")
    assert program["vote_status"] == "FAILED"
    assert program["enhanced_engagement_required"] is True
    assert program["design_status"] == "DISCLOSED", (
        "a failed vote does not close a program"
    )
    assert program["alignment_status"] == "MISALIGNED"
    assert_money(program["outreach_coverage_pct"], 31.00, "outreach_coverage_pct")

    assert_screen_stale_keeps_last_scores(
        screen_before, read_screen(program_id, screen_before["id"])
    )


def test_remediation_closes_the_design_dimension_after_the_vote_failed():
    """Remediation is the step that finally moves the design dimension to CLOSED.

    "A `CompCommitteeChair` records the program changes made in response, supplying a mandatory `feedback_summary`, and the program moves `vote_status` `FAILED → REMEDIATED` while `design_status` advances `DISCLOSED → CLOSED`, `enhanced_engagement_required` is cleared to false and the program's `version` increments."

    Design: Difficulty/non_linear_state_machine/program_vote_dimension_advances_while_design_dimension_holds
    """
    env = _disclosed_program_with_coverage()
    program_id = env["program"]["id"]

    certify_vote(program_id, 400000, 600000)
    failed = read_pay_program(program_id)
    assert failed["vote_status"] == "FAILED"
    assert failed["design_status"] == "DISCLOSED"

    remediate_program(program_id)

    program = read_pay_program(program_id)
    assert program["vote_status"] == "REMEDIATED"
    assert program["design_status"] == "CLOSED"
    assert program["enhanced_engagement_required"] is False
    assert program["version"] > failed["version"]


def test_remediation_before_the_vote_reaches_failed_is_rejected():
    """The vote dimension must actually be at FAILED before remediation is open.

    "Remediation is refused on any program whose `vote_status` is not `FAILED`, with `ERR_VOTE_NOT_FAILED`, and — the substantive gate — it requires that the committee have actually engaged holders of at least 30.00 percent of shares outstanding: an `outreach_coverage_pct` below 30.00 is refused with `ERR_OUTREACH_COVERAGE_INSUFFICIENT`."

    Design: Difficulty/non_linear_state_machine/program_vote_dimension_advances_while_design_dimension_holds
    """
    env = _disclosed_program_with_coverage()
    program_id = env["program"]["id"]

    # Coverage is 31.00, comfortably over the substantive floor, so the only
    # remaining obstacle is that the vote dimension is still NOT_VOTED.
    before = read_pay_program(program_id)
    assert before["vote_status"] == "NOT_VOTED"
    assert_money(before["outreach_coverage_pct"], 31.00, "outreach_coverage_pct")

    response = api_client.remediate_pay_program(
        program_id,
        remediation_payload("STI weighting reduced and a relative TSR modifier added."),
        make_comp_committee_chair_headers(CHAIR_ONE),
    )
    validate_error(response, ApiErrorId.ERR_VOTE_NOT_FAILED, 409)

    after = read_pay_program(program_id)
    assert after["vote_status"] == "NOT_VOTED"
    assert after["design_status"] == "DISCLOSED"


def test_second_vote_certification_is_rejected_once_the_ballot_is_certified():
    """The vote dimension leaves NOT_VOTED exactly once.

    "The program's `vote_status` must still be `NOT_VOTED`, or the answer is `ERR_VOTE_ALREADY_CERTIFIED`."

    Design: Difficulty/non_linear_state_machine/program_vote_dimension_advances_while_design_dimension_holds
    """
    env = _disclosed_program_with_coverage()
    program_id = env["program"]["id"]

    certify_vote(program_id, 400000, 600000)
    assert read_pay_program(program_id)["vote_status"] == "FAILED"

    response = api_client.certify_vote(
        program_id,
        vote_certification_payload(900000, 100000, 0),
        make_comp_committee_chair_headers(CHAIR_ONE),
    )
    validate_error(response, ApiErrorId.ERR_VOTE_ALREADY_CERTIFIED, 409)

    program = read_pay_program(program_id)
    assert program["vote_status"] == "FAILED"
    assert_money(program["support_pct"], 40.00, "support_pct")


@pytest.mark.parametrize(
    "votes_for,votes_against,expected_support,expected_design,expected_enhanced",
    [
        (600000, 400000, 60.00, "DISCLOSED", True),
        (800000, 200000, 80.00, "CLOSED", False),
    ],
)
def test_passing_vote_moves_the_design_dimension_only_above_the_responsiveness_trigger(
    votes_for, votes_against, expected_support, expected_design, expected_enhanced
):
    """A vote that carries closes the design only when support reaches 70.00.

    "If support reached 70.00 or more, the design dimension also advances `DISCLOSED → CLOSED` and the program is done."

    "If support passed but fell short of the responsiveness trigger, `design_status` stays at `DISCLOSED` and `enhanced_engagement_required` stands as a standing obligation until the committee remediates."

    Design: Difficulty/non_linear_state_machine/program_vote_dimension_advances_while_design_dimension_holds
    """
    env = setup_disclosed_program()
    program_id = env["program"]["id"]
    assert read_pay_program(program_id)["design_status"] == "DISCLOSED"

    certify_vote(program_id, votes_for, votes_against)

    program = read_pay_program(program_id)
    assert_money(program["support_pct"], expected_support, "support_pct")
    assert program["vote_status"] == "PASSED"
    assert program["design_status"] == expected_design
    assert program["enhanced_engagement_required"] is expected_enhanced


def test_failed_vote_returns_filed_sections_other_than_the_cda_to_drafting():
    """The failure cascade rewrites every filed section except the CD&A narrative.

    "Caused by that, every `LEGAL_CLEARED` section of the program returns to `DRAFTING` with `revision_round` incremented and `cleared_by_user_id` cleared; every `FILED` section other than the `CD_AND_A` narrative likewise returns to `DRAFTING` for the responsiveness rewrite."

    Design: Difficulty/non_linear_state_machine/program_vote_dimension_advances_while_design_dimension_holds
    """
    env = setup_disclosed_program()
    program_id = env["program"]["id"]
    cda_id = env["cda_draft"]["id"]

    summary = carry_cda_draft_to_filed(
        program_id,
        section_code="SUMMARY_COMP_TABLE",
        word_count=900,
        required_tables_included=True,
        author_user_id=COUNSEL_ONE,
        clearer_user_id=COUNSEL_TWO,
    )
    assert summary["status"] == "FILED"
    assert summary["revision_round"] == 0

    certify_vote(program_id, 400000, 600000)
    assert read_pay_program(program_id)["vote_status"] == "FAILED"

    bounced = read_cda_draft(program_id, summary["id"])
    assert bounced["status"] == "DRAFTING"
    assert bounced["revision_round"] == 1
    assert bounced["cleared_by_user_id"] is None

    narrative = read_cda_draft(program_id, cda_id)
    assert narrative["status"] == "FILED", (
        "the CD_AND_A narrative is the one filed section the failure cascade leaves alone"
    )


# ===========================================================================
# The disclosure section's cyclic review loop
# ===========================================================================
def _committee_approved_program_with_current_iss_screen():
    """A COMMITTEE_APPROVED program carrying one current ISS screen."""
    env = setup_pay_program()
    env["screens"]["ISS"] = create_screen(env["program"]["id"], "ISS")
    return env


def test_disclosure_section_reenters_review_until_the_tables_are_attached():
    """The review loop runs twice before clearance succeeds, counting each pass.

    "Bouncing a section back — permitted to `SecuritiesCounsel` and `CompCommitteeChair`, with an optional `feedback_summary` — returns it `IN_REVIEW → DRAFTING`, increments `revision_round` by one, clears `cleared_by_user_id` and increments `version`."

    "The section's `required_tables_included` must be true, and additionally, when the section is the `CD_AND_A` narrative, its `word_count` must be at least 1500 — other section codes carry no length floor — and a failure of either condition is `ERR_CDA_TABLES_INCOMPLETE`."

    Design: Difficulty/non_linear_state_machine/cda_draft_revision_cycle_reenters_review_with_incremented_round
    """
    env = _committee_approved_program_with_current_iss_screen()
    program_id = env["program"]["id"]

    draft = create_cda_draft(program_id, "SUMMARY_COMP_TABLE", 900, False, COUNSEL_ONE)
    assert draft["status"] == "DRAFTING"
    assert draft["revision_round"] == 0
    assert draft["cleared_by_user_id"] is None

    # First pass through review, bounced straight back.
    submit_cda_review(draft["id"], COUNSEL_ONE)
    assert read_cda_draft(program_id, draft["id"])["status"] == "IN_REVIEW"
    request_cda_revision(draft["id"], COUNSEL_TWO)
    first = read_cda_draft(program_id, draft["id"])
    assert first["status"] == "DRAFTING"
    assert first["revision_round"] == 1

    # Second pass: the word count grew but the required tables are still missing.
    submit_cda_review(
        draft["id"], COUNSEL_ONE, word_count=1200, required_tables_included=False
    )
    blocked = api_client.legal_clear_cda_draft(
        draft["id"], make_securities_counsel_headers(COUNSEL_TWO)
    )
    validate_error(blocked, ApiErrorId.ERR_CDA_TABLES_INCOMPLETE, 422)
    assert read_cda_draft(program_id, draft["id"])["status"] == "IN_REVIEW", (
        "a refused clearance leaves the section in review rather than advancing it"
    )

    request_cda_revision(draft["id"], COUNSEL_TWO)
    second = read_cda_draft(program_id, draft["id"])
    assert second["status"] == "DRAFTING"
    assert second["revision_round"] == 2

    # Third pass: the tables are attached, so clearance is available.
    submit_cda_review(
        draft["id"], COUNSEL_ONE, word_count=1800, required_tables_included=True
    )
    resubmitted = read_cda_draft(program_id, draft["id"])
    assert resubmitted["status"] == "IN_REVIEW"
    assert resubmitted["word_count"] == 1800
    assert resubmitted["required_tables_included"] is True
    assert resubmitted["revision_round"] == 2

    cleared = legal_clear_cda_draft(draft["id"], COUNSEL_TWO)
    assert cleared["status"] == "LEGAL_CLEARED"
    assert cleared["cleared_by_user_id"] == COUNSEL_TWO
    assert cleared["authored_by_user_id"] == COUNSEL_ONE

    assert read_pay_program(program_id)["design_status"] == "COMMITTEE_APPROVED"


def test_revision_round_counts_every_completed_review_loop():
    """The loop is traversable repeatedly and the round is the count of loops.

    "That loop, `DRAFTING → IN_REVIEW → DRAFTING`, may run any number of times, and `revision_round` is the count of the loops."

    Design: Difficulty/non_linear_state_machine/cda_draft_revision_cycle_reenters_review_with_incremented_round
    """
    env = _committee_approved_program_with_current_iss_screen()
    program_id = env["program"]["id"]

    draft = create_cda_draft(program_id, "SUMMARY_COMP_TABLE", 900, False, COUNSEL_ONE)
    assert draft["revision_round"] == 0

    for expected_round in (1, 2, 3):
        submit_cda_review(draft["id"], COUNSEL_ONE)
        in_review = read_cda_draft(program_id, draft["id"])
        assert in_review["status"] == "IN_REVIEW"
        assert in_review["revision_round"] == expected_round - 1

        request_cda_revision(draft["id"], COUNSEL_TWO)
        drafting = read_cda_draft(program_id, draft["id"])
        assert drafting["status"] == "DRAFTING", (
            "the section returns to the same earlier state, it does not advance"
        )
        assert drafting["revision_round"] == expected_round

    # The fourth entry into review is still available after three completed loops.
    submit_cda_review(draft["id"], COUNSEL_ONE)
    reentered = read_cda_draft(program_id, draft["id"])
    assert reentered["status"] == "IN_REVIEW"
    assert reentered["revision_round"] == 3


def test_filing_a_summary_comp_table_section_does_not_disclose_the_program():
    """Only the CD&A narrative's filing advances the program's design status.

    "Filing any other section code advances nothing on the program."

    Design: Difficulty/non_linear_state_machine/cda_draft_revision_cycle_reenters_review_with_incremented_round
    """
    env = _committee_approved_program_with_current_iss_screen()
    program_id = env["program"]["id"]

    draft = create_cda_draft(program_id, "SUMMARY_COMP_TABLE", 900, True, COUNSEL_ONE)
    submit_cda_review(draft["id"], COUNSEL_ONE)
    legal_clear_cda_draft(draft["id"], COUNSEL_TWO)
    filed = file_cda_draft(draft["id"], COUNSEL_TWO)

    assert filed["status"] == "FILED"
    assert filed["filed_at"] is not None

    assert read_pay_program(program_id)["design_status"] == "COMMITTEE_APPROVED"
