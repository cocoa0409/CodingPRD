"""Aggregate trend reporting: variants, closure metrics, category distribution.

PRD §3.8 pins the two variant inclusion rules, the closure metrics, and the
pinned rounding order of the category distribution.
"""
import pytest

from test_helpers import (
    ApiErrorId,
    get_success_data,
    set_clock,
    setup_staff_group,
    submit_report,
    accept_report_and_get_case,
    create_student,
    score_case,
    draft_plan,
    approve_plan,
    validate_error,
    validate_success,
    make_system_admin_headers,
)


def _generate_trend(api, term_code, window_start, window_end, variant):
    admin = make_system_admin_headers()
    return api.create_trend_report(
        {
            "term_code": term_code,
            "window_start": window_start,
            "window_end": window_end,
            "variant": variant,
        },
        admin,
    )


class TestTrendVariants:
    def _build_variant_population(self, api):
        """caseB created 07-20 closed 08-10 (21 days); caseA created 08-05 left
        INTAKE; caseC created 08-15 closed 08-20 (5 days)."""
        ctx = setup_staff_group()
        # --- caseB created 07-20, closed 08-10 ---
        set_clock(ctx, "2026-07-20T00:00:00Z")
        sb = create_student(external_ref="S2001", full_name="Stu B")
        rb = submit_report(ctx, sb["id"], category="SELF_HARM_RISK",
                           narrative="nb", observed_at="2026-07-19T10:00:00Z")
        _, cb = accept_report_and_get_case(ctx, rb["id"])
        score_case(ctx, cb, mode="INITIAL", rationale="low")
        pb = draft_plan(ctx, cb)
        get_success_data(api.submit_intervention_plan(pb["id"], ctx["cm_headers"]))
        approve_plan(ctx, pb["id"])
        for _ in range(3):
            k = api.list_follow_up_checkins(
                ctx["chair_headers"], params={"case_id": cb, "status": "SCHEDULED"}
            )
            kid = get_success_data(k)[0]["id"]
            get_success_data(
                api.complete_follow_up_checkin(
                    kid, {"outcome": "STABLE", "note": "ok"}, ctx["cm_headers"]
                )
            )
        # --- caseA created 08-05, stays INTAKE ---
        set_clock(ctx, "2026-08-05T00:00:00Z")
        sa = create_student(external_ref="S2002", full_name="Stu A")
        ra = submit_report(ctx, sa["id"], category="ACADEMIC_DISTRESS",
                           narrative="na", observed_at="2026-08-04T10:00:00Z")
        _, ca = accept_report_and_get_case(ctx, ra["id"])
        # --- close caseB on 08-10 ---
        set_clock(ctx, "2026-08-10T00:00:00Z")
        get_success_data(api.close_care_case(cb, ctx["chair_headers"]))
        # --- caseC created 08-15, closed 08-20 ---
        set_clock(ctx, "2026-08-15T00:00:00Z")
        sc = create_student(external_ref="S2003", full_name="Stu C")
        rc = submit_report(ctx, sc["id"], category="SUBSTANCE_CONCERN",
                           narrative="nc", observed_at="2026-08-14T10:00:00Z")
        _, cc = accept_report_and_get_case(ctx, rc["id"])
        score_case(ctx, cc, mode="INITIAL", rationale="low")
        pc = draft_plan(ctx, cc)
        get_success_data(api.submit_intervention_plan(pc["id"], ctx["cm_headers"]))
        approve_plan(ctx, pc["id"])
        for _ in range(3):
            k = api.list_follow_up_checkins(
                ctx["chair_headers"], params={"case_id": cc, "status": "SCHEDULED"}
            )
            kid = get_success_data(k)[0]["id"]
            get_success_data(
                api.complete_follow_up_checkin(
                    kid, {"outcome": "STABLE", "note": "ok"}, ctx["cm_headers"]
                )
            )
        set_clock(ctx, "2026-08-20T00:00:00Z")
        get_success_data(api.close_care_case(cc, ctx["chair_headers"]))
        return ctx

    def test_entry_cohort_counts_only_cases_created_in_window(self, api):
        """PRD §3.8: "`total_cases` counts the input set, where the variant
        decides membership: `ENTRY_COHORT` includes cases whose `created_at`
        falls inside the closed window — a cohort analysis of cases opened in
        the term — while `ACTIVE_IN_WINDOW` includes any case whose
        `created_at` is on or before `window_end` and which was either never
        closed or whose `closed_at` is on or after `window_start`, a
        service-load analysis of everything alive at any point in the term, so
        identical data yields larger totals and different rates under the
        second variant."

        Design: Difficulty/dual_variant_calc/trend_report_entry_cohort_vs_active_window_variants
        """
        self._build_variant_population(api)
        report = validate_success(
            _generate_trend(api, "2026-FALL", "2026-08-01T00:00:00Z",
                            "2026-08-31T23:59:59Z", "ENTRY_COHORT"),
            expected_status=201,
        )
        # caseA (08-05) + caseC (08-15) created in window; caseC closed in window.
        assert report["total_cases"] == 2
        assert report["closed_in_window"] == 1
        assert report["closure_rate_pct"] == pytest.approx(50.0, abs=1e-9)
        assert report["avg_days_to_close"] == pytest.approx(5.0, abs=1e-9)

    def test_active_in_window_overlaps_lifetime_and_diverges(self, api):
        """PRD §3.8: "`total_cases` counts the input set, where the variant
        decides membership: `ENTRY_COHORT` includes cases whose `created_at`
        falls inside the closed window — a cohort analysis of cases opened in
        the term — while `ACTIVE_IN_WINDOW` includes any case whose
        `created_at` is on or before `window_end` and which was either never
        closed or whose `closed_at` is on or after `window_start`, a
        service-load analysis of everything alive at any point in the term, so
        identical data yields larger totals and different rates under the
        second variant."
        PRD §3.8: "From that set, `closed_in_window` counts cases whose
        `closed_at` falls inside the closed window; `closure_rate_pct` is one
        hundred times `closed_in_window` divided by `total_cases`, rounded
        half-up to one decimal place, and is 0.0 when `total_cases` is zero;
        and `avg_days_to_close` is the mean, over the closed-in-window cases,
        of the whole-day span from `created_at` to `closed_at`, rounded half-up
        to one decimal place, 0.0 when no input-set case closed in the window."

        Design: Difficulty/dual_variant_calc/trend_report_entry_cohort_vs_active_window_variants
        """
        self._build_variant_population(api)
        report = validate_success(
            _generate_trend(api, "2026-FALL", "2026-08-01T00:00:00Z",
                            "2026-08-31T23:59:59Z", "ACTIVE_IN_WINDOW"),
            expected_status=201,
        )
        # caseB lifetime overlaps; caseB (21.0d) and caseC (5.0d) closed in window.
        assert report["total_cases"] == 3
        assert report["closed_in_window"] == 2
        assert report["closure_rate_pct"] == pytest.approx(66.7, abs=1e-9)
        assert report["avg_days_to_close"] == pytest.approx(13.0, abs=1e-9)


class TestCategoryDistributionRoundingOrder:
    def test_residual_last_category_observable(self, api):
        """PRD §3.8: "Walking the five categories in their declared order,
        `ACADEMIC_DISTRESS`, `BEHAVIORAL_THREAT`, `SELF_HARM_RISK`,
        `SUBSTANCE_CONCERN`, then `WELLBEING_GENERAL`, each of the first four
        shares is one hundred times that category's count divided by
        `total_cases`, rounded half-up to one decimal place; the last category,
        `WELLBEING_GENERAL`, receives the residual — one hundred minus the sum
        of the first four shares, rounded half-up to one decimal place — so the
        five shares always total 100.0 rather than drifting under independent
        rounding."

        Design: Difficulty/combinatorial_formula/trend_category_share_rounding_order
        """
        ctx = setup_staff_group()
        set_clock(ctx, "2026-08-02T00:00:00Z")
        for i, cat in enumerate(
            ("ACADEMIC_DISTRESS", "BEHAVIORAL_THREAT", "SELF_HARM_RISK"), start=1
        ):
            student = create_student(external_ref=f"S400{i}", full_name=f"Stu {i}")
            ctx["student"] = student
            ctx["report"] = submit_report(ctx, student["id"], category=cat,
                                          narrative=f"n{i}",
                                          observed_at=f"2026-08-01T{8 + i:02d}:00:00Z")
            _, ctx["case_id"] = accept_report_and_get_case(ctx, ctx["report"]["id"])
        report = validate_success(
            _generate_trend(api, "2026-FALL", "2026-08-01T00:00:00Z",
                            "2026-08-31T23:59:59Z", "ENTRY_COHORT"),
            expected_status=201,
        )
        assert report["total_cases"] == 3
        assert report["closed_in_window"] == 0
        assert report["closure_rate_pct"] == pytest.approx(0.0, abs=1e-9)
        assert report["avg_days_to_close"] == pytest.approx(0.0, abs=1e-9)
        dist = report["category_distribution"]
        assert dist["ACADEMIC_DISTRESS"] == pytest.approx(33.3, abs=1e-9)
        assert dist["BEHAVIORAL_THREAT"] == pytest.approx(33.3, abs=1e-9)
        assert dist["SELF_HARM_RISK"] == pytest.approx(33.3, abs=1e-9)
        assert dist["SUBSTANCE_CONCERN"] == pytest.approx(0.0, abs=1e-9)
        # Residual: 100 - (33.3*3 + 0.0) = 0.1 — pinned rounding order.
        assert dist["WELLBEING_GENERAL"] == pytest.approx(0.1, abs=1e-9)

    def test_first_four_shares_rounded_independently_before_residual(self, api):
        """PRD §3.8: "Walking the five categories in their declared order,
        `ACADEMIC_DISTRESS`, `BEHAVIORAL_THREAT`, `SELF_HARM_RISK`,
        `SUBSTANCE_CONCERN`, then `WELLBEING_GENERAL`, each of the first four
        shares is one hundred times that category's count divided by
        `total_cases`, rounded half-up to one decimal place; the last category,
        `WELLBEING_GENERAL`, receives the residual — one hundred minus the sum
        of the first four shares, rounded half-up to one decimal place — so the
        five shares always total 100.0 rather than drifting under independent
        rounding."

        Design: Difficulty/combinatorial_formula/trend_category_share_rounding_order
        """
        ctx = setup_staff_group()
        set_clock(ctx, "2026-08-02T00:00:00Z")
        # Two cases in the FIRST category only: AD=100.0, others 0.0,
        # residual WELLBEING_GENERAL = 100 - 100.0 = 0.0 (no drift on the total).
        for i in (1, 2):
            student = create_student(external_ref=f"S401{i}", full_name=f"Stu X{i}")
            ctx["student"] = student
            ctx["report"] = submit_report(ctx, student["id"], category="ACADEMIC_DISTRESS",
                                          narrative=f"n{i}",
                                          observed_at="2026-08-01T10:00:00Z")
            _, ctx["case_id"] = accept_report_and_get_case(ctx, ctx["report"]["id"])
        report = validate_success(
            _generate_trend(api, "2026-FALL", "2026-08-01T00:00:00Z",
                            "2026-08-31T23:59:59Z", "ENTRY_COHORT"),
            expected_status=201,
        )
        dist = report["category_distribution"]
        assert dist["ACADEMIC_DISTRESS"] == pytest.approx(100.0, abs=1e-9)
        assert dist["BEHAVIORAL_THREAT"] == pytest.approx(0.0, abs=1e-9)
        assert dist["SELF_HARM_RISK"] == pytest.approx(0.0, abs=1e-9)
        assert dist["SUBSTANCE_CONCERN"] == pytest.approx(0.0, abs=1e-9)
        assert dist["WELLBEING_GENERAL"] == pytest.approx(0.0, abs=1e-9)
        total = sum(dist.values())
        assert total == pytest.approx(100.0, abs=1e-9)


class TestTrendEmptyWindow:
    def test_empty_window_all_zeros(self, api, system_admin_headers):
        """PRD §3.8: "From that set, `closed_in_window` counts cases whose
        `closed_at` falls inside the closed window; `closure_rate_pct` is one
        hundred times `closed_in_window` divided by `total_cases`, rounded
        half-up to one decimal place, and is 0.0 when `total_cases` is zero;
        and `avg_days_to_close` is the mean, over the closed-in-window cases,
        of the whole-day span from `created_at` to `closed_at`, rounded half-up
        to one decimal place, 0.0 when no input-set case closed in the window."
        PRD §3.8: "When `total_cases` is zero, every share is 0.0."

        Design: Corner/calculations/trend_report_empty_window_all_zeros
        """
        report = validate_success(
            _generate_trend(api, "2026-SPRING", "2026-01-01T00:00:00Z",
                            "2026-05-31T23:59:59Z", "ENTRY_COHORT"),
            expected_status=201,
        )
        assert report["total_cases"] == 0
        assert report["closed_in_window"] == 0
        assert report["closure_rate_pct"] == pytest.approx(0.0, abs=1e-9)
        assert report["avg_days_to_close"] == pytest.approx(0.0, abs=1e-9)
        assert report["category_distribution"] == {
            "ACADEMIC_DISTRESS": 0.0,
            "BEHAVIORAL_THREAT": 0.0,
            "SELF_HARM_RISK": 0.0,
            "SUBSTANCE_CONCERN": 0.0,
            "WELLBEING_GENERAL": 0.0,
        }


class TestTrendWindowBoundary:
    def test_case_created_exactly_at_window_end_included(self, api):
        """PRD §3.8: "A `SystemAdmin` generates a trend report by naming a
        `term_code` (an academic-term label such as `2026-FALL`), an inclusive
        `window_start` and `window_end` — the end must be strictly later than
        the start, else `ERR_TREND_WINDOW_INVALID` (400) — and a `variant` that
        selects the inclusion rule."
        PRD §3.8: "`total_cases` counts the input set, where the variant
        decides membership: `ENTRY_COHORT` includes cases whose `created_at`
        falls inside the closed window — a cohort analysis of cases opened in
        the term — while `ACTIVE_IN_WINDOW` includes any case whose
        `created_at` is on or before `window_end` and which was either never
        closed or whose `closed_at` is on or after `window_start`, a
        service-load analysis of everything alive at any point in the term, so
        identical data yields larger totals and different rates under the
        second variant."

        Design: Corner/calculations/trend_window_includes_boundary_created_case
        """
        ctx = setup_staff_group()
        set_clock(ctx, "2026-08-31T23:59:59Z")
        s_in = create_student(external_ref="S0015", full_name="Stu In")
        ctx["student"] = s_in
        ctx["report"] = submit_report(ctx, s_in["id"], category="ACADEMIC_DISTRESS",
                                      narrative="in", observed_at="2026-08-31T20:00:00Z")
        _, c_in = accept_report_and_get_case(ctx, ctx["report"]["id"])
        set_clock(ctx, "2026-09-01T00:00:00Z")
        s_out = create_student(external_ref="S0016", full_name="Stu Out")
        ctx["student"] = s_out
        ctx["report"] = submit_report(ctx, s_out["id"], category="ACADEMIC_DISTRESS",
                                      narrative="out", observed_at="2026-09-01T00:00:00Z")
        _, c_out = accept_report_and_get_case(ctx, ctx["report"]["id"])
        report = validate_success(
            _generate_trend(api, "2026-FALL", "2026-08-01T00:00:00Z",
                            "2026-08-31T23:59:59Z", "ENTRY_COHORT"),
            expected_status=201,
        )
        # created_at exactly at window_end is inside the closed window;
        # window_end + 1s is excluded.
        assert report["total_cases"] == 1


class TestTrendWindowInvalid:
    def test_window_end_before_start_rejected(self, api, system_admin_headers):
        """PRD §3.8: "A `SystemAdmin` generates a trend report by naming a
        `term_code` (an academic-term label such as `2026-FALL`), an inclusive
        `window_start` and `window_end` — the end must be strictly later than
        the start, else `ERR_TREND_WINDOW_INVALID` (400) — and a `variant` that
        selects the inclusion rule."

        Design: Corner/errors/trend_window_invalid_rejected
        """
        resp = _generate_trend(api, "2026-FALL", "2026-08-31T00:00:00Z",
                               "2026-08-01T00:00:00Z", "ENTRY_COHORT")
        validate_error(resp, ApiErrorId.ERR_TREND_WINDOW_INVALID)
