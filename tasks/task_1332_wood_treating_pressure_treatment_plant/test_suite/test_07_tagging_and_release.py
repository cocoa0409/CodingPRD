"""Tagging gates, warranty registration fee computation, optimistic
concurrency on registration, and the customer-balance payment invariant
(PRD §2.7, §3.4, §3.8)."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    book_treatment_slot,
    create_charge_payload,
    create_warranty_payload,
    expected_registration_fee_cents,
    get_charge,
    get_customer,
    load_charge,
    log_drip_pad,
    setup_assayed_charge,
    setup_customer,
    setup_cylinder,
    setup_released_charge,
    setup_shop,
    setup_tagged_charge,
    validate_error,
    validate_success,
)

OP = TEST_USERS["plant_operator_headers"]
AR = TEST_USERS["accounts_receivable_headers"]


class TestTagGates:
    def test_charge_tag_from_wrong_state_returns_invalid_state(self, api):
        """PRD §3.8: "The charge must be `ASSAYED_PASS` (otherwise
        `ERR_CHARGE_NOT_ASSAYED_PASS`, 409)."

        Design: Corner/state_machines/charge_tag_from_wrong_state_returns_invalid_state
        """
        shop = setup_shop()
        plant_id = shop["plant"]["id"]
        charge = load_charge(plant_id, shop["cylinder"]["id"], volume_mbf=5.0)
        assert charge["status"] == "IN_CYLINDER"

        resp = api.tag_charge(plant_id, charge["id"], OP)
        validate_error(resp, ApiErrorId.ERR_CHARGE_NOT_ASSAYED_PASS.value)

    def test_idempotency_double_tag_returns_error(self, api):
        """PRD §3.8: "The charge must be `ASSAYED_PASS` (otherwise
        `ERR_CHARGE_NOT_ASSAYED_PASS`, 409)." A second tag arrives when the
        charge is already `TAGGED`, so it fails the same gate.

        Design: Corner/state_machines/idempotency_double_tag_returns_error
        """
        shop = setup_shop()
        plant_id = shop["plant"]["id"]
        tagged = setup_tagged_charge(shop)
        assert tagged["status"] == "TAGGED"

        resp = api.tag_charge(plant_id, tagged["id"], OP)
        validate_error(resp, ApiErrorId.ERR_CHARGE_NOT_ASSAYED_PASS.value)

    def test_tag_state_check_precedes_incising_check(self, api):
        """PRD §2.9: "The ordered cascade itself then runs as follows: ... 5.
        Resource state preconditions ... 10. Incising completeness at tagging
        — `ERR_INCISING_REQUIRED` (422)."
        PRD §2.9: "The ordering is observable."

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_safety_priority_on_tag_endpoint
        """
        shop = setup_shop()
        plant_id = shop["plant"]["id"]
        # DOUGLAS_FIR UC4B requires incising; the piece is NOT incised, and the
        # charge is still IN_CYLINDER (wrong state for tagging). Both rules
        # fail; the state precondition is earlier in the ordered cascade.
        charge = load_charge(
            plant_id, shop["cylinder"]["id"],
            species_group="DOUGLAS_FIR", use_category="UC4B", volume_mbf=5.0)
        assert charge["requires_incising"] is True

        resp = api.tag_charge(plant_id, charge["id"], OP)
        validate_error(resp, ApiErrorId.ERR_CHARGE_NOT_ASSAYED_PASS.value)

    def test_tag_requires_all_pieces_incised(self, api):
        """PRD §3.8: "If `requires_incising` is true, every piece must already
        be incised — a single missed piece fails the tag with
        `ERR_INCISING_REQUIRED` (422)."

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_safety_priority_on_tag_endpoint
        """
        shop = setup_shop()
        plant_id = shop["plant"]["id"]
        # State gate passes (ASSAYED_PASS); only the incising gate fails.
        charge, _cycle, _assay = setup_assayed_charge(
            shop, outcome="PASS", species_group="DOUGLAS_FIR", use_category="UC4B",
            volume_mbf=5.0)
        assert charge["requires_incising"] is True

        log_drip_pad(plant_id, charge["id"])

        resp = api.tag_charge(plant_id, charge["id"], OP)
        validate_error(resp, ApiErrorId.ERR_INCISING_REQUIRED.value)


class TestRegistrationFee:
    def test_custom_treat_vs_plant_stock_fees_diverge(self, api):
        """PRD §3.8: "then apply the custom-treat uplift of eighteen percent
        when `is_custom_treat` is true (nothing when it is not)".
        PRD §3.8: "Registration moves the charge to `RELEASED`, moves each
        `TAGGED` piece to `RELEASED`, debits the fee for custom-treat work by
        adding `registration_fee_cents` to the customer's
        `outstanding_balance_cents`, and increments the charge's `version`
        by 1."

        Design: Difficulty/dual_variant_calc/registration_fee_custom_treat_vs_plant_stock_diverge
        """
        shop = setup_shop()
        plant_id = shop["plant"]["id"]
        customer = setup_customer()

        # Identical charges (SYP, UC4A, 25 mbf, 25-year term); the only
        # difference is ownership_type.
        warranty_stock, released_stock = setup_released_charge(
            shop, warranty_term_years=25,
            species_group="SYP", use_category="UC4A", volume_mbf=25.0,
            ownership_type="PLANT_STOCK")
        expected_stock = expected_registration_fee_cents("UC4A", 25.0, False, 25)
        assert expected_stock == 4408  # round(3200*0.95) * 1.00 * 1.45
        assert warranty_stock["registration_fee_cents"] == expected_stock

        # Second cylinder for the custom-treat charge.
        cyl2 = setup_cylinder(plant_id, cylinder_code="CYL-2")
        book_treatment_slot(plant_id, cyl2["id"])
        shop2 = dict(shop, cylinder=cyl2)
        warranty_custom, released_custom = setup_released_charge(
            shop2, warranty_term_years=25,
            species_group="SYP", use_category="UC4A", volume_mbf=25.0,
            ownership_type="CUSTOM_TREAT", customer_id=customer["id"])
        expected_custom = expected_registration_fee_cents("UC4A", 25.0, True, 25)
        assert expected_custom == 5201  # round(round(3040*1.18)=3587 * 1.45)
        assert warranty_custom["registration_fee_cents"] == expected_custom

        # The uplift makes the two valid paths diverge, and only the
        # custom-treat fee lands on the customer's ledger.
        assert warranty_custom["registration_fee_cents"] != warranty_stock["registration_fee_cents"]
        assert get_customer(customer["id"])["outstanding_balance_cents"] == expected_custom
        assert released_stock["status"] == "RELEASED"
        assert released_custom["status"] == "RELEASED"

    def test_custom_treat_uplift_diverges_at_five_year_term(self, api):
        """PRD §3.8: "then apply the custom-treat uplift of eighteen percent
        when `is_custom_treat` is true (nothing when it is not); then multiply
        by the warranty-term multiplier — 1.00 for five years, 1.45 for
        twenty-five, 1.95 for fifty."

        Design: Difficulty/dual_variant_calc/registration_fee_custom_treat_vs_plant_stock_diverge
        """
        shop = setup_shop()
        plant_id = shop["plant"]["id"]
        customer = setup_customer()

        warranty_stock, _ = setup_released_charge(
            shop, warranty_term_years=5,
            species_group="SYP", use_category="UC4A", volume_mbf=25.0,
            ownership_type="PLANT_STOCK")
        assert warranty_stock["registration_fee_cents"] == 3040  # 3200*0.95*1.00

        cyl2 = setup_cylinder(plant_id, cylinder_code="CYL-2")
        book_treatment_slot(plant_id, cyl2["id"])
        shop2 = dict(shop, cylinder=cyl2)
        warranty_custom, _ = setup_released_charge(
            shop2, warranty_term_years=5,
            species_group="SYP", use_category="UC4A", volume_mbf=25.0,
            ownership_type="CUSTOM_TREAT", customer_id=customer["id"])
        assert warranty_custom["registration_fee_cents"] == 3587  # round(3040*1.18)
        assert warranty_custom["registration_fee_cents"] > warranty_stock["registration_fee_cents"]

    def test_registration_fee_multi_input_tiered_formula(self, api):
        """PRD §3.8: "The `registration_fee_cents` is computed in a pinned
        order: start from the base fee for the charge's `use_category` — 1500
        cents for `UC3B`, 3200 for `UC4A`, 5800 for `UC4B`, 9100 for `UC4C`;
        apply the volume discount keyed to `volume_mbf` — none at ten mbf or
        below, five percent off the base above ten and up to and including
        fifty mbf, twelve percent off above fifty; then apply the custom-treat
        uplift of eighteen percent when `is_custom_treat` is true (nothing
        when it is not); then multiply by the warranty-term multiplier — 1.00
        for five years, 1.45 for twenty-five, 1.95 for fifty."
        PRD §3.8: "Each multiplication is rounded half-up to whole cents
        before the next factor is applied, and applying the factors in any
        other order can yield a different cent figure and is non-conformant."

        Design: Difficulty/combinatorial_formula/registration_fee_multi_input_tiered_formula
        """
        shop = setup_shop(max_volume_mbf=100.0)
        plant_id = shop["plant"]["id"]
        customer = setup_customer()

        # UC4C, 60 mbf (tier 3, 12% off), custom-treat (+18%), 25 years (1.45):
        # round(9100*0.88)=8008; round(8008*1.18)=9449; round(9449*1.45)=13701.
        warranty, released = setup_released_charge(
            shop, warranty_term_years=25,
            species_group="SYP", use_category="UC4C", volume_mbf=60.0,
            ownership_type="CUSTOM_TREAT", customer_id=customer["id"])
        expected = expected_registration_fee_cents("UC4C", 60.0, True, 25)
        assert expected == 13701
        assert warranty["registration_fee_cents"] == expected
        assert get_customer(customer["id"])["outstanding_balance_cents"] == expected

    def test_registration_fee_volume_tier_boundaries(self, api):
        """PRD §3.8: "apply the volume discount keyed to `volume_mbf` — none
        at ten mbf or below, five percent off the base above ten and up to
        and including fifty mbf, twelve percent off above fifty".

        Design: Difficulty/combinatorial_formula/registration_fee_multi_input_tiered_formula
        """
        shop = setup_shop(max_volume_mbf=100.0)
        plant_id = shop["plant"]["id"]

        # Exactly 10 mbf: no discount. UC3B 5-year: 1500 * 1.00 = 1500.
        w10, _ = setup_released_charge(
            shop, warranty_term_years=5,
            species_group="SYP", use_category="UC3B", volume_mbf=10.0,
            ownership_type="PLANT_STOCK")
        assert w10["registration_fee_cents"] == 1500

        # Exactly 50 mbf: 5% off. 1500 * 0.95 = 1425.
        cyl2 = setup_cylinder(plant_id, cylinder_code="CYL-2", max_volume_mbf=100.0)
        book_treatment_slot(plant_id, cyl2["id"])
        w50, _ = setup_released_charge(
            dict(shop, cylinder=cyl2), warranty_term_years=5,
            species_group="SYP", use_category="UC3B", volume_mbf=50.0,
            ownership_type="PLANT_STOCK")
        assert w50["registration_fee_cents"] == 1425

        # Above 50 mbf: 12% off. 1500 * 0.88 = 1320.
        cyl3 = setup_cylinder(plant_id, cylinder_code="CYL-3", max_volume_mbf=100.0)
        book_treatment_slot(plant_id, cyl3["id"])
        w60, _ = setup_released_charge(
            dict(shop, cylinder=cyl3), warranty_term_years=5,
            species_group="SYP", use_category="UC3B", volume_mbf=60.0,
            ownership_type="PLANT_STOCK")
        assert w60["registration_fee_cents"] == 1320


class TestRegistrationConcurrency:
    def test_occ_stale_version_on_warranty_registration(self, api):
        """PRD §2.7: "The same rule binds
        `POST /treatment-plants/{plantId}/charges/{chargeId}/warranty-registrations`:
        the request must carry `expected_charge_version` matching the charge's
        current `version`, and a mismatch is rejected with `ERR_STALE_VERSION`
        (HTTP 412)."
        PRD §3.8: "The warranty itself starts `ACTIVE`".

        Design: Corner/cross_cutting_complexity_layers/occ_stale_version_on_warranty_registration
        """
        shop = setup_shop()
        plant_id = shop["plant"]["id"]
        tagged = setup_tagged_charge(shop)
        current_version = tagged["version"]

        # Stale version -> 412.
        resp = api.register_warranty(
            plant_id, tagged["id"],
            create_warranty_payload(current_version - 1, warranty_term_years=25), OP)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)

        # Correct version -> 201, warranty starts ACTIVE, charge releases.
        resp = api.register_warranty(
            plant_id, tagged["id"],
            create_warranty_payload(current_version, warranty_term_years=25), OP)
        warranty = validate_success(resp, 201)
        assert warranty["status"] == "ACTIVE"
        assert get_charge(plant_id, tagged["id"])["status"] == "RELEASED"


class TestCustomerBalanceInvariant:
    def test_payment_fully_compensates_registration_fee(self, api):
        """PRD §3.8: "debits the fee for custom-treat work by adding
        `registration_fee_cents` to the customer's
        `outstanding_balance_cents`".
        PRD §3.4: "Recording a payment subtracts the supplied `amount_cents`
        from `outstanding_balance_cents`".

        Design: Difficulty/compensating_invariant/customer_balance_payment_invariant
        """
        shop = setup_shop()
        customer = setup_customer()
        balance_before = get_customer(customer["id"])["outstanding_balance_cents"]
        assert balance_before == 0

        warranty, _released = setup_released_charge(
            shop, warranty_term_years=25,
            species_group="SYP", use_category="UC3B", volume_mbf=5.0,
            ownership_type="CUSTOM_TREAT", customer_id=customer["id"])
        fee = warranty["registration_fee_cents"]

        balance_after_reg = get_customer(customer["id"])["outstanding_balance_cents"]
        assert balance_after_reg == balance_before + fee

        validate_success(api.record_payment(customer["id"], {"amount_cents": fee}, AR))
        balance_after_pay = get_customer(customer["id"])["outstanding_balance_cents"]
        assert balance_after_pay == balance_before

    def test_partial_payments_draw_balance_down_stepwise(self, api):
        """PRD §3.4: "Recording a payment subtracts the supplied
        `amount_cents` from `outstanding_balance_cents`".

        Design: Difficulty/compensating_invariant/customer_balance_payment_invariant
        """
        shop = setup_shop()
        customer = setup_customer()
        warranty, _released = setup_released_charge(
            shop, warranty_term_years=25,
            species_group="SYP", use_category="UC3B", volume_mbf=5.0,
            ownership_type="CUSTOM_TREAT", customer_id=customer["id"])
        fee = warranty["registration_fee_cents"]

        validate_success(api.record_payment(customer["id"],
                                            {"amount_cents": fee - 1}, AR))
        assert get_customer(customer["id"])["outstanding_balance_cents"] == 1

        validate_success(api.record_payment(customer["id"], {"amount_cents": 1}, AR))
        assert get_customer(customer["id"])["outstanding_balance_cents"] == 0
        assert get_customer(customer["id"])["status"] == "ACTIVE"
