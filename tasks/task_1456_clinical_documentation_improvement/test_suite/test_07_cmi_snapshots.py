"""CMI snapshot computation: dual variants, rounding order, input-set filtering."""
import pytest

from test_helpers import (
    advance_clock,
    assert_cmi_snapshot,
    close_review,
    create_case,
    create_program,
    create_provider,
    finalize_case,
    validate_success,
)


class TestUnadjustedVsAdjusted:
    def test_unadjusted_and_adjusted_diverge(self, api, cdi_manager_headers):
        """PRD §3.9: "The snapshot reports `case_count` as the number of included
        cases; `unadjusted_cmi` as the mean of `initial_drg_weight` across
        included cases — the coder's first-pass DRG before any CDI query — rounded
        half-up to 4 decimal places; and `adjusted_cmi` as the mean of
        `working_drg_weight` across the same cases, likewise rounded to 4 decimal
        places. The `cdi_lift` is the difference between the two rounded means"

        Design: Difficulty/dual_variant_calc/cmi_snapshot_unadjusted_vs_adjusted_diverge
        """
        from test_helpers import (
            create_and_activate_review,
            create_policy,
            create_query,
            respond_to_query,
            send_query,
        )
        program = create_program()
        policy = create_policy(
            program["id"], response_due_periods=2, escalation_stage_periods=2,
            max_escalation_stage=1,
        )
        provider = create_provider(program["id"])
        # Case A: no CDI change, initial == working == 1.0, FINAL_CODED.
        case_a = create_case(
            program["id"], provider["id"],
            admission_period=0, discharge_period=3,
            initial_drg_code="DRG-X", initial_drg_weight=1.0,
        )
        advance_clock(program["id"], 5)
        finalize_case(case_a["id"])
        # Case B: CDI AGREE moves working to 2.0, then FINAL_CODED as DRG-Y/2.0.
        case_b = create_case(
            program["id"], provider["id"],
            admission_period=0, discharge_period=3,
            initial_drg_code="DRG-X", initial_drg_weight=1.0,
        )
        review_b = create_and_activate_review(case_b["id"])
        q = create_query(
            review_b["id"], provider["id"], policy["id"],
            query_text="Please clarify the documented acuity level.",
            clinical_indicators=["WBC"],
            proposed_drg_code="DRG-Y", proposed_drg_weight=2.0,
            proposed_soi=3, proposed_rom=2,
        )
        q = send_query(q["id"], q["version"])
        respond_to_query(q["id"], provider["id"], response_type="AGREE")
        close_review(review_b["id"])
        finalize_case(case_b["id"], coder_drg_code="DRG-Y", coder_drg_weight=2.0)
        snap = validate_success(
            api.create_cmi_snapshot(program["id"], cdi_manager_headers), expected_status=201
        )
        assert_cmi_snapshot(snap)
        assert snap["case_count"] == 2
        assert snap["unadjusted_cmi"] == pytest.approx(1.0, abs=1e-4)
        assert snap["adjusted_cmi"] == pytest.approx(1.5, abs=1e-4)
        assert snap["cdi_lift"] == pytest.approx(0.5, abs=1e-4)
        assert snap["adjusted_cmi"] != snap["unadjusted_cmi"]

    def test_unadjusted_equals_adjusted_without_cdi_change(self, api, cdi_manager_headers):
        """PRD §3.9: "The `cdi_lift` is the difference between the two rounded
        means, itself expressed to 4 decimal places: each ratio is rounded first,
        and only then is the subtraction performed."

        Design: Difficulty/dual_variant_calc/cmi_snapshot_unadjusted_vs_adjusted_diverge
        """
        program = create_program()
        provider = create_provider(program["id"])
        case = create_case(
            program["id"], provider["id"],
            admission_period=0, discharge_period=3,
            initial_drg_code="DRG-X", initial_drg_weight=2.0,
        )
        advance_clock(program["id"], 5)
        finalize_case(case["id"])
        snap = validate_success(
            api.create_cmi_snapshot(program["id"], cdi_manager_headers), expected_status=201
        )
        assert snap["case_count"] == 1
        assert snap["unadjusted_cmi"] == pytest.approx(2.0, abs=1e-4)
        assert snap["adjusted_cmi"] == pytest.approx(2.0, abs=1e-4)
        assert snap["cdi_lift"] == pytest.approx(0.0, abs=1e-4)


class TestRoundingOrder:
    def test_ratios_rounded_before_subtraction(self, api, cdi_manager_headers):
        """PRD §2.7: "When a computed value combines a ratio and a difference — as
        in the case mix index lift — the ratios are rounded to 4 decimal places
        first, and only then is the subtraction performed."
        PRD §3.9: "The `cdi_lift` is the difference between the two rounded means,
        itself expressed to 4 decimal places: each ratio is rounded first, and
        only then is the subtraction performed."

        Design: Difficulty/combinatorial_formula/cmi_snapshot_round_per_ratio_then_subtract
        """
        program = create_program(baseline_cmi=0.5)
        provider = create_provider(program["id"])
        cases = [
            create_case(
                program["id"], provider["id"],
                admission_period=0, discharge_period=1,
                initial_drg_code="A", initial_drg_weight=0.3333,
            )
            for _ in range(3)
        ]
        advance_clock(program["id"], 5)
        for c in cases:
            finalize_case(c["id"])
        snap = validate_success(
            api.create_cmi_snapshot(program["id"], cdi_manager_headers), expected_status=201
        )
        assert snap["case_count"] == 3
        # mean = 0.9999/3 = 0.3333 (exact at 4dp); both means identical -> lift 0
        assert snap["unadjusted_cmi"] == pytest.approx(0.3333, abs=1e-4)
        assert snap["adjusted_cmi"] == pytest.approx(0.3333, abs=1e-4)
        assert snap["cdi_lift"] == pytest.approx(0.0, abs=1e-4)

    def test_rounding_applied_per_mean(self, api, cdi_manager_headers):
        """PRD §2.7: "All DRG weights, CMI values, priority scores, and
        opportunity deltas in the system are decimal numbers carried to exactly 4
        decimal places, rounded half-up."

        Design: Difficulty/combinatorial_formula/cmi_snapshot_round_per_ratio_then_subtract
        """
        program = create_program()
        provider = create_provider(program["id"])
        # weights 1.0, 1.0, 1.00005 -> true mean 1.0000166..., rounds to 1.0000
        cases = [
            create_case(
                program["id"], provider["id"],
                admission_period=0, discharge_period=1,
                initial_drg_code="A", initial_drg_weight=w,
            )
            for w in (1.0, 1.0, 1.0001)
        ]
        advance_clock(program["id"], 5)
        for c in cases:
            finalize_case(c["id"])
        snap = validate_success(
            api.create_cmi_snapshot(program["id"], cdi_manager_headers), expected_status=201
        )
        assert snap["case_count"] == 3
        # (1.0 + 1.0 + 1.0001) / 3 = 1.00003333... -> round half-up 4dp = 1.0000
        assert snap["unadjusted_cmi"] == pytest.approx(1.0, abs=1e-4)


class TestInputSetFiltering:
    def test_empty_case_set_returns_zero_counts(self, api, cdi_manager_headers):
        """PRD §3.9: "If no cases qualify, all four numeric fields report 0.0000
        and no division occurs."

        Design: Corner/calculations/cmi_snapshot_empty_case_set_returns_zero_counts
        """
        program = create_program()
        snap = validate_success(
            api.create_cmi_snapshot(program["id"], cdi_manager_headers), expected_status=201
        )
        assert_cmi_snapshot(snap)
        assert snap["case_count"] == 0
        assert snap["unadjusted_cmi"] == pytest.approx(0.0, abs=1e-9)
        assert snap["adjusted_cmi"] == pytest.approx(0.0, abs=1e-9)
        assert snap["cdi_lift"] == pytest.approx(0.0, abs=1e-9)
        assert snap["denial_target_misses"] == 0

    def test_open_cases_excluded(self, api, cdi_manager_headers):
        """PRD §3.9: "A snapshot stamps `as_of_period` with the program's current
        period and includes every case in the program whose status is
        `RECONCILED`, `FINAL_CODED`, or `CLOSED` and whose `discharge_period` is
        no later than the `as_of_period`."

        Design: Corner/calculations/cmi_snapshot_excludes_open_cases
        """
        program = create_program()
        provider = create_provider(program["id"])
        # OPEN case (never finalized) with a loud weight that must be excluded.
        create_case(
            program["id"], provider["id"], mrn="M-open",
            admission_period=0, discharge_period=3,
            initial_drg_code="A", initial_drg_weight=5.0,
        )
        cfin = create_case(
            program["id"], provider["id"], mrn="M-fin",
            admission_period=0, discharge_period=3,
            initial_drg_code="A", initial_drg_weight=2.0,
        )
        advance_clock(program["id"], 5)
        finalize_case(cfin["id"])
        snap = validate_success(
            api.create_cmi_snapshot(program["id"], cdi_manager_headers), expected_status=201
        )
        assert snap["case_count"] == 1
        assert snap["unadjusted_cmi"] == pytest.approx(2.0, abs=1e-4)
