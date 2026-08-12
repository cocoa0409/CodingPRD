"""Recognition: delivery acceptance, over-time progress, cost entries (PRD §3.6)."""
import pytest

from test_helpers import (
    ApiErrorId, validate_success, validate_error, validate_paginated,
    create_customer, create_contract, create_ssp, add_pob, get_pob, get_contract,
    set_clock, create_period,
    setup_active_contract_with_pob, setup_active_contract_with_pobs,
)

CLOCK = "2026-06-15T00:00:00Z"


class TestPatternGuard:
    def _setup_two_pattern_contract(self, api):
        return setup_active_contract_with_pobs(
            [
                {"product_code": "ICA", "ssp_cents": 100000,
                 "pob": {"pob_ref": "PIC", "recognition_pattern": "OVER_TIME_INPUT_COST",
                         "estimated_total_cost_cents": 40000}},
                {"product_code": "PITA", "ssp_cents": 100000,
                 "pob": {"pob_ref": "PPIT", "recognition_pattern": "POINT_IN_TIME"}},
            ],
            fixed=200000,
        )

    def test_satisfy_on_over_time_pob_forbidden(self, api, accountant_headers):
        """PRD §3.6: "The pattern guard is symmetric: delivery acceptance
        applies only to `POINT_IN_TIME` obligations, while the recognize run and
        cost entries apply only to the two over-time patterns, and any mismatch
        is rejected with `ERR_RECOGNITION_PATTERN_FORBIDDEN` (HTTP 422)."

        Design: Corner/validations/satisfy_and_recognize_pattern_mismatch_return_pattern_forbidden
        """
        setup = self._setup_two_pattern_contract(api)
        pob_ic = setup["pobs"][0]
        resp = api.satisfy_pob(pob_ic["id"], accountant_headers)
        validate_error(resp, ApiErrorId.ERR_RECOGNITION_PATTERN_FORBIDDEN, 422)

    def test_recognize_on_point_in_time_pob_forbidden(self, api, accountant_headers):
        """PRD §3.6: "The pattern guard is symmetric: delivery acceptance
        applies only to `POINT_IN_TIME` obligations, while the recognize run and
        cost entries apply only to the two over-time patterns, and any mismatch
        is rejected with `ERR_RECOGNITION_PATTERN_FORBIDDEN` (HTTP 422)."

        Design: Corner/validations/satisfy_and_recognize_pattern_mismatch_return_pattern_forbidden
        """
        setup = self._setup_two_pattern_contract(api)
        pob_pit = setup["pobs"][1]
        resp = api.recognize_pob(pob_pit["id"], accountant_headers)
        validate_error(resp, ApiErrorId.ERR_RECOGNITION_PATTERN_FORBIDDEN, 422)

    def test_pobs_unchanged_after_pattern_violations(self, api, accountant_headers):
        """PRD §3.6: "The pattern guard is symmetric: delivery acceptance
        applies only to `POINT_IN_TIME` obligations, while the recognize run and
        cost entries apply only to the two over-time patterns, and any mismatch
        is rejected with `ERR_RECOGNITION_PATTERN_FORBIDDEN` (HTTP 422)."

        Design: Corner/validations/satisfy_and_recognize_pattern_mismatch_return_pattern_forbidden
        """
        setup = self._setup_two_pattern_contract(api)
        pob_ic, pob_pit = setup["pobs"]
        validate_error(api.satisfy_pob(pob_ic["id"], accountant_headers),
                       ApiErrorId.ERR_RECOGNITION_PATTERN_FORBIDDEN, 422)
        validate_error(api.recognize_pob(pob_pit["id"], accountant_headers),
                       ApiErrorId.ERR_RECOGNITION_PATTERN_FORBIDDEN, 422)
        for pob in (pob_ic, pob_pit):
            after = get_pob(pob["id"])
            assert after["status"] == "PENDING"
            assert after["recognized_revenue_cents"] == 0


class TestDualVariantProgress:
    def _setup(self, api):
        set_clock(CLOCK)
        period = create_period()
        create_ssp("WIDGET", region="US", ssp_cents=100000)
        create_ssp("SVC", region="US", ssp_cents=100000)
        customer = create_customer(legal_name="Beta LLC", external_ref="BETA-1")
        from test_helpers.fixtures import walk_contract_to_active
        c_a = create_contract(customer["id"], contract_ref="C-IC")
        pob_a = add_pob(c_a["id"], pob_ref="P1", product_code="WIDGET",
                        recognition_pattern="OVER_TIME_INPUT_COST",
                        estimated_total_cost_cents=80000)
        walk_contract_to_active(c_a["id"])
        c_b = create_contract(customer["id"], contract_ref="C-SL")
        pob_b = add_pob(c_b["id"], pob_ref="P1", product_code="SVC",
                        recognition_pattern="OVER_TIME_STRAIGHT_LINE",
                        service_start_date="2026-06-01", service_end_date="2026-07-01")
        walk_contract_to_active(c_b["id"])
        return period, c_a, pob_a, c_b, pob_b

    def test_input_cost_progress(self, api, accountant_headers):
        """PRD §3.6: "For `OVER_TIME_INPUT_COST`, the ratio is
        `costs_incurred_to_date_cents` divided by `estimated_total_cost_cents`."
        and "The recognition target is the obligation's `allocated_amount_cents`
        multiplied by the unrounded ratio, rounded half up to whole cents".

        Design: Difficulty/dual_variant_calc/progress_input_cost_vs_straight_line
        """
        _, _, pob_a, _, _ = self._setup(api)
        validate_success(api.create_cost_entry(
            pob_a["id"], {"amount_cents": 20000, "incurred_date": "2026-06-10"},
            accountant_headers,
        ), 201)
        pob = get_pob(pob_a["id"])
        assert pob["allocated_amount_cents"] == 100000
        # ratio = 20000/80000 = 0.25 -> target 25000.
        assert pob["recognized_revenue_cents"] == 25000

    def test_straight_line_progress(self, api, accountant_headers):
        """PRD §3.6: "For `OVER_TIME_STRAIGHT_LINE`, the total service length is
        the number of whole days between `service_start_date` and
        `service_end_date`; the elapsed length is the number of whole days
        between `service_start_date` and the earlier of the current logical
        clock date and `service_end_date`, clamped so it is never less than
        zero; and the ratio is the elapsed length divided by the total length."

        Design: Difficulty/dual_variant_calc/progress_input_cost_vs_straight_line
        """
        _, _, _, _, pob_b = self._setup(api)
        validate_success(api.recognize_pob(pob_b["id"], accountant_headers))
        pob = get_pob(pob_b["id"])
        assert pob["allocated_amount_cents"] == 100000
        # ratio = 14/30 -> round_half_up(100000*14/30) = 46667.
        assert pob["recognized_revenue_cents"] == 46667

    def test_identical_allocated_amounts_diverge_by_pattern(self, api, accountant_headers):
        """PRD §3.6: "Over-time recognition is driven by a progress ratio that
        is never rounded before use and never allowed to exceed one. For
        `OVER_TIME_INPUT_COST`, the ratio is `costs_incurred_to_date_cents`
        divided by `estimated_total_cost_cents`."

        Design: Difficulty/dual_variant_calc/progress_input_cost_vs_straight_line
        """
        _, _, pob_a, _, pob_b = self._setup(api)
        validate_success(api.create_cost_entry(
            pob_a["id"], {"amount_cents": 20000, "incurred_date": "2026-06-10"},
            accountant_headers,
        ), 201)
        validate_success(api.recognize_pob(pob_b["id"], accountant_headers))
        rec_a = get_pob(pob_a["id"])["recognized_revenue_cents"]
        rec_b = get_pob(pob_b["id"])["recognized_revenue_cents"]
        assert rec_a == 25000
        assert rec_b == 46667
        assert rec_a != rec_b, (
            "identical allocated amounts must diverge by recognition pattern"
        )


class TestAutoInProgress:
    def test_first_cost_entry_moves_pob_in_progress(self, api, accountant_headers):
        """PRD §3.6: "The first `RECOGNITION` or `CATCH_UP_ADJUSTMENT` entry
        posted for an obligation moves it from `PENDING` to `IN_PROGRESS`
        automatically."

        Design: Corner/state_machines/pob_auto_in_progress_on_first_cost_entry
        """
        setup = setup_active_contract_with_pob(
            pob_overrides={"recognition_pattern": "OVER_TIME_INPUT_COST",
                           "estimated_total_cost_cents": 40000},
        )
        pob = setup["pob"]
        assert pob["status"] == "PENDING"
        validate_success(api.create_cost_entry(
            pob["id"], {"amount_cents": 10000, "incurred_date": "2026-06-10"},
            accountant_headers,
        ), 201)
        after = get_pob(pob["id"])
        assert after["status"] == "IN_PROGRESS"

    def test_cost_entry_accumulates_and_recognizes(self, api, accountant_headers):
        """PRD §3.6: "The cost is added to `costs_incurred_to_date_cents`, the
        input-cost ratio is recomputed, and when the recognition target
        advanced, one `RECOGNITION` entry with origin `COST_ENTRY` posts for the
        difference".

        Design: Corner/state_machines/pob_auto_in_progress_on_first_cost_entry
        """
        setup = setup_active_contract_with_pob(
            pob_overrides={"recognition_pattern": "OVER_TIME_INPUT_COST",
                           "estimated_total_cost_cents": 40000},
        )
        pob = setup["pob"]
        validate_success(api.create_cost_entry(
            pob["id"], {"amount_cents": 10000, "incurred_date": "2026-06-10"},
            accountant_headers,
        ), 201)
        after = get_pob(pob["id"])
        assert after["costs_incurred_to_date_cents"] == 10000
        # ratio 0.25 over allocated 100000 -> 25000.
        assert after["recognized_revenue_cents"] == 25000


class TestProgressRatioBoundary:
    def _setup(self, api):
        return setup_active_contract_with_pob(
            pob_overrides={"recognition_pattern": "OVER_TIME_INPUT_COST",
                           "estimated_total_cost_cents": 40000},
        )

    def test_one_cent_below_estimate_stays_in_progress(self, api, accountant_headers):
        """PRD §3.6: "When the ratio reaches exactly one — costs equal to the
        estimate, or the clock date on or after the service end date — the
        obligation flips to `SATISFIED`, `satisfied_at` is stamped, and
        auto-completion is re-evaluated; a cost total a single cent below the
        estimate does not satisfy the obligation."

        Design: Difficulty/boundary_precision_check/boundary_progress_ratio_exactly_one
        """
        pob = self._setup(api)["pob"]
        validate_success(api.create_cost_entry(
            pob["id"], {"amount_cents": 39999, "incurred_date": "2026-06-10"},
            accountant_headers,
        ), 201)
        after = get_pob(pob["id"])
        assert after["status"] == "IN_PROGRESS"
        # round_half_up(100000 * 39999/40000) == 99998.
        assert after["recognized_revenue_cents"] == 99998

    def test_exactly_one_flips_to_satisfied(self, api, accountant_headers):
        """PRD §3.6: "When the ratio reaches exactly one — costs equal to the
        estimate, or the clock date on or after the service end date — the
        obligation flips to `SATISFIED`, `satisfied_at` is stamped, and
        auto-completion is re-evaluated".

        Design: Difficulty/boundary_precision_check/boundary_progress_ratio_exactly_one
        """
        pob = self._setup(api)["pob"]
        validate_success(api.create_cost_entry(
            pob["id"], {"amount_cents": 40000, "incurred_date": "2026-06-10"},
            accountant_headers,
        ), 201)
        after = get_pob(pob["id"])
        assert after["status"] == "SATISFIED"
        assert after["recognized_revenue_cents"] == 100000
        assert after["satisfied_at"] is not None

    def test_final_cent_crossing_flips_to_satisfied(self, api, accountant_headers):
        """PRD §3.6: "a cost total a single cent below the estimate does not
        satisfy the obligation" while "the ratio reaches exactly one — costs
        equal to the estimate" flips the obligation to `SATISFIED`.

        Design: Difficulty/boundary_precision_check/boundary_progress_ratio_exactly_one
        """
        pob = self._setup(api)["pob"]
        validate_success(api.create_cost_entry(
            pob["id"], {"amount_cents": 39999, "incurred_date": "2026-06-10"},
            accountant_headers,
        ), 201)
        validate_success(api.create_cost_entry(
            pob["id"], {"amount_cents": 1, "incurred_date": "2026-06-11"},
            accountant_headers,
        ), 201)
        after = get_pob(pob["id"])
        assert after["status"] == "SATISFIED"
        assert after["recognized_revenue_cents"] == 100000


class TestRecognizeIdempotence:
    def _setup_straight_line(self, api):
        return setup_active_contract_with_pob(
            product_code="SVC",
            pob_overrides={"recognition_pattern": "OVER_TIME_STRAIGHT_LINE",
                           "service_start_date": "2026-06-01",
                           "service_end_date": "2026-07-01"},
        )

    def test_second_recognize_run_posts_no_new_entry(self, api, accountant_headers):
        """PRD §3.6: "The recognize run synchronizes one over-time obligation
        against the logical clock: it computes the target, and when the target
        exceeds `recognized_revenue_cents` it posts one `RECOGNITION` entry with
        origin `RECOGNIZE` for the difference into the period containing the
        clock date; when the difference is zero the run is a no-op."

        Design: Corner/calculations/recognize_second_run_no_new_entry
        """
        setup = self._setup_straight_line(api)
        pob = setup["pob"]
        validate_success(api.recognize_pob(pob["id"], accountant_headers))
        second = validate_success(api.recognize_pob(pob["id"], accountant_headers))
        assert second["recognized_revenue_cents"] == 46667
        entries = validate_paginated(
            api.list_revenue_entries(accountant_headers, params={"pob_id": pob["id"]})
        )[0]
        assert len(entries) == 1
        assert entries[0]["amount_cents"] == 46667
        assert entries[0]["entry_type"] == "RECOGNITION"
        assert entries[0]["origin"] == "RECOGNIZE"

    def test_recognize_response_reflects_write_immediately(self, api, accountant_headers):
        """PRD §3.6: "when the target exceeds `recognized_revenue_cents` it
        posts one `RECOGNITION` entry with origin `RECOGNIZE` for the difference
        into the period containing the clock date".
        PRD §1 (introduction): "every recognition, billing, void, reversal,
        modification, and re-estimation re-runs that reconciliation atomically
        within the request."

        Design: Corner/calculations/recognize_second_run_no_new_entry
        """
        setup = self._setup_straight_line(api)
        pob = setup["pob"]
        first = validate_success(api.recognize_pob(pob["id"], accountant_headers))
        assert first["recognized_revenue_cents"] == 46667
        contract = get_contract(setup["contract"]["id"])
        assert contract["recognized_to_date_cents"] == 46667
