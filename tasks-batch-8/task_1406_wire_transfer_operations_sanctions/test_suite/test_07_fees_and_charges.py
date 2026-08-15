"""Fee assessment: the tiered base fee, priority surcharge, beneficiary-pays
branch, per-charge rounding order, variant input sets, kind gating, and the
billing lifecycle."""
from test_helpers import (
    ApiErrorId,
    assert_fee_assessment,
    assert_wire,
    assess_fee,
    create_approved_wire,
    create_executed_wire,
    create_wire,
    dual_approve_wire,
    list_wire_fees,
    post_charge,
    release_wire,
    setup_wire_room,
    submit_wire,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS

OPERATOR = TEST_USERS["wire_operator_headers"]


class TestVariantInputSets:
    def test_fee_provisional_vs_final_diverge_on_charge_input_set(self, api):
        """PRD §3.7: "The `PROVISIONAL` variant — a pre-execution estimate,
        and the only kind allowed while the wire is not yet `EXECUTED` or
        `RECALLED` — restricts its input set to charges whose `source` is
        `PROVISIONAL_ESTIMATE`, excluding actual advices. The `FINAL` variant
        — produced automatically at execution and again on any post-execution
        re-assessment — restricts its input set to charges whose `source` is
        `ACTUAL_ADVICE`, excluding estimates (which execution has in any case
        superseded)."
        PRD §3.5: "The wire's `fee_assessed_cents` is set to that final
        assessment's total, and its `net_principal_cents` is computed as the
        wire's `amount_cents` minus the sum of the amounts of `POSTED` charges
        whose `charge_type` is `DEDUCTED_FROM_PRINCIPAL`."

        Same wire, same formula: the PROVISIONAL estimate (one 1000-cent
        DEDUCTED estimate) totals 3000; the FINAL at execution (4000 OUR +
        2000 DEDUCTED advices) totals 7500 and supersedes the provisional.

        Design: Difficulty/dual_variant_calc/fee_provisional_vs_final_diverge_on_charge_input_set
        """
        room = setup_wire_room(business_date="2026-08-03")
        account = room["account"]
        beneficiary = room["beneficiary"]
        wire = create_wire(account["id"], beneficiary["id"], 1000000,
                           purpose="invoice 44")

        post_charge(wire["id"], correspondent_name="CorrBank Est",
                    charge_type="DEDUCTED_FROM_PRINCIPAL", amount_cents=1000,
                    source="PROVISIONAL_ESTIMATE")
        provisional = assess_fee(wire["id"], kind="PROVISIONAL")
        assert_fee_assessment(provisional)
        assert provisional["kind"] == "PROVISIONAL"
        assert provisional["total_fee_cents"] == 3000, (
            f"2500 base + round_half_up(1000*0.50)=500; actual advices "
            f"excluded; got {provisional['total_fee_cents']}")

        wire = submit_wire(wire["id"], "2026-08-03")
        wire = dual_approve_wire(wire["id"])
        post_charge(wire["id"], correspondent_name="CorrBank",
                    charge_type="OUR", amount_cents=4000, source="ACTUAL_ADVICE")
        post_charge(wire["id"], correspondent_name="CorrBank",
                    charge_type="DEDUCTED_FROM_PRINCIPAL", amount_cents=2000,
                    source="ACTUAL_ADVICE")

        executed = release_wire(wire["id"])
        assert executed["status"] == "EXECUTED"
        assert executed["fee_assessed_cents"] == 7500, (
            f"2500 + 4000*1.00 + round_half_up(2000*0.50)=1000; estimates "
            f"excluded; got {executed['fee_assessed_cents']}")
        assert executed["net_principal_cents"] == 998000, (
            f"1000000 - 2000 deducted; got {executed['net_principal_cents']}")

        fees = list_wire_fees(wire["id"])
        assert len(fees) == 2, f"provisional + final, got {len(fees)}"
        prov_after, final = fees[0], fees[1]
        assert prov_after["id"] == provisional["id"]
        assert prov_after["status"] == "SUPERSEDED", (
            "execution supersedes the OPEN provisional assessment")
        assert final["kind"] == "FINAL"
        assert final["status"] == "OPEN"
        assert final["total_fee_cents"] == 7500
        assert prov_after["total_fee_cents"] != final["total_fee_cents"]

    def test_provisional_assessment_excludes_actual_advices(self, api):
        """PRD §3.7: "The `PROVISIONAL` variant — a pre-execution estimate,
        and the only kind allowed while the wire is not yet `EXECUTED` or
        `RECALLED` — restricts its input set to charges whose `source` is
        `PROVISIONAL_ESTIMATE`, excluding actual advices."
        PRD §3.7: "an actual advice may be posted only while the wire is in
        `PENDING_APPROVAL`, `REPAIR`, `APPROVED`, `EXECUTED`, or `RECALLED`;
        posting outside the allowed window is `ERR_INVALID_STATE`."

        With an ACTUAL_ADVICE charge (700 OUR) and a PROVISIONAL_ESTIMATE
        charge (1000 DEDUCTED) both POSTED pre-execution, the provisional
        assessment counts only the estimate: 2500 + 500 = 3000.

        Design: Difficulty/dual_variant_calc/fee_provisional_vs_final_diverge_on_charge_input_set
        """
        room = setup_wire_room(business_date="2026-08-03")
        wire = create_wire(room["account"]["id"], room["beneficiary"]["id"],
                           1000000, purpose="input set probe")
        wire = submit_wire(wire["id"], "2026-08-03")
        post_charge(wire["id"], correspondent_name="CorrAdv",
                    charge_type="OUR", amount_cents=700, source="ACTUAL_ADVICE")
        post_charge(wire["id"], correspondent_name="CorrEst",
                    charge_type="DEDUCTED_FROM_PRINCIPAL", amount_cents=1000,
                    source="PROVISIONAL_ESTIMATE")

        provisional = assess_fee(wire["id"], kind="PROVISIONAL")
        assert provisional["correspondent_share_cents"] == 500, (
            f"only the estimate enters the provisional input set; got "
            f"{provisional['correspondent_share_cents']}")
        assert provisional["total_fee_cents"] == 3000


class TestTieredComponents:
    def test_fee_full_stack_tiered_components(self, api):
        """PRD §3.7: "First, the base fee is read from the payment rail:
        twenty-five dollars for `Fedwire`, thirty-five dollars for `SWIFT`,
        and eighteen dollars for `CHIPS` — recorded as `base_fee_cents`.
        Second, the priority surcharge is ten dollars when the wire's
        `priority` is `SAME_DAY` and zero for `NORMAL`, recorded as
        `priority_fee_cents`. Third, the beneficiary-pays share
        `beneficiary_share_cents` applies only when the wire's `method` is
        `SWIFT` **and** its `charge_mode` is `BENEFICIARY_REMUNERATION`: it is
        forty percent of the base fee, rounded half-up to whole cents"
        PRD §3.7: "for a charge of type `DEDUCTED_FROM_PRINCIPAL`, half the
        charge amount rounded half-up to whole cents; for a charge of type
        `OUR`, the full charge amount"

        SWIFT + SAME_DAY + BENEFICIARY_REMUNERATION with a 3000 DEDUCTED and
        a 2500 OUR advice: 3500 + 1000 + 1400 + (1500 + 2500) = 9900.

        Design: Difficulty/combinatorial_formula/fee_full_stack_tiered_components
        """
        room = setup_wire_room(business_date="2026-08-05")
        wire = create_executed_wire(
            room["account"]["id"], room["beneficiary"]["id"], "2026-08-05",
            5000000, method="SWIFT", priority="SAME_DAY",
            charge_mode="BENEFICIARY_REMUNERATION", purpose="machinery",
            charges=[
                {"correspondent_name": "CorrA",
                 "charge_type": "DEDUCTED_FROM_PRINCIPAL", "amount_cents": 3000,
                 "source": "ACTUAL_ADVICE"},
                {"correspondent_name": "CorrB", "charge_type": "OUR",
                 "amount_cents": 2500, "source": "ACTUAL_ADVICE"},
            ])
        assert_wire(wire)
        assert wire["status"] == "EXECUTED"
        assert wire["net_principal_cents"] == 4997000, (
            f"5000000 - 3000 deducted; got {wire['net_principal_cents']}")

        fees = list_wire_fees(wire["id"])
        assert len(fees) == 1
        fee = fees[0]
        assert_fee_assessment(fee)
        assert fee["base_fee_cents"] == 3500, "SWIFT tier"
        assert fee["priority_fee_cents"] == 1000, "SAME_DAY surcharge"
        assert fee["beneficiary_share_cents"] == 1400, (
            f"round_half_up(3500 * 0.40); got {fee['beneficiary_share_cents']}")
        assert fee["correspondent_share_cents"] == 4000, (
            f"round_half_up(3000*0.50)=1500 + 2500*1.00=2500; got "
            f"{fee['correspondent_share_cents']}")
        assert fee["total_fee_cents"] == 9900
        assert wire["fee_assessed_cents"] == 9900

    def test_beneficiary_share_requires_swift_and_beneficiary_remuneration(self, api):
        """PRD §3.7: "Third, the beneficiary-pays share
        `beneficiary_share_cents` applies only when the wire's `method` is
        `SWIFT` **and** its `charge_mode` is `BENEFICIARY_REMUNERATION`: it is
        forty percent of the base fee, rounded half-up to whole cents; under
        any other combination it is zero."

        The same SWIFT SAME_DAY wire with charge_mode OUR drops the
        beneficiary share entirely: 3500 + 1000 + 0 + 4000 = 8500.

        Design: Difficulty/combinatorial_formula/fee_full_stack_tiered_components
        """
        room = setup_wire_room(business_date="2026-08-05")
        wire = create_executed_wire(
            room["account"]["id"], room["beneficiary"]["id"], "2026-08-05",
            5000000, method="SWIFT", priority="SAME_DAY", charge_mode="OUR",
            purpose="machinery",
            charges=[
                {"correspondent_name": "CorrA",
                 "charge_type": "DEDUCTED_FROM_PRINCIPAL", "amount_cents": 3000,
                 "source": "ACTUAL_ADVICE"},
                {"correspondent_name": "CorrB", "charge_type": "OUR",
                 "amount_cents": 2500, "source": "ACTUAL_ADVICE"},
            ])
        fees = list_wire_fees(wire["id"])
        assert len(fees) == 1
        fee = fees[0]
        assert fee["base_fee_cents"] == 3500
        assert fee["priority_fee_cents"] == 1000
        assert fee["beneficiary_share_cents"] == 0, (
            f"charge_mode OUR keeps the beneficiary share at zero; got "
            f"{fee['beneficiary_share_cents']}")
        assert fee["correspondent_share_cents"] == 4000
        assert fee["total_fee_cents"] == 8500


class TestPerChargeRoundingOrder:
    def test_fee_per_charge_rounding_order_pinned(self, api):
        """PRD §3.7: "Each charge's product is rounded half-up individually
        before summation."
        PRD §3.7: "Fifth, `total_fee_cents` is the sum of the base fee, the
        priority surcharge, the beneficiary share, and the correspondent share
        — and the total is **not** rounded again; the pinned order is per-line
        rounding, then summation, and rounding only the final sum is a
        rejected alternative."

        Two 999-cent DEDUCTED estimates: per-charge rounding yields
        500 + 500 = 1000; the rejected sum-then-round order would yield
        round_half_up(1998 * 0.50) = 999. Totals 3500 vs 3499 discriminate.

        Design: Difficulty/combinatorial_formula/fee_per_charge_rounding_order_pinned
        """
        room = setup_wire_room()
        wire = create_wire(room["account"]["id"], room["beneficiary"]["id"],
                           1000000, purpose="rounding probe")
        post_charge(wire["id"], correspondent_name="CorrX",
                    charge_type="DEDUCTED_FROM_PRINCIPAL", amount_cents=999,
                    source="PROVISIONAL_ESTIMATE")
        post_charge(wire["id"], correspondent_name="CorrY",
                    charge_type="DEDUCTED_FROM_PRINCIPAL", amount_cents=999,
                    source="PROVISIONAL_ESTIMATE")

        fee = assess_fee(wire["id"], kind="PROVISIONAL")
        assert_fee_assessment(fee)
        assert fee["correspondent_share_cents"] == 1000, (
            f"round_half_up(999*0.50)=500 per charge, summed; got "
            f"{fee['correspondent_share_cents']}")
        assert fee["total_fee_cents"] == 3500

    def test_per_charge_rounding_discriminates_on_mixed_odd_lines(self, api):
        """PRD §3.7: "Each charge's product is rounded half-up individually
        before summation."
        PRD §2.10: "Rounding is never deferred to a final total: each charge
        line is rounded independently, then the rounded lines are summed."

        A 999-cent line and a 1-cent line: per-line rounding yields
        500 + 1 = 501; sum-then-round would yield round_half_up(1000*0.50) =
        500. Totals 3001 vs 3000 discriminate.

        Design: Difficulty/combinatorial_formula/fee_per_charge_rounding_order_pinned
        """
        room = setup_wire_room()
        wire = create_wire(room["account"]["id"], room["beneficiary"]["id"],
                           1000000, purpose="rounding probe two")
        post_charge(wire["id"], correspondent_name="CorrX",
                    charge_type="DEDUCTED_FROM_PRINCIPAL", amount_cents=999,
                    source="PROVISIONAL_ESTIMATE")
        post_charge(wire["id"], correspondent_name="CorrY",
                    charge_type="DEDUCTED_FROM_PRINCIPAL", amount_cents=1,
                    source="PROVISIONAL_ESTIMATE")

        fee = assess_fee(wire["id"], kind="PROVISIONAL")
        assert fee["correspondent_share_cents"] == 501, (
            f"500 + round_half_up(1*0.50)=1; got "
            f"{fee['correspondent_share_cents']}")
        assert fee["total_fee_cents"] == 3001


class TestEmptyChargeSet:
    def test_fee_components_chips_normal_no_charges(self, api):
        """PRD §3.7: "First, the base fee is read from the payment rail:
        twenty-five dollars for `Fedwire`, thirty-five dollars for `SWIFT`,
        and eighteen dollars for `CHIPS` — recorded as `base_fee_cents`."
        PRD §3.5: "The wire's `fee_assessed_cents` is set to that final
        assessment's total, and its `net_principal_cents` is computed as the
        wire's `amount_cents` minus the sum of the amounts of `POSTED` charges
        whose `charge_type` is `DEDUCTED_FROM_PRINCIPAL`."

        A CHIPS NORMAL wire with charge_mode OUR and zero charges assesses
        exactly the 1800-cent CHIPS base; net principal equals the amount.

        Design: Corner/calculations/fee_components_chips_normal_no_charges
        """
        room = setup_wire_room(business_date="2026-09-15")
        wire = create_executed_wire(
            room["account"]["id"], room["beneficiary"]["id"], "2026-09-15",
            500000, method="CHIPS", purpose="fee zero")
        assert wire["fee_assessed_cents"] == 1800
        assert wire["net_principal_cents"] == 500000

        fees = list_wire_fees(wire["id"])
        assert len(fees) == 1
        fee = fees[0]
        assert_fee_assessment(fee)
        assert fee["kind"] == "FINAL"
        assert fee["base_fee_cents"] == 1800
        assert fee["priority_fee_cents"] == 0
        assert fee["beneficiary_share_cents"] == 0
        assert fee["correspondent_share_cents"] == 0
        assert fee["total_fee_cents"] == 1800


class TestFeeKindGating:
    def test_fee_assessment_kind_state_gating(self, api):
        """PRD §3.7: "a `PROVISIONAL` request requires the wire to be in
        `INITIATED`, `CALLBACK_PENDING`, `PENDING_APPROVAL`, `REPAIR`, or
        `APPROVED`, and a `FINAL` request requires `EXECUTED` or `RECALLED`;
        mismatches are `ERR_INVALID_STATE`."

        FINAL is rejected while the wire is APPROVED; PROVISIONAL is rejected
        once the wire is EXECUTED.

        Design: Corner/calculations/fee_assessment_kind_state_gating
        """
        room = setup_wire_room(business_date="2026-09-16")
        wire = create_approved_wire(
            room["account"]["id"], room["beneficiary"]["id"], "2026-09-16",
            500000, purpose="gating probe")

        resp_final = api.assess_fee(wire["id"], {"kind": "FINAL"}, OPERATOR)
        validate_error(resp_final, ApiErrorId.ERR_INVALID_STATE)

        executed = release_wire(wire["id"])
        assert executed["status"] == "EXECUTED"

        resp_prov = api.assess_fee(wire["id"], {"kind": "PROVISIONAL"}, OPERATOR)
        validate_error(resp_prov, ApiErrorId.ERR_INVALID_STATE)


class TestFeeBillingLifecycle:
    def test_fee_bill_happy_and_rebill_rejected(self, api):
        """PRD §3.7: "An `OPEN` assessment may be billed by an operator, but
        only when the linked wire is `EXECUTED` or `RECALLED` — billing
        otherwise is `ERR_INVALID_STATE` — moving the assessment to `BILLED`
        and writing an audit entry."

        Billing the auto-created FINAL assessment succeeds once; the second
        bill hits the state precondition.

        Design: Corner/endpoints/fee_bill_happy_and_rebill_rejected
        """
        room = setup_wire_room(business_date="2026-09-28")
        wire = create_executed_wire(
            room["account"]["id"], room["beneficiary"]["id"], "2026-09-28",
            200000, purpose="bill probe")
        fees = list_wire_fees(wire["id"])
        assert len(fees) == 1
        fee = fees[0]
        assert fee["status"] == "OPEN"

        billed = validate_success(api.bill_fee(fee["id"], OPERATOR), 200)
        assert_fee_assessment(billed)
        assert billed["status"] == "BILLED"

        resp = api.bill_fee(fee["id"], OPERATOR)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
