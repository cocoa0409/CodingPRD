"""Qualification gates: prescription state, allowances, upgrade coverage, thresholds."""
import pytest

from test_helpers import (
    ApiErrorId,
    create_prescription,
    get_success_data,
    setup_pending_order,
    setup_pending_order_verified,
    setup_qualified_order,
    validate_error,
    validate_success,
)


class TestQualifyPrescriptionGate:
    def test_qualify_with_unverified_prescription_rejected(self, api, insurance_specialist_headers,
                                                           care_coordinator_headers):
        """PRD §3.3: "the prescription must be `VERIFIED` (`ERR_PRESCRIPTION_NOT_VERIFIED`)".

        Design: Difficulty/cross_entity_state_dependency/qualify_requires_prescription_verified
        """
        ctx = setup_pending_order()  # prescription left PENDING_VERIFICATION
        res = api.qualify_pump_order(ctx["order"]["id"], insurance_specialist_headers)
        validate_error(res, ApiErrorId.ERR_PRESCRIPTION_NOT_VERIFIED, expected_status=409)

        order = validate_success(
            api.get_pump_order(ctx["order"]["id"], care_coordinator_headers), 200
        )
        assert order["fulfillment_status"] == "PENDING_QUALIFICATION"

    def test_failed_qualify_consumes_no_pump_allowance(self, api, insurance_specialist_headers,
                                                       care_coordinator_headers):
        """PRD §3.3: "Qualification also consumes budgets: the policy's
        `pumps_consumed_count` rises by 1" — a rejected qualify never reaches that step, so
        the counter stays at zero.

        Design: Difficulty/cross_entity_state_dependency/qualify_requires_prescription_verified
        """
        ctx = setup_pending_order()
        api.qualify_pump_order(ctx["order"]["id"], insurance_specialist_headers)

        policy = validate_success(
            api.get_policy(ctx["policy"]["id"], care_coordinator_headers), 200
        )
        assert policy["pumps_consumed_count"] == 0


class TestQualifyRbac:
    def test_care_coordinator_cannot_qualify(self, api, care_coordinator_headers):
        """PRD §3.3: "Qualification is the pivotal act, performed by an
        `InsuranceSpecialist`."
        PRD §2.1: "if the caller's role is not in the target endpoint's authorized role
        list, the request is rejected with `ERR_FORBIDDEN` (HTTP 403)."

        Design: Corner/validations/coordinator_cannot_qualify_order
        """
        ctx = setup_pending_order()
        res = api.qualify_pump_order(ctx["order"]["id"], care_coordinator_headers)
        validate_error(res, ApiErrorId.ERR_FORBIDDEN, expected_status=403)

        order = validate_success(
            api.get_pump_order(ctx["order"]["id"], care_coordinator_headers), 200
        )
        assert order["fulfillment_status"] == "PENDING_QUALIFICATION"


class TestPumpAllowance:
    def test_second_qualify_with_allowance_one_rejected(self, api, insurance_specialist_headers,
                                                        care_coordinator_headers):
        """PRD §3.3: "the policy must have pump allowance remaining, i.e.
        `pumps_consumed_count` still below `pump_allowance_per_period`
        (`ERR_PUMP_ALLOWANCE_EXHAUSTED`)".

        Design: Corner/validations/pump_allowance_exhausted_on_second_qualify
        """
        ctx = setup_qualified_order(policy_overrides={"pump_allowance_per_period": 1})
        # Second verified prescription and second order on the same policy.
        rx2 = create_prescription(ctx["member"]["id"], issued_date="2026-05-01")
        get_success_data(api.verify_prescription(rx2["id"], insurance_specialist_headers))
        order2 = get_success_data(
            api.create_pump_order(
                {
                    "member_id": ctx["member"]["id"],
                    "policy_id": ctx["policy"]["id"],
                    "prescription_id": rx2["id"],
                    "pump_item_id": ctx["pump"]["id"],
                    "shipping_address": "8 V St",
                },
                care_coordinator_headers,
            )
        )
        res = api.qualify_pump_order(order2["id"], insurance_specialist_headers)
        validate_error(res, ApiErrorId.ERR_PUMP_ALLOWANCE_EXHAUSTED, expected_status=422)

    def test_allowance_counter_unchanged_and_second_prescription_not_consumed(
        self, api, insurance_specialist_headers, care_coordinator_headers
    ):
        """PRD §2.7: "The invariant maintained at all times is that
        `garments_consumed_count` equals the sum of garment-line quantities over the
        policy's orders whose fulfillment is `QUALIFIED`, `SHIPPED`, or `DELIVERED`;
        consumption happens at qualification and is released at cancellation." — pump
        consumption likewise happens only at a successful qualification.

        Design: Corner/validations/pump_allowance_exhausted_on_second_qualify
        """
        ctx = setup_qualified_order(policy_overrides={"pump_allowance_per_period": 1})
        rx2 = create_prescription(ctx["member"]["id"], issued_date="2026-05-01")
        get_success_data(api.verify_prescription(rx2["id"], insurance_specialist_headers))
        order2 = get_success_data(
            api.create_pump_order(
                {
                    "member_id": ctx["member"]["id"],
                    "policy_id": ctx["policy"]["id"],
                    "prescription_id": rx2["id"],
                    "pump_item_id": ctx["pump"]["id"],
                    "shipping_address": "8 V St",
                },
                care_coordinator_headers,
            )
        )
        api.qualify_pump_order(order2["id"], insurance_specialist_headers)

        policy = validate_success(
            api.get_policy(ctx["policy"]["id"], care_coordinator_headers), 200
        )
        assert policy["pumps_consumed_count"] == 1
        rx2_after = validate_success(
            api.get_prescription(rx2["id"], care_coordinator_headers), 200
        )
        assert rx2_after["status"] == "VERIFIED"


class TestUpgradeCoverage:
    def test_upgrade_pump_without_coverage_rejected(self, api, insurance_specialist_headers,
                                                    care_coordinator_headers):
        """PRD §3.3: "an `UPGRADE`-tier pump requires `upgrade_coverage` on the policy
        (`ERR_UPGRADE_TIER_NOT_COVERED`)".

        Design: Corner/validations/upgrade_not_covered_rejected
        """
        ctx = setup_pending_order_verified(
            pump_overrides={
                "sku": "PUMP-UPG", "name": "UpgPump", "unit_price_cents": 55000,
                "insurance_tier": "UPGRADE", "upgrade_fee_cents": 20000,
                "warranty_months": 24,
            }
        )
        res = api.qualify_pump_order(ctx["order"]["id"], insurance_specialist_headers)
        validate_error(res, ApiErrorId.ERR_UPGRADE_TIER_NOT_COVERED, expected_status=422)

        policy = validate_success(
            api.get_policy(ctx["policy"]["id"], care_coordinator_headers), 200
        )
        assert policy["pumps_consumed_count"] == 0


class TestProvisionalEstimate:
    def test_provisional_estimate_for_upgrade_pump(self, api, insurance_specialist_headers):
        """PRD §3.3: "The insurance base is the pump's `unit_price_cents` minus its
        `upgrade_fee_cents`, because the upgrade surcharge is never covered. The deductible
        remaining is the policy's `deductible_cents` minus `deductible_met_cents`, floored
        at zero; the deductible applied is the smaller of the insurance base and that
        remainder. Coinsurance is the base net of deductible applied, multiplied by
        `coinsurance_pct`, rounded half up."
        PRD §3.3: "The order then stores `provisional_allowed_cents` equal to the pump's
        full list `unit_price_cents`, `provisional_patient_cents` equal to the deductible
        applied plus coinsurance plus the upgrade fee, and its own `upgrade_fee_cents`
        snapshot copied from the catalog item (zero for `STANDARD`)."

        Design: Corner/calculations/provisional_estimate_with_upgrade_fee
        """
        ctx = setup_pending_order_verified(
            policy_overrides={"deductible_cents": 50000, "coinsurance_pct": 0.2,
                              "upgrade_coverage": True},
            pump_overrides={
                "sku": "PUMP-UPG", "name": "UpgPump", "unit_price_cents": 55000,
                "insurance_tier": "UPGRADE", "upgrade_fee_cents": 20000,
                "warranty_months": 24,
            },
        )
        res = api.qualify_pump_order(ctx["order"]["id"], insurance_specialist_headers)
        order = validate_success(res, 200)
        # base = 55000 - 20000 = 35000; ded_applied = min(35000, 50000) = 35000;
        # coins = 0; patient = 35000 + 0 + 20000 = 55000.
        assert order["provisional_allowed_cents"] == 55000
        assert order["upgrade_fee_cents"] == 20000
        assert order["provisional_patient_cents"] == 55000

    def test_qualify_response_carries_provisional_fields_immediately(
        self, api, insurance_specialist_headers
    ):
        """PRD §2.10: "The system favors immediate consistency: when one operation mutates
        several entities, every touch happens in the same request."
        PRD §2.2: "Unless otherwise noted, operations that create or modify a resource will
        return the created or updated resource object in the data field."

        Design: Corner/consistency_model/immediate_visibility_after_qualify
        """
        ctx = setup_pending_order_verified(
            policy_overrides={"deductible_cents": 50000, "coinsurance_pct": 0.2}
        )
        res = api.qualify_pump_order(ctx["order"]["id"], insurance_specialist_headers)
        order = validate_success(res, 200)
        assert order["fulfillment_status"] == "QUALIFIED"
        # base 30000; ded_applied = 30000; coins = 0; patient = 30000.
        assert order["provisional_patient_cents"] == 30000
        # requires_prior_auth defaults false and 30000 < default threshold 50000 (§2.7).
        assert order["prior_auth_required"] is False


class TestPriorAuthThreshold:
    def test_estimate_exactly_at_threshold_requires_prior_auth(
        self, api, insurance_specialist_headers
    ):
        """PRD §2.7: "the comparison at qualification is **inclusive**: an order whose
        estimated allowed amount equals the threshold exactly requires prior authorization
        just as surely as one above it."

        Design: Difficulty/boundary_precision_check/prior_auth_threshold_inclusive_boundary
        """
        ctx = setup_pending_order_verified(
            policy_overrides={"requires_prior_auth": False,
                              "prior_auth_threshold_cents": 30000}
        )
        res = api.qualify_pump_order(ctx["order"]["id"], insurance_specialist_headers)
        order = validate_success(res, 200)
        assert order["provisional_allowed_cents"] == 30000
        assert order["prior_auth_required"] is True
        assert order["fulfillment_status"] == "QUALIFIED"

    def test_estimate_one_cent_below_threshold_does_not_require_prior_auth(
        self, api, insurance_specialist_headers
    ):
        """PRD §3.3: "true when the policy's `requires_prior_auth` flag is set, or when
        `provisional_allowed_cents` is at least `prior_auth_threshold_cents` — the
        threshold comparison is inclusive, so an estimate exactly equal to the threshold
        requires authorization."

        Design: Difficulty/boundary_precision_check/prior_auth_threshold_inclusive_boundary
        """
        ctx = setup_pending_order_verified(
            policy_overrides={"requires_prior_auth": False,
                              "prior_auth_threshold_cents": 30000},
            pump_overrides={"unit_price_cents": 29999},
        )
        res = api.qualify_pump_order(ctx["order"]["id"], insurance_specialist_headers)
        order = validate_success(res, 200)
        assert order["provisional_allowed_cents"] == 29999
        assert order["prior_auth_required"] is False
