"""Grower settlements: component rounding, lifecycle loop, balances, lockdown."""
import pytest

from test_helpers import (
    ApiErrorId,
    assert_settlement,
    create_completed_drying_batch,
    create_completed_run,
    create_grower,
    create_lot,
    get_lot,
    make_admin_headers,
    record_aflatoxin,
    record_kernel_grade,
    record_moisture_kernel,
    route_lot,
    setup_settlement_draft,
    validate_error,
    validate_success,
)


def _delta_farms_settlement(api):
    """The 8000-lb Butte lot scenario: grower 247 c/lb at 7.5% premium, intake
    11.5, dried to 9.5, run 4500/1800/1200, grade 0.72 -> graded 3240.00,
    settlement total 854299."""
    grower = create_grower(
        name="Delta Farms", ranch_code="DF-02",
        base_price_cents_per_lb=247, premium_rate_pct=0.075,
    )
    lot = create_lot(grower["id"], variety="Butte", gross_weight_lbs=8000)
    record_moisture_kernel(
        lot["id"], moisture_pct=11.5, kernel_pct=0.60, foreign_material_pct=0.03
    )
    record_aflatoxin(lot["id"], aflatoxin_ppb=3.0)
    create_completed_drying_batch(lot["id"], final_moisture_pct=9.5)
    route_lot(lot["id"], route="KERNEL")
    create_completed_run(
        lot["id"], kernel_out_lbs=4500, shell_out_lbs=1800, hull_out_lbs=1200
    )
    record_kernel_grade(lot["id"], edible_kernel_pct=0.72, size_spec="SPEC_25_27")
    settlement = validate_success(
        api.create_settlement({"lot_id": lot["id"]}, make_admin_headers()),
        expected_status=201,
    )
    return grower, lot["id"], settlement


class TestSettlementComponentRounding:
    def test_settlement_components_rounded_before_summation(self, api):
        """PRD (Weights, Money, and Rounding Discipline): "each settlement
        component (base_cents, premium_cents, moisture_deduction_cents) is
        individually rounded half-up to whole cents — 0 decimal places — before
        any summation, and the settlement's total_cents is the integer sum of
        those already-rounded components. The total is never produced by summing
        unrounded components and rounding once at the end."

        Design: Difficulty/combinatorial_formula/settlement_component_rounding_order
        """
        _, _, settlement = _delta_farms_settlement(api)
        assert settlement["graded_kernel_weight_lbs"] == pytest.approx(3240.00, abs=0.01)
        # base = round(3240.00 * 247) = 800280
        assert settlement["base_cents"] == 800280
        # premium = round(800280 * 0.075) = 60021 (edible 0.72 >= 0.70)
        assert settlement["premium_cents"] == 60021
        # deduction = round(800280 * 0.005 * (9.5 - 8.0)) = round(6002.1) = 6002
        assert settlement["moisture_deduction_cents"] == 6002
        # total = 800280 + 60021 - 6002 = 854299
        assert settlement["total_cents"] == 854299

    def test_settlement_snapshot_and_grower_derivation(self, api):
        """PRD (Grower Settlement and Payment): "At creation the settlement
        snapshots the lot's graded_kernel_weight_lbs onto its own field of the
        same name, copies the delivering grower from the lot onto grower_id"
        and "New settlements are born in DRAFT."

        Design: Difficulty/combinatorial_formula/settlement_component_rounding_order
        """
        grower, lot_id, settlement = _delta_farms_settlement(api)
        assert_settlement(settlement)
        assert settlement["status"] == "DRAFT"
        assert settlement["lot_id"] == lot_id
        assert settlement["grower_id"] == grower["id"]
        assert settlement["graded_kernel_weight_lbs"] == pytest.approx(3240.00, abs=0.01)


class TestPremiumThreshold:
    def test_premium_grade_threshold_inclusive_at_seventy(self, api):
        """PRD (Grower Settlement and Payment): "premium_cents — the
        already-rounded base_cents multiplied by the grower's premium_rate_pct,
        but only when the lot's edible_kernel_pct is at least 0.70, the premium
        grade bar; below the bar the premium is exactly zero."

        Design: Corner/calculations/premium_grade_threshold_inclusive_at_seventy
        """
        scenario = setup_settlement_draft(
            grower_overrides={"base_price_cents_per_lb": 100, "premium_rate_pct": 0.10},
            lot_kwargs={"gross_weight_lbs": 4000, "moisture_pct": 6.0,
                        "kernel_pct": 0.50, "foreign_material_pct": 0.01},
            run_outputs={"kernel_out_lbs": 2000, "shell_out_lbs": 1000,
                         "hull_out_lbs": 700},
            grade_overrides={"edible_kernel_pct": 0.70},
        )
        st = scenario["settlement"]
        # graded = 2000 * 0.70 = 1400.00; base = round(1400*100) = 140000
        assert st["graded_kernel_weight_lbs"] == pytest.approx(1400.00, abs=0.01)
        assert st["base_cents"] == 140000
        # premium applies at exactly 0.70 (inclusive bar)
        assert st["premium_cents"] == 14000
        # effective moisture 6.0 <= 8.0 -> no deduction
        assert st["moisture_deduction_cents"] == 0
        assert st["total_cents"] == 154000


class TestSettlementLifecycleLoop:
    def test_approve_then_void_then_reapprove_then_pay(self, api):
        """PRD (Grower Settlement and Payment): "Approving a `DRAFT` settlement
        moves it to `ISSUED` and adds its `total_cents` to the grower's
        `payable_outstanding_cents`" and "Voiding an `ISSUED` settlement is the
        exact compensation of approval: it moves the settlement back to `DRAFT`
        and subtracts the same `total_cents` from `payable_outstanding_cents`."
        and "Paying an `ISSUED` settlement moves it to `PAID`, subtracts
        `total_cents` from `payable_outstanding_cents`, adds it to the grower's
        `lifetime_paid_cents`".

        Design: Difficulty/non_linear_state_machine/settlement_issue_void_loop
        """
        grower, lot_id, st = _delta_farms_settlement(api)
        total = st["total_cents"]
        assert total == 854299

        approved = validate_success(api.approve_settlement(st["id"], make_admin_headers()))
        assert approved["status"] == "ISSUED"
        g = validate_success(api.get_grower(grower["id"], make_admin_headers()))
        assert g["payable_outstanding_cents"] == total

        voided = validate_success(api.void_settlement(st["id"], make_admin_headers()))
        assert voided["status"] == "DRAFT"
        g = validate_success(api.get_grower(grower["id"], make_admin_headers()))
        assert g["payable_outstanding_cents"] == 0

        validate_success(api.approve_settlement(st["id"], make_admin_headers()))
        paid = validate_success(api.pay_settlement(st["id"], make_admin_headers()))
        assert paid["status"] == "PAID"
        g = validate_success(api.get_grower(grower["id"], make_admin_headers()))
        assert g["payable_outstanding_cents"] == 0
        assert g["lifetime_paid_cents"] == total

    def test_pay_bubbles_lot_to_settled(self, api):
        """PRD (Grower Settlement and Payment): paying "moves the settlement's
        lot from `PROCESSED` to `SETTLED`, the lot's terminal resting state
        alongside `DISPOSED`."

        Design: Difficulty/non_linear_state_machine/settlement_issue_void_loop
        """
        grower, lot_id, st = _delta_farms_settlement(api)
        validate_success(api.approve_settlement(st["id"], make_admin_headers()))
        validate_success(api.pay_settlement(st["id"], make_admin_headers()))
        lot_after = get_lot(lot_id)
        assert lot_after["status"] == "SETTLED"


class TestGrowerPayableRoundtrip:
    def test_approve_void_leaves_payable_unchanged(self, api):
        """PRD (Grower Settlement and Payment): "Voiding an ISSUED settlement is
        the exact compensation of approval: it moves the settlement back to
        DRAFT and subtracts the same total_cents from payable_outstanding_cents."

        Design: Difficulty/compensating_invariant/grower_payable_approve_void_roundtrip
        """
        grower, _, st = _delta_farms_settlement(api)
        validate_success(api.approve_settlement(st["id"], make_admin_headers()))
        g = validate_success(api.get_grower(grower["id"], make_admin_headers()))
        assert g["payable_outstanding_cents"] == 854299

        validate_success(api.void_settlement(st["id"], make_admin_headers()))
        g = validate_success(api.get_grower(grower["id"], make_admin_headers()))
        assert g["payable_outstanding_cents"] == 0

    def test_void_does_not_touch_lifetime_paid(self, api):
        """PRD (Grower Settlement and Payment): "Paying an `ISSUED` settlement
        moves it to `PAID`, subtracts `total_cents` from
        `payable_outstanding_cents`, adds it to the grower's
        `lifetime_paid_cents`" — only pay moves the lifetime balance; the
        approve/void pair leaves it at its initial 0.

        Design: Difficulty/compensating_invariant/grower_payable_approve_void_roundtrip
        """
        grower, _, st = _delta_farms_settlement(api)
        validate_success(api.approve_settlement(st["id"], make_admin_headers()))
        voided = validate_success(api.void_settlement(st["id"], make_admin_headers()))
        assert voided["status"] == "DRAFT"
        g = validate_success(api.get_grower(grower["id"], make_admin_headers()))
        assert g["lifetime_paid_cents"] == 0
        assert g["payable_outstanding_cents"] == 0


class TestSettlementStateErrors:
    def _simple_draft(self, api):
        """2000-lb lot, run 1000/500/300, grade 0.80 -> graded 800.00, grower
        price 100, no premium: settlement total 80000."""
        return setup_settlement_draft(
            grower_overrides={"base_price_cents_per_lb": 100},
            lot_kwargs={"gross_weight_lbs": 2000},
            run_outputs={"kernel_out_lbs": 1000, "shell_out_lbs": 500,
                         "hull_out_lbs": 300},
            grade_overrides={"edible_kernel_pct": 0.80, "size_spec": "UNSIZED"},
        )

    def test_settlement_approve_twice_returns_invalid_state(self, api):
        """PRD (Validation Order): "Triggers attempted on an entity already in
        a terminal state are rejected with `ERR_ALREADY_TERMINAL` (409); any
        other invalid from-state with `ERR_INVALID_STATE` (409)." Approving an
        ISSUED settlement is an invalid from-state for approve, which requires
        DRAFT.

        Design: Corner/state_machines/settlement_approve_twice_returns_invalid_state
        """
        scenario = self._simple_draft(api)
        st = scenario["settlement"]
        # graded 800.00 * 100 = 80000; no premium (rate defaults 0.0), no deduction.
        assert st["total_cents"] == 80000
        validate_success(api.approve_settlement(st["id"], make_admin_headers()))
        resp = api.approve_settlement(st["id"], make_admin_headers())
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
        g = validate_success(
            api.get_grower(scenario["grower"]["id"], make_admin_headers())
        )
        assert g["payable_outstanding_cents"] == 80000

    def test_settlement_cancelled_terminal_lockdown(self, api):
        """PRD (Grower Settlement and Payment): "PAID and CANCELLED are
        terminal: actions attempted on a settlement already in either state are
        rejected with ERR_ALREADY_TERMINAL".

        Design: Corner/state_machines/settlement_cancelled_terminal_lockdown
        """
        scenario = self._simple_draft(api)
        st = scenario["settlement"]
        validate_success(api.cancel_settlement(st["id"], make_admin_headers()))
        resp = api.approve_settlement(st["id"], make_admin_headers())
        validate_error(resp, ApiErrorId.ERR_ALREADY_TERMINAL, expected_status=409)
        g = validate_success(
            api.get_grower(scenario["grower"]["id"], make_admin_headers())
        )
        assert g["payable_outstanding_cents"] == 0
