"""What a freshly created row carries, what a read returns, and what is refused."""

from test_helpers import (
    AUDITOR,
    BREEDER,
    COORDINATOR,
    NON_EXISTENT_UUID,
    OFFICER,
    ApiErrorId,
    add_line_item,
    advance_clock,
    assert_common_fields,
    assert_decimal_equals,
    assert_instant_equals,
    create_genetic_test_payload,
    create_propagator,
    create_propagator_agreement_payload,
    create_production_quota_payload,
    create_protection_filing_payload,
    create_royalty_line_item_payload,
    create_royalty_report_payload,
    create_trial_site,
    create_variety,
    create_variety_payload,
    create_variety_trial_payload,
    is_iso8601_timestamp,
    is_valid_uuid,
    licensed_quota,
    read_version,
    sampled_case,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestVarietyCreationContract:
    """A newly registered variety begins in a fully clean state."""

    def test_create_returns_every_declared_field_at_its_clean_value(self, api):
        """The five inputs are echoed and the eleven derived or defaulted fields
        all sit at the values the contract pins for a brand-new candidate.

        PRD 3.1: "A newly registered variety begins in a fully clean state: `lifecycle_state` is `CANDIDATE`, `brand_status` is `BRAND_NONE`, `protection_posture` is `UNPROTECTED`, `protected_jurisdictions` is an empty list, `regional_performance_index` is 0.00, `passed_trial_region_count` is 0, `active_sublicense_count` is 0, `brand_renewal_count` is 0, and `version` is 1."

        Design: Corner/entities/variety_create_returns_every_declared_field_with_defaults
        """
        created = validate_success(
            api.create_variety(
                create_variety_payload(
                    denomination="Aurora Bramble", species="Rubus idaeus",
                    breeder_code="AB", royalty_basis_default="PER_PLANT",
                    base_royalty_cents_per_plant=35, base_royalty_cents_per_acre=1200,
                ),
                BREEDER,
            ),
            201,
        )

        assert created["denomination"] == "Aurora Bramble"
        assert created["species"] == "Rubus idaeus"
        assert created["breeder_code"] == "AB"
        assert created["lifecycle_state"] == "CANDIDATE"
        assert created["brand_status"] == "BRAND_NONE"
        assert created["protection_posture"] == "UNPROTECTED"
        assert created["protected_jurisdictions"] == []
        assert_decimal_equals(created["regional_performance_index"], "0.00",
                              "regional_performance_index")
        assert created["passed_trial_region_count"] == 0
        assert created["active_sublicense_count"] == 0
        assert created["brand_renewal_count"] == 0
        assert created["version"] == 1

    def test_the_nullable_fields_are_null_and_created_at_comes_from_the_clock(self, api):
        """The brand and release fields are all null until something writes them,
        and the audit stamp is taken from the logical clock's startup value rather
        than from wall-clock time.

        PRD 3.1: "`brand_mark_text`, `brand_registry_class`, `brand_registered_on`, `brand_renewal_due_at` and `released_at` are all null."

        Design: Corner/entities/variety_create_returns_every_declared_field_with_defaults
        """
        created = validate_success(
            api.create_variety(create_variety_payload(), BREEDER), 201
        )

        assert created["brand_mark_text"] is None
        assert created["brand_registry_class"] is None
        assert created["brand_registered_on"] is None
        assert created["brand_renewal_due_at"] is None
        assert created["released_at"] is None
        assert_common_fields(created, "Variety")
        assert_instant_equals(created["created_at"], "2026-08-01T00:00:00Z", "created_at")


class TestVarietyRetrievalContract:
    """A read returns the stored row and is never itself a mutation."""

    def test_fetch_returns_the_row_as_written_without_bumping_the_version(self, api):
        """The supplied basis and per-acre rate come back unchanged and the version
        stays at 1, because only a mutation moves it.

        PRD 2.4: "`version` — an integer that starts at 1 when the record is created and increments by exactly 1 on every mutation of that record."

        Design: Corner/entities/variety_get_by_id_returns_the_stored_row
        """
        created = create_variety(
            api, denomination="Aurora Bramble", royalty_basis_default="PER_ACRE",
            breeder_code="AB", base_royalty_cents_per_plant=35,
            base_royalty_cents_per_acre=1200,
        )

        fetched = validate_success(api.get_variety(created["id"], AUDITOR))

        assert fetched["id"] == created["id"]
        assert fetched["royalty_basis_default"] == "PER_ACRE"
        assert fetched["base_royalty_cents_per_acre"] == 1200
        assert fetched["version"] == 1


class TestVarietyListingContract:
    """Paging metadata, equality filters, and the declared paging defaults."""

    def _three_varieties(self, api):
        create_variety(api, denomination="Alpha Bramble", breeder_code="AA",
                       species="Rubus idaeus")
        create_variety(api, denomination="Beta Bramble", breeder_code="BB",
                       species="Rubus idaeus")
        create_variety(api, denomination="Gamma Bramble", breeder_code="GB",
                       species="Vitis vinifera")

    def test_total_count_precedes_paging_and_has_more_tracks_the_remainder(self, api):
        """With three rows, a limit of 2 returns two items but still reports the
        unpaged count of three and flags that more remain; offsetting past them
        clears the flag.

        PRD 2.3: "`total_count` is the number of records matching the filters before pagination is applied, and `has_more` is true when records remain beyond the current page."

        Design: Corner/entities/varieties_list_reports_total_count_and_has_more_under_paging
        """
        self._three_varieties(api)

        first_page, first_meta = validate_paginated(
            api.list_varieties(COORDINATOR, {"limit": 2, "offset": 0})
        )
        assert len(first_page) == 2
        assert first_meta["total_count"] == 3
        assert first_meta["has_more"] is True

        second_page, second_meta = validate_paginated(
            api.list_varieties(COORDINATOR, {"limit": 2, "offset": 2})
        )
        assert len(second_page) == 1
        assert second_meta["total_count"] == 3
        assert second_meta["has_more"] is False

    def test_the_species_filter_narrows_and_the_paging_defaults_apply(self, api):
        """Filtering on species leaves one of the three rows, and a call carrying
        no paging inputs at all reports the declared defaults.

        PRD 2.3: "List endpoints are paginated through two query parameters. `limit` caps the number of records returned; it defaults to 10 when omitted, may not be smaller than 1, and may not be larger than 100. `offset` is the number of records to skip before the page begins and defaults to 0."

        Design: Corner/entities/varieties_list_reports_total_count_and_has_more_under_paging
        """
        self._three_varieties(api)

        filtered, filtered_meta = validate_paginated(
            api.list_varieties(COORDINATOR, {"species": "Vitis vinifera"})
        )
        assert len(filtered) == 1
        assert filtered_meta["total_count"] == 1
        assert filtered_meta["has_more"] is False

        _all_rows, default_meta = validate_paginated(api.list_varieties(COORDINATOR))
        assert default_meta["limit"] == 10
        assert default_meta["offset"] == 0
        assert default_meta["total_count"] == 3


class TestPerEntityNotFoundCodes:
    """Each entity answers an unknown identifier with its own 404 code."""

    def test_unknown_ids_return_the_entity_specific_not_found_code(self, api):
        """A syntactically valid but unknown identifier is resolved before anything
        else happens, and the code names the entity that could not be found rather
        than a generic one.

        PRD 2.8: "Each entity has its own 404 code: `ERR_VARIETY_NOT_FOUND` for a `variety_id`, `ERR_PROTECTION_FILING_NOT_FOUND` for a `filing_id`, `ERR_TRIAL_SITE_NOT_FOUND` for a `trial_site_id`, `ERR_VARIETY_TRIAL_NOT_FOUND` for a `trial_id`, `ERR_PROPAGATOR_NOT_FOUND` for a `propagator_id` or a `suspected_propagator_id`, `ERR_AGREEMENT_NOT_FOUND` for an `agreement_id`, `ERR_QUOTA_NOT_FOUND` for a `quota_id`, `ERR_TAG_ORDER_NOT_FOUND` for a `tag_order_id`, `ERR_ROYALTY_REPORT_NOT_FOUND` for a `report_id` or a `royalty_report_id`, `ERR_LINE_ITEM_NOT_FOUND` for a `line_item_id`, `ERR_SUBLICENSE_GRANT_NOT_FOUND` for a `grant_id`, `ERR_SURVEILLANCE_CASE_NOT_FOUND` for a `case_id`, `ERR_GENETIC_TEST_NOT_FOUND` for a `test_id`, and `ERR_AUDIT_ENGAGEMENT_NOT_FOUND` for an `engagement_id`."

        Design: Corner/entities/protection_filing_get_unknown_id_returns_not_found
        """
        create_variety(api, denomination="Ember Bramble", breeder_code="EB")

        validate_error(
            api.get_protection_filing(NON_EXISTENT_UUID, BREEDER),
            ApiErrorId.ERR_PROTECTION_FILING_NOT_FOUND.value,
            404,
        )
        validate_error(
            api.get_variety_trial(NON_EXISTENT_UUID, BREEDER),
            ApiErrorId.ERR_VARIETY_TRIAL_NOT_FOUND.value,
            404,
        )
        validate_error(
            api.get_genetic_test(NON_EXISTENT_UUID, BREEDER),
            ApiErrorId.ERR_GENETIC_TEST_NOT_FOUND.value,
            404,
        )


class TestRequiredFieldContract:
    """An input field with no declared default may not be omitted."""

    def test_omitting_a_required_input_is_refused_and_writes_nothing(self, api):
        """Each of the five required variety inputs is individually mandatory, and
        the rejection happens before any database lookup, so no row survives.

        PRD 2.8: "Body shape and field-level constraints — `ERR_INVALID_REQUEST` (HTTP 400). The body must parse, must carry every required field, must carry no unknown field, and every value must satisfy its declared constraints: enum values must be declared members, integer quantities must be at least zero (or at least one where the field says so), decimal fields must carry no more precision than declared, and timestamps must be ISO 8601."

        Design: Corner/entities/variety_create_missing_required_field_returns_invalid_request
        """
        for missing in ("base_royalty_cents_per_acre", "denomination", "species",
                        "breeder_code", "base_royalty_cents_per_plant"):
            payload = create_variety_payload(denomination="Halcyon Bramble",
                                             breeder_code="HB")
            payload.pop(missing)
            validate_error(
                api.create_variety(payload, BREEDER),
                ApiErrorId.ERR_INVALID_REQUEST.value,
                400,
            )

        _rows, meta = validate_paginated(api.list_varieties(BREEDER))
        assert meta["total_count"] == 0


class TestDeclaredDefaultsAcrossTheGraph:
    """Omitting an optional input yields exactly the declared default."""

    def test_the_agreement_quota_and_filing_defaults_are_applied(self, api):
        """Four independent defaults land at once: the quality tier, the territory
        class, the protection term and the annuity grace window.

        PRD 3.5: "A `LicensingOfficer` drafts one against a `propagator_id`, declaring the `quality_tier` the propagator has certified to — one of `TIER_A`, `TIER_B` or `TIER_C`, defaulting to `TIER_B` when omitted — the `territory_codes` the propagator may produce and sublicense in, and the term bounds `term_start` and `term_end`."

        Design: Corner/entities/agreement_quota_and_filing_defaults_applied_when_optional_inputs_omitted
        """
        variety = create_variety(api, denomination="Ivory Bramble", breeder_code="IB")
        propagator = create_propagator(api, legal_name="Ivory Lane Nursery",
                                       home_territory_code="US-WA")

        agreement_payload = create_propagator_agreement_payload(
            propagator["id"], territory_codes=["US-WA"]
        )
        agreement_payload.pop("quality_tier", None)
        agreement = validate_success(
            api.create_propagator_agreement(agreement_payload, OFFICER), 201
        )
        validate_success(api.countersign_agreement(agreement["id"], OFFICER))
        assert agreement["quality_tier"] == "TIER_B"

        quota_payload = create_production_quota_payload(
            agreement["id"], variety["id"], season_code="2026S1", basis="PER_PLANT",
            territory_code="US-WA", allocated_units=5000,
        )
        quota_payload.pop("territory_class", None)
        quota = validate_success(api.create_production_quota(quota_payload, OFFICER), 201)
        assert quota["territory_class"] == "DOMESTIC"

    def test_the_filing_term_and_grace_defaults_and_the_variety_basis_default(self, api):
        """A filing created without a term takes 20 years and starts its grace
        window at 90 days before any annuity has been posted, while the variety
        itself falls back to the per-plant basis.

        PRD 3.1: "A new filing starts in `DRAFT` with `annuity_sequence_no` 0, `installments_paid_count` 0, `annuity_days_late` 0, `annuity_surcharge_cents` 0, `annuity_volume_credit_cents` 0, `annuity_total_due_cents` 0, `version` 1, and null values for `filed_on`, `granted_on`, `annuity_due_date` and `lapse_reason`."

        Design: Corner/entities/agreement_quota_and_filing_defaults_applied_when_optional_inputs_omitted
        """
        variety_payload = create_variety_payload(denomination="Ivory Bramble",
                                                 breeder_code="IB")
        variety_payload.pop("royalty_basis_default", None)
        variety = validate_success(api.create_variety(variety_payload, BREEDER), 201)
        assert variety["royalty_basis_default"] == "PER_PLANT"

        filing_payload = create_protection_filing_payload(
            variety["id"], instrument_type="PLANT_PATENT", jurisdiction_code="US",
            annuity_base_cents=200000,
        )
        filing_payload.pop("term_years", None)
        filing = validate_success(
            api.create_protection_filing(filing_payload, BREEDER), 201
        )

        assert filing["term_years"] == 20
        assert filing["annuity_grace_days"] == 90
        assert filing["status"] == "DRAFT"
        assert filing["annuity_sequence_no"] == 0


class TestComputedFieldsAreNotInputs:
    """A payload naming a derived field is rejected as an unknown field."""

    def _countersigned_agreement(self, api):
        variety = create_variety(api, denomination="Juniper Bramble", breeder_code="JB")
        propagator = create_propagator(api, legal_name="Juniper Fields",
                                       home_territory_code="US-WA")
        agreement = validate_success(
            api.create_propagator_agreement(
                create_propagator_agreement_payload(
                    propagator["id"], quality_tier="TIER_B", territory_codes=["US-WA"]
                ),
                OFFICER,
            ),
            201,
        )
        validate_success(api.countersign_agreement(agreement["id"], OFFICER))
        return variety, agreement

    def test_naming_units_available_is_refused_and_a_clean_create_derives_it(self, api):
        """The three tag-inventory fields are derived from the quota's tag orders,
        so a payload trying to set one is an unknown field; without it the create
        succeeds and the available figure equals the allocation.

        PRD 3.6: "`units_available` is `allocated_units` minus `tags_committed_units`."

        Design: Corner/entities/quota_derived_unit_fields_are_computed_and_extra_field_rejected
        """
        variety, agreement = self._countersigned_agreement(api)

        validate_error(
            api.create_production_quota(
                create_production_quota_payload(
                    agreement["id"], variety["id"], season_code="2026S1",
                    basis="PER_PLANT", territory_code="US-WA",
                    territory_class="DOMESTIC", allocated_units=7000,
                    units_available=99999,
                ),
                OFFICER,
            ),
            ApiErrorId.ERR_INVALID_REQUEST.value,
            400,
        )
        _rows, meta = validate_paginated(api.list_production_quotas(OFFICER))
        assert meta["total_count"] == 0

        quota = validate_success(
            api.create_production_quota(
                create_production_quota_payload(
                    agreement["id"], variety["id"], season_code="2026S1",
                    basis="PER_PLANT", territory_code="US-WA",
                    territory_class="DOMESTIC", allocated_units=7000,
                ),
                OFFICER,
            ),
            201,
        )
        assert quota["allocated_units"] == 7000
        assert quota["tags_committed_units"] == 0
        assert quota["units_available"] == 7000
        assert quota["tags_activated_units"] == 0


class TestSystemFieldsAreServerGenerated:
    """State fields and audit stamps are the server's to write."""

    def test_naming_the_lifecycle_state_is_refused_and_the_clock_stamps_created_at(self, api):
        """A caller may not seed a variety directly into RELEASED; without that
        field the create lands in CANDIDATE with the stamp taken from wherever the
        logical clock happens to stand.

        PRD 2.4: "`created_at` — an ISO 8601 UTC timestamp with three fractional digits, stamped when the record is first written and never changed afterwards."

        Design: Corner/entities/variety_system_fields_are_server_generated_and_extra_field_rejected
        """
        advance_clock(api, "2026-08-10T00:00:00Z")

        validate_error(
            api.create_variety(
                create_variety_payload(denomination="Kestrel Bramble",
                                       breeder_code="KB", lifecycle_state="RELEASED"),
                BREEDER,
            ),
            ApiErrorId.ERR_INVALID_REQUEST.value,
            400,
        )

        created = validate_success(
            api.create_variety(
                create_variety_payload(denomination="Kestrel Bramble",
                                       breeder_code="KB"),
                BREEDER,
            ),
            201,
        )
        assert created["lifecycle_state"] == "CANDIDATE"
        assert created["version"] == 1
        assert_instant_equals(created["created_at"], "2026-08-10T00:00:00Z", "created_at")


class TestFieldLevelTypeConstraints:
    """Enum membership and numeric floors are checked before any lookup."""

    def test_an_undeclared_instrument_type_is_refused(self, api):
        """Only the two named instruments exist, so a third value is not a declared
        member and no filing row is written.

        PRD 3.1: "A `BreederAdmin` opens each application against a `variety_id`, choosing the `instrument_type` — either `PLANT_PATENT` or `PLANT_VARIETY_CERTIFICATE` — and naming the `jurisdiction_code` (2 to 4 uppercase characters, for example `US`, `EU` or `CA`)."

        Design: Corner/entities/protection_filing_instrument_type_rejects_undeclared_enum_member
        """
        variety = create_variety(api, denomination="Larkspur Bramble", breeder_code="LB")

        validate_error(
            api.create_protection_filing(
                create_protection_filing_payload(
                    variety["id"], instrument_type="UTILITY_PATENT",
                    jurisdiction_code="US", annuity_base_cents=200000,
                ),
                BREEDER,
            ),
            ApiErrorId.ERR_INVALID_REQUEST.value,
            400,
        )
        _rows, meta = validate_paginated(api.list_protection_filings(BREEDER))
        assert meta["total_count"] == 0

    def test_an_annuity_base_below_the_floor_is_refused(self, api):
        """The base instalment must be at least 1000 cents; 999 fails the field
        constraint while the certificate instrument at 200000 is accepted.

        PRD 3.1: "The application also fixes the money and duration of the future maintenance obligation: `annuity_base_cents`, the base amount of each maintenance instalment, is a whole number of cents of at least 1000, and `term_years`, the protection term measured from grant, is an integer between 5 and 25 that defaults to 20 when omitted."

        Design: Corner/entities/protection_filing_instrument_type_rejects_undeclared_enum_member
        """
        variety = create_variety(api, denomination="Larkspur Bramble", breeder_code="LB")

        validate_error(
            api.create_protection_filing(
                create_protection_filing_payload(
                    variety["id"], instrument_type="PLANT_PATENT",
                    jurisdiction_code="US", annuity_base_cents=999,
                ),
                BREEDER,
            ),
            ApiErrorId.ERR_INVALID_REQUEST.value,
            400,
        )

        filing = validate_success(
            api.create_protection_filing(
                create_protection_filing_payload(
                    variety["id"], instrument_type="PLANT_VARIETY_CERTIFICATE",
                    jurisdiction_code="US", annuity_base_cents=200000,
                ),
                BREEDER,
            ),
            201,
        )
        assert filing["status"] == "DRAFT"


class TestGeneticTestImmutability:
    """The one entity that departs from the common field set."""

    def _case_with_two_tests(self, api):
        variety = create_variety(api, denomination="Marlow Bramble", breeder_code="MB")
        case = sampled_case(api, variety["id"], sampled_unit_count=40,
                            market_survey_ref="MS-2026-014")
        first = validate_success(
            api.create_genetic_test(case["id"], create_genetic_test_payload(0.8100),
                                    AUDITOR),
            201,
        )
        second = validate_success(
            api.create_genetic_test(case["id"], create_genetic_test_payload(0.9300),
                                    AUDITOR),
            201,
        )
        return case, first, second

    def test_a_genetic_test_carries_no_updated_at_and_no_version(self, api):
        """The laboratory record exposes only the identity and creation stamp, and
        its result is derived from the confidence against the inclusive threshold.

        PRD 2.4: "There is exactly one exception. A `GeneticTest` is an immutable laboratory record: it carries `id` and `created_at` only. It has no `updated_at` and no `version`, there is no endpoint that modifies it, and nothing in the system ever mutates one after creation."

        Design: Corner/entities/genetic_test_is_immutable_and_carries_no_version_field
        """
        _case, first, second = self._case_with_two_tests(api)

        fetched = validate_success(api.get_genetic_test(first["id"], AUDITOR))
        assert "updated_at" not in fetched
        assert "version" not in fetched
        assert is_valid_uuid(fetched["id"])
        assert is_iso8601_timestamp(fetched["created_at"])
        assert fetched["result"] == "NO_MATCH"
        assert validate_success(api.get_genetic_test(second["id"], AUDITOR))["result"] == (
            "MATCH"
        )

    def test_a_second_test_appends_a_row_rather_than_amending_the_first(self, api):
        """Two results on one case are two rows; the earlier confidence is
        untouched and the case's high-water mark rises to the later one.

        PRD 3.9: "Recording a test re-derives the case's `max_match_confidence` as the highest `match_confidence` among all of that case's tests, and increments the case's `version` by 1."

        Design: Corner/entities/genetic_test_is_immutable_and_carries_no_version_field
        """
        case, first, second = self._case_with_two_tests(api)
        assert first["id"] != second["id"]

        unchanged = validate_success(api.get_genetic_test(first["id"], AUDITOR))
        assert_decimal_equals(unchanged["match_confidence"], "0.8100", "match_confidence")

        _rows, meta = validate_paginated(
            api.list_genetic_tests(AUDITOR, {"case_id": case["id"]})
        )
        assert meta["total_count"] == 2

        refreshed = validate_success(api.get_surveillance_case(case["id"], AUDITOR))
        assert refreshed["status"] == "TESTING"
        assert_decimal_equals(refreshed["max_match_confidence"], "0.9300",
                              "max_match_confidence")


class TestBodyForeignKeyResolution:
    """Body foreign keys are resolved in the order the operation declares them."""

    def test_an_unknown_trial_site_parent_is_named_in_the_error(self, api):
        """With a real variety and an unknown site, the site is the parent that
        cannot be resolved and no trial row is written.

        PRD 2.8: "Foreign keys supplied in the request **body** are resolved next, using the same per-entity 404 codes, and they are resolved in the order the fields are listed for that operation."

        Design: Corner/entities/variety_trial_create_rejects_unknown_trial_site_parent
        """
        variety = create_variety(api, denomination="Norwood Bramble", breeder_code="NB")
        create_trial_site(api, site_name="Norwood Station", region_code="PNW",
                          plot_capacity=60)

        validate_error(
            api.create_variety_trial(
                create_variety_trial_payload(variety["id"], NON_EXISTENT_UUID,
                                             plot_count=10),
                COORDINATOR,
            ),
            ApiErrorId.ERR_TRIAL_SITE_NOT_FOUND.value,
            404,
        )
        _rows, meta = validate_paginated(api.list_variety_trials(COORDINATOR))
        assert meta["total_count"] == 0

    def test_the_variety_is_resolved_first_when_both_parents_are_unknown(self, api):
        """`variety_id` is declared before `trial_site_id`, so the variety decides
        the error; with both parents real the booking lands in PLANNED with all five
        observations still unrecorded.

        PRD 3.4: "A new trial starts in `PLANNED` with `performance_index` 0.00, `version` 1, and null values for `yield_index`, `vigor_score`, `uniformity_score`, `disease_resistance_score`, `propagation_pass_rate` and `evaluated_at`."

        Design: Corner/entities/variety_trial_create_rejects_unknown_trial_site_parent
        """
        variety = create_variety(api, denomination="Norwood Bramble", breeder_code="NB")
        site = create_trial_site(api, site_name="Norwood Station", region_code="PNW",
                                 plot_capacity=60)

        validate_error(
            api.create_variety_trial(
                create_variety_trial_payload(NON_EXISTENT_UUID, NON_EXISTENT_UUID,
                                             plot_count=10),
                COORDINATOR,
            ),
            ApiErrorId.ERR_VARIETY_NOT_FOUND.value,
            404,
        )

        trial = validate_success(
            api.create_variety_trial(
                create_variety_trial_payload(variety["id"], site["id"], plot_count=10),
                COORDINATOR,
            ),
            201,
        )
        assert trial["status"] == "PLANNED"
        assert_decimal_equals(trial["performance_index"], "0.00", "performance_index")
        assert trial["version"] == 1
        assert trial["yield_index"] is None
        assert trial["propagation_pass_rate"] is None
        assert trial["evaluated_at"] is None
        assert site["id"] == trial["trial_site_id"]


class TestRoyaltyLineItemJunction:
    """The line item is the many-to-many junction, unique on its pair."""

    def _two_quotas_and_two_reports(self, api):
        chain = licensed_quota(
            api, quality_tier="TIER_B", territory_class="DOMESTIC",
            allocated_units=5000, season_code="2026S1", basis="PER_PLANT",
            variety_overrides={"denomination": "Oakhill Bramble", "breeder_code": "OB"},
            territory_codes=["US-WA"], propagator_name="Oakhill Growers",
        )
        second_quota = validate_success(
            api.create_production_quota(
                create_production_quota_payload(
                    chain["agreement_id"], chain["variety_id"], season_code="2026S2",
                    basis="PER_PLANT", territory_class="DOMESTIC",
                    allocated_units=5000,
                ),
                OFFICER,
            ),
            201,
        )
        first_report = validate_success(
            api.create_royalty_report(
                create_royalty_report_payload(chain["agreement_id"]),
                chain["propagator_headers"],
            ),
            201,
        )
        add_line_item(api, chain, first_report["id"], 100)
        add_line_item(api, chain, first_report["id"], 200,
                      quota_id=second_quota["id"])
        second_report = validate_success(
            api.create_royalty_report(
                create_royalty_report_payload(
                    chain["agreement_id"], period_code="2026Q4",
                    period_start="2026-11-01T00:00:00Z",
                    period_end="2027-02-01T00:00:00Z",
                    due_at="2027-02-15T00:00:00Z",
                ),
                chain["propagator_headers"],
            ),
            201,
        )
        add_line_item(api, chain, second_report["id"], 300)
        return chain, first_report, second_report

    def test_the_junction_is_many_to_many_in_both_directions(self, api):
        """One report carries lines for two quotas and one quota is billed on two
        reports, which is what makes the pair — not either side alone — the unit of
        uniqueness.

        PRD 3.7: "Line items are browsable filtered by `report_id` to read one report's lines, by `quota_id` to trace every report that has billed a given quota, or by `overrun_flagged` to sweep up the lines that failed tag verification."

        Design: Corner/entities/royalty_line_item_is_the_report_quota_junction_and_duplicate_pair_rejected
        """
        chain, first_report, _second_report = self._two_quotas_and_two_reports(api)

        _by_report, report_meta = validate_paginated(
            api.list_royalty_line_items(BREEDER, {"report_id": first_report["id"]})
        )
        assert report_meta["total_count"] == 2

        _by_quota, quota_meta = validate_paginated(
            api.list_royalty_line_items(BREEDER, {"quota_id": chain["quota_id"]})
        )
        assert quota_meta["total_count"] == 2

    def test_a_second_line_for_the_same_pair_is_refused(self, api):
        """Reporting the same quota twice on one report would double-count the same
        production, so the duplicate is refused and neither the line collection nor
        the report's version moves.

        PRD 3.7: "At most one line may exist per combination of report and quota, and a second is rejected with `ERR_DUPLICATE_LINE_ITEM_QUOTA` (HTTP 409), since reporting the same quota twice on one report would double-count the same production."

        Design: Corner/entities/royalty_line_item_is_the_report_quota_junction_and_duplicate_pair_rejected
        """
        chain, first_report, _second_report = self._two_quotas_and_two_reports(api)
        before_version = read_version(api, api.get_royalty_report, first_report["id"],
                                      chain["propagator_headers"])

        validate_error(
            api.create_royalty_line_item(
                first_report["id"],
                create_royalty_line_item_payload(chain["quota_id"], 400, before_version),
                chain["propagator_headers"],
            ),
            ApiErrorId.ERR_DUPLICATE_LINE_ITEM_QUOTA.value,
            409,
        )

        _rows, meta = validate_paginated(
            api.list_royalty_line_items(BREEDER, {"report_id": first_report["id"]})
        )
        assert meta["total_count"] == 2
        after = validate_success(api.get_royalty_report(first_report["id"], BREEDER))
        assert after["version"] == before_version


class TestGeneticTestListingFilters:
    """Tests are reached from their case by filtering, not by URL nesting."""

    def test_the_case_result_and_lab_filters_each_narrow_the_collection(self, api):
        """Two tests on one case and one on another are separated by `case_id`, and
        the result and laboratory filters narrow further still.

        PRD 3.9: "Tests are browsable filtered by `case_id` to read a case's full marker-test record, by `result`, or by `lab_code`."

        Design: Corner/entities/genetic_tests_are_reachable_from_their_surveillance_case_by_filter
        """
        variety = create_variety(api, denomination="Pinehurst Bramble", breeder_code="PB")
        case_a = sampled_case(api, variety["id"], sampled_unit_count=25,
                              market_survey_ref="MS-2026-021")
        validate_success(
            api.create_genetic_test(case_a["id"], create_genetic_test_payload(0.8100),
                                    AUDITOR),
            201,
        )
        validate_success(
            api.create_genetic_test(case_a["id"], create_genetic_test_payload(0.9300),
                                    AUDITOR),
            201,
        )
        case_b = sampled_case(api, variety["id"], sampled_unit_count=10,
                              market_survey_ref="MS-2026-022")
        validate_success(
            api.create_genetic_test(
                case_b["id"],
                create_genetic_test_payload(0.4000, lab_code="WESTLAB",
                                            marker_panel="SNP-8"),
                AUDITOR,
            ),
            201,
        )

        rows_a, meta_a = validate_paginated(
            api.list_genetic_tests(BREEDER, {"case_id": case_a["id"]})
        )
        assert meta_a["total_count"] == 2
        assert all(row["case_id"] == case_a["id"] for row in rows_a)

        _matches, match_meta = validate_paginated(
            api.list_genetic_tests(BREEDER, {"case_id": case_a["id"], "result": "MATCH"})
        )
        assert match_meta["total_count"] == 1

        _rows_b, meta_b = validate_paginated(
            api.list_genetic_tests(BREEDER, {"case_id": case_b["id"]})
        )
        assert meta_b["total_count"] == 1

        _by_lab, lab_meta = validate_paginated(
            api.list_genetic_tests(BREEDER, {"lab_code": "WESTLAB"})
        )
        assert lab_meta["total_count"] == 1

        refreshed_b = validate_success(api.get_surveillance_case(case_b["id"], AUDITOR))
        assert_decimal_equals(refreshed_b["max_match_confidence"], "0.4000",
                              "max_match_confidence")
