"""Cut-list explosion math: waste tiers, length surcharges, cap, pinned rounding."""
import pytest

from test_helpers import (
    validate_success,
    TEST_USERS,
    make_jig,
    make_sealed_design,
    explode_cut_list,
    cut_list_line_payload,
    lines_of,
    setup_confirmed_job,
    cut_list_fresh,
)

PP = TEST_USERS["production_planner_headers"]


def _waste_tier_lists():
    """Two sealed designs on one confirmed job, each exploded into a cut list:
    TR-MSR (SPF_MSR2400) with 12/16/20-ft lines and TR-NO2 (SPF_NO2) with a 20-ft line."""
    ns = setup_confirmed_job(job_name="Waste Job", contract=1000000)
    ns.jig = make_jig()
    ns.dsg_msr = make_sealed_design(ns.job["id"], ns.eng1, ns.eng2, component_ref="TR-MSR",
                                    lumber_grade="SPF_MSR2400", quantity_required=1)
    ns.cl_msr, msr_lines = explode_cut_list(ns.dsg_msr["id"], ns.jig["id"], [
        cut_list_line_payload("TC-1", "L2X6", 12.0, 10),
        cut_list_line_payload("BC-16", "L2X4", 16.0, 10),
        cut_list_line_payload("BC-20", "L2X4", 20.0, 5),
    ])
    ns.msr_lines = msr_lines
    ns.dsg_no2 = make_sealed_design(ns.job["id"], ns.eng1, ns.eng2, component_ref="TR-NO2",
                                    lumber_grade="SPF_NO2", quantity_required=1,
                                    span_ft=24.0, pitch_degrees=18.43)
    ns.cl_no2, ns.no2_lines = explode_cut_list(ns.dsg_no2["id"], ns.jig["id"], [
        cut_list_line_payload("CAP-1", "L2X6", 20.0, 1),
    ])
    return ns


class TestWasteTierLengthGradeInteraction:
    def test_msr_length_tiers_progression(self, api):
        """PRD §3.4: "The line's `waste_pct` starts from a base rate keyed on the
        design's `lumber_grade`: 0.08 for `SPF_NO2`, 0.05 for `SPF_MSR2400`, and 0.06
        for `SYP_NO1`. To that base, a length surcharge is added: 0.04 when
        `length_ft` is at least 20 feet, else 0.02 when it is at least 16 feet but
        under 20, else 0." and "The line's `required_board_feet` — its reservation
        coverage requirement — is `line_board_feet` multiplied by one plus
        `waste_pct`, rounded half-up to 2 decimal places."

        Design: Difficulty/combinatorial_formula/waste_tier_length_grade_interaction
        """
        ns = _waste_tier_lists()
        lines = lines_of(ns.cl_msr["id"])
        l12, l16, l20 = lines["TC-1"], lines["BC-16"], lines["BC-20"]
        assert l12["line_board_feet"] == pytest.approx(120.00)
        assert l12["waste_pct"] == pytest.approx(0.05), "12 ft: no length surcharge"
        assert l12["required_board_feet"] == pytest.approx(126.00)
        assert l16["line_board_feet"] == pytest.approx(106.67)
        assert l16["waste_pct"] == pytest.approx(0.07), "exactly 16 ft takes the 0.02 surcharge"
        assert l16["required_board_feet"] == pytest.approx(114.14)
        assert l20["line_board_feet"] == pytest.approx(66.67)
        assert l20["waste_pct"] == pytest.approx(0.09), "20 ft takes the 0.04 surcharge"
        assert l20["required_board_feet"] == pytest.approx(72.67)
        header = cut_list_fresh(ns.cl_msr["id"])
        assert header["total_board_feet"] == pytest.approx(312.81)
        assert header["total_pieces"] == 25
        assert header["total_plates"] == 28, "quantity_required 1 x 28 per ROOF_TRUSS"

    def test_no2_twenty_foot_line_clamps_at_cap(self, api):
        """PRD §3.4: "The sum is then capped at 0.11 — the smaller of the summed rate
        and the cap applies. Because the cap clamps the sum, grade and length interact
        non-linearly: an `SPF_NO2` line at 20 feet or more lands exactly on the cap,
        while an `SPF_MSR2400` line of the same length does not."

        Design: Difficulty/combinatorial_formula/waste_tier_length_grade_interaction
        """
        ns = _waste_tier_lists()
        cap_line = lines_of(ns.cl_no2["id"])["CAP-1"]
        assert cap_line["waste_pct"] == pytest.approx(0.11), \
            "raw 0.08 + 0.04 = 0.12 is clamped to the 0.11 cap"
        assert cap_line["required_board_feet"] == pytest.approx(22.20)
        assert cut_list_fresh(ns.cl_no2["id"])["total_board_feet"] == pytest.approx(22.20)


def _rounding_list():
    """SPF_NO2 design exploded into two identical L2X4 8.0-ft x1 lines."""
    ns = setup_confirmed_job(job_name="Rounding Job", contract=100000)
    ns.jig = make_jig()
    ns.dsg = make_sealed_design(ns.job["id"], ns.eng1, ns.eng2, component_ref="TR-R",
                                lumber_grade="SPF_NO2", quantity_required=2,
                                span_ft=12.0, pitch_degrees=14.04, design_load_psf=30.0)
    ns.cl_r, ns.lines = explode_cut_list(ns.dsg["id"], ns.jig["id"], [
        cut_list_line_payload("M-1", "L2X4", 8.0, 1),
        cut_list_line_payload("M-2", "L2X4", 8.0, 1),
    ])
    return ns


class TestCutListTotalRoundingOrder:
    def test_per_line_rounding_then_sum(self, api):
        """PRD §3.4: "`total_board_feet` is the sum of the lines' `required_board_feet`
        values, each already rounded to 2 decimals — the system rounds per line first,
        then sums the rounded values. Summing raw values and rounding once at the end
        is forbidden and produces different totals: two `L2X4` lines of 8.0 feet at
        quantity 1 in `SPF_NO2` yield 5.76 plus 5.76, totalling 11.52 under the pinned
        order, versus 11.51 if the raw sum were rounded once."

        Design: Difficulty/combinatorial_formula/cut_list_total_rounding_order
        """
        ns = _rounding_list()
        lines = lines_of(ns.cl_r["id"])
        for label in ("M-1", "M-2"):
            assert lines[label]["line_board_feet"] == pytest.approx(5.33)
            assert lines[label]["required_board_feet"] == pytest.approx(5.76), \
                "per-line round_half_up of 5.7564 is 5.76"
        total = cut_list_fresh(ns.cl_r["id"])["total_board_feet"]
        assert total == pytest.approx(11.52), "pinned per-line-then-sum order"
        assert abs(total - 11.51) > 1e-9, "sum-then-round would produce 11.51"

    def test_piece_and_plate_totals(self, api):
        """PRD §3.4: "`total_pieces` is the integer sum of `qty` over all lines.
        `total_plates` is the design's `quantity_required` multiplied by a per-unit
        plate count keyed on `component_type`: 24 for `FLOOR_TRUSS`, 28 for
        `ROOF_TRUSS`, and 12 for `WALL_PANEL`."

        Design: Difficulty/combinatorial_formula/cut_list_total_rounding_order
        """
        ns = _rounding_list()
        header = cut_list_fresh(ns.cl_r["id"])
        assert header["total_pieces"] == 2
        assert header["total_plates"] == 56, "quantity_required 2 x 28 per ROOF_TRUSS"


class TestWasteLengthThresholdExact16ft:
    def test_exactly_16ft_crosses_tier(self, api):
        """PRD §3.4: "To that base, a length surcharge is added: 0.04 when `length_ft`
        is at least 20 feet, else 0.02 when it is at least 16 feet but under 20, else 0."

        Design: Corner/calculations/waste_length_threshold_exact_16ft
        """
        ns = setup_confirmed_job(job_name="Edge Job", contract=100000)
        jig = make_jig()
        dsg = make_sealed_design(ns.job["id"], ns.eng1, ns.eng2, component_ref="TR-E",
                                 lumber_grade="SPF_NO2", quantity_required=1,
                                 span_ft=24.0, pitch_degrees=18.43)
        cl, _ = explode_cut_list(dsg["id"], jig["id"], [
            cut_list_line_payload("EDGE-15", "L2X4", 15.9, 10),
            cut_list_line_payload("EDGE-16", "L2X4", 16.0, 10),
        ])
        lines = lines_of(cl["id"])
        assert lines["EDGE-15"]["waste_pct"] == pytest.approx(0.08), "15.9 ft: no surcharge"
        assert lines["EDGE-15"]["required_board_feet"] == pytest.approx(114.49)
        assert lines["EDGE-16"]["waste_pct"] == pytest.approx(0.10), \
            "exactly 16.0 ft crosses the at-least-16 tier"
        assert lines["EDGE-16"]["required_board_feet"] == pytest.approx(117.34)
        assert cut_list_fresh(cl["id"])["total_board_feet"] == pytest.approx(231.83)
