"""Registry entities: echoed fields, declared defaults and computed blocks."""
import pytest

from test_helpers import (
    ADMIN,
    CONVERTER,
    ENGINEER,
    EXTRUDER,
    NON_EXISTENT_UUID,
    QUALITY,
    ApiErrorId,
    assert_regrind_transaction,
    barrier_grade_payload,
    create_bag_lot_payload,
    create_blend_recipe_payload,
    create_component_payload,
    create_extrusion_line_payload,
    create_film_roll_payload,
    create_resin_grade_payload,
    food_certified_line_payload,
    food_contact_pool_payload,
    get_success_data,
    is_iso8601_timestamp,
    is_valid_uuid,
    non_food_product_payload,
    setup_food_run_gauged,
    setup_pool_with_reincorporation,
    setup_print_job_completed,
    tie_grade_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

# The ten Product fields that carry no default at all.
REQUIRED_PRODUCT_FIELDS = {
    "product_code": "P-MIN-1",
    "customer_code": "CUST-MIN",
    "bag_style": "FLAT",
    "target_gauge_micron": 40.0,
    "layflat_width_mm": 400.0,
    "bag_length_mm": 600.0,
    "min_bottom_seal_n_per_15mm": 18.0,
    "min_strength_index": 25.0,
    "bags_per_case": 250,
    "cases_per_pallet": 30,
}


class TestResinGradeRegistry:
    """A resin grade is pure reference data: every field is supplied and echoed."""

    def test_creation_echoes_every_declared_field(self, api):
        """The barrier grade comes back exactly as it was posted.

        PRD: "A grade is identified by `grade_code` and classified by
        `material_class`, which is either `VIRGIN_RESIN` or
        `ADDITIVE_MASTERBATCH`, and by `polymer_family`".

        Design: Corner/entities/resin_grade_creation_returns_201_with_every_declared_field
        """
        grade = validate_success(
            api.create_resin_grade(barrier_grade_payload(), ADMIN), 201)

        assert grade["grade_code"] == "EV-4004"
        assert grade["material_class"] == "VIRGIN_RESIN"
        assert grade["polymer_family"] == "EVOH"
        assert grade["density_kg_m3"] == pytest.approx(1170.0, abs=0.01)
        assert grade["cost_per_kg"] == pytest.approx(8.90, abs=0.01)
        assert grade["dart_impact_index"] == pytest.approx(12.0, abs=0.01)
        assert grade["haze_index"] == pytest.approx(4.0, abs=0.01)
        assert grade["cof_index"] == pytest.approx(0.35, abs=0.01)
        assert grade["seal_initiation_temp_c"] == pytest.approx(180.0, abs=0.01)
        assert grade["is_barrier"] is True
        assert grade["food_contact_approved"] is True
        assert grade["pcr_content_pct"] == pytest.approx(0.0, abs=0.01)

    def test_creation_mints_the_four_common_fields(self, api):
        """id, created_at, updated_at and version arrive from the server.

        PRD: "`version`, an integer that starts at 1 on creation and increments
        by one on each mutation of that resource."

        Design: Corner/entities/resin_grade_creation_returns_201_with_every_declared_field
        """
        grade = validate_success(
            api.create_resin_grade(barrier_grade_payload(), ADMIN), 201)

        assert is_valid_uuid(grade["id"])
        assert is_iso8601_timestamp(grade["created_at"])
        assert is_iso8601_timestamp(grade["updated_at"])
        assert grade["version"] == 1

    def test_list_reports_the_whole_set_and_flags_the_last_page(self, api):
        """Three grades over pages of two: has_more flips on the second page.

        PRD: "The `meta` object of a list response carries `limit`, `offset`,
        `total_count` and `has_more`."

        Design: Corner/entities/resin_grade_list_paginates_with_total_count_and_has_more
        """
        get_success_data(api.create_resin_grade(create_resin_grade_payload(), ADMIN))
        get_success_data(api.create_resin_grade(barrier_grade_payload(), ADMIN))
        get_success_data(api.create_resin_grade(tie_grade_payload(), ADMIN))

        first, first_meta = validate_paginated(
            api.list_resin_grades(ENGINEER, params={"limit": 2, "offset": 0}))
        assert first_meta["total_count"] == 3
        assert len(first) == 2
        assert first_meta["has_more"] is True

        second, second_meta = validate_paginated(
            api.list_resin_grades(ENGINEER, params={"limit": 2, "offset": 2}))
        assert second_meta["total_count"] == 3
        assert len(second) == 1
        assert second_meta["has_more"] is False

    def test_polymer_family_filter_counts_only_the_filtered_set(self, api):
        """total_count follows the filter, not the whole collection.

        PRD: "Collections also accept optional equality filters drawn from the
        resource's own attributes, and any combination of them may be supplied
        together with the pagination parameters."

        Design: Corner/entities/resin_grade_list_paginates_with_total_count_and_has_more
        """
        get_success_data(api.create_resin_grade(create_resin_grade_payload(), ADMIN))
        get_success_data(api.create_resin_grade(barrier_grade_payload(), ADMIN))
        get_success_data(api.create_resin_grade(tie_grade_payload(), ADMIN))

        rows, meta = validate_paginated(
            api.list_resin_grades(ENGINEER, params={"polymer_family": "EVOH"}))
        assert meta["total_count"] == 1
        assert rows[0]["grade_code"] == "EV-4004"

    def test_negative_limit_is_rejected_on_an_empty_collection(self, api):
        """The pagination shape is screened before anything is looked up.

        PRD: "A `limit` outside the inclusive range 1 through 100, a non-integer
        `limit`, a negative `offset` or a non-integer `offset` is rejected with
        `ERR_INVALID_PAGINATION` (HTTP 400)."

        Design: Corner/entities/negative_limit_on_resin_grade_list_is_rejected
        """
        error = validate_error(
            api.list_resin_grades(ENGINEER, params={"limit": -1, "offset": 0}),
            ApiErrorId.ERR_INVALID_PAGINATION, 400)

        assert error["error_id"] == ApiErrorId.ERR_INVALID_PAGINATION
        assert isinstance(error["message"], str) and error["message"]


class TestExtrusionLineRegistry:
    """A line's stored values survive the round trip; its posture is derived."""

    def test_read_back_returns_the_posted_values_and_an_open_posture(self, api):
        """A freshly registered line is OPEN with all three counters at zero.

        PRD: "A newly registered line starts with `posture` at `OPEN` and all
        three of `incapable_run_count`, `active_hold_count` and
        `revoked_dossier_count` at zero."

        Design: Corner/entities/get_extrusion_line_by_id_returns_the_stored_entity
        """
        created = get_success_data(
            api.create_extrusion_line(food_certified_line_payload(), ADMIN))

        line = validate_success(
            api.get_extrusion_line(created["id"], EXTRUDER), 200)
        assert line["line_code"] == "L-FD"
        assert line["max_layers"] == 5
        assert line["purge_buffer_minutes"] == 60
        assert line["food_contact_certified"] is True
        assert line["posture"] == "OPEN"
        assert line["incapable_run_count"] == 0
        assert line["active_hold_count"] == 0
        assert line["revoked_dossier_count"] == 0

    def test_process_type_outside_its_enum_is_a_request_shape_violation(self, api):
        """EXTRUDED is not a member of the process_type enum.

        PRD: "Request shape — the body parses, every required field is present,
        types and enum members are valid".

        Design: Corner/entities/invalid_process_type_enum_on_extrusion_line_is_rejected
        """
        validate_error(api.create_extrusion_line(
            create_extrusion_line_payload(line_code="L-BAD",
                                          process_type="EXTRUDED"), ADMIN),
            ApiErrorId.ERR_INVALID_REQUEST, 400)

        _rows, meta = validate_paginated(
            api.list_extrusion_lines(ADMIN, params={"process_type": "BLOWN"}))
        assert meta["total_count"] == 0


class TestProductRequiredFieldsAndDefaults:
    """Ten Product fields are mandatory; eleven more materialise from defaults."""

    def test_omitting_bags_per_case_creates_no_product_at_all(self, api):
        """bags_per_case has no default, so its absence fails the shape check.

        PRD: "`bags_per_case` is the bag count of a full case and must be
        positive."

        Design: Corner/entities/create_product_missing_required_bags_per_case_returns_invalid_request
        """
        payload = dict(REQUIRED_PRODUCT_FIELDS,
                       product_code="P-BAD-1", customer_code="CUST-X")
        payload.pop("bags_per_case")

        validate_error(api.create_product(payload, ADMIN),
                       ApiErrorId.ERR_INVALID_REQUEST, 400)

        _rows, meta = validate_paginated(
            api.list_products(ADMIN, params={"customer_code": "CUST-X"}))
        assert meta["total_count"] == 0

    def test_every_omitted_optional_field_takes_its_declared_default(self, api):
        """Eleven defaults are materialised rather than left null.

        PRD: "`gusset_depth_mm` is the side gusset depth, which defaults to 0.0,
        may not be negative".

        Design: Corner/entities/omitted_optional_product_fields_take_their_declared_defaults
        """
        product = validate_success(
            api.create_product(dict(REQUIRED_PRODUCT_FIELDS), ADMIN), 201)

        assert product["food_contact_required"] is False
        assert product["perforation_required"] is False
        assert product["gauge_tolerance_pct"] == pytest.approx(8.0, abs=0.01)
        assert product["gusset_depth_mm"] == pytest.approx(0.0, abs=0.01)
        assert product["max_regrind_pct_food"] == pytest.approx(10.0, abs=0.01)
        assert product["max_regrind_pct_nonfood"] == pytest.approx(35.0, abs=0.01)
        assert product["declared_recycled_content_pct"] == pytest.approx(0.0,
                                                                        abs=0.01)
        assert product["assumed_regrind_pcr_pct"] == pytest.approx(0.0, abs=0.01)
        assert product["min_partial_case_bags"] == 0
        assert product["count_accuracy_tolerance_pct"] == pytest.approx(2.0,
                                                                       abs=0.01)
        assert product["required_layer_count"] == 1


class TestFilmRollDefaultsFromTheProduct:
    """The two optional roll measurements are copied from the product spec."""

    def test_layflat_and_gauge_default_from_the_product_when_omitted(self, api):
        """A roll wound without measurements inherits the design geometry.

        PRD: "optionally a measured `layflat_mm` (defaulting to the product's
        `layflat_width_mm`) and `gauge_micron_avg` (defaulting to the product's
        `target_gauge_micron`)."

        Design: Corner/entities/film_roll_layflat_and_gauge_default_from_the_product_when_omitted
        """
        world = setup_food_run_gauged(api)

        roll = validate_success(api.create_film_roll(
            create_film_roll_payload(world["run"]["id"], 1, 600.0), EXTRUDER), 201)

        assert roll["status"] == "WOUND"
        assert roll["layflat_mm"] == pytest.approx(300.0, abs=0.01)
        assert roll["gauge_micron_avg"] == pytest.approx(50.0, abs=0.01)
        assert roll["actual_recycled_content_pct"] is None


class TestBagLotComputedCountBlock:
    """None of the count-accuracy figures is an input to lot creation."""

    def test_unit_weight_theoretical_count_and_accuracy_are_computed(self, api):
        """576.0 printed kilograms over a 0.012520 kg bag gives 46006 bags.

        PRD: "`bag_count_theoretical` is the print job's `printed_kg` divided by
        `bag_unit_weight_kg`, rounded **down** to a whole number."

        Design: Corner/entities/bag_lot_unit_weight_theoretical_count_and_accuracy_are_computed_not_supplied
        """
        world = setup_print_job_completed(api)

        lot = validate_success(api.create_bag_lot(
            create_bag_lot_payload(world["print_job"]["id"],
                                   world["product"]["id"], 46000), CONVERTER), 201)

        assert lot["status"] == "CONVERTING"
        assert lot["bag_unit_weight_kg"] == pytest.approx(0.012520, abs=0.000001)
        assert lot["bag_count_theoretical"] == 46006
        assert lot["count_accuracy_pct"] == pytest.approx(99.99, abs=0.01)
        assert lot["count_accuracy_conforming"] is True

    def test_a_new_lot_opens_with_every_bag_unpacked_and_untested(self, api):
        """Creation seeds the unpacked count and nothing else.

        PRD: "A conservation invariant holds after every packout and every
        unwind: `bag_count_produced` always equals `bag_count_unpacked` plus
        `packed_bag_count` plus `bag_count_scrapped`." And: "While fewer than
        three such first-pass specimens exist, `seal_provisional_mean_n` is null
        and `seal_provisional_verdict` reads `PENDING`."

        Design: Corner/entities/bag_lot_unit_weight_theoretical_count_and_accuracy_are_computed_not_supplied
        """
        world = setup_print_job_completed(api)

        lot = validate_success(api.create_bag_lot(
            create_bag_lot_payload(world["print_job"]["id"],
                                   world["product"]["id"], 46000), CONVERTER), 201)

        assert lot["bag_count_unpacked"] == 46000
        assert lot["packed_bag_count"] == 0
        assert lot["bag_count_scrapped"] == 0
        assert lot["seal_provisional_verdict"] == "PENDING"


class TestRegrindPoolSystemFields:
    """Pool aggregates are system-sourced and start at zero, not null."""

    def test_system_fields_are_server_minted_on_create(self, api):
        """A brand-new pool reconciles at zero on every aggregate.

        PRD: "`embedded_pcr_pct` is 0.000 when `cumulative_in_kg` is zero, and
        otherwise `cumulative_in_pcr_kg` divided by `cumulative_in_kg`,
        multiplied by one hundred, rounded to three decimals."

        Design: Corner/entities/system_fields_are_server_minted_on_regrind_pool_create
        """
        pool = validate_success(
            api.create_regrind_pool(food_contact_pool_payload(), ADMIN), 201)

        assert pool["version"] == 1
        assert is_valid_uuid(pool["id"])
        assert is_iso8601_timestamp(pool["created_at"])
        assert pool["available_kg"] == pytest.approx(0.000, abs=0.001)
        assert pool["cumulative_in_kg"] == pytest.approx(0.000, abs=0.001)
        assert pool["cumulative_out_kg"] == pytest.approx(0.000, abs=0.001)
        assert pool["cumulative_in_pcr_kg"] == pytest.approx(0.000, abs=0.001)
        assert pool["embedded_pcr_pct"] == pytest.approx(0.000, abs=0.001)
        assert pool["generation_count"] == 0
        assert pool["reincorporation_count"] == 0


class TestRegrindLedgerRowImmutability:
    """A ledger row is the one resource without updated_at and version."""

    def test_the_row_carries_no_version_and_no_updated_at(self, api):
        """A 50.0 kg draw is readable but has no mutable identity.

        PRD: "A regrind transaction is an immutable ledger row: it carries only
        `id` and `created_at`, and both `updated_at` and `version` are absent
        from it entirely."

        Design: Corner/entities/regrind_transaction_is_immutable_and_carries_no_version
        """
        world = setup_pool_with_reincorporation(api, kg=50.0)

        row = validate_success(api.get_regrind_transaction(
            world["out_transaction"]["id"], QUALITY), 200)
        assert_regrind_transaction(row)

        assert "version" not in row
        assert "updated_at" not in row
        assert row["direction"] == "OUT"
        assert row["origin_kind"] == "REINCORPORATION"
        assert row["kg"] == pytest.approx(50.000, abs=0.001)
        assert row["pool_available_kg_after"] == pytest.approx(50.000, abs=0.001)
        assert row["reverses_transaction_id"] is None


class TestFlatTopologyReferences:
    """Path identifiers resolve before body foreign keys, and both are 404s."""

    def test_an_unknown_bag_lot_uuid_reads_as_not_found(self, api):
        """A well-formed UUID matching no row is a 404, not a 400.

        PRD: "Path identifier resolution, evaluated left to right (a 404 naming
        the entity that failed)."

        Design: Corner/entities/get_bag_lot_with_unknown_uuid_returns_not_found
        """
        validate_error(api.get_bag_lot(NON_EXISTENT_UUID, CONVERTER),
                       ApiErrorId.ERR_BAG_LOT_NOT_FOUND, 404)

    def test_a_component_on_an_unknown_recipe_path_is_refused(self, api):
        """The parent recipe is resolved before the body is inspected.

        PRD: "When a path names an identifier, that identifier is resolved
        before anything to its right and before any body field is examined."

        Design: Corner/entities/component_on_unknown_recipe_path_returns_not_found
        """
        grade = get_success_data(
            api.create_resin_grade(create_resin_grade_payload(), ADMIN))

        validate_error(api.add_recipe_component(
            NON_EXISTENT_UUID,
            create_component_payload(resin_grade_id=grade["id"]), ENGINEER),
            ApiErrorId.ERR_BLEND_RECIPE_NOT_FOUND, 404)

    def test_an_unknown_body_resin_grade_leaves_the_recipe_empty(self, api):
        """The recipe path resolves; the body reference does not.

        PRD: "Foreign-key resolution for identifiers carried in the body —
        `product_id`, `resin_grade_id`, `blend_recipe_id`, `line_id`, `pool_id`".

        Design: Corner/entities/body_level_resin_grade_reference_is_validated_against_the_flat_topology
        """
        product = get_success_data(
            api.create_product(non_food_product_payload(), ADMIN))
        recipe = get_success_data(api.create_blend_recipe(
            create_blend_recipe_payload(product["id"], recipe_code="R-NF-0"),
            ENGINEER))

        validate_error(api.add_recipe_component(
            recipe["id"],
            create_component_payload(resin_grade_id=NON_EXISTENT_UUID), ENGINEER),
            ApiErrorId.ERR_RESIN_GRADE_NOT_FOUND, 404)

        stored = get_success_data(api.get_blend_recipe(recipe["id"], ENGINEER))
        assert stored["total_weight_pct"] == pytest.approx(0.000, abs=0.001)
        assert stored["status"] == "DRAFT"
