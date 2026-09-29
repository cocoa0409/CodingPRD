"""Thresholds tested from below, exactly on and just past the boundary."""

from test_helpers import (
    ERR_DISCIPLINE_MINIMUM_UNFILLABLE,
    SPONSORED_SESSION_START,
    assert_money_equals,
    assert_score_equals,
    assign_and_score,
    assign_panelist,
    create_chair,
    create_panelist,
    lock_slate,
    pay_disbursement,
    payment_dates,
    read_application,
    read_cycle,
    refresh_application,
    refresh_residency,
    score_assignment,
    setup_panel_review_cycle,
    setup_residency_ready_for_payment,
    tax_report,
    validate_error,
    validate_paginated,
    ADMIN_HEADERS,
)

# Four periods of 30,000 cents, so the cumulative exemption of 60,000 is met
# exactly on the second payment and passed for the first time on the third.
THRESHOLD_RATE_CENTS = 15000


def _non_treaty_schedule(api):
    """A non-treaty international artist whose periods step onto the threshold."""
    _cycle, _applicant, residency, rows = setup_residency_ready_for_payment(
        api,
        session_length_weeks=8,
        international=True,
        treaty_country=False,
        weekly_rate_override_cents=THRESHOLD_RATE_CENTS,
        applicant_overrides={"citizenship_country": "MX"},
    )
    assert len(rows) == 4
    assert all(row["gross_cents"] == 30000 for row in rows)
    assert refresh_residency(api, residency)["tax_form_type"] == "1042S"
    assert_money_equals(
        residency.residency["stipend_total_cents"], 120000, "residency award"
    )
    return residency, rows, payment_dates(SPONSORED_SESSION_START, 4)


def test_nothing_is_withheld_below_or_exactly_on_the_exemption(api):
    """The second payment lands on the threshold and is still wholly exempt.

    PRD: "The consequence worth stating twice is that a single payment can be
    partly exempt and partly taxable, and that at a cumulative total of exactly
    60,000 cents nothing is withheld — only the first cent above the threshold
    is taxable."

    Design: Difficulty/boundary_precision_check/cumulative_withholding_zero_exactly_at_threshold
    """
    _residency, rows, dates = _non_treaty_schedule(api)

    below = pay_disbursement(api, rows[0]["id"], dates[0])
    assert below["withholding_rate"] == 0.30
    assert_money_equals(below["cumulative_taxable_cents"], 0, "period 1 taxable")
    assert_money_equals(below["withholding_cents"], 0, "period 1 withholding")
    assert_money_equals(below["net_cents"], 30000, "period 1 net")

    exactly_on = pay_disbursement(api, rows[1]["id"], dates[1])
    assert_money_equals(exactly_on["cumulative_taxable_cents"], 0, "period 2 taxable")
    assert_money_equals(exactly_on["withholding_cents"], 0, "period 2 withholding")
    assert_money_equals(exactly_on["net_cents"], 30000, "period 2 net")


def test_the_first_payment_past_the_threshold_is_taxed_in_full(api):
    """One cent over the line taxes the whole third period, not the whole total.

    PRD: "For a non-treaty international resident receiving four payments of
    30,000 cents, the first two are wholly exempt, the second bringing the
    cumulative total to exactly the threshold, and the third and fourth are each
    fully taxable at 30,000 cents, withholding 9,000 cents apiece."

    Design: Difficulty/boundary_precision_check/cumulative_withholding_zero_exactly_at_threshold
    """
    residency, rows, dates = _non_treaty_schedule(api)
    for index in range(3):
        paid = pay_disbursement(api, rows[index]["id"], dates[index])

    assert_money_equals(paid["cumulative_taxable_cents"], 30000, "period 3 taxable")
    assert_money_equals(paid["withholding_cents"], 9000, "period 3 withholding")
    assert_money_equals(paid["net_cents"], 21000, "period 3 net")

    ledger = refresh_residency(api, residency)
    assert_money_equals(ledger["stipend_paid_gross_cents"], 90000, "paid gross")
    assert_money_equals(ledger["withholding_to_date_cents"], 9000, "withholding to date")


def test_landing_on_the_threshold_produces_no_reconciliation_drift(api):
    """Both withholding variants agree exactly when the boundary is met head-on.

    PRD: "`statutory_liability_cents` is a genuinely different calculation of
    the same liability: the rate is applied **once** to `annual_taxable_cents`
    and the result is rounded half up to whole cents **once**."

    Design: Difficulty/boundary_precision_check/cumulative_withholding_zero_exactly_at_threshold
    """
    residency, rows, dates = _non_treaty_schedule(api)
    for index in range(3):
        pay_disbursement(api, rows[index]["id"], dates[index])

    report = tax_report(api, residency.residency_id)

    assert report["paid_period_count"] == 3
    assert report["withholding_rate"] == 0.30
    assert_money_equals(report["annual_gross_cents"], 90000, "annual gross")
    assert_money_equals(report["annual_taxable_cents"], 30000, "annual taxable")
    assert_money_equals(report["withheld_actual_cents"], 9000, "withheld actual")
    assert_money_equals(report["statutory_liability_cents"], 9000, "statutory")
    assert report["reconciliation_delta_cents"] == 0


# One discipline that never receives an application, alongside the one that
# does, so the alphabetically first minimum is owed against an empty pool.
SCULPT_THEN_PRINT = [
    {},
    {
        "code": "PRINT",
        "name": "Printmaking",
        "required_capability_tags": ["PRINT_PRESS"],
        "required_ventilation_class": "NONE",
        "cohort_max_slots": 4,
        "cohort_min_slots": 1,
    },
]


def _one_scored_discipline(api, print_overrides=None, extra_applicants=0):
    """A cycle whose PRINT minimum is owed but whose PRINT pool is empty."""
    specs = [SCULPT_THEN_PRINT[0], dict(SCULPT_THEN_PRINT[1])]
    if print_overrides:
        specs[1].update(print_overrides)
    cycle, apps = setup_panel_review_cycle(
        api,
        applicant_count=1 + extra_applicants,
        discipline_specs=specs,
        cohort_target_size=10,
        alumni_reserve_pct=0.25,
        slate_min_score=60.0,
    )
    reviewers = [create_panelist(api) for _ in range(2)]
    for reviewer in reviewers:
        assign_and_score(api, apps[0], reviewer, 8, 8, 8, 8)
    return cycle, apps


def test_a_discipline_minimum_owed_against_an_empty_pool_refuses_the_lock(api):
    """The degenerate empty candidate set cannot satisfy a minimum of one slot.

    PRD: "If, after that, the discipline has fewer selections than its
    `cohort_min_slots` — including the degenerate case where it had no
    candidates at all — the entire lock is refused with
    `ERR_DISCIPLINE_MINIMUM_UNFILLABLE` (HTTP 422)."

    Design: Difficulty/boundary_precision_check/discipline_minimum_unfillable_on_empty_eligible_set
    """
    cycle, apps = _one_scored_discipline(api)
    ready = read_cycle(api, cycle.cycle_id)
    assert ready["status"] == "PANEL_REVIEW"
    assert ready["panel_review_complete"] is True
    assert ready["slate_ready_count"] == 1
    assert_score_equals(
        read_application(api, apps[0].application_id)["final_panel_score"],
        80.00,
        "final score",
    )

    validate_error(
        api.lock_slate(cycle.cycle_id, create_chair(api).chair_headers),
        ERR_DISCIPLINE_MINIMUM_UNFILLABLE,
    )

    assert read_cycle(api, cycle.cycle_id)["status"] == "PANEL_REVIEW"


def test_the_refused_lock_writes_no_partial_allocation(api):
    """The alphabetically first discipline fails before any slot is handed out.

    PRD: "Walk the cycle's disciplines in ascending `code` order — an
    alphabetical walk over the operator-assigned codes, not over identifiers."

    Design: Difficulty/boundary_precision_check/discipline_minimum_unfillable_on_empty_eligible_set
    """
    cycle, apps = _one_scored_discipline(api)

    validate_error(
        api.lock_slate(cycle.cycle_id, create_chair(api).chair_headers),
        ERR_DISCIPLINE_MINIMUM_UNFILLABLE,
    )

    survivor = read_application(api, apps[0].application_id)
    assert survivor["status"] == "SCORED"
    assert survivor["waitlist_rank"] is None
    unchanged = read_cycle(api, cycle.cycle_id)
    assert unchanged["slots_filled_count"] == 0
    assert unchanged["alumni_reserved_slots"] == 0
    rows, _meta = validate_paginated(
        api.list_residencies(ADMIN_HEADERS, {"cycle_id": cycle.cycle_id})
    )
    assert rows == []


def test_a_pool_thinned_by_the_minimum_score_is_as_empty_as_no_pool_at_all(api):
    """One candidate scoring below the slate floor leaves the pool empty anyway.

    PRD: "Every application in `SCORED` that never entered the pool — that is,
    whose `final_panel_score` falls below `slate_min_score` — moves `SCORED →
    REJECTED`."

    Design: Difficulty/boundary_precision_check/discipline_minimum_unfillable_on_empty_eligible_set
    """
    cycle, apps = _one_scored_discipline(api, extra_applicants=1)
    thin = apps[1]
    for reviewer in (create_panelist(api), create_panelist(api)):
        assign_and_score(api, thin, reviewer, 5, 5, 5, 5)
    assert_score_equals(
        read_application(api, thin.application_id)["final_panel_score"],
        50.00,
        "thin final score",
    )

    validate_error(
        api.lock_slate(cycle.cycle_id, create_chair(api).chair_headers),
        ERR_DISCIPLINE_MINIMUM_UNFILLABLE,
    )

    assert read_application(api, thin.application_id)["status"] == "SCORED"
    assert read_application(api, apps[0].application_id)["status"] == "SCORED"


def test_dropping_the_minimum_to_zero_lets_the_same_lock_through(api):
    """The refusal was the minimum alone; nothing else about the cycle was wrong.

    PRD: "The outcomes follow mechanically, and each one advances the affected
    application's `version` by 1. Every selected application moves `SCORED →
    OFFERED`."

    Design: Difficulty/boundary_precision_check/discipline_minimum_unfillable_on_empty_eligible_set
    """
    cycle, apps = _one_scored_discipline(api, print_overrides={"cohort_min_slots": 0})

    lock_slate(api, cycle, create_chair(api))

    locked = read_cycle(api, cycle.cycle_id)
    assert locked["status"] == "SLATE_LOCKED"
    assert locked["alumni_reserved_slots"] == 3
    assert refresh_application(api, apps[0])["status"] == "OFFERED"


# Reviewer legs chosen so that the fourth one drives the untrimmed mean onto an
# exact half-cent: 82.00, 80.00, 77.58 and 70.00 sum to 309.58.
HALF_CENT_LEGS = [(9, 8, 8, 7), (8, 8, 8, 8), (9, 9, 8, 8), (7, 7, 7, 7)]
OUTSIDE_EXPERTISE = {"discipline_expertise": ["PRINT"]}


def _four_reviewer_panel(api):
    """Four seated reviewers, the third credentialed in another discipline."""
    _cycle, apps = setup_panel_review_cycle(api, applicant_count=1)
    app = apps[0]
    reviewers = [
        create_panelist(api),
        create_panelist(api),
        create_panelist(api, **OUTSIDE_EXPERTISE),
        create_panelist(api),
    ]
    seats = [assign_panelist(api, app, reviewer) for reviewer in reviewers]
    assert [seat["expertise_matched"] for seat in seats] == [True, True, False, True]
    return app, reviewers, seats


def _record(api, reviewers, seats, index):
    return score_assignment(api, seats[index]["id"], reviewers[index], *HALF_CENT_LEGS[index])


def test_each_reviewer_leg_is_rounded_before_it_joins_the_mean(api):
    """The mismatch multiplier is applied and rounded inside the reviewer's leg.

    PRD: "Multiply it by the expertise multiplier — exactly 1.00 when
    `expertise_matched` is true, and 0.90 when it is false, so a reviewer
    working outside their credentialed disciplines carries ninety percent of the
    weight of one working inside them — and round the product half up to two
    decimal places."

    Design: Difficulty/boundary_precision_check/panel_provisional_mean_lands_exactly_on_a_half_cent
    """
    app, reviewers, seats = _four_reviewer_panel(api)

    totals = [_record(api, reviewers, seats, index)["panelist_total_100"] for index in range(4)]

    assert_score_equals(totals[0], 82.00, "leg 1")
    assert_score_equals(totals[1], 80.00, "leg 2")
    # 86.2 carried at ninety percent, rounded inside the reviewer's own leg.
    assert_score_equals(totals[2], 77.58, "leg 3")
    assert_score_equals(totals[3], 70.00, "leg 4")
    assert refresh_application(api, app)["scored_panelist_count"] == 4


def test_the_fourth_leg_puts_the_untrimmed_mean_on_an_exact_half_cent(api):
    """A mean of 77.395 must round up, and only half-up rounding gives 77.40.

    PRD: "`provisional_screening_score` is the **untrimmed** arithmetic mean:
    sum the contributing reviewer totals, divide by their count, round half up
    to two decimal places."

    Design: Difficulty/boundary_precision_check/panel_provisional_mean_lands_exactly_on_a_half_cent
    """
    app, reviewers, seats = _four_reviewer_panel(api)
    for index in range(3):
        _record(api, reviewers, seats, index)

    three_legs = refresh_application(api, app)
    assert three_legs["scored_panelist_count"] == 3
    assert_score_equals(
        three_legs["provisional_screening_score"], 79.86, "mean of three legs"
    )

    _record(api, reviewers, seats, 3)

    four_legs = refresh_application(api, app)
    assert_score_equals(
        four_legs["provisional_screening_score"], 77.40, "mean of four legs"
    )


def test_the_trim_switches_on_at_the_same_review_and_parts_the_two_scores(api):
    """The fourth review both creates the tie and activates the trim.

    PRD: "When the count reaches at least four reviewers, remove exactly one
    occurrence of the highest reviewer total and exactly one occurrence of the
    lowest reviewer total from the contributing set, then average what remains
    and round half up to two decimal places."

    Design: Difficulty/boundary_precision_check/panel_provisional_mean_lands_exactly_on_a_half_cent
    """
    app, reviewers, seats = _four_reviewer_panel(api)
    for index in range(3):
        _record(api, reviewers, seats, index)

    untrimmed = refresh_application(api, app)
    assert_score_equals(untrimmed["final_panel_score"], 79.86, "final on three legs")

    _record(api, reviewers, seats, 3)

    trimmed = refresh_application(api, app)
    assert trimmed["status"] == "SCORED"
    assert_score_equals(trimmed["final_panel_score"], 78.79, "final on four legs")
    assert_score_equals(
        trimmed["provisional_screening_score"], 77.40, "provisional on four legs"
    )
    assert round(
        trimmed["final_panel_score"] - trimmed["provisional_screening_score"], 2
    ) == 1.39
