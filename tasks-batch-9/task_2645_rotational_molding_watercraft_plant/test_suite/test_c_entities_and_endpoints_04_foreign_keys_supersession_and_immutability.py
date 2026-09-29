"""Body foreign keys, the self-referential mould chain, and per-field immutability.

PRD.md section 2.7 puts existence in band 2 — before schema, before state,
before capacity and before the concurrency guards of section 2.6 — so a request
naming a row that was never minted is a 404 no matter what else is wrong with
it. The same file covers the one FK that points back at the collection it lives
in, and the fields no endpoint accepts as input at all.
"""

from test_helpers import (
    ApiErrorId,
    CLOCK_DEFAULT_UTC,
    assert_instant_equals,
    assert_warranty_reserve_conserved,
    create_customer,
    create_plant_baseline,
    create_production_order,
    create_resin_lot,
    dec,
    demand_forecast_bucket_payload,
    get_success_data,
    mold_payload,
    molding_cycle_payload,
    product_model_payload,
    production_order_payload,
    resin_charge_payload,
    retire_mold_payload,
    service_hold_payload,
    set_clock,
    shipment_line_payload,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    validate_success,
    warehouse_payload,
    warranty_claim_payload,
)

UNKNOWN_ID = "00000000-0000-0000-0000-0000000000ff"


class TestProductModelParentReference:
    """An unresolvable `product_model_id` has its own not-found identifier."""

    @staticmethod
    def _model_and_site(api, admin_headers):
        set_clock(CLOCK_DEFAULT_UTC, admin_headers)
        model = get_success_data(
            api.create_product_model(
                product_model_payload(
                    model_code="PM-CD-PAR", nominal_charge_kg=24.0
                ),
                admin_headers,
            )
        )
        site = get_success_data(
            api.create_warehouse(
                warehouse_payload(site_code="WHS-CD-PAR"), admin_headers
            )
        )
        return model, site

    def test_unresolvable_model_on_a_tool_registration(self, api, admin_headers):
        """POST /molds reports the model-specific not-found code.

        PRD.md section 2.8, Mold: "`product_model_id` (required, must resolve or
        `ERR_PRODUCT_MODEL_NOT_FOUND` — a tool produces exactly one hull
        model)".

        PRD.md section 2.7: "**Existence** — path identifiers first, then body
        foreign keys, each reported with its entity-specific not-found code
        where one exists and with `ERR_RESOURCE_NOT_FOUND` otherwise."

        Design: Corner/entities/ent_parent_product_model_fk_raises_a_dedicated_error_ahead_of_generic_fks
        """
        self._model_and_site(api, admin_headers)

        refused = api.create_mold(
            mold_payload(
                UNKNOWN_ID,
                mold_code="MLD-CD-PAR-X",
                cavity_count=1,
                nominal_charge_kg=24.0,
            ),
            admin_headers,
        )

        validate_error(refused, ApiErrorId.PRODUCT_MODEL_NOT_FOUND, 404)

    def test_unresolvable_model_on_a_demand_bucket(
        self, api, admin_headers, planner_headers
    ):
        """POST /demand-forecast-buckets reports the same dedicated code.

        PRD.md section 2.8, DemandForecastBucket: "`product_model_id` (required,
        must resolve or `ERR_PRODUCT_MODEL_NOT_FOUND`)".

        Design: Corner/entities/ent_parent_product_model_fk_raises_a_dedicated_error_ahead_of_generic_fks
        """
        self._model_and_site(api, admin_headers)

        refused = api.create_demand_forecast_bucket(
            demand_forecast_bucket_payload(
                UNKNOWN_ID,
                season_code="SSN-CD-PAR-X",
                forecast_qty=20,
                window_start_on="2026-09-01",
                window_end_on="2026-10-31",
            ),
            planner_headers,
        )

        validate_error(refused, ApiErrorId.PRODUCT_MODEL_NOT_FOUND, 404)

    def test_each_order_foreign_key_reports_its_own_not_found_code(
        self, api, admin_headers
    ):
        """The order's three foreign keys each carry a dedicated identifier.

        PRD.md section 2.8, ProductionOrder: "`product_model_id` (required, must
        resolve or `ERR_PRODUCT_MODEL_NOT_FOUND`); the optional
        `demand_bucket_id` (default null; when present it must resolve or
        `ERR_DEMAND_BUCKET_NOT_FOUND`, and its own `product_model_id` must equal
        the order's or `ERR_VALIDATION`); `target_warehouse_id` (required, must
        resolve or `ERR_WAREHOUSE_NOT_FOUND`)".

        Design: Corner/entities/ent_parent_product_model_fk_raises_a_dedicated_error_ahead_of_generic_fks
        """
        model, site = self._model_and_site(api, admin_headers)

        bad_model = api.create_production_order(
            production_order_payload(
                UNKNOWN_ID, site["id"], order_code="POR-CD-PAR-X1", ordered_qty=1
            ),
            admin_headers,
        )
        validate_error(bad_model, ApiErrorId.PRODUCT_MODEL_NOT_FOUND, 404)

        bad_site = api.create_production_order(
            production_order_payload(
                model["id"], UNKNOWN_ID, order_code="POR-CD-PAR-X2", ordered_qty=1
            ),
            admin_headers,
        )
        validate_error(bad_site, ApiErrorId.WAREHOUSE_NOT_FOUND, 404)

        bad_bucket = api.create_production_order(
            production_order_payload(
                model["id"],
                site["id"],
                order_code="POR-CD-PAR-X4",
                ordered_qty=1,
                demand_bucket_id=UNKNOWN_ID,
            ),
            admin_headers,
        )
        validate_error(bad_bucket, ApiErrorId.DEMAND_BUCKET_NOT_FOUND, 404)

        # Two unresolvable body foreign keys on one request: PRD.md section 2.7
        # groups body foreign keys into a single band without ordering them
        # against each other, so either identifier is a faithful answer.
        both_bad = api.create_production_order(
            production_order_payload(
                UNKNOWN_ID, UNKNOWN_ID, order_code="POR-CD-PAR-X3", ordered_qty=1
            ),
            admin_headers,
        )
        assert both_bad.status_code == 404
        validate_error_is_one_of(
            both_bad,
            [ApiErrorId.PRODUCT_MODEL_NOT_FOUND, ApiErrorId.WAREHOUSE_NOT_FOUND],
        )

        accepted = validate_success(
            api.create_production_order(
                production_order_payload(
                    model["id"],
                    site["id"],
                    order_code="POR-CD-PAR-OK",
                    ordered_qty=1,
                ),
                admin_headers,
            ),
            expected_status=201,
        )
        assert accepted["product_model_id"] == model["id"]
        assert accepted["target_warehouse_id"] == site["id"]
        assert accepted.get("demand_bucket_id") is None
        assert accepted["status"] == "DRAFT"

        rows, meta = validate_paginated(
            api.list_production_orders(
                {"product_model_id": model["id"]}, admin_headers
            )
        )
        assert meta["total_count"] == 1
        assert rows[0]["order_code"] == "POR-CD-PAR-OK"


class TestBodyForeignKeysOutrankStateAndConcurrency:
    """Existence is band 2; state is band 4 and the stale-version guards band 8."""

    @staticmethod
    def _draft_plant(api):
        ctx = create_plant_baseline()
        ctx["resin_lot"] = create_resin_lot()
        ctx["customer"] = create_customer()
        # Left in DRAFT on purpose: a request that got past the existence gate
        # would fail on the order's state instead, so the two answers differ.
        ctx["production_order"] = create_production_order(ctx, release=False)
        return ctx

    def test_unresolvable_station_beats_the_orders_unschedulable_state(self, api):
        """A bogus `oven_station_id` answers 404, not the order-state 409.

        PRD.md section 2.7: "Each endpoint evaluates its applicable checks in a
        fixed ascending priority order and returns on the first failure it
        finds; no endpoint reports two errors, and no later check runs after an
        earlier one has failed."

        PRD.md section 2.8, MoldingCycle: "`oven_station_id` (required, must
        resolve or `ERR_OVEN_STATION_NOT_FOUND`)".

        Design: Corner/entities/ent_flat_fk_body_references_validated_before_state_occ_and_business_rules
        """
        ctx = self._draft_plant(api)
        order = ctx["production_order"]

        refused = api.create_molding_cycle(
            molding_cycle_payload(
                order["id"],
                UNKNOWN_ID,
                ctx["cooling_bay_id"],
                order["version"],
                operator_technician_id=ctx["molding_operator_id"],
            ),
            ctx["operator_headers"],
        )

        validate_error(refused, ApiErrorId.OVEN_STATION_NOT_FOUND, 404)
        _rows, meta = validate_paginated(
            api.list_molding_cycles({"production_order_id": order["id"]}, ctx["admin_headers"])
        )
        assert meta["total_count"] == 0

    def test_unresolvable_bay_beats_the_stale_order_version_guard(self, api):
        """A bogus `cooling_bay_id` answers 404 even with a hopeless version.

        The declared version below is deliberately wrong; PRD.md section 2.6
        says so explicitly: "These guards are evaluated late — after
        authorization, after existence, after schema, after every state and
        capacity rule the endpoint declares — so a request that is both stale
        and otherwise invalid reports the other failure, not the stale-version
        failure."

        PRD.md section 2.8, MoldingCycle: "`cooling_bay_id` (required, must
        resolve or `ERR_COOLING_BAY_NOT_FOUND`)".

        Design: Corner/entities/ent_flat_fk_body_references_validated_before_state_occ_and_business_rules
        """
        ctx = self._draft_plant(api)
        order = ctx["production_order"]

        refused = api.create_molding_cycle(
            molding_cycle_payload(
                order["id"],
                ctx["oven_station_id"],
                UNKNOWN_ID,
                99,
                operator_technician_id=ctx["molding_operator_id"],
            ),
            ctx["operator_headers"],
        )

        validate_error(refused, ApiErrorId.COOLING_BAY_NOT_FOUND, 404)
        after = validate_success(
            api.get_production_order(order["id"], ctx["admin_headers"])
        )
        assert after["version"] == order["version"]
        assert after["status"] == "DRAFT"

    def test_unresolvable_order_on_a_cycle_creation(self, api):
        """A bogus `production_order_id` answers with the order's own code.

        PRD.md section 2.8, MoldingCycle: "`production_order_id` (required, must
        resolve or `ERR_PRODUCTION_ORDER_NOT_FOUND`)".

        Design: Corner/entities/ent_flat_fk_body_references_validated_before_state_occ_and_business_rules
        """
        ctx = self._draft_plant(api)

        refused = api.create_molding_cycle(
            molding_cycle_payload(
                UNKNOWN_ID,
                ctx["oven_station_id"],
                ctx["cooling_bay_id"],
                1,
                operator_technician_id=ctx["molding_operator_id"],
            ),
            ctx["operator_headers"],
        )

        validate_error(refused, ApiErrorId.PRODUCTION_ORDER_NOT_FOUND, 404)

    def test_unresolvable_cycle_on_a_charge_leaves_the_lot_ledger_alone(self, api):
        """A bogus `molding_cycle_id` answers 404 and moves no resin.

        PRD.md section 2.8, ResinCharge: "`molding_cycle_id` (required, must
        resolve or `ERR_MOLDING_CYCLE_NOT_FOUND`)".

        PRD.md section 2.10: "Cascades are transactional and complete inside the
        triggering request. When any link of a cascade cannot be applied, or
        when any validation the triggering request declares fails, nothing at
        all is persisted: no child row, no ledger movement, no status change, no
        version increment."

        Design: Corner/entities/ent_flat_fk_body_references_validated_before_state_occ_and_business_rules
        """
        ctx = self._draft_plant(api)
        lot = ctx["resin_lot"]

        refused = api.create_resin_charge(
            resin_charge_payload(
                UNKNOWN_ID,
                lot["id"],
                1,
                created_by_technician_id=ctx["resin_technician_id"],
            ),
            ctx["resin_tech_headers"],
        )

        validate_error(refused, ApiErrorId.MOLDING_CYCLE_NOT_FOUND, 404)
        after = validate_success(api.get_resin_lot(lot["id"], ctx["admin_headers"]))
        assert dec(after["available_kg"]) == dec(lot["received_kg"])
        assert dec(after["reserved_kg"]) == dec("0.000")
        assert after["version"] == lot["version"]

    def test_unresolvable_trailer_and_hull_on_a_line_creation(
        self, api, planner_headers
    ):
        """Both of the line's foreign keys are checked before its OCC guard.

        PRD.md section 2.8, ShipmentLine: "`shipment_id` (required, must resolve
        or `ERR_SHIPMENT_NOT_FOUND`) and `finished_unit_id` (required, must
        resolve or `ERR_FINISHED_UNIT_NOT_FOUND`, with at most one loaded line
        per hull — a second one is `ERR_UNIT_INVALID_LOGISTICS_STATE`)."

        Design: Corner/entities/ent_flat_fk_body_references_validated_before_state_occ_and_business_rules
        """
        self._draft_plant(api)

        refused = api.create_shipment_line(
            shipment_line_payload(UNKNOWN_ID, UNKNOWN_ID, 1), planner_headers
        )

        assert refused.status_code == 404
        validate_error_is_one_of(
            refused,
            [ApiErrorId.SHIPMENT_NOT_FOUND, ApiErrorId.FINISHED_UNIT_NOT_FOUND],
        )

    def test_unresolvable_hull_on_a_claim_beats_its_delivery_state_rule(
        self, api, warranty_agent_headers
    ):
        """A row that does not exist cannot be judged on its delivery state.

        PRD.md section 2.8, WarrantyClaim: "`finished_unit_id` (required, must
        resolve or `ERR_FINISHED_UNIT_NOT_FOUND`)".

        PRD.md section 2.7: "**Existence** — path identifiers first, then body
        foreign keys, each reported with its entity-specific not-found code
        where one exists and with `ERR_RESOURCE_NOT_FOUND` otherwise."

        Design: Corner/entities/ent_flat_fk_body_references_validated_before_state_occ_and_business_rules
        """
        ctx = self._draft_plant(api)

        refused = api.create_warranty_claim(
            warranty_claim_payload(
                UNKNOWN_ID,
                ctx["customer"]["customer_id"],
                claim_code="WCL-CD-FK-X",
                claim_type="HARDWARE",
            ),
            warranty_agent_headers,
        )

        validate_error(refused, ApiErrorId.FINISHED_UNIT_NOT_FOUND, 404)

    def test_unresolvable_path_identifier_uses_the_same_existence_gate(
        self, api, admin_headers
    ):
        """A bogus path id on an action endpoint is refused the same way.

        PRD.md section 2.7: "**Existence** — path identifiers first, then body
        foreign keys, each reported with its entity-specific not-found code
        where one exists and with `ERR_RESOURCE_NOT_FOUND` otherwise."

        Design: Corner/entities/ent_flat_fk_body_references_validated_before_state_occ_and_business_rules
        """
        self._draft_plant(api)

        refused = api.service_hold_mold(
            UNKNOWN_ID, service_hold_payload("probe"), admin_headers
        )

        assert refused.status_code == 404
        validate_error_is_one_of(
            refused, [ApiErrorId.MOLD_NOT_FOUND, ApiErrorId.RESOURCE_NOT_FOUND]
        )


class TestMoldSupersessionChain:
    """`replaces_mold_id` needs a retired peer of the very same hull model."""

    @staticmethod
    def _two_models_and_three_tools(api, admin_headers):
        set_clock(CLOCK_DEFAULT_UTC, admin_headers)
        model_a = get_success_data(
            api.create_product_model(
                product_model_payload(
                    model_code="PM-CD-SUP-A", size_class="MID", nominal_charge_kg=24.0
                ),
                admin_headers,
            )
        )
        model_b = get_success_data(
            api.create_product_model(
                product_model_payload(
                    model_code="PM-CD-SUP-B", size_class="MID", nominal_charge_kg=24.0
                ),
                admin_headers,
            )
        )
        retired_peer = get_success_data(
            api.create_mold(
                mold_payload(
                    model_a["id"],
                    mold_code="MLD-CD-SUP-OLD",
                    cavity_count=1,
                    nominal_charge_kg=24.0,
                ),
                admin_headers,
            )
        )
        get_success_data(
            api.retire_mold(
                retired_peer["id"], retire_mold_payload("Worn out"), admin_headers
            )
        )
        retired_peer = get_success_data(
            api.get_mold(retired_peer["id"], admin_headers)
        )
        live_peer = get_success_data(
            api.create_mold(
                mold_payload(
                    model_a["id"],
                    mold_code="MLD-CD-SUP-LIVE",
                    cavity_count=1,
                    nominal_charge_kg=24.0,
                ),
                admin_headers,
            )
        )
        other_model_retired = get_success_data(
            api.create_mold(
                mold_payload(
                    model_b["id"],
                    mold_code="MLD-CD-SUP-OTHER",
                    cavity_count=1,
                    nominal_charge_kg=24.0,
                ),
                admin_headers,
            )
        )
        get_success_data(
            api.retire_mold(
                other_model_retired["id"],
                retire_mold_payload("Worn out"),
                admin_headers,
            )
        )
        return model_a, retired_peer, live_peer, other_model_retired

    def test_unresolvable_predecessor_fails_on_existence_not_eligibility(
        self, api, admin_headers
    ):
        """A `replaces_mold_id` that resolves to nothing is a 404.

        PRD.md section 3.1: "The optional `replaces_mold_id` records the
        worn-out tool this one succeeds; when supplied it must resolve
        (`ERR_MOLD_NOT_FOUND`, HTTP 404), must name a *different* tool of the
        *same* `product_model_id`, and that tool's `status` must already be
        `RETIRED` — any of those three failing yields
        `ERR_INVALID_MOLD_REPLACEMENT` (HTTP 422)."

        Design: Corner/entities/ent_flat_self_referential_mold_supersession_requires_a_retired_peer_of_the_same_model
        """
        model_a, _old, _live, _other = self._two_models_and_three_tools(
            api, admin_headers
        )

        refused = api.create_mold(
            mold_payload(
                model_a["id"],
                mold_code="MLD-CD-SUP-X1",
                cavity_count=1,
                nominal_charge_kg=24.0,
                replaces_mold_id=UNKNOWN_ID,
            ),
            admin_headers,
        )

        validate_error(refused, ApiErrorId.MOLD_NOT_FOUND, 404)

    def test_predecessor_that_is_still_available_is_ineligible(
        self, api, admin_headers
    ):
        """An existing tool of the right model that never retired is refused.

        PRD.md section 3.1: "when supplied it must resolve
        (`ERR_MOLD_NOT_FOUND`, HTTP 404), must name a *different* tool of the
        *same* `product_model_id`, and that tool's `status` must already be
        `RETIRED` — any of those three failing yields
        `ERR_INVALID_MOLD_REPLACEMENT` (HTTP 422)."

        PRD.md section 2.8, Mold: "the optional `replaces_mold_id` (default
        null; when present it must resolve or `ERR_MOLD_NOT_FOUND`, must have
        `status` `RETIRED` or `ERR_MOLD_NOT_AVAILABLE`, and must reference a
        tool of the same `product_model_id` — and must not be the tool itself —
        or `ERR_INVALID_MOLD_REPLACEMENT`)."

        The two sentences above name different identifiers for the very same
        failure, so both are accepted here.

        Design: Corner/entities/ent_flat_self_referential_mold_supersession_requires_a_retired_peer_of_the_same_model
        """
        model_a, _old, live, _other = self._two_models_and_three_tools(
            api, admin_headers
        )

        refused = api.create_mold(
            mold_payload(
                model_a["id"],
                mold_code="MLD-CD-SUP-X2",
                cavity_count=1,
                nominal_charge_kg=24.0,
                replaces_mold_id=live["id"],
            ),
            admin_headers,
        )

        assert refused.status_code in (409, 422)
        validate_error_is_one_of(
            refused,
            [
                ApiErrorId.INVALID_MOLD_REPLACEMENT,
                ApiErrorId.MOLD_NOT_AVAILABLE,
            ],
        )

    def test_retired_predecessor_under_another_model_is_ineligible(
        self, api, admin_headers
    ):
        """Cross-reference integrity is model-scoped, not merely state-scoped.

        PRD.md section 3.1: "when supplied it must resolve
        (`ERR_MOLD_NOT_FOUND`, HTTP 404), must name a *different* tool of the
        *same* `product_model_id`, and that tool's `status` must already be
        `RETIRED` — any of those three failing yields
        `ERR_INVALID_MOLD_REPLACEMENT` (HTTP 422)."

        Design: Corner/entities/ent_flat_self_referential_mold_supersession_requires_a_retired_peer_of_the_same_model
        """
        model_a, _old, _live, other = self._two_models_and_three_tools(
            api, admin_headers
        )

        refused = api.create_mold(
            mold_payload(
                model_a["id"],
                mold_code="MLD-CD-SUP-X3",
                cavity_count=1,
                nominal_charge_kg=24.0,
                replaces_mold_id=other["id"],
            ),
            admin_headers,
        )

        validate_error(refused, ApiErrorId.INVALID_MOLD_REPLACEMENT, 422)

    def test_retired_peer_of_the_same_model_is_accepted_and_queryable(
        self, api, admin_headers
    ):
        """The successor is created, and the chain reads in both directions.

        PRD.md section 3.1: "When it is registered, `cycles_since_service`
        starts at 0 and `status` at `AVAILABLE`."

        PRD.md section 3.1: "Tools are listed with optional `product_model_id`,
        `replaces_mold_id`, `status` and `size_class` filters, so the
        replacement chain is traversable in both directions."

        PRD.md section 3.1: "Retiring a tool requires a `retire_reason` and
        requires `status` to be `AVAILABLE` or `MAINTENANCE`; `RETIRED` is
        terminal and makes the tool a legal `replaces_mold_id` target."

        Design: Corner/entities/ent_flat_self_referential_mold_supersession_requires_a_retired_peer_of_the_same_model
        """
        model_a, old, _live, _other = self._two_models_and_three_tools(
            api, admin_headers
        )

        successor = validate_success(
            api.create_mold(
                mold_payload(
                    model_a["id"],
                    mold_code="MLD-CD-SUP-NEW",
                    cavity_count=1,
                    nominal_charge_kg=24.0,
                    replaces_mold_id=old["id"],
                ),
                admin_headers,
            ),
            expected_status=201,
        )

        assert successor["replaces_mold_id"] == old["id"]
        assert successor["status"] == "AVAILABLE"
        assert successor["cycles_since_service"] == 0
        assert successor["version"] == 1

        predecessor = validate_success(api.get_mold(old["id"], admin_headers))
        assert predecessor["status"] == "RETIRED"
        assert predecessor["version"] == old["version"], (
            "being cited as a supersession target must not touch the "
            "predecessor's version"
        )

        rows, meta = validate_paginated(
            api.list_molds({"replaces_mold_id": old["id"]}, admin_headers)
        )
        assert meta["total_count"] == 1
        assert rows[0]["mold_code"] == "MLD-CD-SUP-NEW"


class TestPerFieldImmutability:
    """Immutability here is the absence of a write path, not a rejection."""

    @staticmethod
    def _registered_model(api, admin_headers):
        set_clock(CLOCK_DEFAULT_UTC, admin_headers)
        return get_success_data(
            api.create_product_model(
                product_model_payload(
                    model_code="PM-CD-IMM",
                    size_class="MID",
                    nominal_charge_kg=24.0,
                    warranty_basis="PRO_RATA_AGE",
                    initial_warranty_reserve_cents=500000,
                ),
                admin_headers,
            )
        )

    def test_amending_only_the_limits_succeeds_and_bumps_the_version(
        self, api, admin_headers
    ):
        """The amendable limits are writable and the version advances by one.

        PRD.md section 3.1: "The amendable fields are the process and quality
        limits: `max_color_delta_e`, `max_regrind_pct`,
        `min_melt_index_g10min`, `max_melt_index_g10min`, `nominal_charge_kg`,
        `charge_tolerance_pct`, `min_cooling_minutes`,
        `target_wall_thickness_mm`, `wall_thickness_min_mm`,
        `wall_cv_max_pct`, `impact_test_min_joules`, `gross_cube_m3`,
        `nest_factor`, `unit_weight_kg` and `msrp_cents`."

        PRD.md section 3.1: "Amending them does not re-judge any measurement
        already stored on a hull; the new limits bind subsequent inspections
        only, and the model's `version` advances by 1."

        Design: Corner/entities/ent_immutability_no_write_path_for_system_minted_units_or_structural_model_fields
        """
        model = self._registered_model(api, admin_headers)

        patched = validate_success(
            api.update_product_model(
                model["id"],
                {
                    "max_regrind_pct": 25.0,
                    "target_wall_thickness_mm": 6.5,
                    "msrp_cents": 195000,
                },
                admin_headers,
            )
        )

        assert dec(patched["max_regrind_pct"]) == dec("25.00")
        assert dec(patched["target_wall_thickness_mm"]) == dec("6.50")
        assert patched["msrp_cents"] == 195000
        assert patched["version"] == 2
        assert_instant_equals(
            patched["updated_at"], CLOCK_DEFAULT_UTC, "updated_at"
        )

    def test_structural_identity_survives_an_amendment_untouched(
        self, api, admin_headers
    ):
        """The five structural fields are not accepted inputs at all.

        PRD.md section 3.1: "A model's structural identity — `model_code`,
        `hull_type`, `size_class`, `warranty_basis` and
        `initial_warranty_reserve_cents` — is immutable after creation."

        PRD.md section 2.8: "fields marked as derived are computed by the
        service and are never accepted from a client — supplying one is ignored
        rather than honoured, and the service's own value always wins."

        Design: Corner/entities/ent_immutability_no_write_path_for_system_minted_units_or_structural_model_fields
        """
        model = self._registered_model(api, admin_headers)

        get_success_data(
            api.update_product_model(
                model["id"],
                {
                    "max_regrind_pct": 25.0,
                    "target_wall_thickness_mm": 6.5,
                    "msrp_cents": 195000,
                },
                admin_headers,
            )
        )

        after = validate_success(api.get_product_model(model["id"], admin_headers))
        assert after["model_code"] == "PM-CD-IMM"
        assert after["hull_type"] == model["hull_type"]
        assert after["size_class"] == "MID"
        assert after["warranty_basis"] == "PRO_RATA_AGE"
        assert after["initial_warranty_reserve_cents"] == 500000

    def test_the_warranty_ledger_is_not_reachable_from_the_amendment_path(
        self, api, admin_headers
    ):
        """Only claim approval and voiding move the two ledger buckets.

        PRD.md section 2.10: "A hull model holds a two-bucket ledger in which
        `warranty_reserve_cents` plus `warranty_paid_cents` always equals the
        immutable `initial_warranty_reserve_cents`; approving a claim moves the
        net payout from reserve to paid, and voiding an approval moves the
        identical integer back."

        Design: Corner/entities/ent_immutability_no_write_path_for_system_minted_units_or_structural_model_fields
        """
        model = self._registered_model(api, admin_headers)

        get_success_data(
            api.update_product_model(
                model["id"],
                {"max_regrind_pct": 25.0, "msrp_cents": 195000},
                admin_headers,
            )
        )

        after = validate_success(api.get_product_model(model["id"], admin_headers))
        assert after["warranty_reserve_cents"] == 500000
        assert after["warranty_paid_cents"] == 0
        assert_warranty_reserve_conserved(after)

    def test_no_client_can_mint_a_hull_row(self, api, admin_headers):
        """Hulls exist only once the demould cascade has run.

        PRD.md section 2.8: "**FinishedUnit** is never created directly; it is
        minted by the demould cascade, and it carries two independent state axes
        on one row."

        PRD.md section 3.5: "Because there is no creation endpoint for hulls,
        the filtered hull list is their only discovery channel."

        Design: Corner/entities/ent_immutability_no_write_path_for_system_minted_units_or_structural_model_fields
        """
        model = self._registered_model(api, admin_headers)

        rows, meta = validate_paginated(api.list_finished_units(None, admin_headers))
        assert meta["total_count"] == 0
        assert rows == []

        # PRD.md section 4 lists no POST /finished-units and no
        # PATCH /finished-units/{finished_unit_id}, and declares no status for a
        # route it never names, so only the effect is asserted here: whatever the
        # server answers, no hull row may appear.
        minted = api._request(
            "POST",
            "/finished-units",
            {
                "product_model_id": model["id"],
                "cavity_index": 1,
                "hull_serial": "PM-CD-IMM-01-0001",
            },
            admin_headers,
        )
        assert not 200 <= minted.status_code < 300, (
            "a client-side create must not succeed on a system-minted row; got "
            f"HTTP {minted.status_code}"
        )

        _rows, after = validate_paginated(api.list_finished_units(None, admin_headers))
        assert after["total_count"] == 0
