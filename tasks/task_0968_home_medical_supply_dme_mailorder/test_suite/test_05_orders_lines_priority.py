"""Order lines: pinned rounding, per-check violations, validation-priority
pairs, OCC on the order, and terminal-state cancel lockdown."""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    order_line_payload,
    create_payer_plan,
    create_formulary_item,
    create_active_patient,
    create_prescription,
    create_fit_profile,
    create_manual_order,
    add_order_line,
    get_order,
    cancel_order,
    get_hsa_account,
    setup_active_patient_with_item,
    INTAKE,
    make_patient_headers,
)


class TestPinnedRounding:
    def test_line_allowed_uses_per_unit_first_rounding(self, api):
        """PRD §2.5: "a pack fee of 999 cents over a pack size of 8 produces a
        unit allowance of 124.88 cents; a line of 3 units must price at 374.64
        cents under the pinned per-unit-first order, whereas the forbidden
        single-round order would produce 374.63 cents."

        Design: Difficulty/combinatorial_formula/line_rounding_order_pinned_mode_b
        """
        ctx = setup_active_patient_with_item(
            hcpcs_code="A6250", category="WOUND", size_code="4X4", size_codes=("4X4",),
            pack_fee_cents=999, pack_size=8, retail_price_cents=650,
            max_units_per_cycle=30, diagnosis_codes=("L89.1",),
        )
        patient_id = ctx["patient"]["id"]
        order = create_manual_order(patient_id)
        line = add_order_line(order["id"], order["version"], ctx["item"]["id"],
                              size_code="4X4", quantity=3, patient_id=patient_id)
        assert line["unit_allowance_cents"] == pytest.approx(124.88, abs=0.001)
        assert line["line_allowed_cents"] == pytest.approx(374.64, abs=0.001), (
            f"pinned order 124.88 x 3 = 374.64 (not 374.63), got {line['line_allowed_cents']}"
        )

    def test_line_allowed_scales_after_unit_rounding(self, api):
        """PRD §2.5: "the per-unit proration of a payer's pack fee is rounded
        half up to 2 decimal places **first**, and only then multiplied by the
        line quantity and rounded half up again." — quantity 10 prices at
        1248.80, not the single-round 1248.75.

        Design: Difficulty/combinatorial_formula/line_rounding_order_pinned_mode_b
        """
        ctx = setup_active_patient_with_item(
            hcpcs_code="A6250", category="WOUND", size_code="4X4", size_codes=("4X4",),
            pack_fee_cents=999, pack_size=8, retail_price_cents=650,
            max_units_per_cycle=30, diagnosis_codes=("L89.1",),
        )
        patient_id = ctx["patient"]["id"]
        order = create_manual_order(patient_id)
        line = add_order_line(order["id"], order["version"], ctx["item"]["id"],
                              size_code="4X4", quantity=10, patient_id=patient_id)
        assert line["unit_allowance_cents"] == pytest.approx(124.88, abs=0.001)
        assert line["line_allowed_cents"] == pytest.approx(1248.80, abs=0.001)


class TestLineValidationRules:
    def test_size_mismatch_with_valid_rx_isolated(self, api):
        """PRD §3.5: "the line's `size_code` must be one of the item's offered
        `size_codes` **and** must equal the patient's `CURRENT` fit profile size
        for the item's category — a missing profile fails this check too —
        otherwise `ERR_SIZE_MISMATCH` (HTTP 422)."

        Design: Corner/validations/size_mismatch_with_valid_rx_isolated
        """
        ctx = setup_active_patient_with_item(size_codes=("45MM", "57MM"))
        patient_id = ctx["patient"]["id"]
        order = create_manual_order(patient_id)

        resp = api.add_order_line(
            order["id"],
            order_line_payload(ctx["item"]["id"], order["version"],
                               size_code="57MM", quantity=1),
            make_patient_headers(patient_id),
        )
        validate_error(resp, ApiErrorId.ERR_SIZE_MISMATCH)

    def test_item_not_on_plan_formulary_rejected(self, api):
        """PRD §3.5: "the item must be covered by the patient's plan, meaning
        the patient's `payer_plan_id` appears in the item's
        `covered_plan_ids`, otherwise `ERR_ITEM_NOT_ON_FORMULARY` (HTTP 422)".

        Design: Corner/validations/item_not_on_plan_formulary_rejected
        """
        mcr = create_payer_plan(plan_type="MEDICARE_DMEPOS", coinsurance_pct=0.20, cycle_months=3)
        com = create_payer_plan(plan_type="COMMERCIAL", coinsurance_pct=0.10, cycle_months=1)
        item = create_formulary_item([com["id"]])  # covers only the commercial plan
        patient = create_active_patient(mcr["id"])
        create_prescription(patient["id"], hcpcs_code="A4419")
        create_fit_profile(patient["id"], patient["version"], category="OSTOMY", size_code="45MM")
        order = create_manual_order(patient["id"])

        resp = api.add_order_line(
            order["id"],
            order_line_payload(item["id"], order["version"], size_code="45MM", quantity=1),
            make_patient_headers(patient["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_ITEM_NOT_ON_FORMULARY)

    def test_quantity_exceeds_allowance_rejected(self, api):
        """PRD §3.5: "the requested `quantity` must not exceed the resupply
        quantity allowance computed exactly as in §3.4 for the patient's plan,
        prescription, item, and any required authorization, otherwise
        `ERR_QUANTITY_EXCEEDS_ALLOWANCE`." — allowance is min(20x3, 60) = 60.

        Design: Corner/validations/quantity_exceeds_allowance_rejected
        """
        ctx = setup_active_patient_with_item(max_units_per_cycle=60, monthly_quantity=20)
        patient_id = ctx["patient"]["id"]
        order = create_manual_order(patient_id)

        resp = api.add_order_line(
            order["id"],
            order_line_payload(ctx["item"]["id"], order["version"],
                               size_code="45MM", quantity=70),
            make_patient_headers(patient_id),
        )
        validate_error(resp, ApiErrorId.ERR_QUANTITY_EXCEEDS_ALLOWANCE)

        fresh = get_order(order["id"])
        line = add_order_line(order["id"], fresh["version"], ctx["item"]["id"],
                              size_code="45MM", quantity=60, patient_id=patient_id)
        assert line["quantity"] == 60


class TestValidationPriorityPairs:
    def test_cancelled_order_submit_reports_state_error_not_fiscal(self, api):
        """PRD §2.10: "A request failing at an earlier band never reports an
        error from a later band." — the state band
        (`ERR_ORDER_NOT_DRAFT` on a non-draft order, §3.5: "a non-draft order is
        rejected with `ERR_ORDER_NOT_DRAFT`") precedes the fiscal band
        (`ERR_INSUFFICIENT_HSA`).

        Design: Difficulty/priority_pair_validation_conflict/state_vs_fiscal_on_cancelled_order_submit
        """
        ctx = setup_active_patient_with_item(
            plan_type="CASH_HSA", coinsurance_pct=1.00, cycle_months=1,
            hsa_initial_credit_cents=100,
        )
        patient_id = ctx["patient"]["id"]
        order = create_manual_order(patient_id)
        add_order_line(order["id"], order["version"], ctx["item"]["id"],
                       size_code="45MM", quantity=10, patient_id=patient_id)
        cancel_order(order["id"], patient_id)

        # Estimated responsibility (10 x 300 = 3000) exceeds the 100-cent HSA
        # balance, but the cancelled state must be reported instead.
        resp = api.submit_order(order["id"], make_patient_headers(patient_id))
        validate_error(resp, ApiErrorId.ERR_ORDER_NOT_DRAFT)

    def test_cancelled_order_submit_fires_no_side_effects(self, api):
        """PRD §3.5: "A `Patient` or `IntakeCoordinator` submits a `DRAFT`
        order; a non-draft order is rejected with `ERR_ORDER_NOT_DRAFT`." — the
        rejected submit leaves fulfillment `CANCELLED` and the HSA balance
        untouched.

        Design: Difficulty/priority_pair_validation_conflict/state_vs_fiscal_on_cancelled_order_submit
        """
        ctx = setup_active_patient_with_item(
            plan_type="CASH_HSA", coinsurance_pct=1.00, cycle_months=1,
            hsa_initial_credit_cents=100,
        )
        patient_id = ctx["patient"]["id"]
        order = create_manual_order(patient_id)
        add_order_line(order["id"], order["version"], ctx["item"]["id"],
                       size_code="45MM", quantity=10, patient_id=patient_id)
        cancelled = cancel_order(order["id"], patient_id)

        api.submit_order(order["id"], make_patient_headers(patient_id))

        after = get_order(order["id"])
        assert after["fulfillment_status"] == "CANCELLED"
        assert after["version"] == cancelled["version"], (
            "rejected submit must not mutate the order"
        )
        account = get_hsa_account(patient_id)
        assert account["balance_cents"] == pytest.approx(100, abs=0.001)

    def test_line_add_without_rx_reports_safety_error_not_constraint(self, api):
        """PRD §2.10: "Business-safety checks follow (`ERR_DIAGNOSIS_REQUIRED`,
        `ERR_NO_VALID_PRESCRIPTION`, `ERR_PRIOR_AUTH_REQUIRED`,
        `ERR_SAMPLE_LIMIT_EXCEEDED`), then business-constraint checks" — with no
        covering prescription AND no fit profile, the safety-band
        `ERR_NO_VALID_PRESCRIPTION` is reported, never the constraint-band
        `ERR_SIZE_MISMATCH`. PRD §2.10: "A request failing at an earlier band
        never reports an error from a later band."

        Design: Difficulty/priority_pair_validation_conflict/safety_vs_constraint_on_line_add
        """
        ctx = setup_active_patient_with_item(
            hcpcs_code="A6250", category="WOUND", size_code="4X4", size_codes=("4X4",),
            pack_fee_cents=999, pack_size=8, retail_price_cents=650,
            max_units_per_cycle=30, with_rx=False, with_fit=False,
        )
        patient_id = ctx["patient"]["id"]
        order = create_manual_order(patient_id)

        resp = api.add_order_line(
            order["id"],
            order_line_payload(ctx["item"]["id"], order["version"],
                               size_code="4X4", quantity=1),
            make_patient_headers(patient_id),
        )
        validate_error(resp, ApiErrorId.ERR_NO_VALID_PRESCRIPTION)

    def test_line_add_rejection_creates_no_line(self, api):
        """PRD §3.5: "an `ACTIVE` prescription covering the line's code must
        exist, otherwise `ERR_NO_VALID_PRESCRIPTION`" — the rejected add leaves
        the order with zero lines.

        Design: Difficulty/priority_pair_validation_conflict/safety_vs_constraint_on_line_add
        """
        ctx = setup_active_patient_with_item(
            hcpcs_code="A6250", category="WOUND", size_code="4X4", size_codes=("4X4",),
            pack_fee_cents=999, pack_size=8, retail_price_cents=650,
            max_units_per_cycle=30, with_rx=False, with_fit=False,
        )
        patient_id = ctx["patient"]["id"]
        order = create_manual_order(patient_id)

        resp = api.add_order_line(
            order["id"],
            order_line_payload(ctx["item"]["id"], order["version"],
                               size_code="4X4", quantity=1),
            make_patient_headers(patient_id),
        )
        validate_error(resp, ApiErrorId.ERR_NO_VALID_PRESCRIPTION)

        lines = validate_success(api.list_order_lines(order["id"], INTAKE), expected_status=200)
        assert lines == [], f"rejected line add must create no line, got {lines}"


class TestOrderOccAndCancel:
    def test_occ_order_line_stale_order_version_rejected(self, api):
        """PRD §2.8: "A mismatch with the order's current `version` is rejected
        with `ERR_STALE_ORDER_VERSION` (HTTP 412), since a stale writer would
        otherwise price and validate its line against an out-of-date line set."

        Design: Corner/complexity_layers/occ_order_line_stale_order_version_rejected
        """
        ctx = setup_active_patient_with_item()
        patient_id = ctx["patient"]["id"]
        order = create_manual_order(patient_id)
        observed = order["version"]

        add_order_line(order["id"], observed, ctx["item"]["id"],
                       size_code="45MM", quantity=5, patient_id=patient_id)

        resp = api.add_order_line(
            order["id"],
            order_line_payload(ctx["item"]["id"], observed, size_code="45MM", quantity=3),
            make_patient_headers(patient_id),
        )
        validate_error(resp, ApiErrorId.ERR_STALE_ORDER_VERSION)

        after = get_order(order["id"])
        assert after["version"] == observed + 1, (
            f"only the first add may bump the version: {observed} -> {after['version']}"
        )

    def test_cancel_cancelled_order_returns_invalid_state(self, api):
        """PRD §3.5: "Cancellation from any later fulfillment state, or from the
        terminal `CANCELLED` state itself, is rejected with
        `ERR_INVALID_STATE`."

        Design: Corner/state_machines/cancel_cancelled_order_returns_invalid_state
        """
        ctx = setup_active_patient_with_item()
        patient_id = ctx["patient"]["id"]
        order = create_manual_order(patient_id)
        cancel_order(order["id"], patient_id)

        resp = api.cancel_order(order["id"], make_patient_headers(patient_id))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
