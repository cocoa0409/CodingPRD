"""Compliance enforcement: how a case is scored and the four-hop cascade an
upheld case sets off."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_compliance_case,
    create_campaign_expense_payload,
    make_candidate_headers,
    read_ballot,
    read_ballot_line,
    read_candidacy,
    read_case,
    read_election,
    setup_disqualified_candidacy_with_reported_spend,
    setup_repeat_offender_before_final_case,
    setup_repeat_offender_inside_open_window,
    setup_severe_case_inside_voting_window,
    setup_slate_pool_over_cap,
    validate_error,
    validate_paginated,
    validate_success,
)

COMMISSIONER = TEST_USERS["commissioner_headers"]
ADVISOR = TEST_USERS["advisor_headers"]


# ─── Scoring a case ───────────────────────────────────────────────────────────

def test_the_overspend_surcharge_is_clamped_at_twenty_five_points(api):
    """PRD §3.5: "Then the overspend surcharge is added: take the respondent's spend basis,
    subtract the election's `spending_cap_cents`, and treat any negative result as zero;
    divide the remaining overspend in cents by one thousand — that is, one penalty point
    for every ten dollars over the cap — and round *up* to a whole number; then take the
    smaller of that number and twenty-five, which is the surcharge ceiling."
    PRD §3.5: "The score begins from a severity base: five points for `MINOR`, fifteen for
    `MAJOR`, forty for `SEVERE`."
    PRD §3.5: "The raw score is the severity base multiplied by the repeat multiplier,
    multiplied by the timing factor, with the overspend surcharge added afterwards — the
    surcharge is never multiplied."

    Design: Corner/calculations/overspend_surcharge_is_capped_at_twenty_five_points
    """
    scenario = setup_slate_pool_over_cap(leader_cents=45_000, member_cents=40_000)
    respondent = scenario["joiner"]
    case = validate_success(
        api.create_compliance_case(
            {
                "election_id": scenario["election"]["id"],
                "candidacy_id": respondent["id"],
                "rule_code": "C-1.1",
                "severity": "MINOR",
                "description": "Chalking outside the approved zone",
            },
            COMMISSIONER,
        ),
        201,
    )

    assert read_candidacy(respondent["id"])["spending_committed_cents"] == 85_000
    assert read_candidacy(scenario["leader"]["id"])["spending_committed_cents"] == 85_000

    upheld = validate_success(api.uphold_case(case["id"], ADVISOR))

    assert_compliance_case(upheld)
    assert upheld["overspend_points_applied"] == 25, (
        "35 000 cents over the cap would score 35 raw points but the ceiling is 25, got "
        f"{upheld['overspend_points_applied']}"
    )
    assert upheld["timing_factor_applied"] == 1.0
    assert upheld["prior_upheld_count"] == 0
    assert upheld["penalty_points"] == 30, (
        f"5 base times 1.0 times 1.0 plus 25 surcharge, got {upheld['penalty_points']}"
    )

    after = read_candidacy(respondent["id"])
    assert after["penalty_points_total"] == 30
    assert after["status"] == "DRAFT", (
        "thirty points is short of the disqualification threshold"
    )


def test_repeat_timing_and_overspend_factors_compose_into_fifty_four_points(api):
    """PRD §3.5: "Repeat offending multiplies it: `prior_upheld_count` is the number of the
    respondent's other cases already in `UPHELD` whose upheld instant precedes this one's,
    ordered by `upheld_at` ascending with `created_at` ascending as the tie-break, and the
    repeat multiplier is one plus one half for each such prior case."
    PRD §3.5: "Timing multiplies it again: `timing_factor_applied` is 1.5 when the case's
    `upheld_at` falls at or after `voting_opens_at` and at or before `voting_closes_at` —
    both endpoints inclusive — and 1.0 otherwise, so an offence adjudicated while the polls
    are open costs half again as much."
    PRD §3.5: "That raw score is rounded half up to an integer exactly once, and the
    smaller of that integer and one hundred becomes the case's `penalty_points`."
    PRD §3.4: "Nothing is tested for the other slate members, and joining a slate
    afterwards can legitimately push a candidacy's committed total past the cap without any
    expense ever having been refused."

    Design: Difficulty/combinatorial_formula/penalty_points_three_factor_nonlinear_composition
    """
    scenario = setup_repeat_offender_inside_open_window()
    respondent = scenario["respondent"]

    assert read_candidacy(respondent["id"])["spending_committed_cents"] == 70_000, (
        "the joint-and-several pool carries the respondent 20 000 cents over the cap"
    )

    upheld = validate_success(
        api.uphold_case(scenario["pending_case"]["id"], ADVISOR)
    )

    assert_compliance_case(upheld)
    assert upheld["prior_upheld_count"] == 1, (
        f"one earlier upheld case, got {upheld['prior_upheld_count']}"
    )
    assert upheld["timing_factor_applied"] == 1.5, (
        "the case is upheld while the polls are open"
    )
    assert upheld["overspend_points_applied"] == 20, (
        f"20 000 cents over the cap is 20 points, got {upheld['overspend_points_applied']}"
    )
    assert upheld["penalty_points"] == 54, (
        "15 times 1.5 times 1.5 is 33.75, plus the 20-point surcharge, rounded half up "
        f"once, got {upheld['penalty_points']}"
    )


def test_fifty_nine_points_leaves_the_repeat_offender_on_the_ballot(api):
    """PRD §3.5: "The respondent's `penalty_points_total` is recomputed, and if it has
    reached sixty points — the disqualification threshold, compared as "at least" — the
    candidacy is disqualified."
    PRD §3.5: "A candidacy's `penalty_points_total` is the sum of `penalty_points` across
    all of its cases currently in `UPHELD`."

    Design: Difficulty/combinatorial_formula/penalty_points_three_factor_nonlinear_composition
    """
    scenario = setup_repeat_offender_inside_open_window()
    respondent = scenario["respondent"]

    validate_success(api.uphold_case(scenario["pending_case"]["id"], ADVISOR))

    earlier = read_case(scenario["minor_case"]["id"])
    assert earlier["penalty_points"] == 5, (
        f"the earlier MINOR case keeps its own score, got {earlier['penalty_points']}"
    )

    after = read_candidacy(respondent["id"])
    assert after["penalty_points_total"] == 59, (
        f"5 plus 54 is one point short of the threshold, got {after['penalty_points_total']}"
    )
    assert after["status"] == "ON_BALLOT", (
        f"fifty-nine points is not enough to disqualify, got {after['status']}"
    )
    assert read_election(scenario["election"]["id"])["ballot_integrity_status"] == "INTACT", (
        "no line was voided, so the count is still intact"
    )


def test_a_severe_case_upheld_inside_the_window_scores_exactly_sixty(api):
    """PRD §3.5: "The score begins from a severity base: five points for `MINOR`, fifteen
    for `MAJOR`, forty for `SEVERE`."
    PRD §3.5: "Timing multiplies it again: `timing_factor_applied` is 1.5 when the case's
    `upheld_at` falls at or after `voting_opens_at` and at or before `voting_closes_at` —
    both endpoints inclusive — and 1.0 otherwise, so an offence adjudicated while the polls
    are open costs half again as much."

    Design: Difficulty/boundary_precision_check/penalty_total_exactly_sixty_disqualifies
    """
    scenario = setup_severe_case_inside_voting_window()

    upheld = validate_success(
        api.uphold_case(scenario["pending_case"]["id"], ADVISOR)
    )

    assert_compliance_case(upheld)
    assert upheld["status"] == "UPHELD"
    assert upheld["prior_upheld_count"] == 0
    assert upheld["timing_factor_applied"] == 1.5
    assert upheld["overspend_points_applied"] == 0, (
        "the respondent reported no spending at all"
    )
    assert upheld["penalty_points"] == 60, (
        f"40 times 1.0 times 1.5 is exactly 60, got {upheld['penalty_points']}"
    )


def test_reaching_exactly_sixty_points_disqualifies_and_voids_the_line(api):
    """PRD §3.5: "The respondent's `penalty_points_total` is recomputed, and if it has
    reached sixty points — the disqualification threshold, compared as "at least" — the
    candidacy is disqualified."
    PRD §3.5: "**Hop three — void the ballot lines.** Every ballot line naming that
    candidacy and still in `ACTIVE` moves `ACTIVE → VOIDED`, and the parent ballot's
    `active_line_count` is decremented by one for each line voided."
    PRD §3.5: "**Hop four — flag the integrity of the count.** Because a line was voided on
    a ballot that had already reached `LOCKED`, `PUBLISHED` or `CLOSED`, the election's
    `ballot_integrity_status` is set to `RECOUNT_REQUIRED`."

    Design: Difficulty/boundary_precision_check/penalty_total_exactly_sixty_disqualifies
    """
    scenario = setup_severe_case_inside_voting_window()

    validate_success(api.uphold_case(scenario["pending_case"]["id"], ADVISOR))

    respondent = read_candidacy(scenario["respondent"]["id"])
    assert respondent["penalty_points_total"] == 60
    assert respondent["status"] == "DISQUALIFIED", (
        f"sixty points is 'at least' the threshold, got {respondent['status']}"
    )
    assert read_ballot_line(scenario["second_line"]["id"])["status"] == "VOIDED"

    ballot = read_ballot(scenario["ballot"]["id"])
    assert ballot["active_line_count"] == 1, (
        f"one of the two lines was voided, got {ballot['active_line_count']}"
    )
    assert read_election(scenario["election"]["id"])["ballot_integrity_status"] == (
        "RECOUNT_REQUIRED"
    )


# ─── The four-hop disqualification cascade ────────────────────────────────────

def test_upholding_the_second_case_scores_the_repeat_and_disqualifies(api):
    """PRD §3.5: "**Hop one — score the case.** The transition `FILED → UPHELD` computes
    the penalty and stamps `adjudicated_by_user_id` and `upheld_at` from the logical
    clock."
    PRD §3.5: "Repeat offending multiplies it: `prior_upheld_count` is the number of the
    respondent's other cases already in `UPHELD` whose upheld instant precedes this one's,
    ordered by `upheld_at` ascending with `created_at` ascending as the tie-break, and the
    repeat multiplier is one plus one half for each such prior case."
    PRD §3.5: "**Hop two — disqualify.** The respondent's `penalty_points_total` is
    recomputed, and if it has reached sixty points — the disqualification threshold,
    compared as "at least" — the candidacy is disqualified. A candidacy in `ELIGIBLE` moves
    `ELIGIBLE → DISQUALIFIED`, and one already on the ballot moves
    `ON_BALLOT → DISQUALIFIED`; either way `disqualified_reason` is stamped."

    Design: Difficulty/transitive_cascade/uphold_to_disqualify_to_line_void_to_recount_flag
    """
    scenario = setup_repeat_offender_before_final_case()

    upheld = validate_success(
        api.uphold_case(scenario["pending_case"]["id"], ADVISOR)
    )

    assert upheld["status"] == "UPHELD"
    assert upheld["prior_upheld_count"] == 1
    assert upheld["timing_factor_applied"] == 1.0, (
        "the polls were never opened, so no timing multiplier applies"
    )
    assert upheld["penalty_points"] == 60, (
        f"40 times 1.5 times 1.0, got {upheld['penalty_points']}"
    )
    assert upheld["adjudicated_by_user_id"] == "advisor-1"
    assert upheld["upheld_at"] is not None

    respondent = read_candidacy(scenario["respondent"]["id"])
    assert respondent["penalty_points_total"] == 75, (
        f"15 from the first case plus 60, got {respondent['penalty_points_total']}"
    )
    assert respondent["status"] == "DISQUALIFIED"


def test_the_voided_line_decrements_the_ballot_and_flags_the_count(api):
    """PRD §3.5: "**Hop three — void the ballot lines.** Every ballot line naming that
    candidacy and still in `ACTIVE` moves `ACTIVE → VOIDED`, and the parent ballot's
    `active_line_count` is decremented by one for each line voided."
    PRD §3.5: "**Hop four — flag the integrity of the count.** Because a line was voided on
    a ballot that had already reached `LOCKED`, `PUBLISHED` or `CLOSED`, the election's
    `ballot_integrity_status` is set to `RECOUNT_REQUIRED`."
    PRD §3.5: "Each of the four hops is mandatory and each bumps the `version` of every
    resource it touches."

    Design: Difficulty/transitive_cascade/uphold_to_disqualify_to_line_void_to_recount_flag
    """
    scenario = setup_repeat_offender_before_final_case()

    validate_success(api.uphold_case(scenario["pending_case"]["id"], ADVISOR))

    voided_line = read_ballot_line(scenario["second_line"]["id"])
    surviving_line = read_ballot_line(scenario["first_line"]["id"])
    assert voided_line["status"] == "VOIDED"
    assert surviving_line["status"] == "ACTIVE", (
        "only lines naming the disqualified candidacy are voided"
    )

    ballot = read_ballot(scenario["ballot"]["id"])
    assert ballot["active_line_count"] == 1, (
        f"the active count drops from two to one, got {ballot['active_line_count']}"
    )
    assert ballot["line_count"] == 2, "voiding never removes the row"

    election = read_election(scenario["election"]["id"])
    assert election["ballot_integrity_status"] == "RECOUNT_REQUIRED"
    assert election["status"] == "BALLOT_PUBLISHED", (
        "the election had not been certified, so nothing is pulled back"
    )
    assert read_candidacy(scenario["first_candidacy"]["id"])["status"] == "ON_BALLOT"


# ─── The rejection ladder ─────────────────────────────────────────────────────

def test_reporting_against_a_disqualified_candidacy_reports_the_state_error(api):
    """PRD §2.5: "Rules are evaluated in ascending priority and the **first** failing rule
    decides the response; later rules are never reached."
    PRD §2.5: "The target row — or, for a child create, the parent row the new child hangs
    from — is in a state from which the requested operation is declared —
    `ERR_INVALID_STATE` (409). This covers every state-transition endpoint plus
    campaign-expense reporting (the referenced candidacy's `status` must not be
    `WITHDRAWN`, `DISQUALIFIED` or `VACATED`)"
    PRD §2.5: "Spending cap — `ERR_SPENDING_CAP_EXCEEDED` (422), on campaign-expense
    reporting."

    Design: Difficulty/priority_pair_validation_conflict/disqualified_candidacy_overspend_expense_yields_state_error
    """
    scenario = setup_disqualified_candidacy_with_reported_spend()
    respondent = scenario["respondent"]
    assert read_candidacy(respondent["id"])["status"] == "DISQUALIFIED"

    response = api.create_campaign_expense(
        create_campaign_expense_payload(
            respondent["id"], category="DIGITAL", amount_cents=20_000,
            incurred_at="2026-08-20T00:00:00Z",
        ),
        make_candidate_headers(respondent["student_id"]),
    )

    validate_error(response, ApiErrorId.ERR_INVALID_STATE.value, 409)
    assert response.json()["data"]["error_id"] != ApiErrorId.ERR_SPENDING_CAP_EXCEEDED.value


def test_the_refused_expense_leaves_the_spend_ledger_untouched(api):
    """PRD §3.4: "Reporting is refused outright when the referenced candidacy is
    `WITHDRAWN`, `DISQUALIFIED` or `VACATED`."
    PRD §3.4: "Two more counters are maintained unconditionally on every candidacy:
    `spending_reported_cents`, the sum of `amount_cents` over that candidacy's own lines in
    any status at all, and `spending_reversed_cents`, the same sum restricted to lines that
    have been reversed."

    Design: Difficulty/priority_pair_validation_conflict/disqualified_candidacy_overspend_expense_yields_state_error
    """
    scenario = setup_disqualified_candidacy_with_reported_spend()
    respondent = scenario["respondent"]

    validate_error(
        api.create_campaign_expense(
            create_campaign_expense_payload(
                respondent["id"], category="DIGITAL", amount_cents=20_000,
                incurred_at="2026-08-20T00:00:00Z",
            ),
            make_candidate_headers(respondent["student_id"]),
        ),
        ApiErrorId.ERR_INVALID_STATE.value,
        409,
    )

    _, meta = validate_paginated(
        api.list_campaign_expenses(
            COMMISSIONER, params={"candidacy_id": respondent["id"]}
        )
    )
    assert meta["total_count"] == 1, (
        f"only the original 45 000-cent line exists, got {meta['total_count']}"
    )
    after = read_candidacy(respondent["id"])
    assert after["spending_committed_cents"] == 45_000
    assert after["spending_reported_cents"] == 45_000
