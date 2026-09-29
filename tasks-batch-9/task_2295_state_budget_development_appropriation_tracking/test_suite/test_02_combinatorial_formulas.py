"""Nested minima, per-row rounding order, and the pinned emergency capacity walk."""

from test_helpers import (
    ApiErrorId,
    assert_reversion_carryforward_conservation,
    fixtures,
    validate_error,
    validate_success,
)

TWO_FUND_LINES = (
    {"fund_type": "GENERAL", "program_code": "P100", "introduced_amount_cents": 2_000_000_000},
    {"fund_type": "DEDICATED", "program_code": "P200", "introduced_amount_cents": 2_000_000_000},
)

DEDICATED_ODD_CENT_LINES = (
    {"fund_type": "DEDICATED", "program_code": "P301", "introduced_amount_cents": 1_000_000_010},
    {"fund_type": "DEDICATED", "program_code": "P302", "introduced_amount_cents": 1_000_000_030},
)


class TestAllotmentCeilingNestedMinimum:
    @staticmethod
    def _two_fund_cycle():
        return fixtures.setup_execution_cycle(appropriations=TWO_FUND_LINES)

    def test_general_fund_quarter_one_cap_binds_below_the_request(self, api):
        """PRD §3.5: "The first limit is simply `requested_cents`."
        PRD §3.5: "The second is the **quarter cap**: the appropriation's current authority multiplied by the share of that authority the fund type permits in that quarter, rounded half up to the cent."
        PRD §3.5: "A `GENERAL`-fund line may release 22 percent of its authority in quarter 1 and 26 percent in each of quarters 2, 3, and 4."
        PRD §3.5: "The ceiling is the smallest of the four limits."
        PRD §3.5: "`binding_constraint` records which limit bound, and ties are broken by a fixed precedence rather than by discovery order: scan the labels `REQUEST`, `QUARTER_CAP`, `UNRELEASED_AUTHORITY`, `CASH_FLOW` in that order and record the first whose limit equals the ceiling."
        PRD §3.5: "If the ceiling is below `requested_cents` while `allow_partial` is false, preparation is rejected with `ERR_ALLOTMENT_EXCEEDS_CEILING`; with `allow_partial` true the smaller amount is accepted and recorded."

        Design: Difficulty/combinatorial_formula/allotment_ceiling_nested_min_with_fund_tiered_quarter_cap
        """
        ctx = self._two_fund_cycle()
        general = ctx["appropriations"]["P100"]
        allotment = fixtures.open_allotment(
            general["id"], quarter=1, requested_cents=500_000_000, allow_partial=True
        )

        prepared = validate_success(api.prepare_allotment(allotment["id"], fixtures.ANALYST), 200)

        assert prepared["computed_release_cents"] == 440_000_000
        assert prepared["binding_constraint"] == "QUARTER_CAP"
        assert prepared["status"] == "PREPARED"
        assert prepared["requested_cents"] == 500_000_000
        assert prepared["released_cents"] == 0

    def test_dedicated_fund_share_lets_the_identical_request_bind_instead(self, api):
        """PRD §3.5: "A `DEDICATED` line is front-loaded: 30 percent in each of quarters 1 and 2 and 20 percent in each of quarters 3 and 4."
        PRD §3.5: "The third limit is **unreleased authority**: current authority minus the appropriation's `released_cents`."
        PRD §3.5: "The ceiling is the smallest of the four limits."
        PRD §3.5: "On success the ceiling is written to `computed_release_cents`, the winning label to `binding_constraint`, the acting identifier to `prepared_by_user_id`, the status becomes `PREPARED`, and `version` increments by 1."

        Design: Difficulty/combinatorial_formula/allotment_ceiling_nested_min_with_fund_tiered_quarter_cap
        """
        ctx = self._two_fund_cycle()
        general = ctx["appropriations"]["P100"]
        dedicated = ctx["appropriations"]["P200"]
        assert general["enacted_amount_cents"] == dedicated["enacted_amount_cents"]

        general_allotment = fixtures.open_allotment(
            general["id"], quarter=1, requested_cents=500_000_000, allow_partial=True
        )
        dedicated_allotment = fixtures.open_allotment(
            dedicated["id"], quarter=1, requested_cents=500_000_000, allow_partial=True
        )

        prepared_general = validate_success(
            api.prepare_allotment(general_allotment["id"], fixtures.ANALYST), 200
        )
        prepared_dedicated = validate_success(
            api.prepare_allotment(dedicated_allotment["id"], fixtures.ANALYST), 200
        )

        assert prepared_dedicated["computed_release_cents"] == 500_000_000
        assert prepared_dedicated["binding_constraint"] == "REQUEST"
        assert prepared_dedicated["status"] == "PREPARED"
        assert prepared_dedicated["prepared_by_user_id"] == "analyst-1"
        assert prepared_general["computed_release_cents"] == 440_000_000
        assert prepared_general["binding_constraint"] == "QUARTER_CAP"


class TestCarryforwardRoundedPerRow:
    @staticmethod
    def _closable_cycle():
        ctx = fixtures.setup_execution_cycle(
            agencies=({"agency_code": "DOT", "name": "Department of Transportation",
                       "agency_type": "EXECUTIVE"},),
            appropriations=DEDICATED_ODD_CENT_LINES,
        )
        fixtures.set_clock("2027-07-01T00:00:00Z")
        return ctx

    def test_each_dedicated_line_rounds_its_own_fifteen_percent_cap(self, api, state_controller_headers):
        """PRD §3.9: "For an `ENACTED` row the split is computed per appropriation and rounded per appropriation."
        PRD §3.9: "The carryforward cap is the fund type's permitted share of current authority, rounded half up to the cent: a `GENERAL`-fund line may carry nothing forward at all — its share is zero percent — a `FEDERAL` line may carry its entire authority forward at one hundred percent, and a `DEDICATED` line may carry 15 percent."
        PRD §3.9: "Then `carryforward_cents` is the smaller of the unexpended authority and that already-rounded cap, and `reverted_cents` is the unexpended authority minus `carryforward_cents`."

        Design: Difficulty/combinatorial_formula/carryforward_cap_rounded_per_row_before_cycle_rollup
        """
        ctx = self._closable_cycle()
        first = ctx["appropriations"]["P301"]
        second = ctx["appropriations"]["P302"]

        validate_success(api.close_budget_cycle(ctx["cycle"]["id"], state_controller_headers), 200)

        closed_first = fixtures.read_appropriation(first["id"])
        closed_second = fixtures.read_appropriation(second["id"])

        assert closed_first["carryforward_cents"] == 150_000_002
        assert closed_first["reverted_cents"] == 850_000_008
        assert closed_second["carryforward_cents"] == 150_000_005
        assert closed_second["reverted_cents"] == 850_000_025
        assert closed_first["authority_status"] == "CLOSED"
        assert closed_second["authority_status"] == "CLOSED"
        assert_reversion_carryforward_conservation(closed_first)
        assert_reversion_carryforward_conservation(closed_second)

    def test_cycle_rollup_sums_the_already_rounded_rows(self, api, state_controller_headers):
        """PRD §3.9: "The cycle's rollups are the sums of those already-rounded per-appropriation figures: `total_carryforward_cents` is the sum of `carryforward_cents` across the cycle's appropriations and `total_reverted_cents` is the sum of `reverted_cents`."
        PRD §3.9: "Totalling authority across appropriations and applying the percentage once at the end is wrong and can differ by a cent per row."
        PRD §3.9: "Finally the cycle's `phase` becomes `CLOSED` and its `version` increments by 1."

        Design: Difficulty/combinatorial_formula/carryforward_cap_rounded_per_row_before_cycle_rollup
        """
        ctx = self._closable_cycle()

        validate_success(api.close_budget_cycle(ctx["cycle"]["id"], state_controller_headers), 200)

        cycle = fixtures.read_budget_cycle(ctx["cycle"]["id"])

        assert cycle["total_carryforward_cents"] == 300_000_007
        assert cycle["total_reverted_cents"] == 1_700_000_033
        assert cycle["phase"] == "CLOSED"
        assert cycle["total_expended_cents"] == 0


class TestEmergencyCapacityPinnedOrder:
    @staticmethod
    def _execution_cycle_with_reserve():
        return fixtures.setup_execution_cycle(
            agencies=({"agency_code": "DPS", "name": "Department of Public Safety",
                       "agency_type": "EXECUTIVE"},),
            appropriations=(
                {
                    "fund_type": "GENERAL",
                    "program_code": "P100",
                    "introduced_amount_cents": 2_000_000_000,
                },
            ),
            reserve_balance_cents=500_000_000,
            constitutional_reserve_pct=0.05,
        )

    def test_request_at_exactly_the_capacity_is_granted_because_step_one_excludes_it(
        self, api, budget_director_headers
    ):
        """PRD §3.7: "Step 1: total the current authority — `enacted_amount_cents` plus `transfers_in_cents` minus `transfers_out_cents` — over every appropriation of the cycle whose `fund_type` is `GENERAL` and whose `authority_status` is `ENACTED`, which includes previously granted emergency rows because they are `ENACTED`, and excludes `PENDING`, `LAPSED`, and `CLOSED` rows as well as the request under evaluation."
        PRD §3.7: "Step 2: multiply the cycle's `constitutional_reserve_pct` by that total and round half up to the cent to obtain the required minimum reserve."
        PRD §3.7: "Step 3: the emergency capacity is the greater of zero and the cycle's `reserve_balance_cents` minus its `emergency_granted_cents` minus that already-rounded required minimum reserve."
        PRD §3.7: "Emergency rows skip the legislative dimension entirely: the created row is `GENERAL` fund with `is_emergency` set to true, `introduced_amount_cents`, `committee_balance_cents`, and `enacted_amount_cents` all equal to `requested_amount_cents`, `authority_status` already `ENACTED`, and `cash_status` `UNRELEASED`, all in the same creation."

        Design: Difficulty/combinatorial_formula/emergency_capacity_pinned_four_step_order_excludes_pending_request
        """
        ctx = self._execution_cycle_with_reserve()
        assert ctx["cycle"]["emergency_granted_cents"] == 0

        response = api.create_emergency_appropriation(
            {
                "budget_cycle_id": ctx["cycle"]["id"],
                "agency_id": ctx["agency"]["id"],
                "program_code": "E900",
                "requested_amount_cents": 400_000_000,
                "justification": "Wildfire suppression shortfall",
            },
            budget_director_headers,
        )
        emergency = validate_success(response, 201)

        assert emergency["is_emergency"] is True
        assert emergency["authority_status"] == "ENACTED"
        assert emergency["cash_status"] == "UNRELEASED"
        assert emergency["enacted_amount_cents"] == 400_000_000
        assert emergency["fund_type"] == "GENERAL"
        assert fixtures.read_budget_cycle(ctx["cycle"]["id"])["emergency_granted_cents"] == 400_000_000

    def test_next_request_of_one_cent_fails_because_capacity_has_collapsed(
        self, api, budget_director_headers
    ):
        """PRD §3.7: "Step 4: if `requested_amount_cents` exceeds the capacity, reject with `ERR_EMERGENCY_EXCEEDS_RESERVE_CAPACITY`; otherwise grant the appropriation and add `requested_amount_cents` to the cycle's `emergency_granted_cents`."
        PRD §3.7: "The cycle's `emergency_granted_cents` — the sum of `enacted_amount_cents` over its appropriations where `is_emergency` is true and `authority_status` is `ENACTED` — is recomputed and the cycle's `version` increments by 1."
        PRD §2.12: "The emergency request fits inside the reserve capacity — otherwise `ERR_EMERGENCY_EXCEEDS_RESERVE_CAPACITY` (422)."

        Design: Difficulty/combinatorial_formula/emergency_capacity_pinned_four_step_order_excludes_pending_request
        """
        ctx = self._execution_cycle_with_reserve()
        granted = validate_success(
            api.create_emergency_appropriation(
                {
                    "budget_cycle_id": ctx["cycle"]["id"],
                    "agency_id": ctx["agency"]["id"],
                    "program_code": "E900",
                    "requested_amount_cents": 400_000_000,
                    "justification": "Wildfire suppression shortfall",
                },
                budget_director_headers,
            ),
            201,
        )
        assert granted["enacted_amount_cents"] == 400_000_000

        response = api.create_emergency_appropriation(
            {
                "budget_cycle_id": ctx["cycle"]["id"],
                "agency_id": ctx["agency"]["id"],
                "program_code": "E901",
                "requested_amount_cents": 1,
                "justification": "Second wildfire draw",
            },
            budget_director_headers,
        )
        validate_error(response, ApiErrorId.ERR_EMERGENCY_EXCEEDS_RESERVE_CAPACITY, 422)

        cycle = fixtures.read_budget_cycle(ctx["cycle"]["id"])
        assert cycle["emergency_granted_cents"] == 400_000_000
