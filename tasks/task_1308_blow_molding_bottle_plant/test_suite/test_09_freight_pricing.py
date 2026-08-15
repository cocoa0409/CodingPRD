"""Freight-of-air pricing: dual-variant warehouse vs blow-on-site comparison, pinned per-pallet dim-weight rounding order, marginal tier boundary, and the missing-rate-card rule."""
import pytest

from test_helpers import (
    validate_success, validate_error, get_success_data,
    create_customer, create_spec, create_rate_card,
    setup_qualified_plant,
    create_freight_quote_payload, create_bottle_spec_payload,
    api_client, ApiErrorId, TEST_USERS,
)

ENGINEER = TEST_USERS["process_engineer"]
LOGISTICS = TEST_USERS["logistics_coordinator"]


class TestWarehouseVsBlowOnSite:
    def _setup_comparison(self):
        """Customer + ACTIVE card (0->120, 500->90, 2000->60 cents/kg) + QUALIFIED spec (bottle cube 4000 cm3, preform cube 150 cm3, weights 22 g)."""
        return setup_qualified_plant(with_rate_card=True)

    def test_identical_quantity_diverges_between_modes(self, api):
        """PRD §3.2: "It reports `warehouse_total_cents` — the freight-of-air charge for shipping finished bottles — and `blow_on_site_total_cents`, which is the freight-of-air charge for shipping the same number of preforms plus an on-site machine fee of 40 cents per bottle."

Design: Difficulty/dual_variant_calc/freight_warehouse_vs_blow_on_site_divergence"""
        ctx = self._setup_comparison()
        res = api.get_logistics_comparison(
            ctx["spec"]["id"], LOGISTICS, params={"quantity": 3000})
        data = validate_success(res, 200)
        # warehouse: 2 full pallets x 1024.0 kg dim = 2048.0 chargeable;
        # 500*120 + 1500*90 + 48*60 = 197880
        assert data["warehouse_total_cents"] == 197880
        # blow-on-site: preform chargeable 99.0 kg * 120 = 11880 freight
        # plus 3000 * 40 = 120000 on-site fee = 131880
        assert data["blow_on_site_total_cents"] == 131880
        # same inputs, two variants diverge
        assert data["warehouse_total_cents"] != data["blow_on_site_total_cents"]

    def test_recommended_mode_picks_strictly_cheaper_blow_on_site(self, api):
        """PRD §3.2: "The `recommended_mode` is `WAREHOUSE` whenever the warehouse total is less than or equal to the blow-on-site total, so ties break toward the warehouse, and `BLOW_ON_SITE` only when it is strictly cheaper."

Design: Difficulty/dual_variant_calc/freight_warehouse_vs_blow_on_site_divergence"""
        ctx = self._setup_comparison()
        res = api.get_logistics_comparison(
            ctx["spec"]["id"], LOGISTICS, params={"quantity": 3000})
        data = validate_success(res, 200)
        # 131880 < 197880 — strictly cheaper blow-on-site
        assert data["recommended_mode"] == "BLOW_ON_SITE"


class TestPerPalletRoundingOrder:
    def _setup_quote(self, api):
        customer = create_customer()
        create_rate_card()
        spec = get_success_data(api.create_bottle_spec(
            create_bottle_spec_payload(customer["id"], spec_code="B330",
                                       color_contrast_class="LIGHT",
                                       bottle_cube_cm3=3325, unit_price_cents=7,
                                       label_type="NONE"),
            ENGINEER))
        return spec

    def test_dim_weight_rounded_per_pallet_then_summed(self, api):
        """PRD §3.8: "Dimensional weight obeys a pinned rounding order that implementers must follow exactly: it is computed per pallet and rounded before summing, never aggregated first. Each full pallet's dimensional weight is its contents' cube plus the 144,000-cubic-centimeter pallet cube, divided by the dim divisor of 6,000 cubic centimeters per kilogram, rounded half-up to one decimal of a kilogram."

Design: Difficulty/combinatorial_formula/freight_per_pallet_rounding_order"""
        spec = self._setup_quote(api)
        res = api.create_freight_quote(
            create_freight_quote_payload(spec["id"], 4500), LOGISTICS)
        quote = validate_success(res, 200)
        assert quote["pallets"] == 3            # ceil(4500 / 1500)
        # per pallet: (1500*3325 + 144000) / 6000 = 855.25 -> 855.3 half-up;
        # 3 x 855.3 = 2565.9 (aggregate-then-round would give 2565.8)
        assert quote["dim_weight_kg"] == pytest.approx(2565.9, abs=1e-6)
        # actual: 4500*22/1000 + 3*20 = 159.0
        assert quote["actual_weight_kg"] == pytest.approx(159.0, abs=1e-6)
        assert quote["chargeable_weight_kg"] == pytest.approx(2565.9, abs=1e-6)

    def test_freight_and_trucks_from_pinned_rounding(self, api):
        """PRD §3.8: "Each tier's charge — its kilograms times its `rate_cents_per_kg` — is rounded half-up to whole cents first, and the tier charges are then summed". "the pallets a truck carries is the smaller of the truck's 96,000,000-cubic-centimeter cube divided by the pallet cube and the truck's 24,000-kilogram payload divided by the pallet gross weight, each division rounded down, and the `trucks` needed is the pallet count divided by that capacity, rounded up."

Design: Difficulty/combinatorial_formula/freight_per_pallet_rounding_order"""
        spec = self._setup_quote(api)
        res = api.create_freight_quote(
            create_freight_quote_payload(spec["id"], 4500), LOGISTICS)
        quote = validate_success(res, 200)
        # 500*120 + 1500*90 + 565.9*60 = 60000 + 135000 + 33954 = 228954
        assert quote["freight_cost_cents"] == 228954
        # pallets/truck = min(floor(96000000/5131500), floor(24000/53))
        #               = min(18, 452) = 18; trucks = ceil(3/18) = 1
        assert quote["trucks"] == 1


class TestTierBoundary:
    def _setup_boundary_spec(self, api):
        customer = create_customer()
        create_rate_card()
        spec = get_success_data(api.create_bottle_spec(
            create_bottle_spec_payload(customer["id"]), ENGINEER))
        return spec

    def test_chargeable_exactly_at_tier_boundary(self, api):
        """PRD §3.8: "Tier boundaries are the brackets' `min_kg` values: the first tier covers from zero up to the second tier's `min_kg`, each subsequent tier covers from its own `min_kg` up to the next tier's, and the last tier is unbounded; the kilograms billed in a tier are the portion of the chargeable weight falling inside that span."

Design: Difficulty/boundary_precision_check/freight_tier_boundary_at_exactly_2000kg"""
        spec = self._setup_boundary_spec(api)
        res = api.create_freight_quote(
            create_freight_quote_payload(spec["id"], 2928), LOGISTICS)
        quote = validate_success(res, 200)
        # pallets: 1 full (1024.0) + remainder 1428 -> 976.0; dim 2000.0
        assert quote["chargeable_weight_kg"] == pytest.approx(2000.0, abs=1e-6)
        # zero kg spill into the 60c tier at the exact boundary:
        # 500*120 + 1500*90 = 195000
        assert quote["freight_cost_cents"] == 195000

    def test_one_kg_step_above_tier_boundary(self, api):
        """PRD §3.8: "the kilograms billed in a tier are the portion of the chargeable weight falling inside that span. Each tier's charge — its kilograms times its `rate_cents_per_kg` — is rounded half-up to whole cents first, and the tier charges are then summed".

Design: Difficulty/boundary_precision_check/freight_tier_boundary_at_exactly_2000kg"""
        spec = self._setup_boundary_spec(api)
        res = api.create_freight_quote(
            create_freight_quote_payload(spec["id"], 2929), LOGISTICS)
        quote = validate_success(res, 200)
        # remainder 1429 -> per-pallet dim 976.7; chargeable 2000.7
        assert quote["chargeable_weight_kg"] == pytest.approx(2000.7, abs=1e-6)
        # 0.7 kg crosses into the 60c tier: 195000 + round(0.7*60) = 195042
        assert quote["freight_cost_cents"] == 195042


class TestRateCardMissing:
    def test_freight_quote_without_active_card_rejected(self, api):
        """PRD §2.6: "any freight computation requires an `ACTIVE` freight rate card to exist, and its absence is reported as `ERR_RATE_CARD_NOT_FOUND` (HTTP 404)."

Design: Corner/errors/get_missing_rate_card_returns_not_found"""
        customer = create_customer()
        spec = get_success_data(api.create_bottle_spec(
            create_bottle_spec_payload(customer["id"], label_type="NONE"),
            ENGINEER))
        res = api.create_freight_quote(
            create_freight_quote_payload(spec["id"], 1000), LOGISTICS)
        validate_error(res, ApiErrorId.ERR_RATE_CARD_NOT_FOUND)
