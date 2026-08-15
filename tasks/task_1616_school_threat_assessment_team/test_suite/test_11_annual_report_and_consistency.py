"""District annual reporting (rounding order) and immediate consistency."""
import pytest

from test_helpers import (
    TEST_USERS,
    create_case,
    create_school,
    get_case,
    screen_case,
    triage_case,
    validate_success,
)

IC = TEST_USERS["intake_coordinator_headers"]
TL = TEST_USERS["team_lead_headers"]


def _entry_numeric_values(entry):
    return [v for v in entry.values()
            if isinstance(v, (int, float)) and not isinstance(v, bool)]


class TestDistrictAnnualReport:
    def _setup_report_window(self, api):
        """Schools A (2 SUBSTANTIVE of 3), B (1 of 3), C (1 of 1), D (none).
        All cases are created at the logical-clock default 2026-08-01, the
        first instant of school year 2026-2027."""
        sch_a = create_school(name="School A", school_code="SA")
        sch_b = create_school(name="School B", school_code="SB")
        sch_c = create_school(name="School C", school_code="SC")
        create_school(name="School D", school_code="SD")

        for school, alias, summary, score in (
                (sch_a, "STU-A1", "a1", 3),
                (sch_a, "STU-A2", "a2", 3),
                (sch_a, "STU-A3", "a3", 1),
                (sch_b, "STU-B1", "b1", 3),
                (sch_b, "STU-B2", "b2", 1),
                (sch_b, "STU-B3", "b3", 1),
                (sch_c, "STU-C1", "c1", 3),
        ):
            case = create_case(school["id"], subject_alias=alias,
                               summary=summary)
            triage_case(case["id"])
            screen_case(case["id"], true_count=score)

    def test_annual_report_totals_and_per_school_rates(self, api):
        """PRD: "Every threat case whose `created_at` falls inside that
        half-open window counts, regardless of status — including `PURGED`
        cases."
        PRD: "Schools with no cases in the window are excluded both from the
        per-school listing and from the mean."
        PRD: "The response carries `school_year`, the district-wide raw sums
        `total_cases` and `substantiated_cases` (counts, not rates), the
        `per_school` array, and `district_substantiation_rate`."

        Design: Difficulty/combinatorial_formula/annual_report_per_school_then_district_rounding
        """
        self._setup_report_window(api)

        report = validate_success(
            api.get_district_annual_report("2026-2027", TL), 200)
        assert report["school_year"] == "2026-2027"
        assert report["total_cases"] == 7
        assert report["substantiated_cases"] == 4

        per_school = report["per_school"]
        assert isinstance(per_school, list)
        assert len(per_school) == 3, (
            "the zero-case school is excluded from the per-school listing"
        )
        # The PRD pins the top-level response fields and the per-school rate
        # values, but not the per-school entry key names; locate the three
        # rates by value (2/3 -> 66.67, 1/3 -> 33.33, 1/1 -> 100.0).
        numeric = [v for entry in per_school for v in _entry_numeric_values(entry)]
        for expected in (66.67, 33.33, 100.0):
            assert any(v == pytest.approx(expected, abs=0.005) for v in numeric), (
                f"missing per-school rate {expected} in {per_school}"
            )

    def test_district_rate_rounds_per_school_rates_first(self, api):
        """PRD: "The district substantiation rate is then the arithmetic mean
        of the included schools' already-rounded rates, itself rounded
        half-up to two decimal places."
        PRD: "This rounding order is pinned: per-school rates are rounded
        first and only then averaged — aggregating raw counts before rounding
        is not equivalent and is not what the report produces."

        Design: Difficulty/combinatorial_formula/annual_report_per_school_then_district_rounding
        """
        self._setup_report_window(api)

        report = validate_success(
            api.get_district_annual_report("2026-2027", TL), 200)
        # Per-school-first: (66.67 + 33.33 + 100.00) / 3 = 66.666... -> 66.67.
        assert report["district_substantiation_rate"] == pytest.approx(
            66.67, abs=0.005)
        # Raw-count aggregation would instead produce 4/7 -> 57.14.
        assert abs(report["district_substantiation_rate"] - 57.14) > 0.5


class TestImmediateConsistency:
    def test_triage_mutation_immediately_visible(self, api):
        """PRD: "`version` (integer): a system-managed integer that increments
        with every mutation of the resource, including mutations caused by
        cascades from related resources."
        PRD: "A successful triage moves the case from `INTAKE` to `TRIAGED`,
        stamps the chosen priority onto `triage_priority` (which is null
        before triage), and writes `CASE_TRIAGED`."

        Design: Corner/consistency_model/mutations_are_immediately_visible
        """
        school = create_school(name="Cons HS", school_code="CON")
        case = create_case(school["id"], subject_alias="STU-CO",
                           summary="consistency")
        version_before = case["version"]

        validate_success(
            api.triage_case(
                case["id"],
                {"triage_priority": "URGENT", "triage_notes": "now visible"},
                IC),
            200,
        )

        after = get_case(case["id"])
        assert after["status"] == "TRIAGED"
        assert after["triage_priority"] == "URGENT"
        assert after["version"] == version_before + 1, (
            "the triage mutation is fully visible in the very next read"
        )
