"""Residual obligations: reporting, snapshot pinning, calculation, dispute loop."""
from test_helpers import (
    ACCOUNTANT,
    AUDITOR,
    CLERK,
    SUPERVISOR,
    ApiErrorId,
    assert_residual_obligation,
    create_calculated_residual,
    create_draft_engagement,
    create_performer,
    create_ratified_agreement,
    create_residual,
    create_residual_obligation_payload,
    create_shooting_production,
    get_residual,
    get_success_data,
    list_all_residuals,
    setup_standard,
    validate_error,
)


class TestResidualReporting:
    def test_provisional_amount_and_snapshot_pinned_at_creation(self, api):
        """PRD §3.9: "Finally, the server computes `provisional_amount_cents` as
        the engagement's tier `day_rate_cents` multiplied by the pinned `base_pct`,
        rounded half-up to integer cents — the tier day rate stands in as the
        estimate base until actual receipts are known."
        PRD §3.9: "At creation, the server pins `base_pct` as a snapshot of the
        agreement's `residual_base_pct_by_market` entry for the chosen market".
        PRD §3.9: "The server also assigns `window_sequence`: the 1-based ordinal
        of this window among the engagement's obligations for the same
        `reuse_market`, ordered by `window_start` ascending with ties broken by
        `created_at` ascending."

        Design: Difficulty/dual_variant_calc/residual_provisional_vs_final_by_market
        """
        ctx = setup_standard()
        res = create_residual(ctx["eng"]["id"])
        assert_residual_obligation(res)
        assert res["status"] == "REPORTED"
        assert res["provisional_amount_cents"] == 4500, (
            "round_half_up(100000 x 0.045)")
        assert res["base_pct"] == 0.045
        assert res["window_sequence"] == 1

    def test_calculate_computes_final_from_receipts(self, api):
        """PRD §3.9: "Calculation runs the final residual computation:
        `final_amount_cents` is the `reported_gross_receipts_cents` multiplied by
        the pinned `base_pct` and then by a window discount, with the final amount
        rounded half-up to integer cents."
        PRD §3.9: "The window discount starts at full value for the first window".

        Design: Difficulty/dual_variant_calc/residual_provisional_vs_final_by_market
        """
        ctx = setup_standard()
        res = create_residual(ctx["eng"]["id"])
        calculated = get_success_data(
            api.calculate_residual_obligation(res["id"], CLERK))
        assert calculated["status"] == "CALCULATED"
        # 20000000 x 0.045 x 1.0 (first window, full value).
        assert calculated["final_amount_cents"] == 900000
        assert calculated["provisional_amount_cents"] == 4500, (
            "the provisional snapshot is never rewritten by calculation")

    def test_second_window_discount_applies(self, api):
        """PRD §3.9: "The window discount starts at full value for the first window
        and steps down by ten percentage points for each subsequent window — that
        is, the discount is one minus one-tenth times the zero-based window index".
        PRD §3.9: "The server also assigns `window_sequence`: the 1-based ordinal
        of this window among the engagement's obligations for the same
        `reuse_market`, ordered by `window_start` ascending".

        Design: Corner/calculations/residual_second_window_discount_applies
        """
        ctx = setup_standard()
        res1 = create_residual(ctx["eng"]["id"])  # 2027-01-05..2027-06-30
        res2 = create_residual(ctx["eng"]["id"],
                               window_start="2027-07-01", window_end="2027-12-31")
        calculated2 = get_success_data(
            api.calculate_residual_obligation(res2["id"], CLERK))
        assert calculated2["window_sequence"] == 2
        # 20000000 x 0.045 x 0.90 = 810000.
        assert calculated2["final_amount_cents"] == 810000
        res1_after = get_residual(res1["id"])
        assert res1_after["window_sequence"] == 1
        assert res1_after["provisional_amount_cents"] == 4500


class TestResidualDisputeCycle:
    def _setup_approved_residual(self, api):
        ctx = setup_standard()
        res = create_calculated_residual(ctx["eng"]["id"])
        get_success_data(api.approve_residual_obligation(res["id"], SUPERVISOR))
        return ctx, res

    def test_dispute_then_recalculate_is_deterministic(self, api):
        """PRD §3.9: "Dispute by a `UnionAuditor` transitions an `APPROVED`
        obligation to `DISPUTED` and increments `version`".
        PRD §3.9: "When calculation runs from `DISPUTED`, the same pinned
        `base_pct` and `window_sequence` are reused, so a recalculation after a
        dispute reflects only the original snapshot."

        Design: Difficulty/non_linear_state_machine/residual_dispute_recalculate_cycle
        """
        _ctx, res = self._setup_approved_residual(api)
        disputed = get_success_data(api.dispute_residual_obligation(
            res["id"], "receipts understated for window", AUDITOR))
        assert disputed["status"] == "DISPUTED"

        recalculated = get_success_data(
            api.calculate_residual_obligation(res["id"], CLERK))
        assert recalculated["status"] == "CALCULATED"
        assert recalculated["final_amount_cents"] == 900000, (
            "recalculation from the pinned snapshot reproduces the first pass")

    def test_reapprove_after_recalculation(self, api):
        """PRD §3.9: "The residual lifecycle thus permits a dispute loop:
        `APPROVED` → `DISPUTED` → `CALCULATED` → `APPROVED`, with each
        recalculation reusing the pinned snapshot."

        Design: Difficulty/non_linear_state_machine/residual_dispute_recalculate_cycle
        """
        _ctx, res = self._setup_approved_residual(api)
        get_success_data(api.dispute_residual_obligation(
            res["id"], "receipts understated for window", AUDITOR))
        get_success_data(api.calculate_residual_obligation(res["id"], CLERK))
        reapproved = get_success_data(
            api.approve_residual_obligation(res["id"], SUPERVISOR))
        assert reapproved["status"] == "APPROVED"
        assert reapproved["provisional_amount_cents"] == 4500, (
            "provisional snapshot survives the whole dispute loop")

    def test_dispute_from_calculated_rejected(self, api):
        """PRD §3.9: "Calculation against an obligation in any other status,
        approval against an obligation not in `CALCULATED`, and dispute against an
        obligation not in `APPROVED` are each rejected with
        `ERR_RESIDUAL_INVALID_STATE`."

        Design: Corner/state_machines/residual_dispute_from_calculated_rejected
        """
        ctx = setup_standard()
        res = create_calculated_residual(ctx["eng"]["id"])
        resp = api.dispute_residual_obligation(res["id"], "premature dispute",
                                               AUDITOR)
        validate_error(resp, ApiErrorId.ERR_RESIDUAL_INVALID_STATE)
        assert get_residual(res["id"])["status"] == "CALCULATED"


class TestResidualCreateGates:
    def test_create_on_draft_engagement_rejected(self, api):
        """PRD §3.9: "The engagement must be `ACTIVE` or `WRAPPED`; otherwise the
        create is rejected with `ERR_COMPLIANCE_STATE`."

        Design: Corner/validations/residual_create_on_draft_engagement_rejected
        """
        agr = create_ratified_agreement()
        prod = create_shooting_production(agr["id"])
        perf = create_performer()
        eng = create_draft_engagement(prod["id"], agr["id"], perf["id"])
        payload = create_residual_obligation_payload(eng["id"])
        resp = api.create_residual_obligation(payload, ACCOUNTANT)
        validate_error(resp, ApiErrorId.ERR_COMPLIANCE_STATE)

    def test_market_without_base_pct_rejected(self, api):
        """PRD §3.9: "The chosen `reuse_market` must have a base percentage defined
        in the engagement's agreement `residual_base_pct_by_market`; a missing
        entry is rejected with `ERR_MARKET_BASE_PCT_MISSING`."

        Design: Corner/validations/residual_market_without_base_pct_rejected
        """
        ctx = setup_standard()
        payload = create_residual_obligation_payload(
            ctx["eng"]["id"], reuse_market="HOME_VIDEO",
            reported_gross_receipts_cents=1000000)
        resp = api.create_residual_obligation(payload, ACCOUNTANT)
        validate_error(resp, ApiErrorId.ERR_MARKET_BASE_PCT_MISSING)

    def test_overlapping_window_rejected(self, api):
        """PRD §3.9: "Windows for the same engagement and the same `reuse_market`
        may not overlap on a closed-interval basis — the other's `window_start` on
        or before this `window_end` and this `window_start` on or before the
        other's `window_end` is a conflict, including a shared boundary date — and
        a violation is rejected with `ERR_RESIDUAL_WINDOW_OVERLAP`."

        Design: Corner/validations/residual_overlapping_window_rejected
        """
        ctx = setup_standard()
        create_residual(ctx["eng"]["id"], window_start="2027-06-01",
                        window_end="2027-12-31",
                        reported_gross_receipts_cents=5000000)
        # Shares the boundary date 2027-12-31 with the existing window.
        payload = create_residual_obligation_payload(
            ctx["eng"]["id"], window_start="2027-12-31", window_end="2028-06-30",
            reported_gross_receipts_cents=1000000)
        resp = api.create_residual_obligation(payload, ACCOUNTANT)
        validate_error(resp, ApiErrorId.ERR_RESIDUAL_WINDOW_OVERLAP)


class TestResidualValidationPriority:
    def _setup_existing_window(self, api):
        ctx = setup_standard()
        create_residual(ctx["eng"]["id"], window_start="2027-06-01",
                        window_end="2027-12-31",
                        reported_gross_receipts_cents=5000000)
        return ctx

    def test_inverted_window_reports_temporal_not_overlap(self, api):
        """PRD §2.7: "When a request violates multiple rules, the rejection
        surfaces the highest-priority failure." — "6. Temporal shape and
        containment rules (date ordering, window containment, jurisdiction
        validity)" precede "7. Business-constraint rules (agreement window
        overlap, performer double-booking, residual window overlap, duplicate work
        date, open batch uniqueness)".
        PRD §3.9: "The `window_end` must be on or after `window_start` (the window
        is a closed interval); an inverted window is rejected with
        `ERR_INVALID_TEMPORAL`."

        Design: Difficulty/priority_pair_validation_conflict/residual_window_temporal_error_beats_overlap_constraint
        """
        ctx = self._setup_existing_window(api)
        # Inverted AND overlapping the existing window: temporal fires first.
        payload = create_residual_obligation_payload(
            ctx["eng"]["id"], window_start="2027-12-01", window_end="2027-06-01",
            reported_gross_receipts_cents=1000000)
        resp = api.create_residual_obligation(payload, ACCOUNTANT)
        validate_error(resp, ApiErrorId.ERR_INVALID_TEMPORAL)

    def test_inverted_window_persists_nothing(self, api):
        """PRD §3.9: "The `window_end` must be on or after `window_start` (the
        window is a closed interval); an inverted window is rejected with
        `ERR_INVALID_TEMPORAL`." A rejected create persists no obligation, so the
        pre-existing window is the only row.

        Design: Difficulty/priority_pair_validation_conflict/residual_window_temporal_error_beats_overlap_constraint
        """
        ctx = self._setup_existing_window(api)
        payload = create_residual_obligation_payload(
            ctx["eng"]["id"], window_start="2027-12-01", window_end="2027-06-01",
            reported_gross_receipts_cents=1000000)
        validate_error(api.create_residual_obligation(payload, ACCOUNTANT),
                       ApiErrorId.ERR_INVALID_TEMPORAL)
        residuals = list_all_residuals()
        assert len(residuals) == 1, "the rejected create persists nothing"
        assert residuals[0]["window_start"] == "2027-06-01"
