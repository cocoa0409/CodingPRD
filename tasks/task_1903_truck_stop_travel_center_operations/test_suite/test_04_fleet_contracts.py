"""Fleet accounts and tiered fuel contracts: tier recompute cascade,
provisional vs confirmed tier quoting, lifecycle gates, and contract OCC."""
import pytest

from test_helpers import (
    ApiErrorId,
    amend_contract_payload,
    create_fuel_sale_payload,
    setup_contract_site,
    setup_fleet_with_contract,
    validate_error,
    validate_success,
    api_client,
)
from test_helpers.constants import TEST_CLOCK_ISO
from test_helpers.fixtures import (
    CASH_1,
    GM,
    authorize_contract_sale,
    create_contract,
    create_fleet,
    finalize_fuel_sale,
    reload_contract,
    reload_fleet,
    void_sale,
)


def _setup_fleet_contract_site():
    ctx = setup_contract_site("Site I", rack_price_4dp=2.7000,
                              clock=TEST_CLOCK_ISO)
    fc = setup_fleet_with_contract(name="Fleet A", credit_limit_cents=50_000_000,
                                   fleet_tier="T1", contract_tier="T1",
                                   discount_per_gallon_off=0.0,
                                   contract_code="C-1")
    return ctx, fc


def _finalize_two_contract_sales(ctx, fc):
    """4900-gal then 200-gal completed contract sales on C-1."""
    s1 = authorize_contract_sale(ctx, fc.fleet["id"], fc.contract["id"],
                                 max_gallons=4900.0)
    finalize_fuel_sale(s1["id"], 4900.0)
    s2 = authorize_contract_sale(ctx, fc.fleet["id"], fc.contract["id"],
                                 max_gallons=200.0)
    finalize_fuel_sale(s2["id"], 200.0)
    return s1, s2


class TestProvisionalVsConfirmedTier:
    def test_fleet_tier_flips_after_inclusive_breakpoint(self, api):
        """PRD section 3.3: "The tier then snaps to `T3` when the rolling
        volume reaches at least 20,000 gallons, `T2` at least 5,000 gallons,
        and `T1` below that; the breakpoint comparisons are inclusive, so
        exactly 5,000 gallons is already `T2`."
        PRD section 3.3: "`rolling_30d_gallons` is the sum of
        `dispensed_gallons` over the fleet's contract sales that are
        `COMPLETED` with `finalized_at` inside the trailing 30-day window,
        both endpoints inclusive".

        Design: Difficulty/dual_variant_calc/contract_tier_provisional_vs_confirmed
        """
        ctx, fc = _setup_fleet_contract_site()
        _finalize_two_contract_sales(ctx, fc)

        recomputed = validate_success(
            api.fleet_tier_recompute(fc.fleet["id"], GM)
        )
        assert recomputed["rolling_30d_gallons"] == pytest.approx(5100.0)
        assert recomputed["pricing_tier"] == "T2"

    def test_contract_quote_uses_contract_tier_not_fleet_tier(self, api):
        """PRD section 3.2: "the authorization always prices the provisional
        tier recorded on the contract itself, while a fleet-level preview
        priced at the fleet's current `pricing_tier` can differ once the
        fleet's rolling volume has crossed a tier breakpoint but the contract
        still carries its original tier."
        PRD section 3.2: "subtracts the tier margin baked into the contract's
        own `pricing_tier` — 0.02 dollars per gallon for `T1`, 0.05 for `T2`,
        and 0.09 for `T3`".

        Design: Difficulty/dual_variant_calc/contract_tier_provisional_vs_confirmed
        """
        ctx, fc = _setup_fleet_contract_site()
        _finalize_two_contract_sales(ctx, fc)  # fleet rolling now 5100 -> T2

        c2 = create_contract(fc.fleet["id"], "C-2", "T2", 0.0)
        validate_success(api.contract_activate(c2["id"], GM))

        s3 = authorize_contract_sale(ctx, fc.fleet["id"], fc.contract["id"],
                                     max_gallons=100.0)
        assert s3["authorized_quote_cents_per_gallon"] == 283, (
            "C-1 stays frozen at T1: 2.7000 + 0.1500 - 0.02 = 2.8300"
        )
        void_sale(s3["id"], "quote probe complete")

        s4 = authorize_contract_sale(ctx, fc.fleet["id"], c2["id"],
                                     max_gallons=100.0)
        assert s4["authorized_quote_cents_per_gallon"] == 280, (
            "C-2 prices at the confirmed T2 tier: 2.7000 + 0.1500 - 0.05"
        )


class TestFinalizeVolumeTierCascade:
    def test_finalize_accumulates_contract_volume_and_rolling(self, api):
        """PRD section 3.2: "A contract sale additionally cascades three hops:
        the contract's `volume_delivered_gallons` grows by
        `dispensed_gallons`, the fleet's `rolling_30d_gallons` is recomputed,
        and the fleet tier recompute may flip `pricing_tier` when a 5,000- or
        20,000-gallon breakpoint is crossed."

        Design: Difficulty/transitive_cascade/contract_finalize_volume_tier_upgrade
        """
        ctx, fc = _setup_fleet_contract_site()
        s1 = authorize_contract_sale(ctx, fc.fleet["id"], fc.contract["id"],
                                     max_gallons=4900.0)
        finalize_fuel_sale(s1["id"], 4900.0)

        contract_mid = reload_contract(fc.contract["id"])
        fleet_mid = reload_fleet(fc.fleet["id"])
        assert contract_mid["volume_delivered_gallons"] == pytest.approx(4900.0)
        assert fleet_mid["rolling_30d_gallons"] == pytest.approx(4900.0)
        assert fleet_mid["pricing_tier"] == "T1", "4900 < 5000 breakpoint"

    def test_rolling_volume_crossing_breakpoint_flips_tier(self, api):
        """PRD section 3.2: "the fleet tier recompute may flip `pricing_tier`
        when a 5,000- or 20,000-gallon breakpoint is crossed."
        PRD section 3.3: "the breakpoint comparisons are inclusive, so
        exactly 5,000 gallons is already `T2`."

        Design: Difficulty/transitive_cascade/contract_finalize_volume_tier_upgrade
        """
        ctx, fc = _setup_fleet_contract_site()
        _finalize_two_contract_sales(ctx, fc)

        contract_end = reload_contract(fc.contract["id"])
        fleet_end = reload_fleet(fc.fleet["id"])
        assert contract_end["volume_delivered_gallons"] == pytest.approx(5100.0)
        assert fleet_end["rolling_30d_gallons"] == pytest.approx(5100.0)
        assert fleet_end["pricing_tier"] == "T2"


class TestFleetTierBoundary:
    def test_fleet_tier_boundary_4999_vs_5000(self, api):
        """PRD section 3.3: "The tier then snaps to `T3` when the rolling
        volume reaches at least 20,000 gallons, `T2` at least 5,000 gallons,
        and `T1` below that; the breakpoint comparisons are inclusive, so
        exactly 5,000 gallons is already `T2`."

        Design: Corner/calculations/calc_fleet_tier_boundary_4999_vs_5000
        """
        ctx = setup_contract_site("Site C5", rack_price_4dp=2.7000,
                                  clock=TEST_CLOCK_ISO, num_pumps=2)
        f1 = setup_fleet_with_contract(name="Fleet One", contract_code="C-1")
        f2 = setup_fleet_with_contract(name="Fleet Two", contract_code="C-2")

        s1 = authorize_contract_sale(ctx, f1.fleet["id"], f1.contract["id"],
                                     pump_idx=0, max_gallons=4999.999)
        finalize_fuel_sale(s1["id"], 4999.999)
        s2 = authorize_contract_sale(ctx, f2.fleet["id"], f2.contract["id"],
                                     pump_idx=1, max_gallons=5000.0)
        finalize_fuel_sale(s2["id"], 5000.0)

        f1_now = reload_fleet(f1.fleet["id"])
        f2_now = reload_fleet(f2.fleet["id"])
        assert f1_now["rolling_30d_gallons"] == pytest.approx(4999.999)
        assert f1_now["pricing_tier"] == "T1"
        assert f2_now["rolling_30d_gallons"] == pytest.approx(5000.0)
        assert f2_now["pricing_tier"] == "T2"


class TestFleetAndContractStateGates:
    def test_contract_authorize_rejected_on_credit_hold(self, api):
        """PRD section 3.3: "Placing the account on credit hold moves it
        `ACTIVE → CREDIT_HOLD`, which blocks new contract fuel authorizations
        and blocks estimate approval on the fleet's work orders."
        PRD section 3.2: "for a contract sale the named fleet must then be
        `ACTIVE` (`ERR_FLEET_NOT_ACTIVE`, HTTP 409)".

        Design: Difficulty/cross_entity_state_dependency/contract_sale_gated_by_fleet_status
        """
        ctx, fc = _setup_fleet_contract_site()
        validate_success(api.fleet_credit_hold(fc.fleet["id"], GM))

        payload = create_fuel_sale_payload(
            ctx.pumps[0]["id"], ctx.shift["id"], pricing_mode="CONTRACT",
            fuel_type="DIESEL", tender_type="FLEET_BILLING", max_gallons=100.0,
            fleet_account_id=fc.fleet["id"], contract_id=fc.contract["id"],
        )
        resp = api.create_fuel_sale(ctx.site["id"], payload, CASH_1)
        validate_error(resp, ApiErrorId.ERR_FLEET_NOT_ACTIVE)

    def test_contract_authorize_succeeds_after_credit_reinstate(self, api):
        """PRD section 3.3: "Reinstatement moves it `CREDIT_HOLD → ACTIVE`."
        PRD section 3.2: "for a contract sale the named fleet must then be
        `ACTIVE` (`ERR_FLEET_NOT_ACTIVE`, HTTP 409)".

        Design: Difficulty/cross_entity_state_dependency/contract_sale_gated_by_fleet_status
        """
        ctx, fc = _setup_fleet_contract_site()
        validate_success(api.fleet_credit_hold(fc.fleet["id"], GM))
        validate_success(api.fleet_credit_reinstate(fc.fleet["id"], GM))

        sale = authorize_contract_sale(ctx, fc.fleet["id"], fc.contract["id"],
                                       max_gallons=100.0)
        assert sale["authorized_quote_cents_per_gallon"] == 283

    def test_contract_suspend_blocks_authorize_then_resume(self, api):
        """PRD section 3.3: "Suspension moves it `ACTIVE → SUSPENDED`,
        blocking new authorizations that quote it; resumption returns
        `SUSPENDED → ACTIVE` under the same window-and-fleet conditions as
        activation."
        PRD section 3.2: "the contract must be `ACTIVE` with the current
        clock inside its window (`ERR_CONTRACT_NOT_ACTIVE`, HTTP 409)".

        Design: Corner/state_machines/sm_contract_suspend_resume_cycle
        """
        ctx, fc = _setup_fleet_contract_site()

        suspended = validate_success(api.contract_suspend(fc.contract["id"], GM))
        assert suspended["status"] == "SUSPENDED"

        payload = create_fuel_sale_payload(
            ctx.pumps[0]["id"], ctx.shift["id"], pricing_mode="CONTRACT",
            fuel_type="DIESEL", tender_type="FLEET_BILLING", max_gallons=50.0,
            fleet_account_id=fc.fleet["id"], contract_id=fc.contract["id"],
        )
        validate_error(api.create_fuel_sale(ctx.site["id"], payload, CASH_1),
                       ApiErrorId.ERR_CONTRACT_NOT_ACTIVE)

        resumed = validate_success(api.contract_resume(fc.contract["id"], GM))
        assert resumed["status"] == "ACTIVE"
        sale = authorize_contract_sale(ctx, fc.fleet["id"], fc.contract["id"],
                                       max_gallons=50.0)
        assert sale["authorized_quote_cents_per_gallon"] == 283

    def test_terminated_contract_rejects_activate(self, api):
        """PRD section 3.3: "termination moves `PENDING`, `ACTIVE`, or
        `SUSPENDED` to terminal `TERMINATED`".
        PRD section 2.10: "the generic rule that the target entity must be in
        a state from which the requested transition exists fails with
        `ERR_INVALID_STATE` (HTTP 409)".

        Design: Corner/state_machines/sm_terminal_contract_locked
        """
        set_clock_and_fleet = setup_fleet_with_contract(activate=False)
        validate_success(api.contract_terminate(set_clock_and_fleet.contract["id"], GM))

        resp = api.contract_activate(set_clock_and_fleet.contract["id"], GM)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert reload_contract(set_clock_and_fleet.contract["id"])["status"] == "TERMINATED"

    def test_pending_contract_authorize_rejected(self, api):
        """PRD section 3.2: "the contract must be `ACTIVE` with the current
        clock inside its window (`ERR_CONTRACT_NOT_ACTIVE`, HTTP 409)".

        Design: Corner/errors/error_contract_not_active_pending
        """
        ctx = setup_contract_site("Site R3", rack_price_4dp=2.7000,
                                  clock=TEST_CLOCK_ISO)
        fc = setup_fleet_with_contract(activate=False)

        payload = create_fuel_sale_payload(
            ctx.pumps[0]["id"], ctx.shift["id"], pricing_mode="CONTRACT",
            fuel_type="DIESEL", tender_type="FLEET_BILLING", max_gallons=50.0,
            fleet_account_id=fc.fleet["id"], contract_id=fc.contract["id"],
        )
        validate_error(api.create_fuel_sale(ctx.site["id"], payload, CASH_1),
                       ApiErrorId.ERR_CONTRACT_NOT_ACTIVE)


class TestContractBusinessRules:
    def test_contract_fuel_type_rejected(self, api):
        """PRD section 3.2: "a contract sale's requested `fuel_type` must
        appear in the contract's `applicable_fuel_types`
        (`ERR_CONTRACT_FUEL_TYPE`, HTTP 422)".

        Design: Corner/validations/validation_contract_fuel_type_rejected
        """
        ctx = setup_contract_site("Site V12", rack_price_4dp=2.7000,
                                  clock=TEST_CLOCK_ISO,
                                  pump_fuel_types=("DIESEL", "GAS_REGULAR"))
        fc = setup_fleet_with_contract(applicable_fuel_types=("DIESEL",))

        payload = create_fuel_sale_payload(
            ctx.pumps[0]["id"], ctx.shift["id"], pricing_mode="CONTRACT",
            fuel_type="GAS_REGULAR", tender_type="FLEET_BILLING",
            max_gallons=50.0, fleet_account_id=fc.fleet["id"],
            contract_id=fc.contract["id"],
        )
        validate_error(api.create_fuel_sale(ctx.site["id"], payload, CASH_1),
                       ApiErrorId.ERR_CONTRACT_FUEL_TYPE)

    def test_contract_discount_shortfall(self, api):
        """PRD section 3.2: "The contract discount may not exceed the tier
        margin already inside the rate; a contract whose
        `discount_per_gallon_off` exceeds its tier's margin is rejected at
        authorization with `ERR_CONTRACT_DISCOUNT_SHORTFALL` (HTTP 422)."

        Design: Corner/validations/validation_contract_discount_shortfall
        """
        ctx = setup_contract_site("Site V13", rack_price_4dp=2.7000,
                                  clock=TEST_CLOCK_ISO)
        fc = setup_fleet_with_contract(discount_per_gallon_off=0.06,
                                       contract_code="C-DEEP")

        payload = create_fuel_sale_payload(
            ctx.pumps[0]["id"], ctx.shift["id"], pricing_mode="CONTRACT",
            fuel_type="DIESEL", tender_type="FLEET_BILLING", max_gallons=50.0,
            fleet_account_id=fc.fleet["id"], contract_id=fc.contract["id"],
        )
        validate_error(api.create_fuel_sale(ctx.site["id"], payload, CASH_1),
                       ApiErrorId.ERR_CONTRACT_DISCOUNT_SHORTFALL)

    def test_credit_limit_projected_over_rejected(self, api):
        """PRD section 3.2: "Before the authorization completes, the fleet's
        projected balance — `current_balance_cents` plus the new
        `provisional_fuel_total_cents` — must stay within the fleet's
        `credit_limit_cents`, else `ERR_CREDIT_LIMIT_EXCEEDED` (HTTP 422)."

        Design: Corner/validations/validation_credit_limit_projected_over
        """
        ctx = setup_contract_site("Site V6", rack_price_4dp=2.7000,
                                  clock=TEST_CLOCK_ISO)
        fc = setup_fleet_with_contract(credit_limit_cents=30_000)

        payload = create_fuel_sale_payload(
            ctx.pumps[0]["id"], ctx.shift["id"], pricing_mode="CONTRACT",
            fuel_type="DIESEL", tender_type="FLEET_BILLING",
            max_gallons=120.25, fleet_account_id=fc.fleet["id"],
            contract_id=fc.contract["id"],
        )
        # provisional total 283 x 120.250 gallons (~34031 cents) > 30000 limit
        validate_error(api.create_fuel_sale(ctx.site["id"], payload, CASH_1),
                       ApiErrorId.ERR_CREDIT_LIMIT_EXCEEDED)


class TestContractAmendOcc:
    def test_occ_contract_amend_stale_rejected(self, api):
        """PRD section 2.6: "when `expected_contract_version` does not match
        the contract's current `version`, the amendment is rejected with
        `ERR_STALE_VERSION` (HTTP 412). A successful amendment increments the
        contract's `version` by 1."

        Design: Corner/complexity_layers/layer_occ_contract_amend_stale_rejected
        """
        fleet = create_fleet("Fleet A", 5_000_000, "T1")
        contract = create_contract(fleet["id"], "C-1", "T1", 0.0)
        pre_activation_version = contract["version"]
        activated = validate_success(api.contract_activate(contract["id"], GM))
        current_version = activated["version"]
        assert current_version == pre_activation_version + 1

        stale = api.amend_contract(
            contract["id"],
            amend_contract_payload(pre_activation_version,
                                   discount_per_gallon_off=0.01),
            GM,
        )
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION, 412)

        amended = validate_success(api.amend_contract(
            contract["id"],
            amend_contract_payload(current_version,
                                   discount_per_gallon_off=0.01),
            GM,
        ))
        assert amended["discount_per_gallon_off"] == pytest.approx(0.01)
        assert amended["version"] == current_version + 1
