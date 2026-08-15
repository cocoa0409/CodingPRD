"""State CE licenses: strict-vs-carryover variants, per-course rounding,
carryover computation at renewal, and void reconciliation."""
import pytest

from test_helpers import (
    CLOCK_DEFAULT,
    TEST_USERS,
    complete_state_insurance_course,
    create_approved_content,
    create_enrollment,
    create_license,
    create_rep,
    get_success_data,
    make_rep_headers,
    set_clock,
    start_enrollment,
    validate_success,
    void_enrollment,
)

ADMIN = TEST_USERS["admin_headers"]


class TestStateCeStrictVsCarryover:
    """strict counts current-window completions only; effective adds capped
    carryover from the prior period."""

    def _setup_two_periods(self, api):
        """Rep with CA license (required 4.0). Period 1: complete S1 (4.0h) +
        S2 (5.0h) => strict 9.0, excess = 9 - 4 = 5. Renew to period 2
        (2027): carried = min(6, 5) = 5.0. Then complete S3 (2.0h) in period 2.
        """
        set_clock(CLOCK_DEFAULT)
        rep = create_rep(
            crd_number="CRD-DV2", insurance_licensed=True,
            resident_state_code="CA", prior_year_excess_hours=0)
        license_ = create_license(
            rep["id"], state_code="CA", required_hours=4.0,
            period_start="2026-01-01T00:00:00Z",
            period_end="2027-01-01T00:00:00Z")
        # Complete 4.0h and 5.0h inside period 1 (default clock 2026-08-01).
        complete_state_insurance_course(rep, credit_hours=4.0, code="S1")
        complete_state_insurance_course(rep, credit_hours=5.0, code="S2")
        # Renew: carried = min(6, max(0, 9 - 4)) = 5.0
        license_ = get_success_data(api.renew_state_ce_license(
            license_["id"],
            {"new_period_start": "2027-01-01T00:00:00Z",
             "new_period_end": "2028-01-01T00:00:00Z"},
            ADMIN))
        # Move clock into period 2 and complete 2.0h.
        set_clock("2027-06-01T00:00:00Z")
        complete_state_insurance_course(rep, credit_hours=2.0, code="S3")
        return rep, license_

    def test_strict_counts_current_window_only(self, api, officer_headers):
        """PRD §3.8: "`earned_hours_strict` is the sum of `credit_hours` over
        the rep's `COMPLETED`, non-voided `STATE_INSURANCE` enrollments whose
        `completed_at` falls inside the current window."

        Design: Difficulty/dual_variant_calc/state_ce_strict_vs_carryover_hours
        """
        rep, license_ = self._setup_two_periods(api)
        data = validate_success(
            api.get_state_ce_license(license_["id"], officer_headers))
        assert data["earned_hours_strict"] == pytest.approx(2.0, abs=0.01), (
            f"strict must count only the 2.0h completed in the current window, "
            f"got {data['earned_hours_strict']}")

    def test_effective_adds_capped_carryover(self, api, officer_headers):
        """PRD §3.8: "`earned_hours_effective` is `earned_hours_strict` plus
        the carried excess, with the carried portion capped at 6 hours —
        carried credit beyond six hours never counts."
        PRD §3.8: "Before the window is replaced, the carryover is computed
        from the closing window: `carried_excess_hours` becomes the smaller of
        6 hours and the positive part of `earned_hours_strict` minus
        `required_hours` — zero when the rep earned no more than required."

        Design: Difficulty/dual_variant_calc/state_ce_strict_vs_carryover_hours
        """
        rep, license_ = self._setup_two_periods(api)
        data = validate_success(
            api.get_state_ce_license(license_["id"], officer_headers))
        assert data["carried_excess_hours"] == pytest.approx(5.0, abs=0.01), (
            f"carried excess must be min(6, 9 - 4) = 5.0, "
            f"got {data['carried_excess_hours']}")
        assert data["earned_hours_effective"] == pytest.approx(7.0, abs=0.01), (
            f"effective must be strict 2.0 + carried 5.0 = 7.0, "
            f"got {data['earned_hours_effective']}")


class TestReportedHoursPerCourseRounding:
    """Each course rounds half-up to 0.5h BEFORE summation (pinned order)."""

    def _setup_rounding_case(self, api):
        """NJ license (required 99); three STATE_INSURANCE completions at the
        default clock 2026-08-01 (inside window [2026-01-01, 2027-01-01)):
        1.25h + 1.25h + 2.0h."""
        set_clock(CLOCK_DEFAULT)
        rep = create_rep(
            crd_number="CRD-CF2", insurance_licensed=True,
            resident_state_code="NJ", prior_year_excess_hours=0)
        license_ = create_license(
            rep["id"], state_code="NJ", required_hours=99,
            period_start="2026-01-01T00:00:00Z",
            period_end="2027-01-01T00:00:00Z")
        complete_state_insurance_course(rep, credit_hours=1.25, code="R1")
        complete_state_insurance_course(rep, credit_hours=1.25, code="R2")
        complete_state_insurance_course(rep, credit_hours=2.0, code="R3")
        return rep, license_

    def test_reported_hours_rounds_per_course_first(self, api, officer_headers):
        """PRD §3.8: "`reported_hours` covers the same window set as
        `earned_hours_strict` but rounds per course before summing: each
        course's `credit_hours` is rounded half up to the nearest half hour —
        equivalently, the hours are doubled, rounded half up to a whole number,
        then halved — and the per-course values are then summed exactly."
        PRD §3.8: "The order is pinned and not interchangeable with rounding
        the total: two courses of 1.25 hours each report 3.0 hours (each rounds
        to 1.5), whereas summing first and rounding would yield 2.5 and is
        non-conforming."

        Design: Difficulty/combinatorial_formula/state_ce_reported_hours_per_course_rounding
        """
        rep, license_ = self._setup_rounding_case(api)
        data = validate_success(
            api.get_state_ce_license(license_["id"], officer_headers))
        # 1.25 -> 1.5, 1.25 -> 1.5, 2.0 -> 2.0; sum = 5.0
        assert data["reported_hours"] == pytest.approx(5.0, abs=0.01), (
            f"per-course-first rounding must yield 1.5 + 1.5 + 2.0 = 5.0, "
            f"got {data['reported_hours']}")

    def test_strict_hours_unrounded_sum(self, api, officer_headers):
        """PRD §3.8: "`earned_hours_strict` is the sum of `credit_hours` over
        the rep's `COMPLETED`, non-voided `STATE_INSURANCE` enrollments whose
        `completed_at` falls inside the current window."

        Design: Difficulty/combinatorial_formula/state_ce_reported_hours_per_course_rounding
        """
        rep, license_ = self._setup_rounding_case(api)
        data = validate_success(
            api.get_state_ce_license(license_["id"], officer_headers))
        assert data["earned_hours_strict"] == pytest.approx(4.5, abs=0.01), (
            f"strict is the raw sum 1.25 + 1.25 + 2.0 = 4.5 (distinct from "
            f"reported 5.0), got {data['earned_hours_strict']}")


class TestLicenseHoursReconcileOnVoid:
    """Voiding the only completion returns earned_hours_strict to 0."""

    def _setup_completed(self, api):
        set_clock(CLOCK_DEFAULT)
        rep = create_rep(
            crd_number="CRD-C39", insurance_licensed=True,
            resident_state_code="CA", prior_year_excess_hours=0)
        license_ = create_license(
            rep["id"], state_code="CA", required_hours=24,
            period_start="2026-01-01T00:00:00Z",
            period_end="2027-01-01T00:00:00Z")
        _content, enrollment = complete_state_insurance_course(
            rep, credit_hours=4.0, code="SI-RECON")
        return rep, license_, enrollment

    def test_completion_raises_strict_hours(self, api, officer_headers):
        """PRD §3.8: "Three hour counters track the license, each recomputed
        whenever one of the rep's `STATE_INSURANCE` enrollments completes or is
        voided, and once more at renewal. `earned_hours_strict` is the sum of
        `credit_hours` over the rep's `COMPLETED`, non-voided `STATE_INSURANCE`
        enrollments whose `completed_at` falls inside the current window."

        Design: Corner/cross_cutting_layers/c_license_hours_reconcile_on_void
        """
        rep, license_, _enr = self._setup_completed(api)
        data = validate_success(
            api.get_state_ce_license(license_["id"], officer_headers))
        assert data["earned_hours_strict"] == pytest.approx(4.0, abs=0.01), (
            f"the 4.0h completion must raise strict hours to 4.0, "
            f"got {data['earned_hours_strict']}")

    def test_void_returns_strict_hours_to_zero(self, api, officer_headers):
        """PRD §3.4: "For `STATE_INSURANCE` content, the license's hour
        counters are recomputed."
        PRD §2.10: "Terminal, non-credit enrollment states — `CANCELLED`,
        `EXPIRED`, `VOIDED`, and `FAILED` — are excluded from every hour
        aggregation in the system."

        Design: Corner/cross_cutting_layers/c_license_hours_reconcile_on_void
        """
        rep, license_, enrollment = self._setup_completed(api)
        before = validate_success(
            api.get_state_ce_license(license_["id"], officer_headers))
        assert before["earned_hours_strict"] == pytest.approx(4.0, abs=0.01)

        void_enrollment(
            enrollment["id"], justification="vendor reported wrong course id")
        after = validate_success(
            api.get_state_ce_license(license_["id"], officer_headers))
        assert after["earned_hours_strict"] == pytest.approx(0, abs=0.01), (
            f"voiding the only completion must reconcile strict hours to 0, "
            f"got {after['earned_hours_strict']}")
