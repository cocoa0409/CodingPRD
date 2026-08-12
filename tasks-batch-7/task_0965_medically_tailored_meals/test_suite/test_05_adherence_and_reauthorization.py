"""Adherence variants, reauthorization adjudication gates, and unit
exhaustion (PRD §3.6, §3.5)."""
import pytest

from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    create_active_member, create_outcome_assessment, create_reauthorization,
    setup_member_with_delivery_history, setup_out_for_delivery,
    confirm_receipt, get_reauthorization, mark_delivered,
)


class TestAdherenceDualVariant:
    def _setup(self):
        """4 DELIVERED + 1 FAILED deliveries in the trailing 84-day window;
        member confirms receipt of the first three delivered parcels."""
        ctx = setup_member_with_delivery_history(
            4, 1,
            member_overrides={"full_name": "M Two", "payer_member_id": "W-200",
                              "income_fpl_percent": 120})
        member_id = ctx["member"]["id"]
        for delivery in ctx["deliveries_delivered"][:3]:
            confirm_receipt(delivery["id"], member_id)
        return ctx

    def test_summary_reports_divergent_adherence_variants(
            self, api, dietitian_headers):
        """PRD §3.6: "Because the two variants use different denominators they
        genuinely diverge: four delivered and one failed delivery with three
        confirmations yields 80.00 delivered-based but 75.00 confirmed-based."

        Design: Difficulty/dual_variant_calc/adherence_delivered_vs_confirmed_variant
        """
        ctx = self._setup()
        summary = validate_success(
            api.get_member_summary(ctx["member"]["id"], dietitian_headers))
        assert summary["adherence_delivered_pct"] == pytest.approx(80.00), \
            "4 DELIVERED over 4 DELIVERED + 1 FAILED"
        assert summary["adherence_confirmed_pct"] == pytest.approx(75.00), \
            "3 confirmed over 4 DELIVERED"
        assert summary["adherence_delivered_pct"] != \
            summary["adherence_confirmed_pct"]

    def test_member_read_carries_both_variants_and_cycle_fulfilled(
            self, api, dietitian_headers):
        """PRD §3.6: "The delivered-based variant gates reauthorization
        approval; both variants appear on the member read and the member
        summary."
        PRD §3.5: "If the delivery's cycle now has all deliveries terminal with
        at least one `DELIVERED`, the cycle flips automatically to `FULFILLED`."

        Design: Difficulty/dual_variant_calc/adherence_delivered_vs_confirmed_variant
        """
        ctx = self._setup()
        member = validate_success(api.get_member(ctx["member"]["id"],
                                                 dietitian_headers))
        assert member["adherence_delivered_pct"] == pytest.approx(80.00)
        assert member["adherence_confirmed_pct"] == pytest.approx(75.00)
        cycle = validate_success(api.get_menu_cycle(ctx["cycle"]["id"],
                                                    dietitian_headers))
        assert cycle["status"] == "FULFILLED"


class TestAdherenceBoundaryAtEighty:
    def _setup(self):
        """Member at exactly 80.00 delivered-based adherence (4 of 5), with a
        second PENDING reauthorization awaiting adjudication."""
        ctx = setup_member_with_delivery_history(
            4, 1,
            member_overrides={"full_name": "M Eleven",
                              "payer_member_id": "W-210",
                              "income_fpl_percent": 120})
        a2 = create_reauthorization(ctx["member"]["id"], authorized_units=8,
                                    max_amount_cents=400_000,
                                    start_date="2026-05-01",
                                    end_date="2026-12-31")
        ctx["second_authorization"] = a2
        return ctx

    def test_exactly_80_percent_approves(self, api, payer_reviewer_headers,
                                         dietitian_headers):
        """PRD §3.6: "The member's `adherence_delivered_pct` must be at least
        80.00; a member below that floor is rejected with
        `ERR_ADHERENCE_BELOW_THRESHOLD`."

        Design: Difficulty/boundary_precision_check/adherence_exactly_80_passes_reauthorization
        """
        ctx = self._setup()
        member = validate_success(api.get_member(ctx["member"]["id"],
                                                 dietitian_headers))
        assert member["adherence_delivered_pct"] == pytest.approx(80.00)
        resp = api.approve_reauthorization(ctx["second_authorization"]["id"],
                                           "AUTH-210B", payer_reviewer_headers)
        approved = validate_success(resp)
        assert approved["status"] == "APPROVED", \
            "the >= 80.00 gate is inclusive, so exactly 80.00 must approve"
        assert approved["authorization_number"] == "AUTH-210B"

    def test_approval_records_number_and_bumps_version(
            self, api, payer_reviewer_headers):
        """PRD §3.6: "A successful approval records the payer's
        `authorization_number` from the request, moves the reauthorization to
        `APPROVED`, and increments its `version`."

        Design: Difficulty/boundary_precision_check/adherence_exactly_80_passes_reauthorization
        """
        ctx = self._setup()
        a2 = ctx["second_authorization"]
        approved = validate_success(
            api.approve_reauthorization(a2["id"], "AUTH-210B",
                                        payer_reviewer_headers))
        assert approved["status"] == "APPROVED"
        assert approved["authorization_number"] == "AUTH-210B"
        assert approved["version"] == a2["version"] + 1


class TestAuthorizationAutoExhaustion:
    def test_reauthorization_auto_exhausted_at_full_utilization(
            self, api, driver_headers):
        """PRD §3.5: "if `used_units` thereby reaches `authorized_units`, the
        authorization flips automatically to `EXHAUSTED`."

        Design: Corner/state_machines/reauthorization_auto_exhausted_at_full_utilization
        """
        ctx = setup_out_for_delivery(
            member_overrides={"full_name": "S Seven", "payer_member_id": "W-S7"},
            auth_overrides={"authorized_units": 1},
            route_overrides={"driver_id": "drv-s7"})
        validate_success(api.mark_delivered(ctx["delivery"]["id"], driver_headers))
        auth = get_reauthorization(ctx["authorization"]["id"])
        assert auth["used_units"] == 1
        assert auth["reserved_units"] == 0
        assert auth["status"] == "EXHAUSTED", \
            "full utilization auto-transitions APPROVED -> EXHAUSTED"
        assert auth["available_units"] == 0


class TestAdherenceBelowThreshold:
    def test_error_adherence_below_threshold(self, api, payer_reviewer_headers,
                                             dietitian_headers):
        """PRD §3.6: "The member's `adherence_delivered_pct` must be at least
        80.00; a member below that floor is rejected with
        `ERR_ADHERENCE_BELOW_THRESHOLD`."

        Design: Corner/errors/error_adherence_below_threshold
        """
        ctx = setup_member_with_delivery_history(
            3, 2,
            member_overrides={"full_name": "N Three",
                              "payer_member_id": "W-N3",
                              "income_fpl_percent": 120})
        member = validate_success(api.get_member(ctx["member"]["id"],
                                                 dietitian_headers))
        assert member["adherence_delivered_pct"] == pytest.approx(60.00), \
            "3 DELIVERED over 3 DELIVERED + 2 FAILED"
        a2 = create_reauthorization(ctx["member"]["id"], authorized_units=8,
                                    max_amount_cents=400_000,
                                    start_date="2026-05-01",
                                    end_date="2026-12-31")
        resp = api.approve_reauthorization(a2["id"], "AUTH-N3B",
                                           payer_reviewer_headers)
        validate_error(resp, ApiErrorId.ERR_ADHERENCE_BELOW_THRESHOLD)
        a2_after = get_reauthorization(a2["id"])
        assert a2_after["status"] == "PENDING"


class TestOutcomeAssessmentRecency:
    def test_error_outcome_assessment_stale(self, api, payer_reviewer_headers):
        """PRD §3.6: "the member must have an outcome assessment whose
        `assessed_at` falls within the trailing 90 days relative to the current
        logical date; without one, approval is rejected with
        `ERR_OUTCOME_ASSESSMENT_STALE`."

        Design: Corner/errors/error_outcome_assessment_stale
        """
        member = create_active_member(full_name="N Four",
                                      payer_member_id="W-N4")
        create_outcome_assessment(member["id"], assessed_at="2025-12-01",
                                  weight_kg=80.0, hba1c_pct=7.5)
        auth = create_reauthorization(member["id"])
        resp = api.approve_reauthorization(auth["id"], "AUTH-N4",
                                           payer_reviewer_headers)
        validate_error(resp, ApiErrorId.ERR_OUTCOME_ASSESSMENT_STALE)
        auth_after = get_reauthorization(auth["id"])
        assert auth_after["status"] == "PENDING"
