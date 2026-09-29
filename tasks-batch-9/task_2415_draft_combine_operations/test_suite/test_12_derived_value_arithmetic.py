"""Derived-value arithmetic across the draft cycle.

Covers the money and points figures the server computes for itself: the slotted
rookie money minted onto every draft pick, the trade chart decay, the per-round
selection clock constant, the compensatory scoring variants and the award-pass
input set, the bulk invitation selector's ranking, and the medical share access
window. Every figure is asserted at the precision the domain publishes it in:
whole cents for money, one decimal for chart points, two decimals for scores.
"""

from test_helpers import (
    ADMIN,
    DRAFT_START_AT,
    advance_clock,
    assert_cents_equal,
    assert_chart_points,
    assert_score,
    build_combine_week,
    build_declaration_open,
    build_medical_evaluation,
    build_order_final,
    build_order_pending,
    claim_verify_payload,
    declare_prospect,
    file_claim,
    finalize_order,
    grant_consent,
    invitation_selection_payload,
    list_picks,
    make_club_gm_headers,
    move_phase,
    pick_by_overall_number,
    pick_index,
    read_claim,
    read_club,
    read_cycle,
    read_evaluation,
    read_pick,
    read_prospect,
    register_prospect,
    request_share,
    rule_prospect_eligible,
    run_lottery,
    selection_payload,
    set_clock,
    share_decision_payload,
    validate_paginated,
    validate_success,
)


class TestSlottedPickMoney:
    """The four slot money fields minted onto every regular draft pick."""

    def test_second_overall_pick_prorates_its_bonus_before_multiplying_back_up(
        self, api
    ):
        """Overall pick two publishes slot money on the pinned proration order.

        The round-one, slot-two year-one base is 118,000,000 cents, the four
        escalated years sum to 502,951,609, the sixty percent bonus is
        301,770,965 and the per-year bonus share is 75,442,741, so the total cap
        commitment lands one cent below the naive total plus bonus.

        PRD: "The same slotting arithmetic runs at draft-order finalize time for every minted pick, populating four read-only fields on the pick from that pick's own position and the four-year drafted length: `slot_total_value_cents`, `slot_signing_bonus_cents`, `slot_first_year_cap_charge_cents` and `slot_total_cap_commitment_cents`."
        PRD: "And `total_cap_commitment_cents` is `total_value_cents` plus the per-year bonus share multiplied by `contract_years`."

        Design: Corner/calculations/minted_pick_slot_money_uses_the_pinned_per_year_rounding
        """
        state = build_order_final(api)
        second = pick_by_overall_number(state["picks"], 2)

        pick = validate_success(
            api.get_draft_pick(second["id"], ADMIN), expected_status=200
        )

        assert pick["round_number"] == 1
        assert pick["pick_in_round"] == 2
        assert pick["overall_number"] == 2
        assert_cents_equal(pick["slot_total_value_cents"], 502951609)
        assert_cents_equal(pick["slot_signing_bonus_cents"], 301770965)
        assert_cents_equal(pick["slot_first_year_cap_charge_cents"], 193442741)
        assert_cents_equal(pick["slot_total_cap_commitment_cents"], 804722573)
        assert pick["slot_total_cap_commitment_cents"] != 804722574


class TestChartValueDecay:
    """Chart points minted at finalize time and rolled into cycle inventory."""

    def test_third_slot_of_each_round_rounds_the_decay_to_one_decimal(self, api):
        """A three-club order exposes the chart rounding at the third slot.

        Round one slot three is 883.6 exactly while round two slot three is
        371.112 before rounding, so it must publish as 371.1, and the six minted
        picks must aggregate to 4009.5 chart points on the cycle.

        PRD: "Every pick carries a **chart value** minted at finalize time: `chart_value_points` is the round's chart base multiplied by a decay factor of 0.94 raised to the power of `pick_in_round` minus one, rounded half up to one decimal place."

        Design: Corner/calculations/chart_decay_rounds_to_one_decimal_at_the_third_slot
        """
        state = build_order_pending(api, club_codes=["ELM", "HAR", "BRN"])
        cycle_id = state["cycle"]["id"]
        run_lottery(api, cycle_id, [300, 200, 50])

        finalize = validate_success(
            api.finalize_draft_order(cycle_id, None, ADMIN), expected_status=200
        )
        assert finalize["created_pick_count"] == 6

        picks, meta = validate_paginated(
            api.list_draft_picks(ADMIN, {"draft_cycle_id": cycle_id, "limit": 10})
        )
        assert meta["total_count"] == 6

        third_overall = picks[2]
        assert third_overall["overall_number"] == 3
        assert third_overall["round_number"] == 1
        assert third_overall["pick_in_round"] == 3
        assert_chart_points(third_overall["chart_value_points"], 883.6)

        sixth_overall = picks[5]
        assert sixth_overall["overall_number"] == 6
        assert sixth_overall["round_number"] == 2
        assert sixth_overall["pick_in_round"] == 3
        assert_chart_points(sixth_overall["chart_value_points"], 371.1)

        cycle = read_cycle(api, cycle_id)
        assert_chart_points(cycle["pick_inventory_chart_points"], 4009.5)
        assert cycle["pick_inventory_count"] == 6

        assert read_club(api, state["clubs"]["BRN"]["id"])["draft_order_index"] == 2
        assert read_club(api, state["clubs"]["HAR"]["id"])["draft_order_index"] == 3


class TestSelectionClockConstants:
    """The allotted minutes are keyed on the round the pick belongs to."""

    def test_round_two_pick_inherits_a_seven_minute_deadline(self, api):
        """The first round-two pick gets seven minutes, not round one's ten.

        Both round-one picks are used at 18:00:00.000Z, so the round-two pick
        that inherits the clock starts from the current instant and its deadline
        lands seven minutes later.

        PRD: "The allotted minutes are 10 for round one, 7 for round two, 5 for rounds three, four, five and six, and 4 for round seven."

        Design: Corner/calculations/round_two_pick_receives_the_seven_minute_clock_constant
        """
        state = build_declaration_open(api)
        cycle_id = state["cycle"]["id"]

        first = register_prospect(api, cycle_id)
        second = register_prospect(
            api,
            cycle_id,
            full_name="Brooks Hale",
            position_group="WR",
            school_code="STH",
            scouting_grade=88.00,
            position_group_scarcity_rank=3,
        )
        for prospect in (first, second):
            declare_prospect(api, prospect)
            rule_prospect_eligible(api, prospect)

        move_phase(api, cycle_id, "COMBINE_WEEK")
        move_phase(api, cycle_id, "ORDER_PENDING")
        run_lottery(api, cycle_id)
        finalize_order(api, cycle_id)
        picks = pick_index(list_picks(api, cycle_id))

        set_clock(api, DRAFT_START_AT)
        move_phase(api, cycle_id, "DRAFT_LIVE")
        advance_clock(api, cycle_id)

        elm = state["clubs"]["ELM"]
        har = state["clubs"]["HAR"]
        validate_success(
            api.create_selection(
                picks["r1p1"]["id"],
                selection_payload(first["id"]),
                make_club_gm_headers(elm["id"]),
            ),
            expected_status=200,
        )

        used = validate_success(
            api.create_selection(
                picks["r1p2"]["id"],
                selection_payload(second["id"]),
                make_club_gm_headers(har["id"]),
            ),
            expected_status=200,
        )

        assert used["status"] == "USED"
        assert used["selected_prospect_id"] == second["id"]

        on_clock = read_pick(api, picks["r2p1"]["id"])
        assert on_clock["status"] == "ON_CLOCK"
        assert on_clock["round_number"] == 2
        assert on_clock["on_clock_started_at"] == "2027-04-22T18:00:00.000Z"
        assert on_clock["deadline_at"] == "2027-04-22T18:07:00.000Z"
        assert on_clock["timeouts_used"] == 0

        assert read_cycle(api, cycle_id)["current_overall_number"] == 3


class TestCompensatoryAwardPass:
    """Which compensatory claims the finalize-time award pass reads."""

    def test_submitted_claim_mints_no_compensatory_pick_at_finalize(self, api):
        """A qualifying but unverified departure claim is ignored by the award pass.

        The claim previews a score of 1470.00 and qualifies, yet because it never
        reached VERIFIED the finalize mint produces only the four regular picks
        and leaves the claim untouched.

        PRD: "Only claims in `VERIFIED` enter the award pass; claims still in `SUBMITTED` and claims in `REJECTED` are excluded."

        Design: Corner/calculations/unverified_compensatory_claim_is_excluded_from_the_award_pass
        """
        state = build_combine_week(api)
        cycle_id = state["cycle"]["id"]
        claim = file_claim(api, state["cycle"], state["clubs"]["ELM"])

        move_phase(api, cycle_id, "ORDER_PENDING")
        run_lottery(api, cycle_id)

        finalize = validate_success(
            api.finalize_draft_order(cycle_id, None, ADMIN), expected_status=200
        )

        assert finalize["created_pick_count"] == 4
        assert finalize["compensatory_pick_count"] == 0

        stored = read_claim(api, claim["id"])
        assert stored["status"] == "SUBMITTED"
        assert_score(stored["claim_score"], 1470.00)
        assert stored["qualifies"] is True
        assert stored["awarded_round"] == 0

        assert read_cycle(api, cycle_id)["pick_inventory_count"] == 4


class TestInvitationSelectorRanking:
    """The bulk selector's pool filter and its tie-break chain."""

    def test_selector_prefers_the_scarcer_of_two_tied_declared_prospects(self, api):
        """The tie on grade is broken by scarcity, and the undeclared top grade is skipped.

        The highest-graded prospect never declared, so the pool holds only the
        two prospects tied at 88.00 and a target of one must take the scarcer
        position group.

        PRD: "The pool is then ordered by `scouting_grade` descending; ties on grade compared at two decimal places are broken by `position_group_scarcity_rank` ascending, so that scarcer position groups are favoured; ties on both are broken by `created_at` ascending."

        Design: Corner/calculations/invitation_selector_skips_undeclared_and_breaks_the_grade_tie_by_scarcity
        """
        state = build_declaration_open(api)
        cycle_id = state["cycle"]["id"]

        undeclared = register_prospect(api, cycle_id)
        broader = register_prospect(
            api,
            cycle_id,
            full_name="Brooks Hale",
            position_group="WR",
            school_code="STH",
            scouting_grade=88.00,
            position_group_scarcity_rank=3,
        )
        scarcer = register_prospect(
            api,
            cycle_id,
            full_name="Cade Rios",
            position_group="TE",
            school_code="EST",
            scouting_grade=88.00,
            position_group_scarcity_rank=2,
        )
        declare_prospect(api, broader)
        declare_prospect(api, scarcer)

        result = validate_success(
            api.select_combine_invitations(
                cycle_id, invitation_selection_payload(1), ADMIN
            ),
            expected_status=200,
        )

        assert result["invited_count"] == 1
        assert result["invited_prospect_ids"] == [scarcer["id"]]

        assert read_prospect(api, scarcer["id"])["invitation_status"] == "INVITED"
        assert read_prospect(api, broader["id"])["invitation_status"] == "NOT_INVITED"
        skipped = read_prospect(api, undeclared["id"])
        assert skipped["invitation_status"] == "NOT_INVITED"
        assert skipped["declaration_status"] == "UNDECLARED"


class TestShareAccessWindow:
    """The three caps that decide a granted share's expiry."""

    def test_consent_expiry_wins_when_it_is_the_tightest_cap(self, api):
        """Granting takes the consent expiry over both league caps.

        Combine week plus seventy-five days lands on 2027-05-14T20:00:00.000Z
        and the draft start plus three days on 2027-04-25T18:00:00.000Z, so the
        consent expiry of 2027-03-15T12:00:00.000Z is the earliest of the three.

        PRD: "The access window itself is computed at the moment of granting, and it is the *earliest* of three independent caps: the cycle's `combine_week_end_at` plus seventy-five days, the cycle's `draft_start_at` plus three days, and the prospect's own `consent_expires_at`."
        PRD: "Granting stamps `granted_at` with the current logical instant, computes `expires_at`, and increments the evaluation's `active_share_count` by one."

        Design: Corner/calculations/share_window_takes_the_consent_expiry_when_it_is_the_earliest_cap
        """
        state = build_medical_evaluation(api)
        grant_consent(api, state["prospect"])
        share = request_share(api, state["evaluation"], state["clubs"]["ELM"])

        granted = validate_success(
            api.decide_medical_record_share(
                share["id"], share_decision_payload("GRANT"), ADMIN
            ),
            expected_status=200,
        )

        assert granted["status"] == "GRANTED"
        assert granted["granted_at"] == "2027-02-22T08:45:00.000Z"
        assert granted["expires_at"] == "2027-03-15T12:00:00.000Z"
        assert granted["effective_access"] == "FULL"

        evaluation = read_evaluation(api, state["evaluation"]["id"])
        assert evaluation["active_share_count"] == 1
        assert evaluation["disclosure_state"] == "DISCLOSABLE"
        assert evaluation["confidentiality_tier"] == "STANDARD"

        prospect = read_prospect(api, state["prospect"]["id"])
        assert prospect["medical_clearance_status"] == "CLEARED"


class TestCompensatoryScoreVariants:
    """The banded authoritative score beside the raw-snap advisory score."""

    def test_verify_publishes_both_variants_and_only_the_banded_one_qualifies(
        self, api
    ):
        """VERIFY freezes 1470.00 authoritative beside 1064.00 advisory.

        A snap share of 0.72 sits inside the top band, so the authoritative
        figure uses the factor 1.00 while the advisory figure uses 0.72; the
        qualifying flag follows the authoritative figure alone.

        PRD: "`VERIFY` advances `SUBMITTED` to `VERIFIED` and is permitted only while the cycle is `COMBINE_WEEK` or `ORDER_PENDING`; it freezes both `claim_score` and `advisory_snap_adjusted_score` at their current values."
        PRD: "`advisory_snap_adjusted_score` is the same base figure multiplied by the *raw* `snap_pct` rather than by the band, plus the same honours bonus, rounded half up to two decimal places."

        Design: Corner/calculations/verify_freezes_both_score_variants_and_the_authoritative_one_decides
        """
        state = build_combine_week(api)
        claim = file_claim(api, state["cycle"], state["clubs"]["ELM"])

        verified = validate_success(
            api.verify_compensatory_claim(
                claim["id"], claim_verify_payload("VERIFY"), ADMIN
            ),
            expected_status=200,
        )

        assert verified["status"] == "VERIFIED"
        assert_score(verified["claim_score"], 1470.00)
        assert_score(verified["advisory_snap_adjusted_score"], 1064.00)
        assert verified["qualifies"] is True
        assert verified["awarded_round"] == 0
        assert verified["awarded_sequence"] == 0
