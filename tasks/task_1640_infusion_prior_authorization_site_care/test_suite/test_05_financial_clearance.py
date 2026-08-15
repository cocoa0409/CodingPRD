"""Financial clearance and the patient-responsibility waterfall: method
variants, per-line rounding, oop cap, add/void conservation, clear gates."""
from test_helpers import (
    ApiErrorId,
    add_line_item,
    assert_financial_clearance,
    assert_line_item,
    create_clearance,
    get_clearance,
    setup_approved_request,
    setup_approved_with_clearance,
    validate_error,
    validate_success,
    void_line_item,
    FINANCE_SPECIALIST_2_HEADERS,
    FINANCE_SPECIALIST_HEADERS,
)


class TestClearanceCreation:
    def test_initial_estimate_zero_over_no_lines(self, api):
        """PRD §3.6: "The new clearance's `method` is derived from the policy
        — `ACCUMULATOR_METHOD` when the policy's `allowed_amount_known` is
        true, `BILLED_CHARGES_METHOD` when false — its status is born
        `ESTIMATED`, the opening specialist is recorded in
        `estimated_by_user_id`, and an initial estimate is computed
        immediately over zero line items."

        Design: Corner/entities/clearance_create_initial_estimate_zero
        """
        ws = setup_approved_request(drug_code="J9102", member_id="M1102")
        clearance = validate_success(api.create_financial_clearance(
            ws["auth"]["id"], FINANCE_SPECIALIST_HEADERS), 201)
        assert_financial_clearance(clearance)
        assert clearance["estimated_patient_responsibility_cents"] == 0
        assert clearance["method"] == "ACCUMULATOR_METHOD"
        assert clearance["status"] == "ESTIMATED"
        assert clearance["estimated_by_user_id"] == "fin-1"

    def test_second_open_clearance_rejected(self, api):
        """PRD §3.6: "Uniqueness is enforced across open records: if the
        request already has a clearance in `ESTIMATED` or `CLEARED` status,
        creation is rejected with `ERR_DUPLICATE_OPEN_CLEARANCE` (409)."

        Design: Corner/validations/duplicate_open_clearance_rejected
        """
        ws = setup_approved_with_clearance(drug_code="J9151",
                                           member_id="M1151")
        resp = api.create_financial_clearance(
            ws["auth"]["id"], FINANCE_SPECIALIST_2_HEADERS)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_OPEN_CLEARANCE)

        clearances = validate_success(api.list_financial_clearances(
            ws["auth"]["id"], FINANCE_SPECIALIST_HEADERS))
        assert len(clearances) == 1, (
            "Exactly one clearance exists for the request")


class TestMethodVariants:
    def _build_variant_pair(self, api):
        """Two approved requests under policies differing only in
        allowed_amount_known, with identical accumulator patients and an
        identical line-item set on each clearance."""
        common = {
            "payer_code": "PAYERX", "validity_days": 90, "max_course_days": 60,
            "max_dose_mg": 1000, "deductible_cents": 100000,
            "coinsurance_pct": 0.20, "oop_max_cents": 500000,
            "prepay_limit_cents": 250000,
        }
        ws_a = setup_approved_with_clearance(
            drug_code="J9001", member_id="M100A",
            policy_overrides={**common, "regimen_name": "DrugA q4w"},
            patient_overrides={"full_name": "Pat Alpha",
                               "deductible_remaining_cents": 50000,
                               "oop_remaining_cents": 300000},
            line_items=(("drug", 200000, 250000), ("admin", 100000, 120000)))
        ws_b = setup_approved_with_clearance(
            drug_code="J9002", member_id="M100B",
            policy_overrides={**common, "regimen_name": "DrugA q4w",
                              "allowed_amount_known": False,
                              "discount_rate": 1.00},
            patient_overrides={"full_name": "Pat Beta",
                               "deductible_remaining_cents": 50000,
                               "oop_remaining_cents": 300000},
            line_items=(("drug", 200000, 250000), ("admin", 100000, 120000)))
        return ws_a, ws_b

    def test_accumulator_vs_billed_charges_estimates_diverge(self, api):
        """PRD §3.6: "For each line, a base amount is established first: under
        `ACCUMULATOR_METHOD` the base is the line's `allowed_amount_cents`;
        under `BILLED_CHARGES_METHOD` the base is the line's
        `billed_charges_cents` multiplied by the policy's `discount_rate`,
        rounded half-up to whole cents."
        PRD §3.6: "Because the two methods differ only in how the base is
        derived, identical line inputs yield a different estimate whenever
        billed charges and allowed amounts diverge; the policy's
        `deductible_cents` and `oop_max_cents` remain plan reference values
        and do not enter this waterfall."

        Design: Difficulty/dual_variant_calc/responsibility_accumulator_vs_billed_variant
        """
        ws_a, ws_b = self._build_variant_pair(api)

        fc_a = get_clearance(ws_a["clearance"]["id"])
        fc_b = get_clearance(ws_b["clearance"]["id"])
        assert fc_a["method"] == "ACCUMULATOR_METHOD"
        assert fc_b["method"] == "BILLED_CHARGES_METHOD"

        lines_a = validate_success(api.list_line_items(
            fc_a["id"], FINANCE_SPECIALIST_HEADERS))
        lines_b = validate_success(api.list_line_items(
            fc_b["id"], FINANCE_SPECIALIST_HEADERS))
        # ACCUMULATOR: L1 ded 50000 + coins 30000 = 80000; L2 coins 20000.
        assert [line["patient_share_cents"] for line in lines_a] == [80000, 20000]
        # BILLED (discount 1.00): L1 base 250000 -> 50000 + 40000 = 90000;
        # L2 base 120000 -> 24000.
        assert [line["patient_share_cents"] for line in lines_b] == [90000, 24000]

        assert fc_a["estimated_patient_responsibility_cents"] == 100000
        assert fc_b["estimated_patient_responsibility_cents"] == 114000
        assert (fc_a["estimated_patient_responsibility_cents"]
                != fc_b["estimated_patient_responsibility_cents"])

    def test_variant_divergence_persists_after_void(self, api):
        """PRD §3.6: "Voiding flips the line to `VOIDED`, and both additions
        and voids recompute the clearance estimate."
        PRD §3.6: "Because the two methods differ only in how the base is
        derived, identical line inputs yield a different estimate whenever
        billed charges and allowed amounts diverge; the policy's
        `deductible_cents` and `oop_max_cents` remain plan reference values
        and do not enter this waterfall."

        Design: Difficulty/dual_variant_calc/responsibility_accumulator_vs_billed_variant
        """
        ws_a, ws_b = self._build_variant_pair(api)

        # Void the second line on both clearances.
        void_line_item(ws_a["line_items"][1]["id"])
        void_line_item(ws_b["line_items"][1]["id"])

        fc_a = get_clearance(ws_a["clearance"]["id"])
        fc_b = get_clearance(ws_b["clearance"]["id"])
        # Only the first line remains active on each side.
        assert fc_a["estimated_patient_responsibility_cents"] == 80000
        assert fc_b["estimated_patient_responsibility_cents"] == 90000
        assert (fc_a["estimated_patient_responsibility_cents"]
                != fc_b["estimated_patient_responsibility_cents"])


class TestPerLineRounding:
    def test_per_line_rounding_then_sum(self, api):
        """PRD §2.6: "The patient-responsibility waterfall rounds per line
        item to whole cents and only then sums the per-line shares."
        PRD §3.6: "The line's `patient_share_cents` is the applied deductible
        plus the coinsurance — rounding happens per line, and only then are
        the per-line shares summed, in the same pinned order."

        Design: Difficulty/combinatorial_formula/responsibility_per_line_rounding_then_sum
        """
        ws = setup_approved_with_clearance(
            drug_code="J9013", member_id="M303",
            policy_overrides={"deductible_cents": 0, "coinsurance_pct": 0.20},
            patient_overrides={"deductible_remaining_cents": 0,
                               "oop_remaining_cents": 900000},
            line_items=(("L1", 33333, 33333), ("L2", 33333, 33333),
                        ("L3", 33333, 33333)))
        lines = validate_success(api.list_line_items(
            ws["clearance"]["id"], FINANCE_SPECIALIST_HEADERS))
        for line in lines:
            # round_half_up(33333 * 0.20) = round_half_up(6666.6) = 6667
            assert line["patient_share_cents"] == 6667
        clearance = get_clearance(ws["clearance"]["id"])
        assert clearance["estimated_patient_responsibility_cents"] == 20001, (
            "3 x 6667 = 20001; sum-then-round would incorrectly give 20000")

    def test_deductible_consumed_oldest_first_with_per_line_rounding(self, api):
        """PRD §3.6: "Only `ACTIVE` line items participate, processed in
        creation order, oldest first."
        PRD §3.6: "The deductible applied to the line is the smaller of that
        base and the remaining deductible balance, and the running balance is
        reduced by the applied amount."

        Design: Difficulty/combinatorial_formula/responsibility_per_line_rounding_then_sum
        """
        ws = setup_approved_with_clearance(
            drug_code="J9014", member_id="M304",
            policy_overrides={"deductible_cents": 100000,
                              "coinsurance_pct": 0.20},
            patient_overrides={"deductible_remaining_cents": 5000,
                               "oop_remaining_cents": 900000},
            line_items=(("L1", 33333, 33333), ("L2", 33333, 33333),
                        ("L3", 33333, 33333)))
        lines = validate_success(api.list_line_items(
            ws["clearance"]["id"], FINANCE_SPECIALIST_HEADERS))
        # Oldest line absorbs the 5000 deductible:
        # L1: 5000 + round_half_up(28333 * 0.2) = 5000 + 5667 = 10667
        # L2/L3: round_half_up(33333 * 0.2) = 6667 each
        assert [line["patient_share_cents"] for line in lines] == [
            10667, 6667, 6667]
        clearance = get_clearance(ws["clearance"]["id"])
        assert clearance["estimated_patient_responsibility_cents"] == 24001


class TestAddVoidConservation:
    def test_add_then_void_restores_estimate(self, api):
        """PRD §3.6: "Voiding flips the line to `VOIDED`, and both additions
        and voids recompute the clearance estimate."
        PRD §3.6: "Only `ACTIVE` line items participate, processed in creation
        order, oldest first."

        Design: Difficulty/compensating_invariant/line_item_add_void_conserves_estimate
        """
        ws = setup_approved_with_clearance(drug_code="J9082",
                                           member_id="M1002")
        assert ws["clearance"]["estimated_patient_responsibility_cents"] == 0

        line = add_line_item(ws["clearance"]["id"], "drug", 100000, 100000)
        assert_line_item(line)
        # deductible 50000 + coinsurance round_half_up(50000 * 0.20) = 10000
        assert line["patient_share_cents"] == 60000
        mid = get_clearance(ws["clearance"]["id"])
        assert mid["estimated_patient_responsibility_cents"] == 60000

        voided = void_line_item(line["id"])
        assert voided["status"] == "VOIDED"
        final = get_clearance(ws["clearance"]["id"])
        assert final["estimated_patient_responsibility_cents"] == 0, (
            "The add/void pair conserves the estimate (no drift)")

    def test_void_rebuilds_estimate_from_remaining_active_lines(self, api):
        """PRD §3.6: "The estimate itself is a deductible-then-coinsurance
        waterfall, rebuilt from scratch at clearance creation, on every
        line-item addition or void, and on every recompute."
        PRD §3.6: "Only `ACTIVE` line items participate, processed in creation
        order, oldest first."

        Design: Difficulty/compensating_invariant/line_item_add_void_conserves_estimate
        """
        ws = setup_approved_with_clearance(
            drug_code="J9083", member_id="M1003",
            line_items=(("L1", 100000, 100000), ("L2", 100000, 100000)))
        # L1: ded 50000 + coins 10000 = 60000; L2: coins 20000. Total 80000.
        assert ws["clearance"]["estimated_patient_responsibility_cents"] == 80000

        void_line_item(ws["line_items"][0]["id"])
        rebuilt = get_clearance(ws["clearance"]["id"])
        # Rebuilt from scratch over L2 alone: the 50000 deductible now applies
        # to L2 -> 50000 + round_half_up(50000 * 0.2) = 60000.
        assert rebuilt["estimated_patient_responsibility_cents"] == 60000


class TestClearanceClearing:
    def test_estimator_cannot_clear_own_clearance(self, api):
        """PRD §2.8: "Third, the `FinanceSpecialist` clearing a financial
        clearance must not be the specialist recorded as its
        `estimated_by_user_id`."
        PRD §3.6: "A `FinanceSpecialist` other than the one recorded in
        `estimated_by_user_id` performs it — same-operator clears are rejected
        with `ERR_SEGREGATION_OF_DUTIES`"

        Design: Corner/validations/sod_clearance_same_estimator_rejected
        """
        ws = setup_approved_with_clearance(
            drug_code="J9154", member_id="M1154",
            line_items=(("drug", 10000, 10000),))

        own = api.clear_financial_clearance(
            ws["clearance"]["id"], FINANCE_SPECIALIST_HEADERS)
        validate_error(own, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

        cleared = validate_success(api.clear_financial_clearance(
            ws["clearance"]["id"], FINANCE_SPECIALIST_2_HEADERS))
        assert cleared["status"] == "CLEARED"
        assert cleared["cleared_by_user_id"] == "fin-2"

    def test_estimate_above_prepay_limit_blocks_clear(self, api):
        """PRD §3.6: "the current `estimated_patient_responsibility_cents`
        must not exceed the policy's `prepay_limit_cents` (otherwise
        `ERR_PREPAY_LIMIT_EXCEEDED`, HTTP 402)"

        Design: Corner/validations/prepay_limit_exceeded_at_clear
        """
        six_lines = tuple((f"L{i}", 200000, 200000) for i in range(1, 7))
        ws = setup_approved_with_clearance(
            drug_code="J9152", member_id="M1152",
            patient_overrides={"deductible_remaining_cents": 50000,
                               "oop_remaining_cents": 900000},
            line_items=six_lines)
        # L1: 50000 + 30000 = 80000; L2..L6: 40000 each. Total 280000.
        assert ws["clearance"]["estimated_patient_responsibility_cents"] == 280000

        resp = api.clear_financial_clearance(
            ws["clearance"]["id"], FINANCE_SPECIALIST_2_HEADERS)
        validate_error(resp, ApiErrorId.ERR_PREPAY_LIMIT_EXCEEDED)

        after = get_clearance(ws["clearance"]["id"])
        assert after["status"] == "ESTIMATED", (
            "A refused clear leaves the clearance ESTIMATED")


class TestEstimateConsistency:
    def test_oop_remaining_caps_the_estimate(self, api):
        """PRD §3.6: "The clearance's
        `estimated_patient_responsibility_cents` is the smaller of that sum
        and the patient's `oop_remaining_cents`."

        Design: Corner/calculations/responsibility_estimate_capped_by_oop_remaining
        """
        ws = setup_approved_with_clearance(
            drug_code="J9121", member_id="M1121",
            policy_overrides={"deductible_cents": 0, "coinsurance_pct": 1.00},
            patient_overrides={"deductible_remaining_cents": 0,
                               "oop_remaining_cents": 150000},
            line_items=(("drug", 200000, 200000),))
        # Raw per-line share: 0 + round_half_up(200000 * 1.00) = 200000.
        assert ws["line_items"][0]["patient_share_cents"] == 200000
        clearance = get_clearance(ws["clearance"]["id"])
        assert clearance["estimated_patient_responsibility_cents"] == 150000, (
            "min(200000, oop_remaining 150000) = 150000")

    def test_recomputed_estimate_visible_immediately(self, api):
        """PRD §3.6: "Voiding flips the line to `VOIDED`, and both additions
        and voids recompute the clearance estimate."
        PRD §2.10: "Every step of every cascade is an independent mutation:
        each resource a cascade touches has its `version` incremented by one
        and its `updated_at` refreshed."

        Design: Corner/consistency_model/immediate_visibility_of_recomputed_estimate
        """
        ws = setup_approved_with_clearance(drug_code="J9190",
                                           member_id="M1190")
        line = add_line_item(ws["clearance"]["id"], "drug", 100000, 100000)
        assert line["patient_share_cents"] == 60000, (
            "The add response already carries the computed share")

        clearance = get_clearance(ws["clearance"]["id"])
        assert clearance["estimated_patient_responsibility_cents"] == 60000, (
            "The immediately following read shows the recomputed estimate")
