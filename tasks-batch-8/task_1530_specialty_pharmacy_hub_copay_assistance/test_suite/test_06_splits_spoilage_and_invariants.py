"""Ship-time financial splits: accumulator vs non-accumulator divergence,
the nested-min branch switch across fills, foundation per-fill rounding
order, exact exhaustion, spoil reversal cascades, and the payer OOP
partition identity."""
from test_helpers import (
    api_client,
    assert_shipment,
    create_approved_enrollment,
    create_approved_with_card,
    create_pool,
    deliver,
    get_enrollment,
    match_assistance,
    request_shipment,
    set_clock,
    ship,
    spoil,
    validate_paginated,
    validate_success,
)
from test_helpers import TEST_USERS

CM = TEST_USERS["case_manager_headers"]
FC = TEST_USERS["financial_counselor_headers"]
RX = TEST_USERS["pharmacy_partner_headers"]


class TestAccumulatorPlanDivergence:

    def test_accumulator_plan_excludes_assistance_from_oop_accrual(self):
        """PRD section 3.6: "Under an accumulator plan
        (`plan_has_accumulator` true), manufacturer assistance is excluded
        from the patient's out-of-pocket accrual, so
        `payer_accumulator_delta_cents` equals `patient_pay_cents`."
        PRD section 3.6: "The enrollment then accrues:
        `payer_accumulated_oop_cents` becomes the smaller of the
        investigation's `oop_max_cents` and its prior value plus the delta,
        and `remaining_oop_cents` is recomputed as `oop_max_cents` minus the
        accumulated total."

        Design: Difficulty/dual_variant_calc/copay_accumulator_plan_split_divergence
        """
        ctx = create_approved_with_card(
            patient_ref="PAT-A",
            bi_overrides={"plan_has_accumulator": True,
                          "patient_cost_share_cents": 20_000,
                          "oop_max_cents": 500_000})
        fill = request_shipment(
            ctx["enrollment"]["id"], requested_delivery_date="2026-08-03")
        shipped = ship(fill["id"])
        assert shipped["assistance_pay_cents"] == 15_000
        assert shipped["patient_pay_cents"] == 5_000
        assert shipped["payer_accumulator_delta_cents"] == 5_000, \
            "accumulator plan: the delta equals patient_pay only"

        enr = get_enrollment(ctx["enrollment"]["id"])
        assert enr["payer_accumulated_oop_cents"] == 5_000
        assert enr["remaining_oop_cents"] == 495_000

    def test_non_accumulator_plan_counts_assistance_toward_oop(self):
        """PRD section 3.6: "Under a non-accumulator plan, assistance counts
        toward the out-of-pocket maximum, so the delta equals
        `patient_pay_cents` plus `assistance_pay_cents` — that is, the full
        frozen cost share."
        PRD section 3.6: "The enrollment then accrues:
        `payer_accumulated_oop_cents` becomes the smaller of the
        investigation's `oop_max_cents` and its prior value plus the delta,
        and `remaining_oop_cents` is recomputed as `oop_max_cents` minus the
        accumulated total."

        Design: Difficulty/dual_variant_calc/copay_accumulator_plan_split_divergence
        """
        ctx = create_approved_with_card(
            patient_ref="PAT-B",
            bi_overrides={"plan_has_accumulator": False,
                          "patient_cost_share_cents": 20_000,
                          "oop_max_cents": 500_000})
        fill = request_shipment(
            ctx["enrollment"]["id"], requested_delivery_date="2026-08-03")
        shipped = ship(fill["id"])
        assert shipped["assistance_pay_cents"] == 15_000
        assert shipped["patient_pay_cents"] == 5_000
        assert shipped["payer_accumulator_delta_cents"] == 20_000, \
            "non-accumulator plan: the full frozen cost share accrues"

        enr = get_enrollment(ctx["enrollment"]["id"])
        assert enr["payer_accumulated_oop_cents"] == 20_000
        assert enr["remaining_oop_cents"] == 480_000


class TestNestedMinBranchSwitching:

    def _setup_card_with_low_annual_cap(self):
        return create_approved_with_card(
            patient_ref="PAT-D",
            bi_overrides={"plan_has_accumulator": False,
                          "patient_cost_share_cents": 20_000},
            program_overrides={"copay_card_per_fill_cap_cents": 15_000,
                               "copay_card_annual_cap_cents": 20_000})

    def test_first_fill_binds_per_fill_cap_branch(self):
        """PRD section 3.6: "With a non-terminal `COPAY_CARD` assistance
        whose `remaining_annual_benefit_cents` is positive,
        `assistance_pay_cents` is the smallest of three values — the
        assistance's `per_fill_cap_cents`, its
        `remaining_annual_benefit_cents`, and the frozen cost share — and
        `patient_pay_cents` is the frozen cost share minus the assistance
        portion."

        Design: Difficulty/combinatorial_formula/copay_card_nested_min_branch_switching
        """
        ctx = self._setup_card_with_low_annual_cap()
        fill = request_shipment(
            ctx["enrollment"]["id"], requested_delivery_date="2026-08-01")
        shipped = ship(fill["id"])
        # min(per_fill_cap 15000, remaining 20000, cost share 20000) = 15000
        assert shipped["assistance_pay_cents"] == 15_000, \
            "fill 1 binds the per-fill-cap branch of the nested min"
        assert shipped["patient_pay_cents"] == 5_000

    def test_second_fill_binds_remaining_annual_benefit_branch(self):
        """PRD section 3.6: "With a non-terminal `COPAY_CARD` assistance
        whose `remaining_annual_benefit_cents` is positive,
        `assistance_pay_cents` is the smallest of three values — the
        assistance's `per_fill_cap_cents`, its
        `remaining_annual_benefit_cents`, and the frozen cost share — and
        `patient_pay_cents` is the frozen cost share minus the assistance
        portion."
        PRD section 3.4: "When a ship-time disbursement drains
        `remaining_annual_benefit_cents` to exactly zero, the record moves
        `ACTIVE` → `EXHAUSTED`; should a later spoil reversal restore the
        remaining benefit above zero, the record automatically reverts
        `EXHAUSTED` → `ACTIVE`."

        Design: Difficulty/combinatorial_formula/copay_card_nested_min_branch_switching
        """
        ctx = self._setup_card_with_low_annual_cap()
        enr_id = ctx["enrollment"]["id"]
        fill_1 = request_shipment(
            enr_id, requested_delivery_date="2026-08-01")
        ship(fill_1["id"])
        deliver(fill_1["id"], "2026-08-01")
        set_clock("2026-08-22T00:00:00Z")

        fill_2 = request_shipment(
            enr_id, requested_delivery_date="2026-08-23")
        shipped_2 = ship(fill_2["id"])
        # min(per_fill_cap 15000, remaining 5000, cost share 20000) = 5000
        assert shipped_2["assistance_pay_cents"] == 5_000, \
            "fill 2 binds the remaining-annual-benefit branch"
        assert shipped_2["patient_pay_cents"] == 15_000

        data, _ = validate_paginated(api_client.list_copay_assistances(enr_id, FC))
        card = data[0]
        assert card["remaining_annual_benefit_cents"] == 0
        assert card["disbursed_cents"] == 20_000
        assert card["status"] == "EXHAUSTED", \
            "draining to exactly zero fires ACTIVE -> EXHAUSTED"

        enr = get_enrollment(enr_id)
        assert enr["payer_accumulated_oop_cents"] == 40_000, \
            "non-accumulator plan: the full cost share accrues per fill"


class TestFoundationRoundingOrder:

    def _setup_foundation_grant(self):
        create_pool(name="Fund50", coverage_pct=50,
                    grant_amount_cents=200_000)
        ctx = create_approved_enrollment(
            patient_ref="PAT-E",
            bi_overrides={"patient_cost_share_cents": 999,
                          "plan_has_accumulator": False})
        assistance = match_assistance(
            ctx["enrollment"]["id"], "FOUNDATION", counselor_id="fc-1")
        ctx["assistance"] = assistance
        ctx["enrollment"] = get_enrollment(ctx["enrollment"]["id"])
        return ctx

    def test_foundation_split_rounds_half_up_per_fill(self):
        """PRD section 3.6: "With a non-terminal `FOUNDATION` assistance
        whose remaining benefit is positive, the raw assistance amount is
        the frozen cost share multiplied by the grant's `coverage_pct` and
        divided by one hundred; that raw amount is rounded half-up to a
        whole cent for this fill, and `assistance_pay_cents` is the smaller
        of the rounded amount and the remaining annual benefit, with
        `patient_pay_cents` again the frozen cost share minus the assistance
        portion."

        Design: Difficulty/combinatorial_formula/foundation_per_fill_rounding_order
        """
        ctx = self._setup_foundation_grant()
        enr_id = ctx["enrollment"]["id"]
        # cost share 999 at 50% -> round_half_up(499.5) == 500 on each fill
        fill_1 = request_shipment(
            enr_id, requested_delivery_date="2026-08-01")
        shipped_1 = ship(fill_1["id"])
        assert shipped_1["assistance_pay_cents"] == 500
        assert shipped_1["patient_pay_cents"] == 499

        deliver(fill_1["id"], "2026-08-01")
        set_clock("2026-08-22T00:00:00Z")
        fill_2 = request_shipment(
            enr_id, requested_delivery_date="2026-08-22")
        shipped_2 = ship(fill_2["id"])
        assert shipped_2["assistance_pay_cents"] == 500

        deliver(fill_2["id"], "2026-08-22")
        set_clock("2026-09-12T00:00:00Z")
        fill_3 = request_shipment(
            enr_id, requested_delivery_date="2026-09-12")
        shipped_3 = ship(fill_3["id"])
        assert shipped_3["assistance_pay_cents"] == 500

    def test_foundation_disbursed_sums_per_fill_rounded_amounts(self):
        """PRD section 3.6: "The rounding order is pinned: each fill is
        rounded first, and `disbursed_cents` accumulates the per-fill
        rounded amounts. Computing the annual total first and rounding once
        is a different, non-conforming algorithm that yields different cents
        — a 999-cent cost share at 50 percent coverage over three fills
        disburses 500 + 500 + 500 = 1500 cents, whereas summing first and
        rounding once would yield 1499 cents."

        Design: Difficulty/combinatorial_formula/foundation_per_fill_rounding_order
        """
        ctx = self._setup_foundation_grant()
        enr_id = ctx["enrollment"]["id"]
        fill_1 = request_shipment(
            enr_id, requested_delivery_date="2026-08-01")
        ship(fill_1["id"])
        deliver(fill_1["id"], "2026-08-01")
        set_clock("2026-08-22T00:00:00Z")
        fill_2 = request_shipment(
            enr_id, requested_delivery_date="2026-08-22")
        ship(fill_2["id"])
        deliver(fill_2["id"], "2026-08-22")
        set_clock("2026-09-12T00:00:00Z")
        fill_3 = request_shipment(
            enr_id, requested_delivery_date="2026-09-12")
        ship(fill_3["id"])

        data, _ = validate_paginated(api_client.list_copay_assistances(enr_id, FC))
        grant = data[0]
        assert grant["disbursed_cents"] == 1_500, (
            f"per-fill-then-sum pins 1500 (the sum-then-round 1499 is "
            f"non-conforming), got {grant['disbursed_cents']}"
        )
        assert grant["remaining_annual_benefit_cents"] == 198_500


class TestExactExhaustionBoundary:

    def test_ship_draining_benefit_to_exactly_zero(self):
        """PRD section 3.6: "With a non-terminal `COPAY_CARD` assistance
        whose `remaining_annual_benefit_cents` is positive,
        `assistance_pay_cents` is the smallest of three values — the
        assistance's `per_fill_cap_cents`, its
        `remaining_annual_benefit_cents`, and the frozen cost share — and
        `patient_pay_cents` is the frozen cost share minus the assistance
        portion."

        Design: Difficulty/boundary_precision_check/copay_benefit_exact_exhaustion
        """
        ctx = create_approved_with_card(
            patient_ref="PAT-M",
            program_overrides={"copay_card_per_fill_cap_cents": 15_000,
                               "copay_card_annual_cap_cents": 15_000})
        fill = request_shipment(
            ctx["enrollment"]["id"], requested_delivery_date="2026-08-03")
        shipped = ship(fill["id"])
        assert shipped["assistance_pay_cents"] == 15_000, \
            "min of cap 15000, remaining 15000, share 20000"
        data, _ = validate_paginated(api_client.list_copay_assistances(
            ctx["enrollment"]["id"], FC))
        assert data[0]["remaining_annual_benefit_cents"] == 0, \
            "the remainder lands on exactly zero"

    def test_exact_zero_remainder_auto_transitions_to_exhausted(self):
        """PRD section 3.4: "When a ship-time disbursement drains
        `remaining_annual_benefit_cents` to exactly zero, the record moves
        `ACTIVE` → `EXHAUSTED`; should a later spoil reversal restore the
        remaining benefit above zero, the record automatically reverts
        `EXHAUSTED` → `ACTIVE`."

        Design: Difficulty/boundary_precision_check/copay_benefit_exact_exhaustion
        """
        ctx = create_approved_with_card(
            patient_ref="PAT-M2",
            program_overrides={"copay_card_per_fill_cap_cents": 15_000,
                               "copay_card_annual_cap_cents": 15_000})
        fill = request_shipment(
            ctx["enrollment"]["id"], requested_delivery_date="2026-08-03")
        ship(fill["id"])
        data, _ = validate_paginated(api_client.list_copay_assistances(
            ctx["enrollment"]["id"], FC))
        assert data[0]["status"] == "EXHAUSTED", \
            "the auto-transition fires at == 0, not below"
        assert data[0]["disbursed_cents"] == 15_000


class TestSpoilReversalCascade:

    def _setup_shipped_fill(self):
        ctx = create_approved_with_card(
            patient_ref="PAT-I",
            bi_overrides={"plan_has_accumulator": False,
                          "patient_cost_share_cents": 20_000,
                          "oop_max_cents": 500_000})
        fill = request_shipment(
            ctx["enrollment"]["id"], requested_delivery_date="2026-08-03")
        ship(fill["id"])
        return ctx, fill

    def test_spoil_reverses_assistance_ledger(self):
        """PRD section 3.6: "First, the assistance that funded the fill is
        compensated: its `remaining_annual_benefit_cents` is increased by
        the fill's `assistance_pay_cents` and its `disbursed_cents` is
        decreased by the same amount, a step skipped entirely when the
        fill's assistance portion was zero or the assistance already stands
        `RELEASED`; if the restoration lifts the remaining benefit above
        zero, an `EXHAUSTED` assistance automatically reverts to `ACTIVE`."

        Design: Difficulty/transitive_cascade/spoil_reversal_cascade_restores_benefit_and_accumulator
        """
        ctx, fill = self._setup_shipped_fill()
        spoiled = spoil(fill["id"], reason="temperature excursion")
        assert spoiled["status"] == "SPOILED"

        data, _ = validate_paginated(api_client.list_copay_assistances(
            ctx["enrollment"]["id"], FC))
        card = data[0]
        assert card["remaining_annual_benefit_cents"] == 100_000, \
            "the 15000 disbursement is credited back"
        assert card["disbursed_cents"] == 0

    def test_spoil_rolls_back_payer_accumulator(self):
        """PRD section 3.6: "Second, the enrollment's
        `payer_accumulated_oop_cents` is reduced by the fill's
        `payer_accumulator_delta_cents`, never dropping below zero, and
        `remaining_oop_cents` is recomputed from the new total."

        Design: Difficulty/transitive_cascade/spoil_reversal_cascade_restores_benefit_and_accumulator
        """
        ctx, fill = self._setup_shipped_fill()
        spoil(fill["id"], reason="temperature excursion")
        enr = get_enrollment(ctx["enrollment"]["id"])
        assert enr["payer_accumulated_oop_cents"] == 0, \
            "the 20000 accrual is rolled back by the reversal"
        assert enr["remaining_oop_cents"] == 500_000


class TestPayerOopPartitionIdentity:

    def _setup_accumulator_card_fill(self):
        ctx = create_approved_with_card(
            patient_ref="PAT-S",
            bi_overrides={"plan_has_accumulator": True,
                          "patient_cost_share_cents": 20_000,
                          "oop_max_cents": 500_000})
        fill = request_shipment(
            ctx["enrollment"]["id"], requested_delivery_date="2026-08-03")
        return ctx, fill

    def test_partition_identity_holds_after_ship(self):
        """PRD section 3.6: "The enrollment then accrues:
        `payer_accumulated_oop_cents` becomes the smaller of the
        investigation's `oop_max_cents` and its prior value plus the delta,
        and `remaining_oop_cents` is recomputed as `oop_max_cents` minus the
        accumulated total."
        PRD section 3.6: "Under an accumulator plan
        (`plan_has_accumulator` true), manufacturer assistance is excluded
        from the patient's out-of-pocket accrual, so
        `payer_accumulator_delta_cents` equals `patient_pay_cents`."

        Design: Difficulty/compensating_invariant/payer_oop_partition_identity
        """
        ctx, fill = self._setup_accumulator_card_fill()
        ship(fill["id"])
        enr = get_enrollment(ctx["enrollment"]["id"])
        assert enr["payer_accumulated_oop_cents"] == 5_000
        assert enr["remaining_oop_cents"] == 495_000
        assert (enr["payer_accumulated_oop_cents"]
                + enr["remaining_oop_cents"]) == 500_000, \
            "the partition sums to the OOP maximum"

    def test_partition_identity_restored_after_compensating_spoil(self):
        """PRD section 3.6: "Second, the enrollment's
        `payer_accumulated_oop_cents` is reduced by the fill's
        `payer_accumulator_delta_cents`, never dropping below zero, and
        `remaining_oop_cents` is recomputed from the new total."
        PRD section 3.6: "The enrollment then accrues:
        `payer_accumulated_oop_cents` becomes the smaller of the
        investigation's `oop_max_cents` and its prior value plus the delta,
        and `remaining_oop_cents` is recomputed as `oop_max_cents` minus the
        accumulated total."

        Design: Difficulty/compensating_invariant/payer_oop_partition_identity
        """
        ctx, fill = self._setup_accumulator_card_fill()
        ship(fill["id"])
        spoil(fill["id"], reason="excursion")
        enr = get_enrollment(ctx["enrollment"]["id"])
        assert enr["payer_accumulated_oop_cents"] == 0
        assert enr["remaining_oop_cents"] == 500_000, \
            "the partition identity is restored with zero drift"


class TestImmediateConsistency:

    def test_ship_response_shows_split_and_read_after_write_agrees(self):
        """PRD section 3.6: "At ship time the financial split runs against
        the shipment's frozen `patient_cost_share_cents`, and its three
        outputs — `assistance_pay_cents`, `patient_pay_cents`, and
        `payer_accumulator_delta_cents` — are null until the shipment
        reaches `SHIPPED`, at which point they are stamped onto it:"
        PRD section 2.2: "Unless otherwise noted, operations that create or
        modify a resource will return the created or updated resource object
        in the data field."
        PRD section 3.6: "The same ship event debits the assistance: its
        `remaining_annual_benefit_cents` decreases by the assistance portion
        and its `disbursed_cents` increases by the same amount, firing the
        `EXHAUSTED` transition if the remainder reaches exactly zero."

        Design: Corner/consistency_model/immediate_consistency_ship_response_shows_split
        """
        ctx = create_approved_with_card(
            patient_ref="PAT-IM",
            bi_overrides={"plan_has_accumulator": False,
                          "patient_cost_share_cents": 20_000})
        fill = request_shipment(
            ctx["enrollment"]["id"], requested_delivery_date="2026-08-03")
        resp = api_client.ship_shipment(fill["id"], RX)
        shipped = validate_success(resp, expected_status=200)
        assert_shipment(shipped)
        assert shipped["assistance_pay_cents"] == 15_000
        assert shipped["patient_pay_cents"] == 5_000
        assert shipped["payer_accumulator_delta_cents"] == 20_000

        data, _ = validate_paginated(api_client.list_copay_assistances(
            ctx["enrollment"]["id"], FC))
        assert data[0]["remaining_annual_benefit_cents"] == 85_000, \
            "the debit is already applied on read-after-write"
        assert data[0]["disbursed_cents"] == 15_000
