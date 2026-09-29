"""Computed-figure corners: the trimmed mean behind committee points, the
weighted composite peer score, the anchor-cycle rebase, additive matter
ledgers, the pool waterfall, the lockstep award branch and the pinned append
order of the year-end true-up."""

from test_helpers import (
    advance_cycle,
    advance_cycle_payload,
    approx2,
    approx4,
    approx6,
    assign_peer_review,
    cast_ballot,
    create_assessment,
    create_committee_member,
    create_cycle,
    create_cycle_payload,
    create_matter,
    create_partner,
    create_verified_billable_hours,
    cycle_version,
    draw_ledger,
    find_award,
    make_cycle_admin_headers,
    pay_draw,
    post_financials,
    read_assessment,
    read_cycle,
    read_matter,
    read_partner,
    score_peer_review,
    setup_deliberation_cycle,
    submit_assessment,
    true_up_award,
    validate_paginated,
    validate_success,
)

ADMIN = make_cycle_admin_headers()


def _lockstep_cycle_in_deliberation(api, cycle_overrides, lockstep_specs):
    """A cycle carried to DELIBERATION in which every named LOCKSTEP partner
    holds a SUBMITTED self-assessment with two SCORED peer reviews, and the two
    committee members are themselves outside the evaluation population."""
    cycle = create_cycle(api, **cycle_overrides)
    partners = [create_partner(api, **spec) for spec in lockstep_specs]
    committee = [
        create_committee_member(api, full_name=f"Cass Committee {n + 1}") for n in range(2)
    ]
    advance_cycle(api, cycle["id"], "SELF_ASSESSMENT")
    for partner in partners:
        assessment = create_assessment(
            api,
            cycle_id=cycle["id"],
            partner_id=partner["id"],
            claimed_origination_pct_total=0.00,
            claimed_non_billable_hours=0.00,
        )
        submit_assessment(api, assessment["id"], partner["id"])
        for member in committee:
            review = assign_peer_review(api, assessment["id"], member["id"])
            score_peer_review(api, review["id"], member["id"], 4, 4, 4)
    advance_cycle(api, cycle["id"], "PEER_REVIEW")
    cycle = advance_cycle(api, cycle["id"], "DELIBERATION")
    return cycle, partners, committee


def test_trimmed_mean_discards_exactly_one_high_and_one_low_ballot(api):
    """PRD 3.7: "With three or more cast ballots the single lowest and single
    highest proposals are discarded and the mean of the remainder is taken,
    rounded half up to 2 decimal places — so exactly three casts leave only the
    middle value standing, and no single outlier ballot can carry a partner."
    "With one or two cast ballots there is no trimming at all and the plain mean
    of them is taken, rounded the same way; the trimming threshold is three."

    Design: Corner/calculations/trimmed_mean_discards_exactly_one_high_and_one_low_ballot
    """
    bundle = setup_deliberation_cycle(api, committee_count=3)
    cycle_id = bundle["cycle"]["id"]
    subject_id = bundle["subject"]["id"]

    versions = []
    points = []
    for ballot, member, proposal in zip(
        bundle["ballots"], bundle["committee"], (900.00, 500.00, 700.00)
    ):
        versions.append(cycle_version(api, cycle_id))
        cast = cast_ballot(
            api,
            ballot_id=ballot["id"],
            committee_member_id=member["id"],
            points_proposed=proposal,
            cycle_id=cycle_id,
        )
        assert cast["state"] == "CAST"
        points.append(read_partner(api, subject_id)["committee_points"])

    # One cast: below the trim threshold, so the plain mean of a single figure.
    assert points[0] == approx2(900.00)
    # Two casts: still no trimming, the plain mean of 900.00 and 500.00.
    assert points[1] == approx2(700.00)
    # Three casts: 500.00 and 900.00 are discarded and only 700.00 stands.
    assert points[2] == approx2(700.00)

    assert versions[0] < versions[1] < versions[2]
    assert read_cycle(api, cycle_id)["total_committee_points"] == approx2(700.00)


def test_composite_score_weighting_and_four_decimal_precision(api):
    """PRD 3.6: "It requires all three of `technical_score`, `collaboration_score`
    and `client_service_score` to be present integers between 1 and 5 inclusive
    — any missing or out-of-range and the request is malformed — accepts an
    optional confidential `comment`, and computes `composite_score` as the
    technical score weighted 0.50 plus the collaboration score weighted 0.25 plus
    the client-service score weighted 0.25, rounded half up to 4 decimal places."

    Design: Corner/calculations/composite_score_weighting_and_four_decimal_precision
    """
    cycle = create_cycle(api)
    subject = create_partner(api, full_name="Prec Ision", compensation_model="FORMULA")
    first = create_committee_member(api, full_name="Ess One", practice_group="TAX")
    second = create_committee_member(api, full_name="Ess Two", practice_group="IP")
    advance_cycle(api, cycle["id"], "SELF_ASSESSMENT")
    assessment = create_assessment(
        api,
        cycle_id=cycle["id"],
        partner_id=subject["id"],
        claimed_origination_pct_total=0.00,
        claimed_non_billable_hours=0.00,
    )
    submit_assessment(api, assessment["id"], subject["id"])
    review_one = assign_peer_review(api, assessment["id"], first["id"])
    review_two = assign_peer_review(api, assessment["id"], second["id"])

    scored_one = score_peer_review(api, review_one["id"], first["id"], 5, 4, 3)
    after_one = read_assessment(api, assessment["id"])
    scored_two = score_peer_review(api, review_two["id"], second["id"], 3, 4, 3)
    after_two = read_assessment(api, assessment["id"])

    # 5 * 0.50 + 4 * 0.25 + 3 * 0.25 = 4.2500, not the unweighted 4.0000.
    assert scored_one["composite_score"] == approx4(4.2500)
    assert scored_one["state"] == "SCORED"
    # 3 * 0.50 + 4 * 0.25 + 3 * 0.25 = 3.2500.
    assert scored_two["composite_score"] == approx4(3.2500)
    assert scored_two["state"] == "SCORED"

    assert after_one["scored_review_count"] == 1
    assert after_one["mean_peer_score"] == approx4(4.2500)
    assert after_two["scored_review_count"] == 2
    assert after_two["mean_peer_score"] == approx4(3.7500)


def test_anchor_cycle_rebases_partner_computed_fields_when_a_later_year_opens(api):
    """PRD 2.6: "Creating a cycle for a later fiscal year immediately makes it the
    anchor and re-bases every one of those fields."

    Design: Corner/calculations/anchor_cycle_rebases_partner_computed_fields_when_a_later_year_opens
    """
    cycle_2026 = create_cycle(api, fiscal_year=2026)
    partner = create_partner(api, full_name="Anna Anchor", compensation_model="FORMULA")
    matter = create_matter(
        api,
        billing_attorney_id=partner["id"],
        responsible_attorney_id=partner["id"],
        client_key="CLI-AN",
        client_display_name="Anchor Analytics",
        matter_type="EXISTING",
        opened_on="2026-01-05",
    )
    record = create_verified_billable_hours(
        api,
        partner_id=partner["id"],
        cycle_id=cycle_2026["id"],
        matter_id=matter["id"],
        hours=100.00,
        service_period_start="2026-02-01",
        service_period_end="2026-02-28",
    )

    assert read_partner(api, partner["id"])["verified_billable_hours"] == approx2(100.00)

    cycle_2027 = validate_success(
        api.create_cycle(
            create_cycle_payload(
                fiscal_year=2027,
                claim_deadline_on="2027-09-30",
                assessment_deadline_on="2027-10-31",
            ),
            ADMIN,
        ),
        201,
    )

    rebased = read_partner(api, partner["id"])
    assert rebased["verified_billable_hours"] == approx2(0.00)
    assert rebased["normalized_credit_index_provisional"] == approx6(0.000000)
    assert rebased["formula_score_provisional"] == approx4(0.0000)

    # Matter.verified_billable_hours is not cycle-scoped and is unaffected.
    assert read_matter(api, matter["id"])["verified_billable_hours"] == approx2(100.00)

    stored = validate_success(api.get_contribution_record(record["id"], ADMIN), 200)
    assert stored["cycle_id"] == cycle_2026["id"]
    assert stored["verified"] is True

    assert read_cycle(api, cycle_2027["id"])["total_formula_score"] == approx4(0.0000)


def test_matter_ledger_running_totals_survive_a_negative_delta(api):
    """PRD 3.2: "A posting supplies `billed_delta_cents`, `collected_delta_cents`
    and `direct_cost_delta_cents` together with the `expected_matter_version`
    required by section 2.8, and each delta is added to the running `billed_cents`,
    `collected_cents` and `direct_cost_cents` respectively."

    Design: Corner/calculations/matter_ledger_running_totals_survive_a_negative_delta
    """
    partner = create_partner(api, full_name="Agg Regate", compensation_model="FORMULA")
    matter = create_matter(
        api,
        billing_attorney_id=partner["id"],
        responsible_attorney_id=partner["id"],
        client_key="CLI-AG",
        client_display_name="Aggregate Advisors",
        matter_type="EXISTING",
        opened_on="2026-01-15",
    )
    version_one = matter["version"]

    first = post_financials(
        api,
        matter["id"],
        billed_delta_cents=5_000_000,
        collected_delta_cents=4_000_000,
        direct_cost_delta_cents=1_000_000,
        expected_matter_version=version_one,
    )
    assert first["realization_pct"] == approx4(0.8000)
    assert first["profitability_index_contribution"] == approx4(0.7500)
    # No verified billable hours, so the two profitability variants coincide.
    assert first["profitability_index_fully_loaded"] == approx4(0.7500)
    version_two = first["version"]

    second = post_financials(
        api,
        matter["id"],
        billed_delta_cents=0,
        collected_delta_cents=-1_000_000,
        direct_cost_delta_cents=0,
        expected_matter_version=version_two,
    )
    # The second posting added a signed delta rather than replacing the totals.
    assert second["billed_cents"] == 5_000_000
    assert second["collected_cents"] == 3_000_000
    assert second["direct_cost_cents"] == 1_000_000
    assert second["realization_pct"] == approx4(0.6000)
    # 2,000,000 / 3,000,000 rounded half up at the fourth decimal place.
    assert second["profitability_index_contribution"] == approx4(0.6667)
    version_three = second["version"]

    assert version_one < version_two < version_three


def test_pool_waterfall_cuts_lockstep_to_its_floor_then_trims_discretionary(api):
    """PRD 3.8: "The lockstep bucket is cut first: its cutting ceiling is the
    lockstep gross multiplied by 0.30 and rounded half up to whole cents, the
    actual cut is the lesser of the shortfall and that ceiling,
    `haircut_applied_pct` records the cut divided by the lockstep gross rounded
    half up to 4 decimal places (and stays 0.0000 when the lockstep gross is 0),
    `lockstep_reserved_cents` becomes the gross less the cut, and the shortfall is
    reduced by the cut."

    Design: Corner/calculations/pool_waterfall_cuts_lockstep_to_its_floor_then_trims_discretionary
    """
    cycle, partners, _committee = _lockstep_cycle_in_deliberation(
        api,
        {
            "distributable_pool_cents": 100_000_000,
            "lockstep_unit_cents": 10_000_000,
            "discretionary_pool_pct": 0.5000,
            "draw_pct": 0.8000,
        },
        [
            {
                "full_name": "Lock Step",
                "compensation_model": "LOCKSTEP",
                "lockstep_step": 8,
                "admission_year": 2000,
            }
        ],
    )
    lockstep_partner = partners[0]

    published = validate_success(
        api.advance_cycle(cycle["id"], advance_cycle_payload("AWARDS_PUBLISHED"), ADMIN), 200
    )

    # Gross demand 80,000,000 lockstep plus 50,000,000 discretionary against a
    # 100,000,000 pool leaves a 30,000,000 shortfall; lockstep absorbs its whole
    # 24,000,000 ceiling and the residual 6,000,000 falls on discretionary.
    assert published["haircut_applied_pct"] == approx4(0.3000)
    assert published["lockstep_reserved_cents"] == 56_000_000
    assert published["discretionary_pool_cents"] == 44_000_000
    assert published["formula_pool_cents"] == 0

    award = find_award(api, cycle["id"], lockstep_partner["id"])
    assert award["award_state"] == "PUBLISHED"
    assert award["basis_model"] == "LOCKSTEP"
    # 8 * 10,000,000 * (1 - 0.3000).
    assert award["target_award_cents"] == 56_000_000
    # round half up of 56,000,000 * 0.8000 / 12, rounded independently.
    assert award["draw_schedule_monthly_cents"] == 3_733_333

    ballots, _meta = validate_paginated(api.list_ballots(ADMIN, {"cycle_id": cycle["id"]}))
    assert ballots == []


def test_lockstep_awards_scale_with_step_and_ignore_the_pool_share(api):
    """PRD 3.8: "A lockstep award is the partner's `lockstep_step` multiplied by
    the cycle's `lockstep_unit_cents` multiplied by one minus
    `haircut_applied_pct`, rounded half up to whole cents — so a full 0.3000
    haircut pays exactly 70 percent of the contractual figure." "A formula award
    is `formula_pool_cents` multiplied by the partner's score and divided by the
    cycle's `total_formula_score`, rounded half up to whole cents, and is 0 when
    that total is 0 (in which case the formula pool stays entirely
    undistributed)."

    Design: Corner/calculations/lockstep_awards_scale_with_step_and_ignore_the_pool_share
    """
    cycle, partners, _committee = _lockstep_cycle_in_deliberation(
        api,
        {
            "distributable_pool_cents": 100_000_000,
            "lockstep_unit_cents": 10_000_000,
            "discretionary_pool_pct": 0.0000,
            "draw_pct": 0.8000,
        },
        [
            {
                "full_name": "Step Three",
                "compensation_model": "LOCKSTEP",
                "lockstep_step": 3,
                "admission_year": 2008,
            },
            {
                "full_name": "Step Six",
                "compensation_model": "LOCKSTEP",
                "lockstep_step": 6,
                "practice_group": "LITIGATION",
                "admission_year": 2002,
            },
        ],
    )
    step_three, step_six = partners

    published = validate_success(
        api.advance_cycle(cycle["id"], advance_cycle_payload("AWARDS_PUBLISHED"), ADMIN), 200
    )

    # 90,000,000 lockstep gross plus a 0 discretionary reservation against a
    # 100,000,000 pool leaves a non-negative 10,000,000 residual.
    assert published["haircut_applied_pct"] == approx4(0.0000)
    assert published["lockstep_reserved_cents"] == 90_000_000
    assert published["discretionary_pool_cents"] == 0
    assert published["formula_pool_cents"] == 10_000_000
    assert published["total_formula_score"] == approx4(0.0000)
    assert published["undistributed_cash_cents"] == 100_000_000

    award_three = find_award(api, cycle["id"], step_three["id"])
    award_six = find_award(api, cycle["id"], step_six["id"])

    # A pure step function, not a pool share: six rungs pay double three rungs.
    assert award_three["target_award_cents"] == 30_000_000
    assert award_six["target_award_cents"] == 60_000_000
    assert award_three["draw_schedule_monthly_cents"] == 2_000_000
    assert award_six["draw_schedule_monthly_cents"] == 4_000_000
    assert award_three["basis_model"] == "LOCKSTEP"
    assert award_six["basis_model"] == "LOCKSTEP"


def test_true_up_appends_capital_withholding_before_evaluating_the_shortfall(api):
    """PRD 3.9: "If the withheld amount is greater than 0, a
    `CAPITAL_WITHHOLDING` row of that amount is appended *first* and applied to
    the partner's `capital_account_balance_cents`." "Appending and applying the
    withholding before evaluating the shortfall is essential; evaluate it first
    and a partner whose delta fully funds their capital call would be stranded in
    `TRUED_UP` instead of reaching `SETTLED` inside the same operation, which is
    exactly the direct `DRAWING → SETTLED` path."

    Design: Corner/calculations/true_up_appends_capital_withholding_before_evaluating_the_shortfall
    """
    cycle, partners, _committee = _lockstep_cycle_in_deliberation(
        api,
        {
            "distributable_pool_cents": 100_000_000,
            "lockstep_unit_cents": 10_000_000,
            "discretionary_pool_pct": 0.0000,
            "draw_pct": 0.8000,
        },
        [
            {
                "full_name": "Chron Ord",
                "compensation_model": "LOCKSTEP",
                "lockstep_step": 3,
                "admission_year": 2008,
                "opening_capital_cents": 0,
                "target_capital_cents": 5_000_000,
            }
        ],
    )
    partner = partners[0]
    advance_cycle(api, cycle["id"], "AWARDS_PUBLISHED")

    award = find_award(api, cycle["id"], partner["id"])
    assert award["target_award_cents"] == 30_000_000
    assert award["draw_schedule_monthly_cents"] == 2_000_000

    drawn = pay_draw(api, award["id"], period_year=2026, period_month=1)
    assert drawn["draw_paid_cents"] == 2_000_000
    assert drawn["payment_state"] == "DRAWING"

    advance_cycle(api, cycle["id"], "TRUE_UP_OPEN")
    settled = true_up_award(api, award["id"])

    assert settled["final_award_cents"] == 30_000_000
    # 30,000,000 less the 2,000,000 already drawn.
    assert settled["true_up_delta_cents"] == 28_000_000
    # max(0, 5,000,000 - 0).
    assert settled["capital_call_cents"] == 5_000_000

    rows = draw_ledger(api, award["id"])
    assert len(rows) == 3
    assert rows[0]["kind"] == "SCHEDULED_DRAW"
    assert rows[0]["amount_cents"] == 2_000_000
    # The withholding is appended before the payout row.
    assert rows[1]["kind"] == "CAPITAL_WITHHOLDING"
    assert rows[1]["amount_cents"] == 5_000_000
    # 28,000,000 less the 5,000,000 withheld.
    assert rows[2]["kind"] == "TRUE_UP"
    assert rows[2]["amount_cents"] == 23_000_000
    assert [row for row in rows if row["kind"] == "CLAWBACK"] == []

    assert read_partner(api, partner["id"])["capital_account_balance_cents"] == 5_000_000
    assert settled["capital_shortfall_cents"] == 0
    assert settled["payment_state"] == "SETTLED"
