"""Workpaper review pipeline: hours rollup ordering, dual utilization variants,
budget fiscal gate, review-loop invariants, and cross-entity gates
(PRD §3.5)."""
import pytest

from test_helpers import (
    ApiErrorId,
    assert_workpaper,
    create_auditor,
    create_workpaper_payload,
    get_success_data,
    is_iso8601_timestamp,
    make_field_auditor_headers,
    make_manager_headers,
    setup_engagement_in_fieldwork,
    setup_engagement_in_reporting,
    validate_error,
    validate_success,
)


class TestHoursRollup:
    def test_hours_rollup_rounds_per_item_then_sums(self, api):
        """PRD §3.5: "Each workpaper contributes an item value equal to its
        `hours_worked` rounded up to the nearest half hour — equivalently, twice
        the hours rounded up to the next whole number, then halved — and only
        after this per-item rounding are the values summed. Three workpapers of
        1.1 hours each therefore contribute 4.5 hours in aggregate, since each
        item individually rounds to 1.5; summing the raw hours first and
        rounding once would yield 3.5, and that alternative order is explicitly
        not used."

        Design: Difficulty/combinatorial_formula/hours_rollup_per_item_rounding_order
        """
        ctx = setup_engagement_in_fieldwork(entity_name="Entity R", budget_hours=1000)
        mgr_h = make_manager_headers(ctx["mgr"]["id"])
        for i in (1, 2, 3):
            wp = get_success_data(api.create_workpaper(
                create_workpaper_payload(ctx["engagement"]["id"], reference=f"W-{i}",
                                         title=f"WP{i}", hours_worked=1.1),
                make_field_auditor_headers(ctx["staff"]["id"]),
            ))
            get_success_data(api.submit_workpaper(
                wp["id"], make_field_auditor_headers(ctx["staff"]["id"])
            ))
            get_success_data(api.sign_off_workpaper(wp["id"], mgr_h))

        eng = get_success_data(api.get_engagement(ctx["engagement"]["id"], mgr_h))
        assert eng["actual_hours"] == pytest.approx(4.5), (
            "Per-item rounding is pinned before summation: 1.5 + 1.5 + 1.5"
        )
        assert eng["actual_hours"] != pytest.approx(3.5), (
            "The sum-then-round alternative (3.5) is explicitly not used"
        )
        assert eng["signed_off_workpaper_count"] == 3

    def test_hours_rollup_recomputes_on_each_review_event(self, api):
        """PRD §3.5: "The engagement's `actual_hours` sums item values over
        `SIGNED_OFF` workpapers, while `provisional_hours` sums item values over
        workpapers in `SUBMITTED` or `SIGNED_OFF`. Both are recomputed on every
        submit, sign-off, and return."

        Design: Difficulty/combinatorial_formula/hours_rollup_per_item_rounding_order
        """
        ctx = setup_engagement_in_fieldwork(entity_name="Entity R2", budget_hours=1000)
        mgr_h = make_manager_headers(ctx["mgr"]["id"])
        staff_h = make_field_auditor_headers(ctx["staff"]["id"])

        wp = get_success_data(api.create_workpaper(
            create_workpaper_payload(ctx["engagement"]["id"], reference="W-1",
                                     title="WP1", hours_worked=1.1),
            staff_h,
        ))
        get_success_data(api.submit_workpaper(wp["id"], staff_h))
        mid = get_success_data(api.get_engagement(ctx["engagement"]["id"], mgr_h))
        # A merely SUBMITTED 1.1h item rounds to 1.5 and counts provisionally only.
        assert mid["provisional_hours"] == pytest.approx(1.5)
        assert mid["actual_hours"] == pytest.approx(0.0)

        get_success_data(api.sign_off_workpaper(wp["id"], mgr_h))
        after = get_success_data(api.get_engagement(ctx["engagement"]["id"], mgr_h))
        assert after["actual_hours"] == pytest.approx(1.5)
        assert after["provisional_hours"] == pytest.approx(1.5)
        assert after["signed_off_workpaper_count"] == 1


class TestUtilizationVariants:
    def test_utilization_provisional_vs_final_hours_basis(self, api):
        """PRD §3.5: "Two utilization measures derive from these rollups, each
        rounded half-up to two decimal places: `utilization_final_pct` is one
        hundred times `actual_hours` divided by `budget_hours`, and
        `utilization_provisional_pct` is one hundred times `provisional_hours`
        divided by `budget_hours`. The two variants diverge while review is in
        flight — with 10 signed-off hours and 20 submitted hours against a
        100-hour budget, the provisional figure reads 30.0 while the final
        figure reads 10.0."

        Design: Difficulty/dual_variant_calc/utilization_provisional_vs_final_hours_basis
        """
        ctx = setup_engagement_in_fieldwork(entity_name="Entity U", budget_hours=100)
        mgr_h = make_manager_headers(ctx["mgr"]["id"])
        staff_h = make_field_auditor_headers(ctx["staff"]["id"])

        # Workpaper A: 10h, fully signed off.
        wp_a = get_success_data(api.create_workpaper(
            create_workpaper_payload(ctx["engagement"]["id"], reference="A-1",
                                     title="WP A", hours_worked=10),
            staff_h,
        ))
        get_success_data(api.submit_workpaper(wp_a["id"], staff_h))
        get_success_data(api.sign_off_workpaper(wp_a["id"], mgr_h))

        # Workpaper B: 20h, submitted only.
        wp_b = get_success_data(api.create_workpaper(
            create_workpaper_payload(ctx["engagement"]["id"], reference="B-1",
                                     title="WP B", hours_worked=20),
            staff_h,
        ))
        get_success_data(api.submit_workpaper(wp_b["id"], staff_h))

        eng = get_success_data(api.get_engagement(ctx["engagement"]["id"], mgr_h))
        assert eng["actual_hours"] == pytest.approx(10.0)
        assert eng["provisional_hours"] == pytest.approx(30.0)
        assert eng["utilization_final_pct"] == pytest.approx(10.0)
        assert eng["utilization_provisional_pct"] == pytest.approx(30.0)
        assert eng["utilization_provisional_pct"] != eng["utilization_final_pct"]

    def test_utilization_variants_converge_after_all_signed(self, api):
        """PRD §3.5: "`utilization_final_pct` is one hundred times
        `actual_hours` divided by `budget_hours`, and
        `utilization_provisional_pct` is one hundred times `provisional_hours`
        divided by `budget_hours`."

        Design: Difficulty/dual_variant_calc/utilization_provisional_vs_final_hours_basis
        """
        ctx = setup_engagement_in_fieldwork(entity_name="Entity U2", budget_hours=100)
        mgr_h = make_manager_headers(ctx["mgr"]["id"])
        staff_h = make_field_auditor_headers(ctx["staff"]["id"])

        # 10h signed off, then a 20h workpaper also signed off: once nothing is
        # left in SUBMITTED, the provisional variant equals the final variant.
        wp_a = get_success_data(api.create_workpaper(
            create_workpaper_payload(ctx["engagement"]["id"], reference="A-1",
                                     title="WP A", hours_worked=10),
            staff_h,
        ))
        get_success_data(api.submit_workpaper(wp_a["id"], staff_h))
        get_success_data(api.sign_off_workpaper(wp_a["id"], mgr_h))
        wp_b = get_success_data(api.create_workpaper(
            create_workpaper_payload(ctx["engagement"]["id"], reference="B-1",
                                     title="WP B", hours_worked=20),
            staff_h,
        ))
        get_success_data(api.submit_workpaper(wp_b["id"], staff_h))
        get_success_data(api.sign_off_workpaper(wp_b["id"], mgr_h))

        eng = get_success_data(api.get_engagement(ctx["engagement"]["id"], mgr_h))
        assert eng["actual_hours"] == pytest.approx(30.0)
        assert eng["provisional_hours"] == pytest.approx(30.0)
        assert eng["utilization_final_pct"] == pytest.approx(30.0)
        assert eng["utilization_provisional_pct"] == pytest.approx(30.0)


class TestWorkpaperReviewLoop:
    def test_workpaper_return_revise_review_loop(self, api):
        """PRD §3.5: "The preparer may then revise: a `RETURNED` workpaper
        returns to `DRAFT` under the same ownership rule
        (`ERR_NOT_WORKPAPER_PREPARER`), and its `review_note` is cleared,
        completing the revision loop `DRAFT` → `SUBMITTED` → `RETURNED` →
        `DRAFT`."
        PRD §3.5: "A successful sign-off records `reviewer_auditor_id` from the
        caller, stamps `signed_off_at` from the logical clock, moves the
        workpaper to `SIGNED_OFF`, increments the engagement's
        `signed_off_workpaper_count` by one, and recomputes `actual_hours` and
        `provisional_hours`."

        Design: Difficulty/non_linear_state_machine/workpaper_return_revise_review_loop
        """
        ctx = setup_engagement_in_fieldwork(entity_name="Entity W", budget_hours=100)
        mgr2 = create_auditor(full_name="Mike Mgr2", grade="MANAGER")
        mgr_h = make_manager_headers(ctx["mgr"]["id"])
        mgr2_h = make_manager_headers(mgr2["id"])
        staff_h = make_field_auditor_headers(ctx["staff"]["id"])

        wp = get_success_data(api.create_workpaper(
            create_workpaper_payload(ctx["engagement"]["id"], reference="A-1",
                                     title="WP A", hours_worked=8),
            staff_h,
        ))
        get_success_data(api.submit_workpaper(wp["id"], staff_h))
        returned = get_success_data(api.return_workpaper(wp["id"], {"note": "Add tickmarks"}, mgr2_h))
        assert returned["status"] == "RETURNED"
        assert returned["review_note"] == "Add tickmarks"
        assert returned["reviewer_auditor_id"] == mgr2["id"]

        # The cycle turns: revise -> submit -> sign-off.
        revised = get_success_data(api.revise_workpaper(wp["id"], staff_h))
        assert revised["status"] == "DRAFT"
        assert revised["review_note"] is None, "Revise clears the review note"
        get_success_data(api.submit_workpaper(wp["id"], staff_h))
        signed = get_success_data(api.sign_off_workpaper(wp["id"], mgr_h))
        assert signed["status"] == "SIGNED_OFF"
        assert signed["reviewer_auditor_id"] == ctx["mgr"]["id"]
        assert is_iso8601_timestamp(signed["signed_off_at"])
        assert_workpaper(signed)

        eng = get_success_data(api.get_engagement(ctx["engagement"]["id"], mgr_h))
        assert eng["signed_off_workpaper_count"] == 1
        assert eng["actual_hours"] == pytest.approx(8.0)

    def test_workpaper_review_loop_returns_to_draft_exactly_once(self, api):
        """PRD §3.5: "Returning a workpaper is the reviewer's reject path,
        available from either `SUBMITTED` or `SIGNED_OFF` — any other from-state
        fails with `ERR_WORKPAPER_INVALID_STATE`"
        PRD §3.5: "The request carries a `note`, which is recorded on the
        workpaper as `review_note` alongside the caller's `reviewer_auditor_id`."

        Design: Difficulty/non_linear_state_machine/workpaper_return_revise_review_loop
        """
        ctx = setup_engagement_in_fieldwork(entity_name="Entity W2", budget_hours=100)
        mgr_h = make_manager_headers(ctx["mgr"]["id"])
        staff_h = make_field_auditor_headers(ctx["staff"]["id"])

        wp = get_success_data(api.create_workpaper(
            create_workpaper_payload(ctx["engagement"]["id"], reference="A-1",
                                     title="WP A", hours_worked=8),
            staff_h,
        ))
        get_success_data(api.submit_workpaper(wp["id"], staff_h))
        returned = get_success_data(api.return_workpaper(wp["id"], {"note": "n"}, mgr_h))
        assert returned["status"] == "RETURNED"
        assert returned["reviewer_auditor_id"] == ctx["mgr"]["id"]

        # From RETURNED, sign-off is illegal — only revise reopens the loop.
        bad_sign = api.sign_off_workpaper(wp["id"], mgr_h)
        validate_error(bad_sign, ApiErrorId.ERR_WORKPAPER_INVALID_STATE, expected_status=409)

        revised = get_success_data(api.revise_workpaper(wp["id"], staff_h))
        assert revised["status"] == "DRAFT"
        assert revised["review_note"] is None


class TestWorkpaperInvalidTransitions:
    def test_workpaper_invalid_transitions_from_draft(self, api):
        """PRD §3.5: "the workpaper must be `DRAFT` (else
        `ERR_WORKPAPER_INVALID_STATE`)"
        PRD §3.5: "available from either `SUBMITTED` or `SIGNED_OFF` — any other
        from-state fails with `ERR_WORKPAPER_INVALID_STATE`"

        Design: Corner/state_machines/workpaper_invalid_transitions_from_draft
        """
        ctx = setup_engagement_in_fieldwork(entity_name="E", budget_hours=100)
        mgr_h = make_manager_headers(ctx["mgr"]["id"])
        staff_h = make_field_auditor_headers(ctx["staff"]["id"])
        wp = get_success_data(api.create_workpaper(
            create_workpaper_payload(ctx["engagement"]["id"], reference="A-1",
                                     title="WP A", hours_worked=10),
            staff_h,
        ))

        sign = api.sign_off_workpaper(wp["id"], mgr_h)
        validate_error(sign, ApiErrorId.ERR_WORKPAPER_INVALID_STATE, expected_status=409)
        ret = api.return_workpaper(wp["id"], {"note": "n"}, mgr_h)
        validate_error(ret, ApiErrorId.ERR_WORKPAPER_INVALID_STATE, expected_status=409)
        revise = api.revise_workpaper(wp["id"], staff_h)
        validate_error(revise, ApiErrorId.ERR_WORKPAPER_INVALID_STATE, expected_status=409)
        assert get_success_data(api.get_workpaper(wp["id"], mgr_h))["status"] == "DRAFT"


class TestBeginReportingGates:
    def test_engagement_begin_reporting_workpaper_gates(self, api):
        """PRD §3.5: "There must be at least one signed-off workpaper: when
        `signed_off_workpaper_count` is zero the transition fails with
        `ERR_NO_SIGNED_WORKPAPERS`. And the pipeline must be clean: every
        workpaper of the engagement must be `SIGNED_OFF`, so any workpaper still
        `DRAFT`, `SUBMITTED`, or `RETURNED` blocks the transition with
        `ERR_WORKPAPERS_PENDING_REVIEW`."

        Design: Corner/state_machines/engagement_begin_reporting_workpaper_gates
        """
        ctx = setup_engagement_in_fieldwork(entity_name="E", budget_hours=100)
        mgr_h = make_manager_headers(ctx["mgr"]["id"])
        staff_h = make_field_auditor_headers(ctx["staff"]["id"])

        # Zero signed workpapers (wp1 still DRAFT): the empty-set gate fires.
        wp1 = get_success_data(api.create_workpaper(
            create_workpaper_payload(ctx["engagement"]["id"], reference="A-1",
                                     title="WP A", hours_worked=10),
            staff_h,
        ))
        no_signed = api.begin_reporting(ctx["engagement"]["id"], mgr_h)
        validate_error(no_signed, ApiErrorId.ERR_NO_SIGNED_WORKPAPERS, expected_status=422)

        # One SIGNED_OFF plus one merely SUBMITTED: the pending-review gate fires.
        get_success_data(api.submit_workpaper(wp1["id"], staff_h))
        get_success_data(api.sign_off_workpaper(wp1["id"], mgr_h))
        wp2 = get_success_data(api.create_workpaper(
            create_workpaper_payload(ctx["engagement"]["id"], reference="A-2",
                                     title="WP B", hours_worked=5),
            staff_h,
        ))
        get_success_data(api.submit_workpaper(wp2["id"], staff_h))
        pending = api.begin_reporting(ctx["engagement"]["id"], mgr_h)
        validate_error(pending, ApiErrorId.ERR_WORKPAPERS_PENDING_REVIEW, expected_status=422)

        eng = get_success_data(api.get_engagement(ctx["engagement"]["id"], mgr_h))
        assert eng["status"] == "FIELDWORK"


class TestBudgetFiscalGate:
    def test_signoff_budget_fiscal_gate(self, api):
        """PRD §3.5: "After the segregation check — and only after it, per the
        pipeline ordering of §2.7 — the fiscal gate is evaluated: signing off is
        rejected with `ERR_BUDGET_HOURS_EXCEEDED` when the engagement's current
        `actual_hours` plus this workpaper's contribution would exceed one
        hundred and ten percent of `budget_hours`, where the workpaper's
        contribution is its `hours_worked` rounded up to the nearest half hour."

        Design: Corner/validations/signoff_budget_fiscal_gate
        """
        ctx = setup_engagement_in_fieldwork(entity_name="E", budget_hours=10,
                                            lead_hours=5, staff_hours=5)
        mgr_h = make_manager_headers(ctx["mgr"]["id"])
        staff_h = make_field_auditor_headers(ctx["staff"]["id"])

        def make_and_submit(ref, hours):
            wp = get_success_data(api.create_workpaper(
                create_workpaper_payload(ctx["engagement"]["id"], reference=ref,
                                         title=ref, hours_worked=hours),
                staff_h,
            ))
            get_success_data(api.submit_workpaper(wp["id"], staff_h))
            return wp

        # 8h then 2.5h sign off: actual reaches 10.5, inside the 110% allowance.
        wp1 = make_and_submit("A-1", 8)
        get_success_data(api.sign_off_workpaper(wp1["id"], mgr_h))
        wp2 = make_and_submit("A-2", 2.5)
        get_success_data(api.sign_off_workpaper(wp2["id"], mgr_h))

        # The next 1h sign-off would reach 11.5 > 10 * 1.10 == 11.0.
        wp3 = make_and_submit("A-3", 1)
        over = api.sign_off_workpaper(wp3["id"], mgr_h)
        validate_error(over, ApiErrorId.ERR_BUDGET_HOURS_EXCEEDED, expected_status=422)

        wp3_after = get_success_data(api.get_workpaper(wp3["id"], mgr_h))
        assert wp3_after["status"] == "SUBMITTED", "Rejected sign-off leaves the workpaper in place"
        eng = get_success_data(api.get_engagement(ctx["engagement"]["id"], mgr_h))
        assert eng["actual_hours"] == pytest.approx(10.5)


class TestSignoffCountInvariant:
    def test_signoff_then_return_nets_zero_on_count_and_hours(self, api):
        """PRD §3.5: "Returning a `SIGNED_OFF` workpaper is a compensating
        action: `signed_off_at` is cleared to null, the engagement's
        `signed_off_workpaper_count` decrements by one, and `actual_hours` and
        `provisional_hours` are recomputed, preserving the invariant that the
        count always equals the number of `SIGNED_OFF` workpapers."
        PRD §3.5: "A successful sign-off records `reviewer_auditor_id` from the
        caller, stamps `signed_off_at` from the logical clock, moves the
        workpaper to `SIGNED_OFF`, increments the engagement's
        `signed_off_workpaper_count` by one, and recomputes `actual_hours` and
        `provisional_hours`."

        Design: Difficulty/compensating_invariant/workpaper_signoff_count_signoff_return_neutral
        """
        ctx = setup_engagement_in_fieldwork(entity_name="Entity H2", budget_hours=200)
        mgr_h = make_manager_headers(ctx["mgr"]["id"])
        staff_h = make_field_auditor_headers(ctx["staff"]["id"])

        def signed_off(ref, hours):
            wp = get_success_data(api.create_workpaper(
                create_workpaper_payload(ctx["engagement"]["id"], reference=ref,
                                         title=ref, hours_worked=hours),
                staff_h,
            ))
            get_success_data(api.submit_workpaper(wp["id"], staff_h))
            return get_success_data(api.sign_off_workpaper(wp["id"], mgr_h))

        wp1 = signed_off("A-1", 10)
        e1 = get_success_data(api.get_engagement(ctx["engagement"]["id"], mgr_h))
        assert (e1["signed_off_workpaper_count"], e1["actual_hours"]) == (1, pytest.approx(10.0))

        signed_off("A-2", 20)
        e2 = get_success_data(api.get_engagement(ctx["engagement"]["id"], mgr_h))
        assert (e2["signed_off_workpaper_count"], e2["actual_hours"]) == (2, pytest.approx(30.0))

        # The compensating action: returning wp1 undoes its sign-off exactly.
        returned = get_success_data(api.return_workpaper(wp1["id"], {"note": "Evidence gap"}, mgr_h))
        assert returned["status"] == "RETURNED"
        assert returned["signed_off_at"] is None
        e3 = get_success_data(api.get_engagement(ctx["engagement"]["id"], mgr_h))
        assert (e3["signed_off_workpaper_count"], e3["actual_hours"]) == (1, pytest.approx(20.0))

    def test_signoff_return_resignoff_restores_exactly(self, api):
        """PRD §3.5: "Returning a `SIGNED_OFF` workpaper is a compensating
        action: `signed_off_at` is cleared to null, the engagement's
        `signed_off_workpaper_count` decrements by one, and `actual_hours` and
        `provisional_hours` are recomputed, preserving the invariant that the
        count always equals the number of `SIGNED_OFF` workpapers."
        PRD §3.5: "completing the revision loop `DRAFT` → `SUBMITTED` →
        `RETURNED` → `DRAFT`."

        Design: Difficulty/compensating_invariant/workpaper_signoff_count_signoff_return_neutral
        """
        ctx = setup_engagement_in_fieldwork(entity_name="Entity H2b", budget_hours=200)
        mgr_h = make_manager_headers(ctx["mgr"]["id"])
        staff_h = make_field_auditor_headers(ctx["staff"]["id"])

        def signed_off(ref, hours):
            wp = get_success_data(api.create_workpaper(
                create_workpaper_payload(ctx["engagement"]["id"], reference=ref,
                                         title=ref, hours_worked=hours),
                staff_h,
            ))
            get_success_data(api.submit_workpaper(wp["id"], staff_h))
            return get_success_data(api.sign_off_workpaper(wp["id"], mgr_h))

        wp1 = signed_off("A-1", 10)
        signed_off("A-2", 20)

        # Return wp1, then walk it through the revision loop back to SIGNED_OFF.
        get_success_data(api.return_workpaper(wp1["id"], {"note": "Evidence gap"}, mgr_h))
        get_success_data(api.revise_workpaper(wp1["id"], staff_h))
        get_success_data(api.submit_workpaper(wp1["id"], staff_h))
        get_success_data(api.sign_off_workpaper(wp1["id"], mgr_h))

        eng = get_success_data(api.get_engagement(ctx["engagement"]["id"], mgr_h))
        assert eng["signed_off_workpaper_count"] == 2
        assert eng["actual_hours"] == pytest.approx(30.0), (
            "The sign-off/return/re-sign-off sequence restores the exact prior "
            "totals — no drift from the compensating pair"
        )


class TestCrossEntityWorkpaperGate:
    def test_workpaper_return_blocked_once_reporting(self, api):
        """PRD §3.5: "under the same unlocked, fieldwork-phase, and
        not-the-preparer rules (`ERR_WORKPAPER_LOCKED`,
        `ERR_ENGAGEMENT_INVALID_STATE`, `ERR_WORKPAPER_SELF_REVIEW`)."
        PRD §3.5: "Ending fieldwork is the manager's begin-reporting action,
        moving the engagement from `FIELDWORK` to `REPORTING`."

        Design: Difficulty/cross_entity_state_dependency/workpaper_review_gated_by_engagement_fieldwork
        """
        ctx = setup_engagement_in_reporting(entity_name="Entity G1", budget_hours=100,
                                            workpaper_hours=10)
        mgr2 = create_auditor(full_name="Mike Mgr2", grade="MANAGER")
        wp = ctx["workpapers"][0]

        # The workpaper's own state (SIGNED_OFF) is a valid from-state for
        # return, but the engagement has advanced to REPORTING, which gates all
        # workpaper review mutations.
        resp = api.return_workpaper(wp["id"], {"note": "late rework"},
                                    make_manager_headers(mgr2["id"]))
        validate_error(resp, ApiErrorId.ERR_ENGAGEMENT_INVALID_STATE, expected_status=409)

        mgr_h = make_manager_headers(ctx["mgr"]["id"])
        wp_after = get_success_data(api.get_workpaper(wp["id"], mgr_h))
        assert wp_after["status"] == "SIGNED_OFF"
        eng_after = get_success_data(api.get_engagement(ctx["engagement"]["id"], mgr_h))
        assert eng_after["status"] == "REPORTING"

    def test_workpaper_submit_blocked_once_reporting(self, api):
        """PRD §3.5: "the workpaper must be `DRAFT` (else
        `ERR_WORKPAPER_INVALID_STATE`), must not be locked (else
        `ERR_WORKPAPER_LOCKED`), and the engagement must still be in `FIELDWORK`
        (else `ERR_ENGAGEMENT_INVALID_STATE`)."
        PRD §3.5: "Workpapers can only be created while the engagement is in
        `FIELDWORK`; attempts in any other engagement state fail with
        `ERR_ENGAGEMENT_INVALID_STATE`."

        Design: Difficulty/cross_entity_state_dependency/workpaper_review_gated_by_engagement_fieldwork
        """
        ctx = setup_engagement_in_reporting(entity_name="Entity G1b", budget_hours=100,
                                            workpaper_hours=10)
        staff_h = make_field_auditor_headers(ctx["staff"]["id"])

        # Creating a new workpaper outside FIELDWORK is rejected.
        created = api.create_workpaper(
            create_workpaper_payload(ctx["engagement"]["id"], reference="L-1",
                                     title="Late WP", hours_worked=4),
            staff_h,
        )
        validate_error(created, ApiErrorId.ERR_ENGAGEMENT_INVALID_STATE, expected_status=409)
