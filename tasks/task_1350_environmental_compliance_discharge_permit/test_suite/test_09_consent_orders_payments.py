"""Consent orders and the penalty ledger: issuance/appeal/finalization,
per-day vs economic-benefit accrual variants, mitigation credit, payment
bounds and the auto-satisfaction cascade (PRD §3.8)."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_consent_order,
    assert_instant_equals,
    assert_penalty_payment,
    create_consent_order,
    create_exceedance_scenario,
    create_final_consent_order,
    drive_corrective_action_to_verified,
    finalize_consent_order,
    get_permit_state,
    issue_consent_order,
    post_payment,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import TEST_USERS
from test_helpers.fixtures import EM, REG

ANY_HEADERS = TEST_USERS["regulator_headers"]  # reads are open to every role (PRD §2.1)
CO = TEST_USERS["compliance_officer_headers"]

class TestConsentOrderLifecycle:
    def test_consent_order_issue_and_appeal_transitions(self, api):
        """PRD §3.8: "Issuance by a `Regulator` requires `PROPOSED`
        (`ERR_CONSENT_ORDER_INVALID_STATE`), stamps `issued_at` with the logical
        clock, moves the order `PROPOSED → ISSUED`" and "from `ISSUED`
        (`ERR_CONSENT_ORDER_INVALID_STATE`) the order moves to `UNDER_APPEAL`, and
        accrual continues through the appeal without pause".
        PRD §3.8: "the linked exceedance's enforcement dimension moves
        `NONE → ORDER_ISSUED`".

        Design: Corner/state_machines/consent_order_issue_and_appeal_transitions
        """
        scenario = create_exceedance_scenario(permit_number="NPDES-SM33")
        order = create_consent_order(
            scenario["exceedance"]["id"],
            base_penalty_cents=100000, daily_accrual_cents=10000,
            statutory_cap_cents=5_000_000,
        )
        assert_consent_order(order)
        assert order["status"] == "PROPOSED"
        assert order["issued_at"] is None

        exceedance = validate_success(
            api.get_exceedance(scenario["exceedance"]["id"], ANY_HEADERS)
        )
        assert exceedance["enforcement_status"] == "ORDER_ISSUED", (
            "enforcement moves at proposal time"
        )

        issued = issue_consent_order(order["id"])
        assert issued["status"] == "ISSUED"
        assert_instant_equals(issued["issued_at"], "2026-08-05T10:00:00Z", "issued_at")

        appealed = validate_success(api.appeal_consent_order(
            order["id"], {"appeal_grounds": "disputed flow data"}, EM
        ))
        assert appealed["status"] == "UNDER_APPEAL"

    def test_consent_order_finalize_from_proposed_rejected(self, api):
        """PRD §3.8: "Finalization by a `Regulator` — allowed from `ISSUED` or
        `UNDER_APPEAL` (`ERR_CONSENT_ORDER_INVALID_STATE`)".

        Design: Corner/state_machines/consent_order_finalize_from_proposed_rejected
        """
        scenario = create_exceedance_scenario(permit_number="NPDES-SM34")
        order = create_consent_order(
            scenario["exceedance"]["id"],
            base_penalty_cents=100000, daily_accrual_cents=10000,
            statutory_cap_cents=5_000_000,
        )
        resp = api.finalize_consent_order(order["id"], REG)
        validate_error(resp, ApiErrorId.ERR_CONSENT_ORDER_INVALID_STATE)

    def test_get_consent_order_not_found(self, api):
        """PRD §2.8: "The first identifier that does not resolve yields the
        corresponding 404: the resource-specific ... `ERR_CONSENT_ORDER_NOT_FOUND`
        ..."

        Design: Corner/entities/get_consent_order_not_found
        """
        resp = api.get_consent_order(NON_EXISTENT_UUID, ANY_HEADERS)
        validate_error(resp, ApiErrorId.ERR_CONSENT_ORDER_NOT_FOUND)

class TestPenaltyAccrualVariants:
    """Difficulty instance consent_order_penalty_per_day_vs_economic_benefit:
    identical violation date (2026-08-05), identical 10-day accrual window
    (finalize at 2026-08-15 with no verified cure), identical base/cap."""

    def _finalize_after_ten_days(self, api, permit_number, **order_overrides):
        scenario = create_exceedance_scenario(permit_number=permit_number)
        order = create_consent_order(scenario["exceedance"]["id"], **order_overrides)
        issue_consent_order(order["id"])
        set_clock("2026-08-15T00:00:00Z")
        finalized = finalize_consent_order(order["id"])
        return scenario, finalized

    def test_penalty_per_day_variant_final_amount(self, api):
        """PRD §3.8: "`accrued_days` counts the whole days from the violation date
        to the end date, and is never less than one" and "Under the `PER_DAY` variant
        the gross assessment is the base penalty plus the daily accrual multiplied
        by the accrued days." and "a base of 1000000 cents assessed over 10 days
        yields 1500000 cents under `PER_DAY` at 50000 per day".
        PRD §3.8: "`outstanding_cents` is set to the final amount".

        Design: Difficulty/dual_variant_calc/consent_order_penalty_per_day_vs_economic_benefit
        """
        scenario, order = self._finalize_after_ten_days(
            api, "NPDES-DV2A",
            assessment_variant="PER_DAY", base_penalty_cents=1_000_000,
            daily_accrual_cents=50_000, statutory_cap_cents=5_000_000,
        )
        assert order["status"] == "FINAL"
        assert order["accrued_days"] == 10, "2026-08-05 violation date -> 2026-08-15 cure"
        assert order["final_amount_cents"] == 1_500_000, "1000000 + 50000 * 10"
        assert order["outstanding_cents"] == 1_500_000

    def test_penalty_economic_benefit_variant_final_amount(self, api):
        """PRD §3.8: "Under the `ECONOMIC_BENEFIT` variant the accrued days are
        divided by thirty and rounded up to a whole number of months, and the gross
        is the base penalty plus the avoided cost multiplied by the month count and
        by the gravity factor" and "4000000 cents under `ECONOMIC_BENEFIT` with an
        avoided cost of 2000000, one month and a gravity factor of 1.5".

        Design: Difficulty/dual_variant_calc/consent_order_penalty_per_day_vs_economic_benefit
        """
        scenario, order = self._finalize_after_ten_days(
            api, "NPDES-DV2B",
            assessment_variant="ECONOMIC_BENEFIT", base_penalty_cents=1_000_000,
            statutory_cap_cents=5_000_000, avoided_cost_cents=2_000_000,
            gravity_factor=1.5,
        )
        assert order["status"] == "FINAL"
        assert order["accrued_days"] == 10
        assert order["final_amount_cents"] == 4_000_000, (
            "1000000 + round(2000000 * ceil(10/30) * 1.5)"
        )
        assert order["outstanding_cents"] == 4_000_000

class TestPaymentLedger:
    def test_penalty_payment_immutable_ledger_line(self, api):
        """PRD §3.8: "Every accepted line records `consent_order_id` tying it to its
        order, is stamped `posted_at` from the logical clock, stands in `POSTED` and
        is never mutated afterward; per §2.4 it carries `id` and `created_at` only."
        and "`paid_cents` is the sum of `POSTED` lines in the `PAYMENT` direction".

        Design: Corner/entities/penalty_payment_immutable_ledger_line
        """
        scenario = create_exceedance_scenario(permit_number="NPDES-ENT8")
        order = create_final_consent_order(
            scenario["exceedance"]["id"],
            base_penalty_cents=1000, daily_accrual_cents=0,
            statutory_cap_cents=5_000_000,
        )
        assert order["outstanding_cents"] == 1000

        payment = post_payment(order["id"], "PAYMENT", 1000)
        assert_penalty_payment(payment)
        assert payment["direction"] == "PAYMENT"
        assert payment["amount_cents"] == 1000
        assert_instant_equals(payment["posted_at"], "2026-08-05T10:00:00Z", "posted_at")

        ledger, meta = validate_paginated(api.list_payments(order["id"], ANY_HEADERS))
        assert len(ledger) == 1 and meta["total_count"] == 1
        assert ledger[0]["id"] == payment["id"]
        assert_penalty_payment(ledger[0])

        after = validate_success(api.get_consent_order(order["id"], ANY_HEADERS))
        assert after["paid_cents"] == 1000
        assert after["outstanding_cents"] == 0

    def test_payment_amount_exceeds_outstanding_rejected(self, api):
        """PRD §3.8: "A `PAYMENT` may not exceed the order's current
        `outstanding_cents` (`ERR_PAYMENT_AMOUNT_INVALID`, HTTP 422)".

        Design: Corner/validations/payment_amount_exceeds_outstanding_rejected
        """
        scenario = create_exceedance_scenario(permit_number="NPDES-VAL11")
        order = create_final_consent_order(
            scenario["exceedance"]["id"],
            base_penalty_cents=1000, daily_accrual_cents=0,
            statutory_cap_cents=5_000_000,
        )
        assert order["outstanding_cents"] == 1000

        resp = api.post_payment(
            order["id"], {"direction": "PAYMENT", "amount_cents": 1001}, CO
        )
        validate_error(resp, ApiErrorId.ERR_PAYMENT_AMOUNT_INVALID)

    def test_refund_exceeding_net_paid_rejected(self, api):
        """PRD §3.8: "a `REFUND` may not exceed the net amount actually collected,
        that is `paid_cents` minus `refunded_cents` (`ERR_REFUND_EXCEEDS_PAID`,
        HTTP 422)".

        Design: Corner/validations/refund_exceeding_net_paid_rejected
        """
        scenario = create_exceedance_scenario(permit_number="NPDES-VAL12")
        order = create_final_consent_order(
            scenario["exceedance"]["id"],
            base_penalty_cents=2000, daily_accrual_cents=0,
            statutory_cap_cents=5_000_000,
        )
        post_payment(order["id"], "PAYMENT", 1000)   # outstanding 1000, stays FINAL
        post_payment(order["id"], "REFUND", 500)     # net collected 500

        resp = api.post_payment(
            order["id"], {"direction": "REFUND", "amount_cents": 600}, CO
        )
        validate_error(resp, ApiErrorId.ERR_REFUND_EXCEEDS_PAID)

    def test_consent_order_terminal_lockdown_satisfied(self, api):
        """PRD §3.8: "Satisfaction is automatic: when a posting drives
        `outstanding_cents` to exactly zero, the order moves `FINAL → SATISFIED`"
        and "Posting requires the order `FINAL` (`ERR_CONSENT_ORDER_NOT_PAYABLE`)".

        Design: Corner/state_machines/consent_order_terminal_lockdown_satisfied
        """
        scenario = create_exceedance_scenario(permit_number="NPDES-SM36")
        order = create_final_consent_order(
            scenario["exceedance"]["id"],
            base_penalty_cents=1000, daily_accrual_cents=0,
            statutory_cap_cents=5_000_000,
        )
        post_payment(order["id"], "PAYMENT", 1000)
        satisfied = validate_success(api.get_consent_order(order["id"], ANY_HEADERS))
        assert satisfied["status"] == "SATISFIED", "auto-transition on outstanding == 0"

        resp = api.post_payment(
            order["id"], {"direction": "PAYMENT", "amount_cents": 1}, CO
        )
        validate_error(resp, ApiErrorId.ERR_CONSENT_ORDER_NOT_PAYABLE)

    def test_cascade_payment_to_satisfied_resolves_enforcement_and_posture(self, api):
        """PRD §3.8: "when a posting drives `outstanding_cents` to exactly zero, the
        order moves `FINAL → SATISFIED`, the linked exceedance's enforcement
        dimension moves `ORDER_ISSUED → RESOLVED`, the permit's `compliance_posture`
        is recomputed — with no other live enforcement and no open corrective
        actions, it can finally return to `GOOD_STANDING`".

        Design: Corner/cross_cutting_layers/cascade_payment_to_satisfied_resolves_enforcement_and_posture
        """
        scenario = create_exceedance_scenario(permit_number="NPDES-LAY4")
        drive_corrective_action_to_verified(
            scenario["corrective_action"]["id"], actual_cost_cents=5000
        )
        order = create_final_consent_order(
            scenario["exceedance"]["id"],
            base_penalty_cents=1000, daily_accrual_cents=0,
            statutory_cap_cents=5_000_000,
        )
        # Verified cure at the violation date: gross 1000 (1 day, daily 0); the
        # mitigation credit is min(1/4 * 1000, 5000) = 250 (PRD §3.8 finalize).
        assert order["final_amount_cents"] == 750
        assert order["outstanding_cents"] == 750
        permit = get_permit_state(scenario["permit"]["id"])
        assert permit["compliance_posture"] == "ENFORCEMENT"

        post_payment(order["id"], "PAYMENT", 750)

        satisfied = validate_success(api.get_consent_order(order["id"], ANY_HEADERS))
        assert satisfied["status"] == "SATISFIED"
        exceedance = validate_success(
            api.get_exceedance(scenario["exceedance"]["id"], ANY_HEADERS)
        )
        assert exceedance["enforcement_status"] == "RESOLVED"
        permit_after = get_permit_state(scenario["permit"]["id"])
        assert permit_after["compliance_posture"] == "GOOD_STANDING", (
            "no live enforcement and no open corrective actions remain"
        )
