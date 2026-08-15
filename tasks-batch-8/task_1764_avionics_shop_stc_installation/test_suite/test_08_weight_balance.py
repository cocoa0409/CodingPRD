"""Weight & balance revisions: per-method rounding, input sets, and CG gating."""
import pytest

from test_helpers import (
    TWO_LINE_EQUIPMENT,
    ApiErrorId,
    accept_wb_revision,
    assert_weight_balance_revision,
    create_and_accept_wb_revision,
    create_wb_revision,
    get_wb_revision,
    make_inspector_headers,
    setup_testing_work_order,
    validate_error,
)

# Two-line addition whose per-line moments diverge between rounding orders:
# 6.26 * 14.43 = 90.3318 -> 90.3; 3.74 * 20.44 = 76.4456 -> 76.4.
PROBE_LINES = [
    {"description": "GPS antenna", "weight_lb": 6.26, "arm_in": 14.43},
    {"description": "AHRS", "weight_lb": 3.74, "arm_in": 20.44},
]


class TestDualVariantMoments:
    def test_incremental_rounds_each_line_before_summing(self, api):
        """PRD §3.7: "Under this method each added line's moment — its `weight_lb` times its `arm_in` — is rounded half-up to one decimal before any summing, and those rounded moments are summed; the removed moment — `removed_weight_lb` times `removed_arm_in` — is likewise rounded half-up to one decimal; `new_moment_lb_in` is then the base moment plus the summed added moments minus the rounded removed moment, with that result itself rounded half-up to one decimal."

        Design: Difficulty/dual_variant_calc/weight_balance_incremental_vs_full_reweigh
        """
        bundle = setup_testing_work_order(
            customer_name="WB Owner", customer_email="wb@x.com",
            equipment_list=[], task_kind="HARNESS_FABRICATION",
            estimated_hours=5.0, actual_hours=5.0,
            work_order_overrides={"warranty_term_months": 12,
                                  "software_subscription_months": 6})
        revision = create_wb_revision(
            bundle["work_order"]["id"], method="INCREMENTAL",
            added_items=PROBE_LINES, removed_weight_lb=9.6, removed_arm_in=30.0)
        assert_weight_balance_revision(revision)
        # Per-line rounded 90.3 + 76.4 = 166.7; 72000.0 + 166.7 - 288.0.
        assert revision["new_moment_lb_in"] == pytest.approx(71878.7, abs=0.05)
        assert revision["new_empty_weight_lb"] == pytest.approx(1800.4, abs=0.05)
        assert revision["new_arm_in"] == pytest.approx(39.92, abs=0.005)

    def test_full_reweigh_rounds_summed_moment_once(self, api):
        """PRD §3.7: "Under this method the line moments are summed unrounded, and `new_moment_lb_in` is the base moment plus that raw sum minus the raw removed-moment product, rounded half-up to one decimal exactly once."
        PRD §3.7: "Identical inputs can therefore yield moments a tenth of a pound-inch apart between the two methods; the rounding order is part of the specification, not an implementation choice."

        Design: Difficulty/dual_variant_calc/weight_balance_incremental_vs_full_reweigh
        """
        bundle = setup_testing_work_order(
            customer_name="WB Owner", customer_email="wb@x.com",
            equipment_list=[], task_kind="HARNESS_FABRICATION",
            estimated_hours=5.0, actual_hours=5.0,
            work_order_overrides={"warranty_term_months": 12,
                                  "software_subscription_months": 6})
        incremental = create_wb_revision(
            bundle["work_order"]["id"], method="INCREMENTAL",
            added_items=PROBE_LINES, removed_weight_lb=9.6, removed_arm_in=30.0)
        full = create_wb_revision(
            bundle["work_order"]["id"], method="FULL_REWEIGH",
            added_items=PROBE_LINES, removed_weight_lb=9.6, removed_arm_in=30.0)
        # Raw sum 166.7774 rounded once: 72000 + 166.7774 - 288.0 -> 71878.8.
        assert full["new_moment_lb_in"] == pytest.approx(71878.8, abs=0.05)
        assert full["new_empty_weight_lb"] == pytest.approx(1800.4, abs=0.05)
        assert full["new_arm_in"] == pytest.approx(39.92, abs=0.005)
        divergence = full["new_moment_lb_in"] - incremental["new_moment_lb_in"]
        assert divergence == pytest.approx(0.1, abs=0.001), (
            "identical inputs yield moments a tenth of a pound-inch apart, "
            f"got {divergence}")


class TestRoundingOrderPinned:
    def test_incremental_per_line_rounding_value(self, api):
        """PRD §3.7: "An `INCREMENTAL` revision builds on the latest `ACCEPTED` revision of the same work order, falling back to the aircraft baseline when none has been accepted, and considers only the manual `added_items`; it never re-reads design lines. Under this method each added line's moment — its `weight_lb` times its `arm_in` — is rounded half-up to one decimal before any summing, and those rounded moments are summed; the removed moment — `removed_weight_lb` times `removed_arm_in` — is likewise rounded half-up to one decimal; `new_moment_lb_in` is then the base moment plus the summed added moments minus the rounded removed moment, with that result itself rounded half-up to one decimal."

        Design: Difficulty/combinatorial_formula/weight_balance_per_line_round_vs_sum_round
        """
        bundle = setup_testing_work_order(
            customer_name="Round Owner", customer_email="round@x.com",
            equipment_list=[], task_kind="HARNESS_FABRICATION",
            estimated_hours=1.0, actual_hours=1.0)
        revision = create_wb_revision(
            bundle["work_order"]["id"], method="INCREMENTAL",
            added_items=PROBE_LINES, removed_weight_lb=9.6, removed_arm_in=30.0)
        assert revision["new_moment_lb_in"] == pytest.approx(71878.7, abs=0.05), (
            "round-per-line-then-sum: 90.3 + 76.4 = 166.7 added moment")

    def test_full_reweigh_sum_then_round_diverges(self, api):
        """PRD §3.7: "A `FULL_REWEIGH` revision always builds on the aircraft baseline — `baseline_empty_weight_lb` and `baseline_moment_lb_in` — ignoring any prior revisions, and folds in every line of the work order's `APPROVED` panel design, each line contributing its `quantity` times its `weight_lb` at its `arm_in`, alongside the manual lines. Under this method the line moments are summed unrounded, and `new_moment_lb_in` is the base moment plus that raw sum minus the raw removed-moment product, rounded half-up to one decimal exactly once."

        Design: Difficulty/combinatorial_formula/weight_balance_per_line_round_vs_sum_round
        """
        bundle = setup_testing_work_order(
            customer_name="Round Owner", customer_email="round@x.com",
            equipment_list=[], task_kind="HARNESS_FABRICATION",
            estimated_hours=1.0, actual_hours=1.0)
        incremental = create_wb_revision(
            bundle["work_order"]["id"], method="INCREMENTAL",
            added_items=PROBE_LINES, removed_weight_lb=9.6, removed_arm_in=30.0)
        full = create_wb_revision(
            bundle["work_order"]["id"], method="FULL_REWEIGH",
            added_items=PROBE_LINES, removed_weight_lb=9.6, removed_arm_in=30.0)
        assert full["new_moment_lb_in"] == pytest.approx(71878.8, abs=0.05), (
            "sum-then-round-once: 166.7774 -> 71878.7774 -> 71878.8")
        assert abs(full["new_moment_lb_in"]
                   - incremental["new_moment_lb_in"]) == pytest.approx(0.1, abs=0.001)


class TestFullReweighInputSet:
    def test_full_reweigh_folds_in_approved_design_lines(self, api):
        """PRD §3.7: "A `FULL_REWEIGH` revision always builds on the aircraft baseline — `baseline_empty_weight_lb` and `baseline_moment_lb_in` — ignoring any prior revisions, and folds in every line of the work order's `APPROVED` panel design, each line contributing its `quantity` times its `weight_lb` at its `arm_in`, alongside the manual lines."
        PRD §3.7: "Weight is common to both methods: `new_empty_weight_lb` is the base weight plus the added lines' weights — design lines counted with their quantities — minus `removed_weight_lb`, rounded half-up to one decimal."

        Design: Corner/calculations/full_reweigh_includes_approved_design_lines
        """
        bundle = setup_testing_work_order(
            customer_name="Reweigh Rex", customer_email="r3@x.com",
            equipment_list=TWO_LINE_EQUIPMENT, task_kind="INSTALLATION",
            estimated_hours=2.0, actual_hours=2.0,
            work_order_overrides={"estimated_downtime_days": 20,
                                  "quoted_labor_hours": 10,
                                  "bay_window_end": "2026-08-30T00:00:00Z"})
        revision = create_wb_revision(bundle["work_order"]["id"],
                                      method="FULL_REWEIGH", added_items=[])
        assert_weight_balance_revision(revision)
        assert revision["new_empty_weight_lb"] == pytest.approx(1810.0, abs=0.05), (
            "1800.0 baseline + 6.26 + 3.74 design weights")
        assert revision["new_moment_lb_in"] == pytest.approx(72166.8, abs=0.05), (
            "72000.0 baseline + raw design moments 166.7774 rounded once")
        assert revision["new_arm_in"] == pytest.approx(39.87, abs=0.005)
        assert revision["cg_within_limits"] is True


class TestCgGateOnAccept:
    def test_out_of_envelope_revision_refused(self, api):
        """PRD §3.7: "And `cg_within_limits` is true exactly when `new_arm_in` lies between the aircraft's `cg_min_arm_in` and `cg_max_arm_in`, inclusive on both ends."
        PRD §3.7: "Acceptance belongs to an `Inspector` and requires two things: the parent work order in `INSTALLATION` or `TESTING` (`ERR_INVALID_STATE`), and `cg_within_limits` true — an out-of-envelope revision is refused with `ERR_CG_OUT_OF_LIMITS` (HTTP 422)."

        Design: Corner/errors/cg_out_of_limits_blocks_accept
        """
        bundle = setup_testing_work_order(
            customer_name="Cg Cathy", customer_email="c4@x.com",
            equipment_list=[], task_kind="HARNESS_FABRICATION",
            estimated_hours=1.0, actual_hours=1.0)
        revision = create_wb_revision(
            bundle["work_order"]["id"], method="INCREMENTAL",
            added_items=[{"description": "aft ballast", "weight_lb": 300.0,
                          "arm_in": 90.0}])
        # 300.0 lb at arm 90.0: moment 99000.0 / weight 2100.0 -> arm 47.14.
        assert revision["new_arm_in"] == pytest.approx(47.14, abs=0.005)
        assert revision["cg_within_limits"] is False, (
            "47.14 exceeds the aft limit 41.5, so the envelope flag is false")

        response = api.accept_weight_balance_revision(
            revision["id"], make_inspector_headers("insp-1"))
        validate_error(response, ApiErrorId.ERR_CG_OUT_OF_LIMITS)
        assert get_wb_revision(revision["id"])["status"] == "COMPUTED", (
            "the refused revision stays COMPUTED")


class TestRemovalRestoresBaseline:
    def test_installation_revision_moves_weight_forward(self, api):
        """PRD §3.7: "An `INCREMENTAL` revision builds on the latest `ACCEPTED` revision of the same work order, falling back to the aircraft baseline when none has been accepted, and considers only the manual `added_items`; it never re-reads design lines."
        PRD §3.7: "The new arm `new_arm_in` is `new_moment_lb_in` divided by `new_empty_weight_lb`, rounded half-up to two decimals."

        Design: Difficulty/compensating_invariant/empty_weight_restored_by_removal_revision
        """
        bundle = setup_testing_work_order(
            customer_name="WB2 Owner", customer_email="wb2@x.com",
            equipment_list=[], task_kind="HARNESS_FABRICATION",
            estimated_hours=1.0, actual_hours=1.0)
        revision = create_wb_revision(
            bundle["work_order"]["id"], method="INCREMENTAL",
            added_items=[{"description": "GPS", "weight_lb": 10.0, "arm_in": 40.0}])
        assert revision["new_empty_weight_lb"] == pytest.approx(1810.0, abs=0.05)
        assert revision["new_moment_lb_in"] == pytest.approx(72400.0, abs=0.05)
        assert revision["new_arm_in"] == pytest.approx(40.0, abs=0.005)
        accepted = accept_wb_revision(revision["id"])
        assert accepted["status"] == "ACCEPTED"

    def test_removal_revision_restores_baseline_and_supersedes(self, api):
        """PRD §3.7: "An `INCREMENTAL` revision builds on the latest `ACCEPTED` revision of the same work order, falling back to the aircraft baseline when none has been accepted, and considers only the manual `added_items`; it never re-reads design lines."
        PRD §3.7: "Accepting moves the revision from `COMPUTED` to `ACCEPTED` and automatically supersedes whichever revision of the same work order was previously `ACCEPTED`, moving it to `SUPERSEDED`."

        Design: Difficulty/compensating_invariant/empty_weight_restored_by_removal_revision
        """
        bundle = setup_testing_work_order(
            customer_name="WB2 Owner", customer_email="wb2@x.com",
            equipment_list=[], task_kind="HARNESS_FABRICATION",
            estimated_hours=1.0, actual_hours=1.0)
        first = create_and_accept_wb_revision(
            bundle["work_order"]["id"], method="INCREMENTAL",
            added_items=[{"description": "GPS", "weight_lb": 10.0, "arm_in": 40.0}])
        second = create_wb_revision(
            bundle["work_order"]["id"], method="INCREMENTAL", added_items=[],
            removed_weight_lb=10.0, removed_arm_in=40.0)
        # Base is the ACCEPTED +10.0 revision; removing the same weight/arm
        # restores the 1800.0 / 72000.0 / 40.0 baseline exactly.
        assert second["new_empty_weight_lb"] == pytest.approx(1800.0, abs=0.05)
        assert second["new_moment_lb_in"] == pytest.approx(72000.0, abs=0.05)
        assert second["new_arm_in"] == pytest.approx(40.0, abs=0.005)
        accepted = accept_wb_revision(second["id"])
        assert accepted["status"] == "ACCEPTED"
        assert get_wb_revision(first["id"])["status"] == "SUPERSEDED", (
            "the previously accepted revision is superseded by the new acceptance")
