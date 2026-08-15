"""Booking creation, derived freight fields, and charge decomposition."""
import pytest

from test_helpers import (
    ApiErrorId,
    create_draft_freight_invoice,
    create_fcl_booking_payload,
    create_lcl_booking_payload,
    setup_fcl_lane,
    setup_lcl_lane,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import BC
from test_helpers.test_users import make_shipper_headers


class TestBookingCreation:
    def test_booking_creation_success_with_system_and_computed_fields(self, api):
        """PRD §3.6: "On creation the booking enters `QUOTED` with a
        server-minted `booking_number` of the form `BK-<seq>`."
        PRD §2.4: "`version` (integer): a system-managed counter that starts
        at 1 on creation and increments by one on every mutation of the
        resource."

        Design: Corner/entities/booking_creation_success_with_system_and_computed_fields
        """
        ctx = setup_lcl_lane()
        booking = validate_success(
            api.create_booking(
                create_lcl_booking_payload(ctx["voyage"]["id"],
                                           ctx["tariff"]["id"]),
                make_shipper_headers(ctx["shipper"]["id"])),
            201)
        assert booking["status"] == "QUOTED"
        assert booking["version"] == 1
        assert isinstance(booking["booking_number"], str)
        assert booking["booking_number"].startswith("BK-")
        assert booking["shipper_id"] == ctx["shipper"]["id"]
        assert booking["chargeable_weight_rt"] == pytest.approx(6.0)
        assert booking["estimated_freight_cents"] == 77400

    def test_booking_create_computed_field_input_ignored(self, api):
        """PRD §3.6: "Two derived fields are computed immediately. The
        `chargeable_weight_rt` is the revenue-ton figure: the greater of
        `gross_weight_kg` divided by 1000 and `volume_cbm` — that is, one
        revenue ton is one metric tonne or one cubic metre, whichever yields
        more — rounded half-up to three decimal places."
        PRD §2.4: "`version` (integer): a system-managed counter that starts
        at 1 on creation and increments by one on every mutation of the
        resource."

        Design: Corner/entities/booking_create_computed_field_input_ignored
        """
        ctx = setup_lcl_lane()
        payload = create_lcl_booking_payload(ctx["voyage"]["id"],
                                             ctx["tariff"]["id"])
        payload["estimated_freight_cents"] = 1
        payload["chargeable_weight_rt"] = 99.0
        payload["version"] = 42
        booking = validate_success(
            api.create_booking(payload,
                               make_shipper_headers(ctx["shipper"]["id"])),
            201)
        assert booking["estimated_freight_cents"] == 77400, (
            "injected computed value must be ignored in favor of the server value"
        )
        assert booking["chargeable_weight_rt"] == pytest.approx(6.0)
        assert booking["version"] == 1

    def test_booking_create_invalid_enum_rejected(self, api):
        """PRD §2.8: "(5) request body shape — required fields present, enum
        members valid, numerics positive where required, conditional fields
        honored (a `SPOT` rate source must carry `spot_rate_per_unit_cents`;
        an `FCL` mode must carry `container_type` and `container_count`; an
        `LCL` mode forbids both)".

        Design: Corner/entities/booking_create_invalid_enum_rejected
        """
        ctx = setup_lcl_lane()
        payload = create_lcl_booking_payload(ctx["voyage"]["id"],
                                             ctx["tariff"]["id"],
                                             commodity_type="BIOHAZARD")
        res = api.create_booking(payload,
                                 make_shipper_headers(ctx["shipper"]["id"]))
        validate_error(res, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)

    def test_spot_booking_without_spot_rate_rejected(self, api):
        """PRD §2.8: "(5) request body shape — required fields present, enum
        members valid, numerics positive where required, conditional fields
        honored (a `SPOT` rate source must carry `spot_rate_per_unit_cents`;
        an `FCL` mode must carry `container_type` and `container_count`; an
        `LCL` mode forbids both)".
        PRD §3.6: "supplies `spot_rate_per_unit_cents` when `SPOT` is declared
        (forbidden when `CONTRACT`)".

        Design: Corner/errors/spot_booking_without_spot_rate_rejected
        """
        ctx = setup_lcl_lane()
        payload = create_lcl_booking_payload(ctx["voyage"]["id"],
                                             ctx["tariff"]["id"],
                                             rate_source="SPOT")
        res = api.create_booking(payload,
                                 make_shipper_headers(ctx["shipper"]["id"]))
        validate_error(res, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)


class TestContractVsSpotRateDivergence:
    def test_contract_rate_booking_estimate(self, api):
        """PRD §3.6: "The unit rate is the tariff's `rate_per_unit_cents` when
        `rate_source` is `CONTRACT`, and the booking's own
        `spot_rate_per_unit_cents` when `rate_source` is `SPOT` — identical
        cargo priced under the two variants can land at different totals."
        PRD §3.6: "For `LCL`, the base is the greater of the chargeable
        revenue tons multiplied by the unit rate and the tariff's
        `minimum_charge_cents`, with the result rounded half-up to integer
        cents after the comparison, and the terminal handling charge is the
        chargeable revenue tons multiplied by 1200 cents per revenue ton,
        rounded half-up."

        Design: Difficulty/dual_variant_calc/contract_vs_spot_rate_freight_divergence
        """
        ctx = setup_lcl_lane()
        booking = validate_success(
            api.create_booking(
                create_lcl_booking_payload(ctx["voyage"]["id"],
                                           ctx["tariff"]["id"]),
                make_shipper_headers(ctx["shipper"]["id"])),
            201)
        # 6.0 RT x 9500 = 57000 base; + BAF 5700 + THC 7200 + DOC 7500.
        assert booking["estimated_freight_cents"] == 77400

    def test_spot_rate_booking_estimate_diverges(self, api):
        """PRD §3.6: "The unit rate is the tariff's `rate_per_unit_cents` when
        `rate_source` is `CONTRACT`, and the booking's own
        `spot_rate_per_unit_cents` when `rate_source` is `SPOT` — identical
        cargo priced under the two variants can land at different totals."

        Design: Difficulty/dual_variant_calc/contract_vs_spot_rate_freight_divergence
        """
        ctx = setup_lcl_lane()
        contract_booking = validate_success(
            api.create_booking(
                create_lcl_booking_payload(ctx["voyage"]["id"],
                                           ctx["tariff"]["id"]),
                make_shipper_headers(ctx["shipper"]["id"])),
            201)
        spot_booking = validate_success(
            api.create_booking(
                create_lcl_booking_payload(ctx["voyage"]["id"],
                                           ctx["tariff"]["id"],
                                           rate_source="SPOT",
                                           spot_rate_per_unit_cents=8000),
                make_shipper_headers(ctx["shipper"]["id"])),
            201)
        # SPOT: 6.0 RT x 8000 = 48000 base; + BAF 4800 + THC 7200 + DOC 7500.
        assert spot_booking["estimated_freight_cents"] == 67500
        assert (contract_booking["estimated_freight_cents"]
                - spot_booking["estimated_freight_cents"]) == 9900


class TestLclWeightMeasureRule:
    def test_chargeable_weight_volume_leg_wins(self, api):
        """PRD §3.6: "The `chargeable_weight_rt` is the revenue-ton figure:
        the greater of `gross_weight_kg` divided by 1000 and `volume_cbm` —
        that is, one revenue ton is one metric tonne or one cubic metre,
        whichever yields more — rounded half-up to three decimal places."

        Design: Difficulty/combinatorial_formula/ocean_freight_lcl_wm_rule_minimum_floor_mode_a
        """
        ctx = setup_lcl_lane()
        booking = validate_success(
            api.create_booking(
                create_lcl_booking_payload(ctx["voyage"]["id"],
                                           ctx["tariff"]["id"]),
                make_shipper_headers(ctx["shipper"]["id"])),
            201)
        # 4000 kg / 1000 = 4.0 loses to 6.0 cbm under the W/M max().
        assert booking["chargeable_weight_rt"] == pytest.approx(6.0)

    def test_lcl_estimate_decomposition(self, api):
        """PRD §3.6: "For `LCL`, the base is the greater of the chargeable
        revenue tons multiplied by the unit rate and the tariff's
        `minimum_charge_cents`, with the result rounded half-up to integer
        cents after the comparison, and the terminal handling charge is the
        chargeable revenue tons multiplied by 1200 cents per revenue ton,
        rounded half-up. On either mode, the bunker adjustment factor is the
        base multiplied by ten percent, rounded half-up, and a documentation
        fee of 7500 cents is added. The total `estimated_freight_cents` is the
        sum of the base, the bunker adjustment, the terminal handling charge,
        and the documentation fee."

        Design: Difficulty/combinatorial_formula/ocean_freight_lcl_wm_rule_minimum_floor_mode_a
        """
        ctx = setup_lcl_lane()
        booking = validate_success(
            api.create_booking(
                create_lcl_booking_payload(ctx["voyage"]["id"],
                                           ctx["tariff"]["id"]),
                make_shipper_headers(ctx["shipper"]["id"])),
            201)
        # base = max(6.0 x 9500, 20000) = 57000; BAF = 5700; THC = 7200;
        # DOC = 7500 -> 77400.
        assert booking["estimated_freight_cents"] == 77400

    def test_lcl_minimum_charge_floor_binds_small_cargo(self, api):
        """PRD §3.6: "For `LCL`, the base is the greater of the chargeable
        revenue tons multiplied by the unit rate and the tariff's
        `minimum_charge_cents`, with the result rounded half-up to integer
        cents after the comparison, and the terminal handling charge is the
        chargeable revenue tons multiplied by 1200 cents per revenue ton,
        rounded half-up."

        Design: Corner/calculations/lcl_minimum_charge_floor_binds_small_cargo
        """
        ctx = setup_lcl_lane()
        booking = validate_success(
            api.create_booking(
                create_lcl_booking_payload(ctx["voyage"]["id"],
                                           ctx["tariff"]["id"],
                                           gross_weight_kg=500,
                                           volume_cbm=0.4),
                make_shipper_headers(ctx["shipper"]["id"])),
            201)
        assert booking["chargeable_weight_rt"] == pytest.approx(0.5)
        # base = max(round(0.5 x 9500) = 4750, 20000) = 20000 (floor binds);
        # BAF = 2000 (computed on the FLOORED base); THC = 600; DOC = 7500.
        assert booking["estimated_freight_cents"] == 30100


class TestRevenueTonPrecision:
    def test_revenue_ton_three_decimal_precision(self, api):
        """PRD §2.7: "Where the spec calls for rounding to 3 decimal places
        (the revenue-ton derivation), the rule is "round half up" applied to
        three decimal digits."
        PRD §3.6: "the terminal handling charge is the chargeable revenue tons
        multiplied by 1200 cents per revenue ton, rounded half-up."

        Design: Corner/calculations/revenue_ton_three_decimal_precision
        """
        ctx = setup_lcl_lane()
        booking = validate_success(
            api.create_booking(
                create_lcl_booking_payload(ctx["voyage"]["id"],
                                           ctx["tariff"]["id"],
                                           gross_weight_kg=333,
                                           volume_cbm=0.2),
                make_shipper_headers(ctx["shipper"]["id"])),
            201)
        assert booking["chargeable_weight_rt"] == pytest.approx(0.333, abs=1e-9)

        confirmed = validate_success(api.confirm_booking(booking["id"], BC), 200)
        assert confirmed["status"] == "CONFIRMED"
        invoice = create_draft_freight_invoice(booking["id"])
        # base = max(round(0.333 x 9500), 20000) = 20000 (floor);
        # BAF = 2000; THC = round_half_up(0.333 x 1200) = round_half_up(399.6)
        # = 400 (fractional-cent guard); DOC = 7500.
        assert invoice["total_cents"] == 29900
        amounts = {line["line_type"]: line["amount_cents"]
                   for line in invoice["lines"]}
        assert amounts["THC"] == 400
        assert amounts["OCEAN_FREIGHT"] == 20000
        assert amounts["BAF"] == 2000
        assert amounts["DOC_FEE"] == 7500


class TestFclFreightDecomposition:
    def test_fcl_freight_decomposition_two_containers(self, api):
        """PRD §3.6: "For `FCL`, the base is the unit rate multiplied by the
        `container_count`, and the terminal handling charge is
        `container_count` times a flat 25000 cents per container."
        PRD §3.6: "On either mode, the bunker adjustment factor is the base
        multiplied by ten percent, rounded half-up, and a documentation fee of
        7500 cents is added."
        PRD §3.12: "Its `lines` array is built per the ocean-freight-charge
        rule: an `OCEAN_FREIGHT` line for the base, a `BAF` line for the
        bunker adjustment, a `THC` line for terminal handling, a `DOC_FEE`
        line for the documentation fee, plus an `INSURANCE_PREMIUM` line when
        the booking has a `BOUND` policy (see §3.13), plus a `ROLLOVER_FEE`
        line consuming any `pending_rollover_fee_cents` accrued through
        shipper-requested rebooks."

        Design: Corner/calculations/fcl_freight_decomposition_two_containers
        """
        ctx = setup_fcl_lane()
        booking = validate_success(
            api.create_booking(
                create_fcl_booking_payload(ctx["voyage"]["id"],
                                           ctx["tariff"]["id"],
                                           container_count=2,
                                           gross_weight_kg=36000,
                                           volume_cbm=100.0,
                                           terms="PREPAID"),
                make_shipper_headers(ctx["shipper"]["id"])),
            201)
        # base = 2 x 185000 = 370000; BAF = 37000; THC = 2 x 25000 = 50000;
        # DOC = 7500 -> 464500.
        assert booking["estimated_freight_cents"] == 464500

        confirm_res = api.confirm_booking(booking["id"],
                                          BC)
        assert confirm_res.status_code == 200
        invoice = create_draft_freight_invoice(booking["id"])
        assert invoice["total_cents"] == 464500
        amounts = {line["line_type"]: line["amount_cents"]
                   for line in invoice["lines"]}
        assert amounts["OCEAN_FREIGHT"] == 370000
        assert amounts["BAF"] == 37000
        assert amounts["THC"] == 50000
        assert amounts["DOC_FEE"] == 7500
