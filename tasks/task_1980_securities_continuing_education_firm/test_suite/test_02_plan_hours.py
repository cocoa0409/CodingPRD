"""Firm element plan hours: certified vs projected variants, required-hours
formula, and the complete/void conservation invariant."""
import pytest

from test_helpers import (
    ApiErrorId,
    complete_enrollment,
    create_approved_content,
    create_enrollment,
    create_needs_analysis_payload,
    create_plan,
    create_published_plan,
    create_rep,
    get_pending_attestation,
    get_success_data,
    make_rep_headers,
    set_clock,
    setup_rep_with_published_plan,
    start_enrollment,
    validate_error,
    validate_success,
    void_enrollment,
    CLOCK_DEFAULT,
)


class TestPlanCertifiedVsProjectedHours:
    """Two variants over the same plan rows: certified counts only COMPLETED;
    projected additionally counts IN_PROGRESS."""

    def _setup(self, api):
        """RR rep (excess 0); FE-A 3.0h APPROVED; FE-B 2.0h APPROVED;
        plan 2026 published; FE-A COMPLETED; FE-B IN_PROGRESS."""
        set_clock(CLOCK_DEFAULT)
        rep = create_rep(crd_number="CRD-DV1", prior_year_excess_hours=0)
        content_a = create_approved_content(
            code="FE-A", ce_category="FIRM_ELEMENT", credit_hours=3.0)
        content_b = create_approved_content(
            code="FE-B", ce_category="FIRM_ELEMENT", credit_hours=2.0)
        plan = create_published_plan(rep["id"], rep["version"], plan_year=2026)
        enr_a = create_enrollment(rep["id"], content_id=content_a["id"])
        start_enrollment(enr_a["id"], rep["id"])
        complete_enrollment(enr_a["id"], rep["id"], score=90)
        enr_b = create_enrollment(rep["id"], content_id=content_b["id"])
        start_enrollment(enr_b["id"], rep["id"])
        return rep, plan, content_a, content_b, enr_a, enr_b

    def test_certified_counts_only_completed(self, api, admin_headers):
        """PRD §3.6: "The plan's `certified_hours` is the sum of `credit_hours`
        over the rep's `COMPLETED`, non-voided enrollments in `FIRM_ELEMENT`
        content whose `completed_at` falls in the calendar year `plan_year`."

        Design: Difficulty/dual_variant_calc/plan_certified_vs_projected_hours
        """
        rep, plan, _ca, _cb, _ea, _eb = self._setup(api)
        data = validate_success(api.get_firm_element_plan(plan["id"], admin_headers))
        assert data["certified_hours"] == pytest.approx(3.0, abs=0.01), (
            f"certified_hours must equal the completed 3.0h only, "
            f"got {data['certified_hours']}")

    def test_projected_adds_in_progress_on_top(self, api, admin_headers):
        """PRD §3.6: "The plan's `projected_hours` is `certified_hours` plus
        the `credit_hours` of the rep's `IN_PROGRESS` `FIRM_ELEMENT`
        enrollments; because in-progress rows carry no `completed_at`, the
        plan-year filter applies only to completed rows, and `projected_hours`
        is therefore always at least `certified_hours`."

        Design: Difficulty/dual_variant_calc/plan_certified_vs_projected_hours
        """
        rep, plan, _ca, _cb, _ea, _eb = self._setup(api)
        data = validate_success(api.get_firm_element_plan(plan["id"], admin_headers))
        assert data["projected_hours"] == pytest.approx(5.0, abs=0.01), (
            f"projected_hours must be certified 3.0 + in-progress 2.0 = 5.0, "
            f"got {data['projected_hours']}")
        assert data["projected_hours"] >= data["certified_hours"]


class TestPlanHoursCompleteVoidInvariant:
    """Complete credits hours; its compensating void debits exactly them back."""

    def _setup_published(self, api):
        set_clock(CLOCK_DEFAULT)
        rep = create_rep(crd_number="CRD-INV2", prior_year_excess_hours=0)
        content = create_approved_content(
            code="FE-INV", ce_category="FIRM_ELEMENT", credit_hours=4.0)
        plan = create_published_plan(rep["id"], rep["version"], plan_year=2026)
        return rep, plan, content

    def test_completion_credits_hours(self, api, admin_headers):
        """PRD §3.6: "The plan's `certified_hours` is the sum of `credit_hours`
        over the rep's `COMPLETED`, non-voided enrollments in `FIRM_ELEMENT`
        content whose `completed_at` falls in the calendar year `plan_year`."

        Design: Difficulty/compensating_invariant/plan_hours_complete_void_invariant
        """
        rep, plan, content = self._setup_published(api)
        before = validate_success(
            api.get_firm_element_plan(plan["id"], admin_headers))
        assert before["certified_hours"] == pytest.approx(0, abs=0.01)

        enr = create_enrollment(rep["id"], content_id=content["id"])
        start_enrollment(enr["id"], rep["id"])
        complete_enrollment(enr["id"], rep["id"], score=88)

        after = validate_success(
            api.get_firm_element_plan(plan["id"], admin_headers))
        assert after["certified_hours"] == pytest.approx(4.0, abs=0.01), (
            f"completion must credit 4.0 hours, got {after['certified_hours']}")

    def test_void_returns_certified_hours_to_zero(self, api, admin_headers):
        """PRD §3.4: "For `FIRM_ELEMENT` content, the matching plan's hours are
        recomputed; if that plan was `CLOSED` and the recomputed
        `certified_hours` now fall below its `required_hours`, the plan
        reopens."
        PRD §2.10: "Terminal, non-credit enrollment states — `CANCELLED`,
        `EXPIRED`, `VOIDED`, and `FAILED` — are excluded from every hour
        aggregation in the system, which is what makes cascades like
        cancellation and voiding automatically subtract their hours from plans
        and licenses."

        Design: Difficulty/compensating_invariant/plan_hours_complete_void_invariant
        """
        rep, plan, content = self._setup_published(api)
        enr = create_enrollment(rep["id"], content_id=content["id"])
        start_enrollment(enr["id"], rep["id"])
        complete_enrollment(enr["id"], rep["id"], score=88)
        mid = validate_success(api.get_firm_element_plan(plan["id"], admin_headers))
        assert mid["certified_hours"] == pytest.approx(4.0, abs=0.01)

        void_enrollment(
            enr["id"], justification="duplicate credit recorded by vendor")
        after = validate_success(
            api.get_firm_element_plan(plan["id"], admin_headers))
        assert after["certified_hours"] == pytest.approx(0, abs=0.01), (
            f"complete+void pair must conserve the credit-hour ledger at 0, "
            f"got {after['certified_hours']}")


class TestRequiredHoursFormula:
    """firm_element_required_hours: tier base + capped surcharge - excess,
    floored at MIN_REQUIRED_HOURS."""

    def test_capped_surcharge_binds_at_three_products(self, api, admin_headers):
        """PRD §3.6: "The computation runs in a pinned order: begin with the
        tier base, 12 hours for a rep whose `role_tier` is `RR` or 16 hours for
        `PRINCIPAL`; add a product surcharge of 2 hours per product launched
        during the plan year, counting products in `LAUNCHED` or `WITHDRAWN`
        status whose `launched_at` falls within `plan_year`, and counting at
        most 3 such products; subtract the rep's `prior_year_excess_hours`; and
        if the result would fall below 6 hours, the requirement is 6."

        Design: Difficulty/combinatorial_formula/firm_element_required_hours_capped_surcharge
        """
        from test_helpers import create_product_payload, TEST_USERS
        officer = TEST_USERS["officer_headers"]
        set_clock(CLOCK_DEFAULT)
        rep = create_rep(
            crd_number="CRD-CF1", role_tier="PRINCIPAL", prior_year_excess_hours=4)

        # Launch four products in 2026 (cap is 3 -> surcharge = 2 * 3 = 6)
        for i in range(1, 5):
            content = create_approved_content(
                code=f"PC-{i}", ce_category="PRODUCT", credit_hours=1.0)
            product = get_success_data(api.create_product(
                create_product_payload(content["id"], product_code=f"P{i}"),
                officer))
            get_success_data(api.launch_product(product["id"], officer))

        # Re-read rep version (plan creation OCC) then create + publish.
        rep_now = validate_success(api.get_representative(rep["id"], admin_headers))
        plan = create_plan(rep["id"], rep_now["version"], plan_year=2026)
        get_success_data(api.record_needs_analysis(
            plan["id"], create_needs_analysis_payload(), admin_headers))
        get_success_data(api.publish_plan(plan["id"], admin_headers))

        data = validate_success(api.get_firm_element_plan(plan["id"], admin_headers))
        # max(6, 16 + 2*min(4,3) - 4) = max(6, 18) = 18
        assert data["required_hours"] == pytest.approx(18, abs=0.01), (
            f"PRINCIPAL base 16 + capped surcharge 6 - excess 4 = 18, "
            f"got {data['required_hours']}")
        assert data["plan_status"] == "PLAN_PUBLISHED"

    def test_surcharge_counts_at_most_three_products(self, api, admin_headers):
        """PRD §3.6: "add a product surcharge of 2 hours per product launched
        during the plan year, counting products in `LAUNCHED` or `WITHDRAWN`
        status whose `launched_at` falls within `plan_year`, and counting at
        most 3 such products."

        Design: Difficulty/combinatorial_formula/firm_element_required_hours_capped_surcharge
        """
        from test_helpers import create_product_payload, TEST_USERS
        officer = TEST_USERS["officer_headers"]
        set_clock(CLOCK_DEFAULT)
        # RR rep with no excess: base 12. Two launched products ->
        # required = max(6, 12 + 2*min(2,3) - 0) = 16.
        rep = create_rep(crd_number="CRD-CF1b", prior_year_excess_hours=0)
        for i in range(1, 3):
            content = create_approved_content(
                code=f"PCB-{i}", ce_category="PRODUCT", credit_hours=1.0)
            product = get_success_data(api.create_product(
                create_product_payload(content["id"], product_code=f"PB{i}"),
                officer))
            get_success_data(api.launch_product(product["id"], officer))

        rep_now = validate_success(api.get_representative(rep["id"], admin_headers))
        plan = create_plan(rep["id"], rep_now["version"], plan_year=2026)
        get_success_data(api.record_needs_analysis(
            plan["id"], create_needs_analysis_payload(), admin_headers))
        get_success_data(api.publish_plan(plan["id"], admin_headers))

        data = validate_success(api.get_firm_element_plan(plan["id"], admin_headers))
        assert data["required_hours"] == pytest.approx(16, abs=0.01), (
            f"RR base 12 + 2*2 surcharge = 16, got {data['required_hours']}")

    def test_floor_binds_when_arithmetic_below_six(self, api, admin_headers):
        """PRD §3.6: "begin with the tier base, 12 hours for a rep whose
        `role_tier` is `RR` or 16 hours for `PRINCIPAL`; ... subtract the rep's
        `prior_year_excess_hours`; and if the result would fall below 6 hours,
        the requirement is 6."

        Design: Corner/calculations/c_required_hours_floor_binds
        """
        set_clock(CLOCK_DEFAULT)
        rep = create_rep(crd_number="CRD-C15", prior_year_excess_hours=9)
        # RR base 12 - excess 9 = 3 < 6 -> floor at 6 (no products launched).
        plan = create_published_plan(rep["id"], rep["version"], plan_year=2026)
        data = validate_success(api.get_firm_element_plan(plan["id"], admin_headers))
        assert data["required_hours"] == pytest.approx(6, abs=0.01), (
            f"max(6, 12 - 9) must floor at MIN_REQUIRED_HOURS = 6, "
            f"got {data['required_hours']}")


class TestFailedAttemptCreditsNoHours:
    """FAILED rows are excluded from both plan-hour variants."""

    def test_failed_attempt_excluded_from_certified(self, api, admin_headers):
        """PRD §3.6: "Both values are held at two decimal places, rounded half
        up, and `CANCELLED`, `EXPIRED`, `VOIDED`, and `FAILED` enrollments
        never contribute to either."

        Design: Corner/calculations/c_failed_attempt_credits_no_hours
        """
        set_clock(CLOCK_DEFAULT)
        rep, plan = setup_rep_with_published_plan(
            plan_year=2026, rep_overrides={"crd_number": "CRD-C18"})
        content = create_approved_content(
            code="FE-FAIL", ce_category="FIRM_ELEMENT", credit_hours=5.0)
        enr = create_enrollment(rep["id"], content_id=content["id"])
        start_enrollment(enr["id"], rep["id"])
        # Fail the attempt: 40 < 70
        resp = api.complete_enrollment(
            enr["id"], {"score": 40}, make_rep_headers(rep["id"]))
        assert validate_success(resp)["enrollment_status"] == "FAILED"

        data = validate_success(api.get_firm_element_plan(plan["id"], admin_headers))
        assert data["certified_hours"] == pytest.approx(0, abs=0.01), (
            f"FAILED rows never contribute to certified_hours, "
            f"got {data['certified_hours']}")

    def test_failed_attempt_excluded_from_projected(self, api, admin_headers):
        """PRD §3.6: "`CANCELLED`, `EXPIRED`, `VOIDED`, and `FAILED`
        enrollments never contribute to either."

        Design: Corner/calculations/c_failed_attempt_credits_no_hours
        """
        set_clock(CLOCK_DEFAULT)
        rep, plan = setup_rep_with_published_plan(
            plan_year=2026, rep_overrides={"crd_number": "CRD-C18b"})
        content = create_approved_content(
            code="FE-FAIL2", ce_category="FIRM_ELEMENT", credit_hours=5.0)
        enr = create_enrollment(rep["id"], content_id=content["id"])
        start_enrollment(enr["id"], rep["id"])
        validate_success(api.complete_enrollment(
            enr["id"], {"score": 40}, make_rep_headers(rep["id"])))

        data = validate_success(api.get_firm_element_plan(plan["id"], admin_headers))
        assert data["projected_hours"] == pytest.approx(0, abs=0.01), (
            f"after the failure the enrollment is FAILED (not IN_PROGRESS), so "
            f"projected_hours must read 0, got {data['projected_hours']}")


class TestImmediateConsistency:
    """Completion response and a same-test plan read agree (no sweep, no lag)."""

    def test_completion_response_shows_completed(self, api, admin_headers):
        """PRD §3.4: "When the `score` meets or exceeds the content's
        `min_passing_score`, the enrollment moves to `COMPLETED`:
        `attempt_count` increments by one, `last_score` records the score, and
        `completed_at` is stamped from the logical clock."
        PRD §2.10: "There are no deferred or eventually-consistent effects
        anywhere in the API."

        Design: Corner/consistency_model/c_immediate_read_after_write_completion
        """
        set_clock(CLOCK_DEFAULT)
        rep, plan = setup_rep_with_published_plan(
            plan_year=2026, rep_overrides={"crd_number": "CRD-C40"})
        content = create_approved_content(
            code="IMM-1", ce_category="FIRM_ELEMENT", credit_hours=3.0)
        enr = create_enrollment(rep["id"], content_id=content["id"])
        start_enrollment(enr["id"], rep["id"])
        resp = api.complete_enrollment(
            enr["id"], {"score": 88}, make_rep_headers(rep["id"]))
        data = validate_success(resp)
        assert data["enrollment_status"] == "COMPLETED", (
            f"completion response must already show COMPLETED, "
            f"got {data['enrollment_status']}")

    def test_immediate_plan_read_reflects_credit(self, api, admin_headers):
        """PRD §2.10: "The system applies every such side effect atomically
        within the triggering request: either the primary transition and all of
        its cascades commit together, or the request fails and nothing changes.
        There are no deferred or eventually-consistent effects anywhere in the
        API."

        Design: Corner/consistency_model/c_immediate_read_after_write_completion
        """
        set_clock(CLOCK_DEFAULT)
        rep, plan = setup_rep_with_published_plan(
            plan_year=2026, rep_overrides={"crd_number": "CRD-C40b"})
        content = create_approved_content(
            code="IMM-2", ce_category="FIRM_ELEMENT", credit_hours=3.0)
        enr = create_enrollment(rep["id"], content_id=content["id"])
        start_enrollment(enr["id"], rep["id"])
        validate_success(api.complete_enrollment(
            enr["id"], {"score": 88}, make_rep_headers(rep["id"])))

        data = validate_success(api.get_firm_element_plan(plan["id"], admin_headers))
        assert data["certified_hours"] == pytest.approx(3.0, abs=0.01), (
            f"immediate plan read must show the credited 3.0 hours with no "
            f"reconciliation pass, got {data['certified_hours']}")
