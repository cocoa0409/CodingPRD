"""The deficiency score: severity base, rainfall multiplier, adders, cap and threshold."""

import pytest

from test_helpers import fixtures as fx
from test_helpers.assertions import assert_deficiency_score
from test_helpers.test_users import INSPECTOR_TWO_HEADERS


class TestEscScoreCombination:
    """Severity counts, the rainfall multiplier and the large-site adder interact."""

    @pytest.fixture
    def large_site(self):
        """A 6.00-acre site with an APPROVED plan, above the 5.00-acre cut."""
        program = fx.setup_active_program()
        site = fx.setup_site_with_approved_plan(
            program["term_id"],
            esc_plan_reference="ESC-BIG-1",
            site_name="SITE-BIG",
            operator_name="Northline Builders",
            disturbed_acres=6.00,
        )
        return {"program": program, "term_id": program["term_id"], "site": site}

    def test_01_the_rainfall_multiplier_is_applied_before_the_large_site_adder(
        self, large_site
    ):
        """1 MINOR and 2 MAJOR on a rained-out 6-acre site scores 74, not 77.

        PRD: "For a `CONSTRUCTION_ESC` inspection, if `rainfall_trigger` is true
        the base is multiplied by 1.20 and rounded to a whole number; then, if the
        subject site's `disturbed_acres` is strictly greater than 5.00, 12 points
        are added."

        Design: Difficulty/combinatorial_formula/esc_deficiency_score_severity_rainfall_and_acreage_interact
        """
        inspection = fx.create_esc_inspection(
            large_site["site"]["id"], "2026-07-01", "2026-07-15", rainfall_trigger=True
        )
        fx.add_findings(inspection["id"], ("MINOR", "MAJOR", "MAJOR"))

        finalized = fx.finalize_inspection(inspection["id"])

        assert finalized["minor_finding_count"] == 1, "one minor finding was appended"
        assert finalized["major_finding_count"] == 2, "two major findings were appended"
        assert finalized["critical_finding_count"] == 0, "no critical finding was appended"
        assert_deficiency_score(finalized, 74, True)
        assert finalized["deficiency_score"] != 77, (
            "77 is the result of adding the large-site 12 points before applying "
            "the 1.20 rainfall multiplier"
        )
        assert finalized["status"] == "FINALIZED", "finalization freezes the score"

    def test_02_without_rainfall_the_same_findings_score_the_bare_base_plus_adder(
        self, large_site
    ):
        """The same 52-point base on the same site scores 64 with no rainfall.

        PRD: "The base is 8 points for each finding counted in
        `minor_finding_count`, plus 22 points for each finding counted in
        `major_finding_count`, plus 34 points for each finding counted in
        `critical_finding_count`."

        Design: Difficulty/combinatorial_formula/esc_deficiency_score_severity_rainfall_and_acreage_interact
        """
        inspection = fx.create_esc_inspection(
            large_site["site"]["id"], "2026-07-01", "2026-07-15", rainfall_trigger=False
        )
        fx.add_findings(inspection["id"], ("MINOR", "MAJOR", "MAJOR"))

        finalized = fx.finalize_inspection(inspection["id"])

        assert_deficiency_score(finalized, 64, False)

    def test_03_an_escalating_erosion_control_inspection_stops_the_site(self, large_site):
        """The 74-point inspection drives the site into STOP_WORK.

        PRD: "When an erosion-control inspection is finalized with a
        `deficiency_score` of 70 or more, the site is driven from
        `ACTIVE_DISTURBANCE` into `STOP_WORK` without any operator asking for it:
        `stop_work_reason` is set to `AUTOMATIC_ESC_DEFICIENCY`,
        `open_deficiency_score` is set to that inspection's `deficiency_score`,
        `stop_work_count` increments by one, and a notice of violation is
        generated as described in §3.6."

        Design: Difficulty/combinatorial_formula/esc_deficiency_score_severity_rainfall_and_acreage_interact
        """
        inspection = fx.create_esc_inspection(
            large_site["site"]["id"], "2026-07-01", "2026-07-15", rainfall_trigger=True
        )
        fx.add_findings(inspection["id"], ("MINOR", "MAJOR", "MAJOR"))
        fx.finalize_inspection(inspection["id"])

        site = fx.read_site(large_site["site"]["id"])
        assert site["field_status"] == "STOP_WORK", "a score of 70 or more stops the work"
        assert site["stop_work_reason"] == "AUTOMATIC_ESC_DEFICIENCY", (
            "the automatic order records its own reason"
        )
        assert site["open_deficiency_score"] == 74, (
            "the site carries the frozen score of the inspection that stopped it"
        )
        assert site["stop_work_count"] == 1, "the automatic order counts as a stop work"

        measure = fx.read_measure(
            large_site["program"]["measures"]["CONSTRUCTION_RUNOFF"]["id"]
        )
        assert measure["enforcement_count"] == 1, (
            "the generated notice of violation reaches the construction runoff measure"
        )


class TestScoreRoundingAndSaturation:
    """The score rounds half up onto the threshold and never passes 100."""

    @pytest.fixture
    def small_site_with_facility(self):
        """A 1.00-acre site with an APPROVED plan and a facility recorded 2026-07-01."""
        program = fx.setup_active_program()
        site = fx.setup_site_with_approved_plan(
            program["term_id"],
            esc_plan_reference="ESC-F-1",
            site_name="SITE-F",
            operator_name="Fernhill Development",
            disturbed_acres=1.00,
        )
        facility = fx.setup_facility_with_agreement(
            site["id"],
            recorded_at="2026-07-01T00:00:00Z",
            inspection_interval_months=12,
            facility_type="WET_POND",
            design_capacity_cf=8000,
            service_area_acres=1.00,
        )
        return {"term_id": program["term_id"], "site": site, "facility": facility}

    def test_04_a_score_of_sixty_nine_point_six_rounds_up_onto_the_threshold(
        self, small_site_with_facility
    ):
        """3 MINOR and 1 CRITICAL with rainfall is 69.6, which rounds to 70.

        PRD: "`deficiency_score` is the resulting figure capped at 100, and
        `escalation_triggered` is set true exactly when `deficiency_score` is 70
        or more."

        Design: Difficulty/boundary_precision_check/deficiency_score_rounds_half_up_onto_the_threshold_and_saturates_at_one_hundred
        """
        inspection = fx.create_esc_inspection(
            small_site_with_facility["site"]["id"],
            "2026-07-01",
            "2026-07-15",
            rainfall_trigger=True,
        )
        fx.add_findings(inspection["id"], ("MINOR", "MINOR", "MINOR", "CRITICAL"))

        finalized = fx.finalize_inspection(inspection["id"])

        assert_deficiency_score(finalized, 70, True)
        assert finalized["deficiency_score"] != 69, (
            "69 is the result of truncating 69.6 instead of rounding it half up"
        )

    def test_05_no_large_site_adder_applies_below_the_five_acre_cut(
        self, small_site_with_facility
    ):
        """A 1.00-acre site earns no 12-point adder.

        PRD: "Coverage begins at one acre, so `disturbed_acres` must be at least
        1.00 and is carried to 2 decimal places."

        Design: Difficulty/boundary_precision_check/deficiency_score_rounds_half_up_onto_the_threshold_and_saturates_at_one_hundred
        """
        site = fx.read_site(small_site_with_facility["site"]["id"])
        assert site["disturbed_acres"] == pytest.approx(1.00, abs=0.01), (
            "the site is the small one"
        )

        inspection = fx.create_esc_inspection(
            site["id"], "2026-07-01", "2026-07-15", rainfall_trigger=True
        )
        fx.add_findings(inspection["id"], ("MINOR", "MINOR", "MINOR", "CRITICAL"))
        finalized = fx.finalize_inspection(inspection["id"])

        assert finalized["deficiency_score"] == 70, (
            "82 would mean the large-site adder was applied to a 1.00-acre site"
        )

    def test_06_a_maintenance_base_above_one_hundred_saturates_at_one_hundred(
        self, small_site_with_facility
    ):
        """Three critical findings are 102 points, reported as 100.

        PRD: "`deficiency_score` is the resulting figure capped at 100, and
        `escalation_triggered` is set true exactly when `deficiency_score` is 70
        or more."

        Design: Difficulty/boundary_precision_check/deficiency_score_rounds_half_up_onto_the_threshold_and_saturates_at_one_hundred
        """
        inspection = fx.create_maintenance_inspection(
            small_site_with_facility["facility"]["id"],
            "2026-07-20",
            "2026-07-25",
            rainfall_trigger=True,
        )
        fx.add_findings(inspection["id"], ("CRITICAL", "CRITICAL", "CRITICAL"))

        finalized = fx.finalize_inspection(inspection["id"], INSPECTOR_TWO_HEADERS)

        assert finalized["critical_finding_count"] == 3, "three critical findings"
        assert_deficiency_score(finalized, 100, True)

    def test_07_the_maintenance_branch_ignores_rainfall_and_adds_no_adder_when_current(
        self, small_site_with_facility
    ):
        """A recorded, non-overdue facility earns neither maintenance adder.

        PRD: "For a `POST_CONSTRUCTION_MAINTENANCE` inspection,
        `rainfall_trigger` is ignored entirely. Instead, if the subject facility's
        `inspection_overdue` is true, 15 points are added; then, if that
        facility's `ownership` is `PRIVATE` and its `agreement_status` is anything
        other than `RECORDED`, a further 25 points are added."

        Design: Difficulty/boundary_precision_check/deficiency_score_rounds_half_up_onto_the_threshold_and_saturates_at_one_hundred
        """
        facility_id = small_site_with_facility["facility"]["id"]
        before = fx.read_facility(facility_id)
        assert before["agreement_status"] == "RECORDED", "the agreement is on record"
        assert before["inspection_overdue"] is False, "the facility is not yet overdue"

        inspection = fx.create_maintenance_inspection(
            facility_id, "2026-07-20", "2026-07-25", rainfall_trigger=True
        )
        fx.add_findings(inspection["id"], ("MINOR", "MAJOR"))
        finalized = fx.finalize_inspection(inspection["id"], INSPECTOR_TWO_HEADERS)

        assert_deficiency_score(finalized, 30, False)
        assert finalized["deficiency_score"] != 36, (
            "36 would mean the rainfall multiplier was applied to a maintenance "
            "inspection"
        )

    def test_08_both_frozen_scores_are_plain_integers(self, small_site_with_facility):
        """Neither branch reports a fractional score.

        PRD: "The **deficiency score** is computed once, at finalize, and never
        recomputed afterwards."

        Design: Difficulty/boundary_precision_check/deficiency_score_rounds_half_up_onto_the_threshold_and_saturates_at_one_hundred
        """
        esc = fx.create_esc_inspection(
            small_site_with_facility["site"]["id"],
            "2026-07-01",
            "2026-07-15",
            rainfall_trigger=True,
        )
        fx.add_findings(esc["id"], ("MINOR", "MINOR", "MINOR", "CRITICAL"))
        finalized_esc = fx.finalize_inspection(esc["id"])

        maintenance = fx.create_maintenance_inspection(
            small_site_with_facility["facility"]["id"], "2026-07-20", "2026-07-25"
        )
        fx.add_findings(maintenance["id"], ("CRITICAL", "CRITICAL", "CRITICAL"))
        finalized_maintenance = fx.finalize_inspection(
            maintenance["id"], INSPECTOR_TWO_HEADERS
        )

        assert isinstance(finalized_esc["deficiency_score"], int), (
            "the erosion-control score must be a whole number"
        )
        assert isinstance(finalized_maintenance["deficiency_score"], int), (
            "the maintenance score must be a whole number"
        )

        site = fx.read_site(small_site_with_facility["site"]["id"])
        assert site["open_deficiency_score"] == 70, (
            "the stopped site carries the erosion-control score"
        )
        facility = fx.read_facility(small_site_with_facility["facility"]["id"])
        assert facility["credit_eligible"] is True, (
            "a high maintenance score does not itself disqualify the facility"
        )
