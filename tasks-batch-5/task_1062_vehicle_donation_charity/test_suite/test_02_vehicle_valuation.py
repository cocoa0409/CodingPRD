"""The asset record and what the car is worth."""
from test_helpers import (
    ApiErrorId,
    assert_vehicle,
    create_vehicle_payload,
    new_charity,
    new_donation,
    new_donor,
    new_vehicle,
    read_donation,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestFairMarketEstimate:
    def test_fmv_applies_the_salvage_cap_and_the_floor_after_a_single_rounding(
        self, api, auction_manager_headers
    ):
        """PRD §3.3: "Multiply the base book value by both multipliers at full precision
        and round that single product half up to whole cents. If the asset carries
        `salvage_flag` as true, the rounded figure is then capped at seventy-five thousand
        cents — that is, the lesser of the rounded figure and seventy-five thousand is
        taken. Finally, whether or not the cap applied, the result is floored at ten
        thousand cents: an estimate below that floor is raised to it. The order is fixed —
        one rounding after the full product, then the salvage cap, then the floor."
        PRD §3.3: "The **condition multiplier** is one for an `EXCELLENT` grade,
        eighty-five hundredths for `GOOD`, sixty-five hundredths for `FAIR`, forty
        hundredths for `POOR`, and fifteen hundredths for `SALVAGE`."

        Design: Difficulty/combinatorial_formula/fmv_three_factor_product_with_salvage_cap_and_floor
        """
        charity = new_charity()
        donor = new_donor()
        salvage_donation = new_donation(
            donor["id"], charity["id"], declared_condition="EXCELLENT", pickup_required=False
        )
        floor_donation = new_donation(
            donor["id"], charity["id"], declared_condition="EXCELLENT", pickup_required=False
        )
        salvage_vehicle = new_vehicle(
            salvage_donation["id"],
            year=2018,
            make="Toyota",
            model="Camry",
            base_book_value_cents=900_000,
            salvage_flag=True,
        )
        floor_vehicle = new_vehicle(
            floor_donation["id"],
            year=2002,
            make="Ford",
            model="Taurus",
            base_book_value_cents=50_000,
        )

        capped = validate_success(
            api.inspect_vehicle(
                salvage_vehicle["id"],
                {"odometer_miles": 60_000, "condition_grade": "GOOD"},
                auction_manager_headers,
            ),
            200,
        )
        floored = validate_success(
            api.inspect_vehicle(
                floor_vehicle["id"],
                {"odometer_miles": 200_000, "condition_grade": "SALVAGE"},
                auction_manager_headers,
            ),
            200,
        )

        assert_vehicle(capped)
        assert capped["fmv_estimate_cents"] == 75_000, (
            "900000 x 0.85 x 1.00 = 765000 is capped at seventy-five thousand cents"
        )
        assert capped["fmv_variant"] == "POST_INSPECTION"
        assert capped["inspected"] is True
        assert floored["fmv_estimate_cents"] == 10_000, (
            "50000 x 0.15 x 0.70 = 5250 is raised to the ten-thousand-cent floor"
        )
        assert read_donation(salvage_donation["id"])["fmv_estimate_cents"] == 75_000
        assert read_donation(floor_donation["id"])["fmv_estimate_cents"] == 10_000

    def test_fmv_post_inspection_variant_replaces_the_base_condition_figure(
        self, api, auction_manager_headers
    ):
        """PRD §3.3: "At creation, the vehicle has not been inspected, and the
        `BASE_CONDITION` variant runs: the grade is taken from the donation's
        `declared_condition` and the mileage is treated as unknown, so the odometer
        multiplier is forced to one regardless of any reading supplied later."
        PRD §3.3: "The **odometer multiplier** is one when the mileage is unknown, and
        otherwise one for a reading of seventy-five thousand miles or fewer, eighty-five
        hundredths for a reading above seventy-five thousand but no more than one hundred
        and fifty thousand, and seventy hundredths for anything higher."

        Design: Difficulty/combinatorial_formula/fmv_three_factor_product_with_salvage_cap_and_floor
        """
        charity = new_charity()
        donor = new_donor()
        donation = new_donation(
            donor["id"], charity["id"], declared_condition="EXCELLENT", pickup_required=False
        )

        vehicle = new_vehicle(
            donation["id"],
            year=2018,
            make="Toyota",
            model="Camry",
            base_book_value_cents=900_000,
        )
        assert vehicle["fmv_estimate_cents"] == 900_000, (
            "declared EXCELLENT with an unknown odometer forces both multipliers to one"
        )
        assert vehicle["fmv_variant"] == "BASE_CONDITION"
        assert vehicle["inspected"] is False

        inspected = validate_success(
            api.inspect_vehicle(
                vehicle["id"],
                {"odometer_miles": 60_000, "condition_grade": "GOOD"},
                auction_manager_headers,
            ),
            200,
        )
        assert inspected["fmv_estimate_cents"] == 765_000, "900000 x 0.85 x 1.00"
        assert inspected["fmv_variant"] == "POST_INSPECTION"
        assert read_donation(donation["id"])["fmv_estimate_cents"] == 765_000

    def test_fmv_is_computed_at_creation_and_is_not_a_client_input(self, api, intake_agent_headers):
        """PRD §3.3: "Both creation and inspection produce a fair-market estimate, written
        to `fmv_estimate_cents` and mirrored onto the donation's own `fmv_estimate_cents`,
        with the donation's `version` advancing as a result."
        PRD §3.3: "At creation the record carries `inspected` as false, with
        `odometer_miles` and `condition_grade` both empty until somebody looks at the car."
        PRD §3.3: "The payload may also set `salvage_flag`, defaulting to false,
        indicating the car is titled or graded as scrap, and `keys_present`, defaulting to
        true, recording whether keys came with the car."

        Design: Corner/entities/corner_vehicle_fmv_estimate_is_computed_and_input_ignored
        """
        charity = new_charity()
        donor = new_donor()
        donation = new_donation(
            donor["id"], charity["id"], declared_condition="FAIR", pickup_required=False
        )

        vehicle = validate_success(
            api.create_vehicle(
                create_vehicle_payload(
                    donation["id"],
                    year=2019,
                    make="Subaru",
                    model="Outback",
                    base_book_value_cents=600_000,
                ),
                intake_agent_headers,
            ),
            201,
        )

        assert_vehicle(vehicle)
        assert vehicle["fmv_estimate_cents"] == 390_000, "600000 x 0.65 x 1.00"
        assert vehicle["fmv_variant"] == "BASE_CONDITION"
        assert vehicle["inspected"] is False
        assert vehicle["odometer_miles"] is None
        assert vehicle["condition_grade"] is None
        assert vehicle["salvage_flag"] is False
        assert vehicle["keys_present"] is True
        assert read_donation(donation["id"])["fmv_estimate_cents"] == 390_000

    def test_fmv_rounds_once_after_the_full_product(self, api, auction_manager_headers):
        """PRD §3.3: "Multiply the base book value by both multipliers at full precision
        and round that single product half up to whole cents."
        PRD §2.6: "First, when a chain of multiplicative factors is applied, the factors
        are multiplied at full precision and the product is rounded **once**, at the point
        the specification names — never factor by factor."

        Design: Corner/calculations/corner_fmv_uses_a_single_half_up_rounding_after_the_full_product
        """
        charity = new_charity()
        donor = new_donor()
        donation = new_donation(
            donor["id"], charity["id"], declared_condition="EXCELLENT", pickup_required=False
        )
        vehicle = new_vehicle(
            donation["id"],
            year=2010,
            make="Mazda",
            model="Protege",
            base_book_value_cents=123_457,
        )
        assert vehicle["fmv_estimate_cents"] == 123_457

        inspected = validate_success(
            api.inspect_vehicle(
                vehicle["id"],
                {"odometer_miles": 100_000, "condition_grade": "FAIR"},
                auction_manager_headers,
            ),
            200,
        )

        assert inspected["fmv_estimate_cents"] == 68_210, (
            "123457 x 0.65 x 0.85 = 68209.9925 rounds half up once to 68210"
        )
        assert inspected["fmv_variant"] == "POST_INSPECTION"
        assert read_donation(donation["id"])["fmv_estimate_cents"] == 68_210

    def test_donation_fmv_mirror_is_resynced_on_every_vehicle_write(
        self, api, auction_manager_headers
    ):
        """PRD §3.2: "A donation read exposes both state axes and every money field:
        `fmv_estimate_cents` (which mirrors the vehicle's fair-market estimate and is
        empty while no vehicle record exists), `gross_proceeds_cents`,
        `program_fee_cents`, `tow_allowance_cents`, `net_to_charity_cents` — all four of
        which start at 0 — and `deduction_amount_cents`, which is empty until a receipt is
        issued."
        PRD §3.3: "Both creation and inspection produce a fair-market estimate, written to
        `fmv_estimate_cents` and mirrored onto the donation's own `fmv_estimate_cents`,
        with the donation's `version` advancing as a result."

        Design: Corner/cross_cutting_layers/corner_donation_fmv_mirror_is_reconciled_on_every_vehicle_write
        """
        charity = new_charity()
        donor = new_donor()
        donation = new_donation(
            donor["id"], charity["id"], declared_condition="GOOD", pickup_required=False
        )
        assert donation["fmv_estimate_cents"] is None

        vehicle = new_vehicle(donation["id"], base_book_value_cents=480_000)
        assert vehicle["fmv_estimate_cents"] == 408_000, "480000 x 0.85 x 1.00"
        assert read_donation(donation["id"])["fmv_estimate_cents"] == 408_000

        inspected = validate_success(
            api.inspect_vehicle(
                vehicle["id"],
                {"odometer_miles": 200_000, "condition_grade": "POOR"},
                auction_manager_headers,
            ),
            200,
        )
        assert inspected["fmv_estimate_cents"] == 134_400, "480000 x 0.40 x 0.70"
        assert inspected["fmv_variant"] == "POST_INSPECTION"
        assert inspected["inspected"] is True
        assert read_donation(donation["id"])["fmv_estimate_cents"] == 134_400


class TestAssetUniqueness:
    def test_duplicate_vehicle_precedes_duplicate_vin(self, api, intake_agent_headers):
        """PRD §3.3: "A second attempt against the same donation is refused with
        `ERR_DUPLICATE_VEHICLE`, and a `vin` already on file is refused with
        `ERR_DUPLICATE_VIN` — in that order, so a caller re-posting the same vehicle to
        the same donation sees the duplicate-vehicle answer."

        Design: Corner/validations/corner_duplicate_vin_and_duplicate_vehicle_per_donation_are_refused
        """
        charity = new_charity()
        donor = new_donor()
        first_donation = new_donation(donor["id"], charity["id"], pickup_required=False)
        second_donation = new_donation(donor["id"], charity["id"], pickup_required=False)
        new_vehicle(first_donation["id"], vin="VINDUPLICATE00001", base_book_value_cents=480_000)

        same_donation = api.create_vehicle(
            create_vehicle_payload(
                first_donation["id"], vin="VINDIFFERENT00001", base_book_value_cents=480_000
            ),
            intake_agent_headers,
        )
        validate_error(same_donation, ApiErrorId.ERR_DUPLICATE_VEHICLE.value)

        same_vin = api.create_vehicle(
            create_vehicle_payload(
                second_donation["id"], vin="VINDUPLICATE00001", base_book_value_cents=480_000
            ),
            intake_agent_headers,
        )
        validate_error(same_vin, ApiErrorId.ERR_DUPLICATE_VIN.value)

        first_rows, _ = validate_paginated(
            api.list_vehicles(intake_agent_headers, params={"donation_id": first_donation["id"]})
        )
        assert len(first_rows) == 1
        second_rows, _ = validate_paginated(
            api.list_vehicles(intake_agent_headers, params={"donation_id": second_donation["id"]})
        )
        assert second_rows == []
