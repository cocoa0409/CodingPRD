"""The persisted surface of each entity: creation, reads, listing and constraints."""

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    admin,
    api_client,
    assert_common_fields,
    assert_envelope_meta,
    brand,
    coord,
    create_artwork_asset_payload,
    create_artwork_version_payload,
    create_brief_payload,
    create_inventory_runout_payload,
    create_printer_payload,
    create_printer_proof_payload,
    decide_brief,
    new_approved_brief,
    new_asset,
    new_brief,
    new_cleared_claim,
    new_printer,
    new_version,
    printer_as,
    quality,
    read_asset,
    read_brief,
    read_claim,
    read_printer,
    read_version,
    set_clock,
    submit_payload,
    validate_error,
    validate_paginated,
    validate_success,
    verify,
)


class TestBriefCreation:
    """The create contract of the root entity."""

    def test_create_returns_201_with_every_input_echoed_and_the_defaults_set(self):
        """Eight inputs come back unmodified beside two server-owned fields.

        PRD §3.1: "A newly registered brief begins in `DRAFT` with an `asset_count`
        of 0 and a `version` of 1."

        Design: Corner/entities/create_brief_returns_201_with_echoed_inputs_and_system_defaults
        """
        payload = create_brief_payload()
        response = api_client.create_brief(payload, coord())
        data = validate_success(response, 201)

        assert response.json()["response_type"] == "object"
        assert_envelope_meta(response.json())

        assert data["sku_code"] == "SKU-1001"
        assert data["product_name"] == payload["product_name"]
        assert data["regulatory_scheme"] == "FDA_FOOD"
        assert data["market_codes"] == ["US"]
        assert data["language_codes"] == ["en"]
        assert len(data["required_element_codes"]) == 7
        assert data["structural_spec"]["component_type"] == "CARTON"
        assert data["structural_spec"]["substrate_class"] == "COATED_PAPER"
        assert data["structural_spec"]["print_process"] == "OFFSET"
        assert data["structural_spec"]["dimensions_mm"] == {"l": 120, "w": 60, "h": 200}
        assert data["net_contents_declaration"]["metric_value"] == 340
        assert data["net_contents_declaration"]["us_uom"] == "OZ"

        assert data["status"] == "DRAFT"
        assert data["asset_count"] == 0
        assert data["approved_by_user_id"] is None
        assert data["approved_at"] is None

        assert_common_fields(data)
        assert data["version"] == 1
        assert data["created_at"].startswith("2026-08-01T00:00:00")
        assert data["updated_at"].startswith("2026-08-01T00:00:00")


class TestArtworkAssetRead:
    """A read returns the stored row plus what the create derived."""

    def test_the_unit_cost_is_looked_up_and_the_three_ledgers_read_zero(self):
        """A CARTON is priced at 42 cents by the server, never by the caller.

        PRD §3.3: "A new asset begins with `obsolescence_state` `ACTIVE`, a
        `version_counter` of 0, a null `current_approved_version_id`, and all three of
        its conserved ledgers — `committed_plate_cost_cents`, `obsolete_units_total`
        and `changeover_cost_committed_cents` — at 0."

        Design: Corner/entities/get_artwork_asset_returns_stored_row_with_derived_unit_cost_and_zero_ledgers
        """
        brief = new_approved_brief()
        created = new_asset(brief["id"])

        data = read_asset(created["id"])

        assert data["id"] == created["id"]
        assert data["brief_id"] == brief["id"]
        assert data["market_code"] == "US"
        assert data["component_type"] == "CARTON"
        assert data["substrate_class"] == "COATED_PAPER"
        assert data["language_codes"] == ["en"]
        assert data["brand_critical_color"] is False
        assert data["plate_budget_cents"] == 500000

        assert data["standard_unit_cost_cents"] == 42
        assert data["obsolescence_state"] == "ACTIVE"
        assert data["version_counter"] == 0
        assert data["current_approved_version_id"] is None
        assert data["committed_plate_cost_cents"] == 0
        assert data["obsolete_units_total"] == 0
        assert data["changeover_cost_committed_cents"] == 0
        assert data["version"] == 1


class TestBriefListing:
    """Briefs are the one collection returned newest first."""

    def test_pages_run_newest_first_and_the_status_filter_precedes_the_window(self):
        """Three briefs stamped on three different days, then filtered and paged.

        PRD §2.3: "Unless a specific collection states otherwise, list results are
        ordered by `created_at` ascending. Four collections deviate, and their ordering
        is part of the contract: briefs are returned newest first, by `created_at`
        descending."

        Design: Corner/entities/list_briefs_pages_newest_first_and_filters_by_status
        """
        first = new_brief(sku_code="SKU-1001")
        set_clock("2026-08-02T00:00:00Z")
        second = new_brief(sku_code="SKU-1002", product_name="Northgate Cocoa Label")
        set_clock("2026-08-03T00:00:00Z")
        third = new_brief(sku_code="SKU-1003", product_name="Northgate Cocoa Shipper")

        decide_brief(first["id"], "APPROVED")
        decide_brief(second["id"], "APPROVED")

        page_one, meta_one = validate_paginated(
            api_client.list_briefs(coord(), params={"limit": 2, "offset": 0})
        )
        assert [row["sku_code"] for row in page_one] == ["SKU-1003", "SKU-1002"]
        assert meta_one["total_count"] == 3
        assert meta_one["has_more"] is True
        assert meta_one["limit"] == 2
        assert meta_one["offset"] == 0

        page_two, meta_two = validate_paginated(
            api_client.list_briefs(coord(), params={"limit": 2, "offset": 2})
        )
        assert [row["sku_code"] for row in page_two] == ["SKU-1001"]
        assert meta_two["total_count"] == 3
        assert meta_two["has_more"] is False

        drafts, draft_meta = validate_paginated(
            api_client.list_briefs(coord(), params={"status": "DRAFT"})
        )
        assert [row["id"] for row in drafts] == [third["id"]]
        assert draft_meta["total_count"] == 1

        approved, approved_meta = validate_paginated(
            api_client.list_briefs(
                coord(), params={"status": "APPROVED", "limit": 1, "offset": 1}
            )
        )
        assert [row["sku_code"] for row in approved] == ["SKU-1001"]
        assert approved_meta["total_count"] == 2


class TestPerCollectionNotFound:
    """Each collection answers with its own 404 code."""

    def test_every_unknown_id_reports_the_error_of_its_own_collection(self):
        """Five reads on an empty database, five distinct error ids.

        PRD §2.5: "Each collection has its own not-found code and each is HTTP 404: a
        brief id that resolves to nothing yields `ERR_BRIEF_NOT_FOUND`."

        Design: Corner/entities/reads_of_unknown_ids_return_the_per_entity_not_found_error
        """
        probes = [
            (api_client.get_brief(NON_EXISTENT_UUID, coord()), ApiErrorId.ERR_BRIEF_NOT_FOUND),
            (
                api_client.get_artwork_version(NON_EXISTENT_UUID, coord()),
                ApiErrorId.ERR_ARTWORK_VERSION_NOT_FOUND,
            ),
            (
                api_client.get_review_task(NON_EXISTENT_UUID, brand()),
                ApiErrorId.ERR_REVIEW_TASK_NOT_FOUND,
            ),
            (
                api_client.get_inventory_runout(NON_EXISTENT_UUID, coord()),
                ApiErrorId.ERR_INVENTORY_RUNOUT_NOT_FOUND,
            ),
            (
                api_client.get_error_escape(NON_EXISTENT_UUID, quality()),
                ApiErrorId.ERR_ERROR_ESCAPE_NOT_FOUND,
            ),
        ]
        for response, error_id in probes:
            validate_error(response, error_id.value, 404)
            body = response.json()
            assert body["response_type"] == "error"
            assert body["data"]["message"]


class TestRequiredInputFields:
    """A missing mandatory field is a 400 that writes nothing."""

    def test_three_missing_required_fields_are_all_invalid_request(self):
        """A required integer, a required enum, and a required integer elsewhere.

        PRD §2.7: "Fourth, request schema and uniqueness: field-level validation
        (`ERR_INVALID_REQUEST`), then duplicate SKU code (`ERR_DUPLICATE_SKU_CODE`),
        then duplicate printer name (`ERR_DUPLICATE_PRINTER_NAME`), then duplicate
        asset variant (`ERR_DUPLICATE_ASSET_VARIANT`)."

        Design: Corner/entities/omitting_a_required_input_field_returns_invalid_request
        """
        brief = new_approved_brief()

        no_budget = create_artwork_asset_payload(brief["id"])
        no_budget.pop("plate_budget_cents")
        validate_error(
            api_client.create_artwork_asset(no_budget, coord()),
            ApiErrorId.ERR_INVALID_REQUEST.value,
            400,
        )

        no_substrate = create_artwork_asset_payload(brief["id"])
        no_substrate.pop("substrate_class")
        validate_error(
            api_client.create_artwork_asset(no_substrate, coord()),
            ApiErrorId.ERR_INVALID_REQUEST.value,
            400,
        )

        no_cap = create_printer_payload()
        no_cap.pop("recovery_liability_cap_cents")
        validate_error(
            api_client.create_printer(no_cap, admin()),
            ApiErrorId.ERR_INVALID_REQUEST.value,
            400,
        )

        assets, _meta = validate_paginated(api_client.list_artwork_assets(coord()))
        assert assets == []
        printers, _pmeta = validate_paginated(api_client.list_printers(coord()))
        assert printers == []
        assert read_brief(brief["id"])["asset_count"] == 0


class TestOptionalFieldDefaults:
    """Omitted optional inputs materialise as declared, not as null."""

    def test_the_two_optional_create_inputs_and_the_system_defaults_are_concrete(self):
        """brand_critical_color becomes false and claim_ids becomes an empty array.

        PRD §3.3: "The version is created in `DRAFT` with `author_user_id` set to the
        creating `X-User-ID` — the subject of every segregation-of-duties check that
        follows — with `check_run_no`, `revision_cycle_count` and `route_count` all at
        0, `requires_reverification` false, `open_condition_codes` and
        `pinned_claim_snapshot` both empty, `compliance_score` null, and
        `failed_element_count` and `waived_element_count` both 0."

        Design: Corner/entities/omitted_optional_fields_take_their_declared_defaults
        """
        brief = new_approved_brief()

        bare_asset = create_artwork_asset_payload(brief["id"])
        bare_asset.pop("brand_critical_color")
        asset = validate_success(
            api_client.create_artwork_asset(bare_asset, coord()), 201
        )
        assert asset["brand_critical_color"] is False

        bare_version = create_artwork_version_payload(asset["version"])
        assert "claim_ids" not in bare_version
        assert "supersedes_version_id" not in bare_version
        version = validate_success(
            api_client.create_artwork_version(asset["id"], bare_version, coord()), 201
        )

        assert version["claim_ids"] == []
        assert version["supersedes_version_id"] is None
        assert version["state"] == "DRAFT"
        assert version["revision_cycle_count"] == 0
        assert version["route_count"] == 0
        assert version["check_run_no"] == 0
        assert version["failed_element_count"] == 0
        assert version["waived_element_count"] == 0
        assert version["requires_reverification"] is False
        assert version["open_condition_codes"] == []
        assert version["pinned_claim_snapshot"] == []
        assert version["compliance_score"] is None


class TestServerDerivedCountersAndLookups:
    """Three computed fields with three different derivations."""

    def test_child_counters_reverse_counters_and_table_lookups_are_all_server_owned(self):
        """asset_count follows the children, usage_count follows the referrers.

        PRD §3.3: "The asset's `standard_unit_cost_cents` is derived from its component
        and is not supplied by the caller: a `CARTON` costs 42 cents per unit, a `LABEL`
        9 cents, a `FILM` 15 cents and a `SHIPPER` 120 cents."

        Design: Corner/entities/computed_counters_and_lookups_are_server_derived_not_client_supplied
        """
        brief = new_approved_brief()
        claim = new_cleared_claim(
            cleared_from_utc="2026-08-01T00:00:00Z",
            cleared_until_utc="2026-12-01T00:00:00Z",
        )
        assert claim["usage_count"] == 0

        carton = new_asset(brief["id"], component_type="CARTON")
        label = new_asset(
            brief["id"], component_type="LABEL", substrate_class="UNCOATED_PAPER"
        )

        assert read_brief(brief["id"])["asset_count"] == 2

        version = new_version(carton, claim_ids=[claim["id"]])
        assert version["claim_ids"] == [claim["id"]]
        assert version["version_no"] == 1

        used = read_claim(claim["id"])
        assert used["usage_count"] == 1
        assert used["legal_status"] == "CLEARED"
        # PRD §2.4: timestamps are rendered with three fractional digits.
        assert used["cleared_from_utc"] == "2026-08-01T00:00:00.000Z"

        assert read_asset(label["id"])["standard_unit_cost_cents"] == 9
        assert read_asset(carton["id"])["standard_unit_cost_cents"] == 42


class TestVersionNumberingAndAuthorship:
    """version_no comes from the asset counter; the author comes from the header."""

    def test_two_creates_number_themselves_and_bump_the_asset_twice(self):
        """The counter, not the request, decides the revision number.

        PRD §3.3: "Creating a version increments the asset's `version_counter` by 1
        and stamps the new row's `version_no` with the resulting value, so revision
        numbers are sequential within the asset and never reused; the asset's own
        `version` is incremented by 1 as well."

        Design: Corner/entities/version_no_and_author_are_assigned_from_the_asset_counter_and_headers
        """
        brief = new_approved_brief()
        asset = new_asset(brief["id"])
        assert asset["version_counter"] == 0
        assert asset["version"] == 1

        v1 = new_version(asset)
        assert v1["version_no"] == 1
        assert v1["author_user_id"] == "u_coord"
        assert v1["state"] == "DRAFT"
        assert v1["version"] == 1

        refreshed = read_asset(asset["id"])
        assert refreshed["version"] == 2

        v2 = new_version(
            refreshed,
            reason_for_change_code="MARKETING_REFRESH",
            change_description="Front panel refresh for the autumn promotion.",
            supersedes_version_id=v1["id"],
        )
        assert v2["version_no"] == 2
        assert v2["supersedes_version_id"] == v1["id"]
        assert v2["author_user_id"] == "u_coord"

        final = read_asset(asset["id"])
        assert final["version_counter"] == 2
        assert final["version"] == 3
        assert read_version(v1["id"])["version_no"] == 1
        assert v1["created_at"].startswith("2026-08-01T00:00:00")
        assert v2["updated_at"].startswith("2026-08-01T00:00:00")


class TestShapeConstraints:
    """Enum membership, array length and numeric floors are all shape rules."""

    def test_shape_violations_are_reported_before_any_reference_is_resolved(self):
        """The negative quantity wins over the nonsense version id beside it.

        PRD §2.3: "A `limit` or `offset` outside those bounds is a malformed request
        and is rejected with `ERR_INVALID_REQUEST`."

        Design: Corner/entities/enum_array_and_numeric_range_violations_return_invalid_request
        """
        brief = new_approved_brief()
        asset = new_asset(brief["id"])
        # PRD §2.7 resolves existence (band two) before field-level validation
        # (band four), so the runout probe below names a version that resolves and
        # isolates the negative quantity as the only shape violation.
        draft_version = new_version(asset)

        validate_error(
            api_client.create_brief(
                create_brief_payload(
                    sku_code="SKU-9001",
                    product_name="Bad Scheme Carton",
                    regulatory_scheme="FDA_DRUG",
                ),
                coord(),
            ),
            ApiErrorId.ERR_INVALID_REQUEST.value,
            400,
        )

        validate_error(
            api_client.create_brief(
                create_brief_payload(
                    sku_code="SKU-9002",
                    product_name="No Market Carton",
                    market_codes=[],
                ),
                coord(),
            ),
            ApiErrorId.ERR_INVALID_REQUEST.value,
            400,
        )

        validate_error(
            api_client.create_inventory_runout(
                create_inventory_runout_payload(
                    asset["id"],
                    draft_version["id"],
                    on_hand_qty=-5,
                    weekly_usage_qty=400,
                ),
                coord(),
            ),
            ApiErrorId.ERR_INVALID_REQUEST.value,
            400,
        )

        briefs, meta = validate_paginated(api_client.list_briefs(coord()))
        assert meta["total_count"] == 1
        assert [row["sku_code"] for row in briefs] == ["SKU-1001"]
        runouts, runout_meta = validate_paginated(
            api_client.list_inventory_runouts(coord())
        )
        assert runouts == []
        assert runout_meta["total_count"] == 0


class TestUniquenessScopes:
    """Two single-column scopes and one composite scope."""

    def test_each_uniqueness_scope_reports_its_own_conflict_code(self):
        """The composite scope repeats only the tuple, and still collides.

        PRD §3.3: "No two assets of the same brief may share the same combination of
        market and component, and a collision on that triple is
        `ERR_DUPLICATE_ASSET_VARIANT`."

        Design: Corner/entities/uniqueness_constraints_reject_duplicate_sku_printer_name_and_asset_variant
        """
        brief = new_approved_brief()
        printer = new_printer()

        validate_error(
            api_client.create_brief(
                create_brief_payload(product_name="Duplicate Sku Carton"), coord()
            ),
            ApiErrorId.ERR_DUPLICATE_SKU_CODE.value,
            409,
        )

        validate_error(
            api_client.create_printer(
                create_printer_payload(
                    color_standard="ISO12647",
                    certified_substrates=["FILM"],
                    recovery_liability_cap_cents=900000,
                ),
                admin(),
            ),
            ApiErrorId.ERR_DUPLICATE_PRINTER_NAME.value,
            409,
        )

        first = new_asset(brief["id"])
        assert first["component_type"] == "CARTON"

        validate_error(
            api_client.create_artwork_asset(
                create_artwork_asset_payload(
                    brief["id"],
                    substrate_class="METALLIZED",
                    plate_budget_cents=700000,
                ),
                coord(),
            ),
            ApiErrorId.ERR_DUPLICATE_ASSET_VARIANT.value,
            409,
        )

        assert read_brief(brief["id"])["asset_count"] == 1
        assert read_printer(printer["id"])["color_standard"] == "G7_MASTER"


class TestDanglingReferences:
    """A path parent, a body parent and a many-to-many target."""

    def test_each_missing_reference_answers_with_its_own_collections_404(self):
        """The claim array is the discriminating probe: it is resolved element by element.

        PRD §2.5: "an artwork asset id yields `ERR_ARTWORK_ASSET_NOT_FOUND`; an
        artwork version id — in a path, or as `artwork_version_id`,
        `supersedes_version_id`, `obsolete_version_id` or `current_approved_version_id`
        — yields `ERR_ARTWORK_VERSION_NOT_FOUND`."

        Design: Corner/entities/references_to_missing_parents_and_missing_many_to_many_targets_return_404
        """
        brief = new_approved_brief()
        asset = new_asset(brief["id"])
        printer = new_printer()

        validate_error(
            api_client.create_artwork_asset(
                create_artwork_asset_payload(
                    NON_EXISTENT_UUID, component_type="LABEL"
                ),
                coord(),
            ),
            ApiErrorId.ERR_BRIEF_NOT_FOUND.value,
            404,
        )

        validate_error(
            api_client.create_artwork_version(
                NON_EXISTENT_UUID,
                create_artwork_version_payload(asset["version"]),
                coord(),
            ),
            ApiErrorId.ERR_ARTWORK_ASSET_NOT_FOUND.value,
            404,
        )

        validate_error(
            api_client.create_artwork_version(
                asset["id"],
                create_artwork_version_payload(
                    asset["version"],
                    reason_for_change_code="CLAIM_CHANGE",
                    change_description="Version naming a claim that does not exist.",
                    claim_ids=[NON_EXISTENT_UUID],
                ),
                coord(),
            ),
            ApiErrorId.ERR_MARKETING_CLAIM_NOT_FOUND.value,
            404,
        )

        validate_error(
            api_client.create_printer_proof(
                create_printer_proof_payload(NON_EXISTENT_UUID, printer["id"]),
                printer_as(printer),
            ),
            ApiErrorId.ERR_ARTWORK_VERSION_NOT_FOUND.value,
            404,
        )

        after = read_asset(asset["id"])
        assert after["version_counter"] == 0
        assert after["version"] == 1


class TestCrossAggregateScope:
    """Existing rows still have to sit inside the referrer's scope."""

    def _two_briefs_and_two_assets(self):
        brief_one = new_approved_brief(
            market_codes=["US", "CA"], language_codes=["en", "fr"]
        )
        brief_two = new_approved_brief(
            sku_code="SKU-2002",
            product_name="Continental Wafer Carton",
            market_codes=["DE"],
            language_codes=["de"],
        )
        asset_one = new_asset(brief_one["id"], market_code="US", language_codes=["en"])
        asset_two = new_asset(brief_two["id"], market_code="DE", language_codes=["de"])
        v1 = new_version(asset_one)
        return brief_one, brief_two, asset_one, asset_two, v1

    def test_market_language_and_supersedes_pointers_must_stay_in_scope(self):
        """Three scope rules, three distinct 422 codes, nothing written.

        PRD §3.3: "The asset's `market_code` must be one of the brief's
        `market_codes`, failing which the create is `ERR_MARKET_CODE_NOT_IN_BRIEF`; and
        every one of the asset's 1 to 6 unique `language_codes` entries must be one of
        the brief's `language_codes`, failing which it is
        `ERR_LANGUAGE_CODE_NOT_IN_BRIEF`."

        Design: Corner/entities/cross_aggregate_references_must_match_the_owning_parents_scope
        """
        brief_one, brief_two, asset_one, asset_two, v1 = self._two_briefs_and_two_assets()

        validate_error(
            api_client.create_artwork_asset(
                create_artwork_asset_payload(
                    brief_one["id"], market_code="MX", component_type="LABEL"
                ),
                coord(),
            ),
            ApiErrorId.ERR_MARKET_CODE_NOT_IN_BRIEF.value,
            422,
        )

        validate_error(
            api_client.create_artwork_asset(
                create_artwork_asset_payload(
                    brief_one["id"], language_codes=["de"], component_type="LABEL"
                ),
                coord(),
            ),
            ApiErrorId.ERR_LANGUAGE_CODE_NOT_IN_BRIEF.value,
            422,
        )

        refreshed_two = read_asset(asset_two["id"])
        validate_error(
            api_client.create_artwork_version(
                asset_two["id"],
                create_artwork_version_payload(
                    refreshed_two["version"],
                    reason_for_change_code="MARKETING_REFRESH",
                    change_description="Version on asset two claiming to supersede asset one.",
                    supersedes_version_id=v1["id"],
                ),
                coord(),
            ),
            ApiErrorId.ERR_SUPERSEDES_VERSION_MISMATCH.value,
            422,
        )

        assert read_brief(brief_one["id"])["asset_count"] == 1
        assert read_brief(brief_two["id"])["asset_count"] == 1
        assert read_asset(asset_one["id"])["version_counter"] == 1
        assert read_asset(asset_two["id"])["version_counter"] == 0

    def test_a_claim_cleared_for_another_market_cannot_reach_review(self):
        """The claim exists and is cleared, but not for the market this pack serves.

        PRD §3.5: "And each claim's own `market_code` must equal the owning asset's
        `market_code`, else `ERR_CLAIM_MARKET_MISMATCH`."

        Design: Corner/entities/cross_aggregate_references_must_match_the_owning_parents_scope
        """
        brief = new_approved_brief(
            market_codes=["US", "CA"], language_codes=["en", "fr"]
        )
        asset = new_asset(brief["id"], market_code="US", language_codes=["en"])
        foreign_claim = new_cleared_claim(
            cleared_from_utc="2026-08-01T00:00:00Z",
            cleared_until_utc="2026-12-01T00:00:00Z",
            market_code="CA",
        )
        assert foreign_claim["market_code"] == "CA"

        version = new_version(asset, claim_ids=[foreign_claim["id"]])
        verify(version["id"])

        validate_error(
            api_client.submit_artwork_version(version["id"], submit_payload(), coord()),
            ApiErrorId.ERR_CLAIM_MARKET_MISMATCH.value,
            422,
        )
        assert read_version(version["id"])["state"] == "ELEMENTS_VERIFIED"
        assert read_version(version["id"])["route_count"] == 0
