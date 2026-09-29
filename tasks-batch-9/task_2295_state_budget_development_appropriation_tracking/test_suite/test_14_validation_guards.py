"""Guards that read derived state: replay floors, certification, duty separation and ceilings."""

from test_helpers import (
    ApiErrorId,
    fixtures,
    make_director_headers,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestReplayFloorGuard:
    @staticmethod
    def _line_with_a_deep_first_cut_and_a_later_restoration():
        ctx = fixtures.setup_legislative_cycle(
            appropriations=(
                {
                    "fund_type": "GENERAL",
                    "program_code": "P100",
                    "introduced_amount_cents": 2_000_000_000,
                    "enact": False,
                },
            )
        )
        appropriation_id = ctx["appropriations"]["P100"]["id"]
        fixtures.record_committee_action(
            appropriation_id,
            chamber="HOUSE",
            committee_name="Appropriations",
            action_type="DECREASE",
            amount_cents=1_500_000_000,
            sequence_number=1,
        )
        fixtures.record_committee_action(
            appropriation_id,
            chamber="SENATE",
            committee_name="Finance",
            action_type="INCREASE",
            amount_cents=1_000_000_000,
            sequence_number=3,
        )
        ctx["appropriation_id"] = appropriation_id
        return ctx

    def test_an_intermediate_negative_position_rejects_the_insert_while_exactly_zero_passes(
        self, api, legislative_fiscal_officer_headers
    ):
        """PRD §3.4: "If the balance would fall below zero at any position in the replay, the entire insert is rejected with `ERR_NEGATIVE_APPROPRIATION_BALANCE` and no row is written and no balance is changed."
        PRD §2.12: "The replayed committee balance is never negative at any sequence position — otherwise `ERR_NEGATIVE_APPROPRIATION_BALANCE` (422). Applies to `POST /fiscal/committee-actions`."
        PRD §3.4: "The replay starts from `introduced_amount_cents` and applies each action in turn, writing the post-action balance onto that action as its `running_balance_cents`."
        PRD §3.4: "The actions of an appropriation can be listed in `sequence_number` ascending order."

        Design: Corner/validations/negative_intermediate_committee_balance_rejects_the_whole_insert
        """
        ctx = self._line_with_a_deep_first_cut_and_a_later_restoration()
        appropriation_id = ctx["appropriation_id"]

        def cut(amount_cents):
            return {
                "appropriation_id": appropriation_id,
                "chamber": "SENATE",
                "committee_name": "Finance",
                "action_type": "DECREASE",
                "amount_cents": amount_cents,
                "sequence_number": 2,
            }

        validate_error(
            api.create_committee_action(cut(600_000_000), legislative_fiscal_officer_headers),
            ApiErrorId.ERR_NEGATIVE_APPROPRIATION_BALANCE,
            422,
        )
        assert (
            fixtures.read_appropriation(appropriation_id)["committee_balance_cents"]
            == 1_500_000_000
        )

        accepted = validate_success(
            api.create_committee_action(cut(500_000_000), legislative_fiscal_officer_headers),
            201,
        )
        assert accepted["running_balance_cents"] == 0

        rows, meta = validate_paginated(
            api.list_appropriation_committee_actions(
                appropriation_id, legislative_fiscal_officer_headers
            )
        )
        assert [row["running_balance_cents"] for row in rows] == [500_000_000, 0, 1_000_000_000]
        assert meta["total_count"] == 3
        assert (
            fixtures.read_appropriation(appropriation_id)["committee_balance_cents"]
            == 1_000_000_000
        )


class TestCertificationRequiresGeneralFundRevenue:
    @staticmethod
    def _prep_cycle_whose_only_adopted_forecast_is_dedicated():
        cycle = fixtures.open_budget_cycle(constitutional_reserve_pct=0.05)
        general = fixtures.record_forecast(
            cycle["id"],
            source_code="SALES_TAX",
            fund_type="GENERAL",
            amount_cents=10_000_000_000,
        )
        fixtures.adopt_forecast(general["id"])
        fixtures.advance_phase(cycle["id"], "EXECUTIVE_PREP")

        dedicated = fixtures.record_forecast(
            cycle["id"],
            source_code="SALES_TAX",
            fund_type="DEDICATED",
            amount_cents=900_000_000,
        )
        fixtures.adopt_forecast(dedicated["id"], supersedes_forecast_id=general["id"])
        return {"cycle": cycle, "general": general, "dedicated": dedicated}

    def test_a_dedicated_forecast_alone_cannot_certify_but_a_general_one_can(
        self, api, budget_director_headers
    ):
        """PRD §3.3: "It requires the cycle to be in `EXECUTIVE_PREP`; it requires adopted general-fund revenue to be greater than zero, meaning at least one `ADOPTED` `GENERAL` forecast exists, otherwise `ERR_NO_ADOPTED_FORECAST`; and it requires the balance test above to pass, otherwise `ERR_BUDGET_NOT_BALANCED`."
        PRD §3.1: "The cycle's `adopted_general_fund_revenue_cents` is the sum of `amount_cents` over every forecast of that cycle whose status is `ADOPTED` and whose `fund_type` is `GENERAL`; `DRAFT` and `SUPERSEDED` rows contribute nothing, and `FEDERAL` and `DEDICATED` rows contribute nothing regardless of status."
        PRD §3.3: "Then `required_reserve_cents` is `constitutional_reserve_pct` multiplied by that adopted revenue, rounded half up to the cent."
        PRD §3.3: "On success `required_reserve_cents` is rewritten, `balance_certified` becomes true, and the cycle's `version` increments by 1."
        PRD §2.12: "At least one adopted `GENERAL`-fund revenue forecast exists for the cycle — otherwise `ERR_NO_ADOPTED_FORECAST` (422). Applies to `POST /fiscal/budget-cycles/{id}/advance-phase` and `POST /fiscal/budget-cycles/{id}/certify-balance`."

        Design: Corner/validations/certify_balance_without_an_adopted_general_fund_forecast_is_rejected
        """
        ctx = self._prep_cycle_whose_only_adopted_forecast_is_dedicated()
        cycle_id = ctx["cycle"]["id"]

        stripped = fixtures.read_budget_cycle(cycle_id)
        assert stripped["adopted_general_fund_revenue_cents"] == 0
        assert stripped["required_reserve_cents"] == 0

        validate_error(
            api.certify_cycle_balance(cycle_id, budget_director_headers),
            ApiErrorId.ERR_NO_ADOPTED_FORECAST,
            422,
        )
        refused = fixtures.read_budget_cycle(cycle_id)
        assert refused["balance_certified"] is False
        assert refused["required_reserve_cents"] == 0

        replacement = fixtures.record_forecast(
            cycle_id,
            source_code="INCOME_TAX",
            fund_type="GENERAL",
            amount_cents=10_000_000_000,
        )
        fixtures.adopt_forecast(replacement["id"])

        certified = validate_success(
            api.certify_cycle_balance(cycle_id, budget_director_headers), 200
        )
        assert certified["balance_certified"] is True
        assert certified["adopted_general_fund_revenue_cents"] == 10_000_000_000
        assert certified["required_reserve_cents"] == 500_000_000


class TestAllotmentApprovalSeparationOfDuties:
    @staticmethod
    def _allotment_prepared_by_a_director(api):
        ctx = fixtures.setup_execution_cycle()
        allotment = fixtures.open_allotment(
            ctx["appropriation"]["id"], quarter=1, requested_cents=440_000_000
        )
        ctx["allotment"] = validate_success(
            api.prepare_allotment(allotment["id"], make_director_headers("dir-1")), 200
        )
        return ctx

    def test_the_preparer_cannot_approve_its_own_row_but_a_second_director_can(
        self, api, budget_director_headers, second_director_headers
    ):
        """PRD §2.9: "The check is on the identifier alone: holding a role that is authorised to approve does not exempt an official from it, which is precisely the case that arises when a `BudgetDirector` both prepares an allotment and later tries to approve it."
        PRD §3.5: "A `BudgetDirector` then approves, moving the allotment `PREPARED → APPROVED`. Approval requires the row to be in `PREPARED`, the acting `X-User-ID` to differ from `prepared_by_user_id`, and the owning appropriation's `cash_status` not to be `FROZEN`."
        PRD §3.5: "It writes `approved_by_user_id` and increments `version` by 1."
        PRD §2.12: "The acting `X-User-ID` differs from the identifier that prepared or proposed the row — otherwise `ERR_SEGREGATION_OF_DUTIES` (403). Applies to three operations: `POST /fiscal/allotments/{id}/approve`, `POST /fiscal/executive-recommendations/{id}/approve`, and `POST /fiscal/budget-transfers/{id}/approve`."

        Design: Corner/validations/allotment_approve_by_its_own_preparer_is_rejected
        """
        ctx = self._allotment_prepared_by_a_director(api)
        allotment_id = ctx["allotment"]["id"]
        assert ctx["allotment"]["prepared_by_user_id"] == "dir-1"

        validate_error(
            api.approve_allotment(allotment_id, budget_director_headers),
            ApiErrorId.ERR_SEGREGATION_OF_DUTIES,
            403,
        )
        refused = fixtures.read_allotment(allotment_id)
        assert refused["status"] == "PREPARED"
        assert refused["approved_by_user_id"] is None

        approved = validate_success(
            api.approve_allotment(allotment_id, second_director_headers), 200
        )
        assert approved["status"] == "APPROVED"
        assert approved["approved_by_user_id"] == "dir-2"
        assert approved["prepared_by_user_id"] == "dir-1"
        assert approved["released_cents"] == 0


class TestAllotmentPrepareSatisfaction:
    def test_every_guard_satisfied_locks_the_ceiling_without_releasing_cash(
        self, api, budget_analyst_headers
    ):
        """PRD §3.5: "It moves the allotment `DRAFT → PREPARED` and requires: the row to be in `DRAFT`; the owning appropriation's `authority_status` to be `ENACTED`, otherwise `ERR_APPROPRIATION_NOT_ENACTED`; that appropriation's `cash_status` not to be `FROZEN`, otherwise `ERR_CASH_FROZEN`; its `release_hold` to be false, otherwise `ERR_RELEASE_HOLD_ACTIVE`; and the owning cycle to be in `EXECUTION`."
        PRD §3.5: "A new allotment starts in `DRAFT` with `computed_release_cents` at 0, `binding_constraint` null, `released_cents` at 0, and `prepared_by_user_id`, `approved_by_user_id`, and `recall_reason` all null."
        PRD §3.5: "`binding_constraint` records which limit bound, and ties are broken by a fixed precedence rather than by discovery order: scan the labels `REQUEST`, `QUARTER_CAP`, `UNRELEASED_AUTHORITY`, `CASH_FLOW` in that order and record the first whose limit equals the ceiling."
        PRD §3.5: "On success the ceiling is written to `computed_release_cents`, the winning label to `binding_constraint`, the acting identifier to `prepared_by_user_id`, the status becomes `PREPARED`, and `version` increments by 1."

        Design: Corner/validations/allotment_prepare_succeeds_when_every_guard_is_satisfied
        """
        ctx = fixtures.setup_execution_cycle()
        appropriation_id = ctx["appropriation"]["id"]
        assert ctx["appropriation"]["cash_status"] == "UNRELEASED"
        assert ctx["appropriation"]["release_hold"] is False

        created = validate_success(
            api.create_allotment(
                {
                    "appropriation_id": appropriation_id,
                    "quarter": 1,
                    "requested_cents": 440_000_000,
                    "allow_partial": False,
                },
                budget_analyst_headers,
            ),
            201,
        )
        assert created["status"] == "DRAFT"
        assert created["computed_release_cents"] == 0
        assert created["binding_constraint"] is None

        prepared = validate_success(
            api.prepare_allotment(created["id"], budget_analyst_headers), 200
        )
        assert prepared["status"] == "PREPARED"
        assert prepared["computed_release_cents"] == 440_000_000
        assert prepared["binding_constraint"] == "REQUEST"
        assert prepared["prepared_by_user_id"] == "analyst-1"
        assert prepared["released_cents"] == 0

        assert fixtures.read_appropriation(appropriation_id)["released_cents"] == 0


class TestAllowPartialFlag:
    def test_the_flag_decides_between_a_refusal_and_a_truncated_fill(
        self, api, budget_analyst_headers
    ):
        """PRD §3.5: "If the ceiling is below `requested_cents` while `allow_partial` is false, preparation is rejected with `ERR_ALLOTMENT_EXCEEDS_CEILING`; with `allow_partial` true the smaller amount is accepted and recorded."
        PRD §2.12: "When `allow_partial` is false, the ceiling is at least `requested_cents` — otherwise `ERR_ALLOTMENT_EXCEEDS_CEILING` (422). Applies to `POST /fiscal/allotments/{id}/prepare`. A zero ceiling therefore reports `ERR_NO_RELEASE_CAPACITY`, never `ERR_ALLOTMENT_EXCEEDS_CEILING`, regardless of `allow_partial`."
        PRD §3.5: "The second is the **quarter cap**: the appropriation's current authority multiplied by the share of that authority the fund type permits in that quarter, rounded half up to the cent."
        PRD §3.5: "A `GENERAL`-fund line may release 22 percent of its authority in quarter 1 and 26 percent in each of quarters 2, 3, and 4."
        PRD §3.5: "Cancelling from `DRAFT` moves the row `DRAFT → CANCELLED`, is permitted while the row is in `DRAFT` or `PREPARED`, sets the status to `CANCELLED`, frees the appropriation-and-quarter slot, and increments `version` by 1."

        Design: Corner/validations/allow_partial_true_accepts_a_ceiling_below_the_request
        """
        ctx = fixtures.setup_execution_cycle()
        appropriation_id = ctx["appropriation"]["id"]

        def request(allow_partial):
            return {
                "appropriation_id": appropriation_id,
                "quarter": 1,
                "requested_cents": 600_000_000,
                "allow_partial": allow_partial,
            }

        strict = validate_success(
            api.create_allotment(request(False), budget_analyst_headers), 201
        )
        validate_error(
            api.prepare_allotment(strict["id"], budget_analyst_headers),
            ApiErrorId.ERR_ALLOTMENT_EXCEEDS_CEILING,
            422,
        )
        refused = fixtures.read_allotment(strict["id"])
        assert refused["status"] == "DRAFT"
        assert refused["computed_release_cents"] == 0

        cancelled = validate_success(
            api.cancel_allotment(strict["id"], budget_analyst_headers), 200
        )
        assert cancelled["status"] == "CANCELLED"

        permissive = validate_success(
            api.create_allotment(request(True), budget_analyst_headers), 201
        )
        prepared = validate_success(
            api.prepare_allotment(permissive["id"], budget_analyst_headers), 200
        )
        assert prepared["status"] == "PREPARED"
        assert prepared["computed_release_cents"] == 440_000_000
        assert prepared["binding_constraint"] == "QUARTER_CAP"
        assert prepared["requested_cents"] == 600_000_000


class TestCertificationAgainstCascadedRevenue:
    @staticmethod
    def _prep_cycle_with_nine_billion_approved():
        ctx = fixtures.setup_development_cycle(adopt_revenue=True)
        cycle_id = ctx["cycle"]["id"]
        request, _packages = fixtures.setup_accepted_request(
            cycle_id, ctx["agency"]["id"], base_budget_cents=9_000_000_000
        )
        fixtures.advance_phase(cycle_id, "EXECUTIVE_PREP")
        recommendation = fixtures.prepare_recommendation(
            request["id"],
            recommended_base_cents=9_000_000_000,
            recommended_package_ids=[],
            policy_priority="HEALTH",
        )
        fixtures.approve_recommendation(recommendation["id"])
        ctx["request"] = request
        return ctx

    def test_the_same_certify_call_passes_then_fails_after_revenue_is_superseded_downward(
        self, api, budget_director_headers
    ):
        """PRD §3.3: "The cycle's `total_recommended_cents` is the sum of `recommended_amount_cents` over every recommendation in status `APPROVED` whose request belongs to that cycle; `PREPARED` and `SUPERSEDED` rows are excluded."
        PRD §3.3: "The appropriable amount is the adopted revenue minus that already-rounded reserve. The budget balances when `total_recommended_cents` is less than or equal to the appropriable amount; exact equality balances."
        PRD §3.1: "On success the adopted row becomes `ADOPTED`; the row named by `supersedes_forecast_id`, if any, moves `ADOPTED → SUPERSEDED` and its amount stops counting toward the cycle total; and the cycle recomputes `adopted_general_fund_revenue_cents`, `required_reserve_cents`, `projected_cumulative_cash_cents`, `cash_utilization_pct`, and `cash_posture`, incrementing its `version` by 1."
        PRD §2.12: "Approved recommendations do not exceed adopted revenue net of the constitutional reserve, and `balance_certified` is true when `LEGISLATIVE` is requested — otherwise `ERR_BUDGET_NOT_BALANCED` (422)."
        PRD §3.1: "`SUPERSEDED` is terminal for a forecast."

        Design: Corner/validations/certify_balance_flips_after_a_superseding_forecast_lowers_revenue
        """
        ctx = self._prep_cycle_with_nine_billion_approved()
        cycle_id = ctx["cycle"]["id"]

        certified = validate_success(
            api.certify_cycle_balance(cycle_id, budget_director_headers), 200
        )
        assert certified["balance_certified"] is True
        assert certified["required_reserve_cents"] == 500_000_000
        assert certified["total_recommended_cents"] == 9_000_000_000

        replacement = fixtures.record_forecast(
            cycle_id,
            source_code="SALES_TAX",
            fund_type="GENERAL",
            amount_cents=5_000_000_000,
        )
        adopted = validate_success(
            api.adopt_revenue_forecast(
                replacement["id"],
                budget_director_headers,
                {"supersedes_forecast_id": ctx["forecast"]["id"]},
            ),
            200,
        )
        assert adopted["status"] == "ADOPTED"

        lowered = fixtures.read_budget_cycle(cycle_id)
        assert lowered["adopted_general_fund_revenue_cents"] == 5_000_000_000
        assert lowered["required_reserve_cents"] == 250_000_000

        validate_error(
            api.certify_cycle_balance(cycle_id, budget_director_headers),
            ApiErrorId.ERR_BUDGET_NOT_BALANCED,
            422,
        )
        assert fixtures.read_budget_cycle(cycle_id)["balance_certified"] is True


class TestFourQuarterDrainThenTransfer:
    QUARTER_CLOCKS = {
        2: "2026-11-01T00:00:00Z",
        3: "2027-02-01T00:00:00Z",
        4: "2027-05-01T00:00:00Z",
    }
    QUARTER_CAPS = {1: 220_000_000, 2: 260_000_000, 3: 260_000_000, 4: 260_000_000}

    @staticmethod
    def _drained_source_and_untouched_target():
        ctx = fixtures.setup_execution_cycle(
            appropriations=(
                {
                    "fund_type": "GENERAL",
                    "program_code": "P100",
                    "introduced_amount_cents": 1_000_000_000,
                },
                {
                    "fund_type": "GENERAL",
                    "program_code": "P200",
                    "introduced_amount_cents": 1_000_000_000,
                },
            )
        )
        source_id = ctx["appropriations"]["P100"]["id"]
        released = {}
        for quarter in (1, 2, 3, 4):
            if quarter in TestFourQuarterDrainThenTransfer.QUARTER_CLOCKS:
                fixtures.set_clock(TestFourQuarterDrainThenTransfer.QUARTER_CLOCKS[quarter])
            cap = TestFourQuarterDrainThenTransfer.QUARTER_CAPS[quarter]
            allotment = fixtures.released_allotment(
                source_id, quarter=quarter, requested_cents=cap
            )
            released[quarter] = allotment["released_cents"]
            fixtures.post_expenditure(
                source_id,
                ctx["agency"]["id"],
                quarter=quarter,
                amount_cents=cap,
                object_code="5100",
                vendor_reference=f"INV-Q{quarter}",
            )
        ctx["source_id"] = source_id
        ctx["target_id"] = ctx["appropriations"]["P200"]["id"]
        ctx["released"] = released
        return ctx

    def test_the_drained_line_refuses_a_one_cent_transfer_on_availability_not_on_the_cap(
        self, api, budget_analyst_headers, state_controller_headers
    ):
        """PRD §3.5: "A `GENERAL`-fund line may release 22 percent of its authority in quarter 1 and 26 percent in each of quarters 2, 3, and 4."
        PRD §3.5: "a release that brings `released_cents` exactly equal to current authority moves it `UNRELEASED → FULLY_RELEASED` in one step; and a release from a partly released row that reaches current authority exactly moves it `PARTIALLY_RELEASED → FULLY_RELEASED`."
        PRD §3.7: "A read-only balance summary exposes both side by side, reporting `appropriation_id`, `authority_cents` (the current authority figure), `released_cents`, `expended_cents`, `available_cash_cents`, `available_authority_cents`, and `basis_delta_cents`, the last being `available_authority_cents` minus `available_cash_cents`."
        PRD §3.6: "The amount must also fit inside the source's `available_authority_cents`, otherwise `ERR_TRANSFER_EXCEEDS_AVAILABLE`; that same available-authority test is re-applied at approval, at execution, and — against the *target* row — at reversal, because the figure moves underneath a proposal that sits in the queue."
        PRD §2.12: "The transfer amount fits within available authority on the authority basis — otherwise `ERR_TRANSFER_EXCEEDS_AVAILABLE` (422)."

        Design: Corner/validations/four_quarter_release_chain_reaches_fully_released_then_transfer_exceeds_available
        """
        ctx = self._drained_source_and_untouched_target()
        source_id = ctx["source_id"]

        assert ctx["released"] == {
            1: 220_000_000,
            2: 260_000_000,
            3: 260_000_000,
            4: 260_000_000,
        }
        assert sum(ctx["released"].values()) == 1_000_000_000

        source = fixtures.read_appropriation(source_id)
        assert source["released_cents"] == 1_000_000_000
        assert source["expended_cents"] == 1_000_000_000
        assert source["cash_status"] == "FULLY_RELEASED"
        assert source["authority_status"] == "ENACTED"

        summary = validate_success(
            api.get_appropriation_balance_summary(source_id, state_controller_headers), 200
        )
        assert summary["authority_cents"] == 1_000_000_000
        assert summary["released_cents"] == 1_000_000_000
        assert summary["expended_cents"] == 1_000_000_000
        assert summary["available_cash_cents"] == 0
        assert summary["available_authority_cents"] == 0
        assert summary["basis_delta_cents"] == 0

        validate_error(
            api.create_budget_transfer(
                {
                    "source_appropriation_id": source_id,
                    "target_appropriation_id": ctx["target_id"],
                    "amount_cents": 1,
                    "transfer_type": "INTRA_AGENCY",
                    "justification": "one cent from a drained line",
                    "expected_source_appropriation_version": fixtures.appropriation_version(
                        source_id
                    ),
                },
                budget_analyst_headers,
            ),
            ApiErrorId.ERR_TRANSFER_EXCEEDS_AVAILABLE,
            422,
        )

        cycle = fixtures.read_budget_cycle(ctx["cycle"]["id"])
        assert cycle["total_released_cents"] == 1_000_000_000
        assert cycle["cash_utilization_pct"] == 0.1
        assert cycle["cash_posture"] == "NORMAL"
        assert fixtures.read_appropriation(ctx["target_id"])["transfers_in_cents"] == 0
