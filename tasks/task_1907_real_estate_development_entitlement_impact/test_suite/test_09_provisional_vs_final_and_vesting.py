"""The two assessment variants: provisional pinned at submittal, final
recomputed under the vesting rule at approval (and on re-approval)."""
import pytest

from test_helpers import (
    V2_RATES,
    assert_assessment,
    assert_same_instant,
    create_and_adopt_fee_schedule,
    draft_and_adopt_da,
    file_in_window_appeal,
    finalize_vesting_now,
    get_application,
    get_single_assessment,
    make_decision_authority_headers,
    make_staff_reviewer_headers,
    register_authority,
    register_reviewer,
    render_decision_now,
    resolve_appeal_now,
    set_clock,
    setup_approved_application,
    setup_submitted_application,
    validate_success,
)

CREDIT_PROJECT = {
    "land_use_type": "RESIDENTIAL",
    "dwelling_units": 100,
    "affordable_units": 10,
    "floor_area_sqft": 0,
    "prior_use_basis": {"TRANSPORTATION": 20},
}
CREDIT_APPLICATION = {"improvement_credits": {"TRANSPORTATION": 50000.00}}
TEN_UNITS = {
    "land_use_type": "RESIDENTIAL",
    "dwelling_units": 10,
    "affordable_units": 0,
    "floor_area_sqft": 0,
    "prior_use_basis": {},
}


class TestProvisionalVsFinalAfterScheduleChange:
    def _setup_superseded(self, api):
        """Submitted under V1 (pinned); V2 (+10% every rate) adopted after."""
        ctx = setup_submitted_application(
            project_overrides=CREDIT_PROJECT, application_overrides=CREDIT_APPLICATION
        )
        v2 = create_and_adopt_fee_schedule(
            label="V2", effective_date="2026-08-02T00:00:00Z", rates=V2_RATES
        )
        ctx["v2"] = v2
        return ctx

    def test_provisional_total_stays_pinned_after_supersession(self, api):
        """PRD 3.3: "The application records as `pinned_fee_schedule_id` the
        `ADOPTED` schedule with the latest `effective_date` ... this pin is the
        application's vesting anchor", and the submittal produces "a
        `PROVISIONAL`-variant record whose totals are mirrored back onto the
        application as `provisional_fee_total`".
        PRD 3.1: "the act of adopting automatically moves whatever schedule was
        previously `ADOPTED` to `SUPERSEDED`, preserving it in the historical
        record".

        Design: Difficulty/dual_variant_calc/impact_fee_provisional_vs_final_after_schedule_change
        """
        ctx = self._setup_superseded(api)
        app = get_application(ctx["application"]["id"], ctx["applicant_headers"])
        assert app["pinned_fee_schedule_id"] == ctx["schedule"]["id"], (
            f"pin must hold the submittal-time schedule V1, got "
            f"{app['pinned_fee_schedule_id']}"
        )
        assert app["provisional_fee_total"] == pytest.approx(993000.00, abs=0.005), (
            f"provisional stays at pinned V1 arithmetic after V2 supersedes, "
            f"got {app['provisional_fee_total']}"
        )

        superseded = validate_success(api.get_fee_schedule(ctx["schedule"]["id"], ctx["applicant_headers"]))
        assert superseded["status"] == "SUPERSEDED"

    def test_final_total_uses_current_schedule_without_vested_da(self, api):
        """PRD 3.6: "Schedule selection for the final run follows the vesting
        rule: if a development agreement with `vesting_status` of `VESTED`
        covers the application and the logical clock is on or before its
        `vesting_expires_at` ... the final assessment still uses the pinned
        schedule; otherwise it uses the `ADOPTED` schedule with the latest
        `effective_date` at computation time, which may differ from the pinned
        schedule and produce a different `net_total` for identical project
        data."
        PRD 3.3: "Every assessment carries the `fee_schedule_id` actually
        used".

        No development agreement exists, so the final run uses V2: provisional
        993000.00 (V1) vs final 1097300.00 (V2) — a 104300.00 divergence.

        Design: Difficulty/dual_variant_calc/impact_fee_provisional_vs_final_after_schedule_change
        """
        ctx = self._setup_superseded(api)
        # Advance the same application to DECISION_PENDING, then approve.
        reviewer = register_reviewer()
        reviewer_headers = make_staff_reviewer_headers(reviewer["id"])
        ctx["reviewer"] = reviewer
        ctx["reviewer_headers"] = reviewer_headers
        authority = register_authority()
        ctx["authority"] = authority
        ctx["authority_headers"] = make_decision_authority_headers(authority["id"])

        validate_success(api.open_review(ctx["application"]["id"], reviewer_headers))
        validate_success(
            api.advance_to_decision(ctx["application"]["id"], reviewer_headers)
        )
        render_decision_now(ctx, decision="APPROVE")

        app = get_application(ctx["application"]["id"], ctx["applicant_headers"])
        assert app["provisional_fee_total"] == pytest.approx(993000.00, abs=0.005)
        assert app["final_fee_total"] == pytest.approx(1097300.00, abs=0.005), (
            f"final must recompute under V2 (+10%): 1097300.00, got "
            f"{app['final_fee_total']}"
        )
        assert app["final_fee_total"] - app["provisional_fee_total"] == pytest.approx(
            104300.00, abs=0.005
        )

        final = get_single_assessment(app["id"], reviewer_headers, variant="FINAL")
        assert_assessment(final)
        assert final["fee_schedule_id"] == ctx["v2"]["id"], (
            f"the FINAL assessment must carry the schedule actually used (V2), "
            f"got {final['fee_schedule_id']}"
        )


class TestVestingWindowInclusiveUpperBound:
    def _setup_remand(self, api, with_da: bool):
        """Approved under V1; optional vested DA whose vesting expires
        2026-08-20 (backdated adoption 2025-08-20 + 1 year); V2 adopted; the
        decision is appealed in-window and REVERSED, remanding the application
        to DECISION_PENDING."""
        ctx = setup_approved_application(project_overrides=TEN_UNITS)
        if with_da:
            da = draft_and_adopt_da(
                ctx,
                agreement_number="ORD-V",
                adoption_date="2025-08-20T00:00:00Z",
                vesting_term_years=1,
                registered_voters=100,
            )
            da = finalize_vesting_now(ctx, da["id"])
            assert da["status"] == "EFFECTIVE"
            assert da["vesting_status"] == "VESTED"
            ctx["da"] = da
        ctx["v2"] = create_and_adopt_fee_schedule(
            label="V2", effective_date="2026-08-05T00:00:00Z", rates=V2_RATES
        )
        file_in_window_appeal(ctx, grounds="procedural")
        resolve_appeal_now(ctx, ruling="REVERSED")
        app = get_application(ctx["application"]["id"], ctx["authority_headers"])
        assert app["status"] == "DECISION_PENDING", (
            f"reversal must remand to DECISION_PENDING, got {app['status']}"
        )
        ctx["application"] = app
        return ctx

    def test_final_at_vesting_expiry_instant_still_uses_pinned_schedule(self, api):
        """PRD 3.6: "if a development agreement with `vesting_status` of
        `VESTED` covers the application and the logical clock is on or before
        its `vesting_expires_at` — the boundary instant itself remains vested —
        the final assessment still uses the pinned schedule".
        PRD 3.9: "when the remanded application is approved again, its `FINAL`
        assessment is recomputed under the vesting rule then in force."
        PRD 3.8: "The agreement's `vesting_expires_at` is the `adoption_date`
        plus `vesting_term_years` years".

        Re-approval at the clock exactly equal to vesting_expires_at keeps the
        pinned V1 arithmetic (116000.00 for ten units), not V2's 127600.00.

        Design: Difficulty/resource_temporal_overlap/vesting_window_inclusive_upper_bound
        """
        ctx = self._setup_remand(api, with_da=True)
        assert_same_instant(
            ctx["da"]["vesting_expires_at"],
            "2026-08-20T00:00:00Z",
            "vesting_expires_at",
        )

        set_clock("2026-08-20T00:00:00Z")  # exactly vesting_expires_at
        render_decision_now(ctx, decision="APPROVE")

        app = get_application(ctx["application"]["id"], ctx["authority_headers"])
        assert app["final_fee_total"] == pytest.approx(116000.00, abs=0.005), (
            f"at the vested boundary instant the pinned V1 rates apply "
            f"(116000.00), got {app['final_fee_total']}"
        )

    def test_final_without_vesting_uses_current_schedule_on_reapproval(self, api):
        """PRD 3.6: "otherwise it uses the `ADOPTED` schedule with the latest
        `effective_date` at computation time".
        PRD 3.9: "when the remanded application is approved again, its `FINAL`
        assessment is recomputed under the vesting rule then in force."

        With no development agreement at all, the recomputed final uses V2:
        127600.00 for the same ten units that provisionally priced at
        116000.00 under V1.

        Design: Difficulty/resource_temporal_overlap/vesting_window_inclusive_upper_bound
        """
        ctx = self._setup_remand(api, with_da=False)
        set_clock("2026-08-20T00:00:00Z")
        render_decision_now(ctx, decision="APPROVE")

        app = get_application(ctx["application"]["id"], ctx["authority_headers"])
        assert app["final_fee_total"] == pytest.approx(127600.00, abs=0.005), (
            f"without a vested agreement the recomputation uses V2 "
            f"(127600.00), got {app['final_fee_total']}"
        )
