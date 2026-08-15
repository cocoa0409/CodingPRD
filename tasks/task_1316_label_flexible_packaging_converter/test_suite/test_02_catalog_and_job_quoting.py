"""Catalog registration (substrates, dies, presses) and provisional quoting."""
from test_helpers import (
    EST,
    PRESS_OP,
    api_client,
    assert_label_job,
    assert_substrate,
    create_customer,
    create_ink_recipe,
    create_job_for,
    create_press,
    create_shelf_die,
    create_substrate,
    register_artwork,
    retire_die,
    setup_plant,
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_error,
    validate_success,
)


class TestCatalogRegistration:

    def test_substrate_create_get_roundtrip(self):
        """PRD §3.1: "A substrate is registered with a unique `substrate_code`
        (for example, BOPP-30 or PET-12), the web `width_mm` available on the
        roll, a `cost_per_msq_cents` expressing material cost per thousand
        square inches, and a `food_contact_certified` flag (default false)
        attesting that the material carries a food-contact certification."

        Design: Corner/entities/substrate_create_get_roundtrip
        """
        created = validate_success(api_client.create_substrate(
            {"substrate_code": "RT-1", "width_mm": 850,
             "cost_per_msq_cents": 55, "food_contact_certified": True},
            EST), 201)
        assert_substrate(created)

        fetched = validate_success(
            api_client.get_substrate(created["id"], PRESS_OP), 200)
        assert fetched["id"] == created["id"]
        assert fetched["substrate_code"] == "RT-1"
        assert fetched["width_mm"] == 850
        assert fetched["cost_per_msq_cents"] == 55
        assert fetched["food_contact_certified"] is True

    def test_system_fields_generated_on_create(self):
        """PRD §2.4: "Every resource is identified by an `id`, a server-minted
        UUID with no type prefix. Alongside it, resources carry `created_at`
        and `updated_at` — ISO 8601 UTC timestamps with three fractional digits
        (for example, `2025-05-24T10:30:00.123Z`) — and an integer `version`
        that increments by one on every mutation of the resource, whether the
        mutation is client-invoked or server-driven."

        Design: Corner/entities/system_fields_generated_on_create
        """
        substrate = validate_success(api_client.create_substrate(
            {"substrate_code": "SYS-1", "width_mm": 700,
             "cost_per_msq_cents": 60},
            EST), 201)
        assert is_valid_uuid(substrate["id"])
        assert is_iso8601_timestamp(substrate["created_at"])
        assert is_iso8601_timestamp(substrate["updated_at"])
        assert substrate["version"] == 1


class TestJobCreation:

    def test_job_initial_state_is_quoted(self):
        """PRD §3.4: "A job walks the chain `QUOTED` → `APPROVED` → `RELEASED`
        → `ON_PRESS` → `PRINTED` → `REWOUND` → `SHIPPED`, with `CANCELLED`
        reachable from the first three states. At creation the job is `QUOTED`;
        `material_ft`, `good_quantity_produced` and `invoiced_price_cents`
        remain unset, `die_charge_applied_cents` starts at 0, and the system
        computes a provisional `quoted_price_cents` from four components."
        PRD §3.4: "The provisional `quoted_price_cents` is the sum of base,
        material, ink and plates; the new-die tooling charge is deliberately
        absent from the quote, because only at release does the system know
        whether this job is the die's first use."

        Design: Corner/state_machines/job_initial_state_is_quoted
        """
        plant = setup_plant(account_name="Init Co", artwork_code="AW-I",
                            approve_artwork=False, substrate_code="I-1",
                            recipe_code="INK-I", die_code="D-I",
                            press_code="P-I")
        job = create_job_for(plant, quantity_ordered=1000, repeat_length_mm=76)
        assert_label_job(job)
        assert job["status"] == "QUOTED"
        assert job["version"] == 1
        # base ceil(1*4500)=4500 + material ceil(265.9843*40)=10640
        # + ink ceil(0.2252*300)=68 + plates 120000
        assert job["quoted_price_cents"] == 135208
        assert job["material_ft"] is None
        assert job["good_quantity_produced"] is None
        assert job["invoiced_price_cents"] is None
        assert job["die_charge_applied_cents"] == 0

    def test_job_create_unknown_payload_field_rejected(self):
        """PRD §2.5: "For requests with a body, every required field must be
        present, no unknown fields may appear, and all types and enum members
        must be valid, else `ERR_INVALID_REQUEST`."
        PRD §3.4: "At creation the job is `QUOTED`; `material_ft`,
        `good_quantity_produced` and `invoiced_price_cents` remain unset,
        `die_charge_applied_cents` starts at 0, and the system computes a
        provisional `quoted_price_cents` from four components."

        Design: Corner/entities/job_create_unknown_payload_field_rejected
        """
        plant = setup_plant(account_name="Strict Co", artwork_code="AW-S",
                            approve_artwork=False, substrate_code="ST-1",
                            recipe_code="INK-S", die_code="D-S1",
                            press_code="P-S1")
        payload = {
            "artwork_version_id": plant["artwork"]["id"],
            "substrate_id": plant["substrate"]["id"],
            "ink_recipe_id": plant["ink"]["id"],
            "die_id": plant["die"]["id"],
            "press_id": plant["press"]["id"],
            "quantity_ordered": 2000,
            "repeat_length_mm": 76,
            "rewind_max_rolls": 2,
            "max_splices_per_roll": 1,
            "quoted_price_cents": 1,  # computed server-side: unknown as input
        }
        resp = api_client.create_job(plant["customer"]["id"], payload, EST)
        validate_error(resp, "ERR_INVALID_REQUEST", expected_status=400)

    def test_retired_die_rejected_at_job_create(self):
        """PRD §3.4: "Two guards apply at creation: the referenced die must not
        be `RETIRED` (`ERR_DIE_RETIRED`), and the artwork's `color_count` must
        not exceed the press's `station_count`
        (`ERR_COLOR_COUNT_EXCEEDS_PRESS`)."
        PRD §3.2: "When a die reaches the end of its useful life, an
        `Estimator` retires it, moving it from `ACTIVE` to `RETIRED` and
        incrementing its `version`; retired dies remain visible in inventory
        but cannot be referenced by newly created jobs, which are rejected with
        `ERR_DIE_RETIRED`."

        Design: Corner/validations/retired_die_rejected_at_job_create
        """
        plant = setup_plant(account_name="Retire Co", artwork_code="AW-RT",
                            approve_artwork=False, substrate_code="RT-2",
                            recipe_code="INK-RT", die_code="D-RT",
                            press_code="P-RT")
        retired = retire_die(plant["die"]["id"])
        assert retired["status"] == "RETIRED"

        resp = api_client.create_job(
            plant["customer"]["id"],
            {"artwork_version_id": plant["artwork"]["id"],
             "substrate_id": plant["substrate"]["id"],
             "ink_recipe_id": plant["ink"]["id"],
             "die_id": plant["die"]["id"],
             "press_id": plant["press"]["id"],
             "quantity_ordered": 2000, "repeat_length_mm": 76,
             "rewind_max_rolls": 2, "max_splices_per_roll": 1},
            EST)
        validate_error(resp, "ERR_DIE_RETIRED", expected_status=422)

        fetched = validate_success(api_client.get_die(plant["die"]["id"], EST))
        assert fetched["status"] == "RETIRED", \
            "retired die remains readable in inventory"

    def test_color_count_exceeds_press_rejected(self):
        """PRD §3.4: "Two guards apply at creation: the referenced die must not
        be `RETIRED` (`ERR_DIE_RETIRED`), and the artwork's `color_count` must
        not exceed the press's `station_count`
        (`ERR_COLOR_COUNT_EXCEEDS_PRESS`)."
        PRD §3.1: "Registering a press records a unique `press_code`, the
        `station_count` — the number of print stations, which caps how many
        colors the press can run — the `setup_waste_ft`, being the base feet of
        material consumed in makeready before the first sellable impression,
        and the `run_waste_pct_numerator`, the running-waste percentage
        expressed as a numerator: a value of 5 means five percent of the
        running footage is wasted."

        Design: Corner/validations/color_count_exceeds_press_rejected
        """
        plant = setup_plant(account_name="Stations Co", artwork_code="AW-6C",
                            approve_artwork=False, color_count=6,
                            plate_set_cost_cents=300000,
                            substrate_code="SC-1", recipe_code="INK-SC",
                            die_code="D-SC", press_code="P-SC",
                            station_count=4)
        resp = api_client.create_job(
            plant["customer"]["id"],
            {"artwork_version_id": plant["artwork"]["id"],
             "substrate_id": plant["substrate"]["id"],
             "ink_recipe_id": plant["ink"]["id"],
             "die_id": plant["die"]["id"],
             "press_id": plant["press"]["id"],
             "quantity_ordered": 2000, "repeat_length_mm": 76,
             "rewind_max_rolls": 2, "max_splices_per_roll": 1},
            EST)
        validate_error(resp, "ERR_COLOR_COUNT_EXCEEDS_PRESS",
                       expected_status=409)


class TestProvisionalQuoteTiers:
    """The average-rate tier table keyed on the full ordered quantity."""

    def test_tier_boundary_5000_rate_switch(self):
        """PRD §3.4: "Quantities below 5,000 labels price at 4,500 cents per
        thousand; quantities of at least 5,000 but below 20,000 price at 3,800
        cents per thousand; quantities of 20,000 or more price at 3,200 cents
        per thousand. The base charge is the ordered quantity divided by one
        thousand and multiplied by the applicable per-thousand rate, rounded up
        to whole cents."

        Design: Corner/calculations/tier_boundary_5000_rate_switch
        """
        plant = setup_plant(account_name="Tier5 Co", artwork_code="AW-T5",
                            approve_artwork=False, substrate_code="T5-1",
                            recipe_code="INK-T5", die_code="D-T5",
                            press_code="P-T5")
        j4999 = create_job_for(plant, quantity_ordered=4999,
                               repeat_length_mm=76, rewind_max_rolls=3)
        j5000 = create_job_for(plant, quantity_ordered=5000,
                               repeat_length_mm=76, rewind_max_rolls=3)
        # 4999 -> rate_a: ceil(4.999*4500)=22496 + 30426 + 194 + 120000
        assert j4999["quoted_price_cents"] == 173116
        # 5000 -> rate_b (boundary inclusive): ceil(5*3800)=19000 + same rest
        assert j5000["quoted_price_cents"] == 169620

    def test_tier_boundary_20000_rate_switch(self):
        """PRD §3.4: "Quantities below 5,000 labels price at 4,500 cents per
        thousand; quantities of at least 5,000 but below 20,000 price at 3,800
        cents per thousand; quantities of 20,000 or more price at 3,200 cents
        per thousand. The base charge is the ordered quantity divided by one
        thousand and multiplied by the applicable per-thousand rate, rounded up
        to whole cents."

        Design: Corner/calculations/tier_boundary_20000_rate_switch
        """
        plant = setup_plant(account_name="Tier20 Co", artwork_code="AW-T20",
                            approve_artwork=False, substrate_code="T20-1",
                            recipe_code="INK-T20", die_code="D-T20",
                            press_code="P-T20", station_count=6)
        j19999 = create_job_for(plant, quantity_ordered=19999,
                                repeat_length_mm=76, rewind_max_rolls=5)
        j20000 = create_job_for(plant, quantity_ordered=20000,
                                repeat_length_mm=76, rewind_max_rolls=5)
        # 19999 -> rate_b: ceil(19.999*3800)=75997 + 104637 + 665 + 120000
        assert j19999["quoted_price_cents"] == 301299
        # 20000 -> rate_c (boundary inclusive): 64000 + 104637 + 665 + 120000
        assert j20000["quoted_price_cents"] == 289302

    def test_ink_cost_scales_with_artwork_color_count(self):
        """PRD §3.4: "The ink component allows one pound of ink per 5,000
        linear feet per print station: the provisional total footage multiplied
        by the artwork's `color_count` and divided by 5,000 yields pounds of
        ink, which multiplied by the recipe's `cost_per_lb_cents` and rounded
        up to whole cents is the ink charge. Finally, one plate set per job
        adds the artwork revision's `plate_set_cost_cents`."

        Design: Corner/calculations/ink_cost_scales_with_artwork_color_count
        """
        customer = create_customer(account_name="ColorScale Co")
        av2 = register_artwork(customer["id"], approve=False,
                               artwork_code="AW-2C", revision_no=1,
                               color_count=2, plate_set_cost_cents=120000)
        av4 = register_artwork(customer["id"], approve=False,
                               artwork_code="AW-4C", revision_no=1,
                               color_count=4, plate_set_cost_cents=120000)
        plant = {
            "customer": customer,
            "artwork": av2,
            "substrate": create_substrate(substrate_code="CS-1"),
            "ink": create_ink_recipe(recipe_code="INK-CS"),
            "die": create_shelf_die(die_code="D-CS"),
            "press": create_press(press_code="P-CS", station_count=6),
            "cfg": {},
        }
        j2 = create_job_for(plant, quantity_ordered=1000, repeat_length_mm=76)
        plant["artwork"] = av4
        j4 = create_job_for(plant, quantity_ordered=1000, repeat_length_mm=76)
        assert j2["quoted_price_cents"] == 135208
        # identical job at 4 colors: ink ceil(563*4/5000*300)=136 -> +68 cents
        assert j4["quoted_price_cents"] == 135276


class TestQuoteRoundingOrder:

    def test_quote_ceils_each_component_before_summing(self):
        """PRD §2.7: "All monetary amounts in this API are integer cents; there
        are no fractional cents anywhere, in requests or in responses. Every
        computed charge component is rounded up to the next whole cent
        (ceiling) before the components are summed, and the same ceiling
        discipline applies to material footage and waste figures, which are
        expressed in whole feet."
        PRD §3.4: "The provisional `quoted_price_cents` is the sum of base,
        material, ink and plates; the new-die tooling charge is deliberately
        absent from the quote, because only at release does the system know
        whether this job is the die's first use."

        Design: Difficulty/combinatorial_formula/quote_nested_ceil_component_rounding_order
        """
        plant = setup_plant(account_name="Rounding Inc", artwork_code="AW-4",
                            approve_artwork=False, substrate_code="BOPP-31",
                            recipe_code="INK-4", die_code="D-4",
                            press_code="P-4")
        job = create_job_for(plant, quantity_ordered=4000, repeat_length_mm=76,
                             rewind_max_rolls=2, max_splices_per_roll=1)
        # base 18000 + material ceil(636.8504*40)=25475
        # + ink ceil(0.5392*300)=162 + plates 120000
        assert job["quoted_price_cents"] == 163637, (
            "per-component ceiling pins 163637; summing raw components then "
            "ceiling once would under-count at 163636")

    def test_quote_ceiling_discriminates_second_dataset(self):
        """PRD §2.7: "All monetary amounts in this API are integer cents; there
        are no fractional cents anywhere, in requests or in responses. Every
        computed charge component is rounded up to the next whole cent
        (ceiling) before the components are summed, and the same ceiling
        discipline applies to material footage and waste figures, which are
        expressed in whole feet."
        PRD §3.4: "The provisional `quoted_price_cents` is the sum of base,
        material, ink and plates; the new-die tooling charge is deliberately
        absent from the quote, because only at release does the system know
        whether this job is the die's first use."

        Design: Difficulty/combinatorial_formula/quote_nested_ceil_component_rounding_order
        """
        plant = setup_plant(account_name="Rounding Two", artwork_code="AW-4B",
                            approve_artwork=False, substrate_code="BOPP-31B",
                            recipe_code="INK-4B", die_code="D-4B",
                            press_code="P-4B")
        job = create_job_for(plant, quantity_ordered=1000, repeat_length_mm=76,
                             rewind_max_rolls=2, max_splices_per_roll=1)
        # base 4500 + material ceil(265.9843*40)=10640
        # + ink ceil(0.2252*300)=68 + plates 120000
        assert job["quoted_price_cents"] == 135208, (
            "per-component ceiling pins 135208; summing raw components then "
            "ceiling once would under-count at 135207")
