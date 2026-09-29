"""Contract escalation arithmetic and the spares provisioning waterfall."""

from test_helpers import (
    CUSTOMER_REP,
    PROJECT_DIRECTOR,
    ApiErrorId,
    assert_project,
    assert_spare_part_line,
    assert_spares_ledger_conserved,
    decide_change_order,
    make_project,
    make_spare_part_line,
    make_submitted_change_order,
    provision_spares,
    read_change_order,
    read_project,
    spare_lines_by_part_no,
    spares_provisioning_payload,
    validate_error,
)

FIVE_LINES = (
    {"part_no": "MOTOR-3KW", "criticality": "CRITICAL", "unit_cost_cents": 850_000,
     "min_stock_qty": 2, "lead_time_days": 45},
    {"part_no": "SORT-SHOE", "criticality": "CRITICAL", "unit_cost_cents": 125_500,
     "min_stock_qty": 12, "lead_time_days": 30},
    {"part_no": "BELT-24IN", "criticality": "MAJOR", "unit_cost_cents": 215_001,
     "min_stock_qty": 6, "lead_time_days": 60},
    {"part_no": "PHOTO-EYE", "criticality": "MAJOR", "unit_cost_cents": 430_002,
     "min_stock_qty": 3, "lead_time_days": 21},
    {"part_no": "LABEL-STK", "criticality": "MINOR", "unit_cost_cents": 4_000,
     "min_stock_qty": 50, "lead_time_days": 7},
)


class TestEscalationTierOnPreFeeSubtotal:
    """A price-only change order that lands the subtotal exactly on the tier boundary."""

    def test_tier_is_selected_on_the_subtotal_not_on_the_contract_value(self, api):
        """A subtotal of exactly 250,000,000 cents stays in the 150 basis point tier.

        PRD §3.1: "The evaluation order here is pinned and must not be inverted: the
        tier is **always** selected on the pre-fee subtotal, never on
        `contract_value_cents`, even though the contract value contains the fee."

        Design: Difficulty/combinatorial_formula/escalation_tier_keyed_on_pre_fee_subtotal
        """
        project = make_project(api)
        assert project["escalation_fee_cents"] == 3_600_000
        assert project["contract_value_cents"] == 243_600_000

        change_order = make_submitted_change_order(
            api,
            project["id"],
            title="Controls cabinet upgrade",
            scope_delta_cph=0,
            price_delta_cents=10_000_000,
            schedule_delta_days=5,
        )
        decide_change_order(
            api,
            project["id"],
            change_order["id"],
            "APPROVE",
            headers=CUSTOMER_REP,
            decision_comment="Cabinet upgrade accepted",
        )

        repriced = read_project(api, project["id"])
        assert_project(repriced)
        assert repriced["escalation_fee_cents"] == 3_750_000
        assert repriced["contract_value_cents"] == 253_750_000
        assert repriced["contract_value_cents"] != 255_500_000

    def test_price_only_approval_leaves_the_delivery_dimension_untouched(self, api):
        """A zero scope delta recomputes money and nothing else.

        PRD §3.8: "A pure-price change order — `scope_delta_cph` exactly 0 —
        recomputes money only and leaves the delivery dimension, the simulations, the
        windows and the lots entirely untouched."

        Design: Difficulty/combinatorial_formula/escalation_tier_keyed_on_pre_fee_subtotal
        """
        project = make_project(api)
        change_order = make_submitted_change_order(
            api,
            project["id"],
            title="Controls cabinet upgrade",
            scope_delta_cph=0,
            price_delta_cents=10_000_000,
            schedule_delta_days=5,
        )
        decided = decide_change_order(
            api,
            project["id"],
            change_order["id"],
            "APPROVE",
            headers=CUSTOMER_REP,
            decision_comment="Cabinet upgrade accepted",
        )

        assert decided["status"] == "APPROVED"
        assert decided["decision_comment"] == "Cabinet upgrade accepted"
        after = read_project(api, project["id"])
        assert after["commercial_status"] == "CLEAN"
        assert after["delivery_status"] == "DESIGN"
        assert after["design_version"] == 1


class TestSparesWeightedTargetRounding:
    """Per-line half-up rounding before any accumulation."""

    def test_weighted_target_is_rounded_half_up_on_each_line_at_creation(self, api):
        """Two 1,290,006-cent MAJOR requests each round up to 774,004 cents.

        PRD §3.9: "At creation the line's `requested_cents` is computed as
        `unit_cost_cents` multiplied by `min_stock_qty`, and its
        `weighted_target_cents` as `requested_cents` multiplied by the coverage factor
        for its class, divided by 10000 and rounded half up to a whole cent."

        Design: Difficulty/combinatorial_formula/spares_weighted_target_rounds_per_line_before_summation
        """
        project = make_project(api)
        for line in FIVE_LINES:
            make_spare_part_line(api, project["id"], **line)

        lines = spare_lines_by_part_no(api, project["id"])
        for part_no in ("BELT-24IN", "PHOTO-EYE"):
            assert_spare_part_line(lines[part_no])
            assert lines[part_no]["requested_cents"] == 1_290_006
            assert lines[part_no]["weighted_target_cents"] == 774_004
        assert lines["MOTOR-3KW"]["weighted_target_cents"] == 1_700_000
        assert lines["SORT-SHOE"]["weighted_target_cents"] == 1_506_000
        assert lines["LABEL-STK"]["weighted_target_cents"] == 0

    def test_waterfall_accumulates_the_already_rounded_line_targets(self, api):
        """The two rounded 774,004 targets sum to 1,548,008 rather than 1,548,007.

        PRD §3.9: "Each candidate in turn recomputes `requested_cents` as
        `unit_cost_cents` multiplied by `min_stock_qty`, then `weighted_target_cents`
        as that request multiplied by the class coverage factor, divided by 10000 and
        rounded half up to a whole cent **before any accumulation happens** — each
        line is rounded on its own, and summing the raw requests and rounding the
        total afterwards is a different answer that can differ by a cent per rounded
        line."

        Design: Difficulty/combinatorial_formula/spares_weighted_target_rounds_per_line_before_summation
        """
        project = make_project(api)
        for line in FIVE_LINES:
            make_spare_part_line(api, project["id"], **line)
        provision_spares(api, project["id"])

        lines = spare_lines_by_part_no(api, project["id"])
        assert lines["BELT-24IN"]["allocated_cents"] == 774_004
        assert lines["PHOTO-EYE"]["allocated_cents"] == 774_004
        assert (
            lines["BELT-24IN"]["allocated_cents"] + lines["PHOTO-EYE"]["allocated_cents"]
            == 1_548_008
        )
        assert lines["MOTOR-3KW"]["allocated_cents"] == 1_700_000
        assert lines["MOTOR-3KW"]["status"] == "ALLOCATED"
        assert lines["SORT-SHOE"]["allocated_cents"] == 1_506_000
        assert lines["SORT-SHOE"]["status"] == "ALLOCATED"
        assert lines["LABEL-STK"]["allocated_cents"] == 0
        assert lines["LABEL-STK"]["status"] == "DRAFT"

        after = read_project(api, project["id"])
        assert after["spares_allocated_cents"] == 4_754_008
        assert after["spares_unallocated_cents"] == 245_992


class TestSparesEmptyFundablePool:
    """A crib made only of MINOR lines has no fundable candidate."""

    def test_run_with_only_minor_lines_is_rejected(self, api):
        """The candidate filter yields nothing, so the run fails rather than succeeding.

        PRD §3.9: "If the candidate set is empty the whole run is rejected with
        `ERR_NO_FUNDABLE_SPARE_LINES` and nothing is persisted."

        Design: Difficulty/boundary_precision_check/spares_provisioning_with_empty_fundable_pool_rejected
        """
        project = make_project(api)
        make_spare_part_line(
            api,
            project["id"],
            part_no="LABEL-STK",
            criticality="MINOR",
            unit_cost_cents=4_000,
            min_stock_qty=50,
            lead_time_days=7,
        )
        make_spare_part_line(
            api,
            project["id"],
            part_no="GUIDE-RAIL",
            criticality="MINOR",
            unit_cost_cents=9_000,
            min_stock_qty=4,
            lead_time_days=14,
        )
        current = read_project(api, project["id"])

        response = api.run_spares_provisioning(
            project["id"], spares_provisioning_payload(current["version"]), PROJECT_DIRECTOR
        )
        validate_error(response, ApiErrorId.ERR_NO_FUNDABLE_SPARE_LINES.value)

    def test_rejected_run_leaves_the_ledger_at_budget_equals_unallocated(self, api):
        """Nothing is persisted, so the pool still reads entirely unallocated.

        PRD §3.9: "`MINOR` lines are excluded, keep `status` `DRAFT` and keep
        `allocated_cents` 0."

        Design: Difficulty/boundary_precision_check/spares_provisioning_with_empty_fundable_pool_rejected
        """
        project = make_project(api)
        make_spare_part_line(
            api,
            project["id"],
            part_no="LABEL-STK",
            criticality="MINOR",
            unit_cost_cents=4_000,
            min_stock_qty=50,
            lead_time_days=7,
        )
        make_spare_part_line(
            api,
            project["id"],
            part_no="GUIDE-RAIL",
            criticality="MINOR",
            unit_cost_cents=9_000,
            min_stock_qty=4,
            lead_time_days=14,
        )
        current = read_project(api, project["id"])
        api.run_spares_provisioning(
            project["id"], spares_provisioning_payload(current["version"]), PROJECT_DIRECTOR
        )

        after = read_project(api, project["id"])
        assert after["spares_allocated_cents"] == 0
        assert after["spares_unallocated_cents"] == 5_000_000
        assert_spares_ledger_conserved(after)
        lines = spare_lines_by_part_no(api, project["id"])
        for part_no in ("LABEL-STK", "GUIDE-RAIL"):
            assert lines[part_no]["status"] == "DRAFT"
            assert lines[part_no]["allocated_cents"] == 0
            assert lines[part_no]["weighted_target_cents"] == 0


class TestSparesLedgerConservation:
    """Re-provisioning resets before re-funding, so no cent is double counted."""

    def test_first_run_splits_the_budget_and_conserves_it(self, api):
        """Two CRITICAL lines take 3,206,000 cents and leave 1,794,000 cents.

        PRD §3.9: "When the pass is complete, the project's `spares_allocated_cents`
        is the sum of `allocated_cents` across the candidates and
        `spares_unallocated_cents` is the surviving remainder, so that
        `spares_budget_cents` always equals `spares_allocated_cents` plus
        `spares_unallocated_cents` after every run — the residual absorbs every
        fraction and no cent is created or destroyed."

        Design: Difficulty/compensating_invariant/spares_ledger_conserved_across_reprovisioning_runs
        """
        project = make_project(api)
        for line in FIVE_LINES[:2]:
            make_spare_part_line(api, project["id"], **line)
        provision_spares(api, project["id"])

        after = read_project(api, project["id"])
        assert after["spares_allocated_cents"] == 3_206_000
        assert after["spares_unallocated_cents"] == 1_794_000
        assert after["spares_allocated_cents"] + after["spares_unallocated_cents"] == 5_000_000
        assert_spares_ledger_conserved(after)

    def test_second_run_releases_prior_allocations_before_refunding(self, api):
        """A re-funded CRITICAL line reads 1,700,000 cents, not a doubled 3,400,000.

        PRD §3.9: "The run begins with a compensating reset: every spare part line of
        the project whose `status` is `ALLOCATED`, `PARTIAL` or `UNFUNDED` is returned
        to `DRAFT` with `allocated_cents` set back to 0, the project's
        `spares_allocated_cents` is set to 0, and its `spares_unallocated_cents` is set
        back to the full `spares_budget_cents`."

        Design: Difficulty/compensating_invariant/spares_ledger_conserved_across_reprovisioning_runs
        """
        project = make_project(api)
        for line in FIVE_LINES[:2]:
            make_spare_part_line(api, project["id"], **line)
        provision_spares(api, project["id"])

        for line in FIVE_LINES[2:4]:
            make_spare_part_line(api, project["id"], **line)
        provision_spares(api, project["id"])

        after = read_project(api, project["id"])
        assert after["spares_allocated_cents"] == 4_754_008
        assert after["spares_unallocated_cents"] == 245_992
        assert after["spares_allocated_cents"] + after["spares_unallocated_cents"] == 5_000_000

        lines = spare_lines_by_part_no(api, project["id"])
        assert lines["MOTOR-3KW"]["allocated_cents"] == 1_700_000
        assert lines["BELT-24IN"]["allocated_cents"] == 774_004
        assert lines["PHOTO-EYE"]["allocated_cents"] == 774_004
        for line in lines.values():
            assert line["status"] in ("ALLOCATED", "PARTIAL", "UNFUNDED", "DRAFT")


class TestChangeOrderDecisionRecord:
    """The approved order itself carries the rep's remark and identity."""

    def test_approval_stores_the_decision_comment_and_reviewer(self, api):
        """The rep's opaque identifier lands in reviewed_by_user_id.

        PRD §3.8: "`decision_comment` and `reviewed_by_user_id` are stored, and the
        project's `version` and the order's `version` each increment by 1."

        Design: Difficulty/combinatorial_formula/escalation_tier_keyed_on_pre_fee_subtotal
        """
        project = make_project(api)
        change_order = make_submitted_change_order(
            api,
            project["id"],
            title="Controls cabinet upgrade",
            scope_delta_cph=0,
            price_delta_cents=10_000_000,
            schedule_delta_days=5,
        )
        decide_change_order(
            api,
            project["id"],
            change_order["id"],
            "APPROVE",
            headers=CUSTOMER_REP,
            decision_comment="Cabinet upgrade accepted",
        )

        stored = read_change_order(api, change_order["id"])
        assert stored["status"] == "APPROVED"
        assert stored["decision_comment"] == "Cabinet upgrade accepted"
        assert stored["reviewed_by_user_id"] == CUSTOMER_REP["X-User-ID"]
        assert stored["schedule_delta_days"] == 5
