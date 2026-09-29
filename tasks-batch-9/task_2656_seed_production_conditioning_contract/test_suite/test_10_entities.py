"""Resource shapes, envelopes, defaults and reference-data reads."""

from __future__ import annotations

import pytest

from test_helpers import (
    GOLDEN_FIGURES,
    NON_EXISTENT_UUID,
    TEST_DEFAULTS,
    assert_conditioning_line,
    assert_field_history_record,
    assert_grower,
    assert_harvest_event,
    assert_no_mutable_common_fields,
    assert_seed_lot,
    assert_variety,
    create_conditioning_line_payload,
    create_field_history_record_payload,
    create_grower_payload,
    create_production_contract_payload,
    create_variety_payload,
    get_success_data,
    harvested_lot_state,
    is_iso8601_timestamp,
    is_valid_uuid,
    make_conditioning_manager_headers,
    make_field_history_record,
    make_field_officer_headers,
    make_grower,
    make_production_field,
    make_program_admin_headers,
    make_variety,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestVarietyRegistration:
    def test_registering_a_variety_echoes_every_declared_field(self, api):
        """A complete variety payload returns 201 and reads back exactly as supplied.

        PRD: "Registering a variety records its `crop_kind` — one of `WHEAT`, `TRITICALE`,
        `SOYBEAN`, `SUNFLOWER`, `ALFALFA` or `CANOLA` — together with its `variety_name` and the
        highest class it may ever be certified as, `max_seed_class`, which is one of `FOUNDATION`,
        `REGISTERED` or `CERTIFIED`."

        PRD: "An operation that brings a new resource into existence returns 201 Created; every
        other successful operation — including every state transition, every read, the computed
        eligibility assessment (which persists no assessment resource of its own), the equipment
        cleanout certification, and the administrative clock capability — returns 200 OK."

        Design: Corner/entities/variety_creation_returns_declared_fields
        """
        variety = validate_success(
            api.create_variety(create_variety_payload(), make_program_admin_headers()), 201
        )
        assert_variety(variety)
        assert is_valid_uuid(variety["id"])

        assert variety["crop_kind"] == TEST_DEFAULTS["CROP_KIND"]
        assert variety["variety_name"] == TEST_DEFAULTS["VARIETY_NAME"]
        assert variety["max_seed_class"] == TEST_DEFAULTS["MAX_SEED_CLASS"]
        assert variety["isolation_min_m"] == pytest.approx(TEST_DEFAULTS["ISOLATION_MIN_M"], abs=0.01)
        assert variety["restricted_prior_crop_kinds"] == TEST_DEFAULTS["RESTRICTED_PRIOR_CROP_KINDS"]
        assert variety["restricted_prior_crop_years"] == TEST_DEFAULTS["RESTRICTED_PRIOR_CROP_YEARS"]
        assert variety["germination_min_pct"] == pytest.approx(TEST_DEFAULTS["GERMINATION_MIN_PCT"], abs=0.01)
        assert variety["purity_min_pct"] == pytest.approx(TEST_DEFAULTS["PURITY_MIN_PCT"], abs=0.01)
        assert variety["max_off_type_per_10000"] == pytest.approx(TEST_DEFAULTS["MAX_OFF_TYPE_PER_10000"], abs=0.01)
        assert variety["max_restricted_weed_per_10000"] == pytest.approx(
            TEST_DEFAULTS["MAX_RESTRICTED_WEED_PER_10000"], abs=0.01
        )
        assert variety["max_disease_incidence_pct"] == pytest.approx(
            TEST_DEFAULTS["MAX_DISEASE_INCIDENCE_PCT"], abs=0.01
        )
        assert variety["max_rogueing_rounds"] == TEST_DEFAULTS["MAX_ROGUEING_ROUNDS"]
        assert variety["estimated_conditioning_shrink_pct"] == pytest.approx(
            TEST_DEFAULTS["ESTIMATED_CONDITIONING_SHRINK_PCT"], abs=0.01
        )
        assert variety["germ_validity_days"] == TEST_DEFAULTS["GERM_VALIDITY_DAYS"]
        assert variety["max_carryover_generations"] == TEST_DEFAULTS["MAX_CARRYOVER_GENERATIONS"]
        assert variety["treatment_required"] is False


class TestGrowerRetrieval:
    def test_a_registered_grower_reads_back_with_system_initialised_standing(self, api):
        """The read returns the captured contact data plus the platform's own standing fields.

        PRD: "Registering a contract grower captures `grower_name`, `region_code` and
        `contact_email`."

        PRD: "Two further properties are computed by the platform and never supplied by the caller:
        `status`, the grower's compliance standing, which is one of `GOOD_STANDING`, `WATCH` or
        `SUSPENDED` and starts at `GOOD_STANDING`; and `compliance_flag_count`, which counts the
        number of times a contract of this grower has entered a rogueing-required or rejected
        condition and starts at 0."

        Design: Corner/entities/grower_retrieval_returns_stored_data
        """
        created = make_grower(api)

        stored = validate_success(api.get_grower(created["id"], make_field_officer_headers()), 200)
        assert_grower(stored)
        assert stored["id"] == created["id"]
        assert stored["grower_name"] == TEST_DEFAULTS["GROWER_NAME"]
        assert stored["region_code"] == TEST_DEFAULTS["REGION_CODE"]
        assert stored["contact_email"] == TEST_DEFAULTS["CONTACT_EMAIL"]
        assert stored["status"] == "GOOD_STANDING"
        assert stored["compliance_flag_count"] == 0
        assert stored["version"] == 1


class TestGrowerListing:
    def test_two_growers_page_one_at_a_time_with_a_complete_meta_block(self, api):
        """A one-row page reports the unpaginated total and whether more rows remain.

        PRD: "The `meta` block of a list response carries `limit`, `offset`, `total_count` and
        `has_more`, where `total_count` is the number of records matching the filters before
        pagination is applied and `has_more` indicates whether any matching records remain beyond
        the current page."

        PRD: "List responses order records by `created_at` ascending."

        Design: Corner/entities/growers_listing_returns_pagination_envelope
        """
        first = make_grower(api)
        second = make_grower(
            api,
            grower_name=TEST_DEFAULTS["SECOND_GROWER_NAME"],
            region_code=TEST_DEFAULTS["SECOND_REGION_CODE"],
            contact_email=TEST_DEFAULTS["SECOND_CONTACT_EMAIL"],
        )

        page_one, meta_one = validate_paginated(
            api.list_growers(make_program_admin_headers(), {"limit": 1, "offset": 0})
        )
        assert len(page_one) == 1
        assert meta_one["total_count"] == 2
        assert meta_one["has_more"] is True
        assert meta_one["limit"] == 1
        assert meta_one["offset"] == 0

        page_two, meta_two = validate_paginated(
            api.list_growers(make_program_admin_headers(), {"limit": 1, "offset": 1})
        )
        assert len(page_two) == 1
        assert meta_two["total_count"] == 2
        assert meta_two["has_more"] is False
        assert meta_two["offset"] == 1

        assert [page_one[0]["id"], page_two[0]["id"]] == [first["id"], second["id"]]

    def test_the_region_filter_narrows_the_total_count(self, api):
        """Filtering by region selects one grower and the total reflects the filter, not the table.

        PRD: "Collections additionally accept optional equality filters, which combine
        conjunctively with each other and with pagination."

        PRD: "Growers may be filtered by `status` and `region_code`."

        Design: Corner/entities/growers_listing_returns_pagination_envelope
        """
        make_grower(api)
        second = make_grower(
            api,
            grower_name=TEST_DEFAULTS["SECOND_GROWER_NAME"],
            region_code=TEST_DEFAULTS["SECOND_REGION_CODE"],
            contact_email=TEST_DEFAULTS["SECOND_CONTACT_EMAIL"],
        )

        growers, meta = validate_paginated(
            api.list_growers(
                make_program_admin_headers(),
                {"region_code": TEST_DEFAULTS["SECOND_REGION_CODE"], "limit": 10, "offset": 0},
            )
        )
        assert meta["total_count"] == 1
        assert meta["has_more"] is False
        assert len(growers) == 1
        assert growers[0]["id"] == second["id"]
        assert growers[0]["region_code"] == TEST_DEFAULTS["SECOND_REGION_CODE"]


class TestGrowerNotFound:
    def test_an_unknown_grower_id_is_a_404_rather_than_an_empty_success(self, api):
        """A well-formed but unknown identifier resolves to the grower's own not-found error.

        PRD: "4. Existence of every path-templated resource, left to right — the fifteen not-found
        errors of §2.6."

        PRD: "All fifteen carry HTTP 404."

        Design: Corner/entities/grower_get_with_unknown_id_not_found
        """
        existing = make_grower(api)

        response = api.get_grower(NON_EXISTENT_UUID, make_program_admin_headers())
        validate_error(response, "ERR_GROWER_NOT_FOUND", 404)

        still_there = validate_success(
            api.get_grower(existing["id"], make_program_admin_headers()), 200
        )
        assert still_there["id"] == existing["id"]
        assert still_there["status"] == "GOOD_STANDING"


def _contract_parents(api):
    """A variety, a grower and one 320-acre field carrying a single history record."""
    variety = make_variety(api)
    grower = make_grower(api)
    field = make_production_field(api, grower["id"])
    make_field_history_record(api, field["id"])
    return variety, grower, field


class TestContractDraftRequiredFields:
    def test_a_draft_without_a_base_price_is_refused_and_writes_nothing(self, api):
        """Omitting a required commercial term is a request-shape failure, not a stored draft.

        PRD: "3. Request shape: every required input field present, JSON types correct, enum
        members valid, single-field numeric ranges honoured, and pagination bounds respected —
        `ERR_INVALID_REQUEST`."

        Design: Corner/entities/contract_create_missing_base_price_rejected
        """
        variety, grower, field = _contract_parents(api)
        payload = create_production_contract_payload(grower["id"], variety["id"], field["id"])
        del payload["base_price_per_unit_cents"]

        response = api.create_production_contract(payload, make_program_admin_headers())
        validate_error(response, "ERR_INVALID_REQUEST", 400)

        _contracts, meta = validate_paginated(
            api.list_production_contracts(make_program_admin_headers())
        )
        assert meta["total_count"] == 0


class TestContractSeedClassEnum:
    def test_an_undeclared_seed_class_is_refused_before_the_acreage_rule(self, api):
        """`GOLD_STANDARD` is not a contract class, so the shape rule speaks first.

        PRD: "A `ProgramAdmin` drafts a contract by binding three independent parents together in
        one payload — the `grower_id` of the contracted grower, the `variety_id` of the variety
        under production, and the `production_field_id` of the field dedicated to this contract —
        together with the `season_year`, which must fall between 2000 and 2100 inclusive, and the
        `seed_class` being produced, which is one of `FOUNDATION`, `REGISTERED`, `CERTIFIED` or
        `COMMERCIAL_INCREASE`."

        PRD: "3. Request shape: every required input field present, JSON types correct, enum
        members valid, single-field numeric ranges honoured, and pagination bounds respected —
        `ERR_INVALID_REQUEST`."

        Design: Corner/entities/contract_invalid_seed_class_enum_rejected
        """
        variety, grower, field = _contract_parents(api)

        response = api.create_production_contract(
            create_production_contract_payload(
                grower["id"],
                variety["id"],
                field["id"],
                seed_class="GOLD_STANDARD",
                contracted_acres=900.0,
            ),
            make_program_admin_headers(),
        )
        error = validate_error(response, "ERR_INVALID_REQUEST", 400)
        assert error["error_id"] != "ERR_CONTRACTED_ACRES_EXCEED_FIELD"

        _contracts, meta = validate_paginated(
            api.list_production_contracts(make_program_admin_headers())
        )
        assert meta["total_count"] == 0


class TestConditioningLineDefaults:
    def test_an_omitted_status_defaults_to_available_over_a_blank_run_history(self, api):
        """A freshly registered line is available and has no completed run behind it.

        PRD: "An optional `status` of `AVAILABLE` or `OUT_OF_SERVICE` defaults to `AVAILABLE`."

        PRD: "Two computed properties track the line's history: `last_cleanout_variety_id`, the
        variety of the most recently completed run on the line, and `last_run_end_utc`, that run's
        window end."

        PRD: "Both are null before the line's first completion."

        Design: Corner/entities/conditioning_line_status_default_available
        """
        payload = create_conditioning_line_payload()
        assert "status" not in payload

        line = validate_success(
            api.create_conditioning_line(payload, make_conditioning_manager_headers()), 201
        )
        assert_conditioning_line(line)
        assert line["status"] == "AVAILABLE"
        assert line["line_code"] == TEST_DEFAULTS["LINE_CODE"]
        assert line["cleanout_minutes_required"] == TEST_DEFAULTS["LINE_CLEANOUT_MINUTES_REQUIRED"]
        assert line["capacity_kg_per_hour"] == pytest.approx(
            TEST_DEFAULTS["CAPACITY_KG_PER_HOUR"], abs=0.01
        )
        assert line["last_cleanout_variety_id"] is None
        assert line["last_run_end_utc"] is None
        assert line["version"] == 1


class TestSeedLotProvisionalUnits:
    def test_the_provisional_figure_is_computed_and_a_supplied_one_carries_no_weight(self, api):
        """The lot's provisional units come from the formula, not from the harvest payload.

        PRD: "Next, `provisional_clean_kg` is the gross field weight reduced by the moisture
        dockage percentage and then reduced again by the variety's book
        `estimated_conditioning_shrink_pct`, each reduction applied as a proportional factor of one
        minus the percentage divided by one hundred, with the result rounded half-up to three
        decimal places."

        PRD: "Finally, `provisional_clean_units` is that provisional clean mass divided by the
        clean seed unit of 25.0 kilograms, rounded half-up to two decimal places."

        Design: Corner/entities/seed_lot_provisional_units_computed_input_ignored
        """
        state = harvested_lot_state(api, harvest_overrides={"provisional_clean_units": 9999.99})

        event = state["harvest_event"]
        assert_harvest_event(event)
        assert event["moisture_dockage_pct"] == pytest.approx(GOLDEN_FIGURES["MOISTURE_DOCKAGE_PCT"], abs=0.01)
        assert event["provisional_clean_kg"] == pytest.approx(GOLDEN_FIGURES["PROVISIONAL_CLEAN_KG"], abs=0.001)
        assert event["provisional_clean_units"] == pytest.approx(
            GOLDEN_FIGURES["PROVISIONAL_CLEAN_UNITS"], abs=0.01
        )

        lot = state["seed_lot"]
        assert_seed_lot(lot)
        assert lot["provisional_clean_units"] == pytest.approx(
            GOLDEN_FIGURES["PROVISIONAL_CLEAN_UNITS"], abs=0.01
        )
        assert lot["intake_moisture_pct"] == pytest.approx(TEST_DEFAULTS["MOISTURE_PCT"], abs=0.01)
        assert lot["current_kg"] == pytest.approx(TEST_DEFAULTS["GROSS_WEIGHT_KG"], abs=0.001)
        assert lot["cumulative_shrink_kg"] == pytest.approx(0.0, abs=0.001)
        assert lot["dockage_pct"] == pytest.approx(0.00, abs=0.01)

        assert state["contract"]["provisional_clean_units_total"] == pytest.approx(
            GOLDEN_FIGURES["PROVISIONAL_CLEAN_UNITS"], abs=0.01
        )


class TestGrowerSystemFields:
    def test_the_server_mints_identity_and_standing_whatever_the_body_claims(self, api):
        """Identity, version and standing are the platform's to write, not the caller's.

        PRD: "Every resource the platform persists is addressed by an `id` that the server mints as
        a UUID."

        PRD: "The identifier carries no type prefix and is never supplied by the client."

        PRD: "Two further properties are computed by the platform and never supplied by the caller:
        `status`, the grower's compliance standing, which is one of `GOOD_STANDING`, `WATCH` or
        `SUSPENDED` and starts at `GOOD_STANDING`; and `compliance_flag_count`, which counts the
        number of times a contract of this grower has entered a rogueing-required or rejected
        condition and starts at 0."

        Design: Corner/entities/grower_system_fields_generated_input_ignored
        """
        grower = validate_success(
            api.create_grower(
                create_grower_payload(
                    id=NON_EXISTENT_UUID,
                    version=99,
                    status="SUSPENDED",
                    compliance_flag_count=7,
                ),
                make_program_admin_headers(),
            ),
            201,
        )
        assert_grower(grower)
        assert grower["id"] != NON_EXISTENT_UUID
        assert is_valid_uuid(grower["id"])
        assert grower["version"] == 1
        assert grower["status"] == "GOOD_STANDING"
        assert grower["compliance_flag_count"] == 0
        assert is_iso8601_timestamp(grower["created_at"])
        assert is_iso8601_timestamp(grower["updated_at"])

        stored = get_success_data(api.get_grower(grower["id"], make_program_admin_headers()))
        assert stored["status"] == "GOOD_STANDING"
        assert stored["compliance_flag_count"] == 0
        assert stored["version"] == 1


class TestImmutableReferenceRecords:
    def test_a_variety_read_carries_no_version_and_no_updated_at(self, api):
        """The immutable reference row has nothing to concurrency-check.

        PRD: "Four resource kinds are deliberate exceptions because they are immutable or
        append-only records rather than living state."

        PRD: "A `Variety`, a `TreatmentProduct`, a `FieldHistoryRecord` and a `HarvestEvent` each
        carry only `id` and `created_at`."

        PRD: "Both `updated_at` and `version` are absent from those four resources entirely — they
        are not present-and-null, they are not part of the response shape at all."

        Design: Corner/entities/variety_immutable_has_no_version_field
        """
        created = make_variety(api)

        variety = validate_success(api.get_variety(created["id"], make_program_admin_headers()), 200)
        assert_variety(variety)
        assert_no_mutable_common_fields(variety)
        assert variety["id"] == created["id"]
        assert is_iso8601_timestamp(variety["created_at"])

    def test_an_appended_history_record_carries_no_version_either(self, api):
        """The append-only cropping record is shaped the same way as the variety.

        PRD: "A `Variety`, a `TreatmentProduct`, a `FieldHistoryRecord` and a `HarvestEvent` each
        carry only `id` and `created_at`."

        PRD: "Both `updated_at` and `version` are absent from those four resources entirely — they
        are not present-and-null, they are not part of the response shape at all."

        Design: Corner/entities/variety_immutable_has_no_version_field
        """
        grower = make_grower(api)
        field = make_production_field(api, grower["id"])
        make_field_history_record(api, field["id"])

        records, meta = validate_paginated(
            api.list_field_history_records(
                make_field_officer_headers(),
                {"production_field_id": field["id"], "limit": 10, "offset": 0},
            )
        )
        assert meta["total_count"] == 1
        assert len(records) == 1
        assert_field_history_record(records[0])
        assert_no_mutable_common_fields(records[0])
        assert records[0]["crop_kind"] == TEST_DEFAULTS["HISTORY_CROP_KIND"]
        assert records[0]["crop_year"] == TEST_DEFAULTS["HISTORY_CROP_YEAR"]


class TestFieldHistoryUnderUnknownField:
    def test_appending_history_to_an_unknown_field_is_a_404_that_writes_nothing(self, api):
        """The path parameter is resolved before the body is considered at all.

        PRD: "For a request addressed at a path that names more than one resource, the leftmost path
        parameter is resolved first and, if it does not resolve to an existing row, the request
        fails immediately with that resource's own not-found error before any deeper parameter is
        examined."

        PRD: "All fifteen carry HTTP 404."

        Design: Corner/entities/field_history_create_on_unknown_field_not_found
        """
        grower = make_grower(api)
        field = make_production_field(api, grower["id"])
        make_field_history_record(api, field["id"])

        response = api.create_field_history_record(
            NON_EXISTENT_UUID,
            create_field_history_record_payload(crop_kind="WHEAT", crop_year=2025),
            make_field_officer_headers(),
        )
        validate_error(response, "ERR_PRODUCTION_FIELD_NOT_FOUND", 404)

        records, meta = validate_paginated(
            api.list_field_history_records(
                make_field_officer_headers(), {"production_field_id": field["id"]}
            )
        )
        assert meta["total_count"] == 1
        assert records[0]["crop_kind"] == TEST_DEFAULTS["HISTORY_CROP_KIND"]
        assert records[0]["crop_year"] == TEST_DEFAULTS["HISTORY_CROP_YEAR"]

        stored_field = get_success_data(
            api.get_production_field(field["id"], make_field_officer_headers())
        )
        assert stored_field["history_record_count"] == 1


class TestSeedLotGraph:
    def test_the_lot_is_reachable_from_either_of_its_two_parents(self, api):
        """Contract and variety are independent parents of the same lot node.

        PRD: "Seed lots may be filtered by `variety_id`, `production_contract_id`,
        `parent_seed_lot_id`, `conditioning_status`, `certification_status` and `season_year`."

        PRD: "Harvest events may be filtered by `production_contract_id`, `harvest_equipment_id`
        and `seed_lot_id`."

        PRD: "The harvest event records the identifier of the lot it minted as its own
        `seed_lot_id`."

        Design: Corner/entities/seed_lot_graph_links_resolve_from_both_parents
        """
        state = harvested_lot_state(api)
        lot_id = state["seed_lot"]["id"]
        headers = make_conditioning_manager_headers()

        by_contract, contract_meta = validate_paginated(
            api.list_seed_lots(
                headers, {"production_contract_id": state["contract"]["id"], "limit": 10, "offset": 0}
            )
        )
        by_variety, variety_meta = validate_paginated(
            api.list_seed_lots(headers, {"variety_id": state["variety"]["id"], "limit": 10, "offset": 0})
        )
        assert contract_meta["total_count"] == 1
        assert variety_meta["total_count"] == 1
        assert by_contract[0]["id"] == lot_id
        assert by_variety[0]["id"] == lot_id

        lot = by_contract[0]
        assert lot["production_contract_id"] == state["contract"]["id"]
        assert lot["variety_id"] == state["variety"]["id"]
        assert lot["season_year"] == TEST_DEFAULTS["SEASON_YEAR"]

        events, event_meta = validate_paginated(
            api.list_harvest_events(headers, {"seed_lot_id": lot_id, "limit": 10, "offset": 0})
        )
        assert event_meta["total_count"] == 1
        assert events[0]["id"] == state["harvest_event"]["id"]
        assert events[0]["seed_lot_id"] == lot_id
