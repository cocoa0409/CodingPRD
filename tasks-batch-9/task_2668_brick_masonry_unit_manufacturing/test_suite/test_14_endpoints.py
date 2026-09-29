"""
The shape of the HTTP surface itself: the read/list/filter trio, action endpoints,
cross-referenced link creation, and reads whose payload is entirely derived.
"""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as F
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_CLAY_PIT_NOT_FOUND,
    ERR_COMPONENT_SHARE_TOTAL_INVALID,
    ERR_FORMULATION_NOT_FOUND,
    ERR_PIT_PLANT_MISMATCH,
    ERR_PLANT_IDLED,
)
from test_helpers.test_users import BODY_ENGINEER, PLANT_ADMIN, SALES_REP


class TestFormulationCrudSurface:
    """
    Section 1 gives formulations a create, a read and a filtered list and no
    mutating route of any other shape.
    """

    def test_read_and_the_three_list_filters_are_the_entire_surface(self, api, clock):
        """
        Three drafts, read one, then filter the list by plant, colour and status.

        Section 3.2 starts a formulation "with an empty components array,
        component_share_total_pct at 0, dequalified_count at 0 and qualified_at
        null", and section 2.4 sorts every list "by created_at ascending" with meta
        carrying "limit, offset, total_count and has_more". The only mutating routes
        are the two action endpoints, so a stored recipe is never edited in place.

        Design: Corner/endpoints/formulation_create_read_and_filtered_list_are_the_whole_crud_surface
        """
        plant = fx.create_plant(api)
        first = fx.create_draft_formulation(api, plant["id"])
        second = fx.create_draft_formulation(api, plant["id"], target_color_family="BROWN")
        third = fx.create_draft_formulation(api, plant["id"])

        read = validate_success(api.get_formulation(first["id"], BODY_ENGINEER))
        assert read["id"] == first["id"]
        assert read["formulation_code"] == first["formulation_code"]
        assert read["target_cdi"] == 20.00
        assert read["clay_tons_per_thousand_units"] == 3.20
        assert read["version"] == 1
        assert read["status"] == "DRAFT"
        assert read["component_share_total_pct"] == 0.00
        assert read["components"] == []
        assert read["dequalified_count"] == 0
        assert read["qualified_at"] is None

        by_plant, meta_plant = validate_paginated(
            api.list_formulations(BODY_ENGINEER, params={"plant_id": plant["id"]})
        )
        assert meta_plant["total_count"] == 3
        assert meta_plant["has_more"] is False
        assert by_plant[0]["id"] == first["id"]

        by_colour, meta_colour = validate_paginated(
            api.list_formulations(BODY_ENGINEER, params={"target_color_family": "RED"})
        )
        assert meta_colour["total_count"] == 2
        assert [row["id"] for row in by_colour] == [first["id"], third["id"]]
        assert second["id"] not in [row["id"] for row in by_colour]

        page_one, meta_one = validate_paginated(
            api.list_formulations(
                BODY_ENGINEER, params={"status": "DRAFT", "limit": 2, "offset": 0}
            )
        )
        assert len(page_one) == 2
        assert meta_one["total_count"] == 3
        assert meta_one["has_more"] is True
        assert page_one[0]["id"] == first["id"]

        page_two, meta_two = validate_paginated(
            api.list_formulations(
                BODY_ENGINEER, params={"status": "DRAFT", "limit": 2, "offset": 2}
            )
        )
        assert len(page_two) == 1
        assert meta_two["has_more"] is False
        assert page_two[0]["id"] == third["id"]


class TestActionEndpointSemantics:
    """
    Section 3.9 makes plant idling a one-way action rather than a state setter.
    """

    def test_idling_is_not_idempotent_and_seals_child_creation(self, api, clock):
        """
        The second idle and a later kiln registration both report ERR_PLANT_IDLED.

        Section 3.9 stamps `idled_at` "from the logical clock" on the ACTIVE to IDLED
        move, and section 5 maps ERR_PLANT_IDLED to HTTP 409. Section 2.2 increments
        `version` on a mutation only, so two refusals leave it where the single
        successful action put it.

        Design: Corner/endpoints/plant_idle_action_endpoint_is_terminal_and_seals_the_plant_for_writes
        """
        plant = fx.create_plant(api)
        assert plant["status"] == "ACTIVE"
        assert plant["idled_at"] is None
        assert plant["version"] == 1

        idled = validate_success(api.idle_plant(plant["id"], PLANT_ADMIN))
        assert idled["status"] == "IDLED"
        assert idled["idled_at"] == "2026-08-01T00:00:00Z"
        assert idled["version"] == 2

        validate_error(api.idle_plant(plant["id"], PLANT_ADMIN), ERR_PLANT_IDLED, 409)
        validate_error(
            api.create_kiln(plant["id"], F.kiln_payload(), PLANT_ADMIN),
            ERR_PLANT_IDLED,
            409,
        )

        after = validate_success(api.get_plant(plant["id"], PLANT_ADMIN))
        assert after["status"] == "IDLED"
        assert after["version"] == 2

        kilns, meta = validate_paginated(api.list_kilns(plant["id"], PLANT_ADMIN))
        assert meta["total_count"] == 0
        assert kilns == []


class TestCrossReferencedLinkCreation:
    """
    A component append names a parent in the path and a pit in the body, and both
    sides must resolve to the same plant.
    """

    def test_the_path_id_the_body_id_and_their_co_location_are_checked_in_that_order(
        self, api, clock
    ):
        """
        A dead path id, a dead pit id and a foreign pit each stop the append.

        Section 3.2: "The pit must belong to the same plant as the formulation; if it
        does not, the append is rejected with ERR_PIT_PLANT_MISMATCH", and section 5
        maps that to HTTP 422 while both missing ids are 404s. The same section makes
        `components` "an ordered array of objects, not a foreign-key column - a
        component object holds only its pit_id and its share_pct".

        Design: Corner/endpoints/formulation_component_link_needs_both_sides_present_and_co_located
        """
        home = fx.create_plant(api)
        other = fx.create_plant(api)
        pit_a = fx.create_clay_pit(api, home["id"])
        pit_z = fx.create_clay_pit(api, other["id"])
        body = fx.create_draft_formulation(api, home["id"])
        version = body["version"]

        validate_error(
            api.add_formulation_component(
                NON_EXISTENT_UUID,
                F.formulation_component_payload(pit_a["id"], 50.00, version),
                BODY_ENGINEER,
            ),
            ERR_FORMULATION_NOT_FOUND,
            404,
        )
        validate_error(
            api.add_formulation_component(
                body["id"],
                F.formulation_component_payload(NON_EXISTENT_UUID, 50.00, version),
                BODY_ENGINEER,
            ),
            ERR_CLAY_PIT_NOT_FOUND,
            404,
        )
        validate_error(
            api.add_formulation_component(
                body["id"],
                F.formulation_component_payload(pit_z["id"], 50.00, version),
                BODY_ENGINEER,
            ),
            ERR_PIT_PLANT_MISMATCH,
            422,
        )

        untouched = validate_success(api.get_formulation(body["id"], BODY_ENGINEER))
        assert untouched["component_share_total_pct"] == 0.00
        assert untouched["version"] == version
        assert untouched["components"] == []

        appended = validate_success(
            api.add_formulation_component(
                body["id"],
                F.formulation_component_payload(pit_a["id"], 50.00, version),
                BODY_ENGINEER,
            )
        )
        assert appended["component_share_total_pct"] == 50.00
        assert appended["version"] == version + 1

        reread = validate_success(api.get_formulation(body["id"], BODY_ENGINEER))
        assert len(reread["components"]) == 1
        assert reread["components"][0]["pit_id"] == pit_a["id"]
        assert reread["components"][0]["share_pct"] == 50.00
        assert reread["component_share_total_pct"] == 50.00


class TestComputedReadAfterAnAction:
    """
    Nothing on an order is derived at intake: the whole freight and promise block
    appears only once assignment has run, and a later read returns it unchanged.
    """

    def test_the_derived_block_is_absent_at_intake_and_complete_after_assignment(
        self, api, clock
    ):
        """
        A 12000-unit order 60 miles out reads back 27.00 tons, 71102 cents and 15 days.

        Section 3.5 creates an order with "every freight figure, lead_time_days,
        promised_ship_date ... all null", bills "requested_units multiplied by 4.5
        pounds, divided by 2000", the surcharge at "4.5 percent when the base is at
        least 50000 cents but under 150000", and promises "a base of 14 days" plus the
        run-out term. The FINAL variant is untouched until packaging.

        Design: Corner/endpoints/order_read_after_assignment_returns_the_full_derived_freight_and_lead_time_block
        """
        env = fx.build_plant_with_assets(api, clock=None)
        assert env["formulation"]["computed_durability_grade"] == "SW"
        order = fx.create_order(api, requested_units=12000)
        assert order["freight_status"] == "UNQUOTED"
        assert order["distance_miles"] is None
        assert order["estimated_freight_cents"] is None
        assert order["lead_time_days"] is None
        assert order["promised_ship_date"] is None

        assigned = validate_success(api.assign_plant(order["id"], SALES_REP))
        assert assigned["plant_id"] == env["plant"]["id"]

        read = validate_success(api.get_order(order["id"], SALES_REP))
        assert read["distance_miles"] == 60
        assert read["estimated_billable_tons"] == 27.00
        assert read["estimated_base_freight_cents"] == 68040
        assert read["estimated_fuel_surcharge_cents"] == 3062
        assert read["estimated_freight_cents"] == 71102
        assert read["lead_time_days"] == 15
        assert read["promised_ship_date"] == "2026-08-16T00:00:00Z"
        assert read["freight_status"] == "ESTIMATED"
        assert read["fulfillment_status"] == "ASSIGNED"
        assert read["final_freight_cents"] is None
        assert read["final_billable_tons"] is None
        assert read["freight_variance_cents"] is None


class TestConditionalActionEndpoint:
    """
    Section 3.2 gates qualification on an exact share total, and the same error id
    covers an overshooting append and a duplicated pit.
    """

    def test_qualify_demands_exactly_one_hundred_and_the_appends_that_get_there(
        self, api, clock
    ):
        """
        90.00 will not qualify; a 20.00 append overshoots; a repeat pit is refused; 10.00 lands it.

        Section 3.2: "the running component_share_total_pct after the append must not
        exceed 100.00, and the same clay pit must not appear twice in one formulation;
        either violation is rejected with ERR_COMPONENT_SHARE_TOTAL_INVALID", and the
        DRAFT to QUALIFIED move "requires that component_share_total_pct equal exactly
        100.00". Qualification "re-runs the chemistry" over the accepted shares only,
        and `shale_share_pct` is "the exact two-decimal sum of share_pct over only
        those components whose pit has material_type SHALE".

        Design: Corner/endpoints/qualify_is_allowed_only_when_the_component_shares_total_exactly_one_hundred
        """
        plant = fx.create_plant(api)
        pit_a = fx.create_clay_pit(api, plant["id"], iron_oxide_pct=7.500, lime_pct=1.200)
        pit_b = fx.create_shale_pit(api, plant["id"], iron_oxide_pct=5.000, lime_pct=0.800)
        pit_c = fx.create_clay_pit(api, plant["id"], iron_oxide_pct=2.500, lime_pct=1.200)

        body = fx.create_draft_formulation(api, plant["id"])
        body = fx.add_components(api, body, [(pit_a["id"], 50.00), (pit_b["id"], 40.00)])
        assert body["component_share_total_pct"] == 90.00
        version = body["version"]

        validate_error(
            api.qualify_formulation(body["id"], BODY_ENGINEER),
            ERR_COMPONENT_SHARE_TOTAL_INVALID,
            422,
        )
        validate_error(
            api.add_formulation_component(
                body["id"],
                F.formulation_component_payload(pit_c["id"], 20.00, version),
                BODY_ENGINEER,
            ),
            ERR_COMPONENT_SHARE_TOTAL_INVALID,
            422,
        )
        validate_error(
            api.add_formulation_component(
                body["id"],
                F.formulation_component_payload(pit_a["id"], 10.00, version),
                BODY_ENGINEER,
            ),
            ERR_COMPONENT_SHARE_TOTAL_INVALID,
            422,
        )

        completed = validate_success(
            api.add_formulation_component(
                body["id"],
                F.formulation_component_payload(pit_c["id"], 10.00, version),
                BODY_ENGINEER,
            )
        )
        assert completed["component_share_total_pct"] == 100.00
        assert completed["version"] == version + 1
        assert len(completed["components"]) == 3

        qualified = validate_success(api.qualify_formulation(body["id"], BODY_ENGINEER))
        assert qualified["status"] == "QUALIFIED"
        assert qualified["qualified_at"] == "2026-08-01T00:00:00Z"
        assert qualified["shale_share_pct"] == 40.00
        assert qualified["blend_iron_oxide_pct"] == 6.000
        assert qualified["blend_lime_pct"] == 1.040
