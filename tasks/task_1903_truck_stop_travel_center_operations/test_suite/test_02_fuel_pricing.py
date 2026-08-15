"""Retail and contract fuel pricing: quote composition, provisional vs final
variants, price windows, supersede/truncate, and OCC on the price book."""
import pytest

from test_helpers import (
    ApiErrorId,
    create_fuel_price_payload,
    create_fuel_sale_payload,
    post_fuel_price,
    set_clock,
    setup_contract_site,
    setup_enrolled_member,
    setup_fuel_site,
    validate_error,
    validate_success,
    api_client,
)
from test_helpers.constants import DEFAULT_CLOCK_ISO, TEST_CLOCK_ISO
from test_helpers.fixtures import (
    CASH_1,
    FDL,
    GM,
    authorize_retail_sale,
    create_pump,
    create_register,
    finalize_fuel_sale,
    open_shift,
    reload_member,
    reload_site,
    void_sale,
)


def _finalize_retail_200pt_sale():
    """Full recipe: diesel 385, member 9000 pts enrolled in a 0.10-off
    network; RETAIL sale redeeming 200 points with max_gallons 40, dispensed
    38."""
    ctx = setup_fuel_site("Site A", diesel_cents=385, clock=TEST_CLOCK_ISO)
    env = setup_enrolled_member(points=9000)
    sale = authorize_retail_sale(
        ctx, member_id=env.member["id"], redeem_points=200, max_gallons=40.0
    )
    return ctx, env, sale


class TestProvisionalVsFinalVariants:
    def test_retail_sale_provisional_and_final_totals_differ(self, api):
        """PRD section 3.2: "Multiplying it by `max_gallons` yields
        `provisional_fuel_total_cents`, the provisional variant of the sale
        total." and "The provisional and final totals therefore differ exactly
        when dispensed volume differs from the authorized cap."
        PRD section 3.2: "The fuel amount is that unit price multiplied by the
        actual `dispensed_gallons`, rounded half up to whole cents, recorded
        as `fuel_amount_cents`."

        Design: Difficulty/dual_variant_calc/fuel_sale_provisional_vs_final_totals
        """
        _, _, sale = _finalize_retail_200pt_sale()
        # 385 - 10 network - min(200, 500) x 0.5 points = 275 cents/gal
        assert sale["authorized_quote_cents_per_gallon"] == 275
        assert sale["provisional_fuel_total_cents"] == 11000  # 275 x 40.000

        finalized = finalize_fuel_sale(sale["id"], 38.0)
        assert finalized["status"] == "COMPLETED"
        assert finalized["final_unit_price_cents"] == 275
        assert finalized["fuel_amount_cents"] == 10450  # 275 x 38.000
        assert finalized["total_cents"] == 10450
        assert finalized["provisional_fuel_total_cents"] == 11000
        assert finalized["total_cents"] != finalized["provisional_fuel_total_cents"]

    def test_retail_finalize_loyalty_debit_and_credit(self, api):
        """PRD section 3.2: "Loyalty then settles both directions: the
        requested points burn FEFO from the member's lots and are recorded as
        `points_redeemed` with their cent value in `points_discount_cents`,
        while earned points — the post-redemption `total_cents` divided by one
        hundred, multiplied by 0.5 points per dollar, rounded half up — are
        granted as a new lot expiring 360 days out, recorded as
        `points_earned`, and the member's `points_balance` is recomputed."

        Design: Difficulty/dual_variant_calc/fuel_sale_provisional_vs_final_totals
        """
        _, env, sale = _finalize_retail_200pt_sale()
        finalized = finalize_fuel_sale(sale["id"], 38.0)

        assert finalized["points_redeemed"] == 200
        assert finalized["points_discount_cents"] == 100
        # round_half_up(104.50 x 0.5) = round_half_up(52.25) = 52
        assert finalized["points_earned"] == 52

        member = reload_member(env.member["id"])
        assert member["points_balance"] == 8852  # 9000 - 200 + 52


class TestRetailQuoteStacking:
    def _setup_stacking(self):
        ctx = setup_fuel_site(
            "Site C",
            diesel_cents=385,
            extra_prices=[("GAS_REGULAR", 50)],
            clock=TEST_CLOCK_ISO,
            num_pumps=3,
            pump_fuel_types=[("DIESEL",), ("DIESEL",), ("GAS_REGULAR",)],
        )
        env_a = setup_enrolled_member(points=9000, full_name="Driver A",
                                      email="a@x.com",
                                      fuel_types=("DIESEL", "GAS_REGULAR"))
        env_b = setup_enrolled_member(points=9000, stack_cap_points=100,
                                      full_name="Driver B", email="b@x.com",
                                      fuel_types=("DIESEL", "GAS_REGULAR"),
                                      network_name="FleetPass-B")
        return ctx, env_a, env_b

    def test_retail_quote_stack_cap_clamps_points_leg(self, api):
        """PRD section 3.2: "The redemption count is the smaller of
        `requested_redeem_points` and the member's `stack_cap_points`, itself
        pinned as `stack_cap_snapshot`; each point is worth half a cent, so
        the points allowance is the redemption count multiplied by 0.5 cents,
        rounded half up to whole cents." and "The provisional unit price is
        the retail basis minus the network allowance converted to cents ...
        then minus the points allowance, floored at zero, and is stored as
        `authorized_quote_cents_per_gallon`."

        Design: Difficulty/combinatorial_formula/retail_quote_stacking_min_and_floor
        """
        ctx, env_a, env_b = self._setup_stacking()
        sale_a = authorize_retail_sale(
            ctx, pump_idx=0, member_id=env_a.member["id"], redeem_points=200,
            max_gallons=10.0,
        )
        assert sale_a["authorized_quote_cents_per_gallon"] == 275
        assert sale_a["stack_cap_snapshot"] == 500

        sale_b = authorize_retail_sale(
            ctx, pump_idx=1, member_id=env_b.member["id"], redeem_points=120,
            max_gallons=10.0,
        )
        # min(120, 100) = 100 points -> 50 cents allowance
        assert sale_b["stack_cap_snapshot"] == 100
        assert sale_b["authorized_quote_cents_per_gallon"] == 325

    def test_retail_quote_floors_at_zero_and_finalize_burns_points(self, api):
        """PRD section 3.2: "The provisional unit price is the retail basis
        minus the network allowance converted to cents — that subtraction
        rounded half up to whole cents — then minus the points allowance,
        floored at zero".
        PRD section 3.2: "the requested points burn FEFO from the member's
        lots and are recorded as `points_redeemed` with their cent value in
        `points_discount_cents`".

        Design: Difficulty/combinatorial_formula/retail_quote_stacking_min_and_floor
        """
        ctx, env_a, _ = self._setup_stacking()
        sale_c = authorize_retail_sale(
            ctx, pump_idx=2, member_id=env_a.member["id"], redeem_points=100,
            max_gallons=10.0, fuel_type="GAS_REGULAR",
        )
        # max(0, 50 - 10 - 50) = 0
        assert sale_c["authorized_quote_cents_per_gallon"] == 0

        finalized = finalize_fuel_sale(sale_c["id"], 10.0)
        assert finalized["total_cents"] == 0
        assert finalized["points_redeemed"] == 100
        assert finalized["points_earned"] == 0

        member = reload_member(env_a.member["id"])
        assert member["points_balance"] == 8900  # 9000 - 100 + 0


class TestContractQuoteTierTable:
    def test_contract_quote_tier_table(self, api):
        """PRD section 3.2: "The server adds a freight allowance of 0.1500
        dollars per gallon and subtracts the tier margin baked into the
        contract's own `pricing_tier` — 0.02 dollars per gallon for `T1`,
        0.05 for `T2`, and 0.09 for `T3` — rounding the result half up at four
        decimal places, then multiplying by one hundred and rounding half up
        to integer cents".

        Design: Corner/calculations/calc_contract_quote_tier_table
        """
        from test_helpers.fixtures import (
            authorize_contract_sale,
            create_contract,
            create_fleet,
        )

        ctx = setup_contract_site("Site C3", rack_price_4dp=2.7000,
                                  clock=TEST_CLOCK_ISO, num_pumps=3)
        fleet = create_fleet("Fleet A", 50_000_000, "T1")
        contracts = {}
        for code, tier in (("C-T1", "T1"), ("C-T2", "T2"), ("C-T3", "T3")):
            contract = create_contract(fleet["id"], code, tier, 0.0)
            validate_success(api.contract_activate(contract["id"], GM))
            contracts[tier] = contract["id"]

        q1 = authorize_contract_sale(ctx, fleet["id"], contracts["T1"],
                                     pump_idx=0, max_gallons=50.0)
        q2 = authorize_contract_sale(ctx, fleet["id"], contracts["T2"],
                                     pump_idx=1, max_gallons=50.0)
        q3 = authorize_contract_sale(ctx, fleet["id"], contracts["T3"],
                                     pump_idx=2, max_gallons=50.0)

        assert q1["authorized_quote_cents_per_gallon"] == 283  # 2.7000+0.1500-0.02
        assert q2["authorized_quote_cents_per_gallon"] == 280  # -0.05
        assert q3["authorized_quote_cents_per_gallon"] == 276  # -0.09


class TestPriceWindowsAndOcc:
    def test_future_price_activates_on_clock(self, api):
        """PRD section 3.1: "Because window effectiveness is evaluated against
        the logical clock, a future-dated price simply becomes the selected
        quote as the clock advances into its window."
        PRD section 3.1: "When an existing price starts strictly earlier than
        the new one, it is truncated — its `effective_to` is rewritten to the
        new price's `effective_from` and it stays `ACTIVE`."

        Design: Corner/complexity_layers/layer_future_price_activates_on_clock
        """
        from test_helpers.fixtures import create_site

        site = create_site("Site L2")
        price_a, _ = post_fuel_price(site["id"], "DIESEL", 385)
        price_b, _ = post_fuel_price(
            site["id"], "DIESEL", 399, effective_from="2026-08-20T00:00:00Z"
        )
        set_clock(TEST_CLOCK_ISO)
        pump = create_pump(site["id"], 1, ("DIESEL",))
        register = create_register(site["id"])
        shift = open_shift(site["id"], register["id"])
        ctx_site = site

        payload = create_fuel_sale_payload(
            pump["id"], shift["id"], pricing_mode="RETAIL", fuel_type="DIESEL",
            tender_type="CASH", max_gallons=10.0,
        )
        sale1 = validate_success(
            api.create_fuel_sale(ctx_site["id"], payload, CASH_1), 201
        )
        assert sale1["authorized_quote_cents_per_gallon"] == 385
        void_sale(sale1["id"], "quote probe")

        set_clock("2026-08-21T00:00:00Z")
        sale2 = validate_success(
            api.create_fuel_sale(ctx_site["id"], payload, CASH_1), 201
        )
        assert sale2["authorized_quote_cents_per_gallon"] == 399

        site_now = reload_site(site["id"])
        assert site_now["diesel_retail_cents_per_gallon"] == 399

        price_a_now = validate_success(api.get_fuel_price(price_a["id"], FDL))
        assert price_a_now["effective_to"] == "2026-08-20T00:00:00Z"
        assert price_a_now["status"] == "ACTIVE"

    def test_duplicate_price_start_rejected_later_start_truncates(self, api):
        """PRD section 3.1: "When the new `effective_from` exactly equals an
        existing `ACTIVE` same-fuel price's `effective_from`, the duplicate
        start is rejected outright with `ERR_OVERLAPPING_PRICE_WINDOW`
        (HTTP 422), as is any malformed window."
        PRD section 3.1: "When an existing price starts strictly earlier than
        the new one, it is truncated — its `effective_to` is rewritten to the
        new price's `effective_from` and it stays `ACTIVE`."

        Design: Corner/validations/validation_duplicate_price_window_start_rejected
        """
        from test_helpers.fixtures import create_site

        site = create_site("Site V5")
        price_a, site_v = post_fuel_price(site["id"], "DIESEL", 385)

        dup = api.create_fuel_price(
            site["id"],
            create_fuel_price_payload(site_v, "DIESEL", 390,
                                      effective_from=DEFAULT_CLOCK_ISO),
            FDL,
        )
        validate_error(dup, ApiErrorId.ERR_OVERLAPPING_PRICE_WINDOW)

        later = api.create_fuel_price(
            site["id"],
            create_fuel_price_payload(site_v, "DIESEL", 390,
                                      effective_from="2026-08-20T00:00:00Z"),
            FDL,
        )
        validate_success(later, 201)

        price_a_now = validate_success(api.get_fuel_price(price_a["id"], FDL))
        assert price_a_now["effective_to"] == "2026-08-20T00:00:00Z"
        assert price_a_now["status"] == "ACTIVE"

    def test_occ_fuel_price_stale_rejected(self, api):
        """PRD section 2.6: "when `expected_site_version` does not match the
        site's current `version`, the create is rejected with
        `ERR_STALE_VERSION` (HTTP 412). A successful price posting increments
        the site's `version` by 1."

        Design: Corner/complexity_layers/layer_occ_fuel_price_stale_rejected
        """
        from test_helpers.fixtures import create_site

        site = create_site("Site L1")
        stale_version = site["version"]

        first = api.create_fuel_price(
            site["id"],
            create_fuel_price_payload(stale_version, "DIESEL", 385),
            FDL,
        )
        validate_success(first, 201)

        stale = api.create_fuel_price(
            site["id"],
            create_fuel_price_payload(stale_version, "DIESEL", 390,
                                      effective_from="2026-08-20T00:00:00Z"),
            FDL,
        )
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION, 412)

        site_now = reload_site(site["id"])
        assert site_now["version"] == stale_version + 1, (
            "exactly one successful price posting must have bumped the site "
            "version"
        )

    def test_no_active_price_for_fuel_type(self, api):
        """PRD section 3.2: "The server selects the site's `ACTIVE` price row
        for the requested `fuel_type` whose window contains the current clock
        ... creation-time overlap rules guarantee at most one match, and none
        at all is `ERR_NO_ACTIVE_PRICE` (HTTP 422)."

        Design: Corner/errors/error_no_active_price_for_fuel_type
        """
        ctx = setup_fuel_site("Site R7", diesel_cents=385, clock=TEST_CLOCK_ISO,
                              pump_fuel_types=("DIESEL", "DEF"))
        payload = create_fuel_sale_payload(
            ctx.pumps[0]["id"], ctx.shift["id"], pricing_mode="RETAIL",
            fuel_type="DEF", tender_type="CASH", max_gallons=10.0,
        )
        resp = api.create_fuel_sale(ctx.site["id"], payload, CASH_1)
        validate_error(resp, ApiErrorId.ERR_NO_ACTIVE_PRICE)
