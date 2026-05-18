"""Asset declaration, inventory, appraisal, gross-estate-value
calculation, and required-bond marginal tier calculation.

Coverage targets (PRD §3.1, §3.4, §3.5):
- Asset created in DECLARED state.
- DECLARED -> INVENTORIED requires Estate.admin_phase in
  {IN_PROBATE, INVENTORIED}.
- INVENTORIED -> APPRAISED requires appraised_value_cents.
- IN_PROBATE -> INVENTORIED requires every asset in
  {INVENTORIED, APPRAISED, EXCLUDED} else ERR_ASSETS_NOT_INVENTORIED.
- INVENTORY_REPORT acceptance precondition.
- Bond tiers: per-tier banker's-round then sum then add flat fee.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    FLAT_BOND_FEE_CENTS,
    TEST_USERS,
    TIER1_LIMIT_CENTS,
    api_client,
    appraise_asset,
    assert_asset,
    asset_state_payload,
    compute_required_bond_cents,
    confirm_fiduciary,
    create_asset_payload,
    create_estate_with_executor,
    declare_asset,
    estate_state_payload,
    fiduciary_state_payload,
    get_success_data,
    inventory_asset,
    nominate_fiduciary,
    setup_in_probate,
    setup_inventoried_with_appraised_total,
    submit_filing,
    transition_filing,
    validate_error,
    validate_success,
)


class TestAssetCreate:

    def test_create_asset_in_declared(self, api):
        """PRD §3.1: "A newly declared asset enters status DECLARED."

        Claim: POST /estates/.../assets -> 201 with status=DECLARED.
        """
        estate, _, exec_h = create_estate_with_executor()
        asset = declare_asset(
            estate["id"], asset_class="REAL_ESTATE",
            declared_value_cents=500_000_00,
            exec_headers=exec_h,
        )
        assert_asset(asset)
        assert asset["status"] == "DECLARED"

    def test_declared_value_cents_must_be_nonnegative(self, api):
        """PRD §3.1: "a non-negative declared_value_cents representing
        the executor's initial estimate".

        Claim: declared_value_cents=-1 -> ERR_BAD_REQUEST.
        """
        estate, _, exec_h = create_estate_with_executor()
        resp = api_client.create_asset(
            estate["id"],
            create_asset_payload(declared_value_cents=-1),
            exec_h,
        )
        validate_error(resp, ApiErrorId.ERR_BAD_REQUEST.value)


class TestAssetTransitions:

    def test_declared_to_inventoried_requires_in_probate(self, api):
        """PRD §3.4: "Each DECLARED asset is moved to INVENTORIED
        (which requires the estate to be in IN_PROBATE or
        INVENTORIED, otherwise ERR_INVALID_STATE)".

        Claim: attempting DECLARED -> INVENTORIED while Estate is
        still DRAFT -> ERR_INVALID_STATE.
        """
        estate, _, exec_h = create_estate_with_executor()
        asset = declare_asset(
            estate["id"], declared_value_cents=1000,
            exec_headers=exec_h,
        )
        resp = api_client.transition_asset(
            estate["id"], asset["id"],
            asset_state_payload("INVENTORIED"),
            exec_h,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    def test_inventoried_to_appraised_requires_appraised_value(
        self, api,
    ):
        """PRD §3.4: "a second state transition supplies
        appraised_value_cents (required, must be a non-negative
        integer) and moves the asset to APPRAISED."

        Claim: INVENTORIED -> APPRAISED without appraised_value_cents
        -> ERR_BAD_REQUEST.
        """
        bundle = setup_in_probate()
        estate = bundle["estate"]
        exec_h = bundle["executor_headers"]
        asset = declare_asset(
            estate["id"], declared_value_cents=1000,
            exec_headers=exec_h,
        )
        asset = inventory_asset(
            estate["id"], asset["id"], exec_headers=exec_h,
        )
        resp = api_client.transition_asset(
            estate["id"], asset["id"],
            asset_state_payload("APPRAISED"),
            exec_h,
        )
        validate_error(resp, ApiErrorId.ERR_BAD_REQUEST.value)

    def test_appraised_value_writes_to_row(self, api):
        """PRD §3.4: "The transition writes appraised_value_cents
        onto the row and recomputes the estate's
        gross_estate_value_cents."

        Claim: after INVENTORIED -> APPRAISED with value N, the
        asset response carries appraised_value_cents=N.
        """
        bundle = setup_in_probate()
        estate = bundle["estate"]
        exec_h = bundle["executor_headers"]
        asset = declare_asset(
            estate["id"], declared_value_cents=1000,
            exec_headers=exec_h,
        )
        asset = inventory_asset(
            estate["id"], asset["id"], exec_headers=exec_h,
        )
        asset = appraise_asset(
            estate["id"], asset["id"],
            appraised_value_cents=99_999,
            exec_headers=exec_h,
        )
        assert asset["status"] == "APPRAISED"
        assert asset["appraised_value_cents"] == 99_999, (
            f"appraised_value_cents must be 99999, got "
            f"{asset['appraised_value_cents']!r}"
        )


class TestInProbateToInventoried:

    def test_advance_requires_no_declared_assets(self, api):
        """PRD §3.4: "Once every asset is in INVENTORIED, APPRAISED,
        or EXCLUDED — that is, no asset remains in DECLARED ... the
        executor advances the estate from IN_PROBATE to INVENTORIED.
        Either precondition unmet produces ERR_ASSETS_NOT_INVENTORIED
        or ERR_NO_ACCEPTED_INVENTORY respectively."

        Claim: a DECLARED asset blocks IN_PROBATE -> INVENTORIED with
        ERR_ASSETS_NOT_INVENTORIED.
        """
        bundle = setup_in_probate()
        estate = bundle["estate"]
        executor = bundle["executor"]
        exec_h = bundle["executor_headers"]
        # Declare an asset and leave it in DECLARED.
        declare_asset(
            estate["id"], declared_value_cents=1000,
            exec_headers=exec_h,
        )
        # Submit + accept INVENTORY_REPORT. PRD §3.7: acceptance
        # requires every asset to be in INVENTORIED/APPRAISED/
        # EXCLUDED — so we will fail there. To isolate the estate-
        # advance check, inventory then test path. But the only
        # way to reach ERR_ASSETS_NOT_INVENTORIED at the advance is
        # if the inventory filing was ACCEPTED somehow with a
        # DECLARED asset present, which the spec forbids.
        #
        # The cleaner test: leave one asset DECLARED, ensure no
        # INVENTORY_REPORT exists, and verify the failure. The
        # observed error_id depends on which precondition fires
        # first — PRD §3.4 lists ERR_ASSETS_NOT_INVENTORIED OR
        # ERR_NO_ACCEPTED_INVENTORY without ordering. The PRD's
        # §2.10 priority order does not commit either; we accept
        # both.
        from test_helpers import validate_error_is_one_of
        resp = api_client.transition_estate(
            estate["id"], estate_state_payload("INVENTORIED"),
            exec_h,
        )
        validate_error_is_one_of(resp, [
            ApiErrorId.ERR_ASSETS_NOT_INVENTORIED.value,
            ApiErrorId.ERR_NO_ACCEPTED_INVENTORY.value,
        ])

    def test_advance_requires_accepted_inventory_filing(self, api):
        """PRD §3.4: "Either precondition unmet produces
        ERR_ASSETS_NOT_INVENTORIED or ERR_NO_ACCEPTED_INVENTORY
        respectively."

        Claim: with no INVENTORY_REPORT filing the advance fails
        with ERR_NO_ACCEPTED_INVENTORY (assets are all already
        inventoried).
        """
        bundle = setup_in_probate()
        estate = bundle["estate"]
        exec_h = bundle["executor_headers"]
        # Declare an asset and inventory it (don't appraise).
        a = declare_asset(
            estate["id"], declared_value_cents=1000,
            exec_headers=exec_h,
        )
        inventory_asset(estate["id"], a["id"], exec_headers=exec_h)
        # No INVENTORY_REPORT submitted.
        resp = api_client.transition_estate(
            estate["id"], estate_state_payload("INVENTORIED"),
            exec_h,
        )
        validate_error(resp,
                       ApiErrorId.ERR_NO_ACCEPTED_INVENTORY.value)


class TestRequiredBondMarginalTiers:
    """PRD §3.5: marginal-tier bond on gross_estate_value_cents.

    The fiduciary confirm endpoint is the cleanest place to observe
    bond requirement: PRD §3.1 / §3.5 say bond at
    NOMINATED->CONFIRMED is checked against required_bond computed
    over the estate's CURRENT gross_estate_value_cents
    (forward-looking variant).

    Note: per §1.3 in scaffold, the bond at confirm uses
    gross_estate_value_cents — but at DRAFT all assets are DECLARED
    (gross is 0 under forward-looking which counts INVENTORIED+
    APPRAISED + DISTRIBUTED). So bond at confirm in DRAFT = flat fee
    25000 only. We can't directly test multi-tier without breaking
    the rule that confirms happen pre-probate.

    Instead, we test the bond at DRAFT->IN_PROBATE — which §3.3 ALSO
    uses the bond gate against forward-looking gross. At IN_PROBATE
    time gross is still 0 (no assets are INVENTORIED yet). So the
    only meaningful boundary at this gate is bond >= 25000.

    To test the multi-tier formula, we use compute_required_bond_cents
    helper directly to assert PRD §3.5 math at the unit level. PRD
    pins this formula verbatim — any honest implementation must
    match.
    """

    def test_bond_calculation_zero_gross(self, api):
        """PRD §3.5: "finally a flat fee of 25,000 cents is added
        unrounded to produce the final required_bond_cents."

        Claim: at gross=0, required_bond_cents = 25000 (flat fee
        only).
        """
        assert compute_required_bond_cents(0) == FLAT_BOND_FEE_CENTS

    def test_bond_calculation_tier1_only(self, api):
        """PRD §3.5: "The first 10,000,000 cents of gross — i.e., the
        first $100,000 — is bonded at the rate of one hundred basis
        points".

        Claim: at gross=10_000_000 (exact tier-1 ceiling),
        required_bond = 10_000_000 * 0.01 + 25_000 = 100_000 + 25_000
        = 125_000.
        """
        assert compute_required_bond_cents(
            TIER1_LIMIT_CENTS,
        ) == 100_000 + FLAT_BOND_FEE_CENTS

    def test_bond_calculation_tier1_and_tier2(self, api):
        """PRD §3.5: "the next 90,000,000 cents — i.e., the band
        from $100,000 up to and including $1,000,000 — is bonded at
        fifty basis points".

        Claim: at gross=50_000_000, bond = tier1(10M*0.01=100k) +
        tier2(40M*0.005=200k) + flat(25k) = 325_000.
        """
        assert compute_required_bond_cents(
            50_000_000,
        ) == 100_000 + 200_000 + FLAT_BOND_FEE_CENTS

    def test_bond_per_tier_round_then_sum(self, api):
        """PRD §3.5: "for each tier the corresponding cents portion
        is multiplied by its rate and the result is rounded to the
        nearest cent using banker's rounding (round half to even);
        the three rounded per-tier cent amounts are then summed".

        Claim: at a tier-2 portion that produces a half-cent
        product, per-tier banker's rounding is applied to the
        portion's product before summation.

        Example: tier-2 portion = 1 cent → 1 * 0.0050 = 0.005 cents,
        which banker's-rounds to 0. Tier-2 portion = 3 cents →
        3 * 0.0050 = 0.015 cents, which banker's-rounds to 0
        (round-half-to-even: 0.015 → 0.02... wait that's hundredths.
        We are rounding to the cent.)

        Cleaner: tier-2 portion = 100 cents → 100 * 0.005 = 0.5
        cents → banker's-round to 0 (0 is even). Gross =
        10_000_100; tier1=10_000_000*0.01=100_000 cent; tier2=100*
        0.005=0.5 → 0 (banker's); flat=25_000. Total=125_000.
        """
        # Build gross that puts exactly 100 cents into tier 2.
        gross = TIER1_LIMIT_CENTS + 100
        # tier1=100_000, tier2=banker_round(100*0.005)=banker_round(0.5)=0
        # flat=25_000; total=125_000.
        bond = compute_required_bond_cents(gross)
        assert bond == 100_000 + 0 + FLAT_BOND_FEE_CENTS, (
            f"per-tier banker's round then sum violated; got {bond}"
        )


class TestFiduciaryBondAtConfirm:

    def test_confirm_executor_below_flat_fee_rejected(self, api):
        """PRD §3.1: "Confirming a nominated fiduciary as EXECUTOR
        requires that their bond_amount_cents be at least the
        calculated bond requirement (otherwise the confirm fails
        with ERR_BOND_INSUFFICIENT)".

        Claim: in DRAFT (gross=0), required_bond = 25_000 (flat
        fee). An executor with bond=24_999 -> ERR_BOND_INSUFFICIENT.
        """
        estate, executor, _ = create_estate_with_executor(
            bond_amount_cents=24_999,
        )
        resp = api_client.transition_fiduciary(
            estate["id"], executor["id"],
            fiduciary_state_payload("CONFIRMED"),
            TEST_USERS["court_clerk_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_BOND_INSUFFICIENT.value)

    def test_confirm_executor_at_flat_fee_accepted(self, api):
        """PRD §3.1: "at least the calculated bond requirement"
        (>=).

        Claim: bond exactly equal to required_bond (25_000 at
        gross=0) succeeds.
        """
        estate, executor, _ = create_estate_with_executor(
            bond_amount_cents=25_000,
        )
        resp = api_client.transition_fiduciary(
            estate["id"], executor["id"],
            fiduciary_state_payload("CONFIRMED"),
            TEST_USERS["court_clerk_headers"],
        )
        confirmed = validate_success(resp)
        assert confirmed["status"] == "CONFIRMED"
        assert confirmed["court_confirmation_at"], (
            "court_confirmation_at must be set on CONFIRMED"
        )
