"""Two figures derived from one dataset: untrimmed versus trimmed panel means,
and provisional versus final-settled stipend awards."""

from test_helpers import (
    ADMIN_HEADERS,
    assign_and_score,
    assign_panelist,
    complete_all_trainings,
    create_applicant,
    create_panelist,
    create_residency,
    read_cycle,
    refresh_application,
    refresh_residency,
    schedule_residency,
    score_assignment,
    set_clock,
    setup_open_cycle,
    setup_panel_review_cycle,
    assert_cycle_stipend_ledger,
    assert_money_equals,
    assert_score_equals,
    check_in,
    terminate_residency,
    validate_success,
)

SCULPT_DISCIPLINE = {
    "portfolio_min_items": 2,
    "requires_hazmat_review": True,
}

# Four rubric legs whose reviewer totals are 82.00, 80.00, 77.58 and 70.00.
LEG_HIGH = (9, 8, 8, 7)
LEG_MIDDLE = (8, 8, 8, 8)
LEG_OUTSIDE_EXPERTISE = (9, 9, 8, 8)
LEG_LOW = (7, 7, 7, 7)


def _panel_of_four(api):
    """Seat four reviewers on one application and score the first three."""
    cycle, apps = setup_panel_review_cycle(
        api,
        applicant_count=1,
        panel_quorum=2,
        discipline_overrides=SCULPT_DISCIPLINE,
        application_overrides={
            "media_types": ["IMAGE", "IMAGE"],
        },
    )
    app = apps[0]
    matched_one = create_panelist(api, discipline_expertise=["SCULPT"])
    matched_two = create_panelist(api, discipline_expertise=["SCULPT"])
    outside = create_panelist(api, discipline_expertise=["PRINT"])
    matched_four = create_panelist(api, discipline_expertise=["SCULPT"])

    assign_and_score(api, app, matched_one, *LEG_HIGH)
    assign_and_score(api, app, matched_two, *LEG_MIDDLE)
    assign_and_score(api, app, outside, *LEG_OUTSIDE_EXPERTISE)
    fourth_assignment = assign_panelist(api, app, matched_four)
    return cycle, app, matched_four, fourth_assignment


def test_three_reviewers_leave_both_panel_means_identical(api):
    """Below the trim threshold the untrimmed and trimmed variants agree.

    PRD: "When the count meets quorum but is fewer than four, no trim is
    applied and the mean is taken over all contributors, rounded the same way."

    Design: Difficulty/dual_variant_calc/application_provisional_untrimmed_vs_final_trimmed_panel_score
    """
    _cycle, app, _fourth, _assignment = _panel_of_four(api)

    record = refresh_application(api, app)
    assert record["scored_panelist_count"] == 3
    # (82.00 + 80.00 + 77.58) / 3 = 79.86 on both variants.
    assert_score_equals(record["provisional_screening_score"], 79.86, "provisional")
    assert_score_equals(record["final_panel_score"], 79.86, "final")


def test_expertise_mismatch_multiplier_discounts_the_reviewer_total(api):
    """A reviewer working outside their disciplines carries ninety percent.

    PRD: "Multiply it by the expertise multiplier — exactly 1.00 when
    `expertise_matched` is true, and 0.90 when it is false".

    Design: Difficulty/dual_variant_calc/application_provisional_untrimmed_vs_final_trimmed_panel_score
    """
    cycle, apps = setup_panel_review_cycle(
        api,
        applicant_count=1,
        panel_quorum=2,
        discipline_overrides=SCULPT_DISCIPLINE,
        application_overrides={"media_types": ["IMAGE", "IMAGE"]},
    )
    app = apps[0]
    inside = create_panelist(api, discipline_expertise=["SCULPT"])
    outside = create_panelist(api, discipline_expertise=["PRINT"])

    inside_leg = assign_and_score(api, app, inside, *LEG_OUTSIDE_EXPERTISE)
    outside_leg = assign_and_score(api, app, outside, *LEG_OUTSIDE_EXPERTISE)

    assert inside_leg["expertise_matched"] is True
    assert outside_leg["expertise_matched"] is False
    # Identical raw scores: 86.20 at full weight, 77.58 at ninety percent.
    assert_score_equals(inside_leg["panelist_total_100"], 86.20, "matched total")
    assert_score_equals(outside_leg["panelist_total_100"], 77.58, "mismatched total")


def test_fourth_reviewer_makes_the_trimmed_mean_diverge_from_the_untrimmed_one(api):
    """Crossing four contributors drops one high and one low reviewer total.

    PRD: "When the count reaches at least four reviewers, remove exactly one
    occurrence of the highest reviewer total and exactly one occurrence of the
    lowest reviewer total from the contributing set, then average what remains
    and round half up to two decimal places."

    Design: Difficulty/dual_variant_calc/application_provisional_untrimmed_vs_final_trimmed_panel_score
    """
    _cycle, app, fourth, assignment = _panel_of_four(api)

    leg = score_assignment(api, assignment["id"], fourth, *LEG_LOW)
    assert leg["expertise_matched"] is True
    assert_score_equals(leg["panelist_total_100"], 70.00, "fourth reviewer total")

    record = refresh_application(api, app)
    assert record["scored_panelist_count"] == 4
    # Untrimmed: (82.00 + 80.00 + 77.58 + 70.00) / 4 = 77.395 -> 77.40.
    assert_score_equals(record["provisional_screening_score"], 77.40, "provisional")
    # Trimmed: 82.00 and 70.00 removed, (80.00 + 77.58) / 2 = 78.79.
    assert_score_equals(record["final_panel_score"], 78.79, "final")
    assert record["final_panel_score"] != record["provisional_screening_score"]


def test_the_variant_divergence_does_not_move_the_application_state(api):
    """Recomputation past quorum changes numbers, not the application status.

    PRD: "`rank_in_discipline` is the 1-based position of the application
    inside its own discipline".

    Design: Difficulty/dual_variant_calc/application_provisional_untrimmed_vs_final_trimmed_panel_score
    """
    _cycle, app, fourth, assignment = _panel_of_four(api)

    before = refresh_application(api, app)
    assert before["status"] == "SCORED"

    score_assignment(api, assignment["id"], fourth, *LEG_LOW)

    after = refresh_application(api, app)
    assert after["status"] == "SCORED"
    assert after["rank_in_discipline"] == 1


def test_scheduling_prices_the_award_on_the_provisional_basis(api):
    """A confirmed eight-week calendar commits the whole planned award.

    PRD: "It is the residency's `stipend_weekly_rate_cents` multiplied by the
    planned week count, so the cycle commits the whole award up front."

    Design: Difficulty/dual_variant_calc/residency_provisional_award_vs_final_settled_stipend
    """
    cycle = setup_open_cycle(api, discipline_overrides=SCULPT_DISCIPLINE)
    applicant = create_applicant(api)
    residency = create_residency(api, cycle, applicant)

    schedule_residency(api, residency, "2026-11-02", 8)

    assert residency.residency["stipend_basis"] == "PROVISIONAL"
    assert_money_equals(residency.residency["stipend_total_cents"], 560000, "award")
    assert residency.residency["actual_weeks_in_residence"] is None
    assert_cycle_stipend_ledger(read_cycle(api, cycle.cycle_id), 560000, 19440000)


def test_termination_reprices_the_award_on_the_final_settled_basis(api):
    """Nineteen days served re-prices three whole weeks and releases the rest.

    PRD: "At a weekly rate of 70,000 cents an eight-week session prices
    provisionally at 560,000 cents; terminated after nineteen days served,
    three whole weeks, it re-prices at 210,000 cents and releases the
    350,000-cent difference back to the cycle's uncommitted pool."

    Design: Difficulty/dual_variant_calc/residency_provisional_award_vs_final_settled_stipend
    """
    cycle = setup_open_cycle(api, discipline_overrides=SCULPT_DISCIPLINE)
    applicant = create_applicant(api)
    residency = create_residency(api, cycle, applicant)
    schedule_residency(api, residency, "2026-11-02", 8)
    complete_all_trainings(api, residency)
    set_clock(api, "2026-11-02T09:00:00Z")
    check_in(api, residency)
    set_clock(api, "2026-11-20T15:00:00Z")

    settled = terminate_residency(api, residency, "resident left the programme early")

    assert settled["status"] == "TERMINATED"
    assert settled["stipend_basis"] == "FINAL_SETTLED"
    assert settled["actual_weeks_in_residence"] == 3
    assert_money_equals(settled["stipend_total_cents"], 210000, "settled award")
    assert_cycle_stipend_ledger(read_cycle(api, cycle.cycle_id), 210000, 19790000)


def test_the_money_released_by_settlement_never_leaves_the_cycle_pool(api):
    """Committed plus uncommitted equals the pool before and after settlement.

    PRD: "The **final settled award** is in force while `stipend_basis` is
    `FINAL_SETTLED`, which the termination cascade of §3.6 sets."

    Design: Difficulty/dual_variant_calc/residency_provisional_award_vs_final_settled_stipend
    """
    cycle = setup_open_cycle(api, discipline_overrides=SCULPT_DISCIPLINE)
    applicant = create_applicant(api)
    residency = create_residency(api, cycle, applicant)
    schedule_residency(api, residency, "2026-11-02", 8)
    complete_all_trainings(api, residency)
    set_clock(api, "2026-11-02T09:00:00Z")
    check_in(api, residency)

    before = read_cycle(api, cycle.cycle_id)
    assert (
        before["stipend_committed_cents"] + before["stipend_uncommitted_cents"]
        == before["stipend_pool_cents"]
    )

    set_clock(api, "2026-11-20T15:00:00Z")
    terminate_residency(api, residency)

    after = read_cycle(api, cycle.cycle_id)
    assert (
        after["stipend_committed_cents"] + after["stipend_uncommitted_cents"]
        == after["stipend_pool_cents"]
    )
    assert after["stipend_pool_cents"] == 20000000


def test_an_unfinished_residency_keeps_the_provisional_basis(api):
    """The basis, not the calendar, selects which award variant is in force.

    PRD: "The **provisional award** is in force while `stipend_basis` is
    `PROVISIONAL` — from offer acceptance until the residency completes or
    terminates."

    Design: Difficulty/dual_variant_calc/residency_provisional_award_vs_final_settled_stipend
    """
    cycle = setup_open_cycle(api, discipline_overrides=SCULPT_DISCIPLINE)
    applicant = create_applicant(api)
    residency = create_residency(api, cycle, applicant)
    schedule_residency(api, residency, "2026-11-02", 8)
    complete_all_trainings(api, residency)
    set_clock(api, "2026-11-02T09:00:00Z")
    check_in(api, residency)

    # Walk the clock past the planned end without settling the residency.
    set_clock(api, "2027-01-15T00:00:00Z")
    still_open = refresh_residency(api, residency)

    assert still_open["status"] == "IN_RESIDENCE"
    assert still_open["stipend_basis"] == "PROVISIONAL"
    assert_money_equals(still_open["stipend_total_cents"], 560000, "award")
    assert still_open["actual_weeks_in_residence"] is None
    validate_success(api.get_residency(residency.residency_id, ADMIN_HEADERS))
