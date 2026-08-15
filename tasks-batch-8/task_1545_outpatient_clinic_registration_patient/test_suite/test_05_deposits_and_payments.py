"""Deposit tiering, point-of-service collection, refunds, and voids (PRD §3.5)."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    api_client,
    assert_appointment_invariants,
    create_patient_payload,
    create_payment_payload,
    create_prechecked_visit,
    get_appointment,
    get_success_data,
    post_payment,
    schedule_appointment,
    setup_low_vs_high_risk_estimates,
    setup_visit_with_payment,
    validate_error,
    validate_success,
)

REG = TEST_USERS["registrar_headers"]
FC = TEST_USERS["financial_counselor_headers"]
SUP = TEST_USERS["access_supervisor_headers"]


class TestDepositRiskTiering:
    def test_standard_deposit_tier_quarter_of_estimate(self, api):
        """PRD §3.5: "Below that threshold, a `NEW` visit owes fifty percent of
        the estimate, and any other visit type owes twenty-five percent."
        PRD §3.5: "The strike count comes from the same rule that feeds
        `no_show_risk_strikes`: the number of the patient's appointments in
        `NO_SHOW` status whose `scheduled_start` falls inside the trailing
        365-day half-open window ending at the as-of instant"

        Design: Difficulty/dual_variant_calc/deposit_rule_risk_adjusted_vs_standard
        """
        estimate_low, estimate_high = setup_low_vs_high_risk_estimates()
        # PAYER_VERIFIED: 30000 deductible + 20% of 70000 = 44000.
        assert estimate_low["estimated_patient_responsibility_cents"] == 44000
        # Zero trailing strikes, ESTABLISHED: 25% of 44000 = 11000.
        assert estimate_low["deposit_required_cents"] == 11000

    def test_high_risk_deposit_tier_full_estimate(self, api):
        """PRD §3.5: "With at least two strikes, the deposit target is the
        full estimate — one hundred percent of it."

        Design: Difficulty/dual_variant_calc/deposit_rule_risk_adjusted_vs_standard
        """
        estimate_low, estimate_high = setup_low_vs_high_risk_estimates()
        # Identical coverage inputs yield the same 44000 responsibility...
        assert estimate_high["estimated_patient_responsibility_cents"] == 44000
        # ...but two trailing NO_SHOW appointments push the deposit to 100%.
        assert estimate_high["deposit_required_cents"] == 44000


class TestRefunds:
    def test_refund_above_collected_rejected(self, api):
        """PRD §3.5: "A refund may not exceed the visit's current
        `amount_collected_cents`, although refunding down to exactly zero is
        allowed; an over-large refund is rejected with
        `ERR_REFUND_EXCEEDS_COLLECTED` (HTTP 422)."

        Design: Difficulty/boundary_precision_check/refund_to_exactly_zero_collected_allowed
        """
        ctx = setup_visit_with_payment(payment_amount=5000)
        res = api.create_payment(
            ctx["appointment"]["id"],
            create_payment_payload(amount_cents=5001, method="CARD", kind="REFUND"),
            FC,
        )
        validate_error(res, ApiErrorId.ERR_REFUND_EXCEEDS_COLLECTED)

    def test_refund_to_exactly_zero_allowed(self, api):
        """PRD §3.5: "A refund may not exceed the visit's current
        `amount_collected_cents`, although refunding down to exactly zero is
        allowed; an over-large refund is rejected with
        `ERR_REFUND_EXCEEDS_COLLECTED` (HTTP 422)."
        PRD §3.5: "it is the sum of `amount_cents` over the appointment's
        `POSTED` payments of kind POST, minus the sum over its `POSTED`
        payments of kind REFUND, clamped so it never falls below zero."

        Design: Difficulty/boundary_precision_check/refund_to_exactly_zero_collected_allowed
        """
        ctx = setup_visit_with_payment(payment_amount=5000)
        refund = api.create_payment(
            ctx["appointment"]["id"],
            create_payment_payload(amount_cents=5000, method="CARD", kind="REFUND"),
            FC,
        )
        validate_success(refund, 201)
        appt = get_appointment(ctx["appointment"]["id"])
        assert appt["amount_collected_cents"] == 0
        assert_appointment_invariants(appt)


class TestCollectedAmountInvariant:
    def test_payment_posting_immediately_visible(self, api):
        """PRD §3.5: "The collected total itself is recomputed in full — never
        adjusted incrementally — on every payment posting and every void: it is
        the sum of `amount_cents` over the appointment's `POSTED` payments of
        kind POST, minus the sum over its `POSTED` payments of kind REFUND,
        clamped so it never falls below zero."

        Design: Difficulty/compensating_invariant/payment_post_then_void_preserves_collected_amount
        """
        ctx = create_prechecked_visit(copay_cents=0, coinsurance_pct=20)
        appointment_id = ctx["appointment"]["id"]
        collected_pre = get_appointment(appointment_id)["amount_collected_cents"]
        assert collected_pre == 0

        post_payment(appointment_id, 5000, method="CASH")
        collected_mid = get_appointment(appointment_id)["amount_collected_cents"]
        assert collected_mid == 5000

    def test_void_restores_collected_amount(self, api):
        """PRD §3.5: "An `AccessSupervisor` may void a `POSTED` payment —
        `POSTED` → `VOIDED` — which recomputes the collected total and the
        clearance gate in exactly the same way."

        Design: Difficulty/compensating_invariant/payment_post_then_void_preserves_collected_amount
        """
        ctx = create_prechecked_visit(copay_cents=0, coinsurance_pct=20)
        appointment_id = ctx["appointment"]["id"]
        collected_pre = get_appointment(appointment_id)["amount_collected_cents"]

        payment = post_payment(appointment_id, 5000, method="CASH")
        validate_success(api.void_payment(payment["id"], SUP), 200)

        collected_post = get_appointment(appointment_id)["amount_collected_cents"]
        assert collected_post == collected_pre == 0

    def test_collected_amount_immediate_consistency(self, api):
        """PRD §2.8: "Recomputation is immediate, never deferred to a batch."
        PRD §3.5: "it is the sum of `amount_cents` over the appointment's
        `POSTED` payments of kind POST, minus the sum over its `POSTED`
        payments of kind REFUND, clamped so it never falls below zero."

        Design: Corner/consistency_model/immediate_consistency_collected_amount_in_same_response
        """
        patient = get_success_data(
            api_client.create_patient(
                create_patient_payload(
                    first_name="Imm",
                    last_name="Ediate",
                    date_of_birth="1990-10-10",
                    sex_at_birth="M",
                    primary_phone="+15551800001",
                ),
                REG,
            )
        )
        appt = schedule_appointment(
            patient["id"], scheduled_start="2026-09-30T09:00:00Z", provider_code="DRIM"
        )
        pay_res = api_client.create_payment(
            appt["id"],
            create_payment_payload(amount_cents=2500, method="CARD", kind="POST"),
            FC,
        )
        validate_success(pay_res, 201)
        appt_after = get_appointment(appt["id"])
        assert appt_after["amount_collected_cents"] == 2500


class TestDepositShortfallGate:
    def test_deposit_shortfall_blocks_mark_ready(self, api):
        """PRD §3.5: "Only then does the collection requirement fire, rejecting
        with `ERR_DEPOSIT_SHORTFALL` (HTTP 402) while collected funds remain
        below the deposit target."
        PRD §3.5: "A `FinancialCounselor` moves a `PRE_CHECKED` visit to
        `READY` only when the gate allows it: either `registration_gate` is
        `CLEAR`, or it is `CLEAR_WITH_PAYMENT` and `amount_collected_cents` has
        reached the `deposit_required_cents` of the latest non-`SUPERSEDED`
        estimate."

        Design: Corner/validations/deposit_shortfall_blocks_mark_ready
        """
        ctx = create_prechecked_visit(
            deductible_remaining_cents=30000,
            copay_cents=0,
            coinsurance_pct=20,
            scheduled_start="2026-09-11T09:00:00Z",
            provider_code="DRDP",
        )
        appointment_id = ctx["appointment"]["id"]
        # PAYER_VERIFIED estimate: 30000 + 20% of 70000 = 44000; deposit 25% = 11000.
        estimate_res = api.create_copay_estimate(
            appointment_id,
            {"policy_id": ctx["policy"]["id"], "allowed_amount_cents": 100000},
            FC,
        )
        estimate = validate_success(estimate_res, 201)
        assert estimate["deposit_required_cents"] == 11000

        post_payment(appointment_id, 10000)
        short = api.mark_ready(appointment_id, FC)
        validate_error(short, ApiErrorId.ERR_DEPOSIT_SHORTFALL)

        post_payment(appointment_id, 1000)
        ready = validate_success(api.mark_ready(appointment_id, FC), 200)
        assert ready["status"] == "READY"
