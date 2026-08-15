"""Catalog, grower/field administration, and agronomy (recommendations, plots)."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_grower_account,
    assert_placement_recommendation,
    assert_plot_trial,
    create_field_for,
    create_field_payload,
    create_grower,
    create_grower_payload,
    create_published_recommendation,
    create_plot_trial_payload,
    create_program_payload,
    create_recommendation_payload,
    create_variety,
    get_success_data,
    setup_confirmed_order,
    setup_market,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
SALESREP = TEST_USERS["salesrep_headers"]
AGRONOMIST = TEST_USERS["agronomist_headers"]


class TestGrowerAndFieldCreation:
    def test_grower_computed_balance_field_input_rejected(self, api):
        """PRD §2.8: "Required fields must be present, enum values must be
        members of their declared sets, integer quantities must be at least 1,
        acreage must be greater than zero, and unknown body fields are rejected
        — any violation yields `ERR_INVALID_REQUEST` (HTTP 400)."
        PRD §3.2: "New accounts begin `ACTIVE` with both ledger balances —
        `outstanding_balance_cents` and `prepay_balance_cents` — at zero."

        Design: Corner/entities/grower_computed_balance_field_input_rejected
        """
        bad = create_grower_payload()
        bad["outstanding_balance_cents"] = 999
        resp = api.create_grower(bad, SALESREP)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

        grower = validate_success(api.create_grower(create_grower_payload(), SALESREP),
                                  expected_status=201)
        assert_grower_account(grower)
        assert grower["status"] == "ACTIVE"
        assert grower["outstanding_balance_cents"] == 0
        assert grower["prepay_balance_cents"] == 0

    def test_field_create_invalid_enum_rejected(self, api):
        """PRD §2.8: "Required fields must be present, enum values must be
        members of their declared sets, integer quantities must be at least 1,
        acreage must be greater than zero, and unknown body fields are rejected
        — any violation yields `ERR_INVALID_REQUEST` (HTTP 400)."
        PRD §3.2: "the `soil_type` (`CLAY`, `LOAM`, `SAND`, or `SILT`)".

        Design: Corner/entities/field_create_invalid_enum_rejected
        """
        grower = create_grower()
        payload = create_field_payload(grower["id"], soil_type="GRAVEL")
        resp = api.create_field(payload, SALESREP)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestCatalogGuards:
    def test_delist_variety_blocked_until_open_orders_cancelled(self, api):
        """PRD §3.1: "delisting moves one `LISTED → DELISTED` but is blocked
        with `ERR_VARIETY_HAS_OPEN_ORDERS` while any order line references the
        variety inside an order that is `DRAFT`, `CONFIRMED`, or
        `COMPLIANCE_HOLD`."

        Design: Corner/validations/delist_variety_blocked_until_open_orders_cancelled
        """
        ctx = setup_confirmed_order(units=10)
        resp = api.delist_variety(ctx["variety"]["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_VARIETY_HAS_OPEN_ORDERS)

        get_success_data(api.cancel_order(ctx["order"]["id"], SALESREP))
        variety = validate_success(api.delist_variety(ctx["variety"]["id"], ADMIN))
        assert variety["status"] == "DELISTED"

    def test_variety_delisted_cannot_be_added_to_orders(self, api):
        """PRD §3.5: "the variety must be `LISTED` (`ERR_VARIETY_DELISTED`)".

        Design: Corner/validations/variety_delisted_cannot_be_added_to_orders
        """
        ctx = setup_market(with_lot=False)
        get_success_data(api.delist_variety(ctx["variety"]["id"], ADMIN))
        order = get_success_data(
            api.create_order(
                {"grower_id": ctx["grower"]["id"], "program_id": ctx["program"]["id"]},
                SALESREP,
            )
        )
        resp = api.add_order_line(
            order["id"], {"variety_id": ctx["variety"]["id"], "units": 10}, SALESREP
        )
        validate_error(resp, ApiErrorId.ERR_VARIETY_DELISTED)

    def test_treatment_crop_mismatch_on_line_rejected(self, api):
        """PRD §3.5: "the treatment — when present — must be `AVAILABLE` and
        must target the same `crop` as the variety (`ERR_TREATMENT_INCOMPATIBLE`)".

        Design: Corner/validations/treatment_crop_mismatch_on_line_rejected
        """
        ctx = setup_market(with_lot=False)
        corn_treatment = get_success_data(
            api.create_treatment_option(
                {"code": "FUNG-C", "crop": "CORN", "adder_cents_per_unit": 450}, ADMIN
            )
        )
        order = get_success_data(
            api.create_order(
                {"grower_id": ctx["grower"]["id"], "program_id": ctx["program"]["id"]},
                SALESREP,
            )
        )
        resp = api.add_order_line(
            order["id"],
            {
                "variety_id": ctx["variety"]["id"],
                "units": 10,
                "treatment_option_id": corn_treatment["id"],
            },
            SALESREP,
        )
        validate_error(resp, ApiErrorId.ERR_TREATMENT_INCOMPATIBLE)


class TestAgronomyScores:
    def test_recommendation_computed_score_input_rejected(self, api):
        """PRD §2.8: "Required fields must be present, enum values must be
        members of their declared sets, integer quantities must be at least 1,
        acreage must be greater than zero, and unknown body fields are rejected
        — any violation yields `ERR_INVALID_REQUEST` (HTTP 400)."
        PRD §3.4: "its `placement_score` is computed immediately."

        Design: Corner/entities/recommendation_computed_score_input_rejected
        """
        ctx = setup_market(with_lot=False, with_field=True)
        payload = create_recommendation_payload(
            ctx["field"]["id"], ctx["variety"]["id"], ctx["program"]["id"],
            ctx["field"]["version"],
        )
        payload["placement_score"] = 99
        resp = api.create_recommendation(payload, AGRONOMIST)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_placement_score_weighted_formula_exact_values(self, api):
        """PRD §3.4: "The score is one hundred times the weighted sum — soil
        weighted 0.35, drainage 0.25, maturity 0.25, rotation 0.15 — rounded
        half-up to one decimal place. It is computed at creation and recomputed
        when the recommendation is published."

        Design: Corner/calculations/placement_score_weighted_formula_exact_values
        """
        program = get_success_data(
            api.create_program(create_program_payload(), ADMIN)
        )
        grower = create_grower()
        package = get_success_data(
            api.create_trait_package(
                {
                    "code": "VT2P",
                    "description": "VT Double PRO",
                    "requires_stewardship_agreement": True,
                    "refuge_required_bps": 500,
                },
                ADMIN,
            )
        )
        variety = create_variety(
            sku="CORN-V1", crop="CORN", relative_maturity_days=112,
            trait_package_id=package["id"], base_price_cents_per_unit=25000,
            seeds_per_unit=80000, preferred_soils=["LOAM", "SILT"],
            min_drainage="MODERATE",
        )
        # Perfect fit: soil match, WELL(3) >= MODERATE(2), |112 - 110| = 2 <= 5,
        # rotation SOYBEAN != CORN -> 100 x (0.35 + 0.25 + 0.25 + 0.15) = 100.0
        field_fit = create_field_for(grower)
        # Partial soil only: SAND not preferred (0.5), POOR(1) < MODERATE(2),
        # |112 - 80| = 32 > 15, CORN == CORN -> 100 x 0.35 x 0.5 = 17.5
        field_poor = create_field_for(
            grower, name="Sand Pit", acres=40, soil_type="SAND", drainage="POOR",
            irrigated=False, prev_crop="CORN", maturity_zone=8,
        )

        rec_fit = validate_success(
            api.create_recommendation(
                create_recommendation_payload(
                    field_fit["id"], variety["id"], program["id"], field_fit["version"]
                ),
                AGRONOMIST,
            ),
            expected_status=201,
        )
        assert_placement_recommendation(rec_fit)
        assert rec_fit["placement_score"] == 100.0

        rec_poor = validate_success(
            api.create_recommendation(
                create_recommendation_payload(
                    field_poor["id"], variety["id"], program["id"], field_poor["version"],
                    seeding_rate_seeds_per_acre=32000, expected_yield_index=80,
                ),
                AGRONOMIST,
            ),
            expected_status=201,
        )
        assert rec_poor["placement_score"] == 17.5


class TestRecommendationSupersede:
    def test_publish_supersedes_prior_published_recommendation(self, api):
        """PRD §3.4: "if another recommendation for the same field-and-program
        pair is currently `PUBLISHED`, it moves to `SUPERSEDED` and the new
        recommendation's `supersedes_recommendation_id` records which one it
        displaced."

        Design: Corner/state_machines/publish_supersedes_prior_published_recommendation
        """
        ctx = setup_market(with_lot=False, with_field=True)
        rec1 = create_published_recommendation(ctx["program"], ctx["field"], ctx["variety"])

        field_now = get_success_data(api.get_field(ctx["field"]["id"], AGRONOMIST))
        rec2 = get_success_data(
            api.create_recommendation(
                create_recommendation_payload(
                    ctx["field"]["id"], ctx["variety"]["id"], ctx["program"]["id"],
                    field_now["version"], seeding_rate_seeds_per_acre=36000,
                    expected_yield_index=110,
                ),
                AGRONOMIST,
            )
        )
        rec2 = validate_success(api.publish_recommendation(rec2["id"], AGRONOMIST))
        assert rec2["status"] == "PUBLISHED"
        assert rec2["supersedes_recommendation_id"] == rec1["id"]

        rec1_after = validate_success(api.get_recommendation(rec1["id"], AGRONOMIST))
        assert rec1_after["status"] == "SUPERSEDED"


class TestPlotOccupancy:
    def _field_with_planted_plot(self, api):
        """Field North 40 with a PLANTED plot occupying the half-open interval
        [2027-04-15, 2027-10-01)."""
        ctx = setup_market(with_lot=False, with_field=True)
        plot = get_success_data(
            api.create_plot_trial(
                create_plot_trial_payload(
                    ctx["program"]["id"], ctx["variety"]["id"], ctx["field"]["id"],
                    planting_date="2027-04-15T00:00:00Z",
                    expected_harvest_date="2027-10-01T00:00:00Z",
                    replication_index=1,
                ),
                AGRONOMIST,
            )
        )
        get_success_data(api.record_planting(plot["id"], AGRONOMIST))
        return ctx, plot

    def test_plot_interior_overlap_rejected(self, api):
        """PRD §3.4: "Each trial occupies a half-open interval on its field —
        inclusive of `planting_date`, exclusive of `expected_harvest_date` — and
        planning is rejected with `ERR_PLOT_WINDOW_OVERLAP` if that interval
        overlaps the occupancy interval of another trial on the same field that
        is `PLANNED`, `PLANTED`, or `HARVESTED`."

        Design: Difficulty/resource_temporal_overlap/plot_field_occupancy_half_open_overlap_adjacency_allowed
        """
        ctx, _plot = self._field_with_planted_plot(api)
        resp = api.create_plot_trial(
            create_plot_trial_payload(
                ctx["program"]["id"], ctx["variety"]["id"], ctx["field"]["id"],
                planting_date="2027-05-01T00:00:00Z",
                expected_harvest_date="2027-09-01T00:00:00Z",
                replication_index=2,
            ),
            AGRONOMIST,
        )
        validate_error(resp, ApiErrorId.ERR_PLOT_WINDOW_OVERLAP)

    def test_plot_adjacent_interval_allowed(self, api):
        """PRD §3.4: "Each trial occupies a half-open interval on its field —
        inclusive of `planting_date`, exclusive of `expected_harvest_date` — and
        planning is rejected with `ERR_PLOT_WINDOW_OVERLAP` if that interval
        overlaps the occupancy interval of another trial on the same field that
        is `PLANNED`, `PLANTED`, or `HARVESTED`."

        Design: Difficulty/resource_temporal_overlap/plot_field_occupancy_half_open_overlap_adjacency_allowed
        """
        ctx, _plot = self._field_with_planted_plot(api)
        adjacent = validate_success(
            api.create_plot_trial(
                create_plot_trial_payload(
                    ctx["program"]["id"], ctx["variety"]["id"], ctx["field"]["id"],
                    planting_date="2027-10-01T00:00:00Z",
                    expected_harvest_date="2028-04-15T00:00:00Z",
                    replication_index=2,
                ),
                AGRONOMIST,
            ),
            expected_status=201,
        )
        assert adjacent["status"] == "PLANNED", (
            "half-open semantics: a start equal to the other's end is not an overlap"
        )


class TestFieldRetireAndPlots:
    def test_field_retire_blocked_by_planned_plot(self, api):
        """PRD §3.2: "retirement moves a field `ACTIVE → RETIRED` and is
        available to administrators and sales representatives, but is blocked
        with `ERR_FIELD_HAS_ACTIVE_PLOTS` while any plot trial on the field is
        `PLANNED` or `PLANTED`."

        Design: Corner/validations/field_retire_blocked_by_planned_plot
        """
        ctx = setup_market(with_lot=False, with_field=True)
        plot = get_success_data(
            api.create_plot_trial(
                create_plot_trial_payload(
                    ctx["program"]["id"], ctx["variety"]["id"], ctx["field"]["id"]
                ),
                AGRONOMIST,
            )
        )
        assert_plot_trial(plot)
        resp = api.retire_field(ctx["field"]["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_FIELD_HAS_ACTIVE_PLOTS)

        get_success_data(api.discard_plot_trial(plot["id"], AGRONOMIST))
        field = validate_success(api.retire_field(ctx["field"]["id"], ADMIN))
        assert field["status"] == "RETIRED"

    def test_plot_publish_blocked_until_min_replications_harvested(self, api):
        """PRD §3.4: "the count of trials for the same program-and-variety pair
        that are `HARVESTED` or `PUBLISHED`, this trial included, must be at
        least the program's `min_plot_replications`, otherwise
        `ERR_INSUFFICIENT_PLOT_REPLICATIONS`".

        Design: Corner/validations/plot_publish_blocked_until_min_replications_harvested
        """
        ctx = setup_market(with_lot=False, with_field=True)
        field2 = create_field_for(
            ctx["grower"], name="South 60", acres=60, soil_type="CLAY",
            drainage="MODERATE", irrigated=False, prev_crop="CORN", maturity_zone=12,
        )
        plot1 = get_success_data(
            api.create_plot_trial(
                create_plot_trial_payload(
                    ctx["program"]["id"], ctx["variety"]["id"], ctx["field"]["id"],
                    replication_index=1,
                ),
                AGRONOMIST,
            )
        )
        get_success_data(api.record_planting(plot1["id"], AGRONOMIST))
        get_success_data(api.record_harvest(plot1["id"], 64.2, 13.1, AGRONOMIST))

        resp = api.publish_plot_trial(plot1["id"], AGRONOMIST)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PLOT_REPLICATIONS)

        plot2 = get_success_data(
            api.create_plot_trial(
                create_plot_trial_payload(
                    ctx["program"]["id"], ctx["variety"]["id"], field2["id"],
                    planting_date="2027-04-20T00:00:00Z",
                    expected_harvest_date="2027-10-05T00:00:00Z", replication_index=2,
                ),
                AGRONOMIST,
            )
        )
        get_success_data(api.record_planting(plot2["id"], AGRONOMIST))
        get_success_data(api.record_harvest(plot2["id"], 61.8, 13.4, AGRONOMIST))

        published = validate_success(api.publish_plot_trial(plot1["id"], AGRONOMIST))
        assert published["status"] == "PUBLISHED"
